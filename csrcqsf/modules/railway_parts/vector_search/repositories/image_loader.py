"""
图像加载器
"""
import os
from io import BytesIO
from typing import Optional
from PIL import Image
import requests
from minio import Minio

from csrcqsf.modules.railway_parts.vector_search.utils.logger import setup_logger

logger = setup_logger(__name__)


class ImageLoader:
    """图像加载器（支持 MinIO 和本地文件系统）"""

    def __init__(
        self,
        minio_endpoint: Optional[str] = None,
        minio_access_key: Optional[str] = None,
        minio_secret_key: Optional[str] = None,
        minio_bucket: Optional[str] = None,
        minio_secure: bool = False,
        local_image_root: Optional[str] = None
    ):
        """
        初始化图像加载器

        Args:
            minio_endpoint: MinIO 服务器地址
            minio_access_key: MinIO 访问密钥
            minio_secret_key: MinIO 密钥
            minio_bucket: MinIO 存储桶
            minio_secure: 是否使用 HTTPS
            local_image_root: 本地图像根目录
        """
        self.local_image_root = local_image_root

        # 初始化 MinIO 客户端
        if minio_endpoint and minio_access_key and minio_secret_key:
            self.minio_client = Minio(
                minio_endpoint,
                access_key=minio_access_key,
                secret_key=minio_secret_key,
                secure=minio_secure
            )
            self.minio_bucket = minio_bucket
            logger.info(f"MinIO client initialized: {minio_endpoint}")
        else:
            self.minio_client = None
            logger.info("MinIO client not configured")

    def load_image(self, image_url: str) -> Optional[Image.Image]:
        """
        加载图像（自动识别来源）

        Args:
            image_url: 图像 URL

        Returns:
            PIL Image 对象，加载失败返回 None
        """
        try:
            # MinIO URL
            if image_url.startswith("minio://"):
                return self._load_from_minio(image_url)

            # HTTP/HTTPS URL
            elif image_url.startswith("http://") or image_url.startswith("https://"):
                return self._load_from_url(image_url)

            # 本地文件路径
            else:
                return self._load_from_local(image_url)

        except Exception as e:
            logger.error(f"Failed to load image from {image_url}: {e}")
            return None

    def _load_from_minio(self, minio_url: str) -> Image.Image:
        """
        从 MinIO 加载图像

        Args:
            minio_url: MinIO URL (格式: minio://bucket/path/to/image.jpg)

        Returns:
            PIL Image 对象
        """
        if not self.minio_client:
            raise ValueError("MinIO client not configured")

        # 解析 MinIO URL
        # minio://bucket/path/to/image.jpg -> bucket, path/to/image.jpg
        url_parts = minio_url.replace("minio://", "").split("/", 1)
        bucket = url_parts[0] if len(url_parts) > 0 else self.minio_bucket
        object_name = url_parts[1] if len(url_parts) > 1 else ""

        # 从 MinIO 获取对象
        response = self.minio_client.get_object(bucket, object_name)
        image_data = response.read()
        response.close()
        response.release_conn()

        # 转换为 PIL Image
        image = Image.open(BytesIO(image_data))
        return image.convert("RGB")

    def _load_from_url(self, url: str) -> Image.Image:
        """
        从 HTTP URL 加载图像

        Args:
            url: HTTP/HTTPS URL

        Returns:
            PIL Image 对象
        """
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        image = Image.open(BytesIO(response.content))
        return image.convert("RGB")

    def _load_from_local(self, file_path: str) -> Image.Image:
        """
        从本地文件系统加载图像

        Args:
            file_path: 文件路径（绝对路径或相对于 local_image_root 的路径）

        Returns:
            PIL Image 对象
        """
        # 如果路径包含 bucket 名称（如 bfr-ai-files/xxx），尝试从 MinIO 加载
        if self.minio_client and '/' in file_path and not os.path.isabs(file_path):
            # 检查是否是 bucket/object 格式
            parts = file_path.split('/', 1)
            if len(parts) == 2 and parts[0] == self.minio_bucket:
                try:
                    return self._load_from_minio(f"minio://{file_path}")
                except Exception as e:
                    logger.debug(f"Failed to load from MinIO, trying local: {e}")

        # 如果是相对路径且配置了 local_image_root，则拼接完整路径
        if not os.path.isabs(file_path) and self.local_image_root:
            file_path = os.path.join(self.local_image_root, file_path)

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Image file not found: {file_path}")

        image = Image.open(file_path)
        return image.convert("RGB")
