"""
服务层 - 配件管理API路由
职责：定义API接口、参数验证、调用业务逻辑
注意：此层不包含具体业务实现，仅负责路由和参数处理
"""
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form, Request
from csrcqsf.biz.railwayparts.api_models import *
from bfrcommon.snowflake import get_id
from bfrcommon.common import date_to_str
from csrcqsf.models.sgo import SgoItemImages
from csrcqsf.models.reconstruction import ReconstructionRecord
from csrcqsf.data.pg import SessionLocal
from csrcqsf.settings import ai_settings
# 导入业务逻辑层
from csrcqsf.biz.railwayparts.parts import RailwayPartsManager
from csrcqsf.biz.railwayparts.milvus import MilvusManager
from csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager import (
    MilvusStateManagerV2,
)
from anyio.to_thread import run_sync

# 配件管理路由器
parts_router = APIRouter(
    prefix="/railway/parts",
    tags=["railway"],
    # dependencies=[Depends(get_token_header)],
    responses={404: {"description": "Not found"}},
)



# ============================================
# 配件基础管理接口
# ============================================

@parts_router.post('/item',  tags=["业务-配件管理"], summary='创建配件实体', responses={
    200: {
        'model': str
    }
})
async def create_item(req: CreateItemReq):
    """
    创建配件实体
    
    服务层职责：接收HTTP请求，验证参数，调用业务逻辑
    业务逻辑：RailwayPartsManager.create_item() in biz/railwayparts/parts.py
    """
    await RailwayPartsManager.create_item(item_name=req.item_name, item_code=req.item_code, obj_url=req.obj_url,
                                          height=req.height, length=req.length, width=req.width, weight=req.weight)


@parts_router.post('/item_delete',  tags=["业务-配件管理"], summary='删除配件实体', responses={
    200: {
        'model': str
    }
})
async def delete_item(req: DeleteItemReq):
    """
    删除配件实体
    
    业务逻辑：RailwayPartsManager.delete_item() in biz/railwayparts/parts.py
    """
    item_id_list = [int(item_id) for item_id in (req.item_id_list)]
    await RailwayPartsManager.delete_item(item_id_list=item_id_list)


@parts_router.post('/item_put',  tags=["业务-配件管理"], summary='修改配件实体描述', responses={
    200: {
        'model': str
    }
})
async def put_item(req: UpdateItemReq):
    update_fields = set(req.__fields_set__)
    update_fields.discard("id")
    if "parent_item_id" in update_fields and req.parent_item_id is None:
        update_fields.remove("parent_item_id")

    await RailwayPartsManager.update_item(
        item_id=int(req.id),
        update_fields=update_fields,
        item_name=req.item_name,
        item_code=req.item_code,
        parent_item_id=int(req.parent_item_id) if req.parent_item_id is not None else None,
        length=req.length,
        width=req.width,
        height=req.height,
        weight=req.weight,
    )


@parts_router.post('/item/size_put',  tags=["业务-配件管理"], summary='修改配件3D模型的尺寸描述', responses={
    200: {
        'model': str
    }
})
async def put_item_size_desc(req: UpdateItemSizeStr):
    await RailwayPartsManager.update_item_size(item_id=int(req.item_id), item_size_str=req.item_size_desc)


@parts_router.post('/list_items',  tags=["业务-配件管理"], summary='列出配件列表', responses={
    200: {
        'model': LisItemRes
    }
})
async def list_items(req: ListItemReq):

    return await RailwayPartsManager.list_item(req)


@parts_router.post('/create_item_image',  tags=["业务-图片管理"], summary='为配件上传图片', responses={
    200: {
        'model': CreateItemImagesRes
    }
})
async def create_item_image(
    request: Request,
    item_id: str | None = Form(None),
    files: list[UploadFile] | None = File(None),
):
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        if item_id is None:
            raise Exception("item_id不能为空")
        result = await RailwayPartsManager.create_item_image_files(int(item_id), files or [])
        return CreateItemImagesRes(**result)

    payload = await request.json()
    req = CreateItemImagesReq(**payload)
    result = await RailwayPartsManager.create_item_image(int(req.item_id), image_url_list=req.images_url)
    return CreateItemImagesRes(**result)


