from __future__ import annotations

import asyncio
import io
import inspect
import json
import os
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Callable, Literal

from anyio.to_thread import run_sync
from bfrcommon.snowflake import get_id
from csrcqsf.core.logging_config import logger
from pydantic import BaseModel
from sqlalchemy import String, cast, select, text
from urllib3 import PoolManager
from urllib3.util import create_urllib3_context

from csrcqsf.core.scheduler import scheduler, submit_coroutine_to_main_loop
from csrcqsf.core.settings import (
    sgo_image_download_concurrency,
    sgo_image_download_retries,
    sgo_image_download_timeout_seconds,
    sgo_image_item_batch_size,
    sgo_image_upload_concurrency,
    sgo_image_zip_batch_size,
    sgo_image_zip_max_bytes,
)
from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.infra.db.mdp_db import sgo_sessionLocal
from csrcqsf.infra.storage.minio import minio_bucket, minio_instance
from csrcqsf.models.orm.item import Items
from csrcqsf.models.orm.item_inquiry_history import ItemInquiryHistory
from csrcqsf.models.orm.sgo import SgoItemImages
from csrcqsf.models.orm.sgo_external import (
    SgoCodeInquiry,
    SgoCodeInquiryReturn,
    SgoMaterielFileImg,
    SgoMaterielMasterplate,
)
from csrcqsf.modules.railway_parts.integrations.milvus_state_manager import (
    MilvusStateManagerV2,
)
from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager
from csrcqsf.modules.sgo.photo_parser import extract_photo_raw_urls
from csrcqsf.modules.sgo.schemas import ImageSourceType
from csrcqsf.modules.sgo.sync_task_manager import sgo_sync_task_manager


ctx = create_urllib3_context()
ctx.load_default_certs()
ctx.set_ciphers("AES256-GCM-SHA384")


INQUIRY_HISTORY_COLUMNS = (
    "id",
    "created_by",
    "updated_by",
    "time_created",
    "time_updated",
    "item_id",
    "item_code",
    "inquiry_id",
    "inquiry_num",
    "vehicle_batch",
    "vehicle",
    "train_no",
    "car_num",
    "inquiry_item_name",
    "subordinate_component",
    "remark",
    "return_item_name",
    "return_item_code",
    "inquiry_time",
    "source",
)
MAX_SYNC_FAILURE_DETAILS = 20


@dataclass(frozen=True)
class ImageSyncItem:
    item_id: str
    item_code: str


@dataclass(frozen=True)
class ImageSyncItemBatch:
    requested_ids: list[str]
    items: list[ImageSyncItem]


@dataclass(frozen=True)
class ImageSyncCandidate:
    raw_url: str
    item_id: str
    image_source: ImageSourceType


class SgoImageDownloadError(RuntimeError):
    pass


class SgoImageRetryableError(SgoImageDownloadError):
    pass


class SgoZipTooLargeError(SgoImageDownloadError):
    pass


class SgoImageZipError(RuntimeError):
    pass


async def _notify_progress(progress_callback, payload: dict) -> None:
    if progress_callback is None:
        return
    result = progress_callback(payload)
    if inspect.isawaitable(result):
        await result


def _clean_text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    value = value.strip()
    return value or None


def _item_code_key(value) -> str:
    cleaned = _clean_text(value)
    return str(cleaned).casefold() if cleaned is not None else ""


def _summarize_sgo_auth_response(response) -> str:
    if response is None:
        return "http_status=unavailable"

    status = getattr(response, "status", "unknown")
    headers = getattr(response, "headers", None) or {}
    content_type = headers.get("Content-Type", "unknown")
    data = getattr(response, "data", b"") or b""
    details = [
        f"http_status={status}",
        f"content_type={content_type}",
        f"body_bytes={len(data)}",
    ]
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except Exception:
        payload = None
    if isinstance(payload, dict):
        for key in ("code", "status", "message", "msg", "error"):
            value = payload.get(key)
            if isinstance(value, (str, int, float, bool)) and str(value).strip():
                safe_value = " ".join(str(value).split())[:300]
                details.append(f"response_{key}={safe_value}")
    return ", ".join(details)


def _normalize_vehicle_batch(vehicle: str | None) -> str | None:
    vehicle = _clean_text(vehicle)
    if vehicle is None:
        return None
    return vehicle.split("_", 1)[0].strip() or None


def _inquiry_history_payload_from_source_row(row: dict, item_id: int | None) -> dict:
    return_item_code = _clean_text(row.get("return_item_code"))
    vehicle = _clean_text(row.get("vehicle"))
    return {
        "item_id": item_id,
        "item_code": return_item_code,
        "inquiry_id": _clean_text(row.get("inquiry_id")),
        "inquiry_num": _clean_text(row.get("inquiry_num")),
        "vehicle_batch": _normalize_vehicle_batch(vehicle),
        "vehicle": vehicle,
        "train_no": _clean_text(row.get("train_no")),
        "car_num": _clean_text(row.get("car_num")),
        "inquiry_item_name": _clean_text(row.get("inquiry_item_name")),
        "subordinate_component": _clean_text(row.get("subordinate_component")),
        "remark": _clean_text(row.get("remark")),
        "return_item_name": _clean_text(row.get("return_item_name")),
        "return_item_code": return_item_code,
        "inquiry_time": row.get("inquiry_time"),
        "source": "sgo",
    }


