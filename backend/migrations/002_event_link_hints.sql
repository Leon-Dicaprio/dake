-- 显式迁移：只增加自动维护的轻量关联提示，不改写原阶段与收据。
-- 提示允许误命中，正式查询仍核对原关联条件；新增关联路径时须同步迁移。
ALTER TABLE processing_attempts
    ADD COLUMN event_link_hints JSON GENERATED ALWAYS AS (
        JSON_ARRAY(JSON_EXTRACT(stages,
            '$[*].payload.attributions[*].event_id',
            '$[*].payload.attributions[*].possible_event_ids[*]',
            '$[*].payload.candidate.continuity.previous_event_id',
            '$[*].payload.candidates[*].event_id',
            '$[*].payload.event_id',
            '$[*].payload.input.existing_events[*].event_id',
            '$[*].payload.possible_event_ids[*]',
            '$[*].payload.result.items[*].links[*].event_id',
            '$[*].payload.suggestions[*].continuity.previous_event_id',
            '$[*].payload.suggestions[*].possible_event_ids[*]',
            '$[*].payload.suggestions[*].referenced_event_id',
            '$[*].payload.suggestions[*].value.continuity.previous_event_id',
            '$[*].payload.suggestions[*].value.possible_event_ids[*]',
            '$[*].payload.suggestions[*].value.referenced_event_id'),
        JSON_EXTRACT(receipt,
            '$.cycle.created[*]',
            '$.cycle.filter_audit[*].event_id',
            '$.cycle.filter_audit[*].possible_event_ids[*]',
            '$.cycle.updated[*]',
            '$.writes[*].event_id'))
    ) STORED;
