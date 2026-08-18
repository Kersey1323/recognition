from __future__ import annotations

import inspect
from types import ModuleType
from typing import TYPE_CHECKING, Any, Callable, TypeAlias

from sqlalchemy import and_, or_

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
            "run_sync": parts_service_module.run_sync,
            "logger": parts_service_module.logger,
            "SessionLocal": parts_service_module.SessionLocal,
            "Items": parts_service_module.Items,
            "SgoItemImages": parts_service_module.SgoItemImages,
            "SegmentedImage": parts_service_module.SegmentedImage,
            "MilvusManager": parts_service_module.MilvusManager,
            "ImageIndex": parts_service_module.ImageIndex,
            "IndexStatisticsRes": parts_service_module.IndexStatisticsRes,
            "async_get_count": parts_service_module.async_get_count,
            "select": parts_service_module.select,
            "date_to_str": parts_service_module.date_to_str,
            "_get_milvus_manager_v2_cls": parts_service_module._get_milvus_manager_v2_cls,
            "_get_milvus_state_manager_v2_cls": parts_service_module._get_milvus_state_manager_v2_cls,
            "get_model_client": parts_service_module.get_model_client,
            "ModelServiceError": parts_service_module.ModelServiceError,
            "SegmentedImageService": parts_service_module.SegmentedImageService,
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
    progress_callback: Callable[[dict[str, Any]], Any] | None = None,
    resume_after_created_at: Any = None,
    resume_after_item_id: int | None = None,
    initial_completed_item_count: int = 0,
    initial_success_count: int = 0,
    initial_fail_count: int = 0,
    initial_segmented_count: int = 0,
    initial_fallback_count: int = 0,
    total_items_override: int | None = None,
    runtime=None,
):
    runtime = runtime or _runtime()
    model_client = runtime.get_model_client()
    # 索引任务必须具备完整分割和特征能力；模型缺失时整批拒绝，避免悄悄生成原图索引。
    await model_client.require_indexing_extract_capability()
    manager = runtime._get_milvus_manager_v2_cls()()
    state_manager = runtime._get_milvus_state_manager_v2_cls()()

    async with runtime.SessionLocal() as session:
        if item_id:
            items = [await runtime.Items.get_item_by_id(session, item_id)]
            if items[0] is None:
                raise Exception(f"配件不存在: {item_id}")
        else:
            image_filters = [runtime.SgoItemImages.is_deleted == 0]
            if not rebuild_existing:
                # 部分图片已入库的配件仍需补建剩余图片，不能用配件级状态整体排除。
                image_filters.append(runtime.SgoItemImages.is_indexed != 1)
            item_id_stmt = (
                runtime.select(runtime.SgoItemImages.item_id)
                .where(*image_filters)
                .distinct()
            )
            stmt = runtime.select(runtime.Items).where(runtime.Items.id.in_(item_id_stmt))
            if resume_after_created_at is not None and resume_after_item_id is not None:
                # Retry resumes after the last completed part; an interrupted current part is retried.
                stmt = stmt.where(
                    or_(
                        runtime.Items.time_created < resume_after_created_at,
                        and_(
                            runtime.Items.time_created == resume_after_created_at,
                            runtime.Items.id < resume_after_item_id,
                        ),
                    )
                )
            stmt = stmt.order_by(runtime.Items.time_created.desc()).order_by(runtime.Items.id.desc())
            if limit is not None:
                stmt = stmt.limit(limit)
            items = list(await session.scalars(stmt))

        runtime.logger.info(f"开始为 {len(items)} 个配件建立 V2 索引")
        success_count = initial_success_count
        fail_count = initial_fail_count
        processed_item_count = 0
        skipped_existing_count = 0
        segmented_count = initial_segmented_count
        fallback_count = initial_fallback_count

        from tqdm import tqdm

        total_items = total_items_override or (initial_completed_item_count + len(items))
        progress_bar = tqdm(items)

        async def report_progress(
            processed_items: int,
            current_item_id: int | None,
            estimated_remaining_seconds: int | None,
            completed_item: Any = None,
        ) -> None:
            if progress_callback is None:
                return
            progress = int(processed_items * 100 / total_items) if total_items else 100
            # 索引进度按配件统计；图片成功/失败数展示当前实际处理结果。
            snapshot = {
                "progress": progress,
                "total_items": total_items,
                "completed_item_count": processed_items,
                "processed_items": processed_items,
                "success_count": success_count,
                "fail_count": fail_count,
                "segmented_count": segmented_count,
                "fallback_count": fallback_count,
                "current_item_id": current_item_id,
                "estimated_remaining_seconds": estimated_remaining_seconds,
            }
            if completed_item is not None:
                snapshot["last_completed_item_id"] = completed_item.id
                snapshot["last_completed_item_created_at"] = getattr(
                    completed_item,
                    "time_created",
                    None,
                )
            callback_result = progress_callback(snapshot)
            if inspect.isawaitable(callback_result):
                await callback_result

        await report_progress(initial_completed_item_count, None, None)
        for position, item in enumerate(progress_bar, start=1):
            processed_for_progress = initial_completed_item_count + position - 1
            elapsed = float(progress_bar.format_dict.get("elapsed") or 0)
            rate = progress_bar.format_dict.get("rate")
            estimated_remaining_seconds = None
            if rate is not None and rate > 0:
                estimated_remaining_seconds = max(0, round((len(items) - position + 1) / rate))
            elif position > 1:
                average_seconds = elapsed / (position - 1)
                estimated_remaining_seconds = max(
                    0,
                    round(average_seconds * (len(items) - position + 1)),
                )
            await report_progress(
                processed_for_progress,
                item.id if item is not None else None,
                estimated_remaining_seconds,
            )
            if item is None:
                continue

            try:
                images_result = await runtime.SgoItemImages.list_item_images_by_item_id(session, item.id)
                all_images = list(images_result) if images_result else []
                images = all_images
                if not rebuild_existing:
                    # 非强制重建只补建未索引图片，避免重复覆盖已有向量和分割产物。
                    images = [
                        image
                        for image in all_images
                        if int(getattr(image, "is_indexed", 0) or 0) != 1
                    ]
                item_success_count = 0
                success_image_ids: list[int] = []
                deleted_existing = False
                image_status_changed = False
                segmented_service = runtime.SegmentedImageService(session)

                if len(images) == 0:
                    if all_images:
                        skipped_existing_count += 1
                        runtime.logger.info(f"配件 {item.id} 没有待构建索引的图片，跳过")
                    else:
                        runtime.logger.warning(f"配件 {item.id} 没有图片，跳过")
                    await report_progress(
                        initial_completed_item_count + position,
                        None,
                        0 if position == len(items) else estimated_remaining_seconds,
                        completed_item=item,
                    )
                    continue

                if rebuild_existing:
                    delete_result = {"siglip_deleted": 0, "dinov2_deleted": 0}
                    if getattr(item, "has_v2_index", 0) == 1:
                        delete_result = state_manager.delete_item_index(item.id)
                    deleted_patch_tokens = manager.delete_item_patch_tokens(item.id)
                    for image in images:
                        await segmented_service.remove_source_artifacts(item.id, image.id)
                    await runtime.SgoItemImages.un_indexed_image(
                        session=session,
                        image_id_list=[img.id for img in images],
                    )
                    deleted_existing = True
                    image_status_changed = True
                    runtime.logger.info(
                        "强制重建前已删除旧索引: item=%s, siglip=%s, dinov2=%s, patch_tokens=%s",
                        item.id,
                        int(delete_result.get("siglip_deleted", 0) or 0),
                        int(delete_result.get("dinov2_deleted", 0) or 0),
                        deleted_patch_tokens,
                    )

                processed_item_count += 1
                text_vector = await model_client.siglip_text_features(item.item_name)
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

                        segmented_record = None
                        raw_image_source = getattr(img, "image_source", None)
                        image_source = getattr(raw_image_source, "value", raw_image_source)
                        existing_segmented = None
                        should_segment = image_source == "CREATEBYSELF"
                        if should_segment and not rebuild_existing:
                            existing_segmented = await segmented_service.get_latest_success(
                                item.id,
                                img.id,
                            )

                        if not should_segment:
                            # 仅手动上传图片执行主体分割，业务同步图片保留原始画面建立索引。
                            image_vector = await model_client.siglip_image_features(pil_image)
                            global_vector = await model_client.dinov2_global_vector(pil_image)
                            patch_tokens = await model_client.dinov2_patch_tokens(pil_image)
                            indexed_image_url = img.image_url
                            image_variant = "original"
                        elif existing_segmented is not None:
                            indexed_image = await segmented_service.load_image(existing_segmented)
                            image_vector = await model_client.siglip_image_features(indexed_image)
                            global_vector = await model_client.dinov2_global_vector(indexed_image)
                            patch_tokens = await model_client.dinov2_patch_tokens(indexed_image)
                            indexed_image_url = existing_segmented.segmented_image_url
                            image_variant = "segmented"
                            segmented_record = existing_segmented
                            segmented_count += 1
                        else:
                            try:
                                extracted = await model_client.indexing_extract(pil_image)
                            except Exception as exc:
                                is_fallback_error = (
                                    isinstance(exc, runtime.ModelServiceError)
                                    and exc.error_code
                                    in {
                                        "foreground_not_detected",
                                        "empty_mask",
                                        "invalid_foreground_mask",
                                    }
                                )
                                await segmented_service.persist_failure(
                                    item_id=item.id,
                                    source_image_id=img.id,
                                    source_image_url=img.image_url,
                                    error=str(exc),
                                )
                                image_status_changed = True
                                if not is_fallback_error:
                                    raise

                                # 单图主体不可识别时保留该图片的原图索引，其他模型或网络错误不回退。
                                fallback_count += 1
                                image_vector = await model_client.siglip_image_features(pil_image)
                                global_vector = await model_client.dinov2_global_vector(pil_image)
                                patch_tokens = await model_client.dinov2_patch_tokens(pil_image)
                                indexed_image_url = img.image_url
                                image_variant = "original"
                            else:
                                segmented_record = await segmented_service.persist_success(
                                    item_id=item.id,
                                    source_image_id=img.id,
                                    source_image_url=img.image_url,
                                    image=extracted.segmented_image,
                                    bbox=extracted.bbox,
                                    mask_area=extracted.mask_area,
                                )
                                image_status_changed = True
                                image_vector = extracted.siglip_vector
                                global_vector = extracted.dinov2_global_vector
                                patch_tokens = extracted.dinov2_patch_tokens
                                indexed_image_url = segmented_record.segmented_image_url
                                image_variant = "segmented"
                                segmented_count += 1

                        siglip_ok, dinov2_ok = await manager.index_precomputed_features(
                            item_id=item.id,
                            item_name=item.item_name,
                            item_code=item.item_code,
                            image_id=img.id,
                            image_url=indexed_image_url,
                            description=item.item_name,
                            siglip_image_vector=image_vector,
                            siglip_text_vector=text_vector,
                            dinov2_global_vector=global_vector,
                            dinov2_patch_tokens=patch_tokens,
                            image_variant=image_variant,
                        )

                        if siglip_ok and dinov2_ok:
                            if segmented_record is not None:
                                await segmented_service.mark_indexed(segmented_record)
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
                await report_progress(
                    initial_completed_item_count + position,
                    None,
                    0 if position == len(items) else estimated_remaining_seconds,
                    completed_item=item,
                )
                continue

            if success_image_ids:
                await runtime.SgoItemImages.indexed_image(session=session, image_id_list=success_image_ids)
                image_status_changed = True
            if image_status_changed:
                await session.commit()
            if item_success_count > 0 or deleted_existing:
                await cls.sync_item_v2_index_state(item.id, state_manager=state_manager)

            await report_progress(
                initial_completed_item_count + position,
                None,
                0 if position == len(items) else estimated_remaining_seconds,
                completed_item=item,
            )

        if not items:
            await report_progress(initial_completed_item_count, None, 0)
        runtime.logger.info(f"V2 索引重建完成: 成功={success_count}, 失败={fail_count}")
        return {
            "success_count": success_count,
            "fail_count": fail_count,
            "total": success_count + fail_count,
            "processed_item_count": processed_item_count,
            "skipped_existing_count": skipped_existing_count,
            "segmented_count": segmented_count,
            "fallback_count": fallback_count,
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
