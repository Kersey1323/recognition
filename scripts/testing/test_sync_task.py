#!/usr/bin/env python3
"""测试重建任务状态同步功能"""
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

print("正在导入模块...")
from csrcqsf.core.scheduler import _sync_reconstruction_tasks_wrapper

print("✓ 模块导入成功")
print("\n执行一次任务同步...")

try:
    _sync_reconstruction_tasks_wrapper()
    print("✓ 任务同步执行成功")
except Exception as e:
    print(f"✗ 任务同步执行失败: {e}")
    import traceback
    traceback.print_exc()

print("\n测试完成")
