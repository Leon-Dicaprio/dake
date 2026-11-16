"""执行四类归属和客户恢复边界，复用事件修订及消息事务。"""

from copy import deepcopy
from dataclasses import asdict, replace

from ..analysis.attribution import decide
from ..analysis.contract import ContractError
from ..analysis.continuity import resolve_continuity, validate_continuity
from ..analysis.updates import apply_candidate
from ..analysis.validation import candidate_times
from ..analysis.summary_changes import validate_changes
from ..config import REVIEW
from ..domain.models import message_order


class _ValidationStore:
    """预校验的空写入目标，不接触数据库、记录器或文件。"""

    def save_event(self, event):
        pass

    def record_attributions(self, pending, stream, records):
        pass


def preflight_attributions(candidates, **kwargs):
    """在隔离副本上复用完整归属逻辑，让提交前的合约错误进入已有纠正机会。"""
    apply_attributions(deepcopy(candidates), store=_ValidationStore(), observe=lambda *a, **k: None,
                       **deepcopy(kwargs))


def _proposal_written(candidate, revision, available):
    """只为已保存的具体事实关联建议，同一消息里的另一项事实不能冒领修订。"""
    if candidate.changes is None:
        return True
    for proposed in candidate.changes:
        refs = {(available[ref["message_id"]].source, available[ref["message_id"]].message_id,
                 available[ref["message_id"]].digest, ref["quote"]) for ref in proposed["evidence"]}
        for written in revision.get("changes", []):
            if ((proposed["kind"], proposed["text"].strip(), proposed["replaces"]) ==
                    (written["kind"], written["text"], written["replaces"]) and
                    refs.intersection((ref["source"], ref["message_id"], ref["digest"], ref["quote"]) for ref in written["evidence"])):
                return True
    return False


def _combine(candidates, old, available, new_keys):
    """只合并同一边界内的普通进展；较早字段不能借新消息覆盖当前结论。"""
    combined = None
    for candidate in candidates:
        if candidate_times(candidate, available, new_keys)[1] < old.end_time:
            candidate = replace(candidate, status=None, severity=None, assignees=[], attributes={}, extensions={})
        if combined is None:
            combined = deepcopy(candidate)
            continue
        combined.evidence_ids = list(dict.fromkeys([*combined.evidence_ids, *candidate.evidence_ids]))
        combined.summary = candidate.summary
        combined.status = candidate.status or combined.status
        combined.severity = candidate.severity or combined.severity
        combined.assignees = candidate.assignees or combined.assignees
        combined.attributes.update(candidate.attributes)
        combined.extensions.update(candidate.extensions)
        if (combined.changes is None) != (candidate.changes is None):
            raise ValueError("同一事件不能混用有变化依据和旧版摘要候选")
        if candidate.changes is not None:
            combined.changes.extend(deepcopy(candidate.changes))
    return combined


