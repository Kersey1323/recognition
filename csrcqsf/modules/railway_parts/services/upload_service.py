from __future__ import annotations


def _runtime():
    from csrcqsf.modules.railway_parts.services import reconstruction_video_service

    return reconstruction_video_service


async def _init_remote_source_video_upload(
    cls,
    item_id: int,
    file_name: str,
    file_size: int,
    content_type: str,
    height: float | None = None,
    length: float | None = None,
    width: float | None = None,
    weight: float | None = None,
    runtime=None,
) -> dict:
    runtime = runtime or _runtime()
    object_name = cls._build_source_video_multipart_object_name(item_id=item_id, file_name=file_name)
    video_path = f"{runtime.minio_reconstruction_video_bucket}/{object_name}"
    safe_name = cls._safe_filename(file_name)
    part_size = cls._choose_multipart_part_size(file_size)
    total_parts = max(1, runtime.math.ceil(file_size / part_size))

    async with runtime.SessionLocal() as session:
        active_session = await runtime.ReconstructionVideoUploadSession.get_active_by_item_id(session, item_id)
        if active_session is not None:
            raise runtime.ReconstructionBusinessError(
                f"该配件已存在未完成的上传会话: upload_session_id={active_session.id}"
            )

        upload_id = await cls._create_multipart_upload(
            bucket=runtime.minio_reconstruction_video_bucket,
            object_name=object_name,
            content_type=content_type,
        )

        try:
            upload_session = await runtime.ReconstructionVideoUploadSession.create_session(
                session,
                runtime.ReconstructionVideoUploadSession(
                    item_id=item_id,
                    bucket=runtime.minio_reconstruction_video_bucket,
                    object_name=object_name,
                    video_path=video_path,
                    upload_id=upload_id,
                    file_name=safe_name,
                    file_size=file_size,
                    content_type=content_type or "application/octet-stream",
                    part_size=part_size,
                    total_parts=total_parts,
                    height=height,
                    length=length,
                    width=width,
                    weight=weight,
                    status="initiated",
                    storage_mode="remote",
                    local_status="initiated",
                    remote_status="pending",
                    expires_at=runtime.datetime.utcnow() + runtime.timedelta(days=7),
                ),
            )
            upload_urls = await cls._generate_multipart_upload_urls(
                bucket=runtime.minio_reconstruction_video_bucket,
                object_name=object_name,
                upload_id=upload_id,
                part_numbers=list(range(1, total_parts + 1)),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            await cls._abort_multipart_upload(
                bucket=runtime.minio_reconstruction_video_bucket,
                object_name=object_name,
                upload_id=upload_id,
            )
            raise

    return cls._build_upload_session_payload(upload_session, upload_urls=upload_urls)


async def _init_local_source_video_upload(
    cls,
    item_id: int,
    file_name: str,
    file_size: int,
    content_type: str,
    height: float | None = None,
    length: float | None = None,
    width: float | None = None,
    weight: float | None = None,
    runtime=None,
) -> dict:
    runtime = runtime or _runtime()
    object_name = cls._build_source_video_multipart_object_name(item_id=item_id, file_name=file_name)
    video_path = f"{runtime.minio_reconstruction_video_bucket}/{object_name}"
    safe_name = cls._safe_filename(file_name)
    part_size = cls._choose_multipart_part_size(file_size)
    total_parts = max(1, runtime.math.ceil(file_size / part_size))
    storage = cls._get_local_upload_storage()

    async with runtime.SessionLocal() as session:
        active_session = await runtime.ReconstructionVideoUploadSession.get_active_by_item_id(session, item_id)
        if active_session is not None:
            raise runtime.ReconstructionBusinessError(
                f"该配件已存在未完成的上传会话: upload_session_id={active_session.id}"
            )

        upload_session = await runtime.ReconstructionVideoUploadSession.create_session(
            session,
            runtime.ReconstructionVideoUploadSession(
                item_id=item_id,
                bucket=runtime.minio_reconstruction_video_bucket,
                object_name=object_name,
                video_path=video_path,
                upload_id=str(runtime.get_id()),
                file_name=safe_name,
                file_size=file_size,
                content_type=content_type or "application/octet-stream",
                part_size=part_size,
                total_parts=total_parts,
                height=height,
                length=length,
                width=width,
                weight=weight,
                status="initiated",
                storage_mode="local",
                local_status="initiated",
                remote_status="pending",
                remote_object_name=object_name,
                remote_video_path=video_path,
                expires_at=runtime.datetime.utcnow() + runtime.timedelta(days=7),
            ),
        )

        session_dir = storage.ensure_session_dirs(upload_session.id)
        storage.save_meta(
            session_dir,
            {
                "upload_session_id": upload_session.id,
                "file_name": safe_name,
                "file_size": file_size,
                "part_size": part_size,
                "total_parts": total_parts,
                "uploaded_parts": [],
                "storage_mode": "local",
                "local_status": "initiated",
                "remote_status": "pending",
                "last_sync_error": None,
            },
        )
        upload_session.local_dir = str(session_dir)
        await session.flush()
        await session.commit()

    return cls._build_local_upload_init_payload(upload_session)


async def upload_source_video_local_part(
    cls,
    upload_session_id: int,
    part_number: int,
    file,
    runtime=None,
) -> dict:
    runtime = runtime or _runtime()
    upload_session = await cls._require_upload_session(upload_session_id)
    if upload_session.storage_mode != "local":
        raise runtime.ReconstructionBusinessError("当前上传会话不是本地分片模式")
    if part_number < 1 or part_number > int(upload_session.total_parts):
        raise runtime.ReconstructionBusinessError(f"分片编号超出范围: {part_number}")

    data = await file.read()
    await file.close()
    if not data:
        raise runtime.ReconstructionBusinessError("上传分片内容不能为空")
    expected_part_size = cls._expected_local_part_size(upload_session, part_number)
    if len(data) != expected_part_size:
        runtime.logger.warning(
            "本地上传分片大小与预期不一致: upload_session_id=%s, part_number=%s, expected=%s, actual=%s",
            upload_session_id,
            part_number,
            expected_part_size,
            len(data),
        )

    storage = cls._get_local_upload_storage()
    session_dir = (
        runtime.Path(upload_session.local_dir)
        if upload_session.local_dir
        else storage.ensure_session_dirs(upload_session.id)
    )
    storage.ensure_session_dirs(upload_session.id)
    storage.write_part(session_dir, part_number, data)

    async with runtime.SessionLocal() as session:
        await runtime.ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            local_status="uploading",
            local_dir=str(session_dir),
        )
        await session.commit()

    return {
        "upload_session_id": upload_session.id,
        "part_number": part_number,
        "size": len(data),
        "message": "分片上传成功",
    }


