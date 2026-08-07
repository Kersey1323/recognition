"""Routes for vector index, search, and search history."""

from fastapi import File, Form, HTTPException, UploadFile
from anyio.to_thread import run_sync

from csrcqsf.modules.railway_parts.schemas.search import (
    SearchHistoryDeleteReq,
    SearchHistoryDeleteRes,
    SearchHistoryDetailReq,
    SearchHistoryFeedbackReq,
    SearchHistoryFeedbackRes,
    SearchHistoryListItem,
    SearchHistoryListReq,
    SearchHistoryListRes,
    SearchHistorySummaryRes,
    SearchHistoryVerifyReq,
    SearchHistoryVerifyRes,
    SearchTextReq,
    V2IndexDeleteRes,
)
from csrcqsf.modules.railway_parts.schemas.reconstruction import (
    ReconstructionIndexRebuildRes,
    ReconstructionIndexRebuildStatusRes,
)
from csrcqsf.modules.railway_parts.services.index_rebuild_task_manager import (
    index_rebuild_task_manager,
)
from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager
from csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager import (
    MilvusStateManagerV2,
)
from csrcqsf.core.runtime import ensure_vector_models_enabled

from .router import parts_router


@parts_router.post('/v2/collections/drop', tags=["算法-向量检索V2"], summary='清空V2向量数据库')
async def drop_v2_collections():
    """
    清空向量数据库（删除所有集合）

    警告：此操作会删除以下集合的所有数据：
    - PARTS_SIGLIP_SO400M_1152D_V1: SigLIP 图文特征
    - PARTS_DINOV2_LARGE_1024D_V1: DINOv2 视觉特征

    删除后需要重新调用 /v2/collections/init 创建集合
    """
    ensure_vector_models_enabled()
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
    ensure_vector_models_enabled()
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
):
    """
    重建V2向量索引 (SigLIP + DINOv2)

    参数：
    - item_id: 指定配件ID（可选，为空则重建所有）
    - limit: 限制处理数量（可选，用于测试，如 limit=10 只处理10条数据）
    注意：
    - 所有索引任务都在当前服务进程内异步执行
    - 提交后使用返回的 task_id 查询进度和预计剩余时间
    """
    ensure_vector_models_enabled()
    int_item_id = int(item_id) if item_id not in (None, "") else None

    # 单配件、小批量和全量索引使用同一任务生命周期，避免前端维护两套交互。
    try:
        task = index_rebuild_task_manager.start(
            runner=RailwayPartsManager.rebuild_v2_index,
            item_id=int_item_id,
            limit=limit,
            rebuild_existing=rebuild_existing,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ReconstructionIndexRebuildRes(
        message='索引重建任务已在后台启动',
        task_id=task["task_id"],
        status=task["status"],
        item_id=int_item_id,
        limit=limit or 'all',
        rebuild_existing=rebuild_existing,
    )


@parts_router.get(
    '/v2/index/rebuild/status/{task_id}',
    tags=["算法-向量检索V2"],
    summary='查询V2索引重建进度',
)
async def get_v2_index_rebuild_status(task_id: str):
    """查询当前服务进程内的索引任务进度和预计剩余时间。"""
    task = index_rebuild_task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"索引重建任务不存在: task_id={task_id}")
    return ReconstructionIndexRebuildStatusRes(**task)


@parts_router.delete('/v2/index/{item_id}', tags=["算法-向量检索V2"], summary='删除指定配件的V2索引', responses={
    200: {
        'model': V2IndexDeleteRes
    }
})
async def delete_v2_index(item_id: str):
    ensure_vector_models_enabled()
    result = await RailwayPartsManager.delete_v2_index(int(item_id))
    return V2IndexDeleteRes(**result)


@parts_router.post('/v2/search/text', tags=["算法-向量检索V2"], summary='V2文本检索')
async def search_v2_by_text(
    req: SearchTextReq | None = None,
    query_text: str | None = None,
    top_k: int | None = None,
    search_equipment: str | None = None,
    # use_image_vector: bool = False
):
    """
    使用新算法进行文本检索

    参数：
    - query_text: 查询文本（如"制动盘"）
    - top_k: 参与聚合的图片命中数量，仍按图片结果窗口工作
    - search_equipment: 检索来源，支持 `web`、`terminal`
    - use_image_vector: 是否使用 image_vector 字段（可选）
        - False（默认）: 使用 text_vector 字段进行文本匹配
        - True: 使用 image_vector 字段进行图像内容语义匹配

    算法：
    - 使用 SigLIP 提取文本特征
    - 在 PARTS_SIGLIP_SO400M_1152D_V1 集合中检索
    - 返回结果按 item_id 聚合为候选配件列表
    - image_url: 当前候选配件的代表图
    - rate: 当前候选配件命中图片中的最高分
    - matched_images: 当前候选配件在本次检索中命中的图片列表
    - history_id: 本次检索生成的历史ID，可直接用于后续反馈/校验链路
    """
    ensure_vector_models_enabled()
    if req is None:
        req = SearchTextReq(
            query_text=query_text,
            top_k=top_k if top_k is not None else 10,
            search_equipment=search_equipment or "web",
        )

    result = await RailwayPartsManager.search_v2_by_text(
        query_text=req.query_text,
        top_k=req.top_k,
        search_equipment=req.search_equipment,
        # use_image_vector=use_image_vector
    )
    return result


