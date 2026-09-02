from __future__ import annotations

from sqlalchemy import text


VERSION = "20260902_001"
NAME = "add_viewer360_tasks"


async def upgrade(conn) -> None:
    """显式创建 Viewer360 任务、当前版本指针和失败明细表。"""
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS viewer360_task (
              id BIGINT NOT NULL PRIMARY KEY,
              created_by BIGINT NOT NULL DEFAULT 0,
              updated_by BIGINT NOT NULL DEFAULT 0,
              time_created DATETIME(6) NOT NULL,
              time_updated DATETIME(6) NOT NULL,
              task_id VARCHAR(100) NOT NULL,
              root_task_id VARCHAR(100) NOT NULL,
              retry_from_task_id VARCHAR(100) NULL,
              item_id BIGINT NOT NULL,
              source_video_object VARCHAR(700) NOT NULL,
              source_video_updated_at DATETIME(6) NULL,
              rebuild_existing TINYINT(1) NOT NULL DEFAULT 0,
              retry_mode VARCHAR(30) NOT NULL DEFAULT 'none',
              retry_rows_json JSON NULL,
              retry_reason VARCHAR(500) NULL,
              status VARCHAR(20) NOT NULL DEFAULT 'pending',
              current_stage VARCHAR(30) NOT NULL DEFAULT 'preparing',
              progress INT NOT NULL DEFAULT 0,
              row_count INT NOT NULL DEFAULT 0,
              total_frames INT NOT NULL DEFAULT 0,
              processed_frames INT NOT NULL DEFAULT 0,
              reused_row_count INT NOT NULL DEFAULT 0,
              row_states_json JSON NULL,
              output_bucket VARCHAR(100) NOT NULL,
              output_prefix VARCHAR(700) NOT NULL,
              manifest_object VARCHAR(700) NULL,
              amount_x INT NULL,
              amount_y INT NULL,
              fingerprint VARCHAR(64) NULL,
              pipeline_metadata_json JSON NULL,
              result_deleted_at DATETIME(6) NULL,
              error_message TEXT NULL,
              cancel_reason VARCHAR(500) NULL,
              heartbeat_at DATETIME(6) NULL,
              started_at DATETIME(6) NULL,
              completed_at DATETIME(6) NULL,
              UNIQUE KEY uq_viewer360_task_task_id (task_id),
              KEY ix_viewer360_task_status_created (status, time_created),
              KEY ix_viewer360_task_item_created (item_id, time_created),
              KEY ix_viewer360_task_root_created (root_task_id, time_created)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS item_viewer360_current (
              item_id BIGINT NOT NULL PRIMARY KEY,
              task_id VARCHAR(100) NOT NULL,
              manifest_object VARCHAR(700) NOT NULL,
              amount_x INT NOT NULL,
              amount_y INT NOT NULL,
              fingerprint VARCHAR(64) NOT NULL,
              time_created DATETIME(6) NOT NULL,
              time_updated DATETIME(6) NOT NULL,
              UNIQUE KEY uq_item_viewer360_current_task_id (task_id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS viewer360_task_failure (
              id BIGINT NOT NULL PRIMARY KEY,
              created_by BIGINT NOT NULL DEFAULT 0,
              updated_by BIGINT NOT NULL DEFAULT 0,
              time_created DATETIME(6) NOT NULL,
              time_updated DATETIME(6) NOT NULL,
              task_id VARCHAR(100) NOT NULL,
              row_index INT NULL,
              frame_index INT NULL,
              stage VARCHAR(50) NOT NULL,
              error_type VARCHAR(100) NOT NULL,
              error_message TEXT NOT NULL,
              KEY ix_viewer360_failure_task_created (task_id, time_created)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
    )
