"""同群匹配的 MySQL 8.4 验收；仅使用专用入口及本文件合成事项。"""

from dataclasses import replace
from pathlib import Path

import pytest

from dake.repositories.attempts import DeliveryError
from dake.repositories.mysql import StorageError
from test_execution_mysql import explicit_isolation, case
from test_attribution import candidate, message, window
from test_summary_history import change


pytestmark = pytest.mark.isolated_mysql
ROOT = Path(__file__).resolve().parents[2]


def grouped(case):
    settings = replace(case.settings, group_matching_enabled=True)
    return case.fresh(settings)


def test_group_index_and_exact_message_lookup_are_scoped(case):
    service = grouped(case)
    first = service.run_window(case.uid, window(1))
    old_id = first.created[0]
    other = replace(message("synthetic-other", 2, conversation_id="synthetic-other-room"), uid=case.uid)
    case.source.messages.append(other)
    case.provider.mapping[other.message_id] = candidate(other, changes=[change(other)])
    second = service.run_window(case.uid, window(2))
    assert second.event_count == 2 and second.snapshot_scope == "related_events"
    assert {e["event_id"] for e in second.events} == set(second.created)
    assert case.provider.calls[-1][1:] == ([], [])
    mine = (case.first.source, case.first.conversation_id)
    keys = service.store.group_evidence_keys(case.uid, service.stream, [old_id, second.created[0]], mine)
    assert set(keys) == {old_id}
    heads = service.store.history_event_heads(case.uid, service.stream, window(3).end,
        conversation=mine, message_keys=[case.first.key], limit=8)
    assert [h["event_id"] for h in heads] == [old_id]
    assert not service.store.group_index_incomplete(case.uid, service.stream)


def test_same_group_updates_and_related_receipt_restores_without_model(case, monkeypatch):
    service = grouped(case)
    event_id = service.run_window(case.uid, window(1)).created[0]
    follow = replace(message("synthetic-follow", 2, "虚构报告上传故障鉴权原因已定位"), uid=case.uid)
    case.source.messages.append(follow)
    case.provider.mapping[follow.message_id] = candidate(follow, "update", event_id, [case.first], changes=[change(follow)])
    original = service.state.snapshot
    monkeypatch.setattr(service.state, "snapshot", lambda *_: (_ for _ in ()).throw(OSError("合成文件失败")))
    with pytest.raises(DeliveryError):
        service.run_window(case.uid, window(2))
    parent = case.latest()
    assert parent["receipt"]["cycle"]["snapshot_scope"] == "related_events"
    monkeypatch.setattr(service.state, "snapshot", original)
    result = service.run_window(case.uid, window(2), execution={"retry_of": parent["attempt_id"]})
    assert result.updated == [event_id] and len(case.provider.calls) == 2
    assert result.event_count == 1 and result.recovered_from_attempt_id == parent["attempt_id"]
    assert service.store.event_revision_counts(case.uid, service.stream) == {event_id: 2}


def test_index_failure_rolls_back_events_marks_and_links(case, monkeypatch):
    service = grouped(case)
    def fail(*_):
        raise StorageError("合成索引失败")
    monkeypatch.setattr(service.store, "index_event_groups", fail)
    with pytest.raises(StorageError):
        service.run_window(case.uid, window(1))
    assert not service.store.list_events(case.uid, service.stream)
    assert service.store.pending_messages(case.uid, window(1).start, window(2).end, service.stream)
    rows, _ = service.store._execute("SELECT COUNT(*) AS count FROM event_group_links WHERE uid=%s", (case.uid,))
    assert rows[0]["count"] == 0 and case.latest()["receipt"] is None


@pytest.mark.parametrize("changed", [False, True])
def test_migration_backfill_uses_only_same_digest_messages(case, changed):
    event_id = case.service.run_window(case.uid, window(1)).created[0]
    with case.service.store.transaction(case.uid):
        event = case.service.store.events_by_ids(case.uid, case.service.stream, [event_id])[0]
        for ref in event.evidence:
            ref.pop("conversation_id", None)
        case.service.store.save_event(event)
        if changed:
            case.service.store.upsert_messages([replace(case.first, conversation_id="synthetic-edited-room")])
        case.service.store._execute("DELETE FROM event_group_links WHERE uid=%s", (case.uid,))
        statement = (ROOT / "backend/migrations/004_event_group_links.sql").read_text().split(";")[-2]
        case.service.store._execute(statement + " WHERE e.uid=%s", (case.uid,))
    rows, _ = case.service.store._execute("SELECT conversation_id FROM event_group_links WHERE event_id=%s", (event_id,))
    assert rows[0]["conversation_id"] == ("" if changed else case.first.conversation_id)
    assert case.service.store.group_index_incomplete(case.uid, case.service.stream) == changed


def test_future_window_guard_uses_metadata(case):
    service = grouped(case)
    service.run_window(case.uid, window(1))
    assert service.store.has_future_event_revision(case.uid, service.stream, window(1).start)
    assert not service.store.has_future_event_revision(case.uid, service.stream, window(1).end)


def test_multiple_groups_have_distinct_proposal_ids_in_one_receipt(case):
    service = grouped(case)
    other = replace(message("synthetic-same-window", 1, conversation_id="synthetic-other-room"), uid=case.uid)
    case.source.messages.append(other)
    case.provider.mapping[other.message_id] = candidate(other, changes=[change(other)])
    result = service.run_window(case.uid, window(1))
    stages = case.latest()["stages"]
    proposals = [p["proposal_id"] for s in stages if s["stage"] == "suggestions" for p in s["payload"]["suggestions"]]
    assert len(proposals) == len(set(proposals)) == 2
    assert len(result.created) == result.event_count == 2
    assert len(case.latest()["receipt"]["writes"]) == 2
