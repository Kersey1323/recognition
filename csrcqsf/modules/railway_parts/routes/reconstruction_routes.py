"""Routes for reconstruction source videos, tasks, and results."""

from fastapi import File, Form, UploadFile

from csrcqsf.modules.railway_parts.schemas.reconstruction import (
    ReconstructionAllTasksReq,
    ReconstructionAllTasksRes,
    ReconstructionListRes,
    ReconstructionResultMessageRes,
    ReconstructionResultUploadRes,
    ReconstructionSourceVideoListReq,
    ReconstructionSourceVideoListRes,
    ReconstructionSourceVideoMessageRes,
    ReconstructionSourceVideoRes,
    ReconstructionStatisticsReq,
    ReconstructionStatisticsRes,
    ReconstructionStatusRes,
    ReconstructionTaskItemDetailReq,
    ReconstructionTaskItemDetailRes,
    ReconstructionTaskRes,
    ReconstructionTrainReq,
    ReconstructionVideoReq,
    ReconstructionVideoUploadAbortReq,
    ReconstructionVideoUploadCompleteReq,
    ReconstructionVideoUploadInitReq,
    ReconstructionVideoUploadInitRes,
    ReconstructionVideoUploadMinioHealthRes,
    ReconstructionVideoUploadPartRes,
    ReconstructionVideoUploadProgressReq,
    ReconstructionVideoUploadProgressRes,
    ReconstructionVideoUploadUrlsReq,
    ReconstructionVideoUploadUrlsRes,
)
from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager
from csrcqsf.core.runtime import ensure_gpu_reconstruction_enabled

from .router import parts_router


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
    ensure_gpu_reconstruction_enabled()
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

    上传完成后，服务端会把 `video_path` 绑定到对应配件；后续发起重构时只需传 `item_id`。
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


@parts_router.post('/v2/reconstruct/video/upload/init', tags=["算法-3D重建V2"], summary='V2: 初始化原始视频分片上传')
async def init_reconstruct_v2_video_upload(req: ReconstructionVideoUploadInitReq):
    result = await ReconstructionManager.init_source_video_multipart_upload(
        item_id=int(req.item_id),
        file_name=req.file_name,
        file_size=req.file_size,
        content_type=req.content_type or "application/octet-stream",
        storage_mode=req.storage_mode,
        height=req.height,
        length=req.length,
        width=req.width,
        weight=req.weight,
    )
    return ReconstructionVideoUploadInitRes(**result)


@parts_router.post('/v2/reconstruct/video/upload/part', tags=["算法-3D重建V2"], summary='V2: 上传单个视频分片')
async def upload_reconstruct_v2_video_part(
    upload_session_id: str = Form(...),
    part_number: int = Form(...),
    file: UploadFile = File(...),
):
    result = await ReconstructionManager.upload_source_video_part(
        upload_session_id=int(upload_session_id),
        part_number=part_number,
        file=file,
    )
    return ReconstructionVideoUploadPartRes(**result)


@parts_router.post('/v2/reconstruct/video/upload/progress', tags=["算法-3D重建V2"], summary='V2: 查询原始视频分片上传进度')
async def get_reconstruct_v2_video_upload_progress(req: ReconstructionVideoUploadProgressReq):
    result = await ReconstructionManager.get_source_video_upload_progress(
        upload_session_id=int(req.upload_session_id),
    )
    return ReconstructionVideoUploadProgressRes(**result)


@parts_router.post('/v2/reconstruct/video/upload/urls', tags=["算法-3D重建V2"], summary='V2: 获取原始视频分片上传地址')
async def get_reconstruct_v2_video_upload_urls(req: ReconstructionVideoUploadUrlsReq):
    result = await ReconstructionManager.get_source_video_upload_urls(
        upload_session_id=int(req.upload_session_id),
        part_numbers=req.part_numbers,
    )
    return ReconstructionVideoUploadUrlsRes(**result)


@parts_router.post('/v2/reconstruct/video/upload/complete', tags=["算法-3D重建V2"], summary='V2: 完成原始视频分片上传')
async def complete_reconstruct_v2_video_upload(req: ReconstructionVideoUploadCompleteReq):
    result = await ReconstructionManager.complete_source_video_multipart_upload(
        upload_session_id=int(req.upload_session_id),
    )
    return ReconstructionSourceVideoRes(**result)


