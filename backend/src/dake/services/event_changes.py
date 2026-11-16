"""只投影已保存的批次和事件版本，不补造阶段、不查询当前聊天正文。"""

from copy import deepcopy



def run_in_scope(run, uid, stream):
    """任务请求能证明范围，或至少一个已保存周期能证明范围。"""
    if run.get("uid") != uid:
        return False
    request = run.get("request") or {}
    if request.get("analysis_stream") is not None:
        return request["analysis_stream"] == stream
    return any(c.get("uid") == uid and c.get("stream") == stream for c in run.get("cycles", []))


def _reference(ref):
    """归属收据的 id 是原始 ID，message_id 则含来源前缀。"""
    return dict(source=ref.get("source"), message_id=ref.get("id"), digest=ref.get("digest"),
                conversation_id=ref.get("conversation_id"), send_time=ref.get("send_time"),
                quote=ref.get("quote"), role=ref.get("role"))


def _attribution(record):
    """只公开已知收据字段，未保存的模型原始输出不从结果反推。"""
    basis = [_reference(ref) for ref in record.get("basis", [])]
    new_evidence = [_reference(ref) for ref in record.get("new_evidence", [])]
    for ref in new_evidence:
        ref["role"] = "new"
        if not all(ref.get(k) for k in ("source", "message_id", "digest")):
            continue
        quote = next((item.get("quote") for item in basis if item.get("role") == "new" and
            all(item.get(k) == ref.get(k) for k in ("source", "message_id", "digest"))), None)
        if quote is not None:
            ref["quote"] = quote
    return dict(requested_action=record.get("requested_action"), action=record.get("action"),
                event_id=record.get("event_id"), possible_event_ids=record.get("possible_event_ids", []),
                reason=record.get("reason"), revision_no=record.get("revision_no"),
                change_kind=record.get("change_kind"), summary_changed=record.get("summary_changed"),
                basis=basis, new_evidence=new_evidence)


def event_changes(event, page, offset, known_attempt_ids=()):
    """事件相关性以写入列表或归属收据为准，禁止用全量快照成员关系代替。"""
    uid, stream, event_id = event["uid"], event["stream"], event["event_id"]
    revisions = deepcopy(event.get("updated_by", []))
    # 旧版缺快照时保留空值，不拿当前状态填补过去。
    for revision in revisions:
        snapshot = revision.get("snapshot")
        if snapshot and (snapshot.get("uid"), snapshot.get("stream"), snapshot.get("event_id")) != (uid, stream, event_id):
            revision["snapshot"] = None
    runs = [run for run in page["items"] if run_in_scope(run, uid, stream)]
    visible_ids = {run["run_id"] for run in runs}
    batches, tasks = [], []
    for run in runs:
        request = run.get("request") or {}
        # 只有旧周期能证明范围时，不能把当前窗口也归到这个分析范围。
        request_scoped = request.get("analysis_stream") == stream
        recovered_by = run.get("recovered_by")
        tasks.append(dict(run_id=run["run_id"], status=run["status"], created_at=run.get("created_at"),
            completed_windows=run["completed_windows"], total_windows=run["total_windows"],
            current_window=run.get("current_window") if request_scoped else None,
            current_scope_confirmed=request_scoped, error=run.get("error"),
            recovered_by=recovered_by if recovered_by in visible_ids else None,
            recovery_link_unavailable=bool(recovered_by and recovered_by not in visible_ids)))
        for index, cycle in enumerate(run.get("cycles", [])):
            if (cycle.get("uid"), cycle.get("stream")) != (uid, stream):
                continue
            if cycle.get("attempt_id") in known_attempt_ids:
                continue
            records = [r for r in cycle.get("filter_audit", []) if r.get("kind") == "event_attribution"
                and (r.get("event_id") == event_id or event_id in r.get("possible_event_ids", []))]
            created, updated = event_id in cycle.get("created", []), event_id in cycle.get("updated", [])
            if not (records or created or updated):
                continue
            window = cycle["window"]
            # 只有收据明确指向本事件版本才建立批次关联；同窗口或旧快照不足以证明。
            linked = {r.get("revision_no") for r in records if r.get("event_id") == event_id
                      and r.get("revision_no") is not None}
            revision_indexes = [i for i, r in enumerate(revisions) if r.get("revision_no") in linked
                and r.get("window_start") == window["start"] and r.get("window_end") == window["end"]]
            batches.append(dict(run_id=run["run_id"], cycle_index=cycle.get("_cycle_index", index), window=window,
                processed=cycle.get("processed"), counts_complete=cycle.get("counts_complete", True),
                recovered_from_history=cycle.get("recovered_from_history", False),
                created=created, updated=updated, attributions=[_attribution(r) for r in records],
                revision_indexes=revision_indexes))
    linked_runs = {batch["run_id"] for batch in batches}
    tasks = [task for task in tasks if task["run_id"] in linked_runs]
    for task in tasks:
        if task["recovered_by"] and task["recovered_by"] not in linked_runs:
            task.update(recovered_by=None, recovery_link_unavailable=True)
    return dict(uid=uid, stream=stream, event_id=event_id, batches=batches, tasks=tasks,
                revisions=revisions, total_runs=page["total"], offset=offset,
                next_offset=offset + len(page["items"]) if offset + len(page["items"]) < page["total"] else None)
