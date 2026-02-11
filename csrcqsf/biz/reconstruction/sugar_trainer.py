"""SuGaR 训练器 - 一步完成 3DGS 训练 + Mesh 提取

使用 SuGaR (Surface-Aligned Gaussian Splatting) 从 COLMAP 输出
直接生成高质量 OBJ 网格，替代 OpenSplat/GaussianTrainer + MeshExtractor 的两步流程。

SuGaR 运行在独立 conda 环境中，通过子进程调用。
"""

import glob
import os
import subprocess

from anyio.to_thread import run_sync

from csrcqsf.logger import CodeTimer, logger


class SuGaRTrainer:
    """SuGaR 训练器 - 从 COLMAP 直接到 OBJ
    
    流程: COLMAP 输出 → SuGaR (3DGS训练 + 表面对齐 + Mesh提取) → OBJ
    
    环境变量:
        SUGAR_REPO_PATH: SuGaR 仓库路径，默认 /opt/SuGaR
        SUGAR_CONDA_ENV: conda 环境名称，默认 sugar
    """
    
    SUGAR_REPO_PATH = os.environ.get('SUGAR_REPO_PATH', '/opt/SuGaR')
    SUGAR_PYTHON = os.environ.get('SUGAR_PYTHON', '/root/miniconda3/envs/sugar/bin/python')
    
    @classmethod
    def _check_installed(cls) -> tuple[bool, str]:
        """检查 SuGaR 是否已安装"""
        script = os.path.join(cls.SUGAR_REPO_PATH, 'train_full_pipeline.py')
        if not os.path.exists(script):
            return False, f'SuGaR 未找到: {script}'
        return True, ''
    
    @classmethod
    def _train_and_extract_sync(
        cls,
        colmap_dir: str,
        output_dir: str,
        iterations: int = 7000,
        regularization: str = 'density',
        high_poly: bool = False,
        refinement_time: str = 'short',
        gpu: int = 0,
    ) -> dict:
        """同步执行 SuGaR 全流程
        
        Args:
            colmap_dir: COLMAP 输出目录 (包含 images/ 和 sparse/)
            output_dir: 输出目录
            iterations: 3DGS 训练迭代次数，默认 7000
            regularization: 正则化方式 (density / sdf / dn_consistency)
            high_poly: True=100万顶点, False=20万顶点
            refinement_time: 细化时间 (short/medium/long)
            gpu: GPU 设备编号
            
        Returns:
            dict: 包含 success, message, obj_path 等
        """
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
        
        os.makedirs(output_dir, exist_ok=True)
        
        # 准备 SuGaR 需要的目录结构: scene_path/ 下必须有 images/ 和 sparse/0/
        scene_path = os.path.abspath(cls._prepare_scene_dir(colmap_dir))
        
        # 构建命令
        script = os.path.join(cls.SUGAR_REPO_PATH, 'train_full_pipeline.py')
        
        cmd = [
            cls.SUGAR_PYTHON, script,
            '-s', scene_path,
            '-r', regularization,
            '--export_obj', 'True',
            '--export_ply', 'True',
            '--refinement_time', refinement_time,
            '--gpu', str(gpu),
        ]
        
        # 添加 poly 参数
        if high_poly:
            cmd.extend(['--high_poly', 'True'])
        else:
            cmd.extend(['--low_poly', 'True'])
        
        logger.info(f"SuGaR 开始训练: {' '.join(cmd)}")
        
        # 构建环境变量: 把 sugar 的 bin 目录放到 PATH 最前面
        # 因为 train_full_pipeline.py 内部用 os.system("python ...") 调用子进程，
        # 裸 python 命令必须指向 sugar 环境的 python
        env = os.environ.copy()
        sugar_bin_dir = os.path.dirname(cls.SUGAR_PYTHON)  # /root/miniconda3/envs/sugar/bin
        env['PATH'] = sugar_bin_dir + os.pathsep + env.get('PATH', '')
        # 同时设置 CONDA 相关变量，确保子进程也在正确环境中
        env['CONDA_PREFIX'] = os.path.dirname(sugar_bin_dir)  # /root/miniconda3/envs/sugar
        
        with CodeTimer(name='SuGaR训练+提取'):
            try:
                process = subprocess.run(
                    cmd,
                    cwd=cls.SUGAR_REPO_PATH,  # 关键: 在 SuGaR 根目录运行
                    env=env,                   # 关键: 确保 python 指向 sugar 环境
                    capture_output=True,
                    text=True,
                    timeout=7200,  # 2小时超时
                )
                
                # 无论成功失败，都输出日志
                if process.stdout:
                    logger.info(f"SuGaR stdout:\n{process.stdout}")
                if process.stderr:
                    logger.info(f"SuGaR stderr:\n{process.stderr}")
                
                if process.returncode != 0:
                    error_msg = process.stderr or process.stdout or '未知错误'
                    result['message'] = f'训练失败 (code={process.returncode}):\n{error_msg}'
                    logger.error(f"SuGaR 失败 (code={process.returncode})")
                    return result
                    
            except subprocess.TimeoutExpired:
                result['message'] = '训练超时 (>2小时)'
                return result
            except Exception as e:
                result['message'] = str(e)
                return result
        
        # 查找输出文件
        # SuGaR 输出在 SUGAR_REPO_PATH/output/ 中
        sugar_output_base = os.path.join(cls.SUGAR_REPO_PATH, 'output')
        
        obj_path = cls._find_output_file(sugar_output_base, '*.obj')
        ply_path = cls._find_output_file(sugar_output_base, '*.ply')
        
        if not obj_path:
            result['message'] = f'训练完成但未找到 OBJ 文件: {sugar_output_base}'
            return result
        
        # 复制到目标目录
        import shutil
        target_obj = os.path.join(output_dir, 'output.obj')
        shutil.copy2(obj_path, target_obj)
        
        # 复制纹理文件 (如果有)
        obj_dir = os.path.dirname(obj_path)
        for tex_file in glob.glob(os.path.join(obj_dir, '*.png')):
            shutil.copy2(tex_file, output_dir)
        for mtl_file in glob.glob(os.path.join(obj_dir, '*.mtl')):
            shutil.copy2(mtl_file, output_dir)
        
        if ply_path:
            target_ply = os.path.join(output_dir, 'point_cloud.ply')
            shutil.copy2(ply_path, target_ply)
            result['ply_path'] = target_ply
        
        # 统计网格信息
        v_count, f_count = cls._count_obj_elements(target_obj)
        
        result['success'] = True
        result['message'] = 'SuGaR 训练+提取完成'
        result['obj_path'] = target_obj
        result['num_vertices'] = v_count
        result['num_faces'] = f_count
        
        logger.info(f"SuGaR 完成: {v_count} 顶点, {f_count} 面, OBJ: {target_obj}")
        
        return result
    
    @classmethod
    def _prepare_scene_dir(cls, colmap_dir: str) -> str:
        """准备 SuGaR 需要的场景目录结构
        
        SuGaR 期望 -s 指向的目录结构:
          scene_path/
          ├── images/              (原始图片)
          ├── sparse/0/            (原始 COLMAP，可选)
          └── undistorted/         (去畸变后的数据，优先使用)
              ├── images/
              ├── sparse/0/
              └── point_cloud.ply
          
        我们的 COLMAP 输出结构:
          colmap_dir/
          ├── images/
          ├── colmap/
          │   ├── sparse/0/
          │   └── undistorted/
        """
        # 情况1: 如果有 colmap/undistorted/，返回 colmap/ 并确保有 images 链接
        colmap_subdir = os.path.join(colmap_dir, 'colmap')
        undistorted_dir = os.path.join(colmap_subdir, 'undistorted')
        
        if os.path.exists(undistorted_dir):
            undist_images = os.path.join(undistorted_dir, 'images')
            undist_sparse = os.path.join(undistorted_dir, 'sparse')
            undist_ply = os.path.join(undistorted_dir, 'point_cloud.ply')
            
            if os.path.exists(undist_images) and os.path.exists(undist_sparse):
                # 确保 colmap/ 下有 images/ 符号链接指向原始图片
                colmap_images_link = os.path.join(colmap_subdir, 'images')
                original_images = os.path.join(colmap_dir, 'images')
                
                if not os.path.exists(colmap_images_link) and os.path.exists(original_images):
                    try:
                        os.symlink(original_images, colmap_images_link, target_is_directory=True)
                        logger.info(f"创建 images 符号链接: {colmap_images_link} -> {original_images}")
                    except OSError as e:
                        logger.warning(f"创建符号链接失败: {e}")
                
                logger.info(f"使用 colmap/ 目录 (包含 undistorted 子目录): {colmap_subdir}")
                return colmap_subdir
        
        # 情况2: 已有正确结构 (images/ + sparse/ 在同一层)
        images_dir = os.path.join(colmap_dir, 'images')
        sparse_dir = os.path.join(colmap_dir, 'sparse')
        if os.path.exists(images_dir) and os.path.exists(sparse_dir):
            logger.info(f"场景目录结构正确: {colmap_dir}")
            return colmap_dir
        
        # 情况3: 找不到，返回原目录让 SuGaR 报告具体错误
        logger.warning(f"无法确认场景目录结构，尝试使用: {colmap_dir}")
        return colmap_dir
    
    @classmethod
    def _find_output_file(cls, base_dir: str, pattern: str) -> str:
        """在输出目录中查找最新的匹配文件"""
        matches = glob.glob(os.path.join(base_dir, '**', pattern), recursive=True)
        if not matches:
            return ''
        # 返回最新修改的文件
        return max(matches, key=os.path.getmtime)
    
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
        except Exception:
            pass
        return v_count, f_count
    
    @classmethod
    async def train_and_extract(
        cls,
        colmap_dir: str,
        output_dir: str,
        iterations: int = 7000,
        regularization: str = 'density',
        high_poly: bool = False,
        refinement_time: str = 'short',
        gpu: int = 0,
    ) -> dict:
        """异步执行 SuGaR 全流程"""
        return await run_sync(
            cls._train_and_extract_sync,
            colmap_dir, output_dir, iterations,
            regularization, high_poly, refinement_time, gpu
        )
