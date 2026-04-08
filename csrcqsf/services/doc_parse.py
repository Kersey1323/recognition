from fastapi import APIRouter, BackgroundTasks
from csrcqsf.biz.railwayparts.api_models import *
from bfrcommon.snowflake import get_id
from bfrcommon.common import date_to_str
from csrcqsf.models.sgo import SgoItemImages
from csrcqsf.settings import ai_settings
from csrcqsf.biz.doc_parse import DocBiz
from anyio.to_thread import run_sync
from bfrcommon.api_models import PageReq, PageRes
parts_docs_router = APIRouter(
    prefix="/railway/docs",
    tags=["docs"],
    # dependencies=[Depends(get_token_header)],
    responses={404: {"description": "Not found"}},
)


class CreateFileReq(BaseModel):
    file_name: str 
    file_url : str 

class ListFileReq(PageReq):
    query : str | None = Field(default='', description='搜索关键词', example='手册')
    
    class Config:
        json_schema_extra = {
            "example": {
                "page": 1,
                "pageSize": 20,
                "query": "手册"
            }
        }

class ListFileItem(BaseModel):
    file_name: str | None 
    file_id : str | None 
    table_num: int | None 
    created_date: str | None

class ListFileRes(PageRes):
    files: list[ListFileItem] = []


class DeleteFileReq(BaseModel):
    file_id : str 

class ListFileTableReq(PageReq):
    file_id : str = Field(description='文件ID', example='1990363621896622080')
    query: str | None = Field(default='', description='搜索关键词', example='')
    
    class Config:
        json_schema_extra = {
            "example": {
                "file_id": "1990363621896622080",
                "page": 1,
                "pageSize": 20,
                "query": ""
            }
        }

class ListFileTableItem(BaseModel):
    table_name: str | None 
    table_data: str | None 

class ListFileTableRes(PageRes):
    tables: list[ListFileTableItem] = []

class ExportFileTableToExcelReq(BaseModel):
    file_id : str 
    user_id: str


@parts_docs_router.post('/file',  tags=["docs"], summary='上传并解析配件手册', responses={
    200: {
        'model': str
    }
})
async def create_file(req: CreateFileReq):
    await DocBiz.create_file(req.file_name,req.file_url)


@parts_docs_router.post('/files',  tags=["docs"], summary='列出文件列表', responses={
    200: {
        'model': ListFileRes
    }
})
async def list_file(req: ListFileReq):
    files = await DocBiz.list_files(req.page,req.per_page,req.query)
    res = ListFileRes(
        total=files.total
    )
    for f in files.data:
        item = ListFileItem(
            file_name = f.file_name,
            file_url = f.file_url,
            file_id = str(f.id),
            table_num = f.table_num,
            created_date = date_to_str(f.time_created)
        )
        res.files.append(item)
    return res


@parts_docs_router.post('/file/tables',  tags=["docs"], summary='列出文件的表格数据', responses={
    200: {
        'model': ListFileTableRes
    }
})
async def list_file_tables(req: ListFileTableReq):
    

    tables = await DocBiz.list_tables(int(req.file_id),req.page,req.per_page,req.query)
    res = ListFileTableRes(
        total=tables.total
    )
    for t in tables.data:
        res.tables.append(
            ListFileTableItem(
                table_name=t.table_name,
                table_data=t.table_data
            )
        )

    return res



@parts_docs_router.post('/file/export',  tags=["docs"], summary='导出excel文件', responses={
    200: {
        'model': str
    }
})
async def list_file_tables(req: ExportFileTableToExcelReq):
    await DocBiz.write_to_excel(int(req.file_id),int(req.user_id))