def apply_attributions(candidates, *, store, events, visible_events, available, pending, eligible,
                       background, result, settings, observe, customer_keys=(), recorder=None):
    """先核对整批，再按消息时间执行；恢复与再次发生分别保存，不被批内合并压平。"""
    new_keys = {m.key for m in pending}
    human_keys = {m.key for m in eligible}
    plans = []
    for candidate in candidates:
        if any(key not in new_keys for key in candidate.evidence_ids):
            raise ContractError("明确归属的写入证据只能来自本批新增或变更消息，旧背景须放在 basis")
        validate_changes(candidate, available, human_keys)
        validate_continuity(candidate, available, human_keys)
        record = decide(candidate, visible_events=visible_events, available=available,
                        new_keys=new_keys, eligible_keys=human_keys, background=background,
                        uid=result.uid, stream=result.stream, before=result.window.end,
                        closed_statuses=settings.closed_statuses)
        record.update(kind="event_attribution", window_start=result.window.start.isoformat(),
                      window_end=result.window.end.isoformat(), requested_action=candidate.decision)
        if recorder is not None:
            record.update(attempt_id=recorder.attempt_id, proposal_id=recorder.proposals[id(candidate)])
        plans.append((candidate, record))
    # 同一句明确回顾恢复并报告复发，可先写原事件确认，再创建本次事件。
    def order(pair):
        latest = max((available[key] for key in pair[0].evidence_ids), key=message_order)
        return (*message_order(latest), 0 if (pair[0].continuity or {}).get("kind") == "confirm_recovery" else 1)

    ordered = sorted(plans, key=order)
    groups = []
    for pair in ordered:
        candidate, record = pair
        previous = groups[-1][-1] if groups else None
        if (previous and record["action"] == previous[1]["action"] == "update"
                and record["event_id"] == previous[1]["event_id"]
                and candidate.continuity is None and previous[0].continuity is None
                and candidate.changes != [] and previous[0].changes != []
                and previous[0].status not in settings.closed_statuses):
            groups[-1].append(pair)
        else:
            groups.append([pair])
    current = {event.event_id: event for event in events}
    for group in groups:
        accepted = []
        old = None
        for candidate, record in group:
            related = record["event_id"] or (candidate.continuity or {}).get("previous_event_id")
            old = current.get(related)
            boundary = resolve_continuity(candidate, record, old, available=available,
                customer_keys=customer_keys, closed_statuses=settings.closed_statuses)
            if boundary:
                record["continuity"] = boundary
            if record["action"] == "review":
                result.review.append(dict(review_flag=REVIEW, type=candidate.type,
                    message_ids=[available[key].message_id for key in candidate.evidence_ids],
                    possible_event_ids=record["possible_event_ids"], reason=record["reason"]))
            elif record["action"] == "new" or (record["action"] == "update" and candidate.changes != []):
                accepted.append((candidate, record, boundary))
        updated = None
        if accepted:
            first, record, boundary = accepted[0]
            action = record["action"]
            writable = _combine([c for c, _, _ in accepted], old, available, new_keys) if action == "update" else first
            updated = apply_candidate(writable, old if action == "update" else None, available,
                result.uid, result.stream, result.window, settings, new_keys, continuity=boundary)
            if updated is not None:
                if recorder is not None:
                    updated.updated_by[-1].update(attempt_id=recorder.attempt_id,
                        proposal_ids=[r["proposal_id"] for c, r, _ in accepted
                            if _proposal_written(c, updated.updated_by[-1], available)])
                if writable.changes is not None:
                    updated.updated_by[-1]["policy_version"] = record["policy_version"]
                store.save_event(updated)
                current[updated.event_id] = updated
                if action == "new":
                    record["event_id"] = updated.event_id
                    result.created.append(updated.event_id)
                elif updated.event_id not in result.updated:
                    result.updated.append(updated.event_id)
        for candidate, record in group:
            action = record["action"]
            if candidate.changes is not None and action in {"new", "update"}:
                revision = updated.updated_by[-1] if updated is not None else None
                written = {(ref["source"], ref["message_id"], ref["digest"])
                           for change in revision.get("changes", []) for ref in change["evidence"]} if revision else set()
                referenced = {(ref["source"], ref["id"], ref["digest"]) for ref in record["new_evidence"]}
                if not candidate.changes or not written.intersection(referenced):
                    revision = None
                record.update(revision_no=revision.get("revision_no") if revision else None,
                              summary_changed=revision.get("summary_changed", False) if revision else False,
                              change_kind=revision.get("change_kind") if revision else "no_change")
            observe("decision", candidate=asdict(candidate), action=action, event_id=record["event_id"],
                    possible_event_ids=record["possible_event_ids"], reason=record["reason"],
                    **({"proposal_id": record["proposal_id"],
                        "contributed_to_revision": bool(updated and record["proposal_id"] in updated.updated_by[-1].get("proposal_ids", [])),
                        "change_scope": "combined_event_group" if len(group) > 1 else "single_proposal"} if recorder is not None else {}),
                    before=old.to_dict() if old and action != "new" else None,
                    after=updated.to_dict() if updated else old.to_dict() if old else None)
    # 决策仍与事件、processed_by 一起提交；原输入顺序方便逐条审计。
    records = [record for _, record in plans]
    store.record_attributions(pending, result.stream, records)
    result.filter_audit.extend(records)
    return list(current.values())
