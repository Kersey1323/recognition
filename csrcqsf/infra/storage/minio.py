from bfrcommon.minio import Bucket
from pathlib import Path
from urllib.parse import urlparse
from minio.error import S3Error
from csrcqsf.core.settings import (
    minio_access_key,
    minio_bucket,
    minio_endpoint,
    minio_reconstruction_file_bucket,
    minio_reconstruction_video_bucket,
    minio_search_history_bucket,
    minio_secret_key,
    minio_secure,
)
import traceback
from csrcqsf.core.logging_config import logger

minio_instance = Bucket(
    minio_endpoint,
    minio_access_key,
    minio_secret_key,
    secure=minio_secure,
)


def ensure_minio_bucket(bucket_name: str, lock_enabled: bool = True):
    """确保指定 bucket 存在。"""
    if bucket_name is None or bucket_name.strip() == "":
        raise ValueError("bucket_name 不能为空")

    if minio_instance.exists_bucket(bucket_name) == False:
        minio_instance.create_bucket(bucket_name, lock_enabled)
        logger.info(f"已创建 MinIO bucket: {bucket_name}")


def create_minio_buckets_sync():
    """同步版本：创建项目需要的所有 bucket。"""
    ensure_minio_bucket(minio_bucket)
    ensure_minio_bucket(minio_reconstruction_video_bucket)
    ensure_minio_bucket(minio_reconstruction_file_bucket)
    ensure_minio_bucket(minio_search_history_bucket)


async def create_minio_bucket():
    """兼容旧调用：创建项目默认 bucket 和 3D 重建原始视频 bucket。"""
    try:
        create_minio_buckets_sync()
    except S3Error as e:
        if e.code in {"InvalidAccessKeyId", "SignatureDoesNotMatch"}:
            logger.error(
                "创建 MinIO bucket 失败：请检查凭证是否与服务端匹配。"
                f" endpoint={minio_endpoint}, access_key={minio_access_key}, bucket={minio_bucket}, error={e.code}"
            )
            return
        logger.error(f'创建桶出错:err{e}{traceback.format_exc()}')
    except Exception as e:
        logger.error(f'创建桶出错:err{e}{traceback.format_exc()}')


async def create_minio_buckets():
    await create_minio_bucket()


def parse_minio_path(path: str, default_bucket: str | None = None) -> tuple[str, str]:
    """
    解析 MinIO 对象路径。

    支持：
    - minio://bucket/object
    - s3://bucket/object
    - http://host:port/bucket/object
    - https://host:port/bucket/object
    - /recognition_oss/bucket/object（Nginx internal 代理路径）
    - bucket/object，其中 bucket 必须是项目已知 bucket
    """
    if path is None or path.strip() == "":
        raise ValueError("MinIO path 不能为空")

    raw_path = path.strip()
    internal_proxy_prefix = "/recognition_oss/"
    if raw_path.startswith(internal_proxy_prefix):
        # 业务接口返回的内部代理地址仍指向 MinIO，读取对象前需还原为 bucket/object。
        raw_path = raw_path[len(internal_proxy_prefix):]
    known_buckets = {
        bucket for bucket in [
            minio_bucket,
            minio_reconstruction_video_bucket,
            minio_reconstruction_file_bucket,
            minio_search_history_bucket,
            default_bucket,
        ] if bucket
    }

    # 对外返回可访问 URL，对内始终还原为 MinIO 的 bucket/object 二元定位。
    if raw_path.startswith(("minio://", "s3://")):
        parsed = urlparse(raw_path)
        bucket = parsed.netloc
        object_name = parsed.path.lstrip("/")
    elif raw_path.startswith(("http://", "https://")):
        parsed = urlparse(raw_path)
        parts = parsed.path.lstrip("/").split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"MinIO URL 缺少 bucket 或 object: {path}")
        bucket, object_name = parts
    else:
        bucket = ""
        object_name = ""
        for known_bucket in known_buckets:
            prefix = f"{known_bucket}/"
            if raw_path.startswith(prefix):
                bucket = known_bucket
                object_name = raw_path[len(prefix):]
                break

    if not bucket or not object_name:
        raise ValueError(f"不是可识别的 MinIO 对象路径: {path}")

    return bucket, object_name


def looks_like_minio_path(path: str, default_bucket: str | None = None) -> bool:
    """复用完整解析规则判断路径，避免识别逻辑与实际下载规则分叉。"""
    try:
        parse_minio_path(path, default_bucket=default_bucket)
        return True
    except Exception:
        return False


def download_minio_object_to_file(
    minio_path: str,
    local_path: str,
    default_bucket: str | None = None,
) -> tuple[str, str, str]:
    """下载 MinIO 对象到本地文件，返回 bucket、object_name、local_path。"""
    bucket, object_name = parse_minio_path(minio_path, default_bucket=default_bucket)
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    minio_instance.fget_file(bucket, object_name, local_path)
    return bucket, object_name, local_path
