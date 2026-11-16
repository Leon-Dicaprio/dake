"""查询时为事件证据补上平台、群聊和发送人，不改写已存储的事件。"""

from __future__ import annotations

import json

from ..domain.models import Message
from .sender_identity import SenderRoles, sender_role
from .sender_kinds import SenderKinds, sender_kind

PLATFORM_LABELS = {
    "official_chat": "企业微信",
}

def platform_label(source: str | None) -> str:
    if not source:
        return ""
    if source in PLATFORM_LABELS:
        return PLATFORM_LABELS[source]
    if source.startswith("R:"):
        return "企业微信"
    return source


def parse_payload(payload):
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode()
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload if isinstance(payload, dict) else {}


def conversation_name(payload: dict) -> str:
    conversation_id = str(payload.get("conversation_id") or "")
    return str(payload.get("conversation_name") or conversation_id or "")


def enrich_evidence(item: dict, messages: dict[tuple[str, str], dict],
                    sender_roles: SenderRoles | None = None, sender_kinds: SenderKinds | None = None) -> dict:
    source = str(item.get("source") or "")
    message_id = str(item.get("message_id") or "")
    payload = messages.get((source, message_id), {})
    item = dict(item)
    item["platform"] = source
    item["platform_label"] = platform_label(source)
    item["conversation_id"] = str(payload.get("conversation_id") or "")
    item["conversation_name"] = conversation_name(payload)
    item["sender_name"] = str(payload.get("sender_name") or "")
    hint = payload.get("internal_hint")
    item["internal_hint"] = hint if type(hint) is int and hint in (0, 1) else None
    item["sender_role"] = sender_role(payload, sender_roles)
    item["sender_kind"] = sender_kind(payload, sender_kinds)
    # 原消息未修订时才补完整正文；旧证据摘要不能被后来编辑的聊天悄悄替换。
    item["content"] = None
    if payload.get("content"):
        try:
            if item.get("digest") == Message.from_dict(payload).digest:
                item["content"] = payload["content"]
        except (TypeError, ValueError, KeyError):
            pass
    return item


def enrich_event(item: dict, messages: dict[tuple[str, str], dict],
                 sender_roles: SenderRoles | None = None, sender_kinds: SenderKinds | None = None) -> dict:
    evidence = [enrich_evidence(entry, messages, sender_roles, sender_kinds) for entry in item.get("evidence") or []]
    item = dict(item)
    item["evidence"] = evidence
    conversations: dict[str, dict] = {}
    platforms: list[str] = []
    for entry in evidence:
        label = entry.get("platform_label") or ""
        if label and label not in platforms:
            platforms.append(label)
        conversation_id = entry.get("conversation_id") or ""
        if not conversation_id:
            continue
        conversations[conversation_id] = {
            "id": conversation_id,
            "name": entry.get("conversation_name") or conversation_id,
            "platform": entry.get("platform") or "",
            "platform_label": label,
        }
    item["conversations"] = list(conversations.values())
    item["platforms"] = platforms
    return item


def load_messages(store, uid: str) -> dict[tuple[str, str], dict]:
    rows, _ = store._execute(
        "SELECT source, message_id, payload FROM messages WHERE uid=%s",
        (uid,),
    )
    messages: dict[tuple[str, str], dict] = {}
    for row in rows:
        messages[(row["source"], row["message_id"])] = parse_payload(row["payload"])
    return messages


def enrich_events(store, uid: str, items: list[dict],
                  sender_roles: SenderRoles | None = None, sender_kinds: SenderKinds | None = None) -> list[dict]:
    if not items:
        return items
    messages = load_messages(store, uid)
    return [enrich_event(item, messages, sender_roles, sender_kinds) for item in items]
