"""
业务逻辑层 - 配件管理核心业务
职责：实现具体的业务逻辑、算法调用、数据处理
注意：此层包含核心业务实现，调用数据层和算法模块
"""
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
from csrcqsf.models.item import *
from bfrcommon.snowflake import get_id
from csrcqsf.data.pg import SessionLocal
from csrcqsf.data.mdpdb import sgo_sessionLocal
from csrcqsf.data.minio import ensure_minio_bucket, minio_instance, parse_minio_path
from csrcqsf.models.search_history import (
    MatchedImage,
    SearchHistory,
    SearchResultItem,
    SearchResults,
    SearchReviewTicket,
)
from csrcqsf.models.sgo_models import SgoMaterielMasterplate
# 导入Milvus向量检索管理器
from .milvus import MilvusManager, ImageIndex, PartsIndex, FeaturesIndex, ColletionEnum
from .api_models import *
from bfrcommon.common import date_to_str
from globals_vars import logger
from csrcqsf.models.sgo import (
    ListInqueryItem,
    SgoItemImages,
    ImageSourceType,
    SegmentedImage,
    SegmentStatus,
)
import numpy as np
import cv2
from anyio.to_thread import run_sync
from csrcqsf.data.milvus import milvus_client
from pymilvus import Function, FunctionType
from pymilvus import AnnSearchRequest
from pymilvus.client.embedding_list import EmbeddingList
from csrcqsf.settings import ai_settings,minio_bucket,minio_search_history_bucket,temp_dir
from .vector_db.storage.milvus_manager import MilvusManagerV2
from .vector_db.storage.milvus_state_manager import MilvusStateManagerV2

