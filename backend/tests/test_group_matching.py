"""本群事项匹配的合成验收；不读取业务配置、不访问真实模型。"""

from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest

from dake.analysis.contract import ContractError
from dake.analysis.providers.xhub import XHubConfig, XHubProvider
from dake.config import HistoryRetrievalSettings
from dake.services.processing import IncrementalService
from fakes import FakeSource, MemoryStore
from test_attribution import UID, build, candidate, message, model_output, window
from test_summary_history import change


def setup(tmp_path, **overrides):
    old = message("opening", 1)
    service, store, provider, source = build(tmp_path, [old], {
        old.message_id: candidate(old, attributes={"资源标识": "bucket-A"}, changes=[change(old)])})
    service.settings = replace(service.settings, group_matching_enabled=True, **overrides)
    first = service.run_window(UID, window(1))
    return service, store, provider, source, old, first.created[0]


def follow(setup, msg, action="update", **changes):
    service, store, provider, source, old, event_id = setup
    source.messages.append(msg)
    provider.mapping[msg.message_id] = candidate(msg, action, event_id if action in {"update", "duplicate"} else None,
        [old] if action != "new" or changes.pop("old_basis", False) else [],
        changes=[change(msg)] if action not in {"duplicate", "review"} else [], **changes)
    return service.run_window(UID, window(msg.sent_at.day))


def test_same_group_progress_keeps_id_and_object(tmp_path):
    case = setup(tmp_path)
    result = follow(case, message("follow", 10, "虚构报告上传故障，确认鉴权配置错误"))
    assert result.updated == [case[-1]] and not result.created
    assert len(case[1].group_links[case[-1]]) == 2
    assert all(m.conversation_id == case[4].conversation_id for m in case[2].calls[-1][0] + case[2].calls[-1][1])


def test_same_topic_other_group_creates_its_own_event_without_old_context(tmp_path):
    case = setup(tmp_path)
    msg = message("other", 2, conversation_id="synthetic-separate-group")
    result = follow(case, msg, "new")
    assert len(result.created) == 1 and result.created != [case[-1]] and not result.updated
    assert case[2].calls[-1][1:] == ([], [])
    assert all(item[3] == msg.conversation_id for item in case[1].group_links[result.created[0]])


def test_new_with_text_reference_is_review_even_with_old_proof(tmp_path):
    case = setup(tmp_path)
    msg = message("follow", 2, f"event_id={case[-1]} 虚构报告上传故障已定位鉴权配置")
    result = follow(case, msg, "new", old_basis=True)
    assert result.review and not result.updated and not result.created
    record = case[1].attributions[(msg.key, case[0].stream)]["records"][0]
    assert record["requested_action"] == "new" and record["action"] == "review"
    assert record["program_matching"]["matched_by"] == "explicit_reference"


def test_exact_reference_without_old_evidence_is_review_not_unchecked_update(tmp_path):
    case = setup(tmp_path)
    msg = message("follow", 2, f"event_id={case[-1]} 虚构报告上传故障排查中")
    result = follow(case, msg, "new")
    assert result.review and not result.updated and not result.created and result.processed == 1


def test_cross_group_explicit_reference_cannot_update_or_create(tmp_path):
    case = setup(tmp_path)
    msg = message("follow", 2, f"event_id={case[-1]} 虚构报告上传故障排查中",
                  conversation_id="synthetic-separate-group")
    result = follow(case, msg, "new")
    assert result.review and not result.created and not result.updated
    assert case[2].calls[-1][2] == []


def test_unique_message_reference_is_looked_up_beyond_recent_scan_budget(tmp_path):
    case = setup(tmp_path)
    service, store, provider, source, old, event_id = case
    # 新事件压过旧事项的分页，但明确消息引用仍有独立索引入口。
    extra = message("extra", 9, "另一虚构需求，建立独立核验事项")
    follow(case, extra, "new")
    service.history_retriever.limits = HistoryRetrievalSettings(page_size=1, recent_pages=1, older_pages=1)
    msg = message("follow", 10, f"message_id={old.key} 虚构报告上传鉴权配置错误")
    result = follow(case, msg)
    assert result.updated == [event_id]
    assert event_id in {e.event_id for e in provider.calls[-1][2]}


def test_request_id_does_not_override_independent_new(tmp_path):
    case = setup(tmp_path)
    result = follow(case, message("follow", 2, "request_id=REQ-SYNTHETIC 虚构另一独立报告上传故障"), "new")
    assert result.created and not result.updated


