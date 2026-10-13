"""图片、视频及其他文件的通用 OSS 上传。"""

from datetime import datetime
import os
from pathlib import Path
import re
from uuid import uuid4

from anyio.to_thread import run_sync
from fastapi import UploadFile

from csrcqsf.infra.storage.minio import (
    ensure_minio_bucket,
    minio_bucket,
    minio_instance,
)


class EmptyFileError(ValueError):
    pass


async def upload_file_to_oss(file: UploadFile) -> str:
    filename = Path((file.filename or "file.bin").replace("\\", "/")).name
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip(".") or "file.bin"
    # 按日期和唯一标识存储，独立上传的同名文件不会覆盖已有文件。
    object_name = f"uploads/{datetime.now():%Y%m%d}/{uuid4().hex}_{filename}"

    def upload():
        file.file.seek(0, os.SEEK_END)
        length = file.file.tell()
        file.file.seek(0)
        if not length:
            raise EmptyFileError("上传文件不能为空")
        ensure_minio_bucket(minio_bucket)
        # 直接使用 UploadFile 的临时文件流，视频无需完整读入应用内存。
        minio_instance.client.put_object(
            minio_bucket,
            object_name,
            file.file,
            length=length,
            content_type=file.content_type or "application/octet-stream",
        )

    try:
        await run_sync(upload)
        return f"{minio_bucket}/{object_name}"
    finally:
        await file.close()
