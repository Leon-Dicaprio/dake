"""总输入预算只压缩可选背景，实际发送的身份和原文保持一致。"""
import json
from types import SimpleNamespace
from copy import deepcopy
import pytest
from dake.analysis.providers.xhub import XHubProvider, XHubError
from test_attribution import message


def fixture():
    old = message("optional-old", 1, "合成较早的无关讨论" * 100)
    linked = message("linked", 1, "合成必要证据" * 30)
    recent = message("optional-recent", 2, "合成近期讨论" * 30)
    bot = message("bot", 2, "合成本轮机器人辅助")
    current = dict(id="official_chat:new", content="合成本轮新消息" * 50)
    context = [old, linked, recent, bot]
    payload = dict(new_messages=[current], context_messages=[dict(id=m.key, content=m.content,
        sender_kind="bot" if m is bot else "human") for m in context],
        history_context=dict(items=[dict(id=linked.key, availability="already_in_input")]), existing_events=[])
    request = dict(messages=[dict(role="system", content="合成提示词"),
        dict(role="user", content=json.dumps(payload, ensure_ascii=False))])
    provider = object.__new__(XHubProvider)
    return provider, request, payload, context


def test_budget_removes_old_optional_context_and_keeps_new_and_linked_input():
    p, request, payload, context = fixture()
    before = deepcopy(payload)
    p.settings = SimpleNamespace(history_context=SimpleNamespace(max_input_chars=len(json.dumps(request,ensure_ascii=False))-100))
    sent = p._fit_context(request, payload, context)
    assert [m.key for m in sent] == [m.key for m in context[1:]]
    assert payload["new_messages"] == before["new_messages"]
    assert payload["history_context"] == before["history_context"]
    assert payload["context_budget"]["omitted_messages"] == 1
    assert json.loads(request["messages"][1]["content"]) == payload
    assert len(json.dumps(request, ensure_ascii=False)) <= p.settings.history_context.max_input_chars


def test_mandatory_input_over_budget_stops_without_discarding_new_messages():
    p, request, payload, context = fixture()
    before = deepcopy(payload)
    p.settings = SimpleNamespace(history_context=SimpleNamespace(max_input_chars=10))
    with pytest.raises(XHubError, match="未丢弃新增消息"):
        p._fit_context(request,payload,context)
    assert payload["new_messages"] == before["new_messages"]
    assert {m["id"] for m in payload["context_messages"]} == {context[1].key,context[3].key}


def test_small_input_is_unchanged_and_repair_text_is_part_of_budget():
    p, request, payload, context = fixture()
    before=deepcopy(request)
    size=len(json.dumps(request,ensure_ascii=False))
    p.settings=SimpleNamespace(history_context=SimpleNamespace(max_input_chars=size))
    assert p._fit_context(request,payload,context) is context and request==before
    request["messages"].append(dict(role="assistant",content="合成纠正前输出" * 30))
    assert len(p._fit_context(request,payload,context)) < len(context)
