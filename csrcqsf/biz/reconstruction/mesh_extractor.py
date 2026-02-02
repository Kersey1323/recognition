"""SuGaR Mesh 提取器 - 从 3DGS 模型提取 OBJ 网格

使用 SuGaR (Surface-Aligned Gaussian Splatting and Reconstruction) 方法，
从训练好的 3D Gaussian Splatting 模型中提取高质量的三角网格。
"""

import os
import sys
import subprocess
from pathlib import Path
from anyio.to_thread import run_sync

from csrcqsf.logger import logger, CodeTimer


class MeshExtractor:
    """SuGaR Mesh 提取器
    
    将 3D Gaussian Splatting 模型转换为 OBJ 网格
    """
    
    # SuGaR 仓库路径 (需要预先克隆)
    SUGAR_REPO_PATH = os.environ.get('SUGAR_REPO_PATH', '/opt/SuGaR')
    
    @classmethod
    def _check_sugar_installed(cls) -> tuple[bool, str]:
        """检查 SuGaR 是否已安装"""
        extract_script = os.path.join(cls.SUGAR_REPO_PATH, 'extract_mesh.py')
        if not os.path.exists(extract_script):
            # 尝试使用 pip 安装的 sugar
            try:
                import sugar_scene
                return True, 'pip'
            except ImportError:
                return False, f'SuGaR 未找到: {cls.SUGAR_REPO_PATH}'
        return True, 'repo'
    
    @classmethod
    def _extract_mesh_sync(
        cls,
        gaussian_model_dir: str,
        colmap_dir: str,
        output_path: str,
        mesh_resolution: int = 7,
        decimate_ratio: float = 0.5
    ) -> dict:
        """同步提取 Mesh
        
        Args:
            gaussian_model_dir: 3DGS 模型目录
            colmap_dir: COLMAP 输出目录
            output_path: OBJ 输出路径
            mesh_resolution: 网格分辨率级别 (1-10)
            decimate_ratio: 网格简化比例
            
        Returns:
            dict: 提取结果
        """
        result = {
            'success': False,
            'message': '',
            'obj_path': '',
            'num_vertices': 0,
            'num_faces': 0
        }
        
        # 检查安装
        installed, install_type = cls._check_sugar_installed()
        if not installed:
            result['message'] = install_type
            return result
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with CodeTimer(name='SuGaR Mesh提取'):
            if install_type == 'repo':
                # 使用仓库脚本
                success, msg = cls._extract_via_repo(
                    gaussian_model_dir, colmap_dir, output_path, mesh_resolution
                )
            else:
                # 使用 pip 包
                success, msg = cls._extract_via_pip(
                    gaussian_model_dir, colmap_dir, output_path, mesh_resolution
                )
            
            if not success:
                result['message'] = msg
                return result
        
        # 验证输出
        if not os.path.exists(output_path):
            result['message'] = f'Mesh 提取完成但文件不存在: {output_path}'
            return result
        
        # 统计网格信息
        v_count, f_count = cls._count_obj_elements(output_path)
        
        result['success'] = True
        result['message'] = 'Mesh 提取成功'
        result['obj_path'] = output_path
        result['num_vertices'] = v_count
        result['num_faces'] = f_count
        
        logger.info(f"Mesh 提取完成: {v_count} 顶点, {f_count} 面")
        
        return result
    
    @classmethod
    def _extract_via_repo(
        cls,
        gaussian_model_dir: str,
        colmap_dir: str,
        output_path: str,
        mesh_resolution: int
    ) -> tuple[bool, str]:
        """通过 SuGaR 仓库脚本提取"""
        extract_script = os.path.join(cls.SUGAR_REPO_PATH, 'extract_mesh.py')
        
        cmd = [
            sys.executable, extract_script,
            '-s', colmap_dir,
            '-c', gaussian_model_dir,
            '-o', os.path.dirname(output_path),
            '--mesh_output_name', os.path.basename(output_path),
            '--mesh_resolution', str(mesh_resolution),
        ]
        
        try:
            process = subprocess.run(
                cmd,
                cwd=cls.SUGAR_REPO_PATH,
                capture_output=True,
                text=True,
                timeout=3600
            )
            
            if process.returncode != 0:
                return False, f'提取失败: {process.stderr[-500:]}'
            
            return True, ''
            
        except subprocess.TimeoutExpired:
            return False, '提取超时'
        except Exception as e:
            return False, str(e)
    
    @classmethod
    def _extract_via_pip(
        cls,
        gaussian_model_dir: str,
        colmap_dir: str,
        output_path: str,
        mesh_resolution: int
    ) -> tuple[bool, str]:
        """通过 pip 包提取 (如果可用)"""
        try:
            # 尝试使用 Open3D 的 Poisson 重建作为备选方案
            import open3d as o3d
            import numpy as np
            
            # 读取 3DGS 点云
            gs_ply_path = cls._find_point_cloud(gaussian_model_dir)
            if not gs_ply_path:
                return False, '未找到 3DGS 点云文件'
            
            # 加载点云
            pcd = o3d.io.read_point_cloud(gs_ply_path)
            
            # 估计法线
            pcd.estimate_normals(
                search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=0.1, max_nn=30)
            )
            pcd.orient_normals_consistent_tangent_plane(30)
            
            # Poisson 重建
            mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
                pcd, depth=mesh_resolution + 2
            )
            
            # 移除低密度顶点
            densities = np.asarray(densities)
            density_threshold = np.quantile(densities, 0.1)
            vertices_to_remove = densities < density_threshold
            mesh.remove_vertices_by_mask(vertices_to_remove)
            
            # 保存 OBJ
            o3d.io.write_triangle_mesh(output_path, mesh)
            
            return True, ''
            
        except ImportError:
            return False, 'open3d 未安装，无法使用备选方案'
        except Exception as e:
            return False, str(e)
    
    @classmethod
    def _find_point_cloud(cls, model_dir: str) -> str:
        """查找模型目录中的点云文件"""
        # 查找 point_cloud 目录下的 ply 文件
        for root, dirs, files in os.walk(model_dir):
            for f in files:
                if f.endswith('.ply'):
                    return os.path.join(root, f)
        return ''
    
    @classmethod
    def _count_obj_elements(cls, obj_path: str) -> tuple[int, int]:
        """统计 OBJ 文件的顶点和面数"""
        v_count = 0
        f_count = 0
        try:
            with open(obj_path, 'r') as f:
                for line in f:
                    if line.startswith('v '):
                        v_count += 1
                    elif line.startswith('f '):
                        f_count += 1
        except:
            pass
        return v_count, f_count
    
    @classmethod
    async def extract_mesh(
        cls,
        gaussian_model_dir: str,
        colmap_dir: str,
        output_path: str,
        mesh_resolution: int = 7
    ) -> dict:
        """异步提取 Mesh"""
        return await run_sync(
            cls._extract_mesh_sync, 
            gaussian_model_dir, colmap_dir, output_path, mesh_resolution
        )