@parts_router.post('/v2/search/image', tags=["算法-向量检索V2"], summary='V2图像检索')
async def search_v2_by_image(
    file: list[UploadFile] = File(...),
    top_k: int = Form(10),
    search_mode: str = Form("hybrid"),
    search_equipment: str = Form("web"),
):
    """
    使用新算法进行图像检索（上传图片文件，支持单张或多张）

    参数：
    - file: 上传的图片文件列表（支持单张或多张）
    - 文件格式支持 jpg、png、jpeg 等
    - top_k: 参与聚合的图片命中数量，仍按图片结果窗口工作
    - search_mode: 检索模式
        - "siglip": SigLIP 模式 - 使用 image_vector 字段，简单快速
        - "dinov2": DINOv2 两阶段检索 - global_vector 粗排 + patch_tokens 精排
        - "hybrid": 混合检索（推荐）- RRF 融合 + Patch Token 精排
    - search_equipment: 检索来源，支持 `web`、`terminal`

    算法流程（hybrid模式）：
    1. 粗排：SigLIP + DINOv2 全局特征 RRF 融合
    2. 精排：DINOv2 Patch Token 细粒度匹配
    3. 加权融合：alpha * RRF分数 + (1-alpha) * Patch分数

    注意：
    - siglip 模式：默认使用 text_vector 进行文本匹配，image_vector 是可选字段
    - dinov2 模式：两阶段检索，适合需要精确匹配视觉细节的场景
    - hybrid 模式：推荐使用，融合两个模型的优势
    - 上传 1 张图时走单图检索链路；上传多张图时走后端融合检索链路
    - 返回结果按 item_id 聚合为候选配件列表
    - image_url: 当前候选配件的代表图
    - rate: 当前候选配件命中图片中的最高分
    - matched_images: 当前候选配件在本次检索中命中的图片列表
    - matched_images[].matched_query_indexes: 当前命中图被哪几张查询图共同支持
    - history_id: 本次检索生成的历史ID，可直接用于后续反馈/校验链路
    """
    ensure_vector_models_enabled()
    if len(file) == 1:
        result = await RailwayPartsManager.search_v2_by_image(
            file=file[0],
            top_k=top_k,
            search_mode=search_mode,
            search_equipment=search_equipment,
        )
        return result

    result = await RailwayPartsManager.search_v2_by_images(
        files=file,
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
- `status`: 校验状态筛选，支持 `all`、`pending`、`correct`、`wrong`、`user_misjudged`
- `date_from`: 开始日期，格式 `YYYY-MM-DD`
- `date_to`: 结束日期，格式 `YYYY-MM-DD`

返回值补充说明：

- `search_item_*`: 系统当前 top1 推荐结果
- `correct_item_id`: 当前最终确认结果的配件ID；未确认时为空
- `correct_item_code`: 当前最终确认结果的物料编码；未确认时为空
- `correct_item_name`: 当前最终确认结果的物料名称；未确认时为空
- `correct_image_url`: 当前最终确认结果的代表图；未确认时为空
- `correct_rank`: 当前最终确认结果在原始候选中的排名；未召回时为空
- `correct_source`: `none`、`user_selected`、`review_resolved`
- `ranking_feedback_type`: 真实反馈类型，支持 `top1_correct`、`topk_correct`、`no_correct_match`
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

返回值补充说明：

- 同样返回 `search_item_*`、`correct_item_*`、`correct_source`、`ranking_feedback_type`
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
- `verify_status`: 校验结果，支持 `correct`、`wrong`、`user_misjudged`、`partial`
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
- `selected_item_id`: 可选，用户最终确认正确的配件ID；后端会自动反推该候选在本次结果中的原始排名，并补齐物料编码、名称和代表图
""")
async def submit_v2_search_feedback(req: SearchHistoryFeedbackReq):
    return await RailwayPartsManager.submit_v2_search_feedback(
        history_id=int(req.history_id),
        feedback_result=req.feedback_result,
        remark=req.remark,
        selected_item_id=req.selected_item_id,
    )


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
