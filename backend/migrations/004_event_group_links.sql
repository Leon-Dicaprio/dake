-- 停止写入后显式执行；只回填匹配索引，不改动事件、原证据或历史收据。
CREATE TABLE event_group_links (
    event_id VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
    uid VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    stream VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    source VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
    message_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    digest CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    conversation_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    end_time DATETIME(6) NOT NULL,
    PRIMARY KEY (event_id, source, message_id, digest),
    KEY ix_group_events (uid, stream, source, conversation_id, end_time, event_id),
    KEY ix_group_message (uid, stream, source, message_id, conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- 旧消息必须与证据 digest 一致才能补群；无法还原的归属保留为空，不猜群名。
INSERT INTO event_group_links
    (event_id, uid, stream, source, message_id, digest, conversation_id, end_time)
SELECT DISTINCT e.event_id, e.uid, e.stream, j.source, j.message_id, COALESCE(j.digest, ''),
    COALESCE(NULLIF(j.conversation_id, ''),
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(m.payload, '$.conversation_id')), ''), ''), e.end_time
FROM events e
JOIN JSON_TABLE(e.payload, '$.evidence[*]' COLUMNS (
    source VARCHAR(64) PATH '$.source',
    message_id VARCHAR(128) PATH '$.message_id',
    digest CHAR(64) PATH '$.digest' NULL ON EMPTY,
    conversation_id VARCHAR(128) PATH '$.conversation_id' NULL ON EMPTY
)) AS j
LEFT JOIN messages m ON m.uid=e.uid AND m.source=j.source AND m.message_id=j.message_id AND m.digest=j.digest;
