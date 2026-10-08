"""配件主数据、图片上传和索引展示的一致性业务。"""

from __future__ import annotations

import os
from types import ModuleType

from csrcqsf.core.settings import agent_running

def bind_runtime_dependencies(parts_service_module: ModuleType | None = None) -> None:
    """绑定配件兼容门面的数据库、存储和索引依赖。"""
    if parts_service_module is None:
        from csrcqsf.modules.railway_parts.services import parts_service as parts_service_module

    globals().update(
        {
            "datetime": parts_service_module.datetime,
            "os": parts_service_module.os,
            "Path": parts_service_module.Path,
            "re": parts_service_module.re,
            "np": parts_service_module.np,
            "cv2": parts_service_module.cv2,
            "run_sync": parts_service_module.run_sync,
            "get_id": parts_service_module.get_id,
            "SessionLocal": parts_service_module.SessionLocal,
            "Items": parts_service_module.Items,
            "ItemsParent": parts_service_module.ItemsParent,
            "ItemInquiryHistory": parts_service_module.ItemInquiryHistory,
            "InquiryTextIndexDocumentRepository": (
                parts_service_module.InquiryTextIndexDocumentRepository
            ),
            "SgoItemImages": parts_service_module.SgoItemImages,
            "SegmentedImage": parts_service_module.SegmentedImage,
            "SegmentedImageService": parts_service_module.SegmentedImageService,
            "ImageSourceType": parts_service_module.ImageSourceType,
            "SegmentStatus": parts_service_module.SegmentStatus,
            "ListItem": parts_service_module.ListItem,
            "LisItemRes": parts_service_module.LisItemRes,
            "GetItemDetailRes": parts_service_module.GetItemDetailRes,
            "ItemImageIndexInfo": parts_service_module.ItemImageIndexInfo,
            "ItemImageItem": parts_service_module.ItemImageItem,
            "date_to_str": parts_service_module.date_to_str,
            "_get_milvus_state_manager_v2_cls": parts_service_module._get_milvus_state_manager_v2_cls,
            "_get_minio_helpers": parts_service_module._get_minio_helpers,
            "minio_bucket": parts_service_module.minio_bucket,
        }
    )


def _runtime():
    from csrcqsf.modules.railway_parts.services import item_service as item_service_module

    return item_service_module


def _normalize_parent_item_id(parent_item_id: int | None, runtime=None) -> int:
    if parent_item_id is None or parent_item_id <= 0:
        return 0
    return parent_item_id


async def create_item(
    cls,
    item_name: str,
    item_code: str,
    obj_url: str = None,
    height: float = None,
    length: float = None,
    width: float = None,
    weight: float = None,
    parent_item_id: int | None = None,
    runtime=None,
):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        normalized_parent_item_id = cls._normalize_parent_item_id(parent_item_id)
        if normalized_parent_item_id > 0:
            parent_item = await runtime.Items.get_item_by_id(
                session=session,
                item_id=normalized_parent_item_id,
            )
            if parent_item is None:
                raise Exception(f"id为{normalized_parent_item_id}的父配件不存在")

        item = runtime.Items(
            item_name=item_name,
            item_code=item_code,
            parent_item_id=normalized_parent_item_id,
            obj_url=obj_url,
            height=height,
            long=length,
            width=width,
            weight=weight,
            id=runtime.get_id(),
        )
        await runtime.Items.create_item(session=session, item=item)
        await runtime.ItemsParent.replace_parent_relations(
            session=session,
            item_id=item.id,
            parent_item_id=normalized_parent_item_id,
        )
        await session.commit()


async def delete_pic(cls, image_id: int, runtime=None):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        await runtime.SgoItemImages.delete_image(session=session, image_id=image_id)
        await session.commit()


