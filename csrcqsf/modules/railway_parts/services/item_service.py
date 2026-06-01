from __future__ import annotations

import os
import re
from pathlib import Path
from types import ModuleType


def bind_runtime_dependencies(parts_service_module: ModuleType | None = None) -> None:
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
            "sgo_sessionLocal": parts_service_module.sgo_sessionLocal,
            "Items": parts_service_module.Items,
            "ItemsParent": parts_service_module.ItemsParent,
            "SgoCodeInquiryReturn": parts_service_module.SgoCodeInquiryReturn,
            "SgoItemImages": parts_service_module.SgoItemImages,
            "SegmentedImage": parts_service_module.SegmentedImage,
            "ImageSourceType": parts_service_module.ImageSourceType,
            "SegmentStatus": parts_service_module.SegmentStatus,
            "ListItem": parts_service_module.ListItem,
            "LisItemRes": parts_service_module.LisItemRes,
            "GetItemDetailRes": parts_service_module.GetItemDetailRes,
            "ItemImageIndexInfo": parts_service_module.ItemImageIndexInfo,
            "ItemImageItem": parts_service_module.ItemImageItem,
            "date_to_str": parts_service_module.date_to_str,
            "select": parts_service_module.select,
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
    if req.has_inquery_code == 1:
        async with runtime.sgo_sessionLocal() as session:
            stmt = runtime.select(runtime.SgoCodeInquiryReturn.item_code.distinct())
            data = await session.scalars(stmt)
            item_code_list = list(data.all())

    async with runtime.SessionLocal() as session:
        item_id_list = []
        if req.parent_item_id != 0:
            data = await runtime.ItemsParent.list_item_by_parent_id(session, req.parent_item_id)
            for row in data:
                item_id_list.append(row.item_id)
        items = await runtime.Items.list_items(
            session=session,
            query=req.query,
            page=req.page,
            per_page=req.per_page,
            has_images=req.has_images == 1,
            item_id_list=item_id_list,
            item_code_list=item_code_list,
            need_index=False,
            need_v2_index=req.only_has_index == 1,
            has_source_video=req.has_source_video,
        )

        state_manager = runtime._get_milvus_state_manager_v2_cls()()
        index_dict = state_manager.list_item_index([item.id for item in items.data])
        images = await cls.list_item_images([item.id for item in items.data])
        images_dict: dict[int, list] = {}
        for image in images:
            images_dict.setdefault(image.item_id, []).append(image)

        res = runtime.LisItemRes(total=items.total)
        for item in items.data:
            item_desc = runtime.ListItem(
                item_name=item.item_name,
                item_code=item.item_code,
                ply_url=item.obj_url,
                height=item.height,
                width=item.width,
                length=item.long,
                weight=item.weight,
                video_path=item.source_video_path,
                has_index=1 if item.has_v2_index == 1 else 0,
                has_source_video=1 if item.source_video_path else 0,
                images_total_indexed_num=item.v2_indexed_image_num,
                id=str(item.id),
                created_at=runtime.date_to_str(item.time_created),
            )
            if item.id in images_dict:
                item_desc.images_total_num = len(images_dict[item.id])

            index = index_dict.get(item.id)
            if index is not None:
                item_desc.features = [feature.feature for feature in index.features]
                item_desc.features_num = len(index.features)
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


async def get_item_detail(cls, item_id: int, runtime=None):
    runtime = runtime or _runtime()
    state_manager = runtime._get_milvus_state_manager_v2_cls()()
    index_detail = state_manager.list_item_index([item_id])
    indexed_image_dict = state_manager.get_indexed_images_by_item_id(item_id)

    async with runtime.SessionLocal() as session:
        item = await runtime.Items.get_item_by_id(session=session, item_id=item_id)
        if item is None:
            raise Exception(f"id为{item_id}的配件不存在")

        images = runtime.SgoItemImages.get_images(session=session, item_id=item_id)
        segmented_records = list(await runtime.SegmentedImage.list_by_item_id(session, item_id))
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
            created_at=runtime.date_to_str(item.time_created),
            updated_at=runtime.date_to_str(item.time_updated),
            size_str=item.size_str,
        )
        if index_detail.get(item_id) is not None:
            for feature in index_detail.get(item_id).features:
                res.features.append(feature.feature)
        for image_id, image_url in sorted(indexed_image_dict.items()):
            res.images_index_list.append(
                runtime.ItemImageIndexInfo(
                    image_id=str(image_id),
                    image_url=segmented_image_dict.get(image_id) or image_url,
                )
            )
        async for image in images:
            res.images.append(
                runtime.ItemImageItem(
                    image_id=str(image.id),
                    has_indexed=1 if image.id in indexed_image_dict else 0,
                    image_url=image.image_url or indexed_image_dict.get(image.id),
                    source_type=image.image_source,
                )
            )
    return res


async def create_item_image(cls, item_id: int, image_url_list: list[str], runtime=None):
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
                    is_indexed=1,
                )
            )

        if image_list:
            await runtime.SgoItemImages.create_item_images(session, image_list)
            await session.commit()

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
        "message": "配件图片登记成功",
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
                        is_indexed=1,
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
        "message": "配件图片上传成功",
    }


async def get_image_from_oss(cls, image_url: str, runtime=None):
    runtime = runtime or _runtime()
    _, minio_instance, _ = runtime._get_minio_helpers()

    def _load():
        file_name_arr = image_url.split("/")
        if len(file_name_arr) < 2:
            raise Exception("文件名格式不正确")

        aim_file_name = file_name_arr[1]
        response = None
        try:
            response = minio_instance.client.get_object(runtime.minio_bucket, aim_file_name)
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
