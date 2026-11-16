"""使用虚构账号与内存仓库验证通知过滤，不调用真实模型或数据库。"""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from dake.api.schemas import EvidenceResponse
from dake.services.enrich import enrich_evidence
from dake.services.sender_kinds import load_sender_kinds, sender_kind
from test_engine import build, candidate, day_window, message, UID


def configure(tmp_path, item, **changes):
    account = dict(uid=item.uid, source=item.source, sender_id=item.sender_id,
                   conversation_id=item.conversation_id, kind="bot", basis="合成测试确认")
    account.update(changes)
    path = tmp_path / "config" / "sender_kinds.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(accounts=[account])), encoding="utf-8")
    return account


def bot(mid="bot-1", time="2026-11-08 09:00:00"):
    return replace(message(mid, time), sender_id="synthetic-bot", sender_name="虚构通知账号",
                   internal_hint=0, content="虚构：服务异常通知")


def test_bot_only_window_skips_provider_keeps_messages_and_deduplicates(tmp_path):
    item = bot()
    configure(tmp_path, item)
    service, store, _, provider = build(tmp_path, [item], {item.message_id: candidate(item.key)})
    digest = item.digest
    result = service.run_window(UID, day_window(8))
    assert not result.created and not result.updated and not provider.calls
    assert result.processed == 1 and item.key in store.messages
    assert store.messages[item.key].digest == digest
    assert result.filter_audit[0]["reason"] == "confirmed_bot_without_new_discussion"
    assert not service.run_window(UID, day_window(8)).processed
    assert not provider.calls


def test_later_customer_discussion_can_use_previously_filtered_alert(tmp_path):
    notice = bot()
    human = replace(message("human", "2026-11-09 10:00:00"), sender_id="synthetic-human", internal_hint=0)
    configure(tmp_path, notice)
    related = candidate(human.key)
    related.evidence_ids.append(notice.key)
    service, store, _, provider = build(tmp_path, [notice, human], {human.message_id: related})
    service.run_window(UID, day_window(8))
    result = service.run_window(UID, day_window(9))
    assert len(result.created) == 1
    new, context, _ = provider.calls[0]
    assert [m.key for m in new] == [human.key]
    assert notice.key in [m.key for m in context]
    assert {e["message_id"] for e in store.events[result.created[0]].evidence} == {notice.message_id, human.message_id}


def test_unrelated_human_does_not_allow_bot_only_candidate(tmp_path):
    notice = bot()
    human = replace(message("human", "2026-11-08 10:00:00"), sender_id="synthetic-human", content="虚构：谢谢")
    configure(tmp_path, notice)
    service, store, _, provider = build(tmp_path, [notice, human], {human.message_id: candidate(notice.key)})
    result = service.run_window(UID, day_window(8))
    assert not result.created and not store.events
    assert provider.calls[0][0] == [human]
    assert result.filter_audit[0]["reason"] == "bot_only_candidate"


def test_unknown_customer_without_internal_reply_is_not_filtered(tmp_path):
    human = replace(bot(), sender_id="unconfirmed-account", content="虚构：客户主动提出扩容诉求")
    service, store, _, _ = build(tmp_path, [human], {human.message_id: candidate(human.key)})
    result = service.run_window(UID, day_window(8))
    assert len(result.created) == 1 and not result.filter_audit
    assert len(store.events) == 1


def test_scope_rename_and_independent_identity_axes(tmp_path):
    notice = bot()
    configure(tmp_path, notice)
    kinds = load_sender_kinds(tmp_path)
    assert sender_kind(replace(notice, sender_name="虚构改名").to_dict(), kinds) == "bot"
    for changes in ({"uid": "other"}, {"source": "other"}, {"sender_id": "other"}, {"conversation_id": "other"}):
        assert sender_kind(replace(notice, **changes).to_dict(), kinds) == "unknown"
    evidence = dict(source=notice.source, message_id=notice.message_id, send_time=notice.sent_at.isoformat(),
                    excerpt="虚构通知", digest=notice.digest)
    payload = notice.to_dict()
    response = EvidenceResponse.model_validate(enrich_evidence(evidence, {(notice.source, notice.message_id): payload},
                                                              sender_kinds=kinds))
    assert response.sender_kind == "bot" and response.sender_role == "customer"
    assert "sender_kind" not in payload and "sender_kind" not in evidence


def test_configuration_change_does_not_reprocess_history_or_change_stream(tmp_path):
    notice = bot()
    service, store, _, _ = build(tmp_path, [notice], {notice.message_id: candidate(notice.key)})
    service.run_window(UID, day_window(8))
    old = deepcopy(store.events)
    stream = service.stream
    configure(tmp_path, notice)
    result = service.run_window(UID, day_window(8))
    assert not result.processed and store.events == old and service.stream == stream


def test_bot_recovery_does_not_update_old_event_without_new_discussion(tmp_path):
    human = replace(message("human", "2026-11-08 10:00:00"), sender_id="synthetic-human")
    recovery = replace(bot(time="2026-11-09 10:00:00"), content="虚构：恢复通知")
    configure(tmp_path, recovery)
    service, store, _, provider = build(tmp_path, [human, recovery], {human.message_id: candidate(human.key),
                                                                 recovery.message_id: candidate(recovery.key, status="虚构已恢复")})
    service.run_window(UID, day_window(8))
    old = deepcopy(store.events)
    result = service.run_window(UID, day_window(9))
    assert not result.updated and store.events == old and len(provider.calls) == 1


def test_failed_processing_rolls_back_bot_processing_marks(tmp_path):
    notice = bot()
    human = replace(message("human", "2026-11-08 10:00:00"), sender_id="synthetic-human")
    configure(tmp_path, notice)
    service, store, _, _ = build(tmp_path, [notice, human], {human.message_id: candidate("missing")})
    with pytest.raises(ValueError):
        service.run_window(UID, day_window(8))
    assert not store.messages and not store.processed and not store.events


def test_invalid_config_does_not_disclose_account(tmp_path):
    account = configure(tmp_path, bot(), basis="")
    with pytest.raises(ValueError) as error:
        load_sender_kinds(tmp_path)
    assert account["sender_id"] not in str(error.value)


def test_model_input_marks_bot_and_records_policy_without_switching_stream(tmp_path):
    import httpx
    from dake.analysis.providers.xhub import XHubConfig, XHubProvider, configured_stream
    from dake.config import Settings
    from provider_fakes import output, response

    notice = bot()
    human = replace(message("human", "2026-11-08 10:00:00"), sender_id="synthetic-human")
    configure(tmp_path, notice)
    settings = replace(Settings(), data_dir=tmp_path, uid=UID, provider="xhub")
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return response(output())

    provider = XHubProvider(XHubConfig(model=settings.llm_model, api_key="synthetic-key", max_tokens=settings.llm_max_tokens), settings,
                            transport=httpx.MockTransport(respond))
    try:
        provider.configure_sender_kinds(load_sender_kinds(tmp_path))
        assert provider.extract([human], [notice], []) == []
        payload = json.loads(requests[0]["messages"][1]["content"])
        assert payload["context_messages"][0]["sender_kind"] == "bot"
        assert payload["new_messages"][0]["sender_kind"] == "unknown"
        assert "客户单方明确反馈即可产生事件" in requests[0]["messages"][0]["content"]
        assert provider.name == configured_stream(settings)
        assert provider.traces[0]["notification_policy"]["version"] == "confirmed-senders-v1"
        assert provider.traces[0]["effective_prompt_hash"]
    finally:
        provider.close()
