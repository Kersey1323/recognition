#!/usr/bin/env python3
"""调试主业务外部服务和运行目录配置。"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 60)
print("主业务外部配置调试")
print("=" * 60)

print("\n【环境变量】")
print(f"MODEL_SERVICE_URL: {os.getenv('MODEL_SERVICE_URL', '未设置')}")
print(f"RECONSTRUCTION_SERVER_URL: {os.getenv('RECONSTRUCTION_SERVER_URL', '未设置')}")
print(f"AUTH_PROVIDER: {os.getenv('AUTH_PROVIDER', '未设置')}")
print(f"SGO_SSO_AUTH_URL: {os.getenv('SGO_SSO_AUTH_URL', '未设置')}")
print(f"TEMP_DIR: {os.getenv('TEMP_DIR', '未设置')}")
print(f"LOCAL_IMAGE_ROOT: {os.getenv('LOCAL_IMAGE_ROOT', '未设置')}")

print("\n【settings.py 配置】")
try:
    from csrcqsf.core import settings

    print(f"model_service_url: {settings.model_service_url}")
    print(f"reconstruction_server_url: {settings.reconstruction_server_url}")
    auth_settings = settings.load_auth_settings()
    print(f"auth_provider: {auth_settings.provider}")
    print(f"sgo_sso_auth_url: {auth_settings.sgo_auth_url or '未配置'}")
    print(f"temp_dir: {settings.temp_dir}")
except Exception as exc:
    print(f"❌ 加载 settings.py 失败: {exc}")

print("\n【vector_search/env_config.py 配置】")
try:
    from csrcqsf.modules.railway_parts.vector_search.config.env_config import get_config

    config = get_config()
    print(f"minio_endpoint: {config.minio_endpoint}")
    print(f"milvus: {config.milvus_host}:{config.milvus_port}")
    print(f"siglip_collection_name: {config.siglip_collection_name}")
    print(f"dinov2_collection_name: {config.dinov2_collection_name}")
    print(f"dinov2_patch_tokens_dir: {config.dinov2_patch_tokens_dir}")
    print(f"indexing_checkpoint_file: {config.indexing_checkpoint_file}")
    print(f"indexing_log_dir: {config.indexing_log_dir}")
    print(f"local_image_root: {config.local_image_root}")
except Exception as exc:
    print(f"❌ 加载 env_config.py 失败: {exc}")
    import traceback

    traceback.print_exc()

print("\n说明：主业务已不再读取 MODEL_DIR、SAM3_MODEL_PATH、SAM_MODEL_PATH。")
print("\n" + "=" * 60)
