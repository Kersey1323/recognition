from pydantic import BaseModel,Field

class SimpleSegmentReq(BaseModel):
    file_url: str 

class SimpleSegmentRes(BaseModel):
    mask : str = Field(default='',description='base64的mask')


class Point(BaseModel):
    x: float = 0
    y: float = 0

class PointAndText(BaseModel):
    points_list: list[Point] = []
    txt: str = ''

class OCRResult(BaseModel):
    res: list[PointAndText] = []


class FrontOCRReq(BaseModel):
    file_url: str 