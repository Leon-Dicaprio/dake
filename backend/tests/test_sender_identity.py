"""使用合成账号验证展示身份优先级、账号隔离和原始证据不被改写。"""

from dataclasses import replace
import json

import pytest

from dake.api.schemas import EvidenceResponse
from dake.config import bound
from dake.domain.models import Message
from dake.services.enrich import enrich_evidence
from dake.services.sender_identity import load_sender_roles, sender_role


def test_confirmed_support_overrides_hint_without_changing_message(tmp_path):
    message = Message("synthetic-identity-customer", "1", bound("2026-11-08T10:00:00"),
                      "合成客服答复", sender_id="synthetic-service-account",
                      sender_name="合成客服改名后的昵称", internal_hint=0)
    config = tmp_path / "config" / "sender_roles.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"accounts": [dict(uid=message.uid, source=message.source,
                      sender_id=message.sender_id, role="support")]}), encoding="utf-8")
    roles = load_sender_roles(tmp_path)
    original = message.to_dict()
    evidence = dict(source=message.source, message_id=message.message_id,
                    send_time=message.sent_at.isoformat(), digest=message.digest, excerpt="合成客服答复")
    result = enrich_evidence(evidence, {(message.source, message.message_id): original}, roles)
    response = EvidenceResponse.model_validate(result)
    assert response.sender_role == "support" and response.internal_hint == 0
    assert response.content == message.content and response.digest == message.digest
    assert original == message.to_dict() and "sender_role" not in evidence
    # 同名的其他账号、其他客户与其他来源都不得继承已确认身份。
    for changes in ({"sender_id": "synthetic-other-account"},
                    {"uid": "synthetic-other-customer"}, {"source": "synthetic_demo"}):
        assert sender_role(replace(message, **changes).to_dict(), roles) == "customer"


@pytest.mark.parametrize("hint,expected", [
    (1, "internal"), (0, "customer"), (None, "unknown"),
    (True, "unknown"), ("1", "unknown"), (2, "unknown"),
])
def test_unconfigured_accounts_keep_original_hint_presentation(hint, expected, tmp_path):
    assert sender_role({"internal_hint": hint}, load_sender_roles(tmp_path)) == expected


def test_duplicate_account_configuration_is_rejected_without_exposing_identity(tmp_path):
    account = dict(uid="synthetic-private-uid", source="official_chat",
                   sender_id="synthetic-private-id", role="support")
    config = tmp_path / "config" / "sender_roles.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"accounts": [account, {**account, "role": "customer"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="重复账号") as error:
        load_sender_roles(tmp_path)
    assert account["sender_id"] not in str(error.value)
