"""3D 重建流水线 - 完整的多角度照片到 OBJ 模型的处理流程

包含任务状态管理，支持进度查询。
"""

import asyncio
import os
import shutil
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from anyio.to_thread import run_sync
from pydantic import BaseModel, Field

from csrcqsf.biz.railwayparts.parts import RailwayPartsManager
from csrcqsf.data.minio import minio_instance
from csrcqsf.logger import logger
from csrcqsf.settings import minio_bucket, temp_dir

from .colmap_processor import ColmapProcessor
from .gaussian_trainer import GaussianTrainer
from .mesh_extractor import MeshExtractor


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"           # 等待处理
    DOWNLOADING = "downloading"   # 下载图片中
    COLMAP = "colmap"             # COLMAP 处理中
    TRAINING = "training"         # 3DGS 训练中
    EXTRACTING = "extracting"     # Mesh 提取中
    UPLOADING = "uploading"       # 上传结果中
    COMPLETED = "completed"       # 完成
    FAILED = "failed"             # 失败


class ReconstructionTask(BaseModel):
    """重建任务"""
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_id: int = 0
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0             # 0-100
    message: str = ''
    
    # 统计信息
    total_images: int = 0
    downloaded_images: int = 0
    colmap_points: int = 0
    mesh_vertices: int = 0
    mesh_faces: int = 0
    
    # 结果
    obj_url: str = ''
    
    # 时间
    created_at: str = ''
    started_at: str = ''
    completed_at: str = ''
    
    # 错误信息
    error: str = ''


# 全局任务存储 (生产环境建议使用 Redis)
_task_store: dict[str, ReconstructionTask] = {}


