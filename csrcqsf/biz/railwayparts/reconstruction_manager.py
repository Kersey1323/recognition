"""
三维重构管理器 - 业务逻辑层
直接调用 Celery 任务，支持 Flower 监控
"""
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from anyio.to_thread import run_sync
from bfrcommon.snowflake import get_id
from celery.result import AsyncResult
from fastapi import HTTPException
from globals_vars import logger
from csrcqsf.data.minio import ensure_minio_bucket, looks_like_minio_path, minio_instance
from csrcqsf.data.pg import SessionLocal
from csrcqsf.models.reconstruction import ReconstructionRecord, ReconstructionStatus
from csrcqsf.models.item import Items
from csrcqsf.settings import minio_reconstruction_video_bucket

# 导入 Celery app 和 tasks - 使用延迟导入避免启动时的循环依赖
_celery_app = None
_train_reconstruction = None
_video_reconstruction = None

def _get_celery_modules():
    """延迟导入 Celery 模块"""
    global _celery_app, _train_reconstruction, _video_reconstruction
    
    if _celery_app is None:
        reconstruction_server_path = Path(__file__).parent / "reconstruction_server"
        if str(reconstruction_server_path) not in sys.path:
            sys.path.insert(0, str(reconstruction_server_path))
        
        from celery_app import celery_app
        from tasks import train_reconstruction, video_reconstruction
        
        _celery_app = celery_app
        _train_reconstruction = train_reconstruction
        _video_reconstruction = video_reconstruction
    
    return _celery_app, _train_reconstruction, _video_reconstruction

# 路径配置
BASE_DIR = Path(__file__).parent / "reconstruction_server"
DATA_DIR = BASE_DIR / "data"


