from __future__ import annotations


def _runtime():
    from csrcqsf.modules.railway_parts.services import reconstruction_task_service

    return reconstruction_task_service


def _build_result_object_name(cls, item_id: int, task_id: str) -> str:
    return f"results/{item_id}/{task_id}/point_cloud.ply"


def _format_reconstruction_result_path(cls, object_name: str, runtime=None) -> str:
    runtime = runtime or _runtime()
    return f"{runtime.minio_reconstruction_file_bucket}/{object_name}"


def _safe_result_filename(cls, filename: str | None, runtime=None) -> str:
    runtime = runtime or _runtime()
    raw_name = runtime.Path(filename or "point_cloud.ply").name
    safe_name = runtime.re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
    return safe_name or "point_cloud.ply"


def _resolve_record_ply_path(cls, record, runtime=None) -> str | None:
    runtime = runtime or _runtime()
    _, looks_like_minio_path, _, _, _ = runtime._get_minio_helpers()
    if record.ply_url and not looks_like_minio_path(
        record.ply_url,
        default_bucket=runtime.minio_reconstruction_file_bucket,
    ):
        return record.ply_url

    if record.output_path:
        return str(
            runtime.Path(record.output_path)
            / "point_cloud"
            / f"iteration_{record.iterations}"
            / "point_cloud.ply"
        )

    return None


async def _upload_reconstruction_result_file(
    cls,
    item_id: int,
    task_id: str,
    ply_path: str,
    runtime=None,
) -> str | None:
    runtime = runtime or _runtime()
    if not ply_path:
        return None

    if not runtime.os.path.exists(ply_path):
        runtime.logger.warning(f"重构结果文件不存在，跳过上传: task_id={task_id}, path={ply_path}")
        return None

    ensure_minio_bucket, _, minio_instance, _, _ = runtime._get_minio_helpers()
    ensure_minio_bucket(runtime.minio_reconstruction_file_bucket)
    object_name = cls._build_result_object_name(item_id=item_id, task_id=task_id)

    def _upload() -> None:
        minio_instance.client.fput_object(
            runtime.minio_reconstruction_file_bucket,
            object_name,
            ply_path,
            content_type="application/octet-stream",
        )

    await runtime.run_sync(_upload)
    return cls._format_reconstruction_result_path(object_name, runtime=runtime)


async def _upload_manual_reconstruction_result_file(cls, item_id: int, file, runtime=None) -> dict:
    runtime = runtime or _runtime()
    ensure_minio_bucket, _, minio_instance, _, _ = runtime._get_minio_helpers()
    ensure_minio_bucket(runtime.minio_reconstruction_file_bucket)
    safe_name = cls._safe_result_filename(file.filename, runtime=runtime)
    object_name = f"results/manual/{item_id}/{runtime.get_id()}_{safe_name}"
    content_type = file.content_type or "application/octet-stream"

    def _upload() -> int:
        file.file.seek(0, runtime.os.SEEK_END)
        size = file.file.tell()
        file.file.seek(0)
        minio_instance.client.put_object(
            runtime.minio_reconstruction_file_bucket,
            object_name,
            file.file,
            length=size,
            content_type=content_type,
        )
        return size

    size = await runtime.run_sync(_upload)
    await file.close()
    return {
        "ply_url": cls._format_reconstruction_result_path(object_name, runtime=runtime),
        "filename": safe_name,
        "size": size,
        "content_type": content_type,
    }


async def _persist_success_result(
    cls,
    session,
    record,
    task_result: dict,
    runtime=None,
) -> bool:
    # 远端若已返回 MinIO 路径则直接绑定；本地文件路径则先上传再更新配件模型入口。
    runtime = runtime or _runtime()
    ply_path = task_result.get("ply_path")
    if task_result.get("output_dir") and not record.output_path:
        await runtime.ReconstructionRecord.update_result(
            session=session,
            task_id=record.task_id,
            output_path=task_result.get("output_dir"),
        )
    if not ply_path:
        return False

    _, looks_like_minio_path, _, _, _ = runtime._get_minio_helpers()
    if looks_like_minio_path(
        ply_path,
        default_bucket=runtime.minio_reconstruction_file_bucket,
    ):
        changed = False
        await runtime.ReconstructionRecord.update_result(
            session=session,
            task_id=record.task_id,
            output_path=task_result.get("output_dir"),
            ply_url=ply_path,
        )
        if record.ply_url != ply_path:
            record.ply_url = ply_path
            changed = True
        item = await runtime.Items.get_item_by_id(session, record.item_id)
        if item is not None and item.obj_url != ply_path:
            await runtime.Items.update_obj_url(
                session=session,
                item_id=record.item_id,
                obj_url=ply_path,
            )
            changed = True
        return changed

    if record.ply_url and looks_like_minio_path(
        record.ply_url,
        default_bucket=runtime.minio_reconstruction_file_bucket,
    ):
        item = await runtime.Items.get_item_by_id(session, record.item_id)
        if item is not None and not item.obj_url:
            await runtime.Items.update_obj_url(
                session=session,
                item_id=record.item_id,
                obj_url=record.ply_url,
            )
            return True
        return False

    result_path = await cls._upload_reconstruction_result_file(
        item_id=record.item_id,
        task_id=record.task_id,
        ply_path=ply_path,
        runtime=runtime,
    )
    if result_path is None:
        return False

    await runtime.ReconstructionRecord.update_result(
        session=session,
        task_id=record.task_id,
        output_path=task_result.get("output_dir"),
        ply_url=result_path,
    )
    await runtime.Items.update_obj_url(
        session=session,
        item_id=record.item_id,
        obj_url=result_path,
    )
    record.ply_url = result_path
    return True