def test_conflicting_resource_requires_review(tmp_path):
    case = setup(tmp_path)
    result = follow(case, message("follow", 2), attributes={"资源标识": "bucket-B"})
    assert result.review and not result.updated and not result.created
    assert case[1].events[case[-1]].attributes["资源标识"] == "bucket-A"


def test_missing_resource_is_not_a_conflict(tmp_path):
    case = setup(tmp_path)
    result = follow(case, message("follow", 2, "虚构报告上传鉴权问题已定位"))
    assert result.updated == [case[-1]]


def test_incomplete_index_never_proves_independent_new(tmp_path):
    case = setup(tmp_path)
    case[1].group_links.clear()
    result = follow(case, message("follow", 2, "虚构另一独立诉求"), "new")
    assert result.review and not result.created and result.processed == 1


def test_no_new_fact_is_non_business_and_leaves_event_unchanged(tmp_path):
    case = setup(tmp_path)
    before = deepcopy(case[1].events)
    msg = message("follow", 2, "虚构报告上传故障原文转发，没有新反馈")
    result = follow(case, msg, "duplicate")
    record = case[1].attributions[(msg.key, case[0].stream)]["records"][0]
    assert case[1].events == before and not result.updated and result.processed == 1
    assert record["business_classification"] == "non_business" and record["processing_action"] == "no_action"


def test_missing_group_is_review_without_model_call(tmp_path):
    msg = message("missing", 1, conversation_id="")
    service, store, provider, _ = build(tmp_path, [msg])
    service.settings = replace(service.settings, group_matching_enabled=True)
    result = service.run_window(UID, window(1))
    assert result.review and result.processed == 1 and not provider.calls and not store.events


def test_later_group_error_rolls_back_prior_group_event_and_index(tmp_path):
    a, b = message("a", 1), message("b", 1, conversation_id="synthetic-other-group")
    service, store, provider, _ = build(tmp_path, [a, b], {"a": candidate(a), "b": candidate(b, "update", "invalid")})
    service.settings = replace(service.settings, group_matching_enabled=True)
    with pytest.raises(ContractError):
        service.run_window(UID, window(1))
    assert not store.events and not store.processed and not store.group_links and not store.attributions


def test_large_group_is_split_without_dropping_new_messages(tmp_path):
    messages = [message(str(i), 1, f"虚构独立事项{i}：" + "合成描述" * 180) for i in range(3)]
    service, store, provider, _ = build(tmp_path, messages, {m.message_id: candidate(m) for m in messages})
    service.settings = replace(service.settings, group_matching_enabled=True, group_batch_chars=1024)
    result = service.run_window(UID, window(1))
    assert result.processed == 3 and len(provider.calls) == 3 and len(result.created) == 3
    assert [m.key for call in provider.calls for m in call[0]] == [m.key for m in messages]
    again = service.run_window(UID, window(1))
    assert again.processed == 0 and len(provider.calls) == 3


def test_actual_provider_extracts_objects_and_attribution_in_one_call(tmp_path):
    msg = message("new", 1, "虚构报告上传 bucket-A 失败")
    service, store, _, source = build(tmp_path, [msg])
    settings = replace(service.settings, provider="xhub", group_matching_enabled=True)
    calls = []
    def respond(request):
        calls.append(json.loads(request.content))
        content = model_output(msg, attributes=[dict(name="资源标识", value="bucket-A",
            evidence_ids=[msg.key], quote="bucket-A")])
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]})
    provider = XHubProvider(XHubConfig(settings.llm_model, "synthetic-key"), settings,
                            transport=httpx.MockTransport(respond))
    try:
        service = IncrementalService(store, source, provider, settings)
        result = service.run_window(UID, window(1))
        assert len(calls) == len(result.created) == 1
        payload = json.loads(calls[0]["messages"][1]["content"])
        assert payload["history_retrieval"]["scope"] == "conversation"
        assert store.events[result.created[0]].attributes["资源标识"] == "bucket-A"
    finally:
        provider.close()


def test_group_mode_never_reads_all_customer_event_bodies(tmp_path, monkeypatch):
    case = setup(tmp_path)
    def forbidden(*_):
        raise AssertionError("本群增量不能读取全客户事件正文")
    monkeypatch.setattr(case[1], "list_events", forbidden)
    result = follow(case, message("follow", 2, "虚构报告上传故障已定位鉴权原因"))
    assert result.updated == [case[-1]] and result.snapshot_scope == "related_events" and result.event_count == 1


