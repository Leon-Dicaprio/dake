"""执行与事件的明确引用规则；不以关键词、窗口或全量快照推测关联。"""


def event_link_patterns(event_id):
    """同一组 JSON 包含条件供 SQL 筛选与只读投影复核使用。"""
    stages = [
        ("candidate", dict(stage="history", payload=dict(candidates=[dict(event_id=event_id)]))),
        ("context", dict(stage="history_context", payload=dict(result=dict(items=[dict(links=[dict(event_id=event_id)])])))),
        ("model_input", dict(stage="model_started", payload=dict(input=dict(existing_events=[dict(event_id=event_id)])))),
    ]
    targets = [dict(referenced_event_id=event_id), dict(possible_event_ids=[event_id]),
               dict(continuity=dict(previous_event_id=event_id))]
    for target in targets:
        stages.append(("suggestion", dict(stage="suggestions", payload=dict(suggestions=[dict(value=target)]))))
        stages.append(("suggestion", dict(stage="model_completed", payload=dict(suggestions=[target]))))
    for target in (dict(event_id=event_id), dict(possible_event_ids=[event_id])):
        stages.append(("decision", dict(stage="decision", payload=target)))
        stages.append(("decision", dict(stage="program_result", payload=dict(attributions=[target]))))
    stages.append(("decision", dict(stage="decision", payload=dict(candidate=dict(continuity=dict(previous_event_id=event_id))))))
    patterns = [(reason, "stages", [value]) for reason, value in stages]
    patterns.append(("write", "receipt", dict(writes=[dict(event_id=event_id)])))
    for value in (dict(created=[event_id]), dict(updated=[event_id]),
                  dict(filter_audit=[dict(event_id=event_id)]), dict(filter_audit=[dict(possible_event_ids=[event_id])])):
        patterns.append(("recovery", "receipt", dict(kind="delivery_recovery", cycle=value)))
    return patterns


def contains(value, expected):
    """只比较明确字段值，遵循所用 JSON_CONTAINS 对象与数组包含语义。"""
    if isinstance(expected, dict):
        return isinstance(value, dict) and all(k in value and contains(value[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(value, list) and all(any(contains(v, e) for v in value) for e in expected)
    return value == expected


def link_reasons(record, event_id):
    """快照里出现事件、理由文字包含 ID，都不是关联证明。"""
    return list(dict.fromkeys(reason for reason, field, expected in event_link_patterns(event_id)
                              if contains(record.get(field), expected)))
