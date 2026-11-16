"""用完全合成的数据验证增量引擎的业务结果与时间边界。"""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from dake.config import Settings
from dake.domain.models import Candidate, Message, Window, parse_time, windows
from dake.services.processing import IncrementalService
from fakes import FakeProvider, FakeSource, MemoryStore


UID = "engine-fixture-customer"


def message(mid, at, *, uid=UID, group="synthetic-group-a"):
    return Message(uid=uid, message_id=mid, sent_at=parse_time(at),
                   content=f"合成消息 {mid}，仅用于验证处理流程。", conversation_id=group)


def candidate(mid, *, topic="synthetic-product-a:issue-a", summary=None, event_type="排障", **kwargs):
    return Candidate(type=event_type, topic_key=topic,
                     summary=summary or f"合成事件进展 {mid}", evidence_ids=[mid], **kwargs)


def day_window(day):
    start = parse_time(f"2026-11-{day:02d}")
    return Window(start, start + timedelta(days=1))


def build(tmp_path, messages=(), mapping=None, **config):
    settings = replace(Settings(), data_dir=tmp_path, uid=UID, **config)
    source = FakeSource(messages)
    provider = FakeProvider(mapping)
    store = MemoryStore()
    service = IncrementalService(store, source, provider, settings)
    return service, store, source, provider


def test_five_day_replay_updates_one_event_across_groups_and_silent_days(tmp_path):
    messages = [message("1", "2026-11-08 09:00:00"),
                message("2", "2026-11-11 10:00:00", group="synthetic-group-b"),
                message("3", "2026-11-12 11:00:00")]
    service, store, _, _ = build(tmp_path, messages, {m.message_id: candidate(m.message_id) for m in messages})
    results = [service.run_window(UID, window) for window in windows(
        service.settings.start, service.settings.end, timedelta(days=1))]

    assert len(results) == 5
    assert [len(result.created) for result in results] == [1, 0, 0, 0, 0]
    assert [len(result.updated) for result in results] == [0, 0, 0, 1, 1]
    event_id = results[0].created[0]
    assert results[3].updated == results[4].updated == [event_id]
    events = store.list_events(UID, service.stream)
    assert len(events) == 1
    event = events[0]
    assert event.created_on == day_window(8).start
    assert event.start_time == messages[0].sent_at
    assert event.end_time == messages[-1].sent_at
    assert [e["message_id"] for e in event.evidence] == ["1", "2", "3"]
    assert [revision["message_ids"] for revision in event.updated_by] == [["1"], ["2"], ["3"]]
    assert event.summary == candidate("3").summary
    assert event.status == event.severity == "未知"


def test_same_type_different_subjects_remain_separate(tmp_path):
    messages = [message("1", "2026-11-08 09:00:00"), message("2", "2026-11-08 09:05:00")]
    service, store, _, _ = build(tmp_path, messages,
                                {"1": candidate("1", topic="product-a:error-a"),
                                 "2": candidate("2", topic="product-a:error-b")})
    result = service.run_window(UID, day_window(8))
    assert len(result.created) == 2
    assert len(store.list_events(UID, service.stream)) == 2


def test_repeated_window_adds_no_events_evidence_or_history(tmp_path):
    item = message("1", "2026-11-08 09:00:00")
    service, store, _, provider = build(tmp_path, [item], {"1": candidate("1")})
    service.run_window(UID, day_window(8))
    before = deepcopy(store.events)
    repeated = service.run_window(UID, day_window(8))
    assert (repeated.created, repeated.updated, repeated.processed, repeated.ingested) == ([], [], 0, 0)
    assert store.events == before
    assert len(provider.calls) == 1


