#!/usr/bin/env python3
"""诊断主业务服务中的环境变量加载情况。"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 60)
print("诊断主业务环境变量加载")
print("=" * 60)

env_file = PROJECT_ROOT / ".env"
print("\n【.env 文件】")
print(f"路径: {env_file}")
print(f"存在: {env_file.exists()}")
if env_file.exists():
    print(f"大小: {env_file.stat().st_size} bytes")

print("\n【加载环境变量】")
load_dotenv(env_file)
print("✓ dotenv 加载完成")

print("\n【关键环境变量】")
key_vars = [
    "MAIN_DB_HOST",
    "MAIN_DB_PORT",
    "MAIN_DB_DATABASE",
    "MILVUS_HOST",
    "MILVUS_PORT",
    "MINIO_ENDPOINT",
    "BASIS_API_HTTP_URL",
    "MODEL_SERVICE_URL",
    "RECONSTRUCTION_SERVER_URL",
]
for var in key_vars:
    value = os.getenv(var)
    print(f"{'✓' if value else '✗'} {var}: {value or '未设置'}")

print("\n【测试 settings.py】")
try:
    from csrcqsf.core import settings

    print("✓ settings.py 加载成功")
    print(f"  temp_dir: {settings.temp_dir}")
    print(f"  model_service_url: {settings.model_service_url}")
    print(f"  reconstruction_server_url: {settings.reconstruction_server_url}")
    print(f"  basis_api_http_url: {settings.basis_api_http_url or '未配置'}")
except Exception as exc:
    print(f"✗ settings.py 加载失败: {exc}")
    import traceback

    traceback.print_exc()

print("\n【测试 env_config.py】")
try:
    from csrcqsf.modules.railway_parts.vector_search.config.env_config import get_config

    config = get_config()
    print("✓ 向量检索配置加载成功")
    print(f"  MinIO: {config.minio_endpoint}")
    print(f"  Milvus: {config.milvus_host}:{config.milvus_port}")
    print(f"  Patch Tokens Dir: {config.dinov2_patch_tokens_dir}")
    print(f"  Checkpoint File: {config.indexing_checkpoint_file}")
except Exception as exc:
    print(f"✗ 向量检索配置加载失败: {exc}")
    import traceback

    traceback.print_exc()

print("\n说明：主业务已不再依赖 MODEL_DIR 或本地模型路径。")
print("\n" + "=" * 60)
print("诊断完成")
print("=" * 60)