async def delete_item_image(
    cls,
    item_id: int,
    image_id: int,
    delete_reason: str | None = None,
    runtime=None,
) -> dict:
    # 先软删除数据库记录，让检索和列表立即不可见，再尽力清理各类外部产物。
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        image = await runtime.SgoItemImages.get_item_image(
            session,
            item_id=item_id,
            image_id=image_id,
            include_deleted=True,
        )
        if image is None:
            raise Exception(f"配件图片不存在: item_id={item_id}, image_id={image_id}")

        if getattr(image, "is_deleted", 0) == 1:
            return {
                "item_id": str(item_id),
                "image_id": str(image_id),
                "image_url": image.image_url,
                "db_deleted": True,
                "minio_deleted": False,
                "milvus_deleted": False,
                "milvus_delete_count": 0,
                "message": "图片已删除",
            }

        await runtime.SgoItemImages.mark_deleted(
            session,
            item_id=item_id,
            image_id=image_id,
            delete_reason=delete_reason,
        )
        await session.commit()

    image_url = image.image_url
    segmented_error = ""
    try:
        async with runtime.SessionLocal() as session:
            segmented_service = runtime.SegmentedImageService(session)
            await segmented_service.remove_source_artifacts(item_id, image_id)
            await session.commit()
    except Exception as exc:
        segmented_error = str(exc)

    minio_deleted = False
    minio_error = ""
    if image_url:
        try:
            await _delete_minio_object(image_url, runtime=runtime)
            minio_deleted = True
        except Exception as exc:
            minio_error = str(exc)

    milvus_deleted = False
    milvus_delete_count = 0
    milvus_error = ""
    try:
        state_manager = runtime._get_milvus_state_manager_v2_cls()()
        delete_result = state_manager.delete_item_image_index(item_id, image_id)
        state_manager.delete_item_image_patch_tokens(item_id, image_id)
        milvus_delete_count = int(delete_result.get("total_deleted", 0))
        milvus_deleted = True
    except Exception as exc:
        milvus_error = str(exc)

    message = "图片删除成功"
    if segmented_error and minio_error and milvus_error:
        message = "图片已删除，分割产物、MinIO 原图和 Milvus 索引删除失败，请人工检查对象残留并对该配件重新同步索引"
    elif minio_error and milvus_error:
        message = "图片已删除，MinIO 对象和 Milvus 索引删除失败，请人工检查对象残留并对该配件重新同步索引"
    elif segmented_error and minio_error:
        message = "图片已删除，分割产物和 MinIO 原图删除失败，请人工检查对象残留并对该配件重新同步索引"
    elif segmented_error and milvus_error:
        message = "图片已删除，分割产物和 Milvus 索引删除失败，请对该配件重新同步索引"
    elif segmented_error:
        message = "图片已删除，分割产物删除失败，请对该配件重新同步索引"
    elif minio_error:
        message = "图片已删除，MinIO 对象删除失败，请人工检查对象残留"
    elif milvus_error:
        message = "图片已删除，Milvus 索引删除失败，请对该配件重新同步索引"

    return {
        "item_id": str(item_id),
        "image_id": str(image_id),
        "image_url": image_url,
        "db_deleted": True,
        "minio_deleted": minio_deleted,
        "milvus_deleted": milvus_deleted,
        "milvus_delete_count": milvus_delete_count,
        "message": message,
    }


async def delete_item(cls, item_id_list: list[int], runtime=None):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        await runtime.Items.delete_item_by_id_list(
            session=session,
            item_id_list=item_id_list,
        )
        await session.commit()


async def update_item(
    cls,
    item_id: int,
    update_fields: set[str],
    item_name: str | None = None,
    item_code: str | None = None,
    parent_item_id: int | None = None,
    length: float | None = None,
    width: float | None = None,
    height: float | None = None,
    weight: float | None = None,
    runtime=None,
):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        item = await runtime.Items.get_item_by_id(session=session, item_id=item_id)
        if item is None:
            raise Exception(f"id为{item_id}的配件不存在")

        normalized_parent_item_id = cls._normalize_parent_item_id(parent_item_id)

        if "item_name" in update_fields and (item_name is None or str(item_name).strip() == ""):
            raise Exception("配件名称不能为空")

        if "item_code" in update_fields and (item_code is None or str(item_code).strip() == ""):
            raise Exception("物料编码不能为空")

        if "item_code" in update_fields and item.item_code != item_code:
            item_by_code = await runtime.Items.get_item_by_item_code(
                session=session,
                item_code=item_code,
            )
            if item_by_code is not None:
                raise Exception(f"物料编码:{item_code}已经存在了")

        if "parent_item_id" in update_fields and normalized_parent_item_id > 0:
            parent_item = await runtime.Items.get_item_by_id(
                session=session,
                item_id=normalized_parent_item_id,
            )
            if parent_item is None:
                raise Exception(f"id为{normalized_parent_item_id}的父配件不存在")

        values = runtime.Items.build_item_updates(
            fields=update_fields,
            item_name=item_name,
            item_code=item_code,
            parent_item_id=normalized_parent_item_id,
            height=height,
            length=length,
            width=width,
            weight=weight,
        )
        await runtime.Items.update_item_fields(session=session, item_id=item_id, values=values)
        if "parent_item_id" in update_fields:
            await runtime.ItemsParent.replace_parent_relations(
                session=session,
                item_id=item_id,
                parent_item_id=normalized_parent_item_id,
            )
        await session.commit()


