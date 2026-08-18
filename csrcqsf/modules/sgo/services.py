from __future__ import annotations

import asyncio
import io
import json
import os
import time
import zipfile
from datetime import datetime
from typing import Callable

from anyio.to_thread import run_sync
from bfrcommon.snowflake import get_id
from globals_vars import logger
from pydantic import BaseModel
from sqlalchemy import select, text
from urllib3 import PoolManager
from urllib3.util import create_urllib3_context

from csrcqsf.core.scheduler import scheduler, submit_coroutine_to_main_loop
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


def _clean_text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    value = value.strip()
    return value or None


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
            task = sgo_sync_task_manager.start("parts", cls.sync_parts_items)
            logger.info(f"SGO 配件定时同步已提交: task_id={task['task_id']}")
        except RuntimeError as exc:
            logger.info(f"跳过本轮 SGO 配件定时同步: {exc}")

    @classmethod
    def get_token(cls):
        url = f"{cls._api_url}/uc/sfsso/authByAccount?tenantId={cls._tenant_id}"
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
                cls.token = TokenResponse.parse_raw(response.data).token
            except Exception as exc:
                logger.error(f"获取sgo token出错:{exc}")

    @classmethod
    async def list_parts_sgo_image(cls, item_id: int):
        async with SessionLocal() as session:
            return await SgoItemImages.list_item_images_by_item_id(session, item_id)

    @classmethod
    async def sync_parts_items(
        cls,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        started_at = time.perf_counter()
        async with SessionLocal() as session:
            part_ids = set(await Items.list_all_item_ids(session))

        need_insert: list[Items] = []
        skipped_count = 0
        fail_count = 0
        failed_item_ids: list[str] = []
        async with sgo_sessionLocal() as session:
            data_list = await SgoMaterielMasterplate.list_sgo_items(session=session)
            source_parts = list(data_list)
            total_items = len(source_parts)
            if progress_callback is not None:
                progress_callback(
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
                    fail_count += 1
                    failed_item_ids.append(str(data.id))
                else:
                    if source_item_id in part_ids:
                        skipped_count += 1
                    elif data.maktx is None or data.MATNR is None:
                        fail_count += 1
                        failed_item_ids.append(str(data.id))
                    else:
                        new_part = Items()
                        new_part.id = source_item_id
                        new_part.item_name = data.maktx
                        new_part.item_code = data.MATNR
                        need_insert.append(new_part)

                if progress_callback is not None and (
                    index == total_items or index % report_interval == 0
                ):
                    elapsed = time.perf_counter() - started_at
                    remaining = int(elapsed / index * (total_items - index)) if index else None
                    progress_callback(
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
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        normalized_ids = list(dict.fromkeys(str(item_id) for item_id in item_id_list))
        total_items = len(normalized_ids)
        success_count = 0
        fail_count = 0
        synced_image_count = 0
        failed_item_ids: list[str] = []
        started_at = time.perf_counter()

        if not normalized_ids:
            return {
                "total_items": 0,
                "processed_items": 0,
                "success_count": 0,
                "fail_count": 0,
                "created_count": 0,
                "skipped_count": 0,
                "synced_image_count": 0,
                "failed_item_ids": [],
            }

        if not cls.token:
            await run_sync(cls.get_token)

        for index, item_id in enumerate(normalized_ids, start=1):
            item_synced_count = 0
            try:
                # 每个配件独立完成基础图和询码图同步，单条失败不会中断后续配件。
                item_synced_count += await cls.get_baseimage_id_from_db([item_id])
                item_synced_count += await cls.get_inquery_code_pic_from_db([item_id])
                success_count += 1
            except Exception as exc:
                fail_count += 1
                failed_item_ids.append(item_id)
                logger.exception(f"同步配件图片失败: item_id={item_id}, error={exc}")
            finally:
                synced_image_count += item_synced_count

            if progress_callback is not None:
                elapsed = time.perf_counter() - started_at
                remaining = int(elapsed / index * (total_items - index)) if index else None
                progress_callback(
                    {
                        "progress": int(index * 100 / total_items) if total_items else 100,
                        "total_items": total_items,
                        "processed_items": index,
                        "success_count": success_count,
                        "fail_count": fail_count,
                        "created_count": synced_image_count,
                        "synced_image_count": synced_image_count,
                        "current_item_id": item_id,
                        "estimated_remaining_seconds": remaining,
                        "failed_item_ids": list(failed_item_ids),
                    }
                )

        return {
            "total_items": total_items,
            "processed_items": total_items,
            "success_count": success_count,
            "fail_count": fail_count,
            "created_count": synced_image_count,
            "skipped_count": 0,
            "synced_image_count": synced_image_count,
            "failed_item_ids": failed_item_ids,
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
            progress_callback(
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
            progress_callback(
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
                SgoCodeInquiry.create_time.label("inquiry_time"),
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
        if not cls.token:
            raise Exception("没有成功获取sgo的token")

        zip_file_name = f"{get_id()}.zip"
        api_url = (
            f"{cls._api_url}/portal/system/file/v1/downloadFileZipCus"
            f"?zipName={zip_file_name}&fileIds={','.join(files_name)}"
        )
        headers = {"Authorization": f"Bearer {cls.token}"}

        with PoolManager(ssl_context=ctx) as pool:
            try:
                response = pool.request("GET", api_url, headers=headers)
                if response.status != 200:
                    data = json.loads(response.data)
                    raise Exception(
                        f"请求出错，返回码为{response.status},message:{data['message']}"
                    )
                return response.data
            except Exception as exc:
                logger.error(f"下载文件出错:{exc}")
                raise

    @classmethod
    async def sync_all_images(cls):
        async with SessionLocal() as session:
            parts_in_db = await Items.list_all_items(session)
            items_id = [str(item.id) for item in parts_in_db]
            items_id.reverse()
        return await cls.sync_images(items_id)

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
    async def _commit_images(cls, sgo_image_list: list[SgoItemImages]):
        if not sgo_image_list:
            return
        async with SessionLocal() as session:
            await SgoItemImages.create_item_images(session, sgo_image_list)
            await session.commit()
