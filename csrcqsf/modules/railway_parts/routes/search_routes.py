"""向量索引、配件检索和检索历史路由。"""

from datetime import datetime
from typing import Annotated

from fastapi import File, Form, HTTPException, Path, Query, UploadFile
from anyio.to_thread import run_sync

from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.models.orm.item import Items
from csrcqsf.modules.railway_parts.schemas.search import (
    ContextualSearchRes,
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
    ReconstructionIndexTaskCancelReq,
    ReconstructionIndexTaskListReq,
    ReconstructionIndexTaskListRes,
)
from csrcqsf.modules.railway_parts.services.index_rebuild_task_manager import (
    index_rebuild_task_manager,
)
from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager
from csrcqsf.modules.railway_parts.services.contextual_search_service import (
    ContextualSearchBusinessError,
)
from csrcqsf.modules.railway_parts.services.search_hierarchy_service import enrich_search_items
from csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager import (
    MilvusStateManagerV2,
)
from csrcqsf.core.runtime import ensure_vector_models_enabled

from .router import parts_router


_INDEX_TASK_ITEM_CODE_FIELDS = {
    "item_id": "item_code",
    "current_item_id": "current_item_code",
    "last_completed_item_id": "last_completed_item_code",
}


async def _replace_index_task_item_ids_with_codes(
    records: list[dict],
) -> list[dict]:
    """将任务内部配件ID批量转换为用户可识别的配件编码。"""
    item_ids = {
        int(record[id_field])
        for record in records
        for id_field in _INDEX_TASK_ITEM_CODE_FIELDS
        if record.get(id_field) not in (None, "")
    }
    item_code_by_id: dict[int, str] = {}
    if item_ids:
        # 同一页任务只访问一次业务库，避免任务列表逐条查询配件编码。
        async with SessionLocal() as session:
            rows = await Items.list_item_id_codes_by_ids(session, list(item_ids))
        item_code_by_id = {
            int(item_id): str(item_code)
            for item_id, item_code in rows
            if item_code not in (None, "")
        }

    resolved_records = []
    for record in records:
        resolved = dict(record)
        for id_field, code_field in _INDEX_TASK_ITEM_CODE_FIELDS.items():
            item_id = resolved.pop(id_field, None)
            if code_field not in resolved:
                resolved[code_field] = (
                    item_code_by_id.get(int(item_id))
                    if item_id not in (None, "")
                    else None
                )
        resolved_records.append(resolved)
    return resolved_records


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


@parts_router.post(
    '/v2/index/rebuild',
    tags=["算法-向量检索V2"],
    summary='提交V2索引重建任务',
    response_model=ReconstructionIndexRebuildRes,
)
async def rebuild_v2_index(
    item_id: str | None = Query(
        default=None,
        description='指定配件ID；不传时创建批量任务。ID建议按字符串传递，避免前端精度丢失',
        example='1979108557241831424',
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        description='批量任务最多处理的配件数量上限，不是图片数量；不传表示处理全部候选配件',
        example=500,
    ),
    rebuild_existing: bool = Query(
        default=False,
        description=(
            '是否强制重建：false 仅处理存在未索引图片的配件，并仅补建未索引图片；'
            'true 会先删除所选配件的旧向量、patch tokens 和分割产物，再重建全部有效图片'
        ),
    ),
):
    """
    提交进程内后台任务，立即返回 `task_id`，前端不需要等待索引完成。

    图片处理规则：

    - `CREATEBYSELF`：调用模型服务 `/api/v1/indexing/extract`，执行 YOLO-World + SAM2
      主体分割，并直接返回 SigLIP、DINOv2 特征。
    - `BASEINFO`、`INQUERY`、空值或未知来源：不分割，使用原图分别调用 SigLIP、DINOv2
      特征接口。
    - 主体未识别、空 Mask 或无效 Mask：记录分割失败并回退原图索引；模型加载、网络等技术
      异常不回退，该图片计入失败数。

    任务约束：批量任务不能与其他索引任务并行；单配件任务最多并行 16 个，同一配件不能重复提交。
    提交后通过进度接口轮询，页面重新打开时可通过任务列表找回 `task_id`。
    """
    ensure_vector_models_enabled()
    int_item_id = int(item_id) if item_id not in (None, "") else None

    # 单配件、小批量和全量索引使用同一任务生命周期，避免前端维护两套交互。
    try:
        task = await index_rebuild_task_manager.start(
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
    response_model=ReconstructionIndexRebuildStatusRes,
)
async def get_v2_index_rebuild_status(
    task_id: Annotated[str, Path(description='提交或重试索引任务时返回的后台任务ID')],
):
    """从持久化任务记录查询进度、图片处理统计、预计剩余时间和失败原因。"""
    task = await index_rebuild_task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"索引重建任务不存在: task_id={task_id}")
    resolved_task = (await _replace_index_task_item_ids_with_codes([task]))[0]
    return ReconstructionIndexRebuildStatusRes(**resolved_task)


