#!/usr/bin/env python3
"""检查主业务当前环境变量和基础日志输出。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from csrcqsf.core.settings import (
    ai_settings,
    basis_api_http_url,
    main_db_database,
    minio_bucket,
    minio_endpoint,
    minio_search_history_bucket,
    reconstruction_server_timeout_sec,
    reconstruction_server_url,
    sgo_mysql_database,
    temp_dir,
)
from globals_vars import logger


def _masked(value: str) -> str:
    return "*" * len(value) if value else "未设置"


def test_environment_variables():
    """输出当前主业务真正使用的配置口径。"""
    print("=" * 60)
    print("主业务配置测试")
    print("=" * 60)

    print("\n【应用配置】")
    print(f"  TEMP_DIR: {temp_dir}")

    print("\n【主业务数据库】")
    print(f"  MySQL: {ai_settings.mysql.url}:{ai_settings.mysql.port}/{main_db_database}")
    print(f"  用户: {ai_settings.mysql.user_name}")
    print(f"  密码: {_masked(ai_settings.mysql.password)}")

    print("\n【Milvus配置】")
    print(f"  URL: {ai_settings.milvus_url}")

    print("\n【MinIO配置】")
    print(f"  端点: {minio_endpoint}")
    print(f"  默认 Bucket: {minio_bucket}")
    print(f"  检索历史 Bucket: {minio_search_history_bucket}")

    print("\n【SGO配置】")
    print(f"  MySQL: {ai_settings.sgo_mysql_url}:{ai_settings.sgo_mysql_port}/{sgo_mysql_database}")

    print("\n【外部服务】")
    print(f"  BASIS_API_GRPC_URL: {ai_settings.basis_api_grpc_url}")
    print(f"  BASIS_API_HTTP_URL: {basis_api_http_url or '未设置'}")
    print(f"  RECONSTRUCTION_SERVER_URL: {reconstruction_server_url}")
    print(f"  RECONSTRUCTION_SERVER_TIMEOUT_SEC: {reconstruction_server_timeout_sec}")

    print("\n✅ 环境变量配置测试完成")


def test_logging_system():
    """验证主业务日志目录和基础日志输出。"""
    print("\n" + "=" * 60)
    print("日志系统测试")
    print("=" * 60)

    logger.info("主业务配置测试脚本日志输出检查")
    logger.warning("主业务配置测试脚本告警输出检查")

    log_dir = PROJECT_ROOT / "logs"
    print("\n【检查日志目录】")
    if log_dir.exists():
        log_files = list(log_dir.glob("*.log"))
        print(f"  日志目录: {log_dir}")
        print(f"  日志文件数量: {len(log_files)}")
    else:
        print(f"  ⚠️  日志目录不存在: {log_dir}")

    print("\n✅ 日志系统测试完成")


def test_configuration_warnings():
    """检查当前主业务最关键的缺省项。"""
    print("\n" + "=" * 60)
    print("配置检查")
    print("=" * 60)

    warnings = []
    if not basis_api_http_url:
        warnings.append("未配置 BASIS_API_HTTP_URL，下载代理鉴权接口会不可用")
    if reconstruction_server_url.strip() == "":
        warnings.append("未配置 RECONSTRUCTION_SERVER_URL，三维重构接口会禁用")

    if warnings:
        print("\n【配置提示】")
        for warning in warnings:
            print(f"  ⚠️  {warning}")
    else:
        print("\n✅ 关键外部服务配置已具备")


def main():
    print("\n" + "=" * 60)
    print("铁路配件智能识别系统 - 主业务配置测试")
    print("=" * 60)

    try:
        test_environment_variables()
        test_logging_system()
        test_configuration_warnings()

        print("\n" + "=" * 60)
        print("✅ 所有测试完成")
        print("=" * 60)
    except Exception as exc:
        print(f"\n❌ 测试失败: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