@parts_router.post('/item_image_indexed',  tags=["算法-特征索引"], summary='为配件建立索引,可以是原图，也可以是裁剪后的照片', deprecated=True, responses={
    200: {
        'model': str
    }
})
async def create_item_image_index(req: CreateItemImagesIndexReq):
    await RailwayPartsManager.create_item_index(req)


@parts_router.post('/get_item_details',  tags=["业务-配件管理"], summary='获取配件的详细信息', responses={
    200: {
        'model': GetItemDetailRes
    }
})
async def get_item_image_detail(req: GetItemDetailReq):
    return await RailwayPartsManager.get_item_detail(int(req.item_id))


@parts_router.post('/update_item_features',  tags=["业务-特征管理"], summary='修改配件文字特征', deprecated=True, responses={
    200: {
        'model': str
    }
})
async def update_item_features(req: UpdateFeatureReq):
    await RailwayPartsManager.update_item_features(req)


@parts_router.post('/delete_item_features',  tags=["业务-特征管理"], summary='删除配件文字特征', deprecated=True, responses={
    200: {
        'model': str
    }
})
async def delete_item_features(req: DeleteFeaturesReq):
    await RailwayPartsManager.delete_item_features(req)


@parts_router.post('/delete_item_image_index',  tags=["业务-图片管理"], summary='删除配件图片索引', deprecated=True, responses={
    200: {
        'model': str
    }
})
async def delete_item_image_index(req: DeleteImageIndexedReq):
    await RailwayPartsManager.delete_item_image_index(int(req.item_id), req.image_file_url)


@parts_router.post('/list_item_features',  tags=["业务-特征管理"], summary='列出当前配件的features', deprecated=True, responses={
    200: {
        'model': ListFeautresRes
    }
})
async def list_item_features(req: ListFeaturesReq):
    features = await MilvusManager.get_parts_feature_set(int(req.item_id))

    res = ListFeautresRes()
    for f in features:
        res.features.append(f)

    return res


@parts_router.post('/image_search',  tags=["算法-智能检索"], summary='根据图片查询配件', deprecated=True, responses={
    200: {
        'model': ImageSearchRes
    }
})
async def item_search(req: ImageSearchReq):
    return await RailwayPartsManager.image_search_to_item(req.images_url, req.radius)



# ============================================
# 算法接口 - 特征索引（已废弃，使用 /v2/index/rebuild）
# ============================================

# 旧的 index_rebuild 接口已删除，请使用 /v2/index/rebuild


# ============================================
# 算法接口 - 智能检索（已废弃，使用 /v2/search/*）
# ============================================

# 旧的 search/v2 接口已删除，请使用：
# - /v2/search/text - 文本检索
# - /v2/search/image - 图像检索


# ============================================
# 业务接口 - 数据统计
# ============================================

@parts_router.post('/data/statistics',  tags=["业务-数据统计"], summary='索引统计', responses={
    200: {
        'model': IndexStatisticsRes
    }
})
async def indexstatistics(req: IndexStatisticsReq):
    return await RailwayPartsManager.statistics()


# ===== 自动分割建立索引接口 =====

from csrcqsf.biz.railwayparts.auto_processor import AutoPartProcessor



# ============================================
# 算法接口 - 图像分割
# ============================================

@parts_router.post('/auto_segment', tags=["算法-图像分割"], deprecated=True,summary='自动分割并建立索引 (SAM + DINOv2)', responses={
    200: {'model': AutoSegmentRes}
})
async def auto_segment(req: AutoSegmentReq):
    """
    自动分割并建立高精度索引
    
    算法流程：
    1. 获取配件的 BASEINFO 类型图片
    2. 使用 SAM (Segment Anything Model) 自动分割出配件主体
    3. 分割后的图片上传到 MinIO
    4. 分割记录保存到数据库 (segmented_image_info 表)
    5. 使用 DINOv2 提取高精度特征（1024维向量）
    6. 建立 Milvus 向量索引
    
    参数：
    - item_id: 配件ID
    - rebuild: 是否重建已有索引
    
    业务逻辑：AutoPartProcessor.auto_segment_by_item_id() in biz/railwayparts/auto_processor.py
    核心算法：SAM分割 + DINOv2特征提取 + Milvus索引
    """
    result = await AutoPartProcessor.auto_segment_by_item_id(
        item_id=int(req.item_id),
        rebuild=req.rebuild
    )
    
    return AutoSegmentRes(
        item_id=result.item_id,
        total_baseinfo_images=result.total_baseinfo_images,
        segmented_count=result.segmented_count,
        indexed_count=result.indexed_count,
        skipped_count=result.skipped_count,
        failed_count=result.failed_count,
        message=result.message
    )


