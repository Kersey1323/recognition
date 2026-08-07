from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING, Any, Callable, TypeAlias

if TYPE_CHECKING:
    from csrcqsf.modules.railway_parts.integrations.milvus_state_manager import (
        ImageIndex as ImageIndexType,
    )
else:
    ImageIndexType: TypeAlias = Any


def bind_runtime_dependencies(parts_service_module: ModuleType | None = None) -> None:
    if parts_service_module is None:
        from csrcqsf.modules.railway_parts.services import parts_service as parts_service_module

    globals().update(
        {
            "datetime": parts_service_module.datetime,
            "os": parts_service_module.os,
            "Path": parts_service_module.Path,
            "run_sync": parts_service_module.run_sync,
            "get_id": parts_service_module.get_id,
            "logger": parts_service_module.logger,
            "SessionLocal": parts_service_module.SessionLocal,
            "Items": parts_service_module.Items,
            "SgoItemImages": parts_service_module.SgoItemImages,
            "SegmentedImage": parts_service_module.SegmentedImage,
            "SegmentStatus": parts_service_module.SegmentStatus,
            "MilvusManager": parts_service_module.MilvusManager,
            "ImageIndex": parts_service_module.ImageIndex,
            "IndexStatisticsRes": parts_service_module.IndexStatisticsRes,
            "async_get_count": parts_service_module.async_get_count,
            "select": parts_service_module.select,
            "date_to_str": parts_service_module.date_to_str,
            "_get_milvus_manager_v2_cls": parts_service_module._get_milvus_manager_v2_cls,
            "_get_milvus_state_manager_v2_cls": parts_service_module._get_milvus_state_manager_v2_cls,
            "_get_minio_helpers": parts_service_module._get_minio_helpers,
            "minio_bucket": parts_service_module.minio_bucket,
            "temp_dir": parts_service_module.temp_dir,
        }
    )


def _runtime():
    from csrcqsf.modules.railway_parts.services import parts_index_service as parts_index_service_module

    return parts_index_service_module


async def delete_item_image_index(cls, item_id: int, image_url_list: list[str], runtime=None):
    runtime = runtime or _runtime()
    now_index_list = await runtime.MilvusManager.list_item_index([item_id])
    if item_id not in now_index_list:
        raise Exception("特征数据库并没有该配件的索引信息")

    index = now_index_list[item_id]
    image_url_set = set(image_url_list)
    new_image_index_list: list[ImageIndexType] = []
    for image_index in index.images:
        if image_index.filename not in image_url_set:
            new_image_index_list.append(image_index)

    index.images = new_image_index_list
    if len(index.images) > 0:
        await runtime.MilvusManager.upsert_data(index)
        async with runtime.SessionLocal() as session:
            await runtime.Items.update_items_index(
                session=session,
                item_id=item_id,
                image_index_num=len(index.images),
                feature_index_num=len(index.features),
            )
            await session.commit()
    else:
        await runtime.MilvusManager.delete_part_index(item_id)
        async with runtime.SessionLocal() as session:
            await runtime.Items.update_items_index(
                session=session,
                item_id=item_id,
                image_index_num=0,
                feature_index_num=0,
            )
            await session.commit()


async def _upload_v2_segmented_image(cls, image, item_id: int, source_image_id: int, runtime=None) -> str:
    runtime = runtime or _runtime()
    ensure_minio_bucket, minio_instance, _ = runtime._get_minio_helpers()
    ensure_minio_bucket(runtime.minio_bucket)
    runtime.Path(runtime.temp_dir).mkdir(parents=True, exist_ok=True)

    token = runtime.get_id()
    object_name = f"v2-segmented/{item_id}/{source_image_id}_{token}.jpg"
    local_path = runtime.os.path.join(runtime.temp_dir, f"v2_segmented_{token}.jpg")
    try:
        rgb_image = image.convert("RGB")
        await runtime.run_sync(rgb_image.save, local_path, "JPEG")
        await runtime.run_sync(
            minio_instance.upload_file,
            runtime.minio_bucket,
            object_name,
            local_path,
            "image/jpeg",
        )
        return f"{runtime.minio_bucket}/{object_name}"
    finally:
        if runtime.os.path.exists(local_path):
            runtime.os.remove(local_path)


