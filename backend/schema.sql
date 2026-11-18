
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `analysis_windows` (
  `window_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `uid` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `stream` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `config_digest` char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `window_start` datetime(6) NOT NULL,
  `window_end` datetime(6) NOT NULL,
  `predecessor_end` datetime(6) DEFAULT NULL,
  `status` varchar(24) COLLATE utf8mb4_bin NOT NULL,
  `available_at` datetime(6) DEFAULT NULL,
  `attempt_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `claimed_epoch` bigint DEFAULT NULL,
  `run_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `stage` varchar(32) COLLATE utf8mb4_bin DEFAULT NULL,
  `queued_at` datetime(6) DEFAULT NULL,
  `started_at` datetime(6) DEFAULT NULL,
  `model_started_at` datetime(6) DEFAULT NULL,
  `committed_at` datetime(6) DEFAULT NULL,
  `error_code` varchar(64) COLLATE utf8mb4_bin DEFAULT NULL,
  PRIMARY KEY (`window_id`),
  UNIQUE KEY `uq_analysis_window` (`uid`,`stream`,`window_start`,`window_end`),
  KEY `ix_analysis_claim` (`status`,`available_at`,`uid`),
  KEY `ix_analysis_uid_start` (`uid`,`status`,`window_start`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `customer_group_history` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `source` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `group_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `run_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `before_value` json DEFAULT NULL,
  `after_value` json NOT NULL,
  `recorded_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_customer_group_history` (`source`,`group_id`,`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `customer_groups` (
  `source` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `group_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `group_name` varchar(512) COLLATE utf8mb4_bin NOT NULL,
  `uid` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `status` varchar(16) COLLATE utf8mb4_bin NOT NULL,
  `reason` varchar(256) COLLATE utf8mb4_bin NOT NULL,
  `candidate_uids` json NOT NULL,
  `first_seen_at` datetime(6) NOT NULL,
  `last_seen_at` datetime(6) NOT NULL,
  `synced_at` datetime(6) NOT NULL,
  PRIMARY KEY (`source`,`group_id`),
  KEY `ix_customer_groups_uid` (`uid`),
  KEY `ix_customer_groups_status` (`status`,`synced_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `customer_profiles` (
  `uid` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `level` varchar(8) COLLATE utf8mb4_bin DEFAULT NULL,
  `rank_value` varchar(64) COLLATE utf8mb4_bin DEFAULT NULL,
  `tam` varchar(256) COLLATE utf8mb4_bin DEFAULT NULL,
  `tam_b` varchar(256) COLLATE utf8mb4_bin DEFAULT NULL,
  `level_state` varchar(16) COLLATE utf8mb4_bin NOT NULL,
  `tam_state` varchar(16) COLLATE utf8mb4_bin NOT NULL,
  `level_error` varchar(256) COLLATE utf8mb4_bin DEFAULT NULL,
  `tam_error` varchar(256) COLLATE utf8mb4_bin DEFAULT NULL,
  `level_synced_at` datetime(6) DEFAULT NULL,
  `tam_synced_at` datetime(6) DEFAULT NULL,
  `attempted_at` datetime(6) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`uid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `events` (
  `event_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `uid` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `stream` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `type` varchar(32) COLLATE utf8mb4_bin NOT NULL,
  `topic_key` varchar(512) COLLATE utf8mb4_bin DEFAULT NULL,
  `start_time` datetime(6) NOT NULL,
  `end_time` datetime(6) NOT NULL,
  `status` varchar(128) COLLATE utf8mb4_bin NOT NULL,
  `review_flag` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL,
  `payload` json NOT NULL,
  PRIMARY KEY (`event_id`),
  KEY `ix_events_uid_stream_end` (`uid`,`stream`,`end_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `isolated_records` (
  `isolation_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `uid` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `source` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `message_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `digest` char(64) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  `send_time` datetime(6) DEFAULT NULL,
  `kind` varchar(32) COLLATE utf8mb4_bin NOT NULL,
  `reason` varchar(255) COLLATE utf8mb4_bin NOT NULL,
  `window_start` datetime(6) DEFAULT NULL,
  `window_end` datetime(6) DEFAULT NULL,
  `payload` json DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  PRIMARY KEY (`isolation_id`),
  UNIQUE KEY `uq_isolated_version` (`source`,`message_id`,`digest`,`kind`),
  KEY `ix_isolated_uid` (`uid`,`created_at`),
  KEY `ix_isolated_kind` (`kind`,`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `messages` (
  `source` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `message_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `uid` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `sent_at` datetime(6) NOT NULL,
  `digest` char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `payload` json NOT NULL,
  `processed_by` json NOT NULL,
  PRIMARY KEY (`source`,`message_id`),
  KEY `ix_messages_uid_time` (`uid`,`sent_at`,`message_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `processing_attempts` (
  `attempt_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `uid` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `stream` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `run_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `window_index` int DEFAULT NULL,
  `window_start` varchar(40) COLLATE utf8mb4_bin NOT NULL,
  `window_end` varchar(40) COLLATE utf8mb4_bin NOT NULL,
  `retry_of` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `outcome` varchar(24) COLLATE utf8mb4_bin NOT NULL,
  `created_at` varchar(40) COLLATE utf8mb4_bin NOT NULL,
  `finished_at` varchar(40) COLLATE utf8mb4_bin DEFAULT NULL,
  `error_type` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL,
  `metadata` json NOT NULL,
  `stages` json NOT NULL,
  `receipt` json DEFAULT NULL,
  `delivery` json DEFAULT NULL,
  `event_link_hints` json GENERATED ALWAYS AS (json_array(json_extract(`stages`,_utf8mb4'$[*].payload.attributions[*].event_id',_utf8mb4'$[*].payload.attributions[*].possible_event_ids[*]',_utf8mb4'$[*].payload.candidate.continuity.previous_event_id',_utf8mb4'$[*].payload.candidates[*].event_id',_utf8mb4'$[*].payload.event_id',_utf8mb4'$[*].payload.input.existing_events[*].event_id',_utf8mb4'$[*].payload.possible_event_ids[*]',_utf8mb4'$[*].payload.result.items[*].links[*].event_id',_utf8mb4'$[*].payload.suggestions[*].continuity.previous_event_id',_utf8mb4'$[*].payload.suggestions[*].possible_event_ids[*]',_utf8mb4'$[*].payload.suggestions[*].referenced_event_id',_utf8mb4'$[*].payload.suggestions[*].value.continuity.previous_event_id',_utf8mb4'$[*].payload.suggestions[*].value.possible_event_ids[*]',_utf8mb4'$[*].payload.suggestions[*].value.referenced_event_id'),json_extract(`receipt`,_utf8mb4'$.cycle.created[*]',_utf8mb4'$.cycle.filter_audit[*].event_id',_utf8mb4'$.cycle.filter_audit[*].possible_event_ids[*]',_utf8mb4'$.cycle.updated[*]',_utf8mb4'$.writes[*].event_id'))) STORED,
  `window_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `claim_epoch` bigint DEFAULT NULL,
  `model_state` varchar(32) COLLATE utf8mb4_bin DEFAULT NULL,
  `request_digest` char(64) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  `error_code` varchar(64) COLLATE utf8mb4_bin DEFAULT NULL,
  PRIMARY KEY (`attempt_id`),
  KEY `ix_attempt_scope_outcome` (`uid`,`stream`,`outcome`),
  KEY `ix_attempt_run_window` (`uid`,`stream`,`run_id`,`window_index`),
  KEY `ix_attempt_model_state` (`uid`,`model_state`),
  KEY `ix_attempt_window` (`window_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `processing_runs` (
  `run_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `uid` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `mode` varchar(16) COLLATE utf8mb4_bin NOT NULL,
  `status` varchar(16) COLLATE utf8mb4_bin NOT NULL,
  `request` json NOT NULL,
  `total_windows` int NOT NULL,
  `completed_windows` int NOT NULL DEFAULT '0',
  `current_window` json DEFAULT NULL,
  `current_baseline` json DEFAULT NULL,
  `runner_id` varchar(36) COLLATE utf8mb4_bin DEFAULT NULL,
  `recovered_by` varchar(36) COLLATE utf8mb4_bin DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `started_at` datetime(6) DEFAULT NULL,
  `finished_at` datetime(6) DEFAULT NULL,
  `error` varchar(512) COLLATE utf8mb4_bin DEFAULT NULL,
  `cycles` json NOT NULL,
  PRIMARY KEY (`run_id`),
  KEY `ix_runs_status_created` (`status`,`created_at`),
  KEY `ix_runs_uid_created` (`uid`,`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `runtime_limits` (
  `resource` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `slot` int NOT NULL,
  `owner` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `epoch` bigint NOT NULL DEFAULT '0',
  `lease_until` datetime(6) DEFAULT NULL,
  `next_allowed_at` datetime(6) DEFAULT NULL,
  `held_reason` varchar(64) COLLATE utf8mb4_bin DEFAULT NULL,
  PRIMARY KEY (`resource`,`slot`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `source_state` (
  `source` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `coverage_start` datetime(6) DEFAULT NULL,
  `fetched_until` datetime(6) DEFAULT NULL,
  `owner` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `epoch` bigint NOT NULL DEFAULT '0',
  `lease_until` datetime(6) DEFAULT NULL,
  `next_poll_at` datetime(6) DEFAULT NULL,
  `incomplete_reason` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL,
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`source`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `source_windows` (
  `fetch_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `source` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `window_start` datetime(6) NOT NULL,
  `window_end` datetime(6) NOT NULL,
  `refresh_generation` bigint NOT NULL DEFAULT '0',
  `status` varchar(24) COLLATE utf8mb4_bin NOT NULL,
  `retry_at` datetime(6) DEFAULT NULL,
  `message_count` int NOT NULL DEFAULT '0',
  `isolated_count` int NOT NULL DEFAULT '0',
  `digest` char(64) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  `error_reason` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `finished_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`fetch_id`),
  UNIQUE KEY `uq_source_window` (`source`,`window_start`,`window_end`,`refresh_generation`),
  KEY `ix_source_window_status` (`source`,`status`,`retry_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `task_definitions` (
  `task_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `config` json NOT NULL,
  `frozen_uids` json NOT NULL,
  `enabled` tinyint(1) NOT NULL DEFAULT '0',
  `version` int NOT NULL DEFAULT '1',
  `cursor_at` datetime(6) DEFAULT NULL,
  `next_run_at` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`task_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `task_executions` (
  `execution_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `task_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `status` varchar(24) COLLATE utf8mb4_bin NOT NULL,
  `stage` varchar(24) COLLATE utf8mb4_bin NOT NULL,
  `state` json NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `finished_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`execution_id`),
  KEY `ix_task_executions_task` (`task_id`,`created_at`),
  KEY `ix_task_executions_status` (`status`,`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `uid_pipeline_state` (
  `uid` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `active_stream` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `origin` datetime(6) DEFAULT NULL,
  `catchup_target` datetime(6) DEFAULT NULL,
  `planned_until` datetime(6) DEFAULT NULL,
  `analyzed_until` datetime(6) DEFAULT NULL,
  `active_window_start` datetime(6) DEFAULT NULL,
  `active_window_end` datetime(6) DEFAULT NULL,
  `owner` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `epoch` bigint NOT NULL DEFAULT '0',
  `lease_until` datetime(6) DEFAULT NULL,
  `heartbeat_at` datetime(6) DEFAULT NULL,
  `input_revision` bigint NOT NULL DEFAULT '0',
  `block_reason` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL,
  `block_kind` varchar(32) COLLATE utf8mb4_bin DEFAULT NULL,
  `last_served_at` datetime(6) DEFAULT NULL,
  `phase` varchar(16) COLLATE utf8mb4_bin NOT NULL DEFAULT 'catchup',
  `incomplete` tinyint NOT NULL DEFAULT '0',
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`uid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