def test_quarter_hour_filters_future_messages_before_storage_and_provider(tmp_path):
    messages = [message("1", "2026-11-08 00:04:00"),
                message("2", "2026-11-08 00:15:00"),
                message("3", "2026-11-08 01:00:00")]
    service, store, _, provider = build(tmp_path, list(reversed(messages)),
                                      {m.message_id: candidate(m.message_id) for m in messages})
    first = Window(parse_time("2026-11-08 00:00:00"), parse_time("2026-11-08 00:15:00"))
    second = Window(first.end, first.end + timedelta(minutes=15))
    service.run_window(UID, first)
    assert set(store.messages) == {messages[0].key}
    service.run_window(UID, second)
    assert set(store.messages) == {messages[0].key, messages[1].key}
    assert [m.message_id for m in provider.calls[0][0]] == ["1"]
    assert [m.message_id for m in provider.calls[1][0]] == ["2"]
    assert [m.message_id for m in provider.calls[1][1]] == ["1"]
    for (_, context, events), window in zip(provider.calls, (first, second)):
        assert all(m.sent_at < window.end for m in context)
        assert all(e.end_time < window.end for e in events)


def test_subday_window_spanning_midnight_reads_both_dates(tmp_path):
    messages = [message("1", "2026-11-08 23:59:59"),
                message("2", "2026-11-09 00:00:00"),
                message("3", "2026-11-09 00:15:00")]
    start = parse_time("2026-11-08 23:45:00")
    service, store, source, provider = build(tmp_path, messages,
                                           {m.message_id: candidate(m.message_id) for m in messages}, start=start)
    result = service.run_window(UID, Window(start, parse_time("2026-11-09 00:15:00")))
    assert result.processed == 2
    assert [day.isoformat() for _, day in source.calls] == ["2026-11-08", "2026-11-09"]
    assert [m.message_id for m in provider.calls[0][0]] == ["1", "2"]
    assert messages[2].key not in store.messages


def test_batch_merges_duplicate_candidates_and_keeps_latest_progress(tmp_path):
    messages = [message("1", "2026-11-08 09:00:00"), message("2", "2026-11-08 10:00:00")]
    service, store, _, _ = build(tmp_path, messages,
                                {"1": [candidate("1"), candidate("1")], "2": candidate("2")})
    result = service.run_window(UID, day_window(8))
    assert len(result.created) == 1
    event = store.list_events(UID, service.stream)[0]
    assert [e["message_id"] for e in event.evidence] == ["1", "2"]
    assert len(event.updated_by) == 1
    assert event.summary == candidate("2").summary


def test_batch_does_not_merge_same_topic_beyond_configured_recognition_window(tmp_path):
    messages = [message("1", "2026-11-08 01:00:00"), message("2", "2026-11-08 03:00:00")]
    service, store, _, _ = build(tmp_path, messages,
                                {m.message_id: candidate(m.message_id) for m in messages},
                                match_window=timedelta(hours=1))
    result = service.run_window(UID, day_window(8))
    assert len(result.created) == 2
    assert len(store.list_events(UID, service.stream)) == 2


def test_unknown_subject_is_reviewed_without_silent_creation_or_merge(tmp_path):
    messages = [message("1", "2026-11-08 09:00:00"), message("2", "2026-11-09 09:00:00")]
    service, store, _, _ = build(tmp_path, messages, {"1": candidate("1"), "2": candidate("2", topic=None)})
    first = service.run_window(UID, day_window(8))
    original = deepcopy(store.events)
    uncertain = service.run_window(UID, day_window(9))
    assert uncertain.created == uncertain.updated == []
    assert uncertain.processed == 0
    assert uncertain.review[0]["review_flag"] == "待确认"
    assert uncertain.review[0]["possible_event_ids"] == first.created
    assert uncertain.watermark["last_message_id"] == "1"
    assert store.events == original
    assert [m.message_id for m in store.pending_messages(UID, service.settings.start, day_window(9).end, service.stream)] == ["2"]