async def persist_task_result_by_task_id(cls, task_id: str, task_result: dict, runtime=None) -> bool:
    """将远端终态和 PLY 结果原子关联到任务及配件主数据。"""
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        record = await runtime.ReconstructionRecord.get_by_task_id(session, task_id)
        if not record:
            runtime.logger.warning(f"重构结果持久化时未找到任务记录: task_id={task_id}")
            return False

        completed_at = runtime.datetime.now()
        elapsed_sec = task_result.get("elapsed_sec")
        task_error = runtime.get_reconstruction_task_failure_message(task_result)
        if task_error is not None:
            await runtime.ReconstructionRecord.update_status(
                session=session,
                task_id=task_id,
                status=runtime.ReconstructionStatus.FAILED,
                progress=record.progress,
                current_stage="失败",
                error_message=task_error,
                completed_at=completed_at,
                elapsed_sec=elapsed_sec,
            )
            await session.commit()
            return False

        changed = await cls._persist_success_result(
            session=session,
            record=record,
            task_result=task_result,
            runtime=runtime,
        )

        await runtime.ReconstructionRecord.update_status(
            session=session,
            task_id=task_id,
            status=runtime.ReconstructionStatus.SUCCESS,
            progress=100,
            current_stage="完成",
            error_message=None,
            completed_at=completed_at,
            elapsed_sec=elapsed_sec,
        )
        await session.commit()
        return changed


async def ensure_item_result_persisted(cls, item_id: int, runtime=None) -> bool:
    # 兼容早期成功任务未写回 obj_url 的情况，寻找已有成功结果补齐引用。
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        item = await runtime.Items.get_item_by_id(session, item_id)
        if item is None or item.obj_url:
            return False

        records = await runtime.ReconstructionRecord.get_by_item_id(session, item_id)
        for record in records:
            if record.status != runtime.ReconstructionStatus.SUCCESS:
                continue

            changed = await cls._persist_success_result(
                session=session,
                record=record,
                task_result={
                    "ply_path": cls._resolve_record_ply_path(record, runtime=runtime),
                    "output_dir": record.output_path,
                },
                runtime=runtime,
            )
            if changed:
                await session.commit()
                return True

        return False


async def upload_reconstruction_result(cls, item_id: int, file, runtime=None) -> dict:
    runtime = runtime or _runtime()
    item = await cls._require_item_exists(item_id)
    if item.obj_url:
        raise runtime.ReconstructionBusinessError("已经存在重构模型，请先删除后再上传")
    if not str(file.filename or "").lower().endswith(".ply"):
        raise runtime.ReconstructionBusinessError("仅支持上传 .ply 文件")

    uploaded = await cls._upload_manual_reconstruction_result_file(
        item_id,
        file,
        runtime=runtime,
    )

    async with runtime.SessionLocal() as session:
        try:
            await runtime.Items.update_obj_url(
                session=session,
                item_id=item_id,
                obj_url=uploaded["ply_url"],
            )
            await session.commit()
        except Exception:
            await session.rollback()
            await cls._delete_minio_object(
                uploaded["ply_url"],
                default_bucket=runtime.minio_reconstruction_file_bucket,
            )
            raise

    return {
        "item_id": item_id,
        "ply_url": uploaded["ply_url"],
        "filename": uploaded["filename"],
        "size": uploaded["size"],
        "content_type": uploaded["content_type"],
        "message": "重构模型上传成功",
    }


async def delete_reconstruction_result(cls, task_id: str, runtime=None) -> dict:
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        record = await runtime.ReconstructionRecord.get_by_task_id(session, task_id)
        if not record:
            raise runtime.ReconstructionBusinessError(f"重构任务不存在: task_id={task_id}")

        result_paths = list(
            dict.fromkeys(
                path
                for path in (record.ply_url, record.obj_url, record.glb_url)
                if path
            )
        )
        if not result_paths:
            raise runtime.ReconstructionBusinessError(f"重构任务未绑定三维重构结果: task_id={task_id}")

        _, looks_like_minio_path, _, _, _ = runtime._get_minio_helpers()
        minio_result_count = 0
        deleted_count = 0
        for result_path in result_paths:
            if looks_like_minio_path(
                result_path,
                default_bucket=runtime.minio_reconstruction_file_bucket,
            ):
                minio_result_count += 1
                if await cls._delete_minio_object(
                    result_path,
                    default_bucket=runtime.minio_reconstruction_file_bucket,
                ):
                    deleted_count += 1
            else:
                runtime.logger.info(
                    f"任务重构结果不是MinIO路径，仅清理数据库引用: task_id={task_id}, path={result_path}"
                )

        item = await runtime.Items.get_item_by_id(session, record.item_id)
        # 删除历史任务时保留配件当前模型；只有当前绑定指向该任务结果才同步清空。
        if item and item.obj_url in result_paths:
            await runtime.Items.update_obj_url(
                session=session,
                item_id=record.item_id,
                obj_url=None,
            )

        record.ply_url = None
        record.obj_url = None
        record.glb_url = None
        await session.flush()
        await session.commit()

    if minio_result_count:
        message = "三维重构结果删除成功" if deleted_count else "三维重构结果对象不存在，元数据已清理"
    else:
        message = "旧本地重构结果引用已清理"

    return {
        "task_id": task_id,
        "item_id": record.item_id,
        "result_path": result_paths[0],
        "message": message,
    }