@parts_router.post(
    '/v2/index/rebuild/tasks/list',
    tags=["算法-向量检索V2"],
    summary='查询V2索引重建任务列表',
    response_model=ReconstructionIndexTaskListRes,
)
async def list_v2_index_rebuild_tasks(req: ReconstructionIndexTaskListReq):
    """
    分页查询持久化任务，用于页面重新打开后恢复任务列表和继续轮询。

    **请求字段**

    | 字段 | 含义 |
    | --- | --- |
    | `page` | 页码，建议从 1 开始 |
    | `pageSize` | 每页返回的任务数量 |
    | `status` | 按任务状态筛选，取值见下表 |
    | `task_scope` | 按任务范围筛选，取值见下表 |
    | `item_id` | 可选配件ID；有值时只查询该配件的 `single` 任务 |

    **status 状态**

    | 值 | 含义 |
    | --- | --- |
    | `all` | 不按状态筛选，返回全部状态 |
    | `active` | 活动任务集合，包括等待中、运行中、取消中的任务 |
    | `pending` | 已创建，正在等待后台执行 |
    | `running` | 后台正在构建索引 |
    | `cancelling` | 已收到取消请求，正在等待任务协程退出 |
    | `success` | 任务已执行完成；仍需检查 `fail_count` 是否存在单图失败 |
    | `failed` | 任务级异常导致整体执行失败，可查看 `error_message` |
    | `cancelled` | 任务已取消并结束 |
    | `interrupted` | 服务重启时发现任务未完成，可调用重试接口继续 |

    **task_scope 范围**

    | 值 | 含义 |
    | --- | --- |
    | `all` | 不按任务范围筛选 |
    | `single` | 指定 `item_id` 创建的单配件任务，最多并行 16 个 |
    | `batch` | 未指定 `item_id` 的批量任务，不能与其他索引任务并行 |
    """
    item_id = int(req.item_id) if req.item_id not in (None, "") else None
    records, total = await index_rebuild_task_manager.list(
        page=req.page,
        per_page=req.per_page,
        status=req.status,
        task_scope=req.task_scope,
        item_id=item_id,
    )
    resolved_records = await _replace_index_task_item_ids_with_codes(records)
    return ReconstructionIndexTaskListRes(
        total=total,
        page=req.page,
        pageSize=req.per_page,
        records=[ReconstructionIndexRebuildStatusRes(**record) for record in resolved_records],
    )


@parts_router.post(
    '/v2/index/rebuild/tasks/{task_id}/cancel',
    tags=["算法-向量检索V2"],
    summary='取消V2索引重建任务',
    response_model=ReconstructionIndexRebuildStatusRes,
)
async def cancel_v2_index_rebuild_task(
    task_id: Annotated[str, Path(description='需要取消的后台索引任务ID')],
    req: ReconstructionIndexTaskCancelReq,
):
    """请求取消等待中或运行中的任务；返回 `cancelling` 后应继续轮询到 `cancelled`。"""
    try:
        task = await index_rebuild_task_manager.cancel(task_id, req.cancel_reason)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"索引重建任务不存在: task_id={task_id}",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    resolved_task = (await _replace_index_task_item_ids_with_codes([task]))[0]
    return ReconstructionIndexRebuildStatusRes(**resolved_task)


