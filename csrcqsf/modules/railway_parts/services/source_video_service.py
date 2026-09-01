"""配件三维重构源视频的绑定、替换与删除业务。"""

from __future__ import annotations


def _runtime():
    from csrcqsf.modules.railway_parts.services import reconstruction_video_service

    return reconstruction_video_service


async def _upload_source_video_file(cls, item_id: int, file, runtime=None) -> dict:
    runtime = runtime or _runtime()
    ensure_minio_bucket, _, minio_instance, _, _ = runtime._get_minio_helpers()
    ensure_minio_bucket(runtime.minio_reconstruction_video_bucket)
    safe_name = cls._safe_filename(file.filename)
    date_dir = runtime.datetime.now().strftime("%Y%m%d")
    object_name = f"raw-videos/{item_id}/{date_dir}/{runtime.get_id()}_{safe_name}"
    content_type = file.content_type or "application/octet-stream"

    def _upload() -> int:
        file.file.seek(0, runtime.os.SEEK_END)
        size = file.file.tell()
        file.file.seek(0)
        minio_instance.client.put_object(
            runtime.minio_reconstruction_video_bucket,
            object_name,
            file.file,
            length=size,
            content_type=content_type,
        )
        return size

    size = await runtime.run_sync(_upload)
    await file.close()
    return {
        "video_path": f"{runtime.minio_reconstruction_video_bucket}/{object_name}",
        "filename": safe_name,
        "size": size,
        "content_type": content_type,
    }


async def upload_source_video(
    cls,
    item_id: int,
    file,
    height: float | None = None,
    length: float | None = None,
    width: float | None = None,
    weight: float | None = None,
    runtime=None,
) -> dict:
    runtime = runtime or _runtime()
    item = await cls._require_item_exists(item_id)
    if item.source_video_path:
        raise runtime.ReconstructionBusinessError(
            f"配件已存在原始视频，请使用更新接口替换: item_id={item_id}"
        )

    uploaded = await cls._upload_source_video_file(item_id, file)
    async with runtime.SessionLocal() as session:
        try:
            await runtime.Items.update_source_video(
                session=session,
                item_id=item_id,
                video_path=uploaded["video_path"],
                filename=uploaded["filename"],
                size=uploaded["size"],
                content_type=uploaded["content_type"],
                height=height,
                length=length,
                width=width,
                weight=weight,
                updated_at=runtime.datetime.now(),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            await cls._delete_minio_object(uploaded["video_path"])
            raise

        item = await runtime.Items.get_item_by_id(session, item_id)

    return cls._format_source_video_item(item, message="原始视频上传成功")


async def list_source_videos(
    cls,
    page: int = 1,
    page_size: int = 100,
    runtime=None,
) -> dict:
    runtime = runtime or _runtime()
    limit, offset = cls._page_to_limit_offset(page=page, page_size=page_size)
    async with runtime.SessionLocal() as session:
        records, total = await runtime.Items.list_source_videos(
            session=session,
            limit=limit,
            offset=offset,
        )
        return {
            "total": total,
            "page": page,
            "pageSize": page_size,
            "records": [cls._format_source_video_item(item) for item in records],
        }


async def get_source_video(cls, item_id: int, runtime=None) -> dict:
    runtime = runtime or _runtime()
    item = await cls._require_item_exists(item_id)
    if not item.source_video_path:
        raise runtime.ReconstructionBusinessError(f"配件未绑定原始视频: item_id={item_id}")
    return cls._format_source_video_item(item, message="原始视频查询成功")


async def update_source_video(
    cls,
    item_id: int,
    file=None,
    height: float | None = None,
    length: float | None = None,
    width: float | None = None,
    weight: float | None = None,
    runtime=None,
) -> dict:
    # 新文件先上传并提交新引用，成功后才删除旧对象，避免更新失败导致视频丢失。
    runtime = runtime or _runtime()
    item = await cls._require_item_exists(item_id)
    old_video_path = item.source_video_path
    if not old_video_path and file is None:
        raise runtime.ReconstructionBusinessError(f"配件未绑定原始视频: item_id={item_id}")

    uploaded = None
    if file is not None:
        uploaded = await cls._upload_source_video_file(item_id, file)

    async with runtime.SessionLocal() as session:
        try:
            if uploaded is not None:
                await runtime.Items.update_source_video(
                    session=session,
                    item_id=item_id,
                    video_path=uploaded["video_path"],
                    filename=uploaded["filename"],
                    size=uploaded["size"],
                    content_type=uploaded["content_type"],
                    height=height,
                    length=length,
                    width=width,
                    weight=weight,
                    updated_at=runtime.datetime.now(),
                )
            else:
                await runtime.Items.update_measurements(
                    session=session,
                    item_id=item_id,
                    height=height,
                    length=length,
                    width=width,
                    weight=weight,
                )
            await session.commit()
        except Exception:
            await session.rollback()
            if uploaded is not None:
                await cls._delete_minio_object(uploaded["video_path"])
            raise

        item = await runtime.Items.get_item_by_id(session, item_id)

    if uploaded is not None and old_video_path:
        try:
            await cls._delete_minio_object(old_video_path)
        except Exception as exc:
            runtime.logger.error(
                f"旧原始视频删除失败: item_id={item_id}, path={old_video_path}, err={exc}"
            )

    return cls._format_source_video_item(item, message="原始视频更新成功")


async def delete_source_video(cls, item_id: int, runtime=None) -> dict:
    # 对象已不存在时仍清理数据库元数据，使接口具备最终幂等性。
    runtime = runtime or _runtime()
    item = await cls._require_item_exists(item_id)
    old_video_path = item.source_video_path
    if not old_video_path:
        raise runtime.ReconstructionBusinessError(f"配件未绑定原始视频: item_id={item_id}")

    deleted = await cls._delete_minio_object(old_video_path)
    async with runtime.SessionLocal() as session:
        await runtime.Items.clear_source_video(session=session, item_id=item_id)
        await session.commit()

    message = "原始视频删除成功" if deleted else "原始视频对象不存在，元数据已清理"
    return {
        "item_id": item_id,
        "message": message,
    }