@parts_router.get('/segmented_images/{item_id}', tags=["业务-图片管理"],deprecated=True, summary='获取配件的分割记录', responses={
    200: {'model': ListSegmentedImagesRes}
})
async def list_segmented_images(item_id: str):
    """获取配件的分割记录列表"""
    records = await AutoPartProcessor.list_segmented_images(int(item_id))
    
    return ListSegmentedImagesRes(
        item_id=item_id,
        records=[
            SegmentedImageItem(**rec) for rec in records
        ]
    )


# ===== 新的3D重建接口 (Celery + Redis) =====

from csrcqsf.biz.railwayparts.reconstruction_manager import ReconstructionManager
from csrcqsf.biz.railwayparts.reconstruction_api_models import (
    ReconstructionTrainReq,
    ReconstructionVideoReq,
    ReconstructionTaskRes,
    ReconstructionStatusRes,
    ReconstructionListRes,
    ReconstructionStatisticsReq,
    ReconstructionStatisticsRes,
    ReconstructionSourceVideoRes,
    ReconstructionSourceVideoListReq,
    ReconstructionSourceVideoListRes,
    ReconstructionSourceVideoMessageRes,
    ReconstructionResultMessageRes,
    ReconstructionResultUploadRes,
    ReconstructionAllTasksReq,
    ReconstructionAllTasksRes,
    ReconstructionIndexRebuildRes,
)


@parts_router.post('/v2/reconstruct/train', tags=["算法-3D重建V2"], summary='V2: 从已有场景数据训练')
async def reconstruct_v2_train(req: ReconstructionTrainReq):
    """
    从已有场景数据直接训练（快速）
    
    前提：场景数据已在 reconstruction_server/data/{scene}/ 中
    
    参数：
    - item_id: 配件ID
    - scene: 场景名称（data目录下的文件夹名）
    - iterations: 训练迭代次数（默认30000）
    - output_name: 输出名称（可选）
    
    返回：
    - task_id: 任务ID，用于查询进度
    """
    result = await ReconstructionManager.submit_train_task(
        item_id=int(req.item_id),
        scene=req.scene,
        iterations=req.iterations,
        output_name=req.output_name
    )
    
    return ReconstructionTaskRes(**result)


@parts_router.post('/v2/reconstruct/video', tags=["算法-3D重建V2"], summary='V2: 新增三维重构原始视频')
async def upload_reconstruct_v2_video(
    item_id: str = Form(...),
    height: float | None = Form(None),
    length: float | None = Form(None),
    width: float | None = Form(None),
    weight: float | None = Form(None),
    file: UploadFile = File(...)
):
    """
    上传三维重构原始视频到独立 MinIO bucket。
    
    返回的 `video_path` 可以直接作为 `/v2/reconstruct/tasks/video` 的 `video_path` 参数。
    """
    result = await ReconstructionManager.upload_source_video(
        item_id=int(item_id),
        height=height,
        length=length,
        width=width,
        weight=weight,
        file=file
    )
    return ReconstructionSourceVideoRes(**result)


@parts_router.post('/v2/reconstruct/video/list', tags=["算法-3D重建V2"], summary='V2: 分页列出三维重构原始视频')
async def list_reconstruct_v2_source_videos(req: ReconstructionSourceVideoListReq):
    result = await ReconstructionManager.list_source_videos(
        page=req.page,
        page_size=req.per_page,
    )
    return ReconstructionSourceVideoListRes(**result)


@parts_router.get('/v2/reconstruct/video/{item_id}', tags=["算法-3D重建V2"], summary='V2: 查询配件三维重构原始视频')
async def get_reconstruct_v2_source_video(item_id: str):
    result = await ReconstructionManager.get_source_video(int(item_id))
    return ReconstructionSourceVideoRes(**result)