@parts_router.post(
    '/v2/index/rebuild/tasks/{task_id}/retry',
    tags=["算法-向量检索V2"],
    summary='重试V2索引重建任务',
    response_model=ReconstructionIndexRebuildRes,
)
async def retry_v2_index_rebuild_task(
    task_id: Annotated[
        str,
        Path(description='需要重试的 failed、cancelled 或 interrupted 任务ID'),
    ],
):
    """
    从来源任务最近完成的配件检查点创建新任务并返回新的 `task_id`。

    重试精确到配件级，不重复处理已完成配件；失败或中断时正在处理的配件会重新处理。
    """
    try:
        task = await index_rebuild_task_manager.retry(
            task_id,
            runner=RailwayPartsManager.rebuild_v2_index,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"索引重建任务不存在: task_id={task_id}",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ReconstructionIndexRebuildRes(
        message='索引重建重试任务已在后台启动',
        task_id=task["task_id"],
        status=task["status"],
        item_id=task.get("item_id"),
        limit=task.get("item_limit") or 'all',
        rebuild_existing=bool(task.get("rebuild_existing", False)),
    )


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
    source_inquiry_id: str | None = None,
    source_inquiry_time: datetime | None = None,
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
            source_inquiry_id=source_inquiry_id,
            source_inquiry_time=source_inquiry_time,
        )

    search_kwargs = {
        "query_text": req.query_text,
        "top_k": req.top_k,
        "search_equipment": req.search_equipment,
    }
    if req.source_inquiry_id and req.source_inquiry_time:
        search_kwargs.update(
            source_inquiry_id=req.source_inquiry_id,
            source_inquiry_time=req.source_inquiry_time,
        )
    result = await RailwayPartsManager.search_v2_by_text(**search_kwargs)
    await enrich_search_items(result.data)
    return result


