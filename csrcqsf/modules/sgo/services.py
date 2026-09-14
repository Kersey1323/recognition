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
from sqlalchemy import String, case, cast, or_, select, text, tuple_
from urllib3 import PoolManager
from urllib3.util import create_urllib3_context

from csrcqsf.core.scheduler import scheduler, submit_coroutine_to_main_loop
from csrcqsf.core.settings import (
    inquiry_text_auto_index_enabled,
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
from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager
from csrcqsf.modules.sgo.item_mapping import normalize_sgo_return_item
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


def _elapsed_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000


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
        # 本地业务库需要完整保留询码流水；老数据可能只有人工返回描述没有编码。
        # 现有线上字段为 NOT NULL，用空字符串表示“未返回编码”，BGE 索引阶段会过滤掉这类记录。
        "return_item_code": return_item_code or "",
        "inquiry_time": row.get("inquiry_time"),
        "source": "sgo",
    }


def _build_inquiry_history_upsert_sql() -> str:
    # 询码历史只允许首次落库；并发重复写入命中唯一键时保持原记录不变。
    columns = ", ".join(f"`{column}`" for column in INQUIRY_HISTORY_COLUMNS)
    placeholders = ", ".join(f":{column}" for column in INQUIRY_HISTORY_COLUMNS)
    return (
        f"INSERT INTO `{ItemInquiryHistory.__tablename__}` ({columns}) "
        f"VALUES ({placeholders}) AS new "
        f"ON DUPLICATE KEY UPDATE `id` = `{ItemInquiryHistory.__tablename__}`.`id`"
    )


class TokenResponse(BaseModel):
    token: str