class ReconstructionManager:
    """三维重构管理器"""

    @classmethod
    async def _require_item_exists(cls, item_id: int):
        """确保配件存在，避免重建记录写入时触发外键异常。"""
        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session, item_id)

        if item is None:
            raise HTTPException(
                status_code=400,
                detail=f"配件不存在，无法创建重建任务: item_id={item_id}"
            )

        return item

    @staticmethod
    def _safe_filename(filename: str | None) -> str:
        raw_name = Path(filename or "source_video.mp4").name
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
        return safe_name or "source_video.mp4"

    @classmethod
    async def upload_source_video(cls, item_id: int, file) -> dict:
        """
        上传三维重构原始视频到独立 MinIO bucket。

        返回的 video_path 可直接传给 submit_video_task / /v2/reconstruct/video。
        """
        await cls._require_item_exists(item_id)
        ensure_minio_bucket(minio_reconstruction_video_bucket)

        safe_name = cls._safe_filename(file.filename)
        date_dir = datetime.now().strftime("%Y%m%d")
        object_name = f"raw-videos/{item_id}/{date_dir}/{get_id()}_{safe_name}"
        content_type = file.content_type or "application/octet-stream"

        def _upload() -> int:
            file.file.seek(0, os.SEEK_END)
            size = file.file.tell()
            file.file.seek(0)
            minio_instance.client.put_object(
                minio_reconstruction_video_bucket,
                object_name,
                file.file,
                length=size,
                content_type=content_type,
            )
            return size

        size = await run_sync(_upload)
        await file.close()

        return {
            "item_id": item_id,
            "bucket": minio_reconstruction_video_bucket,
            "object_name": object_name,
            "video_path": f"{minio_reconstruction_video_bucket}/{object_name}",
            "size": size,
            "content_type": content_type,
            "message": "原始视频上传成功",
        }
    
    @classmethod
    async def submit_train_task(
        cls,
        item_id: int,
        scene: str,
        iterations: int = 30000,
        output_name: str = None
    ) -> dict:
        """
        提交训练任务（从已有场景数据）
        
        Args:
            item_id: 配件ID
            scene: 场景名称
            iterations: 训练迭代次数
            output_name: 输出名称
            
        Returns:
            dict: 包含 task_id 的响应
        """
        await cls._require_item_exists(item_id)

        # 获取 Celery 模块
        _, train_reconstruction, _ = _get_celery_modules()
        
        # 检查场景是否存在
        scene_dir = DATA_DIR / scene
        if not scene_dir.exists():
            raise ValueError(f"场景 '{scene}' 不存在: {scene_dir}")
        
        # 生成输出名称
        if not output_name:
            output_name = f"{scene}_{int(os.urandom(4).hex(), 16):08x}"
        
        # 提交 Celery 任务
        task = train_reconstruction.apply_async(
            args=[scene, iterations, output_name]
        )
        task_id = task.id
        
        # 创建数据库记录
        async with SessionLocal() as session:
            await ReconstructionRecord.create_record(
                session=session,
                item_id=item_id,
                task_id=task_id,
                task_type="train",
                scene_name=scene,
                iterations=iterations
            )
            await session.commit()
        
        logger.info(f"训练任务已提交: task_id={task_id}, item_id={item_id}, scene={scene}")
        
        return {
            "task_id": task_id,
            "item_id": item_id,
            "mode": "train",
            "message": "训练任务已提交"
        }
    
    @classmethod
    async def submit_video_task(
        cls,
        item_id: int,
        video_path: str,
        name: str,
        iterations: int = 30000,
        fps: float = 3,
        image_size: int = 1600,
        blur_threshold: float = 0,
        dedup_threshold: int = 25,
        min_frames: int = 30,
        sam3_model: str = "",
        text_prompt: str = "object",
        mask_dilate: int = 15,
        camera: str = "OPENCV",
        no_gpu: bool = True,
        skip_extract: bool = False,
        skip_filter: bool = False,
        skip_colmap: bool = False,
        skip_sam3: bool = False,
        output_name: str = None
    ) -> dict:
        """
        提交视频重建任务
        
        Args:
            item_id: 配件ID
            video_path: 视频文件路径
            name: 场景名称
            iterations: 训练迭代次数
            其他参数见 video_reconstruction task
            
        Returns:
            dict: 包含 task_id 的响应
        """
        await cls._require_item_exists(item_id)

        # 获取 Celery 模块
        _, _, video_reconstruction = _get_celery_modules()
        
        # 本地路径直接检查；MinIO 对象路径由 Celery worker 下载后再检查。
        if not looks_like_minio_path(video_path) and not os.path.exists(video_path):
            raise ValueError(f"视频文件不存在: {video_path}")
        
        # 生成输出名称
        if not output_name:
            output_name = f"{name}_{int(os.urandom(4).hex(), 16):08x}"
        
        # 提交 Celery 任务
        task = video_reconstruction.apply_async(
            kwargs={
                "video_path": video_path,
                "name": name,
                "iterations": iterations,
                "output_name": output_name,
                "fps": fps,
                "image_size": image_size,
                "blur_threshold": blur_threshold,
                "dedup_threshold": dedup_threshold,
                "min_frames": min_frames,
                "sam3_model": sam3_model,
                "text_prompt": text_prompt,
                "mask_dilate": mask_dilate,
                "camera": camera,
                "no_gpu": no_gpu,
                "skip_extract": skip_extract,
                "skip_filter": skip_filter,
                "skip_colmap": skip_colmap,
                "skip_sam3": skip_sam3,
            }
        )
        task_id = task.id
        
        # 创建数据库记录
        async with SessionLocal() as session:
            await ReconstructionRecord.create_record(
                session=session,
                item_id=item_id,
                task_id=task_id,
                task_type="video",
                scene_name=name,
                video_path=video_path,
                iterations=iterations
            )
            await session.commit()
        
        logger.info(f"视频重建任务已提交: task_id={task_id}, item_id={item_id}, video={video_path}")
        
        return {
            "task_id": task_id,
            "item_id": item_id,
            "mode": "video",
            "message": "视频重建任务已提交"
        }
    
    @classmethod
    async def get_task_status(cls, task_id: str) -> dict:
        """
        获取任务状态（从 Celery）
        
        Args:
            task_id: 任务ID
            
        Returns:
            dict: 任务状态信息
        """
        # 获取 Celery 模块
        celery_app, _, _ = _get_celery_modules()
        
        # 从 Celery 获取任务状态
        result = AsyncResult(task_id, app=celery_app)
        
        # 从数据库获取记录
        async with SessionLocal() as session:
            record = await ReconstructionRecord.get_by_task_id(session, task_id)
            
            if not record:
                # 如果数据库中没有记录，只返回 Celery 状态
                response = {
                    "task_id": task_id,
                    "status": result.state,
                    "result": None,
                    "error": None,
                    "stage": None,
                    "progress": 0,
                }
                
                if result.state == "PENDING":
                    response["stage"] = "等待中"
                elif result.state == "STARTED":
                    response["stage"] = "已开始"
                elif result.state == "PROGRESS":
                    info = result.info or {}
                    response["stage"] = info.get("stage", "处理中")
                    response["progress"] = info.get("progress", 0)
                elif result.state == "SUCCESS":
                    response["stage"] = "完成"
                    response["progress"] = 100
                    response["result"] = result.result
                elif result.state == "FAILURE":
                    response["stage"] = "失败"
                    response["error"] = str(result.info)
                
                return response
            
            # 映射 Celery 状态到 ReconstructionStatus
            status_map = {
                "PENDING": ReconstructionStatus.PENDING,
                "STARTED": ReconstructionStatus.TRAINING,
                "PROGRESS": ReconstructionStatus.TRAINING,
                "SUCCESS": ReconstructionStatus.SUCCESS,
                "FAILURE": ReconstructionStatus.FAILED,
            }
            
            new_status = status_map.get(result.state, record.status)
            
            # 获取进度和阶段信息
            progress = record.progress
            stage = record.current_stage
            error = record.error_message
            
            if result.state == "PROGRESS":
                info = result.info or {}
                stage = info.get("stage", stage)
                progress = info.get("progress", progress)
            elif result.state == "SUCCESS":
                progress = 100
                stage = "完成"
                # 更新结果信息
                task_result = result.result or {}
                if task_result.get("ply_path"):
                    await ReconstructionRecord.update_result(
                        session=session,
                        task_id=task_id,
                        output_path=task_result.get("output_dir"),
                        ply_url=task_result.get("ply_path")
                    )
            elif result.state == "FAILURE":
                error = str(result.info)
                stage = "失败"
            
            # 更新数据库状态
            if new_status != record.status or progress != record.progress:
                await ReconstructionRecord.update_status(
                    session=session,
                    task_id=task_id,
                    status=new_status,
                    progress=progress,
                    current_stage=stage,
                    error_message=error
                )
                await session.commit()
            
            # 返回完整信息
            return {
                "task_id": task_id,
                "item_id": record.item_id,
                "status": new_status,
                "progress": progress,
                "current_stage": stage,
                "error_message": error,
                "ply_url": record.ply_url,
                "obj_url": record.obj_url,
                "glb_url": record.glb_url,
                "total_frames": record.total_frames,
                "filtered_frames": record.filtered_frames,
                "colmap_points": record.colmap_points,
                "time_created": record.time_created.isoformat() if record.time_created else None,
                "time_updated": record.time_updated.isoformat() if record.time_updated else None
            }
    
    @classmethod
    async def list_item_tasks(cls, item_id: int) -> list[dict]:
        """
        列出配件的所有重构任务
        
        Args:
            item_id: 配件ID
            
        Returns:
            list[dict]: 任务列表
        """
        async with SessionLocal() as session:
            records = await ReconstructionRecord.get_by_item_id(session, item_id)
            
            return [
                {
                    "task_id": r.task_id,
                    "item_id": r.item_id,
                    "status": r.status,
                    "progress": r.progress,
                    "current_stage": r.current_stage,
                    "error_message": r.error_message,
                    "ply_url": r.ply_url,
                    "obj_url": r.obj_url,
                    "glb_url": r.glb_url,
                    "total_frames": r.total_frames,
                    "filtered_frames": r.filtered_frames,
                    "colmap_points": r.colmap_points,
                    "time_created": r.time_created.isoformat() if r.time_created else None,
                    "time_updated": r.time_updated.isoformat() if r.time_updated else None
                }
                for r in records
            ]
    
    @classmethod
    async def list_all_tasks(
        cls,
        status: str = None,
        limit: int = 100,
        offset: int = 0
    ) -> dict:
        """
        列出所有重构任务（支持分页和状态筛选）
        
        Args:
            status: 任务状态筛选（可选）
            limit: 每页数量
            offset: 偏移量
            
        Returns:
            dict: 包含任务列表和总数
        """
        async with SessionLocal() as session:
            records, total = await ReconstructionRecord.get_all_tasks(
                session=session,
                status=status,
                limit=limit,
                offset=offset
            )
            
            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "records": [
                    {
                        "task_id": r.task_id,
                        "item_id": r.item_id,
                        "task_type": r.task_type,
                        "status": r.status,
                        "progress": r.progress,
                        "current_stage": r.current_stage,
                        "scene_name": r.scene_name,
                        "error_message": r.error_message,
                        "ply_url": r.ply_url,
                        "obj_url": r.obj_url,
                        "glb_url": r.glb_url,
                        "total_frames": r.total_frames,
                        "filtered_frames": r.filtered_frames,
                        "colmap_points": r.colmap_points,
                        "time_created": r.time_created.isoformat() if r.time_created else None,
                        "time_updated": r.time_updated.isoformat() if r.time_updated else None
                    }
                    for r in records
                ]
            }
    
    @classmethod
    def list_scenes(cls) -> list[str]:
        """
        列出可用场景
        
        Returns:
            list[str]: 场景名称列表
        """
        if not DATA_DIR.exists():
            return []
        return sorted(
            d.name for d in DATA_DIR.iterdir()
            if d.is_dir() and (d / "sparse").exists()
        )
    
    @classmethod
    async def cancel_task(cls, task_id: str) -> dict:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            dict: 取消结果
        """
        # 获取 Celery 模块
        celery_app, _, _ = _get_celery_modules()
        
        result = AsyncResult(task_id, app=celery_app)
        result.revoke(terminate=True)
        
        # 更新数据库状态
        async with SessionLocal() as session:
            await ReconstructionRecord.update_status(
                session=session,
                task_id=task_id,
                status=ReconstructionStatus.FAILED,
                error_message="任务已取消"
            )
            await session.commit()
        
        logger.info(f"任务已取消: task_id={task_id}")
        
        return {"message": f"任务 {task_id} 已取消"}