async def statistics(cls, runtime=None):
    runtime = runtime or _runtime()
    res = runtime.IndexStatisticsRes()
    async with runtime.SessionLocal() as session:
        res.total_item_num = await runtime.async_get_count(session, runtime.select(runtime.Items))

    state_manager = runtime._get_milvus_state_manager_v2_cls()()
    snapshot = state_manager.get_statistics_snapshot()
    item_state_snapshot = state_manager.get_item_index_state_snapshot()

    res.total_image_index = int(snapshot.get("siglip_count", 0) or 0)
    res.total_feature_index = int(snapshot.get("dinov2_count", 0) or 0)
    res.total_index = res.total_image_index + res.total_feature_index
    res.total_indexed_item_num = sum(
        1
        for item_state in item_state_snapshot.values()
        if int(item_state.get("has_v2_index", 0) or 0) == 1
    )
    res.recognition_number = 0
    res.corrrect_recognition_number = 0
    res.recognition_ration = 0
    return res


async def create_v2_collections(cls, drop_existing: bool = False, runtime=None):
    runtime = runtime or _runtime()
    manager = runtime._get_milvus_state_manager_v2_cls()()
    if drop_existing:
        runtime.logger.warning("删除已存在的集合...")
        await runtime.run_sync(manager.drop_collections)
        runtime.logger.info("已存在的集合已删除")
    await runtime.run_sync(manager.create_collections)
    runtime.logger.info("V2 collections created successfully")