def test_review_of_shared_message_does_not_repeat_confirmed_event_revision(tmp_path):
    item = message("1", "2026-11-08 09:00:00")
    service, store, _, _ = build(tmp_path, [item],
                                {"1": [candidate("1"), candidate("1", topic=None, ambiguous=True)]})
    first = service.run_window(UID, day_window(8))
    original = deepcopy(store.events)
    repeated = service.run_window(UID, day_window(8))
    assert len(first.created) == 1
    assert first.review and repeated.review
    assert repeated.created == repeated.updated == []
    assert store.events == original


def test_forged_evidence_rolls_back_ingestion_and_events_then_can_retry(tmp_path):
    messages = [message("1", "2026-11-08 09:00:00"), message("2", "2026-11-08 10:00:00")]
    service, store, _, provider = build(tmp_path, messages,
                                       {"1": candidate("1"), "2": candidate("not-in-input")})
    with pytest.raises(ValueError, match="不存在的证据"):
        service.run_window(UID, day_window(8))
    assert not store.events and not store.messages and not store.processed
    assert service.state.read(UID, service.stream) == {}
    provider.mapping["2"] = candidate("2")
    retry = service.run_window(UID, day_window(8))
    assert retry.processed == 2
    assert len(retry.created) == 1


def test_late_arrival_before_watermark_is_processed_without_reverting_summary(tmp_path):
    first = message("1", "2026-11-08 10:00:00")
    latest = message("2", "2026-11-09 10:00:00")
    service, store, source, provider = build(tmp_path, [first, latest],
                                           {"1": candidate("1"), "2": candidate("2")})
    created = service.run_window(UID, day_window(8)).created
    service.run_window(UID, day_window(9))
    late = message("99", "2026-11-09 09:00:00")
    source.messages.append(late)
    provider.mapping["99"] = candidate("99")
    result = service.run_window(UID, day_window(10))
    assert result.updated == created
    assert result.processed == 1
    event = store.list_events(UID, service.stream)[0]
    assert event.summary == candidate("2").summary
    assert event.end_time == latest.sent_at
    assert {e["message_id"] for e in event.evidence} == {"1", "2", "99"}
    assert result.watermark["last_message_id"] == "2"
    assert result.watermark["last_send_time"] == latest.sent_at.isoformat()


def test_new_provider_version_reprocesses_messages_in_an_isolated_event_stream(tmp_path):
    item = message("1", "2026-11-08 09:00:00")
    service, store, source, _ = build(tmp_path, [item], {"1": candidate("1")})
    first = service.run_window(UID, day_window(8))
    second_provider = FakeProvider({"1": candidate("1")}, name="fixture-test-v2")
    second_service = IncrementalService(store, source, second_provider, service.settings)
    second = second_service.run_window(UID, day_window(8))
    assert second.processed == 1
    assert second.created != first.created
    assert len(store.list_events(UID, service.stream)) == len(store.list_events(UID, second_service.stream)) == 1


def test_empty_day_advances_window_cursor_without_inventing_message_watermark(tmp_path):
    service, store, _, provider = build(tmp_path)
    result = service.run_window(UID, day_window(8))
    assert result.created == result.updated == []
    assert result.watermark == {"next_start": day_window(8).end.isoformat(),
                                "last_send_time": None, "last_message_id": None}
    assert service.state.read(UID, service.stream) == result.watermark
    assert not provider.calls and not store.events


def test_repeated_historical_snapshot_contains_no_future_evidence_or_progress(tmp_path):
    messages = [message("1", "2026-11-08 09:00:00"), message("2", "2026-11-11 10:00:00")]
    service, store, _, provider = build(tmp_path, messages,
                                       {m.message_id: candidate(m.message_id) for m in messages})
    original = service.run_window(UID, day_window(8))
    service.run_window(UID, day_window(11))
    current = deepcopy(store.events)
    repeated = service.run_window(UID, day_window(8))
    assert repeated.events == original.events
    assert [e["message_id"] for e in repeated.events[0]["evidence"]] == ["1"]
    assert repeated.events[0]["summary"] == candidate("1").summary
    assert len(provider.calls) == 2
    assert store.events == current
    assert service.state.read(UID, service.stream)["next_start"] == day_window(11).end.isoformat()


