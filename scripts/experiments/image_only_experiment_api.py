"""Expose the existing image endpoint against a process-local experiment index."""

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from csrcqsf.modules.railway_parts.routes.search_routes import search_v2_by_image
from csrcqsf.modules.railway_parts.vector_search.config.env_config import get_config


app = FastAPI(title='Isolated image experiment')


@app.get('/health')
async def health():
    config = get_config()
    return {'status': 'ok', 'collection': config.siglip_collection_name,
            'group_by_item': config.siglip_group_by_item}


@app.post('/railway/parts/v2/search/image')
async def image_search(
    file: list[UploadFile] = File(...), top_k: int = Form(20),
    search_mode: str = Form('siglip'), search_equipment: str = Form('web'),
):
    if search_mode != 'siglip':
        raise HTTPException(400, 'This experiment only accepts SigLIP images')
    # 直接复用主服务图像接口的多图融合与配件聚合，只在当前进程选择独立实验库。
    result = await search_v2_by_image(file=file, top_k=top_k,
                                    search_mode=search_mode, search_equipment=search_equipment)
    return {'status': 'success', 'data': result}