@parts_router.post('/v2/reconstruct/video/upload/abort', tags=["算法-3D重建V2"], summary='V2: 取消原始视频分片上传')
async def abort_reconstruct_v2_video_upload(req: ReconstructionVideoUploadAbortReq):
    result = await ReconstructionManager.abort_source_video_multipart_upload(
        upload_session_id=int(req.upload_session_id),
    )
    return ReconstructionSourceVideoMessageRes(**result)


@parts_router.post('/v2/reconstruct/video/upload/minio/health', tags=["算法-3D重建V2"], summary='V2: 检查 MinIO 并批量同步本地上传任务')
async def health_reconstruct_v2_video_minio_and_sync():
    result = await ReconstructionManager.check_minio_and_sync_local_uploads()
    return ReconstructionVideoUploadMinioHealthRes(**result)


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


@parts_router.post('/v2/reconstruct/tasks/video', tags=["算法-3D重建V2"], summary='V2: 从视频完整重建（V3自动分割）')
async def reconstruct_v2_video(req: ReconstructionVideoReq):
    """
    完整视频重建流程

    流程：已绑定原始视频 → 提帧 → 去模糊去重 → COLMAP → YOLO+SAM2 自动分割 → 3DGS训练

    参数：
    - item_id: 配件ID
    - iterations: 训练迭代次数
    - fps / image_size / blur_threshold / dedup_threshold / min_frames / max_frames: 帧提取与筛选参数
    - mask_dilate / fill_interior_holes: 分割后处理参数
    - camera / colmap_gpu: COLMAP 参数，默认使用 CPU

    说明：
    - 服务端会根据 `item_id` 自动读取已绑定的 `video_path` 和配件名称
    - 输出目录默认使用 `时间_item_name` 作为运行名
    - 业务接口不再暴露 SAM3 / prompt / 手工框 / 断点调试参数

    返回：
    - task_id: 任务ID，用于查询进度
    """
    ensure_gpu_reconstruction_enabled()
    result = await ReconstructionManager.submit_video_task(
        item_id=int(req.item_id),
        iterations=req.iterations,
        fps=req.fps,
        image_size=req.image_size,
        blur_threshold=req.blur_threshold,
        dedup_threshold=req.dedup_threshold,
        min_frames=req.min_frames,
        max_frames=req.max_frames,
        mask_dilate=req.mask_dilate,
        fill_interior_holes=req.fill_interior_holes,
        camera=req.camera,
        colmap_gpu=req.colmap_gpu,
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


@parts_router.delete('/v2/reconstruct/result/{task_id}', tags=["算法-3D重建V2"], summary='V2: 删除指定重构任务的三维模型')
async def delete_reconstruct_v2_result(task_id: str):
    """
    删除指定重构任务生成的三维模型。

    行为：
    - 按 `task_id` 删除该任务的 MinIO 模型对象
    - 清空该任务的 `ply_url/obj_url/glb_url`，保留任务历史和 `output_path`
    - 只有 `item_info.obj_url` 指向该任务模型时才清空配件当前绑定
    - 删除历史任务模型不会影响配件当前绑定的其他模型
    """
    result = await ReconstructionManager.delete_reconstruction_result(task_id)
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


@parts_router.post('/v2/reconstruct/tasks/get_item_details', tags=["算法-3D重建V2"], summary='V2: 获取重建任务详情')
async def get_reconstruct_v2_task_item_details(req: ReconstructionTaskItemDetailReq):
    """按任务ID返回对应重建结果和配件信息，避免同一配件的多次重建结果互相覆盖。"""
    result = await ReconstructionManager.get_task_item_detail(req.task_id)
    return ReconstructionTaskItemDetailRes(**result)


@parts_router.post('/v2/reconstruct/statistics', tags=["算法-3D重建V2"], summary='V2: 三维重构统计')
async def reconstruct_v2_statistics(_req: ReconstructionStatisticsReq):
    result = await ReconstructionManager.statistics()
    return ReconstructionStatisticsRes(**result)


@parts_router.delete('/v2/reconstruct/cancel/{task_id}', tags=["算法-3D重建V2"], summary='V2: 取消任务')
async def cancel_reconstruct_task(task_id: str):
    """取消正在执行的重建任务"""
    ensure_gpu_reconstruction_enabled()
    return await ReconstructionManager.cancel_task(task_id)


@parts_router.get('/v2/reconstruct/scenes', tags=["算法-3D重建V2"], summary='V2: 列出可用场景')
async def list_reconstruction_scenes():
    """
    列出 reconstruction_server/data/ 目录下所有可用场景

    返回已准备好 COLMAP 数据的场景，可直接用于训练
    """
    scenes = await ReconstructionManager.list_scenes()
    return {"scenes": scenes}