def test_context_lookback_is_separate_from_identity_window(tmp_path):
    messages = [message("1", "2026-11-08 09:00:00"), message("2", "2026-11-11 10:00:00")]
    service, _, _, provider = build(tmp_path, messages,
                                   {m.message_id: candidate(m.message_id) for m in messages},
                                   context_lookback=timedelta(hours=1), match_window=timedelta(days=7))
    created = service.run_window(UID, day_window(8)).created
    result = service.run_window(UID, day_window(11))
    assert result.updated == created
    assert not provider.calls[-1][1]
    assert provider.calls[-1][2][0].event_id == created[0]


def test_customer_identity_isolation_even_when_type_and_topic_match(tmp_path):
    other_uid = "another-fixture-customer"
    messages = [message("1", "2026-11-08 09:00:00"), message("2", "2026-11-08 10:00:00", uid=other_uid)]
    service, store, _, _ = build(tmp_path, messages,
                                {m.message_id: candidate(m.message_id) for m in messages})
    first = service.run_window(UID, day_window(8))
    second = service.run_window(other_uid, day_window(8))
    assert first.created != second.created
    assert len(store.list_events(UID, service.stream)) == len(store.list_events(other_uid, service.stream)) == 1


def test_old_context_evidence_cannot_bypass_recognition_window(tmp_path):
    messages = [message("1", "2026-11-08 09:00:00"), message("2", "2026-11-08 12:00:00")]
    later = candidate("2")
    later.evidence_ids = ["1", "2"]
    service, store, _, provider = build(tmp_path, messages, {"1": candidate("1"), "2": later},
                                       match_window=timedelta(hours=1))
    first = service.run_window(UID, Window(parse_time("2026-11-08"), parse_time("2026-11-08 10:00:00")))
    original = deepcopy(store.events[first.created[0]])
    second = service.run_window(UID, Window(parse_time("2026-11-08 10:00:00"), parse_time("2026-11-08 13:00:00")))
    assert [m.message_id for m in provider.calls[-1][1]] == ["1"]
    assert len(second.created) == 1
    assert second.updated == []
    assert second.created != first.created
    assert store.events[first.created[0]] == original


@pytest.mark.parametrize("action", ["created", "updated"])
def test_snapshot_failure_keeps_cursor_and_retry_recovers_committed_changes(tmp_path, monkeypatch, action):
    messages = [message("1", "2026-11-08 09:00:00"), message("2", "2026-11-09 10:00:00")]
    service, store, _, provider = build(tmp_path, messages,
                                       {m.message_id: candidate(m.message_id) for m in messages})
    target = day_window(8)
    if action == "updated":
        service.run_window(UID, day_window(8))
        target = day_window(9)
    previous_cursor = deepcopy(service.state.read(UID, service.stream))
    write_snapshot = service.state.snapshot

    def fail_snapshot(_result):
        raise OSError("模拟快照写入失败")

    monkeypatch.setattr(service.state, "snapshot", fail_snapshot)
    with pytest.raises(OSError, match="模拟快照写入失败"):
        service.run_window(UID, target)

    # 数据库已提交，但文件失败不能越过这一轮；恢复后应能补齐变化记录。
    assert service.state.read(UID, service.stream) == previous_cursor
    assert len(store.events) == 1
    committed = deepcopy(store.events)
    previous_calls = len(provider.calls)
    monkeypatch.setattr(service.state, "snapshot", write_snapshot)
    repeated = service.run_window(UID, target)
    assert repeated.processed == 0
    assert repeated.created == repeated.updated == []
    assert store.events == committed
    assert len(provider.calls) == previous_calls
    assert service.state.read(UID, service.stream)["next_start"] == target.end.isoformat()

    files = list((tmp_path / "snapshots" / service.state.key(UID, service.stream)).glob("*.json"))
    snapshots = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    recovered = next(snapshot for snapshot in snapshots if snapshot["window"]["start"] == target.start.isoformat())
    assert recovered["recovered_from_history"] is True
    assert recovered[action] == list(committed)
    assert recovered["updated" if action == "created" else "created"] == []


