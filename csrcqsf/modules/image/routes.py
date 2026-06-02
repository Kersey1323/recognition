from fastapi import APIRouter

from csrcqsf.core.runtime import ensure_ocr_model_enabled
from csrcqsf.modules.image.schemas import FrontOCRReq
from csrcqsf.modules.image.services import SegmentBiz


image_router = APIRouter(
    prefix="/images",
    tags=["image"],
    responses={404: {"description": "Not found"}},
)


@image_router.post('/ocr/front', tags=["算法-OCR识别"], summary='获取ocr内容', responses={
    200: {
        'model': str
    }
})
async def front_image(req: FrontOCRReq):
    ensure_ocr_model_enabled()
    return await SegmentBiz.front_end_ocr(req.file_url)
