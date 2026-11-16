-- 仅供经确认后的独立迁移使用；应用启动和业务执行均不自动执行本文件。
CREATE TABLE IF NOT EXISTS processing_attempts (
    attempt_id VARCHAR(36) COLLATE utf8mb4_bin PRIMARY KEY,
    uid VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    stream VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    run_id VARCHAR(36) COLLATE utf8mb4_bin NULL,
    window_index INT NULL,
    window_start VARCHAR(40) NOT NULL,
    window_end VARCHAR(40) NOT NULL,
    retry_of VARCHAR(36) COLLATE utf8mb4_bin NULL,
    outcome VARCHAR(24) NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    finished_at VARCHAR(40) NULL,
    error_type VARCHAR(128) NULL,
    metadata JSON NOT NULL,
    stages JSON NOT NULL,
    receipt JSON NULL,
    delivery JSON NULL,
    KEY ix_attempt_scope_outcome (uid,stream,outcome),
    KEY ix_attempt_run_window (uid,stream,run_id,window_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