@pytest.mark.parametrize("interval", [timedelta(days=1), timedelta(minutes=15)])
def test_closed_event_grace_behaves_equally_for_day_and_subday_batches(tmp_path, interval):
    messages = [message("1", "2026-11-08 09:00:00"), message("2", "2026-11-08 12:00:00")]
    service, store, _, _ = build(tmp_path, messages,
                                {"1": candidate("1", status="synthetic_closed"), "2": candidate("2")},
                                closed_statuses=("synthetic_closed",), closed_grace=timedelta(hours=1),
                                match_window=timedelta(days=7))
    results = [service.run_window(UID, window) for window in windows(
        day_window(8).start, day_window(8).end, interval)]
    assert sum(len(result.created) for result in results) == 2
    assert sum(len(result.updated) for result in results) == 0
    events = store.list_events(UID, service.stream)
    assert len(events) == 2
    assert events[0].closed_at == messages[0].sent_at
    assert events[1].closed_at is None


def test_message_without_status_does_not_extend_closed_event_grace(tmp_path):
    messages = [message("1", "2026-11-08 09:00:00"),
                message("2", "2026-11-08 09:30:00"),
                message("3", "2026-11-08 10:15:00")]
    mapping = {"1": candidate("1", status="synthetic_closed"),
               "2": candidate("2"), "3": candidate("3")}
    service, store, _, _ = build(tmp_path, messages, mapping,
                                closed_statuses=("synthetic_closed",), closed_grace=timedelta(hours=1),
                                match_window=timedelta(days=7))
    first = service.run_window(UID, Window(parse_time("2026-11-08 09:00:00"), parse_time("2026-11-08 09:15:00")))
    second = service.run_window(UID, Window(parse_time("2026-11-08 09:15:00"), parse_time("2026-11-08 09:45:00")))
    assert second.updated == first.created
    event = store.events[first.created[0]]
    assert event.end_time == messages[1].sent_at
    assert event.closed_at == messages[0].sent_at
    third = service.run_window(UID, Window(parse_time("2026-11-08 09:45:00"), parse_time("2026-11-08 10:30:00")))
    assert len(third.created) == 1
    assert third.created != first.created
    assert third.updated == []


def test_late_candidate_with_newer_context_does_not_revert_summary_or_status(tmp_path):
    first = message("1", "2026-11-08 10:00:00")
    latest = message("2", "2026-11-09 10:00:00")
    service, store, source, provider = build(
        tmp_path, [first, latest],
        {"1": candidate("1", status="synthetic_earlier"),
         "2": candidate("2", summary="合成的较新进展", status="synthetic_latest")},
    )
    created = service.run_window(UID, day_window(8)).created
    service.run_window(UID, day_window(9))
    late = message("99", "2026-11-09 09:00:00")
    source.messages.append(late)
    old_progress = candidate("99", summary="合成的较早进展", status="synthetic_earlier")
    old_progress.evidence_ids = ["99", "2"]
    provider.mapping["99"] = old_progress

    result = service.run_window(UID, day_window(10))
    assert result.updated == created
    assert [m.message_id for m in provider.calls[-1][0]] == ["99"]
    assert "2" in [m.message_id for m in provider.calls[-1][1]]
    event = store.events[created[0]]
    assert event.summary == "合成的较新进展"
    assert event.status == "synthetic_latest"
    assert event.end_time == latest.sent_at
    assert {e["message_id"] for e in event.evidence} == {"1", "2", "99"}