async def list_item(cls, req, runtime=None):
    runtime = runtime or _runtime()
    item_code_list = []
    exact_item_code = str(getattr(req, "item_code", "") or "").strip()
    if exact_item_code:
        item_code_list = [exact_item_code]

    async with runtime.SessionLocal() as session:
        item_id_list = []
        if req.parent_item_id != 0:
            data = await runtime.ItemsParent.list_item_by_parent_id(session, req.parent_item_id)
            for row in data:
                item_id_list.append(row.item_id)
        items = await runtime.Items.list_items(
            session=session,
            query=req.query,
            item_name=getattr(req, "item_name", None),
            vehicle_batch=getattr(req, "vehicle_batch", None),
            page=req.page,
            per_page=req.per_page,
            has_images=req.has_images == 1,
            item_id_list=item_id_list,
            item_code_list=item_code_list,
            need_index=False,
            need_v2_index=req.only_has_index == 1,
            has_source_video=req.has_source_video,
            has_inquiry_history=req.has_inquery_code == 1,
        )

        page_item_ids = [item.id for item in items.data]
        inquiry_rows = await runtime.ItemInquiryHistory.list_summary_by_item_ids(
            session,
            page_item_ids,
        )
        inquiry_summary = {
            int(item_id): (inquiry_nums, int(inquiry_count))
            for item_id, inquiry_nums, inquiry_count in inquiry_rows
        }
        features_by_item = (
            await runtime.InquiryTextIndexDocumentRepository.list_features_by_item_ids(
                session,
                page_item_ids,
            )
        )

        images = await cls.list_item_images(page_item_ids)
        images_dict: dict[int, list] = {}
        for image in images:
            images_dict.setdefault(image.item_id, []).append(image)

        res = runtime.LisItemRes(total=items.total)
        for item in items.data:
            inquiry_nums, inquiry_count = inquiry_summary.get(item.id, ([], 0))
            item_images = images_dict.get(item.id, [])
            features = features_by_item.get(item.id, [])
            item_desc = runtime.ListItem(
                item_name=item.item_name,
                item_code=item.item_code,
                vehicle_batch=getattr(item, "vehicle_batch", None),
                ply_url=item.obj_url,
                height=item.height,
                width=item.width,
                length=item.long,
                weight=item.weight,
                video_path=item.source_video_path,
                has_index=1 if item.has_v2_index == 1 else 0,
                has_source_video=1 if item.source_video_path else 0,
                images_total_indexed_num=item.v2_indexed_image_num,
                images_url=[image.image_url for image in item_images],
                features=features,
                features_num=len(features),
                inquiry_nums=inquiry_nums,
                inquiry_count=inquiry_count,
                id=str(item.id),
                created_at=runtime.date_to_str(item.time_created),
            )
            item_desc.images_total_num = len(item_images)
            res.items.append(item_desc)
        return res


async def list_item_images(cls, item_id_list: list[int], runtime=None):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        result = await runtime.SgoItemImages.list_item_images_by_item_id_list(session, item_id_list)
        return list(result) if result else []


async def update_item_size(cls, item_id: int, item_size_str: str, runtime=None):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        await runtime.Items.put_item_size_desc(
            session=session,
            item_id=item_id,
            size_desc=item_size_str,
        )
        await session.commit()


