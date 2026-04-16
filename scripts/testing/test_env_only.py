#!/usr/bin/env python3
"""
简单的环境变量测试脚本（不依赖项目模块）
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
PROJECT_ROOT = Path(__file__).parent.parent.parent
env_file = PROJECT_ROOT / ".env"

print("=" * 60)
print("环境变量测试")
print("=" * 60)

if env_file.exists():
    print(f"\n✅ 找到 .env 文件: {env_file}")
    load_dotenv(env_file)
else:
    print(f"\n⚠️  未找到 .env 文件: {env_file}")
    print("将使用系统环境变量")

print("\n【应用配置】")
print(f"  APP_ENV: {os.getenv('APP_ENV', '未设置')}")
print(f"  APP_PORT: {os.getenv('APP_PORT', '未设置')}")
print(f"  APP_DEBUG: {os.getenv('APP_DEBUG', '未设置')}")
print(f"  APP_LOG_LEVEL: {os.getenv('APP_LOG_LEVEL', '未设置')}")

print("\n【数据库配置】")
print(f"  PG_HOST: {os.getenv('PG_HOST', '未设置')}")
print(f"  PG_PORT: {os.getenv('PG_PORT', '未设置')}")
print(f"  PG_USER: {os.getenv('PG_USER', '未设置')}")
pg_password = os.getenv('PG_PASSWORD', '')
print(f"  PG_PASSWORD: {'*' * len(pg_password) if pg_password else '未设置'}")
print(f"  PG_DATABASE: {os.getenv('PG_DATABASE', '未设置')}")

print("\n【Redis配置】")
print(f"  REDIS_HOST: {os.getenv('REDIS_HOST', '未设置')}")
print(f"  REDIS_PORT: {os.getenv('REDIS_PORT', '未设置')}")
redis_password = os.getenv('REDIS_PASSWORD', '')
print(f"  REDIS_PASSWORD: {'已设置' if redis_password else '未设置'}")

print("\n【Milvus配置】")
print(f"  MILVUS_HOST: {os.getenv('MILVUS_HOST', '未设置')}")
print(f"  MILVUS_PORT: {os.getenv('MILVUS_PORT', '未设置')}")

print("\n【MinIO配置】")
print(f"  MINIO_ENDPOINT: {os.getenv('MINIO_ENDPOINT', '未设置')}")
print(f"  MINIO_BUCKET: {os.getenv('MINIO_BUCKET', '未设置')}")

print("\n【JWT配置】")
jwt_secret = os.getenv('JWT_SECRET_KEY', '')
print(f"  JWT_SECRET_KEY: {'*' * 20 if jwt_secret else '未设置'}")
print(f"  JWT_ALGORITHM: {os.getenv('JWT_ALGORITHM', '未设置')}")

print("\n【安全检查】")
warnings = []

if 'dev' in jwt_secret.lower() or 'test' in jwt_secret.lower():
    warnings.append("⚠️  JWT密钥使用了默认值，生产环境必须修改！")

if not redis_password and os.getenv('APP_ENV') == 'production':
    warnings.append("⚠️  生产环境Redis未设置密码！")

if os.getenv('APP_ENV') == 'production' and os.getenv('APP_LOG_LEVEL') == 'DEBUG':
    warnings.append("⚠️  生产环境不应使用DEBUG日志级别！")

if warnings:
    for warning in warnings:
        print(f"  {warning}")
else:
    print("  ✅ 未发现安全问题")

print("\n" + "=" * 60)
print("测试完成！")
print("=" * 60)
