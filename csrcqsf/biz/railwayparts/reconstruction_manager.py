"""
三维重构管理器 - 业务逻辑层
直接使用 PipelineManager，不需要额外的 API 服务
"""
from csrcqsf.logger import logger
from csrcqsf.data.pg import SessionLocal
from csrcqsf.models.reconstruction import ReconstructionRecord, ReconstructionStatus
from csrcqsf.models.item import Items
from csrcqsf.biz.railwayparts.reconstruction_server.pipelineManager import PipelineManager, JobStatus


# 全局 PipelineManager 实例
_pipeline_manager = PipelineManager()


class ReconstructionManager:
    """三维重构管理器"""
    
    @classmethod
    def get_pipeline_manager(cls) -> PipelineManager:
        """获取 PipelineManager 实例"""
        return _pipeline_manager
    
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
        # 直接调用 PipelineManager
        mgr = cls.get_pipeline_manager()
        job_id = mgr.submit(
            scene=scene,
            iterations=iterations,
            output_name=output_name
        )
        
        # 创建数据库记录
        async with SessionLocal() as session:
            await ReconstructionRecord.create_record(
                session=session,
                item_id=item_id,
                task_id=job_id,
                task_type="train",
                scene_name=scene,
                iterations=iterations
            )
            await session.commit()
        
        logger.info(f"训练任务已提交: task_id={job_id}, item_id={item_id}, scene={scene}")
        
        return {
            "task_id": job_id,
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
            其他参数见 PipelineManager.submit_video
            
        Returns:
            dict: 包含 task_id 的响应
        """
        # 直接调用 PipelineManager
        mgr = cls.get_pipeline_manager()
        job_id = mgr.submit_video(
            video_path=video_path,
            name=name,
            iterations=iterations,
            fps=fps,
            image_size=image_size,
            blur_threshold=blur_threshold,
            dedup_threshold=dedup_threshold,
            min_frames=min_frames,
            sam3_model=sam3_model,
            text_prompt=text_prompt,
            mask_dilate=mask_dilate,
            camera=camera,
            no_gpu=no_gpu,
            skip_extract=skip_extract,
            skip_filter=skip_filter,
            skip_colmap=skip_colmap,
            skip_sam3=skip_sam3,
            output_name=output_name
        )
        
        # 创建数据库记录
        async with SessionLocal() as session:
            await ReconstructionRecord.create_record(
                session=session,
                item_id=item_id,
                task_id=job_id,
                task_type="video",
                scene_name=name,
                video_path=video_path,
                iterations=iterations
            )
            await session.commit()
        
        logger.info(f"视频重建任务已提交: task_id={job_id}, item_id={item_id}, video={video_path}")
        
        return {
            "task_id": job_id,
            "item_id": item_id,
            "mode": "video",
            "message": "视频重建任务已提交"
        }
    
    @classmethod
    async def get_task_status(cls, task_id: str) -> dict:
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            dict: 任务状态信息
        """
        # 从 PipelineManager 获取实时状态
        mgr = cls.get_pipeline_manager()
        job_status = mgr.get_status(task_id)
        
        if not job_status:
            # 如果 PipelineManager 中没有，尝试从数据库获取
            async with SessionLocal() as session:
                record = await ReconstructionRecord.get_by_task_id(session, task_id)
                if record:
                    return {
                        "task_id": task_id,
                        "item_id": record.item_id,
                        "status": record.status,
                        "progress": record.progress,
                        "current_stage": record.current_stage,
                        "error_message": record.error_message,
                        "ply_url": record.ply_url,
                        "obj_url": record.obj_url,
                        "glb_url": record.glb_url,
                        "total_frames": record.total_frames,
                        "filtered_frames": record.filtered_frames,
                        "colmap_points": record.colmap_points,
                        "created_at": record.created_at.isoformat() if record.created_at else None,
                        "updated_at": record.updated_at.isoformat() if record.updated_at else None
                    }
            return {"task_id": task_id, "error": "任务不存在"}
        
        # 从数据库获取记录并更新
        async with SessionLocal() as session:
            record = await ReconstructionRecord.get_by_task_id(session, task_id)
            
            if record:
                # 映射 JobStatus 到 ReconstructionStatus
                status_map = {
                    JobStatus.PENDING: ReconstructionStatus.PENDING,
                    JobStatus.TRAINING: ReconstructionStatus.TRAINING,
                    JobStatus.RUNNING: ReconstructionStatus.TRAINING,
                    JobStatus.DONE: ReconstructionStatus.SUCCESS,
                    JobStatus.FAILED: ReconstructionStatus.FAILED
                }
                
                new_status = status_map.get(job_status["status"], record.status)
                stage = job_status.get("stage", record.current_stage)
                error = job_status.get("error", record.error_message)
                
                # 计算进度（简单估算）
                progress = record.progress
                if new_status == ReconstructionStatus.TRAINING:
                    progress = 50  # 训练中设为50%
                elif new_status == ReconstructionStatus.SUCCESS:
                    progress = 100
                
                # 更新数据库状态
                await ReconstructionRecord.update_status(
                    session=session,
                    task_id=task_id,
                    status=new_status,
                    progress=progress,
                    current_stage=stage,
                    error_message=error
                )
                
                # 如果任务成功，更新结果信息
                if new_status == ReconstructionStatus.SUCCESS:
                    ply_path = job_status.get("ply_path")
                    output_dir = job_status.get("output_dir")
                    
                    await ReconstructionRecord.update_result(
                        session=session,
                        task_id=task_id,
                        output_path=output_dir,
                        ply_url=ply_path
                    )
                    
                    # 更新配件表的 obj_url（如果有 OBJ 文件）
                    # 注意：PipelineManager 输出的是 PLY，可能需要转换
                    if ply_path:
                        item = await Items.get_item_by_id(session, record.item_id)
                        if item and not item.obj_url:
                            # 这里可以设置 PLY 路径，或者触发 PLY->OBJ 转换
                            item.obj_url = ply_path
                
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
                    "psnr": job_status.get("psnr"),
                    "elapsed_sec": job_status.get("elapsed_sec"),
                    "output_dir": job_status.get("output_dir"),
                    "log_file": job_status.get("log_file"),
                    "total_frames": record.total_frames,
                    "filtered_frames": record.filtered_frames,
                    "colmap_points": record.colmap_points,
                    "created_at": record.created_at.isoformat() if record.created_at else None,
                    "updated_at": record.updated_at.isoformat() if record.updated_at else None
                }
        
        # 如果数据库中没有记录，只返回 PipelineManager 状态
        return {
            "task_id": task_id,
            "item_id": None,
            **job_status
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
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None
                }
                for r in records
            ]
    
    @classmethod
    async def list_all_jobs(cls) -> list[dict]:
        """
        列出所有任务（从 PipelineManager）
        
        Returns:
            list[dict]: 任务列表
        """
        mgr = cls.get_pipeline_manager()
        return mgr.list_jobs()
    
    @classmethod
    def list_scenes(cls) -> list[str]:
        """
        列出可用场景
        
        Returns:
            list[str]: 场景名称列表
        """
        mgr = cls.get_pipeline_manager()
        return mgr.list_scenes()