async def get_item_detail(
    cls,
    item_id: int,
    source_inquiry_id: str | None = None,
    source_inquiry_time=None,
    runtime=None,
):
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        item = await runtime.Items.get_item_by_id(session=session, item_id=item_id)
        if item is None:
            raise Exception(f"id为{item_id}的配件不存在")

        images = [
            image
            async for image in runtime.SgoItemImages.get_images(
                session=session,
                item_id=item_id,
            )
        ]
        # 图片只有在两套向量均写入成功后才会标记为已索引，详情页直接读取该持久化状态。
        indexed_image_dict = {
            int(image.id): image.image_url
            for image in images
            if int(image.is_indexed or 0) == 1
        }
        segmented_records = list(await runtime.SegmentedImage.list_by_item_id(session, item_id))
        history_filter = (
            {
                "exclude_inquiry_id": source_inquiry_id,
                "before_inquiry_time": source_inquiry_time,
            }
            if agent_running and source_inquiry_id and source_inquiry_time
            else {}
        )
        features_by_item = (
            await runtime.InquiryTextIndexDocumentRepository.list_features_by_item_ids(
                session,
                [item_id],
                **history_filter,
            )
        )
        segmented_image_dict: dict[int, str | None] = {}
        for record in segmented_records:
            source_image_id = int(record.source_image_id)
            if source_image_id in segmented_image_dict:
                continue
            if record.status == runtime.SegmentStatus.SUCCESS and record.segmented_image_url:
                segmented_image_dict[source_image_id] = record.segmented_image_url
            else:
                segmented_image_dict[source_image_id] = None

        res = runtime.GetItemDetailRes(
            ply_url=item.obj_url,
            id=str(item.id),
            height=item.height,
            width=item.width,
            length=item.long,
            weight=item.weight,
            video_path=item.source_video_path,
            name=item.item_name,
            item_code=item.item_code,
            vehicle_batch=getattr(item, "vehicle_batch", None),
            created_at=runtime.date_to_str(item.time_created),
            updated_at=runtime.date_to_str(item.time_updated),
            size_str=item.size_str,
            features=features_by_item.get(item_id, []),
            features_num=len(features_by_item.get(item_id, [])),
        )
        for image_id, image_url in sorted(indexed_image_dict.items()):
            res.images_index_list.append(
                runtime.ItemImageIndexInfo(
                    image_id=str(image_id),
                    image_url=segmented_image_dict.get(image_id) or image_url,
                )
            )
        for image in images:
            res.images.append(
                runtime.ItemImageItem(
                    image_id=str(image.id),
                    has_indexed=1 if image.id in indexed_image_dict else 0,
                    image_url=image.image_url or indexed_image_dict.get(image.id),
                    source_type=image.image_source,
                )
            )
    return res


def _wake_auto_index_scan(runtime) -> None:
    try:
        runtime.auto_index_scheduler.wake()
    except Exception:
        # 图片事务已经提交；调度通知失败只能影响处理时效，由 30 秒扫描兜底。
        runtime.logger.exception("配件图片已保存，但自动索引扫描器唤醒失败")


async def create_item_image(cls, item_id: int, image_url_list: list[str], runtime=None):
    # 路径登记接口只新增未出现的自主采集图，重复请求保持幂等。
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        item = await runtime.Items.get_item_by_id(session, item_id)
        if item is None:
            raise Exception("配件不存在")

        item_images_result = await runtime.SgoItemImages.list_item_images_by_item_id(
            session,
            item_id=item_id,
        )
        item_images = list(item_images_result) if item_images_result else []
        image_url_set = {image.image_url for image in item_images}

        image_list = []
        for image_url in image_url_list:
            if image_url in image_url_set:
                continue
            image_list.append(
                runtime.SgoItemImages(
                    item_id=item_id,
                    image_url=image_url,
                    image_source=runtime.ImageSourceType.CREATEBYSELF,
                    is_indexed=0,
                )
            )

        if image_list:
            await runtime.SgoItemImages.create_item_images(session, image_list)
            await session.commit()

    if image_list:
        # 自主采集图片提交后立即唤醒统一自动索引调度器，缩短等待下一轮扫描的时间。
        _wake_auto_index_scan(runtime)

    return {
        "item_id": item_id,
        "uploaded_count": len(image_list),
        "records": [
            {
                "image_id": image.id,
                "image_url": image.image_url,
                "filename": runtime.Path(image.image_url).name,
            }
            for image in image_list
        ],
        "message": (
            "配件图片登记成功，等待自动索引"
            if image_list
            else "没有新增配件图片"
        ),
        "auto_index_pending": bool(image_list),
    }


def _safe_upload_filename(filename: str | None, fallback: str = "image.bin", runtime=None) -> str:
    runtime = runtime or _runtime()
    raw_name = runtime.Path(filename or fallback).name
    safe_name = runtime.re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
    return safe_name or fallback