async def rebuild_v2_index(
    cls,
    item_id: int = None,
    limit: int = None,
    rebuild_existing: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    runtime=None,
):
    runtime = runtime or _runtime()
    manager = runtime._get_milvus_manager_v2_cls()()
    state_manager = runtime._get_milvus_state_manager_v2_cls()()

    async with runtime.SessionLocal() as session:
        if item_id:
            items = [await runtime.Items.get_item_by_id(session, item_id)]
            if items[0] is None:
                raise Exception(f"配件不存在: {item_id}")
        else:
            item_id_stmt = runtime.select(runtime.SgoItemImages.item_id).where(
                runtime.SgoItemImages.is_deleted == 0
            ).distinct()
            stmt = runtime.select(runtime.Items).where(runtime.Items.id.in_(item_id_stmt))
            if not rebuild_existing:
                stmt = stmt.where(runtime.Items.has_v2_index == 0)
            stmt = stmt.order_by(runtime.Items.time_created.desc()).order_by(runtime.Items.id.desc())
            if limit is not None:
                stmt = stmt.limit(limit)
            items = list(await session.scalars(stmt))

        runtime.logger.info(f"开始为 {len(items)} 个配件建立 V2 索引")
        success_count = 0
        fail_count = 0
        processed_item_count = 0
        skipped_existing_count = 0

        from tqdm import tqdm

        total_items = len(items)
        progress_bar = tqdm(items)

        def report_progress(
            processed_items: int,
            current_item_id: int | None,
            estimated_remaining_seconds: int | None,
        ) -> None:
            if progress_callback is None:
                return
            progress = int(processed_items * 100 / total_items) if total_items else 100
            # 索引进度按配件统计；图片成功/失败数展示当前实际处理结果。
            progress_callback(
                {
                    "progress": progress,
                    "total_items": total_items,
                    "processed_items": processed_items,
                    "success_count": success_count,
                    "fail_count": fail_count,
                    "current_item_id": current_item_id,
                    "estimated_remaining_seconds": estimated_remaining_seconds,
                }
            )

        report_progress(0, None, None)
        for position, item in enumerate(progress_bar, start=1):
            processed_for_progress = position - 1
            elapsed = float(progress_bar.format_dict.get("elapsed") or 0)
            rate = progress_bar.format_dict.get("rate")
            estimated_remaining_seconds = None
            if rate is not None and rate > 0:
                estimated_remaining_seconds = max(
                    0,
                    round((total_items - processed_for_progress) / rate),
                )
            elif processed_for_progress > 0:
                average_seconds = elapsed / processed_for_progress
                estimated_remaining_seconds = max(
                    0,
                    round(average_seconds * (total_items - processed_for_progress)),
                )
            report_progress(
                processed_for_progress,
                item.id if item is not None else None,
                estimated_remaining_seconds,
            )
            if item is None:
                continue
            if not rebuild_existing and getattr(item, "has_v2_index", 0) == 1:
                skipped_existing_count += 1
                runtime.logger.info(f"跳过已存在索引的配件: item={item.id}")
                continue

            try:
                images_result = await runtime.SgoItemImages.list_item_images_by_item_id(session, item.id)
                images = list(images_result) if images_result else []
                item_success_count = 0
                success_image_ids: list[int] = []
                segmented_records_to_create: list = []
                deleted_existing = False
                image_status_changed = False

                if len(images) == 0:
                    runtime.logger.warning(f"配件 {item.id} 没有图片，跳过")
                    continue

                if rebuild_existing and getattr(item, "has_v2_index", 0) == 1:
                    delete_result = state_manager.delete_item_index(item.id)
                    await runtime.SgoItemImages.un_indexed_image(
                        session=session,
                        image_id_list=[img.id for img in images],
                    )
                    await runtime.SegmentedImage.delete_by_item_id(session, item.id)
                    deleted_existing = True
                    image_status_changed = True
                    runtime.logger.info(
                        "强制重建前已删除旧索引: item=%s, siglip=%s, dinov2=%s",
                        item.id,
                        int(delete_result.get("siglip_deleted", 0) or 0),
                        int(delete_result.get("dinov2_deleted", 0) or 0),
                    )

                processed_item_count += 1
                for img in images:
                    try:
                        image_array = await cls.get_image_from_oss(img.image_url)
                        if image_array is None:
                            runtime.logger.warning(f"图片加载失败: {img.image_url}")
                            continue

                        from PIL import Image
                        import cv2

                        image_rgb = cv2.cvtColor(image_array, cv2.COLOR_BGR2RGB)
                        pil_image = Image.fromarray(image_rgb)
                        siglip_ok, dinov2_ok = await manager.index_image(
                            image=pil_image,
                            item_id=item.id,
                            item_name=item.item_name,
                            item_code=item.item_code,
                            image_id=img.id,
                            image_url=img.image_url,
                            description=item.item_name,
                        )

                        preprocess_outcome = getattr(manager, "last_preprocess_outcome", None)
                        if preprocess_outcome is not None:
                            if preprocess_outcome.result_image is not None:
                                try:
                                    segmented_url = await cls._upload_v2_segmented_image(
                                        preprocess_outcome.result_image,
                                        item.id,
                                        img.id,
                                    )
                                    segmented_records_to_create.append(
                                        runtime.SegmentedImage(
                                            id=runtime.get_id(),
                                            item_id=item.id,
                                            source_image_id=img.id,
                                            source_image_url=img.image_url,
                                            segmented_image_url=segmented_url,
                                            status=runtime.SegmentStatus.SUCCESS,
                                            is_indexed=1 if siglip_ok and dinov2_ok else 0,
                                        )
                                    )
                                except Exception as exc:
                                    runtime.logger.warning(
                                        "保存分割图失败: item=%s, image=%s, error=%s",
                                        item.id,
                                        img.id,
                                        exc,
                                    )
                                    segmented_records_to_create.append(
                                        runtime.SegmentedImage(
                                            id=runtime.get_id(),
                                            item_id=item.id,
                                            source_image_id=img.id,
                                            source_image_url=img.image_url,
                                            status=runtime.SegmentStatus.FAILED,
                                            is_indexed=0,
                                            error_message=str(exc),
                                        )
                                    )
                            else:
                                segmented_records_to_create.append(
                                    runtime.SegmentedImage(
                                        id=runtime.get_id(),
                                        item_id=item.id,
                                        source_image_id=img.id,
                                        source_image_url=img.image_url,
                                        status=runtime.SegmentStatus.FAILED,
                                        is_indexed=0,
                                        error_message="SAM3 preprocessing returned no segmented image",
                                    )
                                )

                        if siglip_ok and dinov2_ok:
                            success_count += 1
                            item_success_count += 1
                            success_image_ids.append(img.id)
                            runtime.logger.info(f"索引成功: item={item.id}, image={img.id}")
                        else:
                            fail_count += 1
                            runtime.logger.warning(
                                f"索引部分失败: item={item.id}, siglip={siglip_ok}, dinov2={dinov2_ok}"
                            )
                    except Exception as exc:
                        fail_count += 1
                        runtime.logger.error(f"索引失败: item={item.id}, image={img.id}, error={exc}")
            except Exception as exc:
                fail_count += 1
                runtime.logger.error(f"处理配件失败: item={item.id}, error={exc}")
                continue

            if success_image_ids:
                await runtime.SgoItemImages.indexed_image(session=session, image_id_list=success_image_ids)
                image_status_changed = True
            if segmented_records_to_create:
                await runtime.SegmentedImage.batch_create(session, segmented_records_to_create)
                image_status_changed = True
            if image_status_changed:
                await session.commit()
            if item_success_count > 0 or deleted_existing:
                await cls.sync_item_v2_index_state(item.id, state_manager=state_manager)

        report_progress(total_items, None, 0)
        runtime.logger.info(f"V2 索引重建完成: 成功={success_count}, 失败={fail_count}")
        return {
            "success_count": success_count,
            "fail_count": fail_count,
            "total": success_count + fail_count,
            "processed_item_count": processed_item_count,
            "skipped_existing_count": skipped_existing_count,
        }


