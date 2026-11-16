"""摘要和变化历史的合成验收；不读取真实配置、聊天或数据库。"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import json
import socket

import pytest

from dake.analysis.attribution import parse_attribution_output
from dake.analysis.contract import ContractError
from dake.analysis.updates import snapshot_as_of
from dake.api.schemas import EventResponse
from dake.config import Settings
from dake.domain.models import TZ, parse_time
from test_attribution import UID, build, candidate, message, model_output, window


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    """显式禁用真实依赖；所有消息和模型结果均为本文件新造。"""
    def forbidden(*args, **kwargs):
        raise RuntimeError("摘要历史验收只能使用本地替身")
    monkeypatch.setattr(Settings, "load", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr("pymysql.connect", forbidden)


def change(msg, text=None, kind="progress", replaces=None):
    return dict(kind=kind, text=text or msg.content, replaces=replaces,
                evidence=[dict(message_id=msg.key, quote=msg.content)])


def opening(tmp_path):
    old = message("opening", 1, "虚构工单 CASE-SUM-42 上传失败，原因未知，待排查。")
    service, store, provider, source = build(tmp_path, [old], {old.message_id: candidate(old, changes=[change(old)])})
    first = service.run_window(UID, window(1))
    return service, store, provider, source, old, first.created[0]


def followup(setup, msg, *, changes=None, **kwargs):
    service, store, provider, source, old, event_id = setup
    source.messages.append(msg)
    provider.mapping[msg.message_id] = candidate(msg, "update", event_id, [old],
        changes=[change(msg)] if changes is None else changes, **kwargs)
    return service.run_window(UID, window(msg.sent_at.day))


def test_material_progress_retains_problem_and_versions_with_proof(tmp_path):
    setup = opening(tmp_path)
    service, store, _, _, old, event_id = setup
    before = deepcopy(store.events[event_id])
    new = message("diagnosis", 2, "虚构排查确认客户端重试未生效，需修复重试逻辑。")
    started = datetime.now(TZ)
    result = followup(setup, new)
    event = store.events[event_id]
    revision = event.updated_by[-1]
    assert event.summary == old.content + "\n" + new.content
    assert event.updated_by[:-1] == before.updated_by
    assert [r["revision_no"] for r in event.updated_by] == [1, 2]
    assert started <= parse_time(revision["recorded_at"]) <= datetime.now(TZ)
    assert revision["recorded_at"] != revision["window_start"]
    assert revision["summary_changed"] and revision["change_kind"] == "progress"
    ref = revision["changes"][0]["evidence"][0]
    assert ref == dict(source=new.source, message_id=new.message_id, digest=new.digest,
                       conversation_id=new.conversation_id, send_time=new.sent_at.isoformat(), quote=new.content)
    assert result.updated == [event_id] and "summary" in revision["changed_fields"]
    assert result.filter_audit[0]["revision_no"] == 2
    assert store.attributions[(new.key, service.stream)]["records"][0]["summary_changed"] is True
    committed = deepcopy(event)
    retry = service.run_window(UID, window(2))
    assert retry.processed == 0 and not retry.updated and store.events[event_id] == committed


@pytest.mark.parametrize("mode", ["duplicate", "empty_update", "same_fact"])
def test_acknowledgement_or_rephrasing_does_not_create_revision(tmp_path, mode):
    setup = opening(tmp_path)
    service, store, provider, source, old, event_id = setup
    before = deepcopy(store.events[event_id])
    ack = message("ack", 2, "虚构工单 CASE-SUM-42 的消息收到。")
    source.messages.append(ack)
    facts = [change(ack, text=old.content)] if mode == "same_fact" else []
    provider.mapping[ack.message_id] = candidate(ack, "duplicate" if mode == "duplicate" else "update",
        event_id, [old], summary="措辞不同的虚构摘要", changes=facts)
    result = service.run_window(UID, window(2))
    assert not result.updated and result.processed == 1
    assert store.events[event_id] == before
    retry = service.run_window(UID, window(2))
    assert retry.processed == 0 and len(provider.calls) == 2 and store.events[event_id] == before


def test_new_confirmation_records_progress_without_rewriting_summary(tmp_path):
    setup = opening(tmp_path)
    _, store, _, _, old, event_id = setup
    new = message("confirmed", 2, "虚构工单 CASE-SUM-42 今天重新测试仍失败。")
    result = followup(setup, new, changes=[change(new, kind="confirmation")], summary="不应覆盖的摘要")
    event = store.events[event_id]
    assert result.updated == [event_id] and event.summary == old.content
    assert event.updated_by[-1]["change_kind"] == "confirmation"
    assert event.updated_by[-1]["summary_changed"] is False
    assert event.end_time == new.sent_at


def test_same_batch_keeps_all_progress_and_saves_one_revision(tmp_path):
    setup = opening(tmp_path)
    service, store, provider, source, old, event_id = setup
    a = message("a", 2, "虚构工单发现请求重复发送。")
    b = replace(message("b", 2, "虚构工单增加了超时日志，等待复测。"), sent_at=a.sent_at + timedelta(hours=1))
    source.messages += [a, b]
    provider.mapping.update({m.message_id: candidate(m, "update", event_id, [old], changes=[change(m)]) for m in [a, b]})
    result = service.run_window(UID, window(2))
    event = store.events[event_id]
    assert event.summary == "\n".join([old.content, a.content, b.content])
    assert len(event.updated_by) == 2 and result.updated == [event_id]
    assert [c["text"] for c in event.updated_by[-1]["changes"]] == [a.content, b.content]
    assert all(r["revision_no"] == 2 for r in result.filter_audit)


@pytest.mark.parametrize("repeated", [False, True])
def test_empty_update_in_mixed_batch_has_no_evidence_or_revision_of_its_own(tmp_path, repeated):
    setup = opening(tmp_path)
    service, store, provider, source, old, event_id = setup
    ack, progress = message("ack", 2, "虚构工单收到。"), message("progress", 2, "虚构工单已增加重试日志。")
    source.messages += [ack, progress]
    provider.mapping.update(ack=candidate(ack, "update", event_id, [old], changes=[change(ack, old.content)] if repeated else []),
                            progress=candidate(progress, "update", event_id, [old], changes=[change(progress)]))
    result = service.run_window(UID, window(2))
    assert result.filter_audit[0]["change_kind"] == "no_change" and result.filter_audit[0]["revision_no"] is None
    assert store.events[event_id].updated_by[-1]["message_ids"] == [progress.message_id]


def test_explicit_correction_replaces_only_target_fragment(tmp_path):
    setup = opening(tmp_path)
    _, store, _, _, old, event_id = setup
    before = deepcopy(store.events[event_id])
    correction = message("correction", 2, "虚构工单更正：已确认是客户端超时，其他诉求不变。")
    text = "已确认客户端超时，等待修复"
    followup(setup, correction, changes=[change(correction, text=text, kind="correction", replaces="原因未知，待排查")])
    event = store.events[event_id]
    assert event.summary == old.content.replace("原因未知，待排查", text)
    assert event.updated_by[0] == before.updated_by[0]
    assert event.updated_by[-1]["change_kind"] == "correction"
    assert event.updated_by[-1]["changes"][0]["replaces"] == "原因未知，待排查"


def test_late_feedback_adds_evidence_without_overwriting_latest_conclusion(tmp_path):
    setup = opening(tmp_path)
    service, store, provider, source, old, event_id = setup
    latest = message("latest", 10, "虚构工单已确认客户端超时，等待修复。")
    followup(setup, latest)
    before = deepcopy(store.events[event_id])
    late = message("late", 9, "虚构工单此前怀疑网络问题。")
    source.messages.append(late)
    provider.mapping[late.message_id] = candidate(late, "update", event_id, [old], changes=[change(late)], status="虚构旧状态")
    result = service.run_window(UID, window(11))
    event = store.events[event_id]
    assert result.updated == [event_id] and event.summary == before.summary and event.status == before.status
    assert event.updated_by[-1]["change_kind"] == "evidence_only"
    assert event.updated_by[-1]["summary_changed"] is False
    assert event.updated_by[-1]["changes"][0]["evidence"][0]["send_time"] == late.sent_at.isoformat()


@pytest.mark.parametrize("error", ["history_evidence", "forged_quote", "missing_target", "overlap", "empty_field_evidence", "whole_summary"])
def test_invalid_change_rejects_whole_batch_without_advancing_version(tmp_path, error):
    setup = opening(tmp_path)
    service, store, provider, source, old, event_id = setup
    new = message("new", 2, "虚构工单确认客户端错误。")
    facts = [change(new)]
    extensions = {}
    if error == "history_evidence":
        facts[0]["evidence"] = [dict(message_id=old.key, quote=old.content)]
    elif error == "forged_quote":
        facts[0]["evidence"][0]["quote"] = "输入里没有这句话"
    elif error == "missing_target":
        facts[0]["replaces"] = "不存在的旧片段"
    elif error == "overlap":
        facts = [change(new, replaces="原因未知，待排查"), change(new, text="另一虚构纠正", replaces="原因未知")]
    elif error == "whole_summary":
        facts[0]["replaces"] = old.content
    else:
        facts = []
        extensions = {"extraction_v1": {"status": {"evidence_ids": [new.key], "value": "虚构状态", "quote": new.content}}}
    source.messages.append(new)
    provider.mapping[new.message_id] = candidate(new, "update", event_id, [old], changes=facts, extensions=extensions)
    before = deepcopy((store.messages, store.events, store.processed, store.attributions))
    with pytest.raises(ContractError):
        service.run_window(UID, window(2))
    assert (store.messages, store.events, store.processed, store.attributions) == before


def test_snapshot_and_api_preserve_proof_and_hide_future_versions(tmp_path):
    setup = opening(tmp_path)
    service, store, _, _, old, event_id = setup
    new = message("follow", 2, "虚构工单增加复测步骤。")
    followup(setup, new)
    event = store.events[event_id]
    first = snapshot_as_of(event, window(1).end)
    assert first["summary"] == old.content and len(first["updated_by"]) == 1
    current = EventResponse.model_validate(event.to_dict()).model_dump()
    assert current["updated_by"][-1]["changes"][0]["evidence"][0]["digest"] == new.digest
    saved = service.state.load_snapshot(UID, service.stream, window(2))
    assert saved["events"][0]["updated_by"][-1]["revision_no"] == 2
    legacy = deepcopy(event.to_dict())
    legacy["updated_by"] = [{key: value for key, value in event.updated_by[0].items()
                             if key in {"action", "window_start", "window_end", "message_ids", "snapshot"}}]
    old_api = EventResponse.model_validate(legacy)
    assert old_api.updated_by[0].revision_no is None and old_api.updated_by[0].recorded_at is None


def test_formal_contract_validates_change_quotes_and_keeps_existing_stream():
    msg = message("new", 1)
    result = parse_attribution_output(model_output(msg), [msg], [], [])
    assert result[0].changes == [change(msg)]
    payload = json.loads(model_output(msg))
    payload["candidates"][0]["changes"][0]["evidence"][0]["quote"] = "未提供的原文"
    with pytest.raises(ContractError):
        parse_attribution_output(json.dumps(payload), [msg], [], [])


def test_edited_message_keeps_old_version_quote_and_digest(tmp_path):
    setup = opening(tmp_path)
    service, store, provider, source, old, event_id = setup
    diagnosis = message("diagnosis", 2, "虚构工单此前怀疑客户端版本偏旧。")
    followup(setup, diagnosis)
    previous = deepcopy(store.events[event_id].updated_by[-1])
    corrected = replace(diagnosis, content="虚构工单更正：已经排除客户端版本，确认是上传参数错误。")
    source.messages[-1] = corrected
    provider.mapping[corrected.message_id] = candidate(corrected, "update", event_id, [old], changes=[change(
        corrected, text="已排除客户端版本，确认上传参数错误。", kind="correction", replaces=diagnosis.content)])
    result = service.run_window(UID, window(2))
    event = store.events[event_id]
    assert result.updated == [event_id] and len(event.updated_by) == 3
    assert event.updated_by[1] == previous
    assert previous["changes"][0]["evidence"][0]["digest"] == diagnosis.digest
    assert event.updated_by[-1]["changes"][0]["evidence"][0]["digest"] == corrected.digest
    assert len({ref["digest"] for ref in event.evidence if ref["message_id"] == diagnosis.message_id}) == 2


def test_field_uses_time_of_its_quote_not_other_evidence(tmp_path):
    setup = opening(tmp_path)
    service, store, provider, source, old, event_id = setup
    latest = message("latest", 10, "虚构工单正在验证中。")
    followup(setup, latest, status="验证中")
    late, fresh = message("late", 9, "虚构工单当时待排查。"), message("fresh", 11, "虚构工单已补充测试日志。")
    source.messages += [late, fresh]
    provider.mapping["fresh"] = candidate(fresh, "update", event_id, [old], status="待排查",
        evidence_ids=[late.key, fresh.key], changes=[change(late), change(fresh)], extensions={"extraction_v1": {
            "status": dict(value="待排查", evidence_ids=[late.key, fresh.key], quote="待排查")}})
    result = service.run_window(UID, window(11))
    event = store.events[event_id]
    assert result.updated == [event_id] and event.status == "验证中"
    assert fresh.content in event.summary and late.content not in event.summary
    assert [c["effect"] for c in event.updated_by[-1]["changes"]] == ["evidence_only", "progress"]


def test_snapshot_failure_retry_preserves_same_committed_revision(tmp_path, monkeypatch):
    setup = opening(tmp_path)
    service, store, _, _, _, event_id = setup
    save = service.state.snapshot
    def failed(*args):
        raise OSError("虚构快照失败")
    monkeypatch.setattr(service.state, "snapshot", failed)
    with pytest.raises(OSError):
        followup(setup, message("follow", 2, "虚构工单已确认参数错误。"))
    committed = deepcopy(store.events[event_id])
    assert len(committed.updated_by) == 2
    monkeypatch.setattr(service.state, "snapshot", save)
    result = service.run_window(UID, window(2))
    assert result.processed == 0 and not result.updated and store.events[event_id] == committed