def test_same_group_number_in_another_source_is_isolated(tmp_path):
    case = setup(tmp_path)
    result = follow(case, message("other-source", 2, source="synthetic_other_source"), "new")
    assert result.created and not result.updated
    assert case[2].calls[-1][1:] == ([], [])


def test_negated_text_reference_is_not_forced_into_old_event(tmp_path):
    case = setup(tmp_path)
    msg = message("negation", 2, f"这件虚构新问题与 event_id={case[-1]} 无关")
    result = follow(case, msg, "new", old_basis=True)
    assert result.review and not result.updated and not result.created


def test_multiple_events_linked_to_one_message_do_not_become_unique_target(tmp_path):
    case = setup(tmp_path)
    service, store, provider, source, old, event_id = case
    other = deepcopy(store.events[event_id])
    from uuid import uuid4
    other.event_id = str(uuid4())
    other.updated_by[-1]["snapshot"]["event_id"] = other.event_id
    with store.transaction(UID):
        store.save_event(other)
    msg = message("follow", 2, f"message_id={old.key} 虚构报告上传故障进展")
    result = follow(case, msg)
    assert result.review and not result.updated and not result.created


def test_queued_mode_and_batch_budget_are_frozen(tmp_path):
    from contextlib import contextmanager
    from dake.jobs.runner import prepare_request, RunRunner
    from test_runs import MemoryRuns
    case = setup(tmp_path)
    settings = replace(case[0].settings, uid="1000000001", group_batch_chars=2048)
    request, total = prepare_request(settings, dict(start=window(2).start.isoformat(), end=window(2).end.isoformat(), interval="1d"))
    runs = MemoryRuns()
    runs.create(request, total)
    seen = []
    @contextmanager
    def factory(frozen, **_):
        seen.append(frozen)
        yield IncrementalService(MemoryStore(), FakeSource([]), case[2], frozen)
    runner = RunRunner(replace(settings, group_matching_enabled=False, group_batch_chars=8192), runs, service_factory=factory)
    runner.execute(runs.claim_next(runner.runner_id))
    assert seen[0].group_matching_enabled and seen[0].group_batch_chars == 2048
    assert next(iter(runs.items.values()))["status"] == "succeeded"


def test_legacy_request_shape_and_execution_policy_remain_compatible(tmp_path):
    from dake.jobs.runner import prepare_request
    from dake.services.executions import execution_policy
    case = setup(tmp_path)
    service = case[0]
    service.settings = replace(service.settings, group_matching_enabled=False, uid="1000000001")
    request, _ = prepare_request(service.settings, {})
    assert not any(key.startswith("group_") for key in request)
    assert not any(key.startswith("group_") for key in execution_policy(service))


def test_new_with_correction_is_review_and_valid_matter_still_commits(tmp_path):
    a=message('valid',1,'虚构独立资源申请')
    b=message('conflict',1,'虚构上传故障实际一直存在')
    service,store,provider,_=build(tmp_path,[a,b],{
        a.message_id:candidate(a,changes=[change(a)]),
        b.message_id:candidate(b,changes=[change(b,kind='correction',replaces='虚构已恢复')]),
    })
    service.settings=replace(service.settings,group_matching_enabled=True)
    result=service.run_window(UID,window(1))
    assert len(result.created)==len(result.review)==1 and result.processed==2
    record=store.attributions[(b.key,service.stream)]['records'][0]
    assert record['requested_action']=='new' and record['action']=='review'
    assert len(store.events)==1


def test_initial_conflict_does_not_hide_fabricated_evidence(tmp_path):
    from dake.analysis.attribution import parse_attribution_output
    msg=message('conflict',1)
    facts=[change(msg,kind='correction',replaces='虚构已恢复')]
    facts[0]['evidence'][0]['quote']='不在原文中的虚构引文'
    with pytest.raises(ContractError,match='直接证据'):
        parse_attribution_output(model_output(msg,changes=facts),[msg],[],[],review_initial_conflicts=True)


def test_initial_conflict_parser_keeps_actual_model_suggestion(tmp_path):
    from dake.analysis.attribution import parse_attribution_output
    msg=message('conflict',1)
    facts=[change(msg,kind='correction',replaces='虚构已恢复')]
    notes=[]
    parsed=parse_attribution_output(model_output(msg,changes=facts),[msg],[],[],
        review_initial_conflicts=True,normalizations=notes)
    assert parsed[0].decision=='new' and parsed[0].changes==facts
    assert notes[-1]['reason']=='initial_action_conflict_requires_review'
    with pytest.raises(ContractError,match='新建只记录'):
        parse_attribution_output(model_output(msg,changes=facts),[msg],[],[])
