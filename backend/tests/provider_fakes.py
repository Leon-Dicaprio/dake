"""仅供测试使用的消息、候选和模拟模型响应，不提供应用演示入口。"""

import json
from dake.domain.models import Message, parse_time
import httpx

UID = "synthetic-contract-customer"

def message(identifier="m1", time="2026-11-08T09:00:00+08:00", text="合成空间 a 下载失败。"):
    return Message(uid=UID, source="official_chat", message_id=identifier,
                   sent_at=parse_time(time), content=text, sender_id="synthetic-support")


def candidate(**changes):
    value = dict(type="排障", topic_key="存储/a/下载失败", summary="合成空间 a 下载失败。",
                 evidence_ids=[message().key], status=None, severity=None, assignees=[],
                 attributes=[], extensions=[], decision="new", referenced_event_id=None,
                 decision_reason="新出现的明确问题")
    value.update(changes)
    return value


def output(*items):
    return json.dumps(dict(schema_version="1.0", candidates=list(items)), ensure_ascii=False)


def response(content, **changes):
    value = dict(choices=[dict(finish_reason="stop", message=dict(content=content))],
                 usage=dict(prompt_tokens=20, completion_tokens=10, total_tokens=30))
    value.update(changes)
    return httpx.Response(200, json=value)