async def _delete_minio_object(object_path: str, runtime=None) -> None:
    runtime = runtime or _runtime()
    _, minio_instance, parse_minio_path = runtime._get_minio_helpers()
    try:
        bucket, object_name = parse_minio_path(
            object_path,
            default_bucket=runtime.minio_bucket,
        )
    except Exception:
        if "/" in object_path:
            bucket, object_name = object_path.split("/", 1)
        else:
            bucket, object_name = runtime.minio_bucket, object_path

    def _delete():
        minio_instance.client.remove_object(bucket, object_name)

    await runtime.run_sync(_delete)


async def create_item_image_files(cls, item_id: int, files: list, runtime=None) -> dict:
    """上传原图并创建待索引记录；数据库失败时回收本次已上传对象。"""
    runtime = runtime or _runtime()
    if len(files) == 0:
        raise Exception("未上传图片文件")

    ensure_minio_bucket, minio_instance, _ = runtime._get_minio_helpers()
    ensure_minio_bucket(runtime.minio_bucket)

    async with runtime.SessionLocal() as session:
        item = await runtime.Items.get_item_by_id(session, item_id)
        if item is None:
            raise Exception("配件不存在")

        uploaded_paths: list[str] = []
        image_rows: list = []
        uploaded_filenames: list[str] = []

        try:
            for file in files:
                safe_name = cls._safe_upload_filename(file.filename, fallback="image.jpg")
                date_dir = runtime.datetime.now().strftime("%Y%m%d")
                object_name = f"manual-upload/{item_id}/{date_dir}/{runtime.get_id()}_{safe_name}"
                content_type = file.content_type or "application/octet-stream"

                def _upload() -> int:
                    file.file.seek(0, os.SEEK_END)
                    size = file.file.tell()
                    file.file.seek(0)
                    minio_instance.client.put_object(
                        runtime.minio_bucket,
                        object_name,
                        file.file,
                        length=size,
                        content_type=content_type,
                    )
                    return size

                await runtime.run_sync(_upload)
                await file.close()

                image_url = f"{runtime.minio_bucket}/{object_name}"
                uploaded_paths.append(image_url)
                uploaded_filenames.append(safe_name)
                image_rows.append(
                    runtime.SgoItemImages(
                        item_id=item_id,
                        image_url=image_url,
                        raw_url=None,
                        image_source=runtime.ImageSourceType.CREATEBYSELF,
                        is_indexed=0,
                    )
                )

            await runtime.SgoItemImages.create_item_images(session, image_rows)
            await session.commit()
        except Exception:
            await session.rollback()
            for image_url in uploaded_paths:
                try:
                    await cls._delete_minio_object(image_url)
                except Exception:
                    pass
            raise

    if image_rows:
        # 文件与图片记录均已提交后再通知扫描器，索引失败不会回滚上传结果。
        _wake_auto_index_scan(runtime)

    return {
        "item_id": item_id,
        "uploaded_count": len(image_rows),
        "records": [
            {
                "image_id": image.id,
                "image_url": image.image_url,
                "filename": filename,
            }
            for image, filename in zip(image_rows, uploaded_filenames)
        ],
        "message": "配件图片上传成功，等待自动索引",
        "auto_index_pending": bool(image_rows),
    }


async def get_image_from_oss(cls, image_url: str, runtime=None):
    runtime = runtime or _runtime()
    _, minio_instance, parse_minio_path = runtime._get_minio_helpers()

    def _load():
        # CREATEBYSELF 图片位于 manual-upload 多级目录，读取时必须保留完整对象路径。
        bucket, object_name = parse_minio_path(
            image_url,
            default_bucket=runtime.minio_bucket,
        )
        response = None
        try:
            response = minio_instance.client.get_object(bucket, object_name)
            if response.status != 200:
                raise Exception("oss请求出错")

            if response.data:
                nparr = runtime.np.frombuffer(response.data, runtime.np.uint8)
                image = runtime.cv2.imdecode(nparr, runtime.cv2.IMREAD_COLOR)
                try:
                    return cls.resize_image(image)
                except Exception:
                    return image
            return None
        finally:
            if response:
                response.close()
                response.release_conn()

    return await runtime.run_sync(_load)


def resize_image(cls, image, max_size=1920, runtime=None):
    runtime = runtime or _runtime()
    height, width = image.shape[:2]
    if max(height, width) > max_size:
        scale = max_size / max(height, width)
        new_height = int(height * scale)
        new_width = int(width * scale)
        image = runtime.cv2.resize(
            image,
            (new_width, new_height),
            interpolation=runtime.cv2.INTER_AREA,
        )
    return image
