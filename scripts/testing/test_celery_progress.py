#!/usr/bin/env python3
"""
测试 Celery 任务进度更新 - 使用实际日志文件模拟训练过程
"""
import sys
import os
import re
import time
from pathlib import Path

# 添加 reconstruction_server 到路径
reconstruction_server_path = Path(__file__).parent.parent.parent / "csrcqsf" / "biz" / "railwayparts" / "reconstruction_server"
sys.path.insert(0, str(reconstruction_server_path))

from celery_app import celery_app
from celery.result import AsyncResult

# 日志文件路径
LOG_FILE = Path(__file__).parent.parent.parent / "csrcqsf" / "biz" / "railwayparts" / "reconstruction_server" / "logs" / "95cc6415-129b-4cbd-9ab8-dfb77a862f45.log"

def simulate_training_progress(task_id: str):
    """
    模拟训练进度更新，从实际日志文件中提取进度
    """
    print(f"\n模拟任务 {task_id} 的训练进度更新...")
    print("=" * 60)
    
    if not LOG_FILE.exists():
        print(f"✗ 日志文件不存在: {LOG_FILE}")
        return False
    
    # 正则表达式
    progress_pattern = re.compile(r'Training progress:\s+(\d+)%')
    iteration_pattern = re.compile(r'\|\s*(\d+)/(\d+)')
    
    # 读取日志文件
    with open(LOG_FILE, 'r') as f:
        lines = f.readlines()
    
    # 提取所有训练进度行
    progress_lines = [line for line in lines if "Training progress" in line]
    
    if not progress_lines:
        print("✗ 日志文件中没有找到训练进度信息")
        return False
    
    print(f"✓ 找到 {len(progress_lines)} 行训练进度信息")
    
    # 初始化进度
    celery_app.backend.store_result(
        task_id,
        result={'stage': '初始化训练', 'progress': 0},
        state='PROGRESS'
    )
    print(f"  [0%] 初始化训练")
    
    # 模拟进度更新（每隔一定百分比更新一次）
    last_progress = 0
    update_count = 0
    
    for line in progress_lines:
        progress_match = progress_pattern.search(line)
        if progress_match:
            raw_progress = int(progress_match.group(1))
            # 训练进度映射到 10-95%
            mapped_progress = min(10 + int(raw_progress * 0.85), 95)
            
            # 只在进度变化超过 5% 时更新（模拟实际场景）
            if mapped_progress >= last_progress + 5:
                last_progress = mapped_progress
                
                # 提取迭代次数
                iter_match = iteration_pattern.search(line)
                if iter_match:
                    current = int(iter_match.group(1))
                    total = int(iter_match.group(2))
                    stage = f"训练中 {current}/{total}"
                else:
                    stage = "训练中"
                
                # 更新状态
                celery_app.backend.store_result(
                    task_id,
                    result={'stage': stage, 'progress': mapped_progress},
                    state='PROGRESS'
                )
                
                update_count += 1
                print(f"  [{mapped_progress}%] {stage}")
                
                # 模拟延迟
                time.sleep(0.1)
    
    # 完成
    celery_app.backend.store_result(
        task_id,
        result={'stage': '完成', 'progress': 100},
        state='SUCCESS'
    )
    print(f"  [100%] 完成")
    print(f"\n✓ 共更新了 {update_count} 次进度")
    
    return True

def verify_progress_updates(task_id: str):
    """
    验证进度更新是否正确保存和读取
    """
    print(f"\n验证任务 {task_id} 的进度信息...")
    print("=" * 60)
    
    result = AsyncResult(task_id, app=celery_app)
    task_meta = celery_app.backend.get_task_meta(task_id)
    
    print(f"State: {result.state}")
    print(f"Info: {result.info}")
    print(f"Task Meta: {task_meta}")
    
    if result.state == 'SUCCESS':
        if result.info and result.info.get('progress') == 100:
            print("\n✓ 进度信息验证成功")
            return True
        else:
            print(f"\n✗ 进度信息不正确: {result.info}")
            return False
    else:
        print(f"\n✗ 任务状态不正确: {result.state}")
        return False

def test_real_task_progress(task_id: str):
    """
    测试实际运行中的任务进度
    """
    print(f"\n查询实际任务 {task_id} 的进度...")
    print("=" * 60)
    
    result = AsyncResult(task_id, app=celery_app)
    task_meta = celery_app.backend.get_task_meta(task_id)
    
    print(f"State: {result.state}")
    print(f"Info: {result.info}")
    
    if task_meta:
        print(f"\nTask Meta:")
        print(f"  - status: {task_meta.get('status')}")
        print(f"  - result: {task_meta.get('result')}")
        print(f"  - traceback: {task_meta.get('traceback')}")
    
    # 如果是 PROGRESS 状态，检查进度信息
    if result.state == 'PROGRESS':
        if result.info:
            stage = result.info.get('stage', 'Unknown')
            progress = result.info.get('progress', 0)
            print(f"\n当前进度: [{progress}%] {stage}")
            
            if progress > 10:
                print("✓ 进度正在更新")
                return True
            else:
                print("✗ 进度停留在初始值")
                return False
        else:
            print("\n✗ 进度信息为空")
            return False
    elif result.state == 'STARTED':
        print("\n⚠ 任务已开始但还没有进度更新")
        return False
    else:
        print(f"\n任务状态: {result.state}")
        return True

if __name__ == "__main__":
    print("Celery 任务进度更新测试\n")
    
    if len(sys.argv) > 1:
        # 如果提供了任务 ID，查询实际任务
        task_id = sys.argv[1]
        test_real_task_progress(task_id)
    else:
        # 否则运行模拟测试
        test_task_id = f"test-progress-{int(time.time())}"
        
        # 模拟训练进度
        if simulate_training_progress(test_task_id):
            # 验证进度更新
            time.sleep(0.5)
            verify_progress_updates(test_task_id)
        
        print("\n" + "=" * 60)
        print("提示：要测试实际任务，请运行:")
        print(f"  python {sys.argv[0]} <task_id>")
        print("=" * 60)
