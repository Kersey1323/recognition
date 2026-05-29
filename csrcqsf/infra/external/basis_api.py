import json
import os

import grpc
from api.basis.fileTask_pb2 import SendFileTaskRequest
from api.basis.fileTask_pb2_grpc import FileTaskStub
from api.basis.message_pb2 import CreateMessageRequest, MessagePayLoad
from api.basis.message_pb2_grpc import MessageStub
from bfrcommon.file import file_ext
from bfrcommon.snowflake import get_id
from csrcqsf.core.settings import ai_settings, minio_bucket
from csrcqsf.infra.storage.minio import minio_instance
from globals_vars import logger


class GrpcClient:

    def __init__(self):
        # channel 和 stub 初始化
        self.channel = grpc.insecure_channel(ai_settings.basis_api_grpc_url,
        options=[
            # 心跳间隔10秒
            ('grpc.keepalive_time_ms',  10000),
            # 心跳超时5秒
            ('grpc.keepalive_timeout_ms',  5000),
            # 初始重连间隔
            ('grpc.initial_reconnect_backoff_ms',  1000),
            # 最大重连间隔
            ('grpc.max_reconnect_backoff_ms',  16000),
            ('grpc.enable_retries', 1),
            ('grpc.service_config', """{
            "retryPolicy": {
                "maxAttempts": 5,
                "initialBackoff": "0.3s",
                "maxBackoff": "10s",
                "backoffMultiplier": 2,
                "retryableStatusCodes": ["UNAVAILABLE", "INTERNAL"]
            }
        }"""),
                                                 ],

                                             )
        self.file_sub = FileTaskStub(channel=self.channel)
        self.message_sub = MessageStub(channel=self.channel)
        logger.info('grpc_client init')
        # self.socketio_sub =

    def send_file_task(self, file_name: str,size:int, file_to_user_id: int, name: str):
        """
        file_name 在bucket里的文件名
        """
        # if os.path.exists(file_full_path) == False:
        #     raise Exception(f'文件{file_full_path}不存在')

        # base_name = os.path.basename(file_full_path)
        ext = file_ext(file_name)
        # minio_instance.upload_file(
        #     minio_bucket, base_name, file_full_path)

        # size = os.path.getsize(file_full_path)
        item = SendFileTaskRequest.FileTaskItem(
            code=str(get_id()),
            name=name,
            status=1,
            size=size,
            process=0,
            type=ext[1:],
            source='科研数据分析',
            data=f'{minio_bucket}/{file_name}'
        )
        req = SendFileTaskRequest(list=[item], userId=file_to_user_id)
        self.file_sub.SendFileTask(req)


grpc_client = GrpcClient()