def _build_inquiry_history_upsert_sql() -> str:
    columns = ", ".join(f"`{column}`" for column in INQUIRY_HISTORY_COLUMNS)
    placeholders = ", ".join(f":{column}" for column in INQUIRY_HISTORY_COLUMNS)
    updates = ", ".join(
        f"`{column}` = new.`{column}`"
        for column in INQUIRY_HISTORY_COLUMNS
        if column
        not in {
            "id",
            "time_created",
            "time_updated",
            "inquiry_id",
            "return_item_code",
            "source",
        }
    )
    return (
        f"INSERT INTO `{ItemInquiryHistory.__tablename__}` ({columns}) "
        f"VALUES ({placeholders}) AS new "
        f"ON DUPLICATE KEY UPDATE {updates}, `time_updated` = CURRENT_TIMESTAMP"
    )


class TokenResponse(BaseModel):
    token: str


class SGOBiz:
    token = ""
    _token_error_detail = ""
    _api_url = os.getenv("SGO_API_URL", "https://sgo.csrcqsf.com")
    _tenant_id = os.getenv("SGO_TENANT_ID", "1463844437338755072")
    _username = os.getenv("SGO_USERNAME", "wrps")
    _password = os.getenv("SGO_PASSWORD", "REMOVED_CREDENTIAL")
    _encryption = os.getenv("SGO_ENCRYPTION", "REMOVED_CREDENTIAL")

    @classmethod
    def init(cls):
        scheduler.add_job(
            cls._submit_scheduled_parts_sync,
            "interval",
            minutes=100,
            id="sgo-parts-sync",
            replace_existing=True,
        )
        if os.getenv("SGO_ENABLE_IMAGE_SYNC", "false").lower() == "true":
            scheduler.add_job(cls.get_token, "interval", minutes=60)
            cls.get_token()
        else:
            logger.info("SGO 图片同步已禁用（SGO_ENABLE_IMAGE_SYNC != true）")

    @classmethod
    def _submit_scheduled_parts_sync(cls):
        """定时线程只负责投递，实际同步仍在主事件循环的受管理任务中运行。"""
        future = submit_coroutine_to_main_loop(cls._start_scheduled_parts_sync())

        def _log_submission_result(completed_future):
            try:
                completed_future.result()
            except Exception as exc:
                logger.error(f"提交 SGO 配件定时同步失败: {exc}")

        future.add_done_callback(_log_submission_result)

    @classmethod
    async def _start_scheduled_parts_sync(cls):
        try:
            task = await sgo_sync_task_manager.start("parts", cls.sync_parts_items)
            logger.info(f"SGO 配件定时同步已提交: task_id={task['task_id']}")
        except RuntimeError as exc:
            logger.info(f"跳过本轮 SGO 配件定时同步: {exc}")

    @classmethod
    def get_token(cls):
        url = f"{cls._api_url}/uc/sfsso/authByAccount?tenantId={cls._tenant_id}"
        response = None
        with PoolManager(ssl_context=ctx) as pool:
            try:
                response = pool.request(
                    "POST",
                    url,
                    json={
                        "password": cls._password,
                        "username": cls._username,
                        "encryption": cls._encryption,
                    },
                    timeout=10,
                )
                if not 200 <= response.status < 300:
                    raise SgoImageDownloadError(
                        f"SGO 认证服务返回 HTTP {response.status}"
                    )
                token = TokenResponse.parse_raw(response.data).token.strip()
                if not token:
                    raise SgoImageDownloadError("SGO 认证响应中的 token 为空")
                cls.token = token
                cls._token_error_detail = ""
                logger.info(
                    f"SGO token 获取成功: endpoint={url}, token_length={len(token)}"
                )
                return True
            except Exception as exc:
                cls.token = ""
                cls._token_error_detail = (
                    f"endpoint={url}; "
                    f"username_configured={bool(cls._username)}, "
                    f"password_configured={bool(cls._password)}, "
                    f"encryption_configured={bool(cls._encryption)}, "
                    f"tenant_id_configured={bool(cls._tenant_id)}; "
                    f"{_summarize_sgo_auth_response(response)}; "
                    f"exception={type(exc).__name__}: {exc}"
                )
                logger.exception(f"获取 SGO token 失败: {cls._token_error_detail}")
                return False

    @classmethod
    async def list_parts_sgo_image(cls, item_id: int):
        async with SessionLocal() as session:
            return await SgoItemImages.list_item_images_by_item_id(session, item_id)

    @classmethod
    async def count_image_sync_items(
        cls,
        *,
        sync_scope: Literal["selected", "all"],
        item_id_list: list[str],
    ) -> int:
        if sync_scope == "selected":
            return len(dict.fromkeys(str(item_id) for item_id in item_id_list))
        async with SessionLocal() as session:
            return await Items.count_all_items(session)

    @classmethod
    async def _iter_image_item_batches(
        cls,
        *,
        sync_scope: Literal["selected", "all"],
        item_id_list: list[str],
        batch_size: int,
    ) -> AsyncIterator[ImageSyncItemBatch]:
        if sync_scope == "selected":
            normalized_ids = list(
                dict.fromkeys(str(item_id) for item_id in item_id_list)
            )
            for start in range(0, len(normalized_ids), batch_size):
                requested_ids = normalized_ids[start : start + batch_size]
                numeric_ids = []
                for item_id in requested_ids:
                    try:
                        numeric_ids.append(int(item_id))
                    except (TypeError, ValueError):
                        continue
                async with SessionLocal() as session:
                    rows = await Items.list_item_id_codes_by_ids(session, numeric_ids)
                row_map = {
                    str(item_id): ImageSyncItem(
                        item_id=str(item_id),
                        item_code=str(item_code or ""),
                    )
                    for item_id, item_code in rows
                }
                yield ImageSyncItemBatch(
                    requested_ids=requested_ids,
                    items=[
                        row_map[item_id]
                        for item_id in requested_ids
                        if item_id in row_map
                    ],
                )
            return

        last_id = 0
        while True:
            async with SessionLocal() as session:
                rows = await Items.list_item_id_codes_after(
                    session,
                    last_id,
                    batch_size,
                )
            if not rows:
                break
            items = [
                ImageSyncItem(
                    item_id=str(item_id),
                    item_code=str(item_code or ""),
                )
                for item_id, item_code in rows
            ]
            yield ImageSyncItemBatch(
                requested_ids=[item.item_id for item in items],
                items=items,
            )
            last_id = int(items[-1].item_id)

    @classmethod
    async def _collect_image_candidates(
        cls,
        items: list[ImageSyncItem],
    ) -> tuple[dict[str, ImageSyncCandidate], list[dict[str, str]]]:
        if not items:
            return {}, []

        item_ids = [item.item_id for item in items]
        item_by_code = {item.item_code: item for item in items if item.item_code}
        candidates: dict[str, ImageSyncCandidate] = {}
        failures: list[dict[str, str]] = []
        async with sgo_sessionLocal() as session:
            base_rows = await SgoMaterielFileImg.list_image_file(session, item_ids)
            inquiry_rows = await SgoCodeInquiry.list_image_files_by_item_codes(
                session,
                list(item_by_code),
            )

        for row in base_rows:
            try:
                file_descriptions = json.loads(row.file_src or "[]")
                if not isinstance(file_descriptions, list):
                    raise ValueError("file_src 不是图片数组")
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                failures.append(
                    {
                        "item_id": str(row.masterplate_id),
                        "stage": "base_images",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                )
                continue
            for file_item in file_descriptions:
                if not isinstance(file_item, dict):
                    continue
                url_parts = str(file_item.get("url", "")).split("_")
                if len(url_parts) < 2 or not url_parts[1]:
                    continue
                raw_url = url_parts[1]
                candidates[raw_url] = ImageSyncCandidate(
                    raw_url=raw_url,
                    item_id=str(row.masterplate_id),
                    image_source=ImageSourceType.BASEINFO,
                )

        for detailed_photos, nameplate_photos, item_code in inquiry_rows:
            item = item_by_code.get(str(item_code or ""))
            if item is None:
                continue
            for raw_url in (
                extract_photo_raw_urls(detailed_photos)
                + extract_photo_raw_urls(nameplate_photos)
            ):
                candidates[raw_url] = ImageSyncCandidate(
                    raw_url=raw_url,
                    item_id=item.item_id,
                    image_source=ImageSourceType.INQUERY,
                )

        return candidates, failures

    @classmethod
    async def sync_parts_items(
        cls,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        started_at = time.perf_counter()
        async with SessionLocal() as session:
            item_id_codes = await Items.list_all_item_id_codes(session)
            part_ids = {int(item_id) for item_id, _ in item_id_codes}
            part_codes = {
                _item_code_key(item_code): int(item_id)
                for item_id, item_code in item_id_codes
                if _item_code_key(item_code)
            }

        need_insert: list[Items] = []
        skipped_count = 0
        fail_count = 0
        failed_item_ids: list[str] = []
        failure_details: list[dict[str, str]] = []

        def record_invalid_source(item_id: str, reason: str) -> None:
            nonlocal fail_count
            fail_count += 1
            failed_item_ids.append(item_id)
            if len(failure_details) < MAX_SYNC_FAILURE_DETAILS:
                failure_details.append(
                    {
                        "item_id": item_id,
                        "stage": "source_validation",
                        "error_type": "InvalidSourceData",
                        "error_message": reason,
                    }
                )

        async with sgo_sessionLocal() as session:
            data_list = await SgoMaterielMasterplate.list_sgo_items(session=session)
            source_parts = list(data_list)
            # SGO 可能为同一物料编码保留多个模板 ID。主库编码全局唯一，优先保留
            # 已有关联数据的主库记录；新编码按 Snowflake ID 倒序只接收最新模板。
            source_parts.sort(
                key=lambda row: int(row.id) if str(row.id).isdigit() else -1,
                reverse=True,
            )
            total_items = len(source_parts)
            if progress_callback is not None:
                await _notify_progress(
                    progress_callback,
                    {
                        "progress": 0,
                        "total_items": total_items,
                        "processed_items": 0,
                    }
                )

            # 全量源表仍需逐行比对，但只把本地主库缺失且字段完整的配件加入事务。
            report_interval = max(1, total_items // 100)
            for index, data in enumerate(source_parts, start=1):
                try:
                    source_item_id = int(data.id)
                except (TypeError, ValueError):
                    record_invalid_source(str(data.id), "配件 ID 不是有效整数")
                else:
                    item_code = str(data.MATNR).strip() if data.MATNR is not None else ""
                    item_code_key = _item_code_key(item_code)
                    if source_item_id in part_ids:
                        skipped_count += 1
                    elif item_code_key in part_codes:
                        skipped_count += 1
                    elif not item_code_key:
                        record_invalid_source(str(data.id), "物料编码为空")
                    elif data.maktx is None:
                        record_invalid_source(str(data.id), "配件名称为空")
                    else:
                        new_part = Items()
                        new_part.id = source_item_id
                        new_part.item_name = data.maktx
                        new_part.item_code = item_code
                        need_insert.append(new_part)
                        part_ids.add(source_item_id)
                        part_codes[item_code_key] = source_item_id

                if progress_callback is not None and (
                    index == total_items or index % report_interval == 0
                ):
                    elapsed = time.perf_counter() - started_at
                    remaining = int(elapsed / index * (total_items - index)) if index else None
                    await _notify_progress(
                        progress_callback,
                        {
                            "progress": int(index * 100 / total_items) if total_items else 100,
                            "total_items": total_items,
                            "processed_items": index,
                            "success_count": len(need_insert),
                            "fail_count": fail_count,
                            "created_count": len(need_insert),
                            "skipped_count": skipped_count,
                            "current_item_id": data.id,
                            "estimated_remaining_seconds": remaining,
                            "failed_item_ids": list(failed_item_ids),
                            "failure_details": list(failure_details),
                        }
                    )
                    # 大批量比对期间定期让出事件循环，保证状态轮询和其他接口可响应。
                    await asyncio.sleep(0)

        if need_insert:
            async with SessionLocal() as session:
                session.add_all(need_insert)
                await session.commit()

        return {
            "total_items": len(source_parts),
            "processed_items": len(source_parts),
            "success_count": len(need_insert),
            "fail_count": fail_count,
            "created_count": len(need_insert),
            "skipped_count": skipped_count,
            "synced_image_count": 0,
            "failed_item_ids": failed_item_ids,
            "failure_details": failure_details,
        }

    @classmethod
    async def get_baseimage_id_from_db(cls, item_id_list: list[str]) -> int:
        async with sgo_sessionLocal() as session:
            results = await SgoMaterielFileImg.list_image_file(session, item_id_list)
            need_download_pics: dict[str, str] = {}
            raw_url_list: list[str] = []
            for row in results:
                file_describe = json.loads(row.file_src)
                for file_item in file_describe:
                    url_array = str(file_item["url"]).split("_")
                    if len(url_array) < 2:
                        continue
                    url = url_array[1]
                    raw_url_list.append(url)
                    need_download_pics[url] = row.masterplate_id

        if not need_download_pics:
            return 0

        need_to_download = await cls._filter_missing_raw_urls(raw_url_list, need_download_pics)
        if not need_to_download:
            return 0

        sgo_image_list: list[SgoItemImages] = []
        zip_bytes = await run_sync(cls.download_images_from_sgo, need_to_download)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zip_ref:
            for index, file_name in enumerate(zip_ref.namelist()[:-1]):
                content_bytes = zip_ref.read(file_name)
                new_file_name = f"{need_to_download[index]}.jpg"
                await run_sync(
                    minio_instance.client.put_object,
                    minio_bucket,
                    new_file_name,
                    io.BytesIO(content_bytes),
                    len(content_bytes),
                )
                sgo_image = SgoItemImages()
                sgo_image.item_id = int(need_download_pics[need_to_download[index]])
                sgo_image.image_source = ImageSourceType.BASEINFO
                sgo_image.image_url = f"{minio_bucket}/{new_file_name}"
                sgo_image.raw_url = need_to_download[index]
                sgo_image_list.append(sgo_image)

        await cls._commit_images(sgo_image_list)
        return len(sgo_image_list)

    @classmethod
    async def sync_images(
        cls,
        item_id_list: list[str],
        sync_scope: Literal["selected", "all"] = "selected",
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        if sync_scope not in {"selected", "all"}:
            raise ValueError(f"不支持的图片同步范围: {sync_scope}")

        total_items = await cls.count_image_sync_items(
            sync_scope=sync_scope,
            item_id_list=item_id_list,
        )
        success_count = 0
        fail_count = 0
        synced_image_count = 0
        skipped_count = 0
        processed_items = 0
        failed_item_ids: list[str] = []
        failure_summary: list[dict[str, str]] = []
        started_at = time.perf_counter()

        if progress_callback is not None:
            await _notify_progress(
                progress_callback,
                {
                    "progress": 0 if total_items else 100,
                    "total_items": total_items,
                    "processed_items": 0,
                    "success_count": 0,
                    "fail_count": 0,
                    "created_count": 0,
                    "skipped_count": 0,
                    "synced_image_count": 0,
                    "current_item_id": None,
                    "estimated_remaining_seconds": None if total_items else 0,
                    "new_failure_details": [],
                },
            )

        if not total_items:
            return {
                "total_items": 0,
                "processed_items": 0,
                "success_count": 0,
                "fail_count": 0,
                "created_count": 0,
                "skipped_count": 0,
                "synced_image_count": 0,
                "failed_item_ids": [],
                "failure_details": [],
                "failures_persisted_incrementally": True,
            }

        async for batch in cls._iter_image_item_batches(
            sync_scope=sync_scope,
            item_id_list=item_id_list,
            batch_size=sgo_image_item_batch_size,
        ):
            batch_failures: list[dict[str, str]] = []
            resolved_ids = {item.item_id for item in batch.items}
            for item_id in batch.requested_ids:
                if item_id not in resolved_ids:
                    batch_failures.append(
                        {
                            "item_id": item_id,
                            "stage": "source_validation",
                            "error_type": "ItemNotFound",
                            "error_message": "配件不存在于主业务库",
                        }
                    )

            try:
                candidates, metadata_failures = await cls._collect_image_candidates(
                    batch.items
                )
                batch_failures.extend(metadata_failures)
                missing_candidates, existing_count = (
                    await cls._filter_missing_candidates(candidates)
                )
                skipped_count += existing_count
            except Exception as exc:
                logger.exception(
                    "批量查询配件图片元数据失败: item_ids=%s",
                    batch.requested_ids,
                )
                missing_candidates = []
                for item_id in batch.requested_ids:
                    batch_failures.append(
                        {
                            "item_id": item_id,
                            "stage": "image_metadata",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc) or repr(exc),
                        }
                    )

            if missing_candidates and not cls.token:
                await run_sync(cls.get_token)

            batch_processed = len(batch.requested_ids)
            zip_groups = [
                missing_candidates[start : start + sgo_image_zip_batch_size]
                for start in range(
                    0,
                    len(missing_candidates),
                    sgo_image_zip_batch_size,
                )
            ]
            download_semaphore = asyncio.Semaphore(sgo_image_download_concurrency)

            async def store_zip_group(zip_candidates):
                async with download_semaphore:
                    try:
                        synced, upload_failures = await cls._store_zip_candidates(
                            zip_candidates
                        )
                        return zip_candidates, synced, upload_failures, None
                    except Exception as exc:
                        logger.exception(
                            "批量下载 SGO 图片失败: raw_urls=%s",
                            [candidate.raw_url for candidate in zip_candidates],
                        )
                        return zip_candidates, 0, [], exc

            # 同一批配件中的源文件已按 raw_url 去重，只并发下载不同文件；
            # 配件批次仍保持串行，上一批全部提交后才读取下一批。
            zip_tasks = [
                asyncio.create_task(store_zip_group(zip_candidates))
                for zip_candidates in zip_groups
            ]
            completed_candidates = 0
            try:
                for completed_task in asyncio.as_completed(zip_tasks):
                    (
                        zip_candidates,
                        synced,
                        upload_failures,
                        download_error,
                    ) = await completed_task
                    synced_image_count += synced
                    batch_failures.extend(upload_failures)
                    if download_error is not None:
                        stage = (
                            "zip_extract"
                            if isinstance(download_error, SgoImageZipError)
                            else "sgo_download"
                        )
                        for item_id in dict.fromkeys(
                            candidate.item_id for candidate in zip_candidates
                        ):
                            batch_failures.append(
                                {
                                    "item_id": item_id,
                                    "stage": stage,
                                    "error_type": type(download_error).__name__,
                                    "error_message": str(download_error)
                                    or repr(download_error),
                                }
                            )

                    completed_candidates += len(zip_candidates)
                    if (
                        progress_callback is not None
                        and completed_candidates < len(missing_candidates)
                    ):
                        batch_fraction = completed_candidates / len(missing_candidates)
                        estimated_processed = (
                            processed_items + batch_processed * batch_fraction
                        )
                        elapsed = time.perf_counter() - started_at
                        remaining = int(
                            elapsed
                            / estimated_processed
                            * (total_items - estimated_processed)
                        )
                        # 每个并发下载子批完成后立即刷新任务活动状态，避免前端
                        # 长时间显示 0% 且心跳停留在任务启动时间。
                        partial_progress = max(
                            1,
                            min(99, int(estimated_processed * 100 / total_items)),
                        )
                        await _notify_progress(
                            progress_callback,
                            {
                                "progress": partial_progress,
                                "total_items": total_items,
                                "processed_items": processed_items,
                                "success_count": success_count,
                                "fail_count": fail_count,
                                "created_count": synced_image_count,
                                "skipped_count": skipped_count,
                                "synced_image_count": synced_image_count,
                                "current_item_id": zip_candidates[-1].item_id,
                                "estimated_remaining_seconds": remaining,
                            },
                        )
                    await asyncio.sleep(0)
            finally:
                for zip_task in zip_tasks:
                    if not zip_task.done():
                        zip_task.cancel()
                if zip_tasks:
                    await asyncio.gather(*zip_tasks, return_exceptions=True)

            failed_in_batch = set()
            for failure in batch_failures:
                failed_in_batch.add(failure["item_id"])
                if (
                    len(failed_item_ids) < MAX_SYNC_FAILURE_DETAILS
                    and failure["item_id"] not in failed_item_ids
                ):
                    failed_item_ids.append(failure["item_id"])
                if len(failure_summary) < MAX_SYNC_FAILURE_DETAILS:
                    failure_summary.append(failure)

            processed_items += batch_processed
            batch_fail_count = len(failed_in_batch)
            fail_count += batch_fail_count
            success_count += batch_processed - batch_fail_count

            if progress_callback is not None:
                elapsed = time.perf_counter() - started_at
                remaining = (
                    int(elapsed / processed_items * (total_items - processed_items))
                    if processed_items
                    else None
                )
                await _notify_progress(
                    progress_callback,
                    {
                        "progress": (
                            int(processed_items * 100 / total_items)
                            if total_items
                            else 100
                        ),
                        "total_items": total_items,
                        "processed_items": processed_items,
                        "success_count": success_count,
                        "fail_count": fail_count,
                        "created_count": synced_image_count,
                        "skipped_count": skipped_count,
                        "synced_image_count": synced_image_count,
                        "current_item_id": batch.requested_ids[-1],
                        "estimated_remaining_seconds": remaining,
                        "new_failure_details": batch_failures,
                    },
                )
            await asyncio.sleep(0)

        return {
            "total_items": total_items,
            "processed_items": processed_items,
            "success_count": success_count,
            "fail_count": fail_count,
            "created_count": synced_image_count,
            "skipped_count": skipped_count,
            "synced_image_count": synced_image_count,
            "failed_item_ids": failed_item_ids,
            "failure_details": failure_summary,
            "failures_persisted_incrementally": True,
        }

    @classmethod
    async def sync_inquiry_history(
        cls,
        *,
        limit: int | None = None,
        batch_size: int = 500,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        source_rows = await cls._list_sgo_inquiry_history_source_rows(limit=limit)
        total_items = len(source_rows)
        if progress_callback is not None:
            await _notify_progress(
                progress_callback,
                {
                    "progress": 0,
                    "total_items": total_items,
                    "processed_items": 0,
                    "success_count": 0,
                    "fail_count": 0,
                    "created_count": 0,
                    "skipped_count": 0,
                    "synced_image_count": 0,
                    "failed_item_ids": [],
                }
            )

        item_codes = {
            item_code
            for row in source_rows
            if (item_code := _clean_text(row.get("return_item_code"))) is not None
        }
        item_id_map = await cls._list_main_item_ids_by_codes(item_codes)
        payloads = [
            _inquiry_history_payload_from_source_row(
                row,
                item_id=item_id_map.get(str(_clean_text(row.get("return_item_code")))),
            )
            for row in source_rows
        ]
        processed_count = await cls._upsert_inquiry_history_payloads(
            payloads,
            batch_size=batch_size,
        )

        if progress_callback is not None:
            await _notify_progress(
                progress_callback,
                {
                    "progress": 100,
                    "total_items": total_items,
                    "processed_items": total_items,
                    "success_count": processed_count,
                    "fail_count": 0,
                    "created_count": processed_count,
                    "skipped_count": 0,
                    "synced_image_count": 0,
                    "current_item_id": source_rows[-1]["inquiry_id"] if source_rows else None,
                    "estimated_remaining_seconds": 0,
                    "failed_item_ids": [],
                }
            )

        return {
            "total_items": total_items,
            "processed_items": total_items,
            "success_count": processed_count,
            "fail_count": 0,
            "created_count": processed_count,
            "skipped_count": 0,
            "synced_image_count": 0,
            "failed_item_ids": [],
        }

    @classmethod
    async def _list_sgo_inquiry_history_source_rows(
        cls,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        stmt = (
            select(
                SgoCodeInquiry.id.label("inquiry_id"),
                SgoCodeInquiry.inquiry_num.label("inquiry_num"),
                SgoCodeInquiry.vehicle.label("vehicle"),
                SgoCodeInquiry.train_no.label("train_no"),
                SgoCodeInquiry.car_num.label("car_num"),
                SgoCodeInquiry.item_name.label("inquiry_item_name"),
                SgoCodeInquiry.subordinate_component.label("subordinate_component"),
                SgoCodeInquiry.remark.label("remark"),
                SgoCodeInquiryReturn.item_name.label("return_item_name"),
                SgoCodeInquiryReturn.item_code.label("return_item_code"),
                # 甲方 Kingbase 的 sys.datetime 无法由 asyncpg 直接解码；同步历史只需
                # 保留时间文本写入主库，排序仍使用源字段以维持原有同步顺序。
                cast(SgoCodeInquiry.create_time, String).label("inquiry_time"),
            )
            .join(SgoCodeInquiryReturn, SgoCodeInquiry.id == SgoCodeInquiryReturn.inquiry_id)
            .where(SgoCodeInquiryReturn.item_code.is_not(None))
            .where(SgoCodeInquiryReturn.item_code != "")
            .order_by(SgoCodeInquiry.create_time.asc(), SgoCodeInquiry.id.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        async with sgo_sessionLocal() as session:
            result = await session.execute(stmt)
            return [dict(row._mapping) for row in result]

    @classmethod
    async def _list_main_item_ids_by_codes(cls, item_codes: set[str]) -> dict[str, int]:
        if not item_codes:
            return {}
        async with SessionLocal() as session:
            result = await session.execute(
                select(Items.item_code, Items.id).where(Items.item_code.in_(item_codes))
            )
            return {str(item_code): int(item_id) for item_code, item_id in result}

    @classmethod
    async def _upsert_inquiry_history_payloads(
        cls,
        payloads: list[dict],
        *,
        batch_size: int,
    ) -> int:
        if not payloads:
            return 0

        statement = text(_build_inquiry_history_upsert_sql())
        processed_count = 0
        async with SessionLocal() as session:
            for offset in range(0, len(payloads), batch_size):
                batch = payloads[offset : offset + batch_size]
                rows = []
                for payload in batch:
                    now = datetime.now()
                    # 询码历史由外部 SGO 回填结果驱动，直接 SQL upsert 需补齐主库 Base 审计字段。
                    rows.append(
                        {
                            "id": get_id(),
                            "created_by": 0,
                            "updated_by": 0,
                            "time_created": now,
                            "time_updated": now,
                            **payload,
                        }
                    )
                await session.execute(statement, rows)
                processed_count += len(rows)
                await session.flush()
            await session.commit()
        return processed_count

    @classmethod
    async def get_inquery_code_pic_from_db(cls, item_id_list: list[str]) -> int:
        item_code_list: list[str] = []
        items_dict: dict[str, Items] = {}

        async with SessionLocal() as session:
            items = Items.get_item_by_id_list(session, [int(item_id) for item_id in item_id_list])
            async for item in items:
                item_code_list.append(item.item_code)
                items_dict[item.item_code] = item

        if not item_code_list:
            return 0

        stmt = (
            select(
                SgoCodeInquiry.detailed_photos,
                SgoCodeInquiry.nameplate_photos,
                SgoCodeInquiryReturn.item_code,
            )
            .join(SgoCodeInquiryReturn, SgoCodeInquiry.id == SgoCodeInquiryReturn.inquiry_id)
            .where(SgoCodeInquiryReturn.item_code.is_not(None))
            .where(SgoCodeInquiryReturn.item_code != "")
            .where(SgoCodeInquiryReturn.item_code.in_(item_code_list))
        )

        async with sgo_sessionLocal() as session:
            results = await session.execute(stmt)
            need_download_pics: dict[str, int] = {}
            raw_url_list: list[str] = []
            for detailed_photos_str, nameplate_photos_str, item_code in results:
                for url in extract_photo_raw_urls(detailed_photos_str):
                    need_download_pics[url] = items_dict[item_code].id
                    raw_url_list.append(url)

                for url in extract_photo_raw_urls(nameplate_photos_str):
                    need_download_pics[url] = items_dict[item_code].id
                    raw_url_list.append(url)

        if not raw_url_list:
            return 0

        need_to_download = await cls._filter_missing_raw_urls(raw_url_list, need_download_pics)
        if not need_to_download:
            return 0

        sgo_image_list: list[SgoItemImages] = []
        zip_bytes = await run_sync(cls.download_images_from_sgo, need_to_download)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zip_ref:
            for index, file_name in enumerate(zip_ref.namelist()[:-1]):
                content_bytes = zip_ref.read(file_name)
                new_file_name = f"{need_to_download[index]}.jpg"
                await run_sync(
                    minio_instance.client.put_object,
                    minio_bucket,
                    new_file_name,
                    io.BytesIO(content_bytes),
                    len(content_bytes),
                )
                sgo_image = SgoItemImages()
                sgo_image.item_id = int(need_download_pics[need_to_download[index]])
                sgo_image.image_source = ImageSourceType.INQUERY
                sgo_image.image_url = f"{minio_bucket}/{new_file_name}"
                sgo_image.raw_url = need_to_download[index]
                sgo_image_list.append(sgo_image)

        await cls._commit_images(sgo_image_list)
        return len(sgo_image_list)

    @classmethod
    def download_images_from_sgo(cls, files_name: list[str]):
        # 关闭启动时的图片同步不应阻断手动同步；首次下载时按需建立认证会话。
        if not cls.token:
            cls.get_token()
        if not cls.token:
            detail = cls._token_error_detail or "认证函数未返回 token，且没有错误详情"
            raise SgoImageDownloadError(f"SGO token 获取失败: {detail}")

        zip_file_name = f"{get_id()}.zip"
        api_url = (
            f"{cls._api_url}/portal/system/file/v1/downloadFileZipCus"
            f"?zipName={zip_file_name}&fileIds={','.join(files_name)}"
        )
        refreshed_token = False
        attempt = 0
        while attempt < sgo_image_download_retries:
            response = None
            try:
                with PoolManager(ssl_context=ctx) as pool:
                    response = pool.request(
                        "GET",
                        api_url,
                        headers={"Authorization": f"Bearer {cls.token}"},
                        timeout=sgo_image_download_timeout_seconds,
                        preload_content=False,
                    )
                    if response.status == 401:
                        if refreshed_token:
                            raise SgoImageDownloadError("SGO token 刷新后仍然无效")
                        refreshed_token = True
                        cls.token = ""
                        cls.get_token()
                        if not cls.token:
                            detail = cls._token_error_detail or "认证函数未返回 token"
                            raise SgoImageDownloadError(
                                f"SGO token 刷新失败: {detail}"
                            )
                        continue
                    if response.status >= 500:
                        raise SgoImageRetryableError(
                            f"SGO 文件服务返回 {response.status}"
                        )
                    if response.status != 200:
                        raise SgoImageDownloadError(
                            f"SGO 文件下载失败，HTTP {response.status}"
                        )

                    payload = bytearray()
                    for chunk in response.stream(1024 * 1024):
                        payload.extend(chunk)
                        if len(payload) > sgo_image_zip_max_bytes:
                            raise SgoZipTooLargeError(
                                "SGO ZIP 响应超过限制: "
                                f"limit={sgo_image_zip_max_bytes} bytes"
                            )
                    return bytes(payload)
            except (SgoZipTooLargeError, SgoImageDownloadError) as exc:
                if not isinstance(exc, SgoImageRetryableError):
                    raise
                attempt += 1
                if attempt >= sgo_image_download_retries:
                    raise
                time.sleep(min(2 ** (attempt - 1), 5))
            except Exception as exc:
                attempt += 1
                if attempt >= sgo_image_download_retries:
                    raise SgoImageDownloadError(
                        f"SGO 文件下载重试耗尽: {exc}"
                    ) from exc
                time.sleep(min(2 ** (attempt - 1), 5))
            finally:
                if response is not None:
                    response.release_conn()
        raise SgoImageDownloadError("SGO 文件下载重试耗尽")

    @classmethod
    async def _store_zip_candidates(
        cls,
        candidates: list[ImageSyncCandidate],
    ) -> tuple[int, list[dict[str, str]]]:
        if not candidates:
            return 0, []

        zip_bytes = await run_sync(
            cls.download_images_from_sgo,
            [candidate.raw_url for candidate in candidates],
        )
        with io.BytesIO(zip_bytes) as zip_buffer:
            with zipfile.ZipFile(zip_buffer, "r") as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                if len(entries) != len(candidates):
                    raise SgoImageZipError(
                        "SGO ZIP 文件数量不一致: "
                        f"requested={len(candidates)}, actual={len(entries)}"
                    )
                contents = [archive.read(entry) for entry in entries]

        semaphore = asyncio.Semaphore(sgo_image_upload_concurrency)

        async def upload_one(candidate: ImageSyncCandidate, content: bytes):
            new_file_name = f"{candidate.raw_url}.jpg"
            try:
                async with semaphore:
                    with io.BytesIO(content) as image_stream:
                        await run_sync(
                            minio_instance.client.put_object,
                            minio_bucket,
                            new_file_name,
                            image_stream,
                            len(content),
                        )
            except Exception as exc:
                return None, {
                    "item_id": candidate.item_id,
                    "stage": "minio_upload",
                    "error_type": type(exc).__name__,
                    "error_message": f"raw_url={candidate.raw_url}: {exc}",
                }

            image = SgoItemImages()
            image.item_id = int(candidate.item_id)
            image.image_source = candidate.image_source
            image.image_url = f"{minio_bucket}/{new_file_name}"
            image.raw_url = candidate.raw_url
            return image, None

        results = await asyncio.gather(
            *(
                upload_one(candidate, content)
                for candidate, content in zip(candidates, contents)
            )
        )
        images = [image for image, failure in results if image is not None]
        failures = [failure for image, failure in results if failure is not None]
        created_count = await cls._commit_images(images)
        return created_count, failures

    @classmethod
    async def sync_all_images(cls):
        return await cls.sync_images(item_id_list=[], sync_scope="all")

    @classmethod
    async def list_inquery(cls, page: int, per_page: int, status: str, has_indexed: int):
        item_id_list: list[int] = []
        item_code_list: list[str] = []
        if has_indexed in (1, 2):
            item_id_list = MilvusStateManagerV2().get_all_indexed_item_id_list(page, per_page)

        if item_id_list:
            async with SessionLocal() as session:
                async for item in Items.get_item_by_id_list(session, item_id_list):
                    item_code_list.append(item.item_code)

        async with sgo_sessionLocal() as session:
            inquery_id_list: list[str] = []
            if item_code_list:
                return_list = await SgoCodeInquiryReturn.get_return_by_code_id_list(
                    session,
                    item_code_list,
                )
                for row in return_list:
                    inquery_id_list.append(row.inquiry_id)

            return await SgoCodeInquiry.list_code_inquiry(
                session,
                page,
                per_page,
                status,
                has_indexed,
                inquery_id_list,
            )

    @classmethod
    async def resize_image(cls):
        async with SessionLocal() as session:
            from PIL import Image

            async for sgo_image in SgoItemImages.get_all_image(session=session):
                image_ndarray = await RailwayPartsManager.get_image_from_oss(sgo_image.image_url)
                if image_ndarray is None:
                    continue
                pil_image = Image.fromarray(image_ndarray.astype("uint8"))
                buf = io.BytesIO()
                pil_image.save(buf, format="PNG")
                image_bytes = buf.getvalue()

                file_name = sgo_image.image_url.split("/")[-1]
                await run_sync(
                    minio_instance.client.put_object,
                    minio_bucket,
                    file_name,
                    io.BytesIO(image_bytes),
                    len(image_bytes),
                )
                buf.close()

    @classmethod
    async def _filter_missing_raw_urls(
        cls,
        raw_url_list: list[str],
        need_download_pics: dict[str, int | str],
    ) -> list[str]:
        async with SessionLocal() as session:
            item_images = await SgoItemImages.list_item_images_by_raw_url(
                session,
                raw_url_list,
                include_deleted=True,
            )
            url_set = {img.raw_url for img in item_images}
        return [raw_url for raw_url in need_download_pics if raw_url not in url_set]

    @classmethod
    async def _filter_missing_candidates(
        cls,
        candidates: dict[str, ImageSyncCandidate],
    ) -> tuple[list[ImageSyncCandidate], int]:
        if not candidates:
            return [], 0

        raw_urls = list(candidates)
        existing_urls: set[str] = set()
        query_batch_size = 1000
        async with SessionLocal() as session:
            for start in range(0, len(raw_urls), query_batch_size):
                images = await SgoItemImages.list_item_images_by_raw_url(
                    session,
                    raw_urls[start : start + query_batch_size],
                    include_deleted=True,
                )
                existing_urls.update(
                    image.raw_url for image in images if image.raw_url is not None
                )

        missing = [
            candidate
            for raw_url, candidate in candidates.items()
            if raw_url not in existing_urls
        ]
        return missing, len(candidates) - len(missing)

    @classmethod
    async def _commit_images(cls, sgo_image_list: list[SgoItemImages]):
        if not sgo_image_list:
            return 0
        async with SessionLocal() as session:
            raw_urls = [
                image.raw_url
                for image in sgo_image_list
                if image.raw_url is not None
            ]
            existing_images = await SgoItemImages.list_item_images_by_raw_url(
                session,
                raw_urls,
                include_deleted=True,
            )
            existing_urls = {
                image.raw_url
                for image in existing_images
                if image.raw_url is not None
            }
            new_images = [
                image
                for image in sgo_image_list
                if image.raw_url is None or image.raw_url not in existing_urls
            ]
            if not new_images:
                return 0
            # Recognition 单实例只允许运行一个同步任务；写入前二次查询可覆盖
            # 任务重试和跨批次重复源文件，无需修改甲方 Kingbase 表结构。
            await SgoItemImages.create_item_images(session, new_images)
            await session.commit()
            return len(new_images)
