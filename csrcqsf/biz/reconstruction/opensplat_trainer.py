"""OpenSplat 3D Gaussian Splatting 训练器

使用 OpenSplat (C++ 实现) 进行 3D Gaussian Splatting 训练。
OpenSplat 是一个轻量级、高性能的开源实现，支持 CPU/GPU。

Github: https://github.com/pierotofy/OpenSplat
"""

import os
import subprocess

from anyio.to_thread import run_sync

from globals_vars import logger
from csrcqsf.logger import CodeTimer


class OpenSplatTrainer:
    """OpenSplat 3D Gaussian Splatting 训练器

    使用预编译的 OpenSplat 二进制文件进行训练，
    比原版 Python 实现更快、更轻量。
    """

    # OpenSplat 可执行文件路径
    OPENSPLAT_BIN = os.path.join('/usr/local/bin', 'opensplat')

    @classmethod
    def _check_installed(cls) -> tuple[bool, str]:
        """检查 OpenSplat 是否已安装"""
        if not os.path.exists(cls.OPENSPLAT_BIN):
            return False, f'OpenSplat 未找到: {cls.OPENSPLAT_BIN}'
        if not os.access(cls.OPENSPLAT_BIN, os.X_OK):
            return False, f'OpenSplat 不可执行: {cls.OPENSPLAT_BIN}'
        return True, ''

    @classmethod
    def _train_sync(
        cls,
        colmap_dir: str,
        output_path: str,
        iterations: int = 7000,
        save_every: int = 0,
        downscale_factor: int = 1,
        num_points: int = 0,
        sh_degree: int = 3
    ) -> dict:
        """同步训练 3DGS 模型

        Args:
            colmap_dir: COLMAP 输出目录 (包含 sparse/0 和 images)
            output_path: 输出 .ply 文件路径
            iterations: 训练迭代次数 (默认 7000)
            save_every: 每隔多少次保存检查点 (0=仅最终)
            downscale_factor: 图像缩小倍数 (1=原尺寸)
            num_points: 初始点数 (0=自动)
            sh_degree: 球谐函数阶数 (默认 3)

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
        installed, msg = cls._check_installed()
        if not installed:
            result['message'] = msg
            return result

        # 确保输出目录存在
        output_dir = os.path.dirname(output_path)
        os.makedirs(output_dir, exist_ok=True)

        # 构建训练命令
        cmd = [
            cls.OPENSPLAT_BIN,
            os.path.join(colmap_dir, "colmap"),
            # 输入: COLMAP 目录
            "--colmap-image-path", os.path.join(colmap_dir, 'images'),
            '-o', output_path,       # 输出: .ply 文件
            '-n', str(iterations),   # 迭代次数
            '--sh-degree', str(sh_degree),
        ]

        if save_every > 0:
            cmd.extend(['--save-every', str(save_every)])

        if downscale_factor > 1:
            cmd.extend(['-d', str(downscale_factor)])

        if num_points > 0:
            cmd.extend(['--num-points', str(num_points)])

        with CodeTimer(name=f'OpenSplat训练 ({iterations} iterations)'):
            try:
                logger.info(f"开始 OpenSplat 训练: {' '.join(cmd)}")

                process = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=7200  # 2小时超时
                )

                if process.returncode != 0:
                    result['message'] = f'训练失败: {process.stderr[-500:]}'
                    logger.error(f"OpenSplat 输出: {process.stdout[-500:]}")
                    return result

                # 解析输出获取统计信息
                logger.debug(f"OpenSplat 输出: {process.stdout[-1000:]}")

            except subprocess.TimeoutExpired:
                result['message'] = '训练超时 (超过2小时)'
                return result
            except Exception as e:
                result['message'] = f'训练异常: {str(e)}'
                return result

        # 检查输出
        if not os.path.exists(output_path):
            # OpenSplat 可能自动添加 .ply 后缀
            if os.path.exists(output_path + '.ply'):
                output_path = output_path + '.ply'
            else:
                result['message'] = f'训练完成但未找到模型文件: {output_path}'
                return result

        result['success'] = True
        result['message'] = f'OpenSplat 训练完成 ({iterations} iterations)'
        result['model_path'] = output_path

        logger.info(f"OpenSplat 训练完成: {output_path}")

        return result

    @classmethod
    async def train(
        cls,
        colmap_dir: str,
        output_path: str,
        iterations: int = 7000,
        downscale_factor: int = 1
    ) -> dict:
        """异步训练 3DGS 模型

        Args:
            colmap_dir: COLMAP 输出目录
            output_path: 输出 .ply 文件路径
            iterations: 训练迭代次数
            downscale_factor: 图像缩小倍数

        Returns:
            dict: 训练结果
        """
        return await run_sync(
            cls._train_sync,
            colmap_dir,
            output_path,
            iterations,
            0,  # save_every
            downscale_factor
        )

    @classmethod
    async def train_with_docker(
        cls,
        colmap_dir: str,
        output_path: str,
        iterations: int = 7000,
        docker_image: str = 'pierotofy/opensplat:latest'
    ) -> dict:
        """使用 Docker 容器训练 (适合无本地安装的环境)

        Args:
            colmap_dir: COLMAP 输出目录 (本地路径)
            output_path: 输出 .ply 文件路径 (本地路径)
            iterations: 训练迭代次数
            docker_image: Docker 镜像名称

        Returns:
            dict: 训练结果
        """
        result = {
            'success': False,
            'message': '',
            'model_path': '',
            'iterations': iterations
        }

        # 转换为绝对路径
        colmap_dir = os.path.abspath(colmap_dir)
        output_dir = os.path.dirname(os.path.abspath(output_path))
        output_filename = os.path.basename(output_path)

        os.makedirs(output_dir, exist_ok=True)

        # 构建 Docker 命令
        cmd = [
            'docker', 'run', '--rm',
            '--gpus', 'all',  # 使用 GPU
            '-v', f'{colmap_dir}:/data:ro',
            '-v', f'{output_dir}:/output',
            docker_image,
            '/data',
            '-o', f'/output/{output_filename}',
            '-n', str(iterations),
        ]

        def _run():
            try:
                logger.info(f"开始 Docker OpenSplat 训练: {' '.join(cmd)}")

                process = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=7200
                )

                if process.returncode != 0:
                    return False, f'Docker 训练失败: {process.stderr[-500:]}'

                return True, ''

            except subprocess.TimeoutExpired:
                return False, '训练超时'
            except Exception as e:
                return False, str(e)

        with CodeTimer(name=f'Docker OpenSplat训练 ({iterations} iterations)'):
            success, msg = await run_sync(_run)

        if not success:
            result['message'] = msg
            return result

        # 检查输出
        if not os.path.exists(output_path):
            if os.path.exists(output_path + '.ply'):
                output_path = output_path + '.ply'
            else:
                result['message'] = f'训练完成但未找到模型文件: {output_path}'
                return result

        result['success'] = True
        result['message'] = 'Docker OpenSplat 训练完成'
        result['model_path'] = output_path

        return result
