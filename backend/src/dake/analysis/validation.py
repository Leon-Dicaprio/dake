"""验证候选与证据来源，计算新增证据时间边界。"""

from datetime import datetime
from ..domain.models import Candidate, EVENT_TYPES, Message


def evidence_map(messages: list[Message]) -> dict[str, Message]:
    """建立可回查证据索引；跨来源重号时只接受带来源的完整消息键。"""
    result = {m.key: m for m in messages}
    by_id: dict[str, list[Message]] = {}
    for message in messages:
        by_id.setdefault(message.message_id, []).append(message)
    for key, items in by_id.items():
        if len({item.key for item in items}) == 1:
            result[key] = items[-1]
    return result


def validate_candidates(candidates, new_messages, context) -> dict[str, Message]:
    """拒绝非官方主类型、无来源证据和纯历史重复候选，失败时整批回滚。"""
    available = evidence_map(context + new_messages)
    new_keys = {m.key for m in new_messages}
    for item in candidates:
        if not isinstance(item, Candidate) or item.type not in EVENT_TYPES:
            raise ValueError("抽取结果的主类型不在官方六类中")
        if not isinstance(item.summary, str) or not item.summary.strip():
            raise ValueError("抽取结果缺少内容概述")
        if not isinstance(item.evidence_ids, list) or not item.evidence_ids:
            raise ValueError("抽取结果必须提供证据消息 ID")
        if any(not isinstance(key, str) or key not in available for key in item.evidence_ids):
            raise ValueError("抽取结果引用了输入中不存在的证据")
        if not any(available[key].key in new_keys for key in item.evidence_ids):
            raise ValueError("候选事件必须至少由一条本次新增消息支持")
        if item.topic_key is not None and not isinstance(item.topic_key, str):
            raise ValueError("主题标识必须是字符串或空值")
        if any(value is not None and not isinstance(value, str) for value in (item.status, item.severity)):
            raise ValueError("状态和等级必须是字符串或空值")
        if not isinstance(item.assignees, list) or any(not isinstance(v, str) for v in item.assignees):
            raise ValueError("跟进人字段须为字符串列表")
        if not isinstance(item.attributes, dict) or not isinstance(item.extensions, dict):
            raise ValueError("专属属性和扩展字段须为对象")
    return available


def candidate_times(candidate: Candidate, available: dict, new_keys=None) -> tuple[datetime, datetime]:
    """匹配时以新增证据计时，防止旧上下文拉长区间而绕过认回窗口。"""
    times = [available[key].sent_at for key in candidate.evidence_ids
             if new_keys is None or available[key].key in new_keys]
    return min(times), max(times)
