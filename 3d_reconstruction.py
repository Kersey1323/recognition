"""3D 重建测试脚本

从本地图片目录进行 3D Gaussian Splatting 重建测试。
支持选择 opensplat 或 gaussian-splatting 训练器。
"""

import asyncio

from csrcqsf.biz.reconstruction.pipeline import ReconstructionPipeline, TrainerType


async def test_async_task():
    """方式1: 异步任务 (后台运行)"""
    task = await ReconstructionPipeline.create_task_from_local(
        local_image_dir=r"E:\test_images",
        item_id=123,
        upload_result=False,
        trainer_type=TrainerType.OPENSPLAT,  # 或 TrainerType.GAUSSIAN
        iterations=3000
    )
    print(f"任务ID: {task.task_id}")
    
    # 轮询等待任务完成
    while task.status not in ('completed', 'failed'):
        await asyncio.sleep(5)
        task = ReconstructionPipeline.get_task(task.task_id)
        print(f"进度: {task.progress}% - {task.message}")
    
    if task.status == 'completed':
        print(f"完成! OBJ: {task.obj_url}")
    else:
        print(f"失败: {task.error}")


async def test_sync_run():
    """方式2: 同步等待结果 (快速测试)"""
    result = await ReconstructionPipeline.run_local_sync(
        local_image_dir=r"E:\test_images",
        output_dir=r"E:\output",
        iterations=3000,
        trainer_type=TrainerType.OPENSPLAT  # 或 TrainerType.GAUSSIAN
    )
    
    if result['success']:
        print(f"OBJ 路径: {result['obj_path']}")
        print(f"顶点数: {result.get('num_vertices', 'N/A')}")
        print(f"面数: {result.get('num_faces', 'N/A')}")
    else:
        print(f"失败: {result['message']}")


if __name__ == '__main__':
    # 选择测试方式 (取消注释其中一个)
    
    # asyncio.run(test_async_task())  # 异步任务
    asyncio.run(test_sync_run())      # 同步等待