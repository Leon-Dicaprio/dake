"""批内合并与跨周期身份匹配，尊重认回窗口和关闭宽限。"""

from copy import deepcopy
from ..domain.models import Candidate
from .validation import candidate_times


def merge_batch(candidates: list[Candidate], available: dict, match_window, new_keys=None,
                closed_statuses=(), protected_topics=()) -> list[Candidate]:
    """只合并主题明确且落在认回窗口内的同类候选，未知主题留待复核。"""
    merged = []
    unresolved = []
    # 存在关闭边界的主题保留候选顺序，由逐条匹配判定宽限，避免周期长短改变身份。
    protected = set(protected_topics) | {
        (item.type, item.topic_key.strip() if item.topic_key else None)
        for item in candidates if item.status in closed_statuses
    }
    for original in sorted(candidates, key=lambda c: candidate_times(c, available, new_keys)[1]):
        item = deepcopy(original)
        item.topic_key = item.topic_key.strip() if item.topic_key else None
        if item.ambiguous or not item.topic_key or (item.type, item.topic_key) in protected:
            unresolved.append(item)
            continue
        start, end = candidate_times(item, available, new_keys)
        matches = [old for old in merged if old.type == item.type and old.topic_key == item.topic_key
                   and max(start - candidate_times(old, available, new_keys)[1],
                           candidate_times(old, available, new_keys)[0] - end) <= match_window]
        old = matches[-1] if matches else None
        if old is not None:
            if old.referenced_event_id and item.referenced_event_id and old.referenced_event_id != item.referenced_event_id:
                item.ambiguous = True
            item.evidence_ids = list(dict.fromkeys(old.evidence_ids + item.evidence_ids))
            item.status = item.status or old.status
            item.severity = item.severity or old.severity
            item.assignees = item.assignees or old.assignees
            item.attributes = {**old.attributes, **item.attributes}
            item.extensions = {**old.extensions, **item.extensions}
            item.referenced_event_id = item.referenced_event_id or old.referenced_event_id
            item.ambiguous = item.ambiguous or old.ambiguous
            merged.remove(old)
        merged.append(item)
    return sorted(merged + unresolved, key=lambda c: candidate_times(c, available, new_keys)[1])


def match(candidate, events, available, settings, new_keys=None):
    """在已按 UID/分析流隔离的事件中匹配类型、主题和时间，返回复核标记。"""
    start, end = candidate_times(candidate, available, new_keys)
    possible = []
    for event in events:
        if event.type != candidate.type:
            continue
        gap = max(start - event.end_time, event.start_time - end)
        if gap > settings.match_window:
            continue
        if event.closed_at is not None and end - event.closed_at > settings.closed_grace:
            continue
        possible.append(event)
    if candidate.ambiguous or not candidate.topic_key:
        return None, [e.event_id for e in possible], True
    exact = [e for e in possible if e.topic_key == candidate.topic_key]
    if candidate.referenced_event_id:
        exact = [e for e in exact if e.event_id == candidate.referenced_event_id]
        if len(exact) != 1:
            return None, [e.event_id for e in possible], True
    if len(exact) > 1:
        return None, [e.event_id for e in exact], True
    return exact[0] if exact else None, [], False
