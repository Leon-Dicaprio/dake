"""按窗口展示实际处理过程，零事件、失败和待确认同样可查；查询没有写入副作用。"""

from .execution_changes import _inputs, _basis, _scoped, _ref


def project_run_execution(record, uid, stream):
    """只投影当时保存的输入及决定，不取当前消息补造历史，不回传模型原始响应。"""
    scope = dict(uid=uid, stream=stream)
    stages = [s for s in record.get('stages', []) if isinstance(s.get('payload'), dict)
              and _scoped(s['payload'], scope)
              and _scoped(s['payload'].get('input', {}), scope)]
    inputs = _inputs(stages, scope)
    saved = [m for batch in inputs for field in ('new_messages', 'auxiliary_messages') for m in batch[field]]
    histories, contexts = [], []
    for stage in stages:
        payload = stage['payload']
        if stage['stage'] == 'history':
            histories.append(dict(metadata=payload.get('metadata', {}), candidates=[c for c in payload.get('candidates', []) if _scoped(c, scope)]))
        if stage['stage'] == 'history_context':
            packet = payload.get('result') or {}
            if not _scoped(packet, scope):
                continue
            for item in packet.get('items', []):
                if _scoped(item, scope):
                    contexts.append(dict(_ref(item, 'history'), fragments=item.get('fragments', []),
                                         availability=item.get('availability')))
    saved += [dict(m, quote=f['text']) for m in contexts for f in m['fragments']]
    suggestions, decisions = [], []
    for stage in stages:
        payload = stage['payload']
        if stage['stage'] == 'suggestions':
            for raw in payload.get('suggestions', []):
                value = raw.get('value', raw)
                suggestions.append(dict(proposal_id=raw.get('proposal_id'), call_no=payload.get('call_no'),
                    action=value.get('decision'), status=value.get('status'),
                    event_id=value.get('referenced_event_id'), possible_event_ids=value.get('possible_event_ids', []),
                    summary=value.get('summary'), reason=value.get('decision_reason'),
                    facts=[c['text'] for c in value.get('changes') or []], basis=_basis(value.get('basis', []), saved)))
        if stage['stage'] == 'decision':
            decisions.append({k: payload.get(k) for k in ('proposal_id', 'action', 'event_id', 'reason',
                'before', 'after', 'contributed_to_revision', 'change_scope')} |
                dict(possible_event_ids=payload.get('possible_event_ids', [])))
    receipt = record.get('receipt')
    valid = (isinstance(receipt, dict) and receipt.get('version') == 1
             and receipt.get('kind') in {'analysis', 'delivery_recovery'}
             and isinstance(receipt.get('writes'), list) and isinstance(receipt.get('processed_versions'), list)
             and receipt.get('cycle', {}).get('window') == dict(start=record['window_start'], end=record['window_end'])
             and (receipt['kind'] != 'delivery_recovery' or not (receipt['writes'] or receipt['processed_versions']))
             and all(receipt.get('cycle', {}).get(k) == v for k, v in
                     (('uid', uid), ('stream', stream), ('attempt_id', record['attempt_id']))))
    return dict(attempt_id=record['attempt_id'], window=dict(start=record['window_start'], end=record['window_end']),
        outcome=record['outcome'], error_type=record.get('error_type'),
        stages=[dict(stage=s['stage'], status=s['status'], recorded_at=s.get('recorded_at'),
                     call_no=s['payload'].get('call_no'), error_type=s['payload'].get('error_type')) for s in stages],
        inputs=inputs, histories=histories, contexts=contexts, suggestions=suggestions, decisions=decisions,
        commit_status='committed' if valid else 'invalid' if receipt else
            'missing' if record['outcome'] == 'committed' else
            'not_committed' if record['outcome'] == 'not_committed' else 'unconfirmed',
        processed=len(receipt['processed_versions']) if valid else None,
        writes=[dict(event_id=w.get('event_id'), action=w.get('action')) for w in receipt['writes']] if valid else [])
