"""2DGS 训练器 - 2D Gaussian Splatting 训练 + Mesh 提取

使用 2D Gaussian Splatting (hbb1/2d-gaussian-splatting) 进行训练和 TSDF mesh 提取。
比 SuGaR 更快 (~50%)，mesh 质量更好。

2DGS 代码已集成在 gaussians/ 子目录中，使用项目自身的 Python 环境运行。

流程:
  1. train.py -s scene -m model  (2DGS 训练)
  2. render.py -m model --skip_train --skip_test  (渲染 + TSDF mesh 提取)
  3. PLY mesh → OBJ / GLB 转换
"""

import os
import shutil
import subprocess
import sys
import threading

from anyio.to_thread import run_sync

from csrcqsf.logger import CodeTimer, logger


class TDGSTrainer:
    """2D Gaussian Splatting 训练器 (集成模式)
    
    2DGS 代码位于 csrcqsf/biz/reconstruction/gaussians/ 目录中，
    使用项目自身的 Python 环境运行（无需独立 conda 环境）。
    """
    
    # 2DGS 代码目录 (集成在项目中)
    GAUSSIANS_DIR = os.path.join(os.path.dirname(__file__), 'gaussians')
    
    # 当前 Python 解释器
    PYTHON = sys.executable
    
    @classmethod
    def _check_installed(cls) -> tuple[bool, str]:
        """检查 2DGS 是否已安装"""
        train_script = os.path.join(cls.GAUSSIANS_DIR, 'train.py')
        render_script = os.path.join(cls.GAUSSIANS_DIR, 'render.py')
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
        iterations: int = 30000,
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
        env['CUDA_VISIBLE_DEVICES'] = str(gpu)
        
        # ---- Step 1: 2DGS 训练 ----
        train_cmd = [
            cls.PYTHON, 'train.py',
            '-s', scene_path,
            '-m', model_path,
            '--iterations', str(iterations),
            '--depth_ratio', '1.0', # 深度正则化，减少伪影
        ]
        if white_background:
            train_cmd.append('-w')
        
        logger.info(f"2DGS 训练命令: {' '.join(train_cmd)}")
        
        with CodeTimer(name='2DGS训练'):
            returncode, error_output = cls._run_with_streaming(
                train_cmd, cwd=cls.GAUSSIANS_DIR, env=env,
                label='2DGS train', timeout=14400,
            )
            if returncode is None:
                result['message'] = '2DGS 训练超时'
                return result
            if returncode == -1:
                result['message'] = f'2DGS 训练异常: {error_output}'
                return result
            if returncode != 0:
                result['message'] = f'2DGS 训练失败 (code={returncode}):\n{error_output[-500:]}'
                return result
        
        # ---- Step 2: 渲染 + Mesh 提取 ----
        render_cmd = [
            cls.PYTHON, 'render.py',
            '-m', model_path,
            '--skip_train',
            '--skip_test',
            '--num_cluster', '50',
        ]
        
        logger.info(f"2DGS Mesh 提取命令: {' '.join(render_cmd)}")
        
        with CodeTimer(name='2DGS_Mesh提取'):
            returncode, error_output = cls._run_with_streaming(
                render_cmd, cwd=cls.GAUSSIANS_DIR, env=env,
                label='2DGS render', timeout=3600,
            )
            if returncode is None:
                result['message'] = '2DGS Mesh提取超时'
                return result
            if returncode == -1:
                result['message'] = f'2DGS Mesh提取异常: {error_output}'
                return result
            if returncode != 0:
                result['message'] = f'2DGS Mesh提取失败 (code={returncode}):\n{error_output[-500:]}'
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
        
        # 复制原始 PLY (保留完整质量)
        target_ply = os.path.join(output_dir, 'mesh.ply')
        shutil.copy2(mesh_ply, target_ply)
        
        # ---- Step 3.5: Mesh 清理 (去除碎片, 仅用于 OBJ 预览) ----
        cleaned_ply = cls._clean_mesh(mesh_ply)
        
        # ---- Step 4: PLY → OBJ 转换 (基于清理后的 mesh) ----
        target_obj = os.path.join(output_dir, 'output.obj')
        v_count, f_count = cls._convert_ply_to_obj(cleaned_ply, target_obj)
        
        # ---- Step 5: PLY → GLB 转换 (Web 优化) ----
        target_glb = os.path.join(output_dir, 'output.glb')
        cls._convert_ply_to_glb(cleaned_ply, target_glb)
        
        result['success'] = True
        result['message'] = '2DGS 训练+提取完成'
        result['obj_path'] = target_obj
        result['glb_path'] = target_glb
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
    def _run_with_streaming(
        cls,
        cmd: list[str],
        cwd: str,
        env: dict,
        label: str,
        timeout: int,
    ) -> tuple[int | None, str]:
        """运行子进程并实时输出日志
        
        Returns:
            (returncode, error_output)
            returncode=None 表示超时, returncode=-1 表示异常
        """
        stderr_lines: list[str] = []
        
        def _read_stream(stream, level: str):
            """在后台线程中逐行读取流并输出"""
            for line in iter(stream.readline, ''):
                line = line.rstrip()
                if not line:
                    continue
                if level == 'stderr':
                    stderr_lines.append(line)
                    logger.info(f"[{label}] {line}")
                else:
                    logger.info(f"[{label}] {line}")
            stream.close()
        
        try:
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # 行缓冲
            )
            
            # 启动后台线程分别读取 stdout 和 stderr
            stdout_thread = threading.Thread(
                target=_read_stream, args=(process.stdout, 'stdout'), daemon=True
            )
            stderr_thread = threading.Thread(
                target=_read_stream, args=(process.stderr, 'stderr'), daemon=True
            )
            stdout_thread.start()
            stderr_thread.start()
            
            # 等待进程完成
            process.wait(timeout=timeout)
            
            # 等待读取线程完成
            stdout_thread.join(timeout=10)
            stderr_thread.join(timeout=10)
            
            error_output = '\n'.join(stderr_lines[-20:]) if stderr_lines else ''
            return process.returncode, error_output
            
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            return None, ''
        except Exception as e:
            return -1, str(e)
    
    @classmethod
    def _find_output_file(cls, base_dir: str, filename: str) -> str:
        """递归查找输出文件"""
        for root, dirs, files in os.walk(base_dir):
            if filename in files:
                return os.path.join(root, filename)
        return ''
    
    # Mesh 清理: 保留面数 >= 最大组件 * MESH_KEEP_RATIO 的连通分量
    MESH_KEEP_RATIO = 0.05
    
    @classmethod
    def _clean_mesh(cls, ply_path: str) -> str:
        """清理 mesh 碎片，只保留主体部分
        
        返回清理后的 PLY 路径 (在原文件旁生成 _cleaned.ply)
        """
        try:
            import numpy as np
            import open3d as o3d
        except ImportError:
            logger.warning("open3d/numpy 未安装，跳过 mesh 清理")
            return ply_path
        
        mesh = o3d.io.read_triangle_mesh(ply_path)
        if mesh.is_empty():
            return ply_path
        
        raw_f = len(mesh.triangles)
        logger.info(f"Mesh 清理: 原始 {len(mesh.vertices):,} 顶点, {raw_f:,} 面")
        
        # 连通分量分析
        triangle_clusters, cluster_n_triangles, _ = mesh.cluster_connected_triangles()
        triangle_clusters = np.asarray(triangle_clusters)
        cluster_n_triangles = np.asarray(cluster_n_triangles)
        
        n_clusters = len(cluster_n_triangles)
        max_tri = cluster_n_triangles.max()
        threshold = int(max_tri * cls.MESH_KEEP_RATIO)
        
        logger.info(
            f"连通分量: {n_clusters:,} 个, 最大组件 {max_tri:,} 面, "
            f"保留阈值 {threshold:,} 面 ({cls.MESH_KEEP_RATIO*100:.0f}%)"
        )
        
        # 去除小碎片
        keep_mask = cluster_n_triangles[triangle_clusters] >= threshold
        triangles_to_remove = ~keep_mask
        mesh.remove_triangles_by_mask(triangles_to_remove)
        mesh.remove_unreferenced_vertices()
        
        clean_f = len(mesh.triangles)
        removed = raw_f - clean_f
        logger.info(
            f"清理后: {len(mesh.vertices):,} 顶点, {clean_f:,} 面 "
            f"(移除 {removed:,} 面, {removed/raw_f*100:.1f}%)"
        )
        
        # 重新计算法线
        mesh.compute_vertex_normals()
        
        # 居中显示
        center = mesh.get_axis_aligned_bounding_box().get_center()
        mesh.translate(-center)
        logger.info(f"Mesh 已居中: 平移 {-center}")
        
        # 保存清理后的 PLY
        clean_path = ply_path.replace('.ply', '_cleaned.ply')
        o3d.io.write_triangle_mesh(clean_path, mesh)
        logger.info(f"清理后 mesh 保存: {clean_path}")
        
        return clean_path
    
    # OBJ 文件大小上限 (字节), 默认 500MB
    OBJ_MAX_SIZE_MB = 500
    
    @classmethod
    def _convert_ply_to_glb(cls, ply_path: str, glb_path: str) -> None:
        """PLY mesh → GLB 转换 (Web 优化)"""
        try:
            import open3d as o3d
            mesh = o3d.io.read_triangle_mesh(ply_path)
            if mesh.is_empty():
                logger.error(f"PLY mesh 为空: {ply_path}")
                return
                
            # 计算顶点法线
            if not mesh.has_vertex_normals():
                mesh.compute_vertex_normals()
                
            # GLB 导出 (自动保留顶点颜色)
            o3d.io.write_triangle_mesh(glb_path, mesh)
            
            size_mb = os.path.getsize(glb_path) / 1024 / 1024
            logger.info(f"PLY→GLB 转换成功: {glb_path} ({size_mb:.1f} MB)")
            
        except Exception as e:
            logger.error(f"PLY→GLB 转换失败: {e}")

    @classmethod
    def _convert_ply_to_obj(cls, ply_path: str, obj_path: str) -> tuple[int, int]:
        """PLY mesh → OBJ 转换，自动简化以控制文件大小在 OBJ_MAX_SIZE_MB 以内"""
        try:
            import open3d as o3d
            mesh = o3d.io.read_triangle_mesh(ply_path)
            if mesh.is_empty():
                logger.error(f"PLY mesh 为空: {ply_path}")
                return 0, 0
            
            raw_v = len(mesh.vertices)
            raw_f = len(mesh.triangles)
            logger.info(f"原始 mesh: {raw_v} 顶点, {raw_f} 面")
            
            # OBJ 每面约 102 字节 (v行 ~36B*3 + f行 ~30B ≈ 102B/面，偏保守估算)
            bytes_per_face = 102
            max_faces = (cls.OBJ_MAX_SIZE_MB * 1024 * 1024) // bytes_per_face
            
            if raw_f > max_faces:
                logger.info(
                    f"mesh 面数 {raw_f} 超过上限 {max_faces} "
                    f"(OBJ ≈{raw_f * bytes_per_face / 1024 / 1024:.0f}MB, "
                    f"限制 {cls.OBJ_MAX_SIZE_MB}MB), 执行简化..."
                )
                mesh = mesh.simplify_quadric_decimation(
                    target_number_of_triangles=int(max_faces)
                )
                logger.info(
                    f"简化后: {len(mesh.vertices)} 顶点, "
                    f"{len(mesh.triangles)} 面"
                )
            
            # 计算顶点法线 (如果没有)
            if not mesh.has_vertex_normals():
                mesh.compute_vertex_normals()
            
            # 清除顶点颜色 (Open3D 会将颜色写入 v 行, 不兼容标准 OBJ)
            mesh.vertex_colors = o3d.utility.Vector3dVector()
            
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
