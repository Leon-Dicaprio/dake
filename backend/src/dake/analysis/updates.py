"""更新稳定事件身份、追加证据与修订，并恢复历史窗口快照。"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from uuid import uuid4
from ..domain.models import Event, TZ, Window, parse_time
from .validation import candidate_times
from .summary_changes import prepare_summary, restrict_fields


def apply_candidate(candidate, event, available, uid, stream, window: Window, settings, new_keys=None, *, continuity=None):
    """创建或更新稳定 ID，追加可核对证据；完全无变化时返回空值避免空修订。"""
    start, end = candidate_times(candidate, available)
    _, new_end = candidate_times(candidate, available, new_keys)
    created = event is None
    previous = event.to_dict() if event is not None else None
    changes = None
    summary = candidate.summary
    if candidate.changes is not None:
        summary, changes = prepare_summary(candidate, event, available,
            historical=(continuity or {}).get("kind") == "historical",
            keep_facts=bool(continuity and (continuity["kind"] == "retract_recovery" or
                (continuity["kind"] == "confirm_recovery" and event.recovery is None))))
        if not changes and not created:
            return None
        used = {f"{ref['source']}:{ref['message_id']}" for change in changes for ref in change["evidence"]}
        candidate = replace(candidate, evidence_ids=[key for key in candidate.evidence_ids if key in used])
        start, end = candidate_times(candidate, available)
        _, new_end = candidate_times(candidate, available, new_keys)
        candidate = restrict_fields(candidate, event, changes, available)
    if created:
        event = Event(
            event_id=str(uuid4()), uid=uid, stream=stream, type=candidate.type,
            topic_key=candidate.topic_key, start_time=start, end_time=end,
            status=candidate.status or settings.default_status,
            severity=candidate.severity or settings.default_severity,
            summary=summary, created_on=window.start,
        )
    else:
        event = deepcopy(event)
    # 迟到的旧消息只补证据和时间，不允许把较新的概述或状态倒退。
    current_progress = changes is None or any(c["effect"] in {"progress", "correction"} for c in changes)
    if created or (new_end >= event.end_time and current_progress):
        event.summary = summary
        event.status = candidate.status or event.status
        event.severity = candidate.severity or event.severity
        event.assignees = candidate.assignees or event.assignees
        event.attributes.update(candidate.attributes)
        event.extensions.update(candidate.extensions)
        # 未提供新状态的补充证据不能不断延长关闭宽限期；仅进入关闭时记录时刻。
        if event.status in settings.closed_statuses:
            if event.closed_at is None:
                event.closed_at = end
        else:
            event.closed_at = None
    if continuity:
        if continuity["kind"] == "confirm_recovery":
            event.recovery = deepcopy(continuity["recovery"])
        elif continuity["kind"] == "retract_recovery":
            event.recovery = None
            event.closed_at = None
            event.status = candidate.status or settings.default_status
        elif continuity["kind"] == "recurrence":
            event.recurrence_of = deepcopy(continuity["recurrence_of"])
    event.start_time = min(event.start_time, start)
    event.end_time = max(event.end_time, end)
    known = {(e["source"], e["message_id"], e.get("digest")) for e in event.evidence}
    added = []
    for key in candidate.evidence_ids:
        message = available[key]
        identity = message.source, message.message_id, message.digest
        if identity not in known:
            event.evidence.append(dict(source=message.source, message_id=message.message_id,
                                       conversation_id=message.conversation_id,
                                       send_time=message.sent_at.isoformat(), excerpt=message.content[:160],
                                       digest=message.digest))
            known.add(identity)
            added.append(message.message_id)
    snapshot = event.to_dict()
    snapshot.pop("updated_by")
    if previous is not None:
        previous.pop("updated_by")
        if snapshot == previous:
            return None
    revision = dict(
        action="created" if created else "updated", window_start=window.start.isoformat(),
        window_end=window.end.isoformat(), message_ids=added, snapshot=snapshot,
    )
    if changes is not None:
        fields = [key for key in ("summary", "status", "severity", "assignees", "attributes", "recovery", "recurrence_of")
                  if previous is None or previous[key] != snapshot[key]]
        effects = {change["effect"] for change in changes}
        kind = ("created" if created else "correction" if "correction" in effects else
                "progress" if "progress" in effects else "confirmation" if "confirmation" in effects else "evidence_only")
        if continuity and continuity["kind"] == "retract_recovery":
            kind = "correction"
        revision.update(revision_no=len(event.updated_by) + 1, recorded_at=datetime.now(TZ).isoformat(),
                        change_kind=kind, change_summary="；".join(dict.fromkeys(c["text"] for c in changes)),
                        summary_changed=created or previous["summary"] != summary,
                        changed_fields=fields, changes=changes)
    event.updated_by.append(revision)
    return event


def snapshot_as_of(event: Event, end: datetime) -> dict | None:
    """恢复指定窗口结束时的状态，重放旧周期时不显示未来更新。"""
    revisions = [r for r in event.updated_by if parse_time(r["window_end"]) <= end]
    if not revisions:
        return None
    snapshot = deepcopy(revisions[-1]["snapshot"])
    snapshot["updated_by"] = [{k: v for k, v in r.items() if k != "snapshot"} for r in revisions]
    return snapshot
