#!/usr/bin/env python3
"""
测试 Celery 与 Redis 的连接和状态更新
"""
import sys
import os
from pathlib import Path

# 添加 reconstruction_server 到路径
reconstruction_server_path = Path(__file__).parent.parent.parent / "csrcqsf" / "biz" / "railwayparts" / "reconstruction_server"
sys.path.insert(0, str(reconstruction_server_path))

from celery_app import celery_app
from celery.result import AsyncResult
import time

def test_redis_connection():
    """测试 Redis 连接"""
    print("=" * 60)
    print("测试 1: Redis 连接")
    print("=" * 60)
    
    try:
        # 尝试 ping Redis
        result = celery_app.backend.client.ping()
        print(f"✓ Redis 连接成功: {result}")
        return True
    except Exception as e:
        print(f"✗ Redis 连接失败: {e}")
        return False

def test_task_state_update():
    """测试任务状态更新"""
    print("\n" + "=" * 60)
    print("测试 2: 任务状态更新")
    print("=" * 60)
    
    # 创建一个测试任务 ID
    test_task_id = "test-task-" + str(int(time.time()))
    
    try:
        # 手动创建一个 AsyncResult 并更新状态
        result = AsyncResult(test_task_id, app=celery_app)
        
        # 更新状态为 PROGRESS
        celery_app.backend.store_result(
            test_task_id,
            result={'stage': '测试阶段', 'progress': 50},
            state='PROGRESS'
        )
        
        print(f"✓ 状态已更新: task_id={test_task_id}")
        
        # 读取状态
        result = AsyncResult(test_task_id, app=celery_app)
        
        # 直接从 backend 读取
        task_meta = celery_app.backend.get_task_meta(test_task_id)
        
        print(f"  - State: {result.state}")
        print(f"  - Info (result.info): {result.info}")
        print(f"  - Task Meta: {task_meta}")
        
        if task_meta and task_meta.get('status') == 'PROGRESS':
            meta_result = task_meta.get('result')
            if meta_result and isinstance(meta_result, dict) and meta_result.get('progress') == 50:
                print("✓ 状态读取成功")
                return True
            else:
                print(f"✗ 状态读取失败: result 格式不正确 (result={meta_result})")
                return False
        else:
            print(f"✗ 状态读取失败: task_meta={task_meta}")
            return False
            
    except Exception as e:
        print(f"✗ 状态更新失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_celery_config():
    """测试 Celery 配置"""
    print("\n" + "=" * 60)
    print("测试 3: Celery 配置")
    print("=" * 60)
    
    print(f"Broker URL: {celery_app.conf.broker_url}")
    print(f"Backend URL: {celery_app.conf.result_backend}")
    print(f"Task track started: {celery_app.conf.task_track_started}")
    print(f"Task serializer: {celery_app.conf.task_serializer}")
    print(f"Result serializer: {celery_app.conf.result_serializer}")

if __name__ == "__main__":
    print("Celery + Redis 连接测试\n")
    
    # 测试 Redis 连接
    redis_ok = test_redis_connection()
    
    if redis_ok:
        # 测试状态更新
        state_ok = test_task_state_update()
        
        # 显示配置
        test_celery_config()
        
        print("\n" + "=" * 60)
        if redis_ok and state_ok:
            print("✓ 所有测试通过")
        else:
            print("✗ 部分测试失败")
        print("=" * 60)
    else:
        print("\n请确保 Redis 正在运行:")
        print("  redis-server --port 6380")
