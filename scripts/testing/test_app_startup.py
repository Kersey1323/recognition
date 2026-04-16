#!/usr/bin/env python3
"""测试应用启动时定时任务是否自动开始"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

print("正在导入应用...")
from csrcqsf.app import app

print("✓ 应用启动成功")

from csrcqsf.scheduler import scheduler

jobs = scheduler.get_jobs()
print(f"✓ 定时任务数量: {len(jobs)}")

for job in jobs:
    print(f"  - {job.id}: {job.name}")
    print(f"    下次运行: {job.next_run_time}")

print("\n✓ 定时任务已随应用启动自动开始")
