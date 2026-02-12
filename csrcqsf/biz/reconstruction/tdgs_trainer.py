"""2DGS 训练器 - 2D Gaussian Splatting 训练 + Mesh 提取

使用 2D Gaussian Splatting (hbb1/2d-gaussian-splatting) 进行训练和 TSDF mesh 提取。
比 SuGaR 更快 (~50%)，mesh 质量更好。

2DGS 运行在独立 conda 环境中，通过子进程调用。

流程:
  1. train.py -s scene -m model  (2DGS 训练)
  2. render.py -m model --skip_train --skip_test  (渲染 + TSDF mesh 提取)
  3. PLY mesh → OBJ 转换
"""

import os
import shutil
import subprocess

from anyio.to_thread import run_sync

from csrcqsf.logger import CodeTimer, logger


class TDGSTrainer:
    """2D Gaussian Splatting 训练器
    
    环境变量:
        TDGS_REPO_PATH: 2DGS 仓库路径，默认 /opt/2d-gaussian-splatting
        TDGS_PYTHON: conda 环境 python 路径，默认 /root/miniconda3/envs/2dgs/bin/python
    """
    
    TDGS_REPO_PATH = os.environ.get('TDGS_REPO_PATH', '/opt/2d-gaussian-splatting')
    TDGS_PYTHON = os.environ.get('TDGS_PYTHON', '/root/miniconda3/envs/surfel_splatting/bin/python')
    
    @classmethod
    def _check_installed(cls) -> tuple[bool, str]:
        """检查 2DGS 是否已安装"""
        train_script = os.path.join(cls.TDGS_REPO_PATH, 'train.py')
        render_script = os.path.join(cls.TDGS_REPO_PATH, 'render.py')
        if not os.path.exists(train_script):
            return False, f'2DGS 未找到: {train_script}'
        if not os.path.exists(render_script):
            return False, f'2DGS render.py 未找到: {render_script}'
        return True, ''
    
    @classmethod
    async def train_and_extract(
        cls,
        colmap_dir: str,
        output_dir: str,
        iterations: int = 7000,
        gpu: int = 0,
        white_background: bool = False,
    ) -> dict:
        """异步执行 2DGS 训练 + Mesh 提取"""
        return await run_sync(
            cls._train_and_extract_sync,
            colmap_dir, output_dir, iterations, gpu, white_background
        )
    
    @classmethod
    def _train_and_extract_sync(
        cls,
        colmap_dir: str,
        output_dir: str,
        iterations: int = 7000,
        gpu: int = 0,
        white_background: bool = False,
    ) -> dict:
        """同步执行 2DGS 训练 + Mesh 提取"""
        result = {
            'success': False,
            'message': '',
            'obj_path': '',
            'ply_path': '',
            'num_vertices': 0,
            'num_faces': 0,
        }
        
        # 检查安装
        installed, msg = cls._check_installed()
        if not installed:
            result['message'] = msg
            return result
        
        # 准备场景目录
        scene_path = cls._prepare_scene_dir(colmap_dir)
        scene_path = os.path.abspath(scene_path)
        
        # 模型输出目录 (2DGS 会在这里保存训练结果)
        model_path = os.path.join(os.path.abspath(output_dir), '2dgs_model')
        os.makedirs(model_path, exist_ok=True)
        
        # 构建环境变量
        env = os.environ.copy()
        tdgs_bin_dir = os.path.dirname(cls.TDGS_PYTHON)
        env['PATH'] = tdgs_bin_dir + os.pathsep + env.get('PATH', '')
        env['CONDA_PREFIX'] = os.path.dirname(tdgs_bin_dir)
        env['CUDA_VISIBLE_DEVICES'] = str(gpu)
        
        # ---- Step 1: 2DGS 训练 ----
        train_cmd = [
            cls.TDGS_PYTHON, 'train.py',
            '-s', scene_path,
            '-m', model_path,
            '--iterations', str(iterations),
        ]
        if white_background:
            train_cmd.append('-w')
        
        logger.info(f"2DGS 训练命令: {' '.join(train_cmd)}")
        
        with CodeTimer(name='2DGS训练'):
            try:
                process = subprocess.run(
                    train_cmd,
                    cwd=cls.TDGS_REPO_PATH,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=14400,  # 4小时超时
                )
                
                if process.stdout:
                    logger.info(f"2DGS train stdout:\n{process.stdout[-2000:]}")
                if process.stderr:
                    logger.info(f"2DGS train stderr:\n{process.stderr[-2000:]}")
                
                if process.returncode != 0:
                    error_msg = process.stderr or process.stdout or '未知错误'
                    result['message'] = f'2DGS 训练失败 (code={process.returncode}):\n{error_msg[-500:]}'
                    return result
                    
            except subprocess.TimeoutExpired:
                result['message'] = '2DGS 训练超时'
                return result
            except Exception as e:
                result['message'] = f'2DGS 训练异常: {e}'
                return result
        
        # ---- Step 2: 渲染 + Mesh 提取 ----
        render_cmd = [
            cls.TDGS_PYTHON, 'render.py',
            '-m', model_path,
            '--skip_train',
            '--skip_test',
            '--num_cluster', '50',
        ]
        
        logger.info(f"2DGS Mesh 提取命令: {' '.join(render_cmd)}")
        
        with CodeTimer(name='2DGS_Mesh提取'):
            try:
                process = subprocess.run(
                    render_cmd,
                    cwd=cls.TDGS_REPO_PATH,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=3600,  # 1小时超时
                )
                
                if process.stdout:
                    logger.info(f"2DGS render stdout:\n{process.stdout[-2000:]}")
                if process.stderr:
                    logger.info(f"2DGS render stderr:\n{process.stderr[-2000:]}")
                
                if process.returncode != 0:
                    error_msg = process.stderr or process.stdout or '未知错误'
                    result['message'] = f'2DGS Mesh提取失败 (code={process.returncode}):\n{error_msg[-500:]}'
                    return result
                    
            except subprocess.TimeoutExpired:
                result['message'] = '2DGS Mesh提取超时'
                return result
            except Exception as e:
                result['message'] = f'2DGS Mesh提取异常: {e}'
                return result
        
        # ---- Step 3: 查找 mesh 文件并转换 ----
        # 2DGS 输出在 model_path/train/ours_<iteration>/fuse_post.ply
        mesh_ply = cls._find_output_file(model_path, 'fuse_post.ply')
        if not mesh_ply:
            mesh_ply = cls._find_output_file(model_path, 'fuse.ply')
        
        if not mesh_ply:
            result['message'] = f'未找到 mesh 文件: {model_path}'
            return result
        
        logger.info(f"找到 2DGS mesh: {mesh_ply}")
        
        # PLY → OBJ 转换
        target_obj = os.path.join(output_dir, 'output.obj')
        v_count, f_count = cls._convert_ply_to_obj(mesh_ply, target_obj)
        
        if v_count == 0:
            result['message'] = 'PLY → OBJ 转换失败'
            return result
        
        # 复制原始 PLY
        target_ply = os.path.join(output_dir, 'mesh.ply')
        shutil.copy2(mesh_ply, target_ply)
        
        result['success'] = True
        result['message'] = '2DGS 训练+提取完成'
        result['obj_path'] = target_obj
        result['ply_path'] = target_ply
        result['num_vertices'] = v_count
        result['num_faces'] = f_count
        
        logger.info(f"2DGS 完成: {v_count} 顶点, {f_count} 面, OBJ: {target_obj}")
        
        return result
    
    @classmethod
    def _prepare_scene_dir(cls, colmap_dir: str) -> str:
        """准备标准 COLMAP 场景目录 (复用 SuGaR 的逻辑)
        
        2DGS 要求 scene_path 包含:
          scene_path/
          ├── images/
          └── sparse/0/
        """
        scene_dir = os.path.join(colmap_dir, '2dgs_scene')
        
        if os.path.exists(scene_dir):
            shutil.rmtree(scene_dir)
        os.makedirs(scene_dir, exist_ok=True)
        
        # 查找 images
        images_src = os.path.join(colmap_dir, 'images')
        if not os.path.exists(images_src):
            logger.error(f"找不到 images 目录: {images_src}")
            return colmap_dir
        
        # 查找 sparse (优先 undistorted, 其次 colmap/sparse/0)
        sparse_src = None
        for candidate in [
            os.path.join(colmap_dir, 'colmap', 'undistorted', 'sparse', '0'),
            os.path.join(colmap_dir, 'colmap', 'undistorted', 'sparse'),
            os.path.join(colmap_dir, 'colmap', 'sparse', '0'),
        ]:
            if os.path.exists(candidate):
                sparse_src = candidate
                if 'undistorted' in candidate:
                    undist_images = os.path.join(colmap_dir, 'colmap', 'undistorted', 'images')
                    if os.path.exists(undist_images):
                        images_src = undist_images
                break
        
        if not sparse_src:
            logger.error("找不到任何 sparse 数据")
            return colmap_dir
        
        # 创建符号链接: images
        os.symlink(os.path.abspath(images_src), os.path.join(scene_dir, 'images'))
        
        # 复制 sparse 到 sparse/0/
        scene_sparse_0 = os.path.join(scene_dir, 'sparse', '0')
        os.makedirs(scene_sparse_0, exist_ok=True)
        for f in os.listdir(sparse_src):
            src_file = os.path.join(sparse_src, f)
            if os.path.isfile(src_file):
                shutil.copy2(src_file, os.path.join(scene_sparse_0, f))
        
        logger.info(f"2DGS 场景目录: {scene_dir}")
        logger.info(f"  images -> {images_src}")
        logger.info(f"  sparse <- {sparse_src}")
        
        return scene_dir
    
    @classmethod
    def _find_output_file(cls, base_dir: str, filename: str) -> str:
        """递归查找输出文件"""
        for root, dirs, files in os.walk(base_dir):
            if filename in files:
                return os.path.join(root, filename)
        return ''
    
    @classmethod
    def _convert_ply_to_obj(cls, ply_path: str, obj_path: str) -> tuple[int, int]:
        """PLY mesh → OBJ 转换 (使用 open3d 或纯 Python)"""
        try:
            import open3d as o3d
            mesh = o3d.io.read_triangle_mesh(ply_path)
            if mesh.is_empty():
                logger.error(f"PLY mesh 为空: {ply_path}")
                return 0, 0
            
            # 计算顶点法线 (如果没有)
            if not mesh.has_vertex_normals():
                mesh.compute_vertex_normals()
            
            # 保存为 OBJ
            o3d.io.write_triangle_mesh(obj_path, mesh)
            
            v_count = len(mesh.vertices)
            f_count = len(mesh.triangles)
            logger.info(f"PLY→OBJ 转换成功: {v_count} 顶点, {f_count} 面")
            return v_count, f_count
            
        except ImportError:
            logger.warning("open3d 未安装，尝试使用 trimesh")
            try:
                import trimesh
                mesh = trimesh.load(ply_path)
                mesh.export(obj_path)
                return len(mesh.vertices), len(mesh.faces)
            except ImportError:
                logger.error("open3d 和 trimesh 都未安装，无法转换 PLY→OBJ")
                return 0, 0
        except Exception as e:
            logger.error(f"PLY→OBJ 转换失败: {e}")
            return 0, 0
