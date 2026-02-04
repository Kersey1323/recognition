from csrcqsf.biz.reconstruction.pipeline import ReconstructionPipeline

# 方式1: 异步任务 (后台运行)
task = await ReconstructionPipeline.create_task_from_local(
    local_image_dir=r"E:\test_images",
    item_id=123,          # 可选
    upload_result=False   # 测试时不上传
)
print(f"任务ID: {task.task_id}")
# 方式2: 同步等待结果 (快速测试)
result = await ReconstructionPipeline.run_local_sync(
    local_image_dir=r"E:\test_images",
    output_dir=r"E:\output",  # 可选
    iterations=3000           # 可减少迭代次数加快测试
)
print(f"OBJ 路径: {result['obj_path']}")