@parts_router.put('/v2/reconstruct/video/{item_id}', tags=["算法-3D重建V2"], summary='V2: 更新或替换三维重构原始视频')
async def update_reconstruct_v2_source_video(
    item_id: str,
    height: float | None = Form(None),
    length: float | None = Form(None),
    width: float | None = Form(None),
    weight: float | None = Form(None),
    file: UploadFile | None = File(None),
):
    result = await ReconstructionManager.update_source_video(
        item_id=int(item_id),
        file=file,
        height=height,
        length=length,
        width=width,
        weight=weight,
    )
    return ReconstructionSourceVideoRes(**result)


@parts_router.delete('/v2/reconstruct/video/{item_id}', tags=["算法-3D重建V2"], summary='V2: 删除三维重构原始视频')
async def delete_reconstruct_v2_source_video(item_id: str):
    result = await ReconstructionManager.delete_source_video(int(item_id))
    return ReconstructionSourceVideoMessageRes(**result)


@parts_router.post('/v2/reconstruct/tasks/video', tags=["算法-3D重建V2"], summary='V2: 从视频完整重建')
async def reconstruct_v2_video(req: ReconstructionVideoReq):
    """
    完整视频重建流程
    
    流程：已绑定原始视频 → 提帧 → 去模糊去重 → COLMAP → SAM3分割 → 3DGS训练
    
    参数：
    - item_id: 配件ID
    - iterations: 训练迭代次数
    - is_sam3: 是否启用SAM3分割，模型路径由服务端SAM3_MODEL_PATH配置
    - skip_*: 跳过已完成的步骤（断点续跑）

    说明：
    - 服务端会根据 `item_id` 自动读取已绑定的 `video_path` 和配件名称
    - 输出目录默认使用 `时间_item_name` 作为运行名
    
    返回：
    - task_id: 任务ID，用于查询进度
    """
    result = await ReconstructionManager.submit_video_task(
        item_id=int(req.item_id),
        iterations=req.iterations,
        fps=req.fps,
        image_size=req.image_size,
        blur_threshold=req.blur_threshold,
        dedup_threshold=req.dedup_threshold,
        min_frames=req.min_frames,
        is_sam3=req.is_sam3,
        text_prompt=req.text_prompt,
        mask_dilate=req.mask_dilate,
        camera=req.camera,
        no_gpu=req.no_gpu,
        skip_extract=req.skip_extract,
        skip_filter=req.skip_filter,
        skip_colmap=req.skip_colmap,
        skip_sam3=req.skip_sam3,
    )
    
    return ReconstructionTaskRes(**result)


@parts_router.get('/v2/reconstruct/status/{task_id}', tags=["算法-3D重建V2"], summary='V2: 查询任务状态')
async def get_reconstruct_v2_status(task_id: str):
    """
    查询重建任务状态
    
    返回：
    - status: 任务状态 (pending/training/success/failed等)
    - progress: 进度百分比 (0-100)
    - current_stage: 当前阶段描述
    - result: 结果文件URL（完成后）
    """
    result = await ReconstructionManager.get_task_status(task_id)
    return ReconstructionStatusRes(**result)


@parts_router.delete('/v2/reconstruct/result/{item_id}', tags=["算法-3D重建V2"], summary='V2: 删除配件当前三维重构结果')
async def delete_reconstruct_v2_result(item_id: str):
    """
    删除指定配件当前绑定的三维重构结果。

    行为：
    - 删除当前 `item_info.obj_url` 指向的 MinIO 重构结果对象
    - 清空 `item_info.obj_url`
    - 只清空匹配当前 URL 的重构记录结果字段
    - 保留任务历史和本地 `output_path`
    """
    result = await ReconstructionManager.delete_reconstruction_result(int(item_id))
    return ReconstructionResultMessageRes(**result)


@parts_router.post('/v2/reconstruct/result/{item_id}', tags=["算法-3D重建V2"], summary='V2: 上传线下已有三维重构结果')
async def upload_reconstruct_v2_result(
    item_id: str,
    file: UploadFile = File(...),
):
    result = await ReconstructionManager.upload_reconstruction_result(int(item_id), file)
    return ReconstructionResultUploadRes(**result)


@parts_router.get('/v2/reconstruct/item/{item_id}', tags=["算法-3D重建V2"], summary='V2: 列出配件的重建任务')
async def list_item_reconstruct_tasks(item_id: str):
    """
    列出指定配件的所有重建任务
    
    返回任务列表，按创建时间倒序排列
    """
    records = await ReconstructionManager.list_item_tasks(int(item_id))
    return ReconstructionListRes(records=records)


