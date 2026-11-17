"""用合成数据验证单一本群处理链路的时间边界、事务与幂等。"""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from dake.config import Settings
from dake.domain.models import Candidate, Message, Window, parse_time
from dake.services.processing import IncrementalService
from fakes import FakeProvider, FakeSource, MemoryStore


UID = "engine-fixture-customer"


def message(mid, at, *, uid=UID, group="synthetic-group-a"):
    return Message(uid=uid, message_id=mid, sent_at=parse_time(at),
                   content=f"合成消息 {mid}，仅用于验证处理流程。", conversation_id=group)


def candidate(mid, *, topic="synthetic-product-a:issue-a", summary=None, event_type="排障", **kwargs):
    return Candidate(type=event_type, topic_key=topic,
                     summary=summary or f"合成事件进展 {mid}", evidence_ids=[mid],
                     decision="new", decision_reason="虚构独立事项", **kwargs)


def day_window(day):
    start = parse_time(f"2026-11-{day:02d}")
    return Window(start, start + timedelta(days=1))


def build(tmp_path, messages=(), mapping=None, **config):
    settings = replace(Settings(), data_dir=tmp_path, uid=UID, **config)
    available = {key: m for m in messages for key in (m.key, m.message_id)}
    for selected in (mapping or {}).values():
        for item in selected if isinstance(selected, list) else [selected]:
            item.evidence_ids = [available[key].key if key in available else key for key in item.evidence_ids]
            item.basis = item.basis or [dict(message_id=key, quote=available[key].content)
                          for key in item.evidence_ids if key in available]
    source, provider, store = FakeSource(messages), FakeProvider(mapping), MemoryStore()
    return IncrementalService(store, source, provider, settings), store, source, provider


def test_repeated_window_adds_no_events_evidence_or_history(tmp_path):
    item = message("1", "2026-11-08 09:00:00")
    service, store, _, provider = build(tmp_path, [item], {"1": candidate("1")})
    service.run_window(UID, day_window(8))
    before = deepcopy(store.events)
    repeated = service.run_window(UID, day_window(8))
    assert (repeated.created, repeated.updated, repeated.processed, repeated.ingested) == ([], [], 0, 0)
    assert repeated.events == [] and repeated.event_count == 1
    assert store.events == before and len(provider.calls) == 1


def test_quarter_hour_filters_future_messages_before_storage_and_provider(tmp_path):
    messages = [message("1", "2026-11-08 00:04:00"),
                message("2", "2026-11-08 00:15:00"), message("3", "2026-11-08 01:00:00")]
    service, store, _, provider = build(tmp_path, list(reversed(messages)),
                                      {m.message_id: candidate(m.message_id) for m in messages})
    first = Window(parse_time("2026-11-08"), parse_time("2026-11-08 00:15:00"))
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
    messages = [message("1", "2026-11-08 23:59:59"), message("2", "2026-11-09 00:00:00"),
                message("3", "2026-11-09 00:15:00")]
    start = parse_time("2026-11-08 23:45:00")
    service, store, source, provider = build(tmp_path, messages,
        {m.message_id: candidate(m.message_id) for m in messages}, start=start)
    result = service.run_window(UID, Window(start, parse_time("2026-11-09 00:15:00")))
    assert result.processed == 2
    assert [day.isoformat() for _, day in source.calls] == ["2026-11-08", "2026-11-09"]
    assert [m.message_id for m in provider.calls[0][0]] == ["1", "2"]
    assert messages[2].key not in store.messages


def test_empty_day_advances_cursor_without_inventing_message_watermark(tmp_path):
    service, store, _, provider = build(tmp_path)
    result = service.run_window(UID, day_window(8))
    assert result.watermark == dict(next_start=day_window(8).end.isoformat(),
                                    last_send_time=None, last_message_id=None)
    assert service.state.read(UID, service.stream) == result.watermark
    assert not provider.calls and not store.events


def test_provider_without_explicit_attribution_rolls_back_instead_of_matching_topic(tmp_path):
    item = message("1", "2026-11-08 09:00:00")
    service, store, _, _ = build(tmp_path, [item], {"1": candidate("1")})
    service.provider.mapping["1"].decision = None
    with pytest.raises(ValueError, match="明确的事项归属"):
        service.run_window(UID, day_window(8))
    assert not store.events and not store.messages and not store.processed


def test_customer_identity_isolation_even_when_type_and_topic_match(tmp_path):
    messages = [message("1", "2026-11-08 09:00:00"),
                message("2", "2026-11-08 10:00:00", uid="another-fixture-customer")]
    service, store, _, _ = build(tmp_path, messages, {m.message_id: candidate(m.message_id) for m in messages})
    first = service.run_window(UID, day_window(8))
    second = service.run_window(messages[1].uid, day_window(8))
    assert first.created != second.created
    assert len(store.events) == 2
