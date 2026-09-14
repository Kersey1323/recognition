from __future__ import annotations

from sqlalchemy import text


VERSION = "20260914_001"
NAME = "add_inquiry_text_index_documents"


async def upgrade(conn) -> None:
    # 本地镜像只描述当前在线 Collection，供配件列表和详情稳定展示文字索引。
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS `inquiry_text_index_document` (
              `document_key` VARCHAR(64) NOT NULL,
              `history_id` BIGINT NOT NULL,
              `inquiry_id` VARCHAR(64) NOT NULL,
              `item_id` BIGINT NOT NULL,
              `item_code` VARCHAR(100) NOT NULL,
              `description` TEXT NOT NULL,
              `content_hash` VARCHAR(64) NOT NULL,
              `index_task_id` VARCHAR(64) NOT NULL,
              `indexed_at` DATETIME NOT NULL,
              PRIMARY KEY (`document_key`),
              KEY `ix_inquiry_text_index_document_item` (`item_id`),
              KEY `ix_inquiry_text_index_document_task` (`index_task_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
    )