@parts_router.post('/v2/reconstruct/tasks/list', tags=["算法-3D重建V2"], summary='V2: 列出所有重建任务')
async def list_all_reconstruct_tasks(req: ReconstructionAllTasksReq):
    """
    列出所有重建任务（支持分页和状态筛选）
    
    参数：
    - status: 任务状态筛选（可选）
        - pending: 等待中
        - extracting: 提帧中
        - filtering: 帧筛选中
        - colmap: COLMAP处理中
        - sam3: SAM3分割中
        - training: 训练中
        - converting: 转换中
        - success: 成功
        - failed: 失败
        - cancelled: 已取消
    - page: 页码
    - pageSize: 每页数量
    
    返回：
    - total: 总任务数
    - page: 当前页码
    - pageSize: 每页数量
    - records: 任务列表
    """
    result = await ReconstructionManager.list_all_tasks(
        status=req.status,
        page=req.page,
        page_size=req.per_page,
    )
    return ReconstructionAllTasksRes(**result)


@parts_router.post('/v2/reconstruct/statistics', tags=["算法-3D重建V2"], summary='V2: 三维重构统计')
async def reconstruct_v2_statistics(_req: ReconstructionStatisticsReq):
    result = await ReconstructionManager.statistics()
    return ReconstructionStatisticsRes(**result)


@parts_router.delete('/v2/reconstruct/cancel/{task_id}', tags=["算法-3D重建V2"], summary='V2: 取消任务')
async def cancel_reconstruct_task(task_id: str):
    """取消正在执行的重建任务"""
    return await ReconstructionManager.cancel_task(task_id)


@parts_router.get('/v2/reconstruct/scenes', tags=["算法-3D重建V2"], summary='V2: 列出可用场景')
async def list_reconstruction_scenes():
    """
    列出 reconstruction_server/data/ 目录下所有可用场景
    
    返回已准备好 COLMAP 数据的场景，可直接用于训练
    """
    scenes = ReconstructionManager.list_scenes()
    return {"scenes": scenes}



# ============================================
# 新向量数据库接口 (SigLIP + DINOv2)
# ============================================

@parts_router.post('/v2/collections/drop', tags=["算法-向量检索V2"], summary='清空V2向量数据库')
async def drop_v2_collections():
    """
    清空向量数据库（删除所有集合）
    
    警告：此操作会删除以下集合的所有数据：
    - PARTS_SIGLIP_SO400M_1152D_V1: SigLIP 图文特征
    - PARTS_DINOV2_LARGE_1024D_V1: DINOv2 视觉特征
    
    删除后需要重新调用 /v2/collections/init 创建集合
    """
    manager = MilvusStateManagerV2()
    await run_sync(manager.drop_collections)
    
    return {
        'message': 'V2 collections dropped successfully',
        'warning': 'All vector data has been deleted. Please call /v2/collections/init to recreate collections.'
    }


@parts_router.post('/v2/collections/init', tags=["算法-向量检索V2"], summary='初始化V2向量数据库集合')
async def init_v2_collections():
    """
    初始化新的向量数据库集合 (SigLIP + DINOv2)
    
    创建两个集合：
    - PARTS_SIGLIP_SO400M_1152D_V1: SigLIP 图文特征 (1152维)
    - PARTS_DINOV2_LARGE_1024D_V1: DINOv2 视觉特征 (1024维)
    
    注意：
    - 如果集合已存在，将跳过创建
    - 此接口只创建集合结构，不建立索引
    - 建立索引请调用 /v2/index/rebuild 接口
    """
    await RailwayPartsManager.create_v2_collections(drop_existing=False)
    
    return {
        'message': 'V2 collections initialized successfully',
        'next_step': 'Call /v2/index/rebuild to build index'
    }


