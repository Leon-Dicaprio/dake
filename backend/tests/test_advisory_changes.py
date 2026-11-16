"""非写入建议容错：保留实际建议，不冒充事件变更，也不阻断后续窗口。"""
from copy import deepcopy
import pytest
from offline_http import offline_only
from test_executions import setup, last, stage
from test_attribution import UID, candidate, message, window
from test_summary_history import change
from dake.analysis.summary_changes import validate_changes
from dake.analysis.attribution import parse_attribution_output
from test_attribution import model_output
import json


@pytest.mark.parametrize("action", ["duplicate", "review"])
def test_non_writing_changes_are_saved_as_suggestions_and_next_window_runs(tmp_path, action):
    service, attempts, store, source, provider, first = setup(tmp_path)
    event_id = service.run_window(UID, window(1)).created[0]
    before = deepcopy(store.events)
    follow = message("follow", 2, "合成工单的消息已收到。")
    source.messages.append(follow)
    proposed = [change(follow)]
    provider.mapping[follow.message_id] = candidate(follow, action,
        event_id if action == "duplicate" else None, [first], changes=proposed)
    result = service.run_window(UID, window(2))
    assert result.processed == 1 and not result.created and not result.updated
    assert store.events == before
    assert stage(last(attempts), "suggestions")["suggestions"][0]["value"]["changes"] == proposed
    assert last(attempts)["outcome"] == "committed" and last(attempts)["receipt"]["writes"] == []
    assert service.run_window(UID, window(2)).processed == 0
    third = message("third", 3, "合成工单已定位参数问题。")
    source.messages.append(third)
    provider.mapping[third.message_id] = candidate(third, "update", event_id, [first], changes=[change(third)])
    assert service.run_window(UID, window(3)).updated == [event_id]


def test_field_does_not_need_duplicate_change_reference():
    current = message("current", 2, "合成工单继续排查。")
    detail = message("detail", 2, "合成环境为集群甲。")
    c = candidate(current, changes=[change(current)])
    c.evidence_ids.append(detail.key)
    c.extensions["extraction_v1"] = dict(attributes=[dict(name="环境", value="集群甲",
        quote=detail.content, evidence_ids=[detail.key])])
    validate_changes(c, {m.key: m for m in (current, detail)}, {current.key, detail.key})


def test_parser_retains_review_proposal_with_explicit_nonwriting_record():
    current = message("current", 2, "合成工单归属尚不明确。")
    raw = json.loads(model_output(current))
    raw["candidates"][0]["decision"] = "review"
    records = []
    parsed = parse_attribution_output(json.dumps(raw), [current], [], [], normalizations=records)
    assert parsed[0].changes == raw["candidates"][0]["changes"]
    assert parsed[0].decision == "review"
    assert records == [dict(candidate_index=0, field="changes",
        reason="non_writing_action_proposals_only", decision="review", count=1)]


@pytest.mark.parametrize("action", ["review", "new"])
def test_review_invalid_history_quote_is_audited_not_replaced(action):
    current = message("current", 2, "合成工单归属尚不明确。")
    raw = json.loads(model_output(current))
    item = raw["candidates"][0]
    item["decision"] = action
    invalid = dict(message_id="synthetic:old", quote="未提供的合成历史结论")
    item["basis"].append(invalid)
    records = []
    parsed = parse_attribution_output(json.dumps(raw), [current], [], [], normalizations=records,
        history_items=[dict(id="synthetic:old", fragments=[dict(text="仅提供了合成排查片段。")])])
    if action == "review":
        assert parsed[0].decision == "review" and len(parsed[0].basis) == 1
        assert records[-1]["reason"] == "review_invalid_quotes_not_adopted"
        assert records[-1]["excluded"] == [invalid]
    else:
        # 新建已有当前直接依据，多余的历史错引不参与决定。
        assert invalid not in parsed[0].basis
        assert not any(r["reason"] == "review_invalid_quotes_not_adopted" for r in records)


@pytest.mark.parametrize("action", ["review", "update"])
def test_formal_provider_review_bad_quote_commits_without_extra_model_request(tmp_path, action):
    """正式 Provider 使用虚构响应，验证纠错不会导致额外请求或事件写入。"""
    from dataclasses import replace
    import httpx
    from dake.analysis.providers.xhub import XHubProvider, XHubConfig
    from dake.services.processing import IncrementalService
    service, attempts, store, source, _, first = setup(tmp_path)
    follow = message("follow", 2, "合成工单尚不能确定是否同一问题。")
    calls = []
    def respond(request):
        calls.append(1)
        raw = json.loads(model_output(first if len(calls) == 1 else follow))
        if len(calls) > 1:
            c = raw["candidates"][0]
            c["decision"] = action
            if action == "update":
                c["referenced_event_id"] = next(iter(store.events))
                c["basis"].append(dict(message_id=first.key, quote=first.content))
            c["basis"].append(dict(message_id=first.key, quote="合成的不存在引文"))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps(raw)}}]})
    settings = replace(service.settings, provider="xhub")
    provider = XHubProvider(XHubConfig(model=settings.llm_model, api_key="synthetic-only", max_tokens=8192),
        settings, transport=httpx.MockTransport(respond))
    try:
        service = IncrementalService(store, source, provider, settings, attempts=attempts)
        service.run_window(UID, window(1))
        before = deepcopy(store.events)
        source.messages.append(follow)
        result = service.run_window(UID, window(2))
        assert len(calls) == 2 and not result.created
        assert last(attempts)["outcome"] == "committed"
        if action == "review":
            assert len(result.review) == 1 and not result.updated and store.events == before
            assert last(attempts)["receipt"]["writes"] == []
        else:
            assert result.updated == list(before) and not result.review
            assert len(last(attempts)["receipt"]["writes"]) == 1
        records = stage(last(attempts), "model_completed")["normalizations"]
        reason = "review_invalid_quotes_not_adopted" if action == "review" else "redundant_invalid_quotes_not_adopted"
        assert any(r["reason"] == reason for r in records)
    finally:
        provider.close()


@pytest.mark.parametrize("missing", ["current", "history", "version"])
def test_redundant_quote_requires_remaining_current_and_history_proof(missing):
    from types import SimpleNamespace
    from dake.analysis.attribution import normalize_redundant_basis
    current = message("current", 2, "合成工单新的进展。")
    old = message("old", 1, "合成工单原始报告。")
    c = candidate(current, "update", "synthetic-event", [old])
    bad = dict(message_id=old.key, quote="原文中没有的合成引文")
    c.basis.append(bad)
    if missing == "current": c.basis = c.basis[1:]
    if missing == "history": c.basis = [c.basis[0], bad]
    e = SimpleNamespace(event_id="synthetic-event", evidence=[dict(source=old.source,
        message_id=old.message_id, digest="wrong" if missing == "version" else old.digest)])
    before = deepcopy(c)
    assert normalize_redundant_basis(c, {m.key: m for m in (current, old)}, [], [e], {current.key}) == []
    assert c == before
