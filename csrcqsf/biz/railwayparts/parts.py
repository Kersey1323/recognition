"""
业务逻辑层 - 配件管理核心业务
职责：实现具体的业务逻辑、算法调用、数据处理
注意：此层包含核心业务实现，调用数据层和算法模块
"""
from datetime import datetime
import json
from csrcqsf.models.item import *
from bfrcommon.snowflake import get_id
from csrcqsf.data.pg import SessionLocal
from csrcqsf.data.mdpdb import sgo_sessionLocal
from csrcqsf.data.minio import minio_instance
from csrcqsf.models.search_history import SearchParameters, SearchHistory
from csrcqsf.models.sgo_models import SgoMaterielMasterplate
# 导入Milvus向量检索管理器
from .milvus import MilvusManager, ImageIndex, PartsIndex, FeaturesIndex, ColletionEnum
from .api_models import *
from bfrcommon.common import date_to_str
from csrcqsf.logger import logger
from csrcqsf.models.sgo import ListInqueryItem, SgoItemImages, ImageSourceType
import numpy as np
import cv2
from anyio.to_thread import run_sync
from csrcqsf.data.milvus import milvus_client
from pymilvus import Function, FunctionType
from pymilvus import AnnSearchRequest
from pymilvus.client.embedding_list import EmbeddingList
from csrcqsf.settings import ai_settings,minio_bucket
from sqlalchemy import func
from .vector_db.storage.milvus_manager import MilvusManagerV2

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
    async def create_item(cls, item_name: str, item_code: str, obj_url: str = None, height: float = None, length: float = None, width: float = None):
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
    async def update_item(cls, item_id: int, item_name: str, item_code: str, parent_item_id: int = None,
                          obj_url: str = None, length: float = None, width: float = None, height: float = None):
        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session=session, item_id=item_id)
            if item is None:
                raise Exception(f'id为{item_id}的配件不存在')

            if item.item_code != item_code:
                # item_code 修改
                item_by_code = Items.get_item_by_item_code(item_code=item_code)
                if item_by_code is not None:
                    raise Exception(f"物料编码:{item_code}已经存在了")

            if parent_item_id is not None:
                item = await Items.get_item_by_id(session=session, item_id=parent_item_id)
                if item is None:
                    raise Exception(f'id为{item_id}的父配件不存在')

            await Items.put_item(session=session, item_id=item_id, item_name=item_name,
                                 item_code=item_code, parent_item_id=parent_item_id, length=length, width=width, height=height, obj_url=obj_url)
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
            items = await Items.list_items(session=session,  query=req.query, page=req.page, per_page=req.per_page,
                                           has_images=images_has,
                                           item_id_list=item_id_list, item_code_list=item_code_list,need_index=has_index_flag)

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
                    obj_url=item.obj_url,
                    height=item.height,
                    width=item.width,
                    length=item.long,
                    id=str(item.id),
                    created_at=date_to_str(item.time_created)
                )
                if item.id in images_dict:
                    item_desc.images_total_num = len(images_dict[item.id])

                index = index_dict.get(item.id)
                if index is not None:
                    item_desc.images_total_indexed_num = len(index.images)
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
    async def update_item_size(cls, item_id: int, item_size_str: str):
        async with SessionLocal() as session:
            await Items.put_item_size_desc(session=session, item_id=item_id, size_desc=item_size_str)
            await session.commit()

    @classmethod
    async def get_item_detail(cls, item_id: int):

        index_detail = await MilvusManager.list_item_index([item_id])

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
            res = GetItemDetailRes(
                obj_url=item.obj_url,
                id=str(item.id),
                height=item.height,
                width=item.width,
                length=item.long,
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
            image_index_info = []
            if index_detail.get(item_id) is not None:
                image_index_info = index_detail.get(item_id).images

            image_index_dict: dict[int, ImageIndex] = {
                image.image_id: image for image in image_index_info}

            for index in image_index_info:
                res.images_index_list.append(
                    ItemImageIndexInfo(
                        image_id=str(index.image_id),
                        image_url=index.filename
                    )
                )
            async for image in images:
                image_item = ItemImageItem(
                    image_id=str(image.id),
                    has_indexed=False,
                    image_raw_url=image.image_url,
                    source_type=image.image_source
                )
                if image.id in image_index_dict:
                    image_item.has_indexed = True
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

            if len(image_list) == 0:
                return

            await SgoItemImages.create_item_images(session, image_list)
            await session.commit()

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
            stmt = select(Items)
            res.total_item_num = await async_get_count(session, stmt)

            stmt = select(Items).where(Items.feature_index_num.__gt__(0).__and__(Items.image_index_num.__gt__(0)))
            res.total_indexed_item_num = await async_get_count(session,stmt)

            stmt = select(func.sum(Items.image_index_num),func.sum(Items.feature_index_num)).where(Items.feature_index_num.__gt__(0).__and__(Items.image_index_num.__gt__(0)))
            indexed_num_res = await session.execute(stmt)
            data = indexed_num_res.first()
            res.total_feature_index = data[1]
            res.total_image_index = data[0]
            res.total_index = res.total_feature_index + res.total_image_index
            stmt = select(SearchHistory)
            res.recognition_number = await async_get_count(session, stmt)
            stmt = select(SearchHistory).where(SearchHistory.correct_item_code == SearchHistory.search_result_item_code)
            res.corrrect_recognition_number = await async_get_count(session, stmt)
            if res.recognition_number != 0:
                res.recognition_ration = res.corrrect_recognition_number/res.recognition_number
            
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
        manager = MilvusManagerV2()
        
        if drop_existing:
            logger.warning("删除已存在的集合...")
            await run_sync(manager.drop_collections)
            logger.info("已存在的集合已删除")
        
        await run_sync(manager.create_collections)
        logger.info("V2 collections created successfully")
    
    
    
    @classmethod
    async def rebuild_v2_index(cls, item_id: int = None, limit: int = None):
        """
        使用新算法重建索引 (SigLIP + DINOv2)
        
        Args:
            item_id: 指定配件ID（可选，为空则重建所有）
            limit: 限制处理数量（可选，用于测试）
        """
        
        manager = MilvusManagerV2()
        
        async with SessionLocal() as session:
            # 获取需要建库的配件
            if item_id:
                items = [await Items.get_item_by_id(session, item_id)]
                if items[0] is None:
                    raise Exception(f'配件不存在: {item_id}')
            else:
                result = await Items.list_items(
                    session=session,
                    query='',
                    page=1,
                    per_page=limit or 10000,
                    has_images=True
                )
                items = result.data
            
            logger.info(f"开始为 {len(items)} 个配件建立 V2 索引")
            
            success_count = 0
            fail_count = 0
            from tqdm import tqdm
            for item in tqdm(items):
                try:
                    # 获取配件的图片
                    images_result = await SgoItemImages.list_item_images_by_item_id(session, item.id)
                    # 将 ScalarResult 转换为列表
                    images = list(images_result) if images_result else []
                    
                    if len(images) == 0:
                        logger.warning(f"配件 {item.id} 没有图片，跳过")
                        continue
                    
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
                            
                            if siglip_ok and dinov2_ok:
                                success_count += 1
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
            
            logger.info(f"V2 索引重建完成: 成功={success_count}, 失败={fail_count}")
            
            return {
                'success_count': success_count,
                'fail_count': fail_count,
                'total': success_count + fail_count
            }
    
    @classmethod
    async def search_v2_by_text(cls, query_text: str, top_k: int = 10):
        """
        使用新算法进行文本检索
        
        Args:
            query_text: 查询文本
            top_k: 返回结果数量
        
        Returns:
            检索结果列表
        """
       
        
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
        
        return SearchRes(data=search_items)
 
    @classmethod
    async def search_v2_by_image(
        cls,
        file,
        top_k: int = 10,
        search_mode: str = "hybrid"
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
        import io
        
        # 读取上传的文件
        contents = await file.read()
        
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
        
        return SearchRes(data=search_items)