async def init_source_video_multipart_upload(
    cls,
    item_id: int,
    file_name: str,
    file_size: int,
    content_type: str,
    storage_mode: str = "remote",
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
    normalized_storage_mode = (storage_mode or "remote").strip().lower()
    if normalized_storage_mode == "local":
        return await cls._init_local_source_video_upload(
            item_id=item_id,
            file_name=file_name,
            file_size=file_size,
            content_type=content_type,
            height=height,
            length=length,
            width=width,
            weight=weight,
        )
    return await cls._init_remote_source_video_upload(
        item_id=item_id,
        file_name=file_name,
        file_size=file_size,
        content_type=content_type,
        height=height,
        length=length,
        width=width,
        weight=weight,
    )


async def get_source_video_upload_progress(cls, upload_session_id: int, runtime=None) -> dict:
    runtime = runtime or _runtime()
    upload_session = await cls._require_upload_session(upload_session_id)
    if upload_session.storage_mode == "local":
        storage = cls._get_local_upload_storage()
        session_dir = (
            runtime.Path(upload_session.local_dir)
            if upload_session.local_dir
            else storage.get_session_dir(upload_session.id)
        )
        if not session_dir.exists():
            raise runtime.ReconstructionBusinessError(
                f"本地上传会话目录不存在: upload_session_id={upload_session.id}"
            )
        meta = storage.load_meta(session_dir)
        uploaded_parts = []
        for part_number in meta.get("uploaded_parts", []):
            part_path = session_dir / "parts" / f"part-{int(part_number):05d}"
            uploaded_parts.append(
                {
                    "part_number": int(part_number),
                    "size": part_path.stat().st_size if part_path.exists() else None,
                    "etag": "",
                }
            )
        payload = cls._build_upload_session_payload(upload_session)
        payload["uploaded_parts"] = uploaded_parts
        return payload

    uploaded_parts = await cls._list_multipart_uploaded_parts(
        bucket=upload_session.bucket,
        object_name=upload_session.object_name,
        upload_id=upload_session.upload_id,
    )
    payload = cls._build_upload_session_payload(upload_session)
    payload["uploaded_parts"] = uploaded_parts
    return payload


async def get_source_video_upload_urls(
    cls,
    upload_session_id: int,
    part_numbers: list[int],
    runtime=None,
) -> dict:
    runtime = runtime or _runtime()
    upload_session = await cls._require_upload_session(upload_session_id)
    normalized_part_numbers = cls._validate_part_numbers(part_numbers, upload_session.total_parts)
    if upload_session.storage_mode == "local":
        return {
            "upload_session_id": upload_session.id,
            "upload_urls": [
                {
                    "part_number": part_number,
                    "url": "/railway/parts/v2/reconstruct/video/upload/part",
                    "expires_at": None,
                }
                for part_number in normalized_part_numbers
            ],
        }
    upload_urls = await cls._generate_multipart_upload_urls(
        bucket=upload_session.bucket,
        object_name=upload_session.object_name,
        upload_id=upload_session.upload_id,
        part_numbers=normalized_part_numbers,
    )
    return {
        "upload_session_id": upload_session.id,
        "upload_urls": upload_urls,
    }


async def complete_source_video_multipart_upload(cls, upload_session_id: int, runtime=None) -> dict:
    runtime = runtime or _runtime()
    upload_session = await cls._require_upload_session(upload_session_id)
    if upload_session.storage_mode == "local":
        return await cls._complete_local_source_video_upload(upload_session)

    uploaded_parts = await cls._list_multipart_uploaded_parts(
        bucket=upload_session.bucket,
        object_name=upload_session.object_name,
        upload_id=upload_session.upload_id,
    )
    await cls._complete_multipart_upload(
        bucket=upload_session.bucket,
        object_name=upload_session.object_name,
        upload_id=upload_session.upload_id,
        parts=uploaded_parts,
        total_parts=upload_session.total_parts,
    )

    async with runtime.SessionLocal() as session:
        try:
            current_session = await runtime.ReconstructionVideoUploadSession.get_by_id(
                session,
                upload_session_id,
            )
            if current_session is None:
                raise runtime.ReconstructionBusinessError(
                    f"上传会话不存在: upload_session_id={upload_session_id}"
                )

            now = runtime.datetime.now()
            await runtime.Items.update_source_video(
                session=session,
                item_id=current_session.item_id,
                video_path=current_session.video_path,
                filename=current_session.file_name,
                size=current_session.file_size,
                content_type=current_session.content_type,
                height=current_session.height,
                length=current_session.length,
                width=current_session.width,
                weight=current_session.weight,
                updated_at=now,
            )
            await runtime.ReconstructionVideoUploadSession.mark_completed(
                session=session,
                session_id=current_session.id,
                completed_at=now,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            await cls._delete_minio_object(upload_session.video_path)
            raise

        item = await runtime.Items.get_item_by_id(session, upload_session.item_id)

    return cls._format_source_video_item(item, message="原始视频上传成功")


async def abort_source_video_multipart_upload(cls, upload_session_id: int, runtime=None) -> dict:
    runtime = runtime or _runtime()
    upload_session = await cls._require_upload_session(upload_session_id)
    if upload_session.storage_mode == "local":
        return await cls._abort_local_source_video_upload(upload_session)

    await cls._abort_multipart_upload(
        bucket=upload_session.bucket,
        object_name=upload_session.object_name,
        upload_id=upload_session.upload_id,
    )

    async with runtime.SessionLocal() as session:
        await runtime.ReconstructionVideoUploadSession.mark_aborted(session, upload_session_id)
        await session.commit()

    return {
        "item_id": upload_session.item_id,
        "message": "原始视频分片上传已取消",
    }


async def _complete_local_source_video_upload(cls, upload_session, runtime=None) -> dict:
    runtime = runtime or _runtime()
    storage = cls._get_local_upload_storage()
    session_dir = (
        runtime.Path(upload_session.local_dir)
        if upload_session.local_dir
        else storage.get_session_dir(upload_session.id)
    )
    if not session_dir.exists():
        raise runtime.ReconstructionBusinessError(
            f"本地上传会话目录不存在: upload_session_id={upload_session.id}"
        )

    meta = storage.load_meta(session_dir)
    uploaded_parts = {int(part_number) for part_number in meta.get("uploaded_parts", [])}
    expected_parts = set(range(1, int(upload_session.total_parts) + 1))
    missing_parts = sorted(expected_parts - uploaded_parts)
    if missing_parts:
        raise runtime.ReconstructionBusinessError(f"仍有分片未上传: {missing_parts}")

    merged_path = storage.merge_parts(
        session_dir=session_dir,
        total_parts=int(upload_session.total_parts),
        output_file_name=upload_session.file_name,
    )
    meta["local_status"] = "completed"
    meta["remote_status"] = "pending"
    storage.save_meta(session_dir, meta)

    async with runtime.SessionLocal() as session:
        await runtime.ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            status="completed",
            local_status="completed",
            remote_status="pending",
            merged_file_path=str(merged_path),
            local_dir=str(session_dir),
            completed_at=runtime.datetime.now(),
        )
        await session.commit()
        item = await runtime.Items.get_item_by_id(session, upload_session.item_id)

    return cls._format_source_video_item(item, message="本地分片合并完成，等待 MinIO 同步")


async def _abort_local_source_video_upload(cls, upload_session, runtime=None) -> dict:
    runtime = runtime or _runtime()
    storage = cls._get_local_upload_storage()
    session_dir = (
        runtime.Path(upload_session.local_dir)
        if upload_session.local_dir
        else storage.get_session_dir(upload_session.id)
    )
    storage.delete_session(session_dir)

    async with runtime.SessionLocal() as session:
        await runtime.ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            status="aborted",
            local_status="aborted",
        )
        await session.commit()

    return {
        "item_id": upload_session.item_id,
        "message": "本地分片上传已取消",
    }


