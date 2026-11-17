-- 定时编排只保存客户进度、重试与队列关联，不改写消息、事件或原提交收据。
CREATE TABLE IF NOT EXISTS scheduler_control (
    id TINYINT PRIMARY KEY,
    start_date DATE NOT NULL,
    template JSON NOT NULL,
    last_tick DATETIME(6) NULL,
    source_error VARCHAR(256) NULL,
    customer_fingerprint VARCHAR(64) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS processing_schedules (
    schedule_id VARCHAR(36) COLLATE utf8mb4_bin PRIMARY KEY,
    uid VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    stream VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(24) NOT NULL DEFAULT 'active',
    business_start VARCHAR(40) NOT NULL,
    next_start VARCHAR(40) NOT NULL,
    template JSON NOT NULL,
    active_run_id VARCHAR(36) NULL,
    last_run_id VARCHAR(36) NULL,
    retry_attempt_id VARCHAR(36) NULL,
    retry_count INT NOT NULL DEFAULT 0,
    retry_at VARCHAR(40) NULL,
    error VARCHAR(256) NULL,
    last_success VARCHAR(40) NULL,
    last_turn DATETIME(6) NOT NULL DEFAULT '1970-01-01 00:00:00',
    UNIQUE KEY uq_schedule_scope (uid,stream),
    KEY ix_schedule_turn (enabled,last_turn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
