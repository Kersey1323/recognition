import base64
from typing import List
import cv2
import numpy as np
import torch
from ultralytics.engine.results import Results
from ultralytics import SAM
import time
from ultralytics.engine.results import Results
from csrcqsf.api_models import OCRResult, PointAndText, Point
from csrcqsf.settings import SAM_MODEL, temp_dir, minio_bucket, make_sure_models
import os
from csrcqsf.data.minio import minio_instance
from anyio.to_thread import run_sync
from segment_anything import sam_model_registry, SamPredictor, SamAutomaticMaskGenerator
from globals_vars import logger
from csrcqsf.logger import CodeTimer
from bfrcommon.snowflake import get_id
from csrcqsf.biz.railwayparts.parts import RailwayPartsManager
from rapidocr import EngineType, LangDet, LangRec, ModelType as OCRModelType, OCRVersion, RapidOCR

device = "cuda" if torch.cuda.is_available() else "cpu"


class SegmentBiz:
    sam_model: SAM = None
    engine = None
    predictor: SamPredictor = None

    @classmethod
    def _build_ocr_engine(cls):
        return RapidOCR(params={
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Det.lang_type": LangDet.CH,
            "Det.model_type": OCRModelType.MOBILE,
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.limit_side_len": 1080,
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Rec.lang_type": LangRec.CH,
            "Rec.model_type": OCRModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Global.min_height": 10,
            "Global.width_height_ratio": -1,
            "Global.use_cls": False,
            "EngineConfig.onnxruntime.intra_op_num_threads": 8,
            "EngineConfig.onnxruntime.inter_op_num_threads": 4,
            "EngineConfig.onnxruntime.enable_cpu_mem_arena": True,
        })

    @classmethod
    def get_ocr_engine(cls):
        if cls.engine is None:
            cls.engine = cls._build_ocr_engine()
        return cls.engine

    @classmethod
    async def init(cls):
        await make_sure_models()
        model_type = "vit_h"
        cls.sam_model = sam_model_registry[model_type](checkpoint=SAM_MODEL)
        if device == 'cpu':
            logger.info('没有发现显卡，使用cpu计算')
        else:
            logger.info('找到显卡，使用cuda计算')
        cls.sam_model.to(device)
        cls.predictor = SamPredictor(cls.sam_model)

    @classmethod
    def _mask(cls, image):
        with CodeTimer(name='图像分割计算'):
            cls.predictor.set_image(image)
            image_embedding = cls.predictor.get_image_embedding().cpu().numpy()
            cls.predictor.reset_image()

        mask_file_name = f'{get_id()}.npy'
        mask_file_path = os.path.join(temp_dir, mask_file_name)
        np.save(mask_file_path, image_embedding)

        minio_instance.upload_file(
            minio_bucket, mask_file_name, mask_file_path)
        os.remove(mask_file_path)
        return mask_file_name

    @classmethod
    async def mask(cls, file_url: str):
        image = await RailwayPartsManager.get_image_from_oss(file_url)
        return await run_sync(cls._mask, image)

    @classmethod
    def _front_end_ocr(cls, image):
        res = OCRResult()
        with CodeTimer(name='图片文字识别'):
            result = cls.get_ocr_engine()(image)
            if result.boxes is None:
                return res
            for index, row in enumerate(result.boxes):

                point = PointAndText()
                for element in row:
                    point.points_list.append(Point(
                        x=element[0],
                        y=element[1]
                    ))
                    point.txt = result.txts[index]

                res.res.append(point)
        return res

    @classmethod
    async def front_end_ocr(cls, file_url):
        image = await RailwayPartsManager.get_image_from_oss(file_url)
        return await run_sync(cls._front_end_ocr, image)
