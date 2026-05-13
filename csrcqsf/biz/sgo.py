
import requests
from sqlalchemy import Null, null, select, text
from csrcqsf.data.pg import SessionLocal
from globals_vars import logger
from pydantic import BaseModel
from urllib3 import PoolManager
from urllib3.util import create_urllib3_context
from csrcqsf.models.item import Items
from csrcqsf.models.sgo_models import SgoMaterielFileImg, SgoMaterielMasterplate, SgoCodeInquiry, SgoCodeInquiryReturn
from csrcqsf.scheduler import scheduler
from csrcqsf.data.mdpdb import sgo_sessionLocal, sgo_engine
from csrcqsf.biz.railwayparts.parts import RailwayPartsManager
from bfrcommon.snowflake import get_id
from csrcqsf.models.sgo import ImageSourceType, SgoItemImages
import os
from csrcqsf.settings import temp_dir
from anyio.to_thread import run_sync
import zipfile
import aiofiles
import json
import io
from csrcqsf.biz.railwayparts.milvus import MilvusManager
ctx = create_urllib3_context()
ctx.load_default_certs()
ctx.set_ciphers("AES256-GCM-SHA384")


class TokenResponse(BaseModel):
    token: str


def _get_minio_helpers():
    from csrcqsf.data.minio import minio_bucket, minio_instance

    return minio_instance, minio_bucket


# class FileDescribeItem(BaseModel):
#     fileName: str = ''
#     url: str = ''

# class FileDescribe(BaseModel):
#     files: list[FileDescribeItem] = []