@parts_router.post('/v2/index/rebuild', tags=["算法-向量检索V2"], summary='重建V2索引')
async def rebuild_v2_index(
    item_id: str = None,
    limit: int = None,
    rebuild_existing: bool = False,
    background_tasks: BackgroundTasks = None
):
    """
    重建V2向量索引 (SigLIP + DINOv2)
    
    参数：
    - item_id: 指定配件ID（可选，为空则重建所有）
    - limit: 限制处理数量（可选，用于测试，如 limit=10 只处理10条数据）
    - background_tasks: 后台任务（自动传入）
    
    注意：
    - 如果 limit > 100 或未指定 limit，将在后台执行
    - 小批量任务（limit <= 100）会同步执行并返回结果
    """
    # 判断是否需要后台执行
    should_background = (limit is None or limit > 100) and background_tasks is not None
    
    int_item_id = int(item_id) if item_id not in (None, "") else None

    if should_background:
        # 大批量任务放到后台执行
        background_tasks.add_task(
            RailwayPartsManager.rebuild_v2_index,
            item_id=int_item_id,
            limit=limit,
            rebuild_existing=rebuild_existing,
        )
        return ReconstructionIndexRebuildRes(
            message='Index rebuild task started in background',
            item_id=item_id,
            limit=limit or 'all',
            rebuild_existing=rebuild_existing,
        )
    else:
        # 小批量任务直接执行
        result = await RailwayPartsManager.rebuild_v2_index(
            item_id=int_item_id,
            limit=limit,
            rebuild_existing=rebuild_existing,
        )
        return {
            'message': 'Index rebuilt successfully',
            'rebuild_existing': rebuild_existing,
            'result': result
        }


@parts_router.delete('/v2/index/{item_id}', tags=["算法-向量检索V2"], summary='删除指定配件的V2索引', responses={
    200: {
        'model': V2IndexDeleteRes
    }
})
async def delete_v2_index(item_id: str):
    result = await RailwayPartsManager.delete_v2_index(int(item_id))
    return V2IndexDeleteRes(**result)


@parts_router.post('/v2/search/text', tags=["算法-向量检索V2"], summary='V2文本检索')
async def search_v2_by_text(
    query_text: str,
    top_k: int = 10,
    search_equipment: str = "web",
    # use_image_vector: bool = False
):
    """
    使用新算法进行文本检索
    
    参数：
    - query_text: 查询文本（如"制动盘"）
    - top_k: 返回结果数量
    - use_image_vector: 是否使用 image_vector 字段（可选）
        - False（默认）: 使用 text_vector 字段进行文本匹配
        - True: 使用 image_vector 字段进行图像内容语义匹配
    
    算法：
    - 使用 SigLIP 提取文本特征
    - 在 PARTS_SIGLIP_SO400M_1152D_V1 集合中检索
    - 返回最相似的配件
    """
    result = await RailwayPartsManager.search_v2_by_text(
        query_text=query_text,
        top_k=top_k,
        search_equipment=search_equipment,
        # use_image_vector=use_image_vector
    )
    return result


@parts_router.post('/v2/search/image', tags=["算法-向量检索V2"], summary='V2图像检索')
async def search_v2_by_image(
    file: UploadFile = File(...),
    top_k: int = 10,
    search_mode: str = "hybrid",
    search_equipment: str = Form("web"),
):
    """
    使用新算法进行图像检索（上传图片文件）
    
    参数：
    - file: 上传的图片文件（支持 jpg, png, jpeg 等格式）
    - top_k: 返回结果数量
    - search_mode: 检索模式
        - "siglip": SigLIP 模式 - 使用 image_vector 字段，简单快速
        - "dinov2": DINOv2 两阶段检索 - global_vector 粗排 + patch_tokens 精排
        - "hybrid": 混合检索（推荐）- RRF 融合 + Patch Token 精排
    
    算法流程（hybrid模式）：
    1. 粗排：SigLIP + DINOv2 全局特征 RRF 融合
    2. 精排：DINOv2 Patch Token 细粒度匹配
    3. 加权融合：alpha * RRF分数 + (1-alpha) * Patch分数
    
    注意：
    - siglip 模式：默认使用 text_vector 进行文本匹配，image_vector 是可选字段
    - dinov2 模式：两阶段检索，适合需要精确匹配视觉细节的场景
    - hybrid 模式：推荐使用，融合两个模型的优势
    """
    result = await RailwayPartsManager.search_v2_by_image(
        file=file,
        top_k=top_k,
        search_mode=search_mode,
        search_equipment=search_equipment,
    )
    return result


