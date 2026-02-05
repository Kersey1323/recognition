"""3D Gaussian Splatting 训练器

从 COLMAP 输出训练 3D Gaussian Splatting 模型。
"""

import os
import subprocess

from anyio.to_thread import run_sync

from csrcqsf.logger import CodeTimer, logger


class GaussianTrainer:
    """3D Gaussian Splatting 训练器
    
    使用官方 gaussian-splatting 仓库进行训练
    """
    
    # 3DGS 仓库路径 (需要预先克隆)
    GS_REPO_PATH = os.environ.get('GS_REPO_PATH', '/opt/gaussian-splatting')
    # Conda 环境名称
    GS_CONDA_ENV = 'gaussian_splatting'
    
    @classmethod
    def _check_gs_installed(cls) -> tuple[bool, str]:
        """检查 3DGS 是否已安装"""
        train_script = os.path.join(cls.GS_REPO_PATH, 'train.py')
        if not os.path.exists(train_script):
            return False, f'3DGS 仓库未找到: {cls.GS_REPO_PATH}'
        return True, ''
    
    @classmethod
    def _train_sync(
        cls, 
        colmap_dir: str, 
        output_dir: str,
        iterations: int = 7000,
        save_iterations: list[int] = None
    ) -> dict:
        """同步训练 3DGS 模型
        
        Args:
            colmap_dir: COLMAP 输出目录 (包含 sparse/0)
            output_dir: 模型输出目录
            iterations: 训练迭代次数
            save_iterations: 保存检查点的迭代次数
            
        Returns:
            dict: 训练结果
        """
        result = {
            'success': False,
            'message': '',
            'model_path': '',
            'iterations': iterations
        }
        
        # 检查安装
        installed, msg = cls._check_gs_installed()
        if not installed:
            result['message'] = msg
            return result
        
        if save_iterations is None:
            save_iterations = [iterations]
        
        # 构建训练命令
        train_script = os.path.join(cls.GS_REPO_PATH, 'train.py')
        
        cmd = [
            'conda', 'run', '-n', cls.GS_CONDA_ENV, '--no-capture-output',
            'python', train_script,
            '-s', colmap_dir,  # 源数据目录 (COLMAP 输出)
            '-m', output_dir,  # 模型输出目录
            '--iterations', str(iterations),
            '--save_iterations', ' '.join(map(str, save_iterations)),
        ]
        
        with CodeTimer(name=f'3DGS训练 ({iterations} iterations)'):
            try:
                logger.info(f"开始 3DGS 训练: {' '.join(cmd)}")
                
                process = subprocess.run(
                    cmd,
                    cwd=cls.GS_REPO_PATH,
                    capture_output=True,
                    text=True,
                    timeout=7200  # 2小时超时
                )
                
                if process.returncode != 0:
                    result['message'] = f'训练失败: {process.stderr[-500:]}'
                    return result
                    
            except subprocess.TimeoutExpired:
                result['message'] = '训练超时 (超过2小时)'
                return result
            except Exception as e:
                result['message'] = f'训练异常: {str(e)}'
                return result
        
        # 检查输出
        model_path = os.path.join(output_dir, 'point_cloud', f'iteration_{iterations}', 'point_cloud.ply')
        if not os.path.exists(model_path):
            result['message'] = f'训练完成但未找到模型文件: {model_path}'
            return result
        
        result['success'] = True
        result['message'] = f'3DGS 训练完成 ({iterations} iterations)'
        result['model_path'] = model_path
        
        logger.info(f"3DGS 训练完成: {model_path}")
        
        return result
    
    @classmethod
    async def train(
        cls, 
        colmap_dir: str, 
        output_dir: str,
        iterations: int = 7000
    ) -> dict:
        """异步训练 3DGS 模型"""
        return await run_sync(cls._train_sync, colmap_dir, output_dir, iterations)
    
    @classmethod
    def get_model_path(cls, output_dir: str, iteration: int = None) -> str:
        """获取训练好的模型路径"""
        if iteration is None:
            # 查找最新的 iteration
            pc_dir = os.path.join(output_dir, 'point_cloud')
            if os.path.exists(pc_dir):
                iterations = [int(d.split('_')[1]) for d in os.listdir(pc_dir) if d.startswith('iteration_')]
                if iterations:
                    iteration = max(iterations)
        
        if iteration:
            return os.path.join(output_dir, 'point_cloud', f'iteration_{iteration}', 'point_cloud.ply')
        return ''
