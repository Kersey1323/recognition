import base64
import os
from typing import List

import numpy as np

from bfrcommon.snowflake import get_id
from csrcqsf.core.logger import CodeTimer
from csrcqsf.core.settings import minio_bucket, temp_dir
from csrcqsf.infra.external.model_client import get_model_client
from csrcqsf.infra.storage.minio import minio_instance
from csrcqsf.modules.image.schemas import OCRResult, Point, PointAndText
from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager
from csrcqsf.core.logging_config import logger


class SegmentBiz:
    """向小模型服务转发分割和 OCR 请求，并管理产生的中间文件。"""
    @classmethod
    async def init(cls):
        logger.info("SegmentBiz: 模型已迁移至模型服务，本地不再加载")

    @classmethod
    async def mask(cls, file_url: str):
        # SAM embedding 作为后续交互式分割中间结果保存，不在主服务加载模型。
        image = await RailwayPartsManager.get_image_from_oss(file_url)

        with CodeTimer(name="图像分割计算(远程)"):
            client = get_model_client()
            image_embedding = await client.sam_embedding(image)

        mask_file_name = f"{get_id()}.npy"
        mask_file_path = os.path.join(temp_dir, mask_file_name)
        np.save(mask_file_path, image_embedding)

        minio_instance.upload_file(minio_bucket, mask_file_name, mask_file_path)
        # 本地文件上传完成即删除，长期存储统一由 MinIO 承担。
        os.remove(mask_file_path)
        return mask_file_name

    @classmethod
    async def front_end_ocr(cls, file_url):
        """将模型服务 OCR 坐标转换为前端使用的点集结构。"""
        image = await RailwayPartsManager.get_image_from_oss(file_url)

        with CodeTimer(name="图片文字识别(远程)"):
            client = get_model_client()
            results = await client.ocr_recognize(image)

        res = OCRResult()
        for item in results:
            point = PointAndText()
            for p in item.get("points", []):
                point.points_list.append(Point(x=p["x"], y=p["y"]))
            point.txt = item.get("text", "")
            res.res.append(point)
        return res