class ReconstructionPipeline:
    """3D 重建流水线"""
    
    @classmethod
    def get_task(cls, task_id: str) -> Optional[ReconstructionTask]:
        """获取任务状态"""
        return _task_store.get(task_id)
    
    @classmethod
    def list_tasks(cls, item_id: int = None) -> list[ReconstructionTask]:
        """列出任务"""
        tasks = list(_task_store.values())
        if item_id:
            tasks = [t for t in tasks if t.item_id == item_id]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)
    
    @classmethod
    async def create_task(cls, item_id: int, image_urls: list[str]) -> ReconstructionTask:
        """创建重建任务"""
        task = ReconstructionTask(
            item_id=item_id,
            total_images=len(image_urls),
            created_at=datetime.now().isoformat()
        )
        _task_store[task.task_id] = task
        
        # 启动后台处理
        asyncio.create_task(cls._process_task(task, image_urls))
        
        return task
    
    @classmethod
    async def create_task_from_local(
        cls, 
        local_image_dir: str, 
        item_id: int = 0,
        upload_result: bool = False
    ) -> ReconstructionTask:
        """从本地图片目录创建重建任务 (用于快速测试)
        
        Args:
            local_image_dir: 本地图片目录路径，包含多角度照片 (jpg/png)
            item_id: 配件ID，默认为0表示测试任务
            upload_result: 是否上传结果到 MinIO，默认 False
            
        Returns:
            ReconstructionTask: 重建任务对象
        """
        # 统计图片数量
        image_count = 0
        for f in os.listdir(local_image_dir):
            if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                image_count += 1
        
        task = ReconstructionTask(
            item_id=item_id,
            total_images=image_count,
            downloaded_images=image_count,
            created_at=datetime.now().isoformat()
        )
        _task_store[task.task_id] = task
        
        # 启动后台处理
        asyncio.create_task(cls._process_task_from_local(task, local_image_dir, upload_result))
        
        return task
    
    @classmethod
    async def run_local_sync(
        cls, 
        local_image_dir: str, 
        output_dir: str = None,
        iterations: int = 7000
    ) -> dict:
        """同步执行本地 3D 重建 (用于快速测试)
        
        Args:
            local_image_dir: 本地图片目录路径
            output_dir: 输出目录，默认在 temp_dir 下创建
            iterations: 3DGS 训练迭代次数，默认 7000
            
        Returns:
            dict: 包含重建结果的字典
        """
        if output_dir is None:
            output_dir = os.path.join(temp_dir, f'reconstruction_test_{uuid.uuid4().hex[:8]}')
        
        colmap_dir = os.path.join(output_dir, 'colmap')
        gs_output_dir = os.path.join(output_dir, 'gaussian')
        mesh_output_dir = os.path.join(output_dir, 'mesh')
        
        os.makedirs(colmap_dir, exist_ok=True)
        os.makedirs(gs_output_dir, exist_ok=True)
        os.makedirs(mesh_output_dir, exist_ok=True)
        
        # 创建 images 符号链接或复制
        image_link = os.path.join(output_dir, 'images')
        if not os.path.exists(image_link):
            # Windows 上使用复制，Linux 上使用符号链接
            if os.name == 'nt':
                shutil.copytree(local_image_dir, image_link)
            else:
                os.symlink(os.path.abspath(local_image_dir), image_link)
        
        result = {
            'success': False,
            'output_dir': output_dir,
            'obj_path': None,
            'message': ''
        }
        
        try:
            # Step 1: COLMAP SfM
            logger.info(f"[本地测试] 开始 COLMAP SfM: {local_image_dir}")
            colmap_result = await ColmapProcessor.run_sfm(image_link, colmap_dir)
            
            if not colmap_result['success']:
                result['message'] = f"COLMAP 失败: {colmap_result['message']}"
                return result
            
            logger.info(f"[本地测试] COLMAP 完成, 点云数量: {colmap_result['num_points']}")
            
            # Step 2: 3DGS 训练
            logger.info(f"[本地测试] 开始 3DGS 训练, 迭代次数: {iterations}")
            gs_result = await GaussianTrainer.train(
                colmap_dir=output_dir,
                output_dir=gs_output_dir,
                iterations=iterations
            )
            
            if not gs_result['success']:
                result['message'] = f"3DGS 训练失败: {gs_result['message']}"
                return result
            
            logger.info("[本地测试] 3DGS 训练完成")
            
            # Step 3: Mesh 提取
            obj_path = os.path.join(mesh_output_dir, 'output.obj')
            logger.info(f"[本地测试] 开始 Mesh 提取: {obj_path}")
            
            mesh_result = await MeshExtractor.extract_mesh(
                gaussian_model_dir=gs_output_dir,
                colmap_dir=output_dir,
                output_path=obj_path
            )
            
            if not mesh_result['success']:
                result['message'] = f"Mesh 提取失败: {mesh_result['message']}"
                return result
            
            result['success'] = True
            result['obj_path'] = obj_path
            result['num_vertices'] = mesh_result['num_vertices']
            result['num_faces'] = mesh_result['num_faces']
            result['message'] = '3D 重建完成'
            
            logger.info(f"[本地测试] 完成! OBJ: {obj_path}, 顶点: {mesh_result['num_vertices']}, 面: {mesh_result['num_faces']}")
            
            return result
            
        except Exception as e:
            logger.exception(f"[本地测试] 重建失败: {e}")
            result['message'] = str(e)
            return result
    
    @classmethod
    async def _process_task_from_local(
        cls, 
        task: ReconstructionTask, 
        local_image_dir: str,
        upload_result: bool = False
    ):
        """处理本地图片重建任务"""
        task.started_at = datetime.now().isoformat()
        
        # 创建工作目录
        work_dir = os.path.join(temp_dir, f'reconstruction_{task.task_id}')
        colmap_dir = os.path.join(work_dir, 'colmap')
        gs_output_dir = os.path.join(work_dir, 'gaussian')
        mesh_output_dir = os.path.join(work_dir, 'mesh')
        
        os.makedirs(colmap_dir, exist_ok=True)
        os.makedirs(gs_output_dir, exist_ok=True)
        os.makedirs(mesh_output_dir, exist_ok=True)
        
        # 创建 images 链接
        image_link = os.path.join(work_dir, 'images')
        if os.name == 'nt':
            shutil.copytree(local_image_dir, image_link)
        else:
            os.symlink(os.path.abspath(local_image_dir), image_link)
        
        try:
            # Step 1: COLMAP SfM (40%)
            task.status = TaskStatus.COLMAP
            task.message = '正在进行相机位姿估计...'
            task.progress = 10
            _task_store[task.task_id] = task
            
            colmap_result = await ColmapProcessor.run_sfm(image_link, colmap_dir)
            
            if not colmap_result['success']:
                raise Exception(f"COLMAP 失败: {colmap_result['message']}")
            
            task.colmap_points = colmap_result['num_points']
            task.progress = 40
            _task_store[task.task_id] = task
            
            # Step 2: 3DGS 训练 (80%)
            task.status = TaskStatus.TRAINING
            task.message = '正在训练 3D Gaussian Splatting...'
            task.progress = 45
            _task_store[task.task_id] = task
            
            gs_result = await GaussianTrainer.train(
                colmap_dir=work_dir,
                output_dir=gs_output_dir,
                iterations=7000
            )
            
            if not gs_result['success']:
                raise Exception(f"3DGS 训练失败: {gs_result['message']}")
            
            task.progress = 80
            _task_store[task.task_id] = task
            
            # Step 3: Mesh 提取 (95%)
            task.status = TaskStatus.EXTRACTING
            task.message = '正在提取三角网格...'
            task.progress = 82
            _task_store[task.task_id] = task
            
            obj_filename = f'part_{task.item_id}.obj' if task.item_id else 'output.obj'
            obj_path = os.path.join(mesh_output_dir, obj_filename)
            
            mesh_result = await MeshExtractor.extract_mesh(
                gaussian_model_dir=gs_output_dir,
                colmap_dir=work_dir,
                output_path=obj_path
            )
            
            if not mesh_result['success']:
                raise Exception(f"Mesh 提取失败: {mesh_result['message']}")
            
            task.mesh_vertices = mesh_result['num_vertices']
            task.mesh_faces = mesh_result['num_faces']
            task.progress = 95
            _task_store[task.task_id] = task
            
            # Step 4: 上传结果 (可选)
            if upload_result and task.item_id:
                task.status = TaskStatus.UPLOADING
                task.message = '正在上传结果...'
                _task_store[task.task_id] = task
                
                minio_obj_path = f'models/{task.item_id}/{obj_filename}'
                await run_sync(
                    minio_instance.upload_file,
                    minio_bucket, minio_obj_path, obj_path
                )
                
                task.obj_url = f'{minio_bucket}/{minio_obj_path}'
                await cls._update_item_obj_url(task.item_id, task.obj_url)
            else:
                task.obj_url = obj_path  # 本地路径
            
            # 完成
            task.status = TaskStatus.COMPLETED
            task.message = '3D 重建完成'
            task.progress = 100
            task.completed_at = datetime.now().isoformat()
            _task_store[task.task_id] = task
            
            logger.info(f"[本地测试] 重建任务完成: task_id={task.task_id}, obj={task.obj_url}")
            
        except Exception as e:
            logger.error(f"[本地测试] 重建任务失败: task_id={task.task_id}, error={e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.message = f'重建失败: {str(e)}'
            _task_store[task.task_id] = task
            
        finally:
            # 本地测试不自动清理，方便检查结果
            pass
    
    @classmethod
    async def _process_task(cls, task: ReconstructionTask, image_urls: list[str]):
        """处理重建任务"""
        task.started_at = datetime.now().isoformat()
        
        # 创建工作目录
        work_dir = os.path.join(temp_dir, f'reconstruction_{task.task_id}')
        image_dir = os.path.join(work_dir, 'images')
        colmap_dir = os.path.join(work_dir, 'colmap')
        gs_output_dir = os.path.join(work_dir, 'gaussian')
        mesh_output_dir = os.path.join(work_dir, 'mesh')
        
        os.makedirs(image_dir, exist_ok=True)
        os.makedirs(colmap_dir, exist_ok=True)
        os.makedirs(gs_output_dir, exist_ok=True)
        os.makedirs(mesh_output_dir, exist_ok=True)
        
        try:
            # Step 1: 下载图片 (10%)
            task.status = TaskStatus.DOWNLOADING
            task.message = '正在下载图片...'
            task.progress = 5
            _task_store[task.task_id] = task
            
            await cls._download_images(task, image_urls, image_dir)
            task.progress = 10
            _task_store[task.task_id] = task
            
            # Step 2: COLMAP SfM (40%)
            task.status = TaskStatus.COLMAP
            task.message = '正在进行相机位姿估计...'
            task.progress = 15
            _task_store[task.task_id] = task
            
            colmap_result = await ColmapProcessor.run_sfm(image_dir, colmap_dir)
            
            if not colmap_result['success']:
                raise Exception(f"COLMAP 失败: {colmap_result['message']}")
            
            task.colmap_points = colmap_result['num_points']
            task.progress = 40
            _task_store[task.task_id] = task
            
            # Step 3: 3DGS 训练 (80%)
            task.status = TaskStatus.TRAINING
            task.message = '正在训练 3D Gaussian Splatting...'
            task.progress = 45
            _task_store[task.task_id] = task
            
            gs_result = await GaussianTrainer.train(
                colmap_dir=work_dir,  # 3DGS 需要包含 images 和 sparse 的父目录
                output_dir=gs_output_dir,
                iterations=7000
            )
            
            if not gs_result['success']:
                raise Exception(f"3DGS 训练失败: {gs_result['message']}")
            
            task.progress = 80
            _task_store[task.task_id] = task
            
            # Step 4: Mesh 提取 (95%)
            task.status = TaskStatus.EXTRACTING
            task.message = '正在提取三角网格...'
            task.progress = 82
            _task_store[task.task_id] = task
            
            obj_filename = f'part_{task.item_id}.obj'
            obj_path = os.path.join(mesh_output_dir, obj_filename)
            
            mesh_result = await MeshExtractor.extract_mesh(
                gaussian_model_dir=gs_output_dir,
                colmap_dir=work_dir,
                output_path=obj_path
            )
            
            if not mesh_result['success']:
                raise Exception(f"Mesh 提取失败: {mesh_result['message']}")
            
            task.mesh_vertices = mesh_result['num_vertices']
            task.mesh_faces = mesh_result['num_faces']
            task.progress = 95
            _task_store[task.task_id] = task
            
            # Step 5: 上传结果 (100%)
            task.status = TaskStatus.UPLOADING
            task.message = '正在上传结果...'
            _task_store[task.task_id] = task
            
            # 上传到 MinIO
            minio_obj_path = f'models/{task.item_id}/{obj_filename}'
            await run_sync(
                minio_instance.upload_file,
                minio_bucket, minio_obj_path, obj_path
            )
            
            task.obj_url = f'{minio_bucket}/{minio_obj_path}'
            
            # 更新配件的 obj_url
            await cls._update_item_obj_url(task.item_id, task.obj_url)
            
            # 完成
            task.status = TaskStatus.COMPLETED
            task.message = '3D 重建完成'
            task.progress = 100
            task.completed_at = datetime.now().isoformat()
            _task_store[task.task_id] = task
            
            logger.info(f"重建任务完成: task_id={task.task_id}, obj_url={task.obj_url}")
            
        except Exception as e:
            logger.error(f"重建任务失败: task_id={task.task_id}, error={e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.message = f'重建失败: {str(e)}'
            _task_store[task.task_id] = task
            
        finally:
            # 清理临时文件
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception as e:
                logger.exception(f"清理临时文件失败:{e}")
    
    @classmethod
    async def _download_images(cls, task: ReconstructionTask, image_urls: list[str], output_dir: str):
        """下载所有图片"""
        import cv2
        
        for i, url in enumerate(image_urls):
            try:
                image = await RailwayPartsManager.get_image_from_oss(url)
                if image is not None:
                    # 保存图片 (COLMAP 需要 jpg/png)
                    filename = f'image_{i:04d}.jpg'
                    filepath = os.path.join(output_dir, filename)
                    cv2.imwrite(filepath, image)
                    task.downloaded_images += 1
                    _task_store[task.task_id] = task
            except Exception as e:
                logger.warning(f"下载图片失败 [{url}]: {e}")
        
        if task.downloaded_images < 10:
            raise Exception(f"有效图片不足: 下载了 {task.downloaded_images} 张，至少需要 10 张")
    
    @classmethod
    async def _update_item_obj_url(cls, item_id: int, obj_url: str):
        """更新配件的 OBJ URL"""
        from csrcqsf.data.pg import SessionLocal
        from csrcqsf.models.item import Items
        
        try:
            async with SessionLocal() as session:
                item = await Items.get_item_by_id(session, item_id)
                if item:
                    item.obj_url = obj_url
                    await session.commit()
        except Exception as e:
            logger.warning(f"更新配件 obj_url 失败: {e}")
