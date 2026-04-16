#!/usr/bin/env python3
"""
配置测试脚本
用于验证环境变量和日志系统是否正常工作
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from csrcqsf.settings import ai_settings, APP_ENV, APP_PORT, APP_LOG_LEVEL
from globals_vars import logger
from csrcqsf.logger import used_time


def test_environment_variables():
    """测试环境变量配置"""
    print("=" * 60)
    print("环境变量配置测试")
    print("=" * 60)
    
    print(f"\n【应用配置】")
    print(f"  环境: {APP_ENV}")
    print(f"  端口: {APP_PORT}")
    print(f"  日志级别: {APP_LOG_LEVEL}")
    
    print(f"\n【数据库配置】")
    print(f"  PostgreSQL: {ai_settings.pg_host}:{ai_settings.pg_port}/{ai_settings.pg_database}")
    print(f"  用户: {ai_settings.pg_user}")
    print(f"  密码: {'*' * len(ai_settings.pg_password)}")
    
    print(f"\n【Redis配置】")
    print(f"  主机: {ai_settings.redis_host}:{ai_settings.redis_port}")
    print(f"  数据库: {ai_settings.redis_db}")
    print(f"  密码: {'已设置' if ai_settings.redis_password else '未设置'}")
    
    print(f"\n【Milvus配置】")
    print(f"  URL: {ai_settings.milvus_url}")
    
    print(f"\n【MinIO配置】")
    print(f"  端点: {ai_settings.minio_endpoint}")
    print(f"  Bucket: {ai_settings.minio_bucket}")
    print(f"  访问密钥: {'*' * 10}")
    
    print(f"\n【JWT配置】")
    print(f"  算法: {ai_settings.jwt_algorithm}")
    print(f"  访问Token过期: {ai_settings.jwt_access_token_expire_minutes} 分钟")
    print(f"  刷新Token过期: {ai_settings.jwt_refresh_token_expire_days} 天")
    print(f"  密钥: {'*' * 20}")
    
    print(f"\n【SGO配置】")
    print(f"  MySQL: {ai_settings.sgo_mysql_url}:{ai_settings.sgo_mysql_port}/{ai_settings.sgo_mysql_database}")
    
    print("\n✅ 环境变量配置测试完成")


def test_logging_system():
    """测试日志系统"""
    print("\n" + "=" * 60)
    print("日志系统测试")
    print("=" * 60)
    
    # 测试不同级别的日志
    print("\n【测试日志级别】")
    logger.debug("这是DEBUG级别日志")
    logger.info("这是INFO级别日志")
    logger.warning("这是WARNING级别日志")
    logger.error("这是ERROR级别日志")
    
    # 测试结构化日志
    print("\n【测试结构化日志】")
    logger.info("测试结构化日志", extra={
        "test_type": "structured_logging",
        "test_number": 123,
        "test_bool": True
    })
    
    # 测试API请求日志
    print("\n【测试API请求日志】")
    log_api_request(
        method="POST",
        path="/api/test",
        user_id=999,
        ip="127.0.0.1"
    )
    
    # 测试审计日志
    print("\n【测试审计日志】")
    log_audit(
        user_id=999,
        action="test_action",
        resource_type="test_resource",
        resource_id=123,
        ip="127.0.0.1",
        before={"status": "old"},
        after={"status": "new"}
    )
    
    # 测试任务日志
    print("\n【测试任务日志】")
    log_task_start(
        task_id="test_task_001",
        task_type="test_task",
        param1="value1"
    )
    
    log_task_complete(
        task_id="test_task_001",
        task_type="test_task",
        duration=1.23,
        status="success",
        result="测试完成"
    )
    
    # 检查日志文件
    print("\n【检查日志文件】")
    log_dir = PROJECT_ROOT / "logs"
    if log_dir.exists():
        log_files = list(log_dir.glob("*.log"))
        print(f"  日志目录: {log_dir}")
        print(f"  日志文件数量: {len(log_files)}")
        for log_file in sorted(log_files)[:5]:  # 只显示前5个
            size = log_file.stat().st_size
            print(f"    - {log_file.name} ({size:,} bytes)")
    else:
        print(f"  ⚠️  日志目录不存在: {log_dir}")
    
    print("\n✅ 日志系统测试完成")


def test_security_warnings():
    """安全检查"""
    print("\n" + "=" * 60)
    print("安全检查")
    print("=" * 60)
    
    warnings = []
    
    # 检查JWT密钥
    if "dev" in ai_settings.jwt_secret_key.lower() or "test" in ai_settings.jwt_secret_key.lower():
        warnings.append("⚠️  JWT密钥使用了默认值，生产环境必须修改！")
    
    # 检查Redis密码
    if not ai_settings.redis_password and APP_ENV == "production":
        warnings.append("⚠️  生产环境Redis未设置密码！")
    
    # 检查环境
    if APP_ENV == "production" and APP_LOG_LEVEL == "DEBUG":
        warnings.append("⚠️  生产环境不应使用DEBUG日志级别！")
    
    # 检查.env文件
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        warnings.append("⚠️  .env文件不存在，使用默认配置！")
    
    if warnings:
        print("\n【安全警告】")
        for warning in warnings:
            print(f"  {warning}")
    else:
        print("\n✅ 未发现安全问题")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("铁路配件智能识别系统 - 配置测试")
    print("=" * 60)
    
    try:
        # 测试环境变量
        test_environment_variables()
        
        # 测试日志系统
        test_logging_system()
        
        # 安全检查
        test_security_warnings()
        
        print("\n" + "=" * 60)
        print("✅ 所有测试完成！")
        print("=" * 60)
        print("\n提示：")
        print("  1. 检查 logs/ 目录下的日志文件")
        print("  2. 生产环境部署前请修改所有默认密码和密钥")
        print("  3. 参考 docs/ENVIRONMENT_SETUP.md 了解详细配置")
        print()
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