@parts_router.post('/v2/search/image', tags=["算法-向量检索V2"], summary='V2图像检索')
async def search_v2_by_image(
    file: list[UploadFile] = File(...),
    top_k: int = Form(10),
    search_mode: str = Form("siglip"),
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
        - "hybrid": 混合检索 - RRF 融合 + Patch Token 精排
    - search_equipment: 检索来源，支持 `web`、`terminal`

    算法流程（hybrid模式）：
    1. 粗排：SigLIP + DINOv2 全局特征 RRF 融合
    2. 精排：DINOv2 Patch Token 细粒度匹配
    3. 加权融合：alpha * RRF分数 + (1-alpha) * Patch分数

    注意：
    - siglip 模式：默认使用 text_vector 进行文本匹配，image_vector 是可选字段
    - dinov2 模式：两阶段检索，适合需要精确匹配视觉细节的场景
    - hybrid 模式：可按需启用，融合两个模型的优势
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
        await enrich_search_items(result.data)
        return result

    result = await RailwayPartsManager.search_v2_by_images(
        files=file,
        top_k=top_k,
        search_mode=search_mode,
        search_equipment=search_equipment,
    )
    await enrich_search_items(result.data)
    return result


@parts_router.post(
    '/v2/search/contextual',
    tags=["算法-向量检索V2"],
    summary='带业务条件的V2图片/描述检索',
    response_model=ContextualSearchRes,
)
async def search_v2_contextual(
    history_id: str | None = Form(default=None),
    file: list[UploadFile | str] | None = File(
        default=None,
        description="查询图片；允许 Swagger 提交空文件字段",
    ),
    vehicle_batch: str | None = Form(default=None, description="车型精确过滤条件"),
    item_name: str | None = Form(default=None, description="配件名称精确过滤条件；名称不存在时自动取消该过滤"),
    item_description: str | None = Form(default=None, description="配件自然语言描述，用于询码语义检索"),
    train_no: str | None = Form(default=None),
    car_num: str | None = Form(default=None),
    subordinate_component: str | None = Form(default=None),
    source_inquiry_id: str | None = Form(default=None, description="Agent 当前询码 ID"),
    source_inquiry_time: datetime | None = Form(default=None, description="Agent 当前询码时间"),
    search_mode: str = Form(default="siglip"),
    search_equipment: str = Form(default="web"),
):
    """使用图片或配件描述检索，在 wrong 或 pending 历史中保留最近两次结果。"""
    ensure_vector_models_enabled()
    try:
        normalized_history_id = (
            int(history_id) if history_id not in (None, "") else None
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="history_id 必须是有效整数") from exc
    raw_files = list(file or [])
    invalid_file_values = [
        value for value in raw_files if isinstance(value, str) and value.strip()
    ]
    if invalid_file_values:
        raise HTTPException(status_code=422, detail="file 必须上传图片文件或留空")
    # Swagger 勾选 Send empty value 时会把空文件解析成空字符串，业务上按未上传图片处理。
    uploaded_files = [value for value in raw_files if not isinstance(value, str)]
    try:
        result = await RailwayPartsManager.search_v2_contextual(
            history_id=normalized_history_id,
            files=uploaded_files,
            vehicle_batch=vehicle_batch,
            item_name=item_name,
            item_description=item_description,
            train_no=train_no,
            car_num=car_num,
            subordinate_component=subordinate_component,
            source_inquiry_id=source_inquiry_id,
            source_inquiry_time=source_inquiry_time,
            search_mode=search_mode,
            search_equipment=search_equipment,
        )
        await enrich_search_items(
            result.current.data,
            vehicle_batch=result.current.parameters.vehicle_batch,
        )
        if result.previous is not None:
            await enrich_search_items(
                result.previous.data,
                vehicle_batch=result.previous.parameters.vehicle_batch,
            )
        return result
    except ContextualSearchBusinessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


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
- `result.items[].parts_model`: 配件同步到业务库的规格型号
- `result.items[].material_quality`: 配件同步到业务库的材料材质
- `result.items[].suppliers`: 配件同步到业务库的有效供应商列表及供应商侧型号信息
- `result.items[]` 和 `previous_result.items[]` 的 `parent_parts`、`child_parts`: 当前业务库中的直接父子配件编码和名称；各轮按其检索时的车型筛选
""")
async def get_v2_search_history_detail(req: SearchHistoryDetailReq):
    detail = await RailwayPartsManager.get_v2_search_history_detail(int(req.history_id))
    # 历史候选保留检索当时的顺序和得分，父子关系按当前业务库实时补齐。
    if detail.result is not None:
        await enrich_search_items(
            detail.result.items,
            vehicle_batch=getattr(detail.search_parameter, "vehicle_batch", None),
        )
    if detail.previous_result is not None:
        await enrich_search_items(
            detail.previous_result.items,
            vehicle_batch=getattr(detail.previous_search_parameter, "vehicle_batch", None),
        )
    return detail


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

@parts_router.post(
    '/v2/search/history/cleanup/pending',
    tags=["数据清理"],
    summary='清理全部待反馈的检索历史',
    response_model=SearchHistoryDeleteRes,
    description='无需请求参数。删除 pending 及空状态旧记录、关联复核单和查询图片，返回删除数量；保留正确、错误记录及清理开始后新建的历史。',
)
async def cleanup_pending_v2_search_history():
    return await RailwayPartsManager.cleanup_pending_v2_search_history()


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
        'recommendation': '默认使用 siglip 模式；需要细粒度视觉重排时可显式选择 hybrid 模式',
        'text_search_note': '文本检索默认使用 text_vector 字段，可选 use_image_vector=true 使用 image_vector 字段'
    }
