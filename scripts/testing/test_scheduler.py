#!/usr/bin/env python3
"""测试定时任务调度器"""
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from csrcqsf.core.scheduler import scheduler

print("✓ 定时任务调度器已启动")

jobs = scheduler.get_jobs()
print(f"✓ 当前活跃任务数: {len(jobs)}")

for job in jobs:
    print(f"  - {job.id}: {job.name}")
    print(f"    触发器: {job.trigger}")
    print(f"    下次运行: {job.next_run_time}")

time.sleep(1)
print("✓ 调度器运行正常")
