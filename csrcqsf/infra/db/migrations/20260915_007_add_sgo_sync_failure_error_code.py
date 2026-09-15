from sqlalchemy import text


VERSION = "20260915_007"
NAME = "add_sgo_sync_failure_error_code"


async def upgrade(conn) -> None:
    from csrcqsf.infra.db.main_db import _ensure_column

    await _ensure_column(
        conn, "sgo_sync_task_failure", "error_code",
        "`error_code` VARCHAR(50) NULL",
    )
    # 历史失败记录也按同一业务阶段和固定校验原因归类，旧任务可立即按码筛选。
    await conn.execute(text("""
        UPDATE `sgo_sync_task_failure`
        SET `error_code` = CASE
            WHEN `stage` = 'source_validation' AND `error_type` = 'ItemNotFound' THEN 'ITEM_NOT_FOUND'
            WHEN `stage` = 'source_validation' AND `error_message` = '配件 ID 不是有效整数' THEN 'SOURCE_ITEM_ID_INVALID'
            WHEN `stage` = 'source_validation' AND `error_message` = '物料编码为空' THEN 'SOURCE_ITEM_CODE_EMPTY'
            WHEN `stage` = 'source_validation' AND `error_message` = '配件名称为空' THEN 'SOURCE_ITEM_NAME_EMPTY'
            WHEN `stage` = 'source_validation' THEN 'SOURCE_DATA_INVALID'
            WHEN `stage` = 'base_images' THEN 'BASE_IMAGE_METADATA_INVALID'
            WHEN `stage` = 'image_metadata' THEN 'IMAGE_METADATA_FAILED'
            WHEN `stage` = 'sgo_download' THEN 'SGO_DOWNLOAD_FAILED'
            WHEN `stage` = 'zip_extract' THEN 'ZIP_EXTRACT_FAILED'
            WHEN `stage` = 'minio_upload' THEN 'MINIO_UPLOAD_FAILED'
            ELSE 'SYNC_FAILURE_UNKNOWN'
        END
        WHERE `error_code` IS NULL
    """))
    await conn.execute(text(
        "ALTER TABLE `sgo_sync_task_failure` MODIFY COLUMN `error_code` VARCHAR(50) NOT NULL"
    ))
    await conn.execute(text(
        "CREATE INDEX `ix_sgo_sync_failure_task_code` ON `sgo_sync_task_failure` (`task_id`, `error_code`)"
    ))
