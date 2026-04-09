from fastapi import APIRouter, BackgroundTasks
from csrcqsf.api_models import FrontOCRReq
from csrcqsf.biz.railwayparts.api_models import *
from bfrcommon.snowflake import get_id
from bfrcommon.common import date_to_str
from csrcqsf.settings import ai_settings
from csrcqsf.biz.segment import SegmentBiz
from csrcqsf.biz.railwayparts.parts import RailwayPartsManager
image_router = APIRouter(
    prefix="/images",
    tags=["image"],
    # dependencies=[Depends(get_token_header)],
    responses={404: {"description": "Not found"}},
)


@image_router.post('/ocr/front',  tags=["算法-OCR识别"], summary='获取ocr内容', responses={
    200: {
        'model': str
    }
})
async def front_image(req: FrontOCRReq):
    return await SegmentBiz.front_end_ocr(req.file_url)