@parts_router.post('/v2/search/history/list', tags=["算法-向量检索V2"], summary='V2检索历史分页查询', responses={
    200: {
        'model': SearchHistoryListRes
    }
}, description="""
请求体字段说明：

- `page`: 页码，从 1 开始
- `pageSize`: 每页数量
- `search_type`: 检索类型筛选，支持 `all`、`text`、`image`
- `search_equipment`: 检索设备筛选，支持 `all`、`web`、`terminal`
- `keyword`: 关键词筛选，会匹配查询文本、检索结果物料编码/名称、人工纠正物料编码
- `status`: 校验状态筛选，支持 `all`、`pending`、`correct`、`wrong`
- `date_from`: 开始日期，格式 `YYYY-MM-DD`
- `date_to`: 结束日期，格式 `YYYY-MM-DD`
""")
async def list_v2_search_history(req: SearchHistoryListReq):
    return await RailwayPartsManager.list_v2_search_history(req)


@parts_router.post('/v2/search/history/detail', tags=["算法-向量检索V2"], summary='V2检索历史详情', responses={
    200: {
        'model': SearchHistoryListItem
    }
}, description="""
请求体字段说明：

- `history_id`: 检索历史ID
""")
async def get_v2_search_history_detail(req: SearchHistoryDetailReq):
    return await RailwayPartsManager.get_v2_search_history_detail(int(req.history_id))


@parts_router.post('/v2/search/history/summary', tags=["算法-向量检索V2"], summary='V2检索历史统计', responses={
    200: {
        'model': SearchHistorySummaryRes
    }
})
async def summary_v2_search_history():
    return await RailwayPartsManager.summary_v2_search_history()


@parts_router.post('/v2/search/history/verify', tags=["算法-向量检索V2"], summary='V2检索历史校验提交', deprecated=True, responses={
    200: {
        'model': SearchHistoryVerifyRes
    }
}, description="""
请求体字段说明：

- `history_id`: 检索历史ID
- `verify_status`: 校验结果，支持 `correct`、`wrong`、`partial`
- `correct_item_code`: 人工确认后的正确物料编码；当 `verify_status=correct` 且不传时，默认回填首条检索结果编码
- `remark`: 人工校验备注
""")
async def verify_v2_search_history(req: SearchHistoryVerifyReq):
    return await RailwayPartsManager.verify_v2_search_history(
        history_id=int(req.history_id),
        verify_status=req.verify_status,
        correct_item_code=req.correct_item_code,
        remark=req.remark,
    )


@parts_router.post('/v2/search/history/feedback', tags=["算法-向量检索V2"], summary='V2检索历史用户反馈提交', responses={
    200: {
        'model': SearchHistoryFeedbackRes
    }
}, description="""
请求体字段说明：

- `history_id`: 检索历史ID
- `feedback_result`: 用户反馈结果，支持 `correct`、`wrong`
- `remark`: 反馈备注
""")
async def submit_v2_search_feedback(req: SearchHistoryFeedbackReq):
    return await RailwayPartsManager.submit_v2_search_feedback(
        history_id=int(req.history_id),
        feedback_result=req.feedback_result,
        remark=req.remark,
    )


@parts_router.post('/v2/search/review-ticket/list', tags=["算法-向量检索V2"], summary='V2技术部核验清单分页查询', responses={
    200: {
        'model': SearchReviewTicketListRes
    }
}, description="""
请求体字段说明：

- `page`: 页码，从 1 开始
- `pageSize`: 每页数量
- `review_status`: 核验单状态筛选，支持 `all`、`open`、`reviewing`、`resolved`、`closed`
- `issue_type`: 问题类型，支持 `missing_index`、`precision_issue`、`system_bug`
- `search_equipment`: 检索设备筛选，支持 `all`、`web`、`terminal`
- `keyword`: 关键词筛选
- `date_from`: 开始日期，格式 `YYYY-MM-DD`
- `date_to`: 结束日期，格式 `YYYY-MM-DD`
""")
async def list_v2_search_review_tickets(req: SearchReviewTicketListReq):
    return await RailwayPartsManager.list_v2_search_review_tickets(req)


