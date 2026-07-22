#!/usr/bin/env python3
"""简单检查当前 .env 中的主业务运行配置。"""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def _masked(value: str) -> str:
    return "*" * len(value) if value else "未设置"


print("=" * 60)
print("主业务环境变量测试")
print("=" * 60)

if ENV_FILE.exists():
    print(f"\n已加载 .env 文件: {ENV_FILE}")
    load_dotenv(ENV_FILE)
else:
    print(f"\n未找到 .env 文件: {ENV_FILE}")
    print("将仅读取当前 shell 环境变量")

print("\n【应用配置】")
print(f"  APP_PORT: {os.getenv('APP_PORT', '未设置')}")
print(f"  TEMP_DIR: {os.getenv('TEMP_DIR', '未设置')}")

print("\n【主业务数据库】")
print(f"  MAIN_DB_HOST: {os.getenv('MAIN_DB_HOST', '未设置')}")
print(f"  MAIN_DB_PORT: {os.getenv('MAIN_DB_PORT', '未设置')}")
print(f"  MAIN_DB_USER: {os.getenv('MAIN_DB_USER', '未设置')}")
print(f"  MAIN_DB_PASSWORD: {_masked(os.getenv('MAIN_DB_PASSWORD', ''))}")
print(f"  MAIN_DB_DATABASE: {os.getenv('MAIN_DB_DATABASE', '未设置')}")

print("\n【Redis / Celery】")
print(f"  REDIS_HOST: {os.getenv('REDIS_HOST', '未设置')}")
print(f"  REDIS_PORT: {os.getenv('REDIS_PORT', '未设置')}")
print(f"  CELERY_BROKER_URL: {os.getenv('CELERY_BROKER_URL', '未设置')}")
print(f"  CELERY_RESULT_BACKEND: {os.getenv('CELERY_RESULT_BACKEND', '未设置')}")

print("\n【Milvus / MinIO】")
print(f"  MILVUS_HOST: {os.getenv('MILVUS_HOST', '未设置')}")
print(f"  MILVUS_PORT: {os.getenv('MILVUS_PORT', '未设置')}")
print(f"  MINIO_ENDPOINT: {os.getenv('MINIO_ENDPOINT', '未设置')}")
print(f"  MINIO_BUCKET: {os.getenv('MINIO_BUCKET', '未设置')}")

print("\n【外部服务】")
print(f"  BASIS_API_HTTP_URL: {os.getenv('BASIS_API_HTTP_URL', '未设置')}")
print(f"  MODEL_SERVICE_URL: {os.getenv('MODEL_SERVICE_URL', '未设置')}")
print(f"  RECONSTRUCTION_SERVER_URL: {os.getenv('RECONSTRUCTION_SERVER_URL', '未设置')}")
print(
    "  RECONSTRUCTION_SERVER_TIMEOUT_SEC: "
    f"{os.getenv('RECONSTRUCTION_SERVER_TIMEOUT_SEC', '未设置')}"
)

print("\n【检查结果】")
warnings = []
required_keys = [
    "MAIN_DB_HOST",
    "MAIN_DB_PORT",
    "MAIN_DB_USER",
    "MAIN_DB_PASSWORD",
    "MAIN_DB_DATABASE",
    "MINIO_ENDPOINT",
    "MODEL_SERVICE_URL",
]
for key in required_keys:
    if not os.getenv(key):
        warnings.append(f"缺少必需配置: {key}")

if warnings:
    for warning in warnings:
        print(f"  ⚠ {warning}")
else:
    print("  ✅ 关键配置已具备")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