async def delete_v2_index(cls, item_id: int, runtime=None) -> dict:
    runtime = runtime or _runtime()
    async with runtime.SessionLocal() as session:
        item = await runtime.Items.get_item_by_id(session=session, item_id=item_id)
        if item is None:
            raise Exception(f"配件不存在: {item_id}")

    delete_result = runtime._get_milvus_state_manager_v2_cls()().delete_item_index(item_id)
    async with runtime.SessionLocal() as session:
        await runtime.Items.update_v2_index_state(
            session=session,
            item_id=item_id,
            has_v2_index=False,
            v2_indexed_image_num=0,
            updated_at=runtime.datetime.now(),
        )
        await session.commit()
    return {
        "item_id": item_id,
        "siglip_deleted": int(delete_result.get("siglip_deleted", 0) or 0),
        "dinov2_deleted": int(delete_result.get("dinov2_deleted", 0) or 0),
        "message": "V2索引删除成功",
    }


async def sync_all_v2_index_state(cls, runtime=None) -> dict:
    runtime = runtime or _runtime()
    snapshot = runtime._get_milvus_state_manager_v2_cls()().get_item_index_state_snapshot()
    updated_at = runtime.datetime.now()
    rows = [
        {
            "item_id": item_id,
            "has_v2_index": state["has_v2_index"],
            "v2_indexed_image_num": state["v2_indexed_image_num"],
            "updated_at": updated_at,
        }
        for item_id, state in snapshot.items()
    ]

    async with runtime.SessionLocal() as session:
        await runtime.Items.reset_v2_index_state(session=session, updated_at=updated_at)
        if len(rows) > 0:
            await runtime.Items.bulk_update_v2_index_state(session=session, rows=rows)
        await session.commit()

    return {
        "indexed_item_count": len(rows),
        "updated_at": runtime.date_to_str(updated_at),
    }


async def sync_item_v2_index_state(cls, item_id: int, state_manager=None, runtime=None):
    runtime = runtime or _runtime()
    manager = state_manager or runtime._get_milvus_state_manager_v2_cls()()
    snapshot = manager.get_item_index_state_snapshot()
    state = snapshot.get(item_id, {"has_v2_index": 0, "v2_indexed_image_num": 0})
    updated_at = runtime.datetime.now()
    async with runtime.SessionLocal() as session:
        await runtime.Items.update_v2_index_state(
            session=session,
            item_id=item_id,
            has_v2_index=bool(state["has_v2_index"]),
            v2_indexed_image_num=state["v2_indexed_image_num"],
            updated_at=updated_at,
        )
        await session.commit()