@parts_router.post('/v2/search/review-ticket/detail', tags=["算法-向量检索V2"], summary='V2技术部核验单详情', responses={
    200: {
        'model': SearchReviewTicketDetailRes
    }
}, description="""
请求体字段说明：

- `ticket_id`: 核验单ID
""")
async def get_v2_search_review_ticket_detail(req: SearchReviewTicketDetailReq):
    return await RailwayPartsManager.get_v2_search_review_ticket_detail(ticket_id=int(req.ticket_id))


@parts_router.post('/v2/search/review-ticket/update', tags=["算法-向量检索V2"], summary='V2技术部核验单更新', responses={
    200: {
        'model': SearchReviewTicketUpdateRes
    }
}, description="""
请求体字段说明：

- `ticket_id`: 核验单ID
- `review_status`: 目标状态，支持 `reviewing`、`resolved`、`closed`
- `issue_type`: 问题类型，支持 `missing_index`、`precision_issue`、`system_bug`
- `review_remark`: 核验备注
- `resolution_remark`: 解决备注
- `correct_item_code`: 可选，纠正后的物料编码
""")
async def update_v2_search_review_ticket(req: SearchReviewTicketUpdateReq):
    return await RailwayPartsManager.update_v2_search_review_ticket(
        ticket_id=int(req.ticket_id),
        review_status=req.review_status,
        issue_type=req.issue_type,
        review_remark=req.review_remark,
        resolution_remark=req.resolution_remark,
        correct_item_code=req.correct_item_code,
    )


@parts_router.post('/v2/search/review-ticket/summary', tags=["算法-向量检索V2"], summary='V2技术部核验单统计', responses={
    200: {
        'model': SearchReviewTicketSummaryRes
    }
})
async def summary_v2_search_review_ticket():
    return await RailwayPartsManager.summary_v2_search_review_ticket()


@parts_router.post('/item/suggest', tags=["业务-配件管理"], summary='物料编码联想', responses={
    200: {
        'model': ItemSuggestRes
    }
}, description="""
请求体字段说明：

- `keyword`: 联想关键词，可输入物料编码或物料名称片段
- `limit`: 最多返回的联想条数
""")
async def suggest_items(req: ItemSuggestReq):
    return await RailwayPartsManager.suggest_items(req.keyword, limit=req.limit)


@parts_router.post('/v2/search/history/delete', tags=["算法-向量检索V2"], summary='V2检索历史批量删除', responses={
    200: {
        'model': SearchHistoryDeleteRes
    }
}, description="""
请求体字段说明：

- `history_id_list`: 待删除的检索历史ID列表
""")
async def delete_v2_search_history(req: SearchHistoryDeleteReq):
    return await RailwayPartsManager.delete_v2_search_history(
        [int(history_id) for history_id in req.history_id_list]
    )


@parts_router.get('/v2/search/modes', tags=["算法-向量检索V2"], summary='获取V2检索模式说明')
async def get_v2_search_modes():
    """
    获取 V2 检索模式说明
    
    返回各种检索模式的详细说明和适用场景
    """
    return {
        'modes': [
            {
                'name': 'siglip',
                'description': 'SigLIP 图像检索',
                'features': [
                    '使用 image_vector 字段',
                    '图文共享空间，1152维特征',
                    '简单快速'
                ],
                'use_case': '快速图像检索，对精度要求不高的场景',
                'speed': '快',
                'accuracy': '中',
                'note': 'image_vector 是可选字段，默认为 text_vector 匹配'
            },
            {
                'name': 'dinov2',
                'description': 'DINOv2 两阶段检索',
                'features': [
                    'global_vector (1024D) 粗排',
                    'patch_tokens (1369×1024) 精排',
                    '细粒度局部特征匹配'
                ],
                'use_case': '需要精确匹配视觉细节的场景，识别微小规格差异',
                'speed': '慢',
                'accuracy': '高'
            },
            {
                'name': 'hybrid',
                'description': '混合检索（推荐）',
                'features': [
                    'RRF 融合 SigLIP + DINOv2',
                    'Patch Token 精排',
                    '多模型互补，鲁棒性强'
                ],
                'use_case': '生产环境推荐，工业配件精确检索',
                'speed': '中',
                'accuracy': '最高'
            }
        ],
        'recommendation': 'hybrid 模式在准确率和速度之间取得最佳平衡，推荐用于生产环境',
        'text_search_note': '文本检索默认使用 text_vector 字段，可选 use_image_vector=true 使用 image_vector 字段'
    }
