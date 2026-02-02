from bfrcommon.minio import Bucket
from csrcqsf.settings import minio_bucket
import traceback
from csrcqsf.logger import logger
from csrcqsf.settings import ai_settings

minio_instance = Bucket(ai_settings.minio_url,
                        'root', 'REMOVED_CREDENTIAL')


async def create_minio_bucket():
    try:
        if minio_instance.exists_bucket(minio_bucket) == False:
            minio_instance.create_bucket(minio_bucket, True)
    except Exception as e:
        logger.error(f'创建桶出错:err{e}{traceback.format_exc()}')
