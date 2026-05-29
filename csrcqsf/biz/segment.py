import base64
from typing import List
import numpy as np
import os
from csrcqsf.api_models import OCRResult, PointAndText, Point
from csrcqsf.settings import temp_dir, minio_bucket
from csrcqsf.data.minio import minio_instance
from globals_vars import logger
from csrcqsf.logger import CodeTimer
from bfrcommon.snowflake import get_id
from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager
from csrcqsf.biz.model_client import get_model_client


class SegmentBiz:

    @classmethod
    async def init(cls):
        logger.info("SegmentBiz: 模型已迁移至模型服务，本地不再加载")

    @classmethod
    async def mask(cls, file_url: str):
        image = await RailwayPartsManager.get_image_from_oss(file_url)

        with CodeTimer(name='图像分割计算(远程)'):
            client = get_model_client()
            image_embedding = await client.sam_embedding(image)

        mask_file_name = f'{get_id()}.npy'
        mask_file_path = os.path.join(temp_dir, mask_file_name)
        np.save(mask_file_path, image_embedding)

        minio_instance.upload_file(
            minio_bucket, mask_file_name, mask_file_path)
        os.remove(mask_file_path)
        return mask_file_name

    @classmethod
    async def front_end_ocr(cls, file_url):
        image = await RailwayPartsManager.get_image_from_oss(file_url)

        with CodeTimer(name='图片文字识别(远程)'):
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