class RailwayPartsManager:
    """
    配件管理核心业务类
    
    职责：
    1. 配件CRUD操作
    2. 图片管理和索引
    3. 特征提取和检索
    4. 与Milvus向量数据库交互
    """

    _milvus_manager = MilvusManager()

    @classmethod
    async def init(cls):
        """初始化配件管理器"""
        pass

    @classmethod
    async def create_item(
        cls,
        item_name: str,
        item_code: str,
        obj_url: str = None,
        height: float = None,
        length: float = None,
        width: float = None,
        weight: float = None,
    ):
        """
        创建配件实体
        
        参数：
            item_name: 配件名称
            item_code: 配件编码
            obj_url: 3D模型URL（可选）
            height/length/width: 尺寸信息（可选）
        
        数据库操作：Items.create_item() in models/item.py
        """
        item = Items(
            item_name=item_name,
            item_code=item_code,
            obj_url=obj_url,
            height=height,
            long=length,
            width=width,
            weight=weight,
            id=get_id()
        )
        async with SessionLocal() as session:
            await Items.create_item(session=session, item=item)
            # if len(pic_urls) > 0:
            #     await ItemImage.create_images(session=session, item_id=item.id, images=pic_urls)
            await session.commit()

    @classmethod
    async def index_pics(cls, item_id: int):
        image_id_list = []
        async with SessionLocal() as session:
            images = SgoItemImages.get_images(session=session, item_id=item_id)
            async for image in images:
                await cls._milvus_manager.insert_pic(item_id, image.image_url)
                image_id_list.append(image.id)
            await SgoItemImages.indexed_image(session=session, image_id_list=image_id_list)

    @classmethod
    async def delete_pic(cls, image_id: int):
        async with SessionLocal() as session:
            await SgoItemImages.delete_image(session=session, image_id=image_id)
            await session.commit()

    @classmethod
    async def delete_item(cls, item_id_list: list[int]):
        async with SessionLocal() as session:
            await Items.delete_item_by_id_list(session=session, item_id_list=item_id_list)
            await session.commit()

    @classmethod
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
    ):
        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session=session, item_id=item_id)
            if item is None:
                raise Exception(f'id为{item_id}的配件不存在')

            if "item_name" in update_fields and (item_name is None or str(item_name).strip() == ""):
                raise Exception("配件名称不能为空")

            if "item_code" in update_fields and (item_code is None or str(item_code).strip() == ""):
                raise Exception("物料编码不能为空")

            if "item_code" in update_fields and item.item_code != item_code:
                item_by_code = await Items.get_item_by_item_code(session=session, item_code=item_code)
                if item_by_code is not None:
                    raise Exception(f"物料编码:{item_code}已经存在了")

            if "parent_item_id" in update_fields:
                parent_item = await Items.get_item_by_id(session=session, item_id=parent_item_id)
                if parent_item is None:
                    raise Exception(f'id为{parent_item_id}的父配件不存在')

            values = Items.build_item_updates(
                fields=update_fields,
                item_name=item_name,
                item_code=item_code,
                height=height,
                length=length,
                width=width,
                weight=weight,
            )
            await Items.update_item_fields(session=session, item_id=item_id, values=values)
            if "parent_item_id" in update_fields:
                await ItemsParent.replace_parent_relations(
                    session=session,
                    item_id=item_id,
                    parent_item_id=parent_item_id,
                )
            await session.commit()

    @classmethod
    async def list_item(cls, req: ListItemReq):
        item_code_list = []
        if req.has_inquery_code == 1:
            async with sgo_sessionLocal() as session:
                stmt = select(SgoCodeInquiryReturn.item_code.distinct())
                data = await session.scalars(stmt)
                item_code_list = list(data.all())

        async with SessionLocal() as session:
            item_id_list = []
            if req.parent_item_id != 0:
                data = await ItemsParent.list_item_by_parent_id(session, req.parent_item_id)
                for d in data:
                    item_id_list.append(d.item_id)  
            has_index_flag = True if req.only_has_index == 1 else False
            images_has = True if req.has_images == 1 else False
            items = await Items.list_items(
                session=session,
                query=req.query,
                page=req.page,
                per_page=req.per_page,
                has_images=images_has,
                item_id_list=item_id_list,
                item_code_list=item_code_list,
                need_index=False,
                need_v2_index=has_index_flag,
                has_source_video=req.has_source_video,
            )

            index_dict = await MilvusManager.list_item_index([item.id for item in items.data])

            images = await RailwayPartsManager.list_item_images([item.id for item in items.data])
            images_dict: dict[int, list[SgoItemImages]] = {}

            for image in images:
                if image.item_id not in images_dict:
                    images_dict[image.item_id] = []
                images_dict[image.item_id].append(image)

            res = LisItemRes(
                total=items.total
            )
            for item in items.data:
                item_desc = ListItem(
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
                    created_at=date_to_str(item.time_created)
                )
                if item.id in images_dict:
                    item_desc.images_total_num = len(images_dict[item.id])

                index = index_dict.get(item.id)
                if index is not None:
                    item_desc.features = [f.feature for f in index.features]
                    item_desc.features_num = len(index.features)
                res.items.append(item_desc)
            return res

    @classmethod
    async def list_item_images(cls, item_id_list: list[int]):
        async with SessionLocal() as session:
            result = await SgoItemImages.list_item_images_by_item_id_list(session, item_id_list)
            return list(result) if result else []

    @classmethod
    async def delete_item_image_index(cls, item_id: int, image_url_list: list[str]):

        now_index_list = await MilvusManager.list_item_index([item_id])

        if item_id not in now_index_list:
            raise Exception(f'特征数据库并没有该配件的索引信息')

        index = now_index_list[item_id]

        image_url_set = set(image_url_list)

        new_image_index_list: list[ImageIndex] = []

        for image_index in index.images:
            if image_index.filename not in image_url_set:
                new_image_index_list.append(image_index)

        index.images = new_image_index_list  # 覆盖
        
        if len(index.images) > 0:
            await MilvusManager.upsert_data(index)
            async with SessionLocal() as session:
                await Items.update_items_index(session=session, item_id=item_id,
                                               image_index_num=len(index.images), feature_index_num=len(index.features))
                await session.commit()
        else:
            await MilvusManager.delete_part_index(item_id)
            async with SessionLocal() as session:
                await Items.update_items_index(session=session, item_id=item_id,
                                               image_index_num=0, feature_index_num=0)
                await session.commit()

    @classmethod
    async def _upload_v2_segmented_image(
        cls,
        image,
        item_id: int,
        source_image_id: int,
    ) -> str:
        """上传 V2 索引流程生成的分割图到 MinIO。"""
        ensure_minio_bucket(minio_bucket)
        Path(temp_dir).mkdir(parents=True, exist_ok=True)

        token = get_id()
        object_name = f"v2-segmented/{item_id}/{source_image_id}_{token}.jpg"
        local_path = os.path.join(temp_dir, f"v2_segmented_{token}.jpg")

        try:
            rgb_image = image.convert("RGB")
            await run_sync(rgb_image.save, local_path, "JPEG")
            await run_sync(
                minio_instance.upload_file,
                minio_bucket,
                object_name,
                local_path,
                "image/jpeg",
            )
            return f"{minio_bucket}/{object_name}"
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

    @classmethod
    async def _upload_v2_search_query_image(
        cls,
        history_id: int,
        filename: str,
        content_bytes: bytes,
    ) -> str:
        ensure_minio_bucket(minio_search_history_bucket)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", (filename or "query.jpg").strip())
        if not safe_name:
            safe_name = "query.jpg"

        date_prefix = datetime.now().strftime("%Y%m%d")
        object_name = f"query-images/{date_prefix}/{history_id}_{safe_name}"
        await run_sync(
            minio_instance.client.put_object,
            minio_search_history_bucket,
            object_name,
            io.BytesIO(content_bytes),
            len(content_bytes),
        )
        return f"{minio_search_history_bucket}/{object_name}"

    @classmethod
    async def update_item_size(cls, item_id: int, item_size_str: str):
        async with SessionLocal() as session:
            await Items.put_item_size_desc(session=session, item_id=item_id, size_desc=item_size_str)
            await session.commit()

    @classmethod
    async def get_item_detail(cls, item_id: int):
        from csrcqsf.biz.railwayparts.reconstruction_manager import ReconstructionManager

        await ReconstructionManager.ensure_item_result_persisted(item_id)

        index_detail = await MilvusManager.list_item_index([item_id])
        indexed_image_dict = MilvusStateManagerV2().get_indexed_images_by_item_id(item_id)

        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session=session, item_id=item_id)
            if item is None:
                raise Exception(f'id为{item_id}的配件不存在')
            parent_item = None
            # if item.parent_item_id is not None and item.parent_item_id > 0:
            #     parent_item = await Items.get_item_by_id(session=session, item_id=item.parent_item_id)
            #     if parent_item is None:
            #         raise Exception(f'父节点信息找不到')

            images = SgoItemImages.get_images(session=session, item_id=item_id)
            segmented_records = list(await SegmentedImage.list_by_item_id(session, item_id))
            segmented_image_dict: dict[int, str | None] = {}
            for record in segmented_records:
                source_image_id = int(record.source_image_id)
                if source_image_id in segmented_image_dict:
                    continue
                if record.status == SegmentStatus.SUCCESS and record.segmented_image_url:
                    segmented_image_dict[source_image_id] = record.segmented_image_url
                else:
                    segmented_image_dict[source_image_id] = None
            res = GetItemDetailRes(
                ply_url=item.obj_url,
                id=str(item.id),
                height=item.height,
                width=item.width,
                length=item.long,
                weight=item.weight,
                video_path=item.source_video_path,
                name=item.item_name,
                item_code=item.item_code,
                created_at=date_to_str(item.time_created),
                updated_at=date_to_str(item.time_updated),
                size_str=item.size_str,
            )
            if index_detail.get(item_id) is not None:
                for feature in index_detail.get(item_id).features:
                    res.features.append(feature.feature)
            # if parent_item is not None:
            #     res.parent_item_id = str(item.parent_item_id)
            #     res.parent_item_name = parent_item.item_name
            #     res.parent_item_code = parent_item.item_code
            for image_id, image_url in sorted(indexed_image_dict.items()):
                res.images_index_list.append(
                    ItemImageIndexInfo(
                        image_id=str(image_id),
                        image_url=segmented_image_dict.get(image_id) or image_url
                    )
                )
            async for image in images:
                image_item = ItemImageItem(
                    image_id=str(image.id),
                    has_indexed=1 if image.id in indexed_image_dict else 0,
                    image_url=image.image_url or indexed_image_dict.get(image.id),
                    source_type=image.image_source
                )
                res.images.append(image_item)
        return res

    @classmethod
    async def create_item_image(cls, item_id: int, image_url_list: list[str]):
        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session, item_id)
            if item is None:
                raise Exception(f'配件不存在')

            item_images_result = await SgoItemImages.list_item_images_by_item_id(session, item_id=item_id)
            item_images = list(item_images_result) if item_images_result else []

            image_url_set = set()
            for image in item_images:
                image_url_set.add(image.image_url)

            image_list = []
            for image_url in image_url_list:
                if image_url in image_url_set:
                    continue
                image = SgoItemImages(
                    item_id=item_id,
                    image_url=image_url,
                    image_source=ImageSourceType.CREATEBYSELF,
                    is_indexed=1,
                )
                image_list.append(image)

            if len(image_list) > 0:
                await SgoItemImages.create_item_images(session, image_list)
                await session.commit()

        return {
            "item_id": item_id,
            "uploaded_count": len(image_list),
            "records": [
                {
                    "image_id": image.id,
                    "image_url": image.image_url,
                    "filename": Path(image.image_url).name,
                }
                for image in image_list
            ],
            "message": "配件图片登记成功",
        }

    @classmethod
    def _safe_upload_filename(cls, filename: str | None, fallback: str = "image.bin") -> str:
        raw_name = Path(filename or fallback).name
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
        return safe_name or fallback

    @classmethod
    async def _delete_minio_object(cls, object_path: str) -> None:
        bucket, object_name = parse_minio_path(object_path, default_bucket=minio_bucket)

        def _delete():
            minio_instance.client.remove_object(bucket, object_name)

        await run_sync(_delete)

    @classmethod
    async def create_item_image_files(cls, item_id: int, files: list) -> dict:
        if len(files) == 0:
            raise Exception("未上传图片文件")

        ensure_minio_bucket(minio_bucket)

        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session, item_id)
            if item is None:
                raise Exception("配件不存在")

            uploaded_paths: list[str] = []
            image_rows: list[SgoItemImages] = []
            uploaded_filenames: list[str] = []

            try:
                for file in files:
                    safe_name = cls._safe_upload_filename(file.filename, fallback="image.jpg")
                    date_dir = datetime.now().strftime("%Y%m%d")
                    object_name = f"manual-upload/{item_id}/{date_dir}/{get_id()}_{safe_name}"
                    content_type = file.content_type or "application/octet-stream"

                    def _upload() -> int:
                        file.file.seek(0, os.SEEK_END)
                        size = file.file.tell()
                        file.file.seek(0)
                        minio_instance.client.put_object(
                            minio_bucket,
                            object_name,
                            file.file,
                            length=size,
                            content_type=content_type,
                        )
                        return size

                    await run_sync(_upload)
                    await file.close()

                    image_url = f"{minio_bucket}/{object_name}"
                    uploaded_paths.append(image_url)
                    uploaded_filenames.append(safe_name)
                    image_rows.append(
                        SgoItemImages(
                            item_id=item_id,
                            image_url=image_url,
                            raw_url=None,
                            image_source=ImageSourceType.CREATEBYSELF,
                            is_indexed=1,
                        )
                    )

                await SgoItemImages.create_item_images(session, image_rows)
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

    @classmethod
    async def get_image_from_oss(cls, image_url: str):
        """
        image_url格式为 {bucket_name}/{file_name}的格式
        """
        def _():
            file_name_arr = image_url.split("/")
            if len(file_name_arr) < 2:
                raise Exception(f'文件名格式不正确')

            aim_file_name = file_name_arr[1]

            try:
                response = minio_instance.client.get_object(
                    minio_bucket, aim_file_name)
                # Read data from response.
                if response.status != 200:
                    raise Exception(f'oss请求出错')

                if response.data:
                    nparr = np.frombuffer(response.data, np.uint8)
                    # 将数组解码为彩色图像
                    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    try:
                        image = cls.resize_image(image)
                        return image
                    except Exception as e:
                        pass

            finally:
                if response:
                    response.close()
                    response.release_conn()
        return await run_sync(_)

    @classmethod
    def resize_image(cls, image, max_size=1920):
        height, width = image.shape[:2]
        if max(height, width) > max_size:
            scale = max_size / max(height, width)
            new_height = int(height * scale)
            new_width = int(width * scale)
            image = cv2.resize(image, (new_width, new_height),
                               interpolation=cv2.INTER_AREA)
        return image

    @classmethod
    async def delete_item_features(cls, req: DeleteFeaturesReq):
        item_id = int(req.item_id)
        now_index_list = await MilvusManager.list_item_index([item_id])

        async with SessionLocal() as session:
            items = await Items.get_item_by_id(session, item_id)
            if items is None:
                raise Exception('配件信息不存在')

        if item_id not in now_index_list:
            raise Exception(f'特征数据库并没有该配件的索引信息')

        index = now_index_list[item_id]

        delete_feature_set = set(req.features)

        delete_feature_set.remove(items.item_name)

        new_feature_index_list: list[FeaturesIndex] = []

        for feature_index in index.features:
            if feature_index.feature not in delete_feature_set:
                new_feature_index_list.append(feature_index)

        index.features = new_feature_index_list  # 覆盖
        index.updated_at = date_to_str(datetime.now())
        await MilvusManager.upsert_data(index)
        async with SessionLocal() as session:
            await Items.update_items_index(session=session, item_id=item_id,
                                           image_index_num=len(index.images), feature_index_num=len(index.features))
            await session.commit()

    # @classmethod
    # async def update_item_features(cls, req: UpdateFeatureReq):
    #     await run_sync(MilvusManager.update_parts_feature, int(req.item_id), req.old_feature, req.new_feature)

    @classmethod
    async def create_item_index(cls, req: CreateItemImagesIndexReq):
        item_id = int(req.item_id)

        image_id_list = [int(img.image_id) for img in req.images]
        # image_dict = {int(img.image_id): img.image_url for img in req.images}
        if len(image_id_list) == 0:
            image_id_list.append(0)

        index_already_dic = await MilvusManager.list_item_index([int(req.item_id)])

        if item_id not in index_already_dic:
            if len(req.images) == 0:
                raise Exception(f'至少有一个图片索引')

        index_already = index_already_dic.get(int(req.item_id)) or PartsIndex(
            item_id=int(req.item_id), id=get_id(),
            
            created_at=date_to_str(datetime.now())
        )
        index_already.updated_at = date_to_str(datetime.now())
        images_already = set(
            [image.filename for image in index_already.images])
        feature_already = set([f.feature for f in index_already.features])

        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session, item_id)
            if item is None:
                raise Exception(f'配件不存在')
            
            index_already.item_name = item.item_name
            index_already.item_code = item.item_code

            images = await SgoItemImages.get_image_by_id_list(session, image_id_list)

            parent_item_id_list = [p.parent_item_id for p in await ItemsParent.list_parent_item_by_item_id(session, int(req.item_id))]
            index_already.parent_item_info = parent_item_id_list
            vechile_id_list = [p.vechile_id for p in await ItemsVechile.list_item_vechile_info_by_item_id(session, int(req.item_id))]
            index_already.vechile_info = vechile_id_list
            # 建立图片索引
        for need_index_image in req.images:
            img = await cls.get_image_from_oss(need_index_image.image_url)
            if img is None:
                raise Exception(f'加载图片出错')

            # 已经建立索引 直接跳过
            if need_index_image.image_url in images_already:
                continue
            image_vector = await MilvusManager.extract_image_tensor(img)
            image_index = ImageIndex(
                image_id=int(need_index_image.image_id),
                filename=need_index_image.image_url,
                image_vector=image_vector,
                image_index_created=date_to_str(datetime.now())
            )
            # images_index_list.append(image_index)
            index_already.images.append(image_index)

        if item.item_name not in feature_already:
            feature_vector = await MilvusManager.embedding_encode(item.item_name)
            feature_index = FeaturesIndex(
                feature=item.item_name,
                feature_vector=feature_vector,
                feature_index_created=date_to_str(datetime.now())
            )
            index_already.features.append(feature_index)

        # 建立文字特征索引
        for feature in req.features:
            # 已经建立索引 跳过
            if feature in feature_already:
                continue

            feature_vector = await MilvusManager.embedding_encode(feature)
            feature_index = FeaturesIndex(
                feature=feature,
                feature_vector=feature_vector,
                feature_index_created=date_to_str(datetime.now())
            )
            index_already.features.append(feature_index)

        # await MilvusManager.delete_part_index(int(req.item_id))
        # await MilvusManager.insert_part_index(index_already)
        await MilvusManager.upsert_data(index_already)
        async with SessionLocal() as session:
            await Items.update_items_index(session=session, item_id=item_id,
                                           image_index_num=len(index_already.images), feature_index_num=len(index_already.features))
            await session.commit()

    @classmethod
    async def insert_item_image_to_db(cls, item_id: int):
        async with SessionLocal() as session:
            images_gen = SgoItemImages.get_images(
                session=session, item_id=item_id)
            images_list = []
            async for image in images_gen:
                if image.is_indexed == 0:
                    images_list.append(image)
            if len(images_list) == 0:
                return
            await MilvusManager.insert_pic(images_list)

            # 修改已经索引的标志
            await SgoItemImages.indexed_image(session=session, image_id_list=[image.id for image in images_list])
            await session.commit()

    @classmethod
    async def image_search_to_item(cls, image_to_search: list[str], radius: float):
        res = ImageSearchRes()
        search_result = await MilvusManager.image_search(image_to_search, radius)

        if search_result is None or len(search_result) == 0:
            return res

        imageSearchItem_dict: dict[int, ImageSearchItem] = {}

        item_id_set = set()
        image_id_set = set()
        for res_item in search_result:
            item_id_set.add(res_item.item_id)
            image_id_set.add(res_item.image_id)
        item_dict: dict[int, Items] = {}
        image_dict: dict[int, SgoItemImages] = {}
        async with SessionLocal() as session:
            item_list = Items.get_item_by_id_list(
                session=session, item_id_list=list(item_id_set))
            images_list = await SgoItemImages.get_image_by_id_list(
                session=session, image_id_list=list(image_id_set))

            async for item in item_list:
                item_dict[item.id] = item

            for image in images_list:
                image_dict[image.id] = image

        for res_item in search_result:
            item = item_dict.get(res_item.item_id)
            image = image_dict.get(res_item.image_id)
            if item is None or image is None:
                logger.warning(f'配件id:{res_item.item_id}找不到')
                continue
            if res_item.item_id not in imageSearchItem_dict:
                imageSearchItem_dict[res_item.item_id] = ImageSearchItem(
                    item_name=item.item_name, obj_url=item.obj_url, item_code=item.item_code, parent_item_id=item.parent_item_id,
                    created_at=date_to_str(item.time_created),
                    id=str(res_item.item_id),
                    max_distance=res_item.distance,
                    image_url_distance={image.raw_url: res_item.distance}
                )
            else:
                search_item = imageSearchItem_dict[res_item.item_id]
                if res_item.distance > search_item.max_distance:
                    search_item.max_distance = res_item.distance
                search_item.image_url_distance[image.raw_url] = res_item.distance

        res.items = list(imageSearchItem_dict.values())
        return res

    @classmethod
    # rebuild_pic_index 方法已删除，请使用 rebuild_v2_index

    @classmethod
    async def statistics(cls):
        res = IndexStatisticsRes()
        async with SessionLocal() as session:
            res.total_item_num = await async_get_count(session, select(Items))

        state_manager = MilvusStateManagerV2()
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

    @classmethod
    def reciprocal_rank_fusion(search_results_list, k=60):
        """
        手动实现倒数排序融合（RRF）算法，合并多个搜索结果列表。

        :param search_results_list: 一个列表，每个元素是一次搜索返回的Hits对象列表。
        :param k: 平滑因子，默认为60。
        :return: 按RRF分数降序排列的 (文档ID, RRF分数) 元组列表。
        """
        fused_scores = {}

        # 遍历每一个独立的搜索结果列表
        for result_list in search_results_list:
            # 遍历当前列表中的每个结果及其排名（排名从1开始）
            for rank, hit in enumerate(result_list, start=1):
                doc_id = hit.id  # 假设hit.id是文档的唯一标识
                # 计算当前文档在当前列表中的RRF分数
                rrf_score = 1 / (rank + k)
                # 累加分数
                fused_scores[doc_id] = fused_scores.get(
                    doc_id, 0.0) + rrf_score

        # 根据融合后的总分进行降序排序
        final_ranking = sorted(fused_scores.items(),
                               key=lambda x: x[1], reverse=True)
        return final_ranking


    # ==================== 新向量数据库功能 (SigLIP + DINOv2) ====================
    
    @classmethod
    async def create_v2_collections(cls, drop_existing: bool = False):
        """
        创建新的向量数据库集合 (SigLIP + DINOv2)
        
        Args:
            drop_existing: 是否删除已存在的集合（默认 False）
        """
        manager = MilvusStateManagerV2()
        
        if drop_existing:
            logger.warning("删除已存在的集合...")
            await run_sync(manager.drop_collections)
            logger.info("已存在的集合已删除")
        
        await run_sync(manager.create_collections)
        logger.info("V2 collections created successfully")
    
    
    
    @classmethod
    async def rebuild_v2_index(
        cls,
        item_id: int = None,
        limit: int = None,
        rebuild_existing: bool = False,
    ):
        """
        使用新算法重建索引 (SigLIP + DINOv2)
        
        Args:
            item_id: 指定配件ID（可选，为空则重建所有）
            limit: 限制处理数量（可选，用于测试）
            rebuild_existing: 是否重建已存在的索引
        """
        
        manager = MilvusManagerV2()
        state_manager = MilvusStateManagerV2()
        
        async with SessionLocal() as session:
            # 获取需要建库的配件
            if item_id:
                items = [await Items.get_item_by_id(session, item_id)]
                if items[0] is None:
                    raise Exception(f'配件不存在: {item_id}')
            else:
                item_id_stmt = select(SgoItemImages.item_id).distinct()
                stmt = select(Items).where(Items.id.in_(item_id_stmt))
                if not rebuild_existing:
                    stmt = stmt.where(Items.has_v2_index == 0)
                stmt = stmt.order_by(Items.time_created.desc()).order_by(Items.id.desc())
                if limit is not None:
                    stmt = stmt.limit(limit)
                items = list(await session.scalars(stmt))
            
            logger.info(f"开始为 {len(items)} 个配件建立 V2 索引")
            
            success_count = 0
            fail_count = 0
            processed_item_count = 0
            skipped_existing_count = 0
            from tqdm import tqdm
            for item in tqdm(items):
                if item is None:
                    continue
                if not rebuild_existing and getattr(item, "has_v2_index", 0) == 1:
                    skipped_existing_count += 1
                    logger.info(f"跳过已存在索引的配件: item={item.id}")
                    continue

                try:
                    # 获取配件的图片
                    images_result = await SgoItemImages.list_item_images_by_item_id(session, item.id)
                    # 将 ScalarResult 转换为列表
                    images = list(images_result) if images_result else []
                    item_success_count = 0
                    success_image_ids: list[int] = []
                    segmented_records_to_create: list[SegmentedImage] = []
                    deleted_existing = False
                    image_status_changed = False
                    
                    if len(images) == 0:
                        logger.warning(f"配件 {item.id} 没有图片，跳过")
                        continue

                    if rebuild_existing and getattr(item, "has_v2_index", 0) == 1:
                        delete_result = state_manager.delete_item_index(item.id)
                        await SgoItemImages.un_indexed_image(
                            session=session,
                            image_id_list=[img.id for img in images],
                        )
                        await SegmentedImage.delete_by_item_id(session, item.id)
                        deleted_existing = True
                        image_status_changed = True
                        logger.info(
                            "强制重建前已删除旧索引: item=%s, siglip=%s, dinov2=%s",
                            item.id,
                            int(delete_result.get("siglip_deleted", 0) or 0),
                            int(delete_result.get("dinov2_deleted", 0) or 0),
                        )

                    processed_item_count += 1
                    
                    # 为每张图片建立索引
                    for img in images:
                        try:
                            # 从 MinIO 加载图片
                            image_array = await cls.get_image_from_oss(img.image_url)
                            if image_array is None:
                                logger.warning(f"图片加载失败: {img.image_url}")
                                continue
                            
                            # 转换 numpy array 为 PIL Image
                            from PIL import Image
                            import cv2
                            # cv2 读取的是 BGR 格式，需要转换为 RGB
                            image_rgb = cv2.cvtColor(image_array, cv2.COLOR_BGR2RGB)
                            pil_image = Image.fromarray(image_rgb)
                            
                            # 建立索引
                            siglip_ok, dinov2_ok = await manager.index_image(
                                image=pil_image,
                                item_id=item.id,
                                item_name=item.item_name,
                                item_code=item.item_code,
                                image_id=img.id,
                                image_url=img.image_url,
                                description=item.item_name
                            )

                            preprocess_outcome = getattr(
                                manager,
                                "last_preprocess_outcome",
                                None,
                            )
                            if preprocess_outcome is not None:
                                if preprocess_outcome.result_image is not None:
                                    try:
                                        segmented_url = await cls._upload_v2_segmented_image(
                                            preprocess_outcome.result_image,
                                            item.id,
                                            img.id,
                                        )
                                        segmented_records_to_create.append(
                                            SegmentedImage(
                                                id=get_id(),
                                                item_id=item.id,
                                                source_image_id=img.id,
                                                source_image_url=img.image_url,
                                                segmented_image_url=segmented_url,
                                                status=SegmentStatus.SUCCESS,
                                                is_indexed=1 if siglip_ok and dinov2_ok else 0,
                                            )
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            "保存分割图失败: item=%s, image=%s, error=%s",
                                            item.id,
                                            img.id,
                                            e,
                                        )
                                        segmented_records_to_create.append(
                                            SegmentedImage(
                                                id=get_id(),
                                                item_id=item.id,
                                                source_image_id=img.id,
                                                source_image_url=img.image_url,
                                                status=SegmentStatus.FAILED,
                                                is_indexed=0,
                                                error_message=str(e),
                                            )
                                        )
                                else:
                                    segmented_records_to_create.append(
                                        SegmentedImage(
                                            id=get_id(),
                                            item_id=item.id,
                                            source_image_id=img.id,
                                            source_image_url=img.image_url,
                                            status=SegmentStatus.FAILED,
                                            is_indexed=0,
                                            error_message="SAM3 preprocessing returned no segmented image",
                                        )
                                    )
                            
                            if siglip_ok and dinov2_ok:
                                success_count += 1
                                item_success_count += 1
                                success_image_ids.append(img.id)
                                logger.info(f"索引成功: item={item.id}, image={img.id}")
                            else:
                                fail_count += 1
                                logger.warning(f"索引部分失败: item={item.id}, siglip={siglip_ok}, dinov2={dinov2_ok}")
                        
                        except Exception as e:
                            fail_count += 1
                            logger.error(f"索引失败: item={item.id}, image={img.id}, error={e}")
                
                except Exception as e:
                    fail_count += 1
                    logger.error(f"处理配件失败: item={item.id}, error={e}")
                    continue

                if len(success_image_ids) > 0:
                    await SgoItemImages.indexed_image(
                        session=session,
                        image_id_list=success_image_ids,
                    )
                    image_status_changed = True

                if len(segmented_records_to_create) > 0:
                    await SegmentedImage.batch_create(session, segmented_records_to_create)
                    image_status_changed = True

                if image_status_changed:
                    await session.commit()

                if item_success_count > 0 or deleted_existing:
                    await cls.sync_item_v2_index_state(
                        item.id, state_manager=state_manager
                    )
            
            logger.info(f"V2 索引重建完成: 成功={success_count}, 失败={fail_count}")
            
            return {
                'success_count': success_count,
                'fail_count': fail_count,
                'total': success_count + fail_count,
                'processed_item_count': processed_item_count,
                'skipped_existing_count': skipped_existing_count,
            }

    @classmethod
    async def delete_v2_index(cls, item_id: int) -> dict:
        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session=session, item_id=item_id)
            if item is None:
                raise Exception(f'配件不存在: {item_id}')

        delete_result = MilvusStateManagerV2().delete_item_index(item_id)
        async with SessionLocal() as session:
            await Items.update_v2_index_state(
                session=session,
                item_id=item_id,
                has_v2_index=False,
                v2_indexed_image_num=0,
                updated_at=datetime.now(),
            )
            await session.commit()
        return {
            "item_id": item_id,
            "siglip_deleted": int(delete_result.get("siglip_deleted", 0) or 0),
            "dinov2_deleted": int(delete_result.get("dinov2_deleted", 0) or 0),
            "message": "V2索引删除成功",
        }

    @classmethod
    async def sync_all_v2_index_state(cls) -> dict:
        snapshot = MilvusStateManagerV2().get_item_index_state_snapshot()
        updated_at = datetime.now()
        rows = [
            {
                "item_id": item_id,
                "has_v2_index": state["has_v2_index"],
                "v2_indexed_image_num": state["v2_indexed_image_num"],
                "updated_at": updated_at,
            }
            for item_id, state in snapshot.items()
        ]

        async with SessionLocal() as session:
            await Items.reset_v2_index_state(session=session, updated_at=updated_at)
            if len(rows) > 0:
                await Items.bulk_update_v2_index_state(session=session, rows=rows)
            await session.commit()

        return {
            "indexed_item_count": len(rows),
            "updated_at": date_to_str(updated_at),
        }

    @classmethod
    async def sync_item_v2_index_state(
        cls,
        item_id: int,
        state_manager: MilvusStateManagerV2 | None = None,
    ):
        manager = state_manager or MilvusStateManagerV2()
        snapshot = manager.get_item_index_state_snapshot()
        state = snapshot.get(item_id, {"has_v2_index": 0, "v2_indexed_image_num": 0})
        updated_at = datetime.now()
        async with SessionLocal() as session:
            await Items.update_v2_index_state(
                session=session,
                item_id=item_id,
                has_v2_index=bool(state["has_v2_index"]),
                v2_indexed_image_num=state["v2_indexed_image_num"],
                updated_at=updated_at,
            )
            await session.commit()

    @classmethod
    async def _persist_v2_search_history(
        cls,
        *,
        history_id: int,
        query_text: str | None,
        query_image: str | None,
        search_equipment: str,
        search_items: list[SearchItem],
    ) -> None:
        top1 = search_items[0] if search_items else None
        search_results = SearchResults(
            items=[
                SearchResultItem(
                    item_id=str(item.item_id),
                    item_code=item.item_code,
                    item_name=item.item_name,
                    similar=item.rate,
                    image_url=item.image_url,
                    matched_images=[
                        MatchedImage(image_url=matched.image_url, rate=matched.rate)
                        for matched in item.matched_images
                    ],
                )
                for item in search_items
            ]
        )

        try:
            async with SessionLocal() as session:
                session.add(
                    SearchHistory(
                        id=history_id,
                        inquery_id=None,
                        inquery_num=None,
                        search_result_item_name=top1.item_name if top1 else None,
                        search_result_item_code=top1.item_code if top1 else "",
                        search_parameter=None,
                        query_text=query_text,
                        query_image=query_image,
                        search_equipment=search_equipment,
                        verify_status="pending",
                        verify_remark=None,
                        verified_at=None,
                        correct_item_name=None,
                        correct_item_code=None,
                        search_results=search_results,
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("V2检索历史写入失败")

    @classmethod
    def _aggregate_v2_search_items(cls, search_items: list[SearchItem]) -> list[SearchItem]:
        grouped: dict[str, dict] = {}

        for index, item in enumerate(search_items):
            bucket = grouped.setdefault(
                str(item.item_id),
                {
                    "best_item": item,
                    "first_index": index,
                    "matched_images": [],
                },
            )
            bucket["matched_images"].append(
                (index, MatchedImage(image_url=item.image_url, rate=item.rate))
            )
            if item.rate > bucket["best_item"].rate:
                bucket["best_item"] = item

        aggregated_items: list[SearchItem] = []
        for item_id, bucket in grouped.items():
            best_item = bucket["best_item"]
            matched_images = [
                image
                for _, image in sorted(
                    bucket["matched_images"],
                    key=lambda pair: (-pair[1].rate, pair[0]),
                )
            ]
            aggregated_items.append(
                SearchItem(
                    item_id=str(item_id),
                    item_code=best_item.item_code,
                    item_name=best_item.item_name,
                    image_url=best_item.image_url,
                    rate=best_item.rate,
                    matched_images=matched_images,
                )
            )

        aggregated_items.sort(
            key=lambda item: (-item.rate, grouped[str(item.item_id)]["first_index"])
        )
        return aggregated_items

    @classmethod
    def _normalize_review_status(cls, status: str | None) -> str:
        if status == "partial":
            return "wrong"
        return status or "pending"

    @classmethod
    def _build_search_history_item(cls, row, latest_ticket=None):
        if row.query_image:
            search_type = "image"
        elif row.query_text:
            search_type = "text"
        else:
            search_type = "unknown"

        has_open_review_ticket = False
        latest_ticket_id = None
        latest_review_status = None
        latest_issue_type = None
        if latest_ticket is not None:
            has_open_review_ticket = getattr(latest_ticket, "review_status", None) != "closed"
            latest_ticket_id = getattr(latest_ticket, "id", None)
            latest_review_status = getattr(latest_ticket, "review_status", None)
            latest_issue_type = getattr(latest_ticket, "issue_type", None)

        return SearchHistoryListItem(
            history_id=row.id,
            search_type=search_type,
            time_created=date_to_str(row.time_created),
            query_text=row.query_text,
            query_image=row.query_image,
            search_equipment=getattr(row, "search_equipment", None),
            status=cls._normalize_review_status(getattr(row, "verify_status", None)),
            result=row.search_results,
            inquery_id=row.inquery_id,
            inquery_num=row.inquery_num,
            search_item_name=row.search_result_item_name,
            search_item_code=row.search_result_item_code,
            correct_item_name=row.correct_item_name,
            correct_item_code=row.correct_item_code,
            feedback_remark=getattr(row, "verify_remark", None),
            feedback_at=date_to_str(row.verified_at) if getattr(row, "verified_at", None) else None,
            verify_remark=getattr(row, "verify_remark", None),
            verified_at=date_to_str(row.verified_at) if getattr(row, "verified_at", None) else None,
            has_open_review_ticket=has_open_review_ticket,
            latest_ticket_id=str(latest_ticket_id) if latest_ticket_id is not None else None,
            latest_review_status=latest_review_status,
            latest_issue_type=latest_issue_type,
        )

    @classmethod
    def _build_search_review_ticket_item(cls, row):
        return SearchReviewTicketItem(
            ticket_id=row.id,
            history_id=row.history_id,
            review_status=row.review_status,
            issue_type=row.issue_type,
            time_created=date_to_str(row.time_created),
            time_updated=date_to_str(row.time_updated),
            query_text=getattr(row, "query_text", None),
            query_image=getattr(row, "query_image", None),
            search_equipment=getattr(row, "search_equipment", None),
            search_item_name=getattr(row, "search_result_item_name", None),
            search_item_code=getattr(row, "search_result_item_code", None),
            feedback_remark=getattr(row, "verify_remark", None),
            correct_item_name=getattr(row, "correct_item_name", None),
            correct_item_code=getattr(row, "correct_item_code", None),
        )

    @classmethod
    def _build_search_review_ticket_detail(cls, ticket, history):
        return SearchReviewTicketDetailRes(
            ticket_id=ticket.id,
            history_id=ticket.history_id,
            review_status=ticket.review_status,
            issue_type=ticket.issue_type,
            review_remark=ticket.review_remark,
            resolution_remark=ticket.resolution_remark,
            review_started_at=date_to_str(ticket.review_started_at) if ticket.review_started_at else None,
            resolved_at=date_to_str(ticket.resolved_at) if ticket.resolved_at else None,
            closed_at=date_to_str(ticket.closed_at) if ticket.closed_at else None,
            query_text=getattr(history, "query_text", None),
            query_image=getattr(history, "query_image", None),
            search_equipment=getattr(history, "search_equipment", None),
            result=getattr(history, "search_results", None),
            search_item_name=getattr(history, "search_result_item_name", None),
            search_item_code=getattr(history, "search_result_item_code", None),
            feedback_remark=getattr(history, "verify_remark", None),
            correct_item_name=getattr(history, "correct_item_name", None),
            correct_item_code=getattr(history, "correct_item_code", None),
        )

    @classmethod
    async def _enrich_search_history_result_item_names(cls, session, rows) -> None:
        missing_items = []
        item_id_set = set()

        for row in rows:
            search_results = getattr(row, "search_results", None)
            if search_results is None:
                continue

            for result_item in search_results.items:
                if getattr(result_item, "item_name", None):
                    continue
                try:
                    item_id = int(result_item.item_id)
                except (TypeError, ValueError):
                    continue
                item_id_set.add(item_id)
                missing_items.append(result_item)

        if not item_id_set:
            return

        item_name_map = {}
        async for item in Items.get_item_by_id_list(session=session, item_id_list=list(item_id_set)):
            item_name_map[int(item.id)] = item.item_name

        for result_item in missing_items:
            try:
                item_id = int(result_item.item_id)
            except (TypeError, ValueError):
                continue
            item_name = item_name_map.get(item_id)
            if item_name:
                result_item.item_name = item_name

    @classmethod
    async def list_v2_search_history(cls, req: SearchHistoryListReq):
        async with SessionLocal() as session:
            page_result = await SearchHistory.list_search_history(
                session=session,
                page=req.page,
                per_page=req.per_page,
                search_type=req.search_type,
                search_equipment=req.search_equipment,
                keyword=req.keyword,
                status=req.status,
                date_from=req.date_from,
                date_to=req.date_to,
            )
            await cls._enrich_search_history_result_item_names(session, page_result.data)
            latest_ticket_map = await SearchReviewTicket.list_latest_by_history_ids(
                session,
                [int(row.id) for row in page_result.data],
            )

        return SearchHistoryListRes(
            total=page_result.total,
            page=req.page,
            pageSize=req.per_page,
            items=[
                cls._build_search_history_item(row, latest_ticket_map.get(int(row.id)))
                for row in page_result.data
            ],
        )

    @classmethod
    async def get_v2_search_history_detail(cls, history_id: int):
        async with SessionLocal() as session:
            row = await SearchHistory.get_history_by_id(session, history_id)
            if row is not None:
                await cls._enrich_search_history_result_item_names(session, [row])
                latest_ticket_map = await SearchReviewTicket.list_latest_by_history_ids(session, [history_id])
                latest_ticket = latest_ticket_map.get(history_id)
            else:
                latest_ticket = None

        if row is None:
            raise Exception(f"history_id={history_id} 的记录不存在")

        return cls._build_search_history_item(row, latest_ticket)

    @classmethod
    async def summary_v2_search_history(cls):
        async with SessionLocal() as session:
            result = await SearchHistory.summarize_review_status(session)
            open_ticket_count = await SearchReviewTicket.count_open_tickets(session)

        total, pending_count, correct_count, wrong_count = result.one()
        return SearchHistorySummaryRes(
            total=int(total or 0),
            pending_count=int(pending_count or 0),
            correct_count=int(correct_count or 0),
            wrong_count=int(wrong_count or 0),
            open_ticket_count=int(open_ticket_count or 0),
        )

    @classmethod
    async def list_v2_search_review_tickets(cls, req: SearchReviewTicketListReq):
        async with SessionLocal() as session:
            page_result = await SearchReviewTicket.list_tickets(
                session,
                page=req.page,
                per_page=req.per_page,
                review_status=req.review_status,
                issue_type=req.issue_type,
                search_equipment=req.search_equipment,
                keyword=req.keyword,
                date_from=req.date_from,
                date_to=req.date_to,
            )

        return SearchReviewTicketListRes(
            total=page_result.total,
            page=req.page,
            pageSize=req.per_page,
            items=[cls._build_search_review_ticket_item(row) for row in page_result.data],
        )

    @classmethod
    async def get_v2_search_review_ticket_detail(cls, ticket_id: int):
        async with SessionLocal() as session:
            ticket = await SearchReviewTicket.get_by_id(session, ticket_id)
            if ticket is None:
                raise Exception(f"ticket_id={ticket_id} 的记录不存在")

            history = await SearchHistory.get_history_by_id(session, int(ticket.history_id))
            if history is None:
                raise Exception(f"history_id={ticket.history_id} 的记录不存在")

            await cls._enrich_search_history_result_item_names(session, [history])

        return cls._build_search_review_ticket_detail(ticket, history)

    @classmethod
    async def summary_v2_search_review_ticket(cls):
        async with SessionLocal() as session:
            result = await SearchReviewTicket.summarize_tickets(session)

        total, open_count, reviewing_count, resolved_count, closed_count, missing_index_count, precision_issue_count, system_bug_count = result.one()
        return SearchReviewTicketSummaryRes(
            total=int(total or 0),
            open_count=int(open_count or 0),
            reviewing_count=int(reviewing_count or 0),
            resolved_count=int(resolved_count or 0),
            closed_count=int(closed_count or 0),
            missing_index_count=int(missing_index_count or 0),
            precision_issue_count=int(precision_issue_count or 0),
            system_bug_count=int(system_bug_count or 0),
        )

    @classmethod
    async def update_v2_search_review_ticket(
        cls,
        *,
        ticket_id: int,
        review_status: str,
        issue_type: str | None,
        review_remark: str | None,
        resolution_remark: str | None,
        correct_item_code: str | None,
    ):
        allowed_review_status = {"reviewing", "resolved", "closed"}
        allowed_issue_types = {None, "missing_index", "precision_issue", "system_bug"}
        if review_status not in allowed_review_status:
            raise Exception(f"review_status={review_status} 不支持")
        if issue_type not in allowed_issue_types:
            raise Exception(f"issue_type={issue_type} 不支持")

        now = datetime.now()
        correct_item_name = None

        async with SessionLocal() as session:
            ticket = await SearchReviewTicket.get_by_id(session, ticket_id)
            if ticket is None:
                raise Exception(f"ticket_id={ticket_id} 的记录不存在")

            history = None
            if correct_item_code:
                item = await Items.get_item_by_item_code(session, correct_item_code)
                if item is None:
                    raise Exception(f"物料编码 {correct_item_code} 不存在")
                correct_item_name = item.item_name
                history = await SearchHistory.get_history_by_id(session, int(ticket.history_id))
                if history is None:
                    raise Exception(f"history_id={ticket.history_id} 的记录不存在")

                await SearchHistory.update_review_result(
                    session,
                    int(ticket.history_id),
                    verify_status="wrong",
                    correct_item_code=correct_item_code,
                    correct_item_name=correct_item_name,
                    verify_remark=resolution_remark or review_remark,
                    verified_at=now,
                )

            review_started_at = ticket.review_started_at
            resolved_at = ticket.resolved_at
            closed_at = ticket.closed_at
            if review_status == "reviewing":
                review_started_at = review_started_at or now
                resolved_at = None
                closed_at = None
            elif review_status == "resolved":
                review_started_at = review_started_at or now
                resolved_at = now
                closed_at = None
            elif review_status == "closed":
                closed_at = now

            await SearchReviewTicket.update_ticket(
                session,
                ticket_id,
                review_status=review_status,
                issue_type=issue_type,
                review_remark=review_remark,
                resolution_remark=resolution_remark,
                review_started_at=review_started_at,
                resolved_at=resolved_at,
                closed_at=closed_at,
            )
            await session.commit()

        return SearchReviewTicketUpdateRes(
            ticket_id=ticket_id,
            review_status=review_status,
            issue_type=issue_type,
            review_remark=review_remark,
            resolution_remark=resolution_remark,
            correct_item_code=correct_item_code,
            correct_item_name=correct_item_name,
            message="核验单更新成功",
        )

    @classmethod
    async def verify_v2_search_history(
        cls,
        *,
        history_id: int,
        verify_status: str,
        correct_item_code: str | None,
        remark: str | None,
    ):
        verified_at = datetime.now()

        async with SessionLocal() as session:
            history = await SearchHistory.get_history_by_id(session, history_id)
            if history is None:
                raise Exception(f"history_id={history_id} 的记录不存在")

            if verify_status == "correct" and not correct_item_code:
                correct_item_code = history.search_result_item_code
                correct_item_name = history.search_result_item_name
            elif correct_item_code:
                item = await Items.get_item_by_item_code(session, correct_item_code)
                if item is None:
                    raise Exception(f"物料编码 {correct_item_code} 不存在")
                correct_item_name = item.item_name
            else:
                correct_item_name = None

            await SearchHistory.update_review_result(
                session,
                history_id,
                verify_status=verify_status,
                correct_item_code=correct_item_code,
                correct_item_name=correct_item_name,
                verify_remark=remark,
                verified_at=verified_at,
            )
            await session.commit()

        return SearchHistoryVerifyRes(
            history_id=str(history_id),
            status=verify_status,
            correct_item_code=correct_item_code,
            correct_item_name=correct_item_name,
            verify_remark=remark,
            verified_at=date_to_str(verified_at),
            message="校验提交成功",
        )

    @classmethod
    async def suggest_items(cls, keyword: str, limit: int = 10):
        async with SessionLocal() as session:
            rows = await Items.suggest_items(session, keyword=keyword, limit=limit)

        return ItemSuggestRes(
            items=[
                ItemSuggestItem(
                    item_id=str(row.id),
                    item_code=row.item_code,
                    item_name=row.item_name,
                )
                for row in rows
            ]
        )

    @classmethod
    async def delete_v2_search_history(cls, history_id_list: list[int]):
        async with SessionLocal() as session:
            rows = await SearchHistory.delete_history_with_query_images(session, history_id_list)
            await session.commit()

        for history_id, query_image in rows:
            if not query_image:
                continue
            try:
                bucket, object_name = parse_minio_path(
                    query_image,
                    default_bucket=minio_search_history_bucket,
                )
                minio_instance.client.remove_object(bucket, object_name)
            except Exception as exc:
                logger.warning(
                    "删除检索历史查询图失败: history_id=%s, path=%s, error=%s",
                    history_id,
                    query_image,
                    exc,
                )

        return SearchHistoryDeleteRes(
            deleted_count=len(rows),
            message="检索历史删除成功",
        )
    
    @classmethod
    async def search_v2_by_text(
        cls,
        query_text: str,
        top_k: int = 10,
        search_equipment: str = "web",
    ):
        """
        使用新算法进行文本检索
        
        Args:
            query_text: 查询文本
            top_k: 返回结果数量
        
        Returns:
            检索结果列表
        """
        history_id = get_id()
        
        manager = MilvusManagerV2()
        results = await manager.search_by_text(
            text=query_text,
            top_k=top_k,
            # use_image_vector=use_image_vector
        )
        
        # 转换为标准格式
        search_items = []
        async with SessionLocal() as session:
            for result in results:
                item_id = result['entity']['item_id']
                image_url = result['entity']['image_url']
                item = await Items.get_item_by_id(session, item_id)
                if item:
                    search_items.append(SearchItem(
                        item_id=str(item.id),
                        item_code=item.item_code,
                        item_name=item.item_name,
                        image_url=image_url,
                        rate=result['distance']
                    ))
        search_items = cls._aggregate_v2_search_items(search_items)
        await cls._persist_v2_search_history(
            history_id=history_id,
            query_text=query_text,
            query_image=None,
            search_equipment=search_equipment,
            search_items=search_items,
        )
        return SearchRes(history_id=str(history_id), data=search_items)
 
    @classmethod
    async def search_v2_by_image(
        cls,
        file,
        top_k: int = 10,
        search_mode: str = "hybrid",
        search_equipment: str = "web",
    ):
        """
        使用新算法进行图像检索
        
        Args:
            file: 上传的图片文件（FastAPI UploadFile 对象）
            top_k: 返回结果数量
            search_mode: 检索模式 ("siglip", "dinov2", "hybrid")
        
        Returns:
            检索结果列表
        """
        from PIL import Image
        history_id = get_id()
        upload_filename = getattr(file, "filename", "") or ""
        
        # 读取上传的文件
        contents = await file.read()
        query_image = None
        try:
            query_image = await cls._upload_v2_search_query_image(
                history_id=history_id,
                filename=upload_filename,
                content_bytes=contents,
            )
        except Exception as exc:
            logger.warning(
                "保存V2检索查询图失败: filename=%s, error=%s",
                upload_filename,
                exc,
            )
        
        # 将字节流转换为 PIL Image
        pil_image = Image.open(io.BytesIO(contents)).convert('RGB')
        
        manager = MilvusManagerV2()
        results = await manager.search_by_image(
            image=pil_image,
            top_k=top_k,
            mode=search_mode,
            coarse_top_k=50,
            alpha=0.6
        )
        
        # 转换为标准格式
        search_items = []
        async with SessionLocal() as session:
            for result in results:
                item_id = result['entity']['item_id']
                image_url = result['entity'].get('image_url', '')
                item_name = result['entity'].get('item_name', '')
                item_code = result['entity'].get('item_code', '')
                
                # 如果 Milvus 中没有 item_name，则从数据库查询
                if not item_name:
                    item = await Items.get_item_by_id(session, item_id)
                    if item:
                        item_name = item.item_name
                        item_code = item.item_code
                
                search_items.append(SearchItem(
                    item_id=str(item_id),
                    item_code=item_code,
                    item_name=item_name,
                    image_url=image_url,
                    rate=result['distance']
                ))
        search_items = cls._aggregate_v2_search_items(search_items)
        await cls._persist_v2_search_history(
            history_id=history_id,
            query_text=None,
            query_image=query_image,
            search_equipment=search_equipment,
            search_items=search_items,
        )
        return SearchRes(history_id=str(history_id), data=search_items)

    @classmethod
    async def submit_v2_search_feedback(
        cls,
        *,
        history_id: int,
        feedback_result: str,
        remark: str | None,
    ):
        if feedback_result not in {"correct", "wrong"}:
            raise Exception("feedback_result 仅支持 correct 或 wrong")

        feedback_at = datetime.now()
        ticket_id = None
        ticket_created = False

        async with SessionLocal() as session:
            history = await SearchHistory.get_history_by_id(session, history_id)
            if history is None:
                raise Exception(f"history_id={history_id} 的记录不存在")

            active_ticket = await SearchReviewTicket.get_active_by_history_id(session, history_id)
            if feedback_result == "correct" and active_ticket is not None:
                raise Exception("当前记录已进入技术部核验流程，暂不支持改回正确")

            await SearchHistory.update_feedback(
                session,
                history_id,
                verify_status=feedback_result,
                verify_remark=remark,
                verified_at=feedback_at,
            )

            if feedback_result == "wrong":
                if active_ticket is None:
                    active_ticket = await SearchReviewTicket.create_ticket(
                        session,
                        ticket_id=get_id(),
                        history_id=history_id,
                    )
                    ticket_created = True
                ticket_id = active_ticket.id

            await session.commit()

        return SearchHistoryFeedbackRes(
            history_id=history_id,
            verify_status=feedback_result,
            feedback_remark=remark,
            feedback_at=date_to_str(feedback_at),
            ticket_id=ticket_id,
            ticket_created=ticket_created,
            message="用户反馈提交成功",
        )
