
from pydantic import BaseModel
from csrcqsf.biz.railwayparts.parts import RailwayPartsManager
from csrcqsf.data.milvus import milvus_client
from pymilvus import MilvusClient, DataType
from csrcqsf.biz.railwayparts.milvus import FeaturesIndex, ImageIndex, MilvusManager
from typing import Any
from csrcqsf.biz.railwayparts.milvus import ColletionEnum
from bfrcommon.snowflake import get_id
from csrcqsf.data.pg import SessionLocal
from csrcqsf.models.item import Items
from pymilvus.client.embedding_list import EmbeddingList
schema = MilvusClient.create_schema(
    enable_dynamic_field=True,
    auto_id=False
)

collection_name = 'new_index_3'


def create_index():
    schema = MilvusClient.create_schema(
        enable_dynamic_field=True,
        auto_id=False
    )
    schema.add_field(
        field_name="id", datatype=DataType.INT64, is_primary=True)

    schema.add_field(field_name="item_id",
                     datatype=DataType.INT64,  is_primary=False)

    schema.add_field(field_name="item_name",
                     datatype=DataType.VARCHAR, max_length=2000)

    schema.add_field(field_name='image_url',
                     datatype=DataType.VARCHAR, max_length=2000)

    schema.add_field(field_name="image_vector",
                     datatype=DataType.FLOAT_VECTOR, dim=512, mmap_enabled=True)

    index_params = milvus_client.prepare_index_params()

    index_params.add_index(
        field_name="image_vector",
        index_type="HNSW",
        metric_type="COSINE",
        params={
            "M": 64,  # Maximum number of neighbors each node can connect to in the graph
            # Number of candidate neighbors considered for connection during index construction
            "efConstruction": 100
        }  # Index building params

    )
    milvus_client.drop_collection(collection_name)
    milvus_client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params
    )


class NewIndex(BaseModel):
    id: int
    item_id: int
    item_name: str
    image_url: str
    image_vector: Any


async def sync_data():
    index_list = await MilvusManager.list_item_index()

    async with SessionLocal() as session:
        item_id_list = [k for k, _ in index_list.items()]
        item_dict: dict[int, Items] = {}
        async for item in Items.get_item_by_id_list(session, item_id_list):
            item_dict[item.id] = item

    for _, image_index in index_list.items():
        for index,image in enumerate(image_index.images):
            image_data = RailwayPartsManager.get_image_from_oss(image.filename)
            tensor = await MilvusManager.extract_image_tensor(image_data)
            image_index.images[index].image_vector = tensor
        milvus_client.upsert(ColletionEnum.NEWCOLLECTION.value,image_index.dict())


async def search(filename: str):
    image = RailwayPartsManager.get_image_from_oss(filename)
    tensor = await MilvusManager.extract_image_tensor(image)
    query_vector_image = EmbeddingList()

    query_vector_image.add(tensor)

    res = milvus_client.search(
        collection_name=collection_name,
        anns_field="image_vector",
        data=[tensor],
        limit=3,
        search_params={"metric_type": "COSINE", "params": {
            "ef": 10,
        }},
        output_fields=["item_name", "image_url"]
    )
    print(res)

import cv2

def search_v2(item_id: int):
    index = milvus_client.query(collection_name, output_fields=[
                                "image_vector", "image_url"], filter=f'item_id == {item_id}')

    for d in index:
        res = milvus_client.search(
            collection_name=collection_name,
            anns_field="image_vector",
            data=[d['image_vector']],
            limit=3,
            search_params={"metric_type": "COSINE", "params": {
                "ef": 10,
            }},
            output_fields=["item_name", "image_url"]
        )
        print(res)
        print('==========================================')
        image = RailwayPartsManager.get_image_from_oss(d['image_url'])
        cv2.imwrite('test.png',image)
        tensor = MilvusManager.extract_image_tensor(image)
        res2 = milvus_client.search(
            collection_name=collection_name,
            anns_field="image_vector",
            data=[tensor],
            limit=3,
            search_params={"metric_type": "COSINE", "params": {
                "ef": 10,
            }},
            output_fields=["item_name", "image_url"]
        )
        print(res2)


def search_v3(file_name: str):
    image = RailwayPartsManager.get_image_from_oss(file_name)
    tensor = MilvusManager.extract_image_tensor(image)
    query_vector_feature = EmbeddingList()
    query_vector_feature.add(tensor)
    res = milvus_client.search(
            collection_name="PARTS_INDEX",
            anns_field="images[image_vector]",
            data=[query_vector_feature],
            limit=1,
            search_params={"metric_type": "MAX_SIM_L2"},
            output_fields=["item_id", "images"]
    )
    print(res)
# from anyio import run
# create_index()
# run(sync_data)
#search('bfr-ai-files/file_1-1991088472739287040.png')
search_v3('bfr-ai-files/file_1-1991071987404902400.png')
