from __future__ import annotations

import io
import json
import os
import zipfile

from anyio.to_thread import run_sync
from bfrcommon.snowflake import get_id
from globals_vars import logger
from pydantic import BaseModel
from sqlalchemy import select
from urllib3 import PoolManager
from urllib3.util import create_urllib3_context

from csrcqsf.core.scheduler import scheduler
from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.infra.db.mdp_db import sgo_sessionLocal
from csrcqsf.infra.storage.minio import minio_bucket, minio_instance
from csrcqsf.models.orm.item import Items
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
from csrcqsf.modules.sgo.schemas import ImageSourceType


ctx = create_urllib3_context()
ctx.load_default_certs()
ctx.set_ciphers("AES256-GCM-SHA384")


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
        scheduler.add_job(cls.sync_parts_items, "interval", minutes=100)
        if os.getenv("SGO_ENABLE_IMAGE_SYNC", "false").lower() == "true":
            scheduler.add_job(cls.get_token, "interval", minutes=60)
            cls.get_token()
        else:
            logger.info("SGO 图片同步已禁用（SGO_ENABLE_IMAGE_SYNC != true）")

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
    async def sync_parts_items(cls):
        parts: dict[int, Items] = {}
        async with SessionLocal() as session:
            parts_in_db = await Items.list_all_items(session)
        for part in parts_in_db:
            parts[part.id] = part

        need_insert: list[Items] = []
        async with sgo_sessionLocal() as session:
            data_list = await SgoMaterielMasterplate.list_sgo_items(session=session)
            for data in data_list:
                if int(data.id) in parts:
                    continue
                new_part = Items()
                new_part.id = int(data.id)
                new_part.item_name = data.maktx
                new_part.item_code = data.MATNR
                if new_part.item_name is None or new_part.item_code is None:
                    continue
                need_insert.append(new_part)

        if need_insert:
            async with SessionLocal() as session:
                session.add_all(need_insert)
                await session.commit()

    @classmethod
    async def get_baseimage_id_from_db(cls, item_id_list: list[str]):
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
            return

        need_to_download = await cls._filter_missing_raw_urls(raw_url_list, need_download_pics)
        if not need_to_download:
            return

        sgo_image_list: list[SgoItemImages] = []
        zip_bytes = await run_sync(cls.download_images_from_sgo, need_to_download)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zip_ref:
            for index, file_name in enumerate(zip_ref.namelist()[:-1]):
                content_bytes = zip_ref.read(file_name)
                new_file_name = f"{need_to_download[index]}.jpg"
                minio_instance.client.put_object(
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

    @classmethod
    async def sync_images(cls, item_id_list: list[str]):
        await cls.get_baseimage_id_from_db(item_id_list)
        await cls.get_inquery_code_pic_from_db(item_id_list)

    @classmethod
    async def get_inquery_code_pic_from_db(cls, item_id_list: list[str]):
        item_code_list: list[str] = []
        items_dict: dict[str, Items] = {}

        async with SessionLocal() as session:
            items = Items.get_item_by_id_list(session, [int(item_id) for item_id in item_id_list])
            async for item in items:
                item_code_list.append(item.item_code)
                items_dict[item.item_code] = item

        if not item_code_list:
            return

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
                if detailed_photos_str:
                    detailed_photos = json.loads(detailed_photos_str)
                    for photo in detailed_photos:
                        url_array = str(photo["url"]).split("_")
                        if len(url_array) < 2:
                            continue
                        url = url_array[1]
                        need_download_pics[url] = items_dict[item_code].id
                        raw_url_list.append(url)

                if nameplate_photos_str:
                    nameplate_photos = json.loads(nameplate_photos_str)
                    for photo in nameplate_photos:
                        url_array = str(photo["url"]).split("_")
                        if len(url_array) < 2:
                            continue
                        url = url_array[1]
                        need_download_pics[url] = items_dict[item_code].id
                        raw_url_list.append(url)

        if not raw_url_list:
            return

        need_to_download = await cls._filter_missing_raw_urls(raw_url_list, need_download_pics)
        if not need_to_download:
            return

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
        cls.get_token()
        async with SessionLocal() as session:
            parts_in_db = await Items.list_all_items(session)
            items_id = [str(item.id) for item in parts_in_db]
            items_id.reverse()
            for item_id in items_id:
                try:
                    await cls.sync_images([item_id])
                    logger.info(f"完成item_id为{item_id}的图像同步")
                except Exception as exc:
                    logger.error(f"下载图片出错{exc}")

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
            item_images = await SgoItemImages.list_item_images_by_raw_url(session, raw_url_list)
            url_set = {img.raw_url for img in item_images}
        return [raw_url for raw_url in need_download_pics if raw_url not in url_set]

    @classmethod
    async def _commit_images(cls, sgo_image_list: list[SgoItemImages]):
        if not sgo_image_list:
            return
        async with SessionLocal() as session:
            await SgoItemImages.create_item_images(session, sgo_image_list)
            await session.commit()
