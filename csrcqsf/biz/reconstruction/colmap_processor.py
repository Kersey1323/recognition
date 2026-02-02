"""COLMAP 处理器 - 相机位姿估计 (Structure from Motion)

从多角度照片中估计相机位姿和稀疏点云，为后续 3D Gaussian Splatting 提供输入。
"""

import os
import subprocess
import shutil
from pathlib import Path
from anyio.to_thread import run_sync

from csrcqsf.logger import logger, CodeTimer


class ColmapProcessor:
    """COLMAP 相机位姿估计处理器"""
    
    @classmethod
    def _check_colmap_installed(cls) -> bool:
        """检查 COLMAP 是否已安装"""
        try:
            result = subprocess.run(['colmap', '-h'], capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False
    
    @classmethod
    def _run_command(cls, cmd: list[str], cwd: str = None) -> tuple[bool, str]:
        """运行命令并返回结果"""
        try:
            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=3600  # 1小时超时
            )
            if result.returncode != 0:
                logger.error(f"Command failed: {result.stderr}")
                return False, result.stderr
            return True, result.stdout
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)
    
    @classmethod
    def _run_sfm_sync(cls, image_dir: str, output_dir: str, use_gpu: bool = True) -> dict:
        """同步运行 COLMAP SfM 流程
        
        Args:
            image_dir: 输入图片目录
            output_dir: 输出目录
            use_gpu: 是否使用 GPU 加速
            
        Returns:
            dict: 包含 success, message, sparse_dir 等信息
        """
        result = {
            'success': False,
            'message': '',
            'sparse_dir': '',
            'num_images': 0,
            'num_points': 0
        }
        
        # 检查 COLMAP
        if not cls._check_colmap_installed():
            result['message'] = 'COLMAP 未安装，请先安装: apt install colmap'
            return result
        
        # 创建工作目录
        database_path = os.path.join(output_dir, 'database.db')
        sparse_dir = os.path.join(output_dir, 'sparse')
        os.makedirs(sparse_dir, exist_ok=True)
        
        gpu_flag = '1' if use_gpu else '0'
        
        # Step 1: 特征提取
        with CodeTimer(name='COLMAP特征提取'):
            success, msg = cls._run_command([
                'colmap', 'feature_extractor',
                '--database_path', database_path,
                '--image_path', image_dir,
                '--ImageReader.single_camera', '1',
                '--SiftExtraction.use_gpu', gpu_flag
            ])
            if not success:
                result['message'] = f'特征提取失败: {msg}'
                return result
        
        # Step 2: 特征匹配 (exhaustive for small datasets)
        with CodeTimer(name='COLMAP特征匹配'):
            success, msg = cls._run_command([
                'colmap', 'exhaustive_matcher',
                '--database_path', database_path,
                '--SiftMatching.use_gpu', gpu_flag
            ])
            if not success:
                result['message'] = f'特征匹配失败: {msg}'
                return result
        
        # Step 3: 稀疏重建 (mapper)
        with CodeTimer(name='COLMAP稀疏重建'):
            success, msg = cls._run_command([
                'colmap', 'mapper',
                '--database_path', database_path,
                '--image_path', image_dir,
                '--output_path', sparse_dir
            ])
            if not success:
                result['message'] = f'稀疏重建失败: {msg}'
                return result
        
        # 检查输出
        sparse_model_dir = os.path.join(sparse_dir, '0')
        if not os.path.exists(sparse_model_dir):
            result['message'] = 'COLMAP 重建失败，未生成模型'
            return result
        
        # Step 4: 转换为文本格式 (便于后续处理)
        with CodeTimer(name='COLMAP模型转换'):
            success, msg = cls._run_command([
                'colmap', 'model_converter',
                '--input_path', sparse_model_dir,
                '--output_path', sparse_model_dir,
                '--output_type', 'TXT'
            ])
        
        result['success'] = True
        result['message'] = 'COLMAP SfM 完成'
        result['sparse_dir'] = sparse_model_dir
        
        # 统计信息
        images_txt = os.path.join(sparse_model_dir, 'images.txt')
        points_txt = os.path.join(sparse_model_dir, 'points3D.txt')
        
        if os.path.exists(images_txt):
            with open(images_txt, 'r') as f:
                lines = [l for l in f.readlines() if not l.startswith('#') and l.strip()]
                result['num_images'] = len(lines) // 2  # 每张图占2行
        
        if os.path.exists(points_txt):
            with open(points_txt, 'r') as f:
                lines = [l for l in f.readlines() if not l.startswith('#') and l.strip()]
                result['num_points'] = len(lines)
        
        logger.info(f"COLMAP 完成: {result['num_images']} 张图, {result['num_points']} 个点")
        
        return result
    
    @classmethod
    async def run_sfm(cls, image_dir: str, output_dir: str, use_gpu: bool = True) -> dict:
        """异步运行 COLMAP SfM 流程"""
        return await run_sync(cls._run_sfm_sync, image_dir, output_dir, use_gpu)