class SGOBiz:
    """负责从 SGO 同步配件、图片和询码记录到 Recognition 自有存储。"""
    token = ""
    _token_error_detail = ""
    _api_url = os.getenv("SGO_API_URL", "https://sgo.4dlp.com.cn")
    _tenant_id = os.getenv("SGO_TENANT_ID", "1463844437338755072")
    _username = os.getenv("SGO_USERNAME", "wrps")
    _password = os.getenv("SGO_PASSWORD", "REMOVED_CREDENTIAL")
    _encryption = os.getenv("SGO_ENCRYPTION", "REMOVED_CREDENTIAL")

    @classmethod
    def init(cls):
        # 配件主数据可独立定时同步；图片 token 仅在开启图片同步时预热和续期。
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
        """获取图片下载令牌，并保留不含敏感值的诊断信息。"""
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
        # selected 按请求去重后的配件计数，all 只遍历已同步到主库的配件。
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
        """以稳定 ID 游标分批读取配件，避免全量同步一次加载数万条主数据。"""
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
        # 使用主键游标而非 offset，长任务期间数据新增不会造成前后页重复。
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
        """合并配件基础图和询码图片，并按 SGO 原始文件标识去重。"""
        if not items:
            return {}, []

        item_ids = [item.item_id for item in items]
        item_by_code = {item.item_code: item for item in items if item.item_code}
        candidates: dict[str, ImageSyncCandidate] = {}
        failures: list[dict[str, str]] = []
        source_query_started = time.perf_counter()
        async with sgo_sessionLocal() as session:
            base_query_started = time.perf_counter()
            base_rows = await SgoMaterielFileImg.list_image_file(session, item_ids)
            base_query_ms = _elapsed_ms(base_query_started)

            inquiry_query_started = time.perf_counter()
            inquiry_rows = await SgoCodeInquiry.list_image_files_by_item_codes(
                session,
                list(item_by_code),
            )
            inquiry_query_ms = _elapsed_ms(inquiry_query_started)
        source_query_ms = _elapsed_ms(source_query_started)

        parse_started = time.perf_counter()
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

        logger.info(
            "SGO 图片源数据批量采集: items={}, item_codes={}, base_rows={}, "
            "inquiry_rows={}, candidates={}, failures={}, "
            "base_query_ms={:.2f}, inquiry_query_ms={:.2f}, "
            "source_query_ms={:.2f}, parse_ms={:.2f}",
            len(items),
            len(item_by_code),
            len(base_rows),
            len(inquiry_rows),
            len(candidates),
            len(failures),
            base_query_ms,
            inquiry_query_ms,
            source_query_ms,
            _elapsed_ms(parse_started),
        )
        return candidates, failures

    @classmethod
    async def sync_parts_items(
        cls,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        """同步 SGO 配件主数据，已存在 ID 或编码均视为跳过。"""
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
        """同步指定或全部已入库配件的缺失图片，并持续上报任务进度。"""
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

        batch_index = 0
        async for batch in cls._iter_image_item_batches(
            sync_scope=sync_scope,
            item_id_list=item_id_list,
            batch_size=sgo_image_item_batch_size,
        ):
            batch_index += 1
            batch_started = time.perf_counter()
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
                collect_started = time.perf_counter()
                candidates, metadata_failures = await cls._collect_image_candidates(
                    batch.items
                )
                collect_ms = _elapsed_ms(collect_started)
                batch_failures.extend(metadata_failures)
                filter_started = time.perf_counter()
                missing_candidates, existing_count = (
                    await cls._filter_missing_candidates(candidates)
                )
                filter_ms = _elapsed_ms(filter_started)
                skipped_count += existing_count
                logger.info(
                    "SGO 图片同步批次诊断: batch={}, requested_items={}, "
                    "resolved_items={}, candidates={}, existing_images={}, "
                    "missing_images={}, metadata_failures={}, collect_ms={:.2f}, "
                    "filter_ms={:.2f}",
                    batch_index,
                    len(batch.requested_ids),
                    len(batch.items),
                    len(candidates),
                    existing_count,
                    len(missing_candidates),
                    len(metadata_failures),
                    collect_ms,
                    filter_ms,
                )
            except Exception as exc:
                logger.exception(
                    "批量查询配件图片元数据失败: item_ids={}",
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
                token_started = time.perf_counter()
                await run_sync(cls.get_token)
                logger.info(
                    "SGO 图片同步获取 token 完成: batch={}, elapsed_ms={:.2f}",
                    batch_index,
                    _elapsed_ms(token_started),
                )

            # 进度按请求配件数统计；一个配件包含多少图片不会改变 total_items 口径。
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
                            "批量下载 SGO 图片失败: raw_urls={}",
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

            logger.info(
                "SGO 图片同步批次完成: batch={}, requested_items={}, "
                "missing_images={}, zip_groups={}, synced_images_total={}, "
                "skipped_images_total={}, batch_failures={}, batch_elapsed_ms={:.2f}",
                batch_index,
                len(batch.requested_ids),
                len(missing_candidates),
                len(zip_groups),
                synced_image_count,
                skipped_count,
                len(batch_failures),
                _elapsed_ms(batch_started),
            )

            failed_in_batch = set()
            # 同一配件即使多张图片失败，也只在任务配件失败数中累计一次。
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
        _sync_task_id: str | None = None,
    ) -> dict:
        """同步已返回配件编码的询码记录，并触发对应描述的增量语义索引。"""
        sync_started = time.perf_counter()
        source_query_started = time.perf_counter()
        source_rows = await cls._list_sgo_inquiry_history_source_rows(limit=limit)
        source_query_ms = _elapsed_ms(source_query_started)
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

        non_indexable_without_return_code = sum(
            1
            for row in source_rows
            if _clean_text(row.get("return_item_code")) is None
        )
        if non_indexable_without_return_code:
            logger.info(
                "询码历史包含未返回编码记录: non_indexable_without_return_code={}, "
                "total_source_rows={}",
                non_indexable_without_return_code,
                total_items,
            )

        item_codes = {
            item_code
            for row in source_rows
            if (item_code := _clean_text(row.get("return_item_code"))) is not None
        }
        item_map_started = time.perf_counter()
        item_id_map = await cls._list_main_item_ids_by_codes(item_codes)
        item_map_ms = _elapsed_ms(item_map_started)
        payload_build_started = time.perf_counter()
        payloads = [
            _inquiry_history_payload_from_source_row(
                row,
                item_id=item_id_map.get(str(_clean_text(row.get("return_item_code")))),
            )
            for row in source_rows
        ]
        payload_build_ms = _elapsed_ms(payload_build_started)
        local_upsert_started = time.perf_counter()
        upsert_result = await cls._upsert_inquiry_history_payloads(
            payloads,
            batch_size=batch_size,
        )
        local_upsert_ms = _elapsed_ms(local_upsert_started)
        processed_count = int(upsert_result["processed_count"])
        created_count = int(upsert_result["created_count"])
        skipped_count = int(upsert_result["skipped_count"])

        if progress_callback is not None:
            await _notify_progress(
                progress_callback,
                {
                    "progress": 100,
                    "total_items": total_items,
                    "processed_items": total_items,
                    "success_count": processed_count,
                    "fail_count": 0,
                    "created_count": created_count,
                    "skipped_count": skipped_count,
                    "synced_image_count": 0,
                    "current_item_id": source_rows[-1]["inquiry_id"] if source_rows else None,
                    "estimated_remaining_seconds": 0,
                    "failed_item_ids": [],
                }
            )

        result = {
            "total_items": total_items,
            "processed_items": total_items,
            "success_count": processed_count,
            "fail_count": 0,
            "created_count": created_count,
            "skipped_count": skipped_count,
            "synced_image_count": 0,
            "failed_item_ids": [],
            "non_indexable_without_return_code": non_indexable_without_return_code,
        }

        semantic_enqueue_ms = 0.0
        if _sync_task_id is not None:
            result["semantic_index_triggered"] = False
            result["semantic_index_task_id"] = None
            result["semantic_index_warning"] = None
            history_ids = list(upsert_result["history_ids"])
            if history_ids and inquiry_text_auto_index_enabled:
                semantic_enqueue_started = time.perf_counter()
                try:
                    # 询码主数据已经提交后再创建语义索引任务；任务创建失败只记录告警，
                    # 不回滚已经成功写入的询码记录，也不改变 SGO 同步任务的成功状态。
                    semantic_task = await cls._enqueue_inquiry_semantic_index(
                        history_ids,
                        source_sync_task_id=_sync_task_id,
                    )
                    result["semantic_index_triggered"] = True
                    result["semantic_index_task_id"] = semantic_task["task_id"]
                except Exception as exc:
                    warning = str(exc) or repr(exc)
                    result["semantic_index_warning"] = warning
                    logger.exception(
                        "询码同步成功，但增量语义索引任务创建失败: sync_task_id={}",
                        _sync_task_id,
                    )
                finally:
                    semantic_enqueue_ms = _elapsed_ms(semantic_enqueue_started)

        logger.info(
            "SGO 询码历史同步诊断: source_rows={}, item_codes={}, mapped_items={}, "
            "created={}, skipped={}, non_indexable_without_return_code={}, "
            "source_query_ms={:.2f}, item_map_ms={:.2f}, "
            "payload_build_ms={:.2f}, local_upsert_ms={:.2f}, "
            "semantic_enqueue_ms={:.2f}, total_ms={:.2f}",
            total_items,
            len(item_codes),
            len(item_id_map),
            created_count,
            skipped_count,
            non_indexable_without_return_code,
            source_query_ms,
            item_map_ms,
            payload_build_ms,
            local_upsert_ms,
            semantic_enqueue_ms,
            _elapsed_ms(sync_started),
        )
        return result

    @classmethod
    async def _enqueue_inquiry_semantic_index(
        cls,
        history_ids: list[int],
        *,
        source_sync_task_id: str,
    ) -> dict:
        from csrcqsf.modules.railway_parts.services.inquiry_text_index_task_manager import (
            inquiry_text_index_task_manager,
        )

        return await inquiry_text_index_task_manager.enqueue_incremental(
            history_ids,
            source_sync_task_id=source_sync_task_id,
        )

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
                SgoCodeInquiryReturn.item_name.label("return_item_name_raw"),
                SgoCodeInquiryReturn.item_code.label("return_item_code_raw"),
                # 甲方 Kingbase 的 sys.datetime 无法由 asyncpg 直接解码；同步历史只需
                # 保留时间文本写入主库，排序仍使用源字段以维持原有同步顺序。
                cast(SgoCodeInquiry.create_time, String).label("inquiry_time"),
            )
            .join(SgoCodeInquiryReturn, SgoCodeInquiry.id == SgoCodeInquiryReturn.inquiry_id)
            .where(or_(
                SgoCodeInquiryReturn.item_name.is_not(None),
                SgoCodeInquiryReturn.item_code.is_not(None),
            ))
            .order_by(SgoCodeInquiry.create_time.asc(), SgoCodeInquiry.id.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        async with sgo_sessionLocal() as session:
            result = await session.execute(stmt)
            rows = []
            for row in result:
                payload = dict(row._mapping)
                payload["return_item_code"], payload["return_item_name"] = (
                    normalize_sgo_return_item(
                        payload.pop("return_item_name_raw", None),
                        payload.pop("return_item_code_raw", None),
                    )
                )
                rows.append(payload)
            return rows

    @classmethod
    async def _list_main_item_ids_by_codes(cls, item_codes: set[str]) -> dict[str, int]:
        # 询码记录允许先于配件主数据到达，找不到编码时仍保留历史但 item_id 为空。
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
    ) -> dict[str, int | list[int]]:
        if not payloads:
            return {
                "processed_count": 0,
                "created_count": 0,
                "skipped_count": 0,
                "history_ids": [],
            }

        upsert_started = time.perf_counter()
        statement = text(_build_inquiry_history_upsert_sql())
        created_count = 0
        skipped_count = 0
        history_ids: list[int] = []
        batch_count = 0
        existing_query_ms = 0.0
        insert_ms = 0.0
        inserted_verify_ms = 0.0
        async with SessionLocal() as session:
            for offset in range(0, len(payloads), batch_size):
                batch_count += 1
                batch = payloads[offset : offset + batch_size]
                unique_payloads: dict[tuple[str, str, str], dict] = {}
                for payload in batch:
                    key = (
                        str(payload["source"]),
                        str(payload["inquiry_id"]),
                        str(payload["return_item_code"]),
                    )
                    if key in unique_payloads:
                        skipped_count += 1
                        continue
                    unique_payloads[key] = payload

                unique_keys = list(unique_payloads)
                existing_query_started = time.perf_counter()
                existing_result = await session.execute(
                    select(
                        ItemInquiryHistory.source,
                        ItemInquiryHistory.inquiry_id,
                        ItemInquiryHistory.return_item_code,
                    ).where(
                        tuple_(
                            ItemInquiryHistory.source,
                            ItemInquiryHistory.inquiry_id,
                            ItemInquiryHistory.return_item_code,
                        ).in_(unique_keys)
                    )
                )
                existing_query_ms += _elapsed_ms(existing_query_started)
                existing_keys = {
                    (str(source), str(inquiry_id), str(return_item_code))
                    for source, inquiry_id, return_item_code in existing_result
                }
                new_payloads = [
                    payload
                    for key, payload in unique_payloads.items()
                    if key not in existing_keys
                ]
                skipped_count += len(unique_payloads) - len(new_payloads)

                rows = []
                generated_ids = []
                for payload in new_payloads:
                    now = datetime.now()
                    history_id = get_id()
                    generated_ids.append(history_id)
                    # 询码历史由外部 SGO 回填结果驱动，直接 SQL upsert 需补齐主库 Base 审计字段。
                    rows.append(
                        {
                            "id": history_id,
                            "created_by": 0,
                            "updated_by": 0,
                            "time_created": now,
                            "time_updated": now,
                            **payload,
                        }
                    )
                if not rows:
                    continue
                insert_started = time.perf_counter()
                await session.execute(statement, rows)
                await session.flush()
                insert_ms += _elapsed_ms(insert_started)

                # 候选记录可能在预查询后被并发任务抢先插入；只有仍保留本次生成主键的
                # 行才算真正新增，并进入后续 BGE 增量索引。
                inserted_verify_started = time.perf_counter()
                inserted_result = await session.execute(
                    select(ItemInquiryHistory.id).where(
                        ItemInquiryHistory.id.in_(generated_ids)
                    )
                )
                inserted_verify_ms += _elapsed_ms(inserted_verify_started)
                inserted_ids = [int(history_id) for history_id in inserted_result.scalars()]
                history_ids.extend(inserted_ids)
                created_count += len(inserted_ids)
                skipped_count += len(rows) - len(inserted_ids)
            commit_started = time.perf_counter()
            await session.commit()
            commit_ms = _elapsed_ms(commit_started)
        logger.info(
            "SGO 询码历史本地写入诊断: payloads={}, batches={}, created={}, "
            "skipped={}, existing_query_ms={:.2f}, insert_ms={:.2f}, "
            "inserted_verify_ms={:.2f}, commit_ms={:.2f}, total_ms={:.2f}",
            len(payloads),
            batch_count,
            created_count,
            skipped_count,
            existing_query_ms,
            insert_ms,
            inserted_verify_ms,
            commit_ms,
            _elapsed_ms(upsert_started),
        )
        return {
            "processed_count": len(payloads),
            "created_count": created_count,
            "skipped_count": skipped_count,
            "history_ids": list(dict.fromkeys(history_ids)),
        }

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

        resolved_item_code = case(
            (
                SgoCodeInquiryReturn.item_name.in_(item_code_list),
                SgoCodeInquiryReturn.item_name,
            ),
            else_=SgoCodeInquiryReturn.item_code,
        ).label("item_code")
        stmt = (
            select(
                SgoCodeInquiry.detailed_photos,
                SgoCodeInquiry.nameplate_photos,
                resolved_item_code,
            )
            .join(SgoCodeInquiryReturn, SgoCodeInquiry.id == SgoCodeInquiryReturn.inquiry_id)
            .where(or_(
                SgoCodeInquiryReturn.item_name.in_(item_code_list),
                SgoCodeInquiryReturn.item_code.in_(item_code_list),
            ))
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
        """调用 SGO 批量下载接口，校验 ZIP 完整性并对可恢复错误重试。"""
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
        """将 ZIP 中图片并发写入 MinIO，随后一次提交对应图片记录。"""
        if not candidates:
            return 0, []

        zip_download_started = time.perf_counter()
        zip_bytes = await run_sync(
            cls.download_images_from_sgo,
            [candidate.raw_url for candidate in candidates],
        )
        zip_download_ms = _elapsed_ms(zip_download_started)

        zip_extract_started = time.perf_counter()
        with io.BytesIO(zip_bytes) as zip_buffer:
            with zipfile.ZipFile(zip_buffer, "r") as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                if len(entries) != len(candidates):
                    raise SgoImageZipError(
                        "SGO ZIP 文件数量不一致: "
                        f"requested={len(candidates)}, actual={len(entries)}"
                    )
                contents = [archive.read(entry) for entry in entries]
        zip_extract_ms = _elapsed_ms(zip_extract_started)

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

        upload_started = time.perf_counter()
        results = await asyncio.gather(
            *(
                upload_one(candidate, content)
                for candidate, content in zip(candidates, contents)
            )
        )
        upload_ms = _elapsed_ms(upload_started)
        images = [image for image, failure in results if image is not None]
        failures = [failure for image, failure in results if failure is not None]
        commit_started = time.perf_counter()
        created_count = await cls._commit_images(images)
        logger.info(
            "SGO 图片 ZIP 子批处理完成: requested_images={}, zip_bytes={}, "
            "uploaded_images={}, committed_images={}, failures={}, "
            "download_ms={:.2f}, extract_ms={:.2f}, upload_ms={:.2f}, "
            "commit_ms={:.2f}",
            len(candidates),
            len(zip_bytes),
            len(images),
            created_count,
            len(failures),
            zip_download_ms,
            zip_extract_ms,
            upload_ms,
            _elapsed_ms(commit_started),
        )
        return created_count, failures

    @classmethod
    async def sync_all_images(cls):
        return await cls.sync_images(item_id_list=[], sync_scope="all")

    @classmethod
    async def list_inquery(
        cls,
        page: int,
        per_page: int,
        status: str,
        has_indexed: int,
        query: str | None = None,
        vehicle: str | None = None,
        train_no: str | None = None,
        car_num: str | None = None,
    ):
        item_code_list: list[str] = []
        if has_indexed in (1, 2):
            # 配件级索引状态在构建完成后持续回写主表，询码筛选无需遍历向量库。
            async with SessionLocal() as session:
                item_code_list = await Items.list_v2_indexed_item_codes(session)

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
                query,
                vehicle,
                train_no,
                car_num,
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
        # 已软删除图片也视为同步过，避免全量任务把人工删除的错误图片重新导入。
        if not candidates:
            return [], 0

        raw_urls = list(candidates)
        existing_urls: set[str] = set()
        query_batch_size = 1000
        query_started = time.perf_counter()
        query_rounds = 0
        async with SessionLocal() as session:
            for start in range(0, len(raw_urls), query_batch_size):
                query_rounds += 1
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
        logger.info(
            "SGO 图片本地去重查询: candidates={}, query_rounds={}, "
            "existing_images={}, missing_images={}, elapsed_ms={:.2f}",
            len(candidates),
            query_rounds,
            len(existing_urls),
            len(missing),
            _elapsed_ms(query_started),
        )
        return missing, len(candidates) - len(missing)

    @classmethod
    async def _commit_images(cls, sgo_image_list: list[SgoItemImages]):
        """在最终写入前再次按原始地址去重，保证任务重试幂等。"""
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