class SGOBiz:

    token = ''

    @classmethod
    def init(cls):
        scheduler.add_job(cls.get_token, "interval", minutes=60)
        scheduler.add_job(cls.sync_parts_items, "interval", minutes=100)
        cls.get_token()

    @classmethod
    def get_token(cls):
        with PoolManager(ssl_context=ctx) as pool:
            try:
                d = pool.request("POST", "https://sgo.csrcqsf.com/uc/sfsso/authByAccount?tenantId=1463844437338755072", json={
                    "password": "REMOVED_CREDENTIAL",
                    "username": "wrps",
                    "encryption": "REMOVED_CREDENTIAL"
                })

                res = TokenResponse.parse_raw(d.data)
                cls.token = res.token
            except Exception as e:
                logger.error(f"获取sgo token出错:{str(e)}")

    @classmethod
    async def list_parts_sgo_image(cls, item_id: int):
        async with SessionLocal() as session:
            parts_sgo_images = await SgoItemImages.list_item_images_by_item_id(session, item_id)
            return parts_sgo_images

    @classmethod
    async def sync_parts_items(cls):

        parts = {}

        async with SessionLocal() as session:
            parts_in_db = await Items.list_all_items(session)

        for part in parts_in_db:
            parts[part.id] = part

        need_insert = []

        async with sgo_sessionLocal() as session:
            data_list = await SgoMaterielMasterplate.list_sgo_items(session=session)
            for data in data_list:
                if int(data.id) not in parts:
                    new_part = Items()
                    new_part.id = int(data.id)
                    new_part.item_name = data.maktx
                    new_part.item_code = data.MATNR
                    if new_part.item_name is None or new_part.item_code is None:
                        continue
                    need_insert.append(new_part)
        if len(need_insert) > 0:
            async with SessionLocal() as session:
                session.add_all(need_insert)
                await session.commit()

    @classmethod
    async def get_baseimage_id_from_db(cls, item_id_list: list[str]):
        """
        根据物料id获取基本信息附件里的配件图片
        """
        async with sgo_sessionLocal() as session:
            results = await SgoMaterielFileImg.list_image_file(session, item_id_list)
            need_download_pics = {}
            raw_url_list = []
            for row in results:
                file_describe = json.loads(row.file_src)
                for f in file_describe:
                    url_array = str(f['url']).split("_")
                    if len(url_array) < 2:
                        continue
                    url = url_array[1]
                    raw_url_list.append(url)
                    need_download_pics[url] = row.masterplate_id
        if len(need_download_pics) == 0:
            return
        need_to_downlod: list[str] = []

        async with SessionLocal() as session:
            item_images = await SgoItemImages.list_item_images_by_raw_url(session, raw_url_list)
            url_set = set()
            for img in item_images:
                url_set.add(img.raw_url)

            for need_down_url, m_id in need_download_pics.items():
                if need_down_url in url_set:
                    continue
                need_to_downlod.append(need_down_url)

        if len(need_to_downlod) == 0:
            return

        sgo_image_list: list[SgoItemImages] = []

        zip_bytes = await run_sync(cls.download_images_from_sgo, need_to_downlod)
        # 使用with语句安全地打开ZIP文件
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zip_ref:
            # 获取ZIP文件内所有文件和文件夹的路径列表
            for index, file_name in enumerate(zip_ref.namelist()[:-1]):
                # 可以根据需要过滤文件，例如只处理 .txt 文件
                content_bytes = zip_ref.read(file_name)
                new_file_name = f"{need_to_downlod[index]}.jpg"
                minio_instance, minio_bucket = _get_minio_helpers()
                minio_instance.client.put_object(
                    minio_bucket, new_file_name, io.BytesIO(content_bytes), len(content_bytes))
                sgo_image = SgoItemImages()
                sgo_image.item_id = int(
                    need_download_pics[need_to_downlod[index]])
                sgo_image.image_source = ImageSourceType.BASEINFO
                sgo_image.image_url = f"{minio_bucket}/{new_file_name}"
                sgo_image.raw_url = need_to_downlod[index]
                sgo_image_list.append(sgo_image)

        # await run_sync(os.remove, zip_file_path)

        async with SessionLocal() as session:
            if len(sgo_image_list) == 0:
                return
            await SgoItemImages.create_item_images(session, sgo_image_list)
            await session.commit()

    @classmethod
    async def sync_images(cls, item_id_list: list[str]):
        await cls.get_baseimage_id_from_db(item_id_list)
        await cls.get_inquery_code_pic_from_db(item_id_list)

    @classmethod
    async def get_inquery_code_pic_from_db(cls, item_id_list: list[str]):
        item_code_list = []
        items_dict = {}

        async with SessionLocal() as session:
            items = Items.get_item_by_id_list(
                session, [int(id) for id in item_id_list])
            async for item in items:
                item_code_list.append(item.item_code)
                items_dict[item.item_code] = item
        if len(item_code_list) == 0:
            return
        # sql = """
        #     select b.item_code,detailed_photos,nameplate_photos from
        #     sgo_code_inquiry a INNER JOIN sgo_code_inquiry_return b on a.id = b.inquery_id
        #     where b.item_code is not null and b.item_code <> '' and b.item_code in :ids
        #     """
        stmt = (
            select(SgoCodeInquiry.detailed_photos, SgoCodeInquiry.nameplate_photos, SgoCodeInquiryReturn.item_code).join(SgoCodeInquiryReturn, SgoCodeInquiry.id == SgoCodeInquiryReturn.inquiry_id).where(
                SgoCodeInquiryReturn.item_code.is_not(None)
            ).where(SgoCodeInquiryReturn.item_code != '').where(SgoCodeInquiryReturn.item_code.in_(item_code_list))
        )

        async with sgo_sessionLocal() as session:
            # 假设表名为 `your_table`，字段名为 `your_field`，查询语句根据实际情况调整
            # query = 'SELECT right(LEFT(file_src, 80), 19) from sgo_materiel_file_img WHERE masterplate_id = (select id from sgo_materiel_masterplate WHERE MATNR = %s)'

            results = await session.execute(stmt)
            need_download_pics = {}
            raw_url_list = []
            for r in results:
                detailed_photos_str = r[0]
                nameplate_photos_str = r[1]
                item_code = r[2]
                if detailed_photos_str is not None and detailed_photos_str != '':
                    detailed_photos = json.loads(detailed_photos_str)
                    for p in detailed_photos:
                        url_array = str(p["url"]).split("_")
                        if len(url_array) < 2:
                            continue
                        url = url_array[1]
                        need_download_pics[url] = items_dict[item_code].id
                        raw_url_list.append(url)
                if nameplate_photos_str is not None and nameplate_photos_str != '':
                    nameplate_photos = json.loads(nameplate_photos_str)

                    for p in nameplate_photos:
                        url_array = str(p['url']).split("_")
                        if len(url_array) < 2:
                            continue
                        url = url_array[1]
                        need_download_pics[url] = items_dict[item_code].id
                        raw_url_list.append(url)

                need_to_downlod: list[str] = []
        if len(raw_url_list) == 0:
            return

        need_to_downlod: list[str] = []
        async with SessionLocal() as session:
            item_images = await SgoItemImages.list_item_images_by_raw_url(session, raw_url_list)
            url_set = set()
            for img in item_images:
                url_set.add(img.raw_url)

            for need_down_url, m_id in need_download_pics.items():
                if need_down_url in url_set:
                    continue
                need_to_downlod.append(need_down_url)

        if len(need_to_downlod) == 0:
            return

        sgo_image_list: list[SgoItemImages] = []

        # 使用with语句安全地打开ZIP文件
        zip_bytes = await run_sync(cls.download_images_from_sgo, need_to_downlod)
        # 使用with语句安全地打开ZIP文件

        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zip_ref:
            # 获取ZIP文件内所有文件和文件夹的路径列表
            for index, file_name in enumerate(zip_ref.namelist()[:-1]):
                # 可以根据需要过滤文件，例如只处理 .txt 文件
                content_bytes = zip_ref.read(file_name)
                new_file_name = f"{need_to_downlod[index]}.jpg"
                minio_instance, minio_bucket = _get_minio_helpers()
                await run_sync(minio_instance.client.put_object, minio_bucket, new_file_name, io.BytesIO(content_bytes), len(content_bytes))
                sgo_image = SgoItemImages()
                sgo_image.item_id = int(
                    need_download_pics[need_to_downlod[index]])
                sgo_image.image_source = ImageSourceType.INQUERY
                sgo_image.image_url = f"{minio_bucket}/{new_file_name}"
                sgo_image.raw_url = need_to_downlod[index]
                sgo_image_list.append(sgo_image)

        async with SessionLocal() as session:
            if len(sgo_image_list) == 0:
                return
            await SgoItemImages.create_item_images(session, sgo_image_list)
            await session.commit()

    @classmethod
    def download_images_from_sgo(cls, files_name: list[str]):
        if cls.token is None or cls.token == '':
            raise Exception(f'没有成功获取sgo的token')
        headers = {
            # 添加 Authorization 头
            'Authorization': 'Bearer {}'.format(cls.token)
        }
        zip_file_name = f"{get_id()}.zip"
        api_url = "https://sgo.csrcqsf.com/portal/system/file/v1/downloadFileZipCus?zipName={}&fileIds={}".format(
            zip_file_name, ",".join(files_name))

        with PoolManager(ssl_context=ctx) as pool:
            try:
                response = pool.request("GET", api_url, headers=headers)
                if response.status != 200:
                    data = json.loads(response.data)
                    message = data['message']
                    raise Exception(
                        f'请求出错，返回码为{response.status},message:{message}')
                else:
                    return response.data
                # with open(full_zip_file_path, 'wb') as f:
                #     f.write(response.data)
            except Exception as e:
                logger.error(f"下载文件出错:{str(e)}")
                raise e

    @classmethod
    async def sync_all_images(cls):
        cls.get_token()
        from bfrcommon.common import splite_list_by_n
        async with SessionLocal() as session:
            parts_in_db = await Items.list_all_items(session)
            items_id = [str(item.id) for item in parts_in_db]
            items_id.reverse()
            for item_id in items_id:
                try:
                    await cls.sync_images([item_id])
                    logger.info(f"完成item_id为{item_id}的图像同步")
                except Exception as e:
                    logger.error(f"下载图片出错{e}")

    @classmethod
    async def list_inquery(cls, page: int, per_page: int, status: str, has_indexed: int):
        item_id_list: list[int] = []
        item_code_list: list[str] = []
        if has_indexed == 1 or has_indexed == 2:
            item_id_list = await MilvusManager.get_all_indexed_item_id_list(page, per_page)
        if len(item_id_list) > 0:
            async with SessionLocal() as session:
                async for item in Items.get_item_by_id_list(session, item_id_list):
                    item_code_list.append(item.item_code)
        async with sgo_sessionLocal() as session:
            inquery_id_list: list[str] = []
            if len(item_code_list) > 0:
                return_list = await SgoCodeInquiryReturn.get_return_by_code_id_list(session, item_code_list)
                for r in return_list:
                    inquery_id_list.append(r.inquiry_id)
            datas = await SgoCodeInquiry.list_code_inquiry(session, page, per_page, status, has_indexed, inquery_id_list)
        return datas

    @classmethod
    async def resize_image(cls):
        async with SessionLocal() as session:
            from PIL import Image
            async for sgo_image in SgoItemImages.get_all_image(session=session):
                image_ndarray = await RailwayPartsManager.get_image_from_oss(sgo_image.image_url)
                if image_ndarray is None:
                    continue
                pil_image = Image.fromarray(image_ndarray.astype('uint8'))
                buf = io.BytesIO()
                pil_image.save(buf, format='PNG')  # 指定格式，如 'JPEG', 'PNG'
                image_bytes = buf.getvalue()  # 获取字节流
            #    buf.close()

                file_name = sgo_image.image_url.split("/")[-1]
                minio_instance, minio_bucket = _get_minio_helpers()
                await run_sync(minio_instance.client.put_object, minio_bucket, file_name, io.BytesIO(image_bytes), len(image_bytes))
                buf.close()

    