async def _minio_health_check(cls, runtime=None) -> bool:
    runtime = runtime or _runtime()
    ensure_minio_bucket, _, _, _, _ = runtime._get_minio_helpers()

    def _check() -> bool:
        ensure_minio_bucket(runtime.minio_reconstruction_video_bucket)
        return True

    try:
        return await runtime.run_sync(_check)
    except Exception:
        return False


async def _sync_local_session_to_remote(cls, upload_session, session, runtime=None) -> bool:
    runtime = runtime or _runtime()
    merged_file_path = getattr(upload_session, "merged_file_path", None)
    if not merged_file_path or not runtime.Path(merged_file_path).exists():
        await runtime.ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            remote_status="failed",
            last_sync_error="merged file missing",
            sync_attempts=int(getattr(upload_session, "sync_attempts", 0) or 0) + 1,
        )
        return False

    remote_object_name = getattr(upload_session, "remote_object_name", None) or upload_session.object_name
    remote_video_path = getattr(upload_session, "remote_video_path", None) or upload_session.video_path
    remote_upload_id = getattr(upload_session, "remote_upload_id", None)
    if not remote_upload_id:
        remote_upload_id = await cls._create_multipart_upload(
            bucket=upload_session.bucket,
            object_name=remote_object_name,
            content_type=upload_session.content_type or "application/octet-stream",
        )
        await runtime.ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            remote_status="syncing",
            remote_upload_id=remote_upload_id,
        )

    try:
        reader = runtime.LocalFilePartReader(merged_file_path, int(upload_session.part_size))
        uploaded_parts = await cls._list_multipart_uploaded_parts(
            bucket=upload_session.bucket,
            object_name=remote_object_name,
            upload_id=remote_upload_id,
        )
        uploaded_part_numbers = {int(part["part_number"]) for part in uploaded_parts}
        part_etags = {
            int(part["part_number"]): str(part["etag"]).strip().strip('"')
            for part in uploaded_parts
        }

        for part in reader.list_parts():
            if part.part_number in uploaded_part_numbers:
                continue
            etag = await cls._upload_multipart_part_bytes(
                bucket=upload_session.bucket,
                object_name=remote_object_name,
                upload_id=remote_upload_id,
                part_number=part.part_number,
                data=reader.read_part(part),
            )
            part_etags[part.part_number] = etag

        await cls._complete_multipart_upload(
            bucket=upload_session.bucket,
            object_name=remote_object_name,
            upload_id=remote_upload_id,
            parts=[
                {"part_number": part_number, "etag": etag}
                for part_number, etag in sorted(part_etags.items())
            ],
            total_parts=int(upload_session.total_parts),
        )

        now = runtime.datetime.now()
        await runtime.Items.update_source_video(
            session=session,
            item_id=upload_session.item_id,
            video_path=remote_video_path,
            filename=upload_session.file_name,
            size=upload_session.file_size,
            content_type=upload_session.content_type,
            height=upload_session.height,
            length=upload_session.length,
            width=upload_session.width,
            weight=upload_session.weight,
            updated_at=now,
        )
        await runtime.ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            remote_status="completed",
            remote_upload_id=remote_upload_id,
            remote_object_name=remote_object_name,
            remote_video_path=remote_video_path,
            synced_at=now,
            last_sync_error=None,
        )
        return True
    except Exception as exc:
        await runtime.ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            remote_status="failed",
            remote_upload_id=remote_upload_id,
            last_sync_error=str(exc),
            sync_attempts=int(getattr(upload_session, "sync_attempts", 0) or 0) + 1,
        )
        return False


async def check_minio_and_sync_local_uploads(cls, runtime=None) -> dict:
    runtime = runtime or _runtime()
    if not runtime.minio_env_configured():
        return {
            "available": False,
            "message": "未显式配置 MinIO 环境变量",
            "total_pending": 0,
            "synced_count": 0,
            "failed_count": 0,
        }

    if not await cls._minio_health_check():
        return {
            "available": False,
            "message": "MinIO 不可用",
            "total_pending": 0,
            "synced_count": 0,
            "failed_count": 0,
        }

    synced_count = 0
    failed_count = 0
    async with runtime.SessionLocal() as session:
        pending_sessions = await runtime.ReconstructionVideoUploadSession.list_local_sessions_pending_remote_sync(session)
        for upload_session in pending_sessions:
            ok = await cls._sync_local_session_to_remote(upload_session, session)
            if ok:
                synced_count += 1
            else:
                failed_count += 1
        await session.commit()

    return {
        "available": True,
        "message": "MinIO 可用，同步完成",
        "total_pending": synced_count + failed_count,
        "synced_count": synced_count,
        "failed_count": failed_count,
    }
