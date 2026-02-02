
from pydantic import BaseModel
from csrcqsf.data.milvus import milvus_client
from pymilvus import MilvusClient, DataType
from csrcqsf.biz.railwayparts.milvus import FeaturesIndex, ImageIndex, MilvusManager
schema = MilvusClient.create_schema(
    enable_dynamic_field=True,
    auto_id=False
)
schema.add_field(
    field_name="id", datatype=DataType.INT64, is_primary=True)

schema.add_field(field_name="item_id",
                 datatype=DataType.INT64,  is_primary=False)

schema.add_field(field_name="parent_item_info",
                 datatype=DataType.ARRAY, element_type=DataType.INT64, max_capacity=1000)

schema.add_field(field_name="vechile_info",
                 datatype=DataType.ARRAY, element_type=DataType.VARCHAR, max_capacity=1000, max_length=2000)

schema.add_field(field_name="created_at",
                 datatype=DataType.VARCHAR, max_length=2000)

image_struct_schema = MilvusClient.create_struct_field_schema()
image_struct_schema.add_field(field_name="image_id",
                              datatype=DataType.INT64, is_primary=False)
image_struct_schema.add_field(field_name="image_vector",
                              datatype=DataType.FLOAT_VECTOR, dim=512, mmap_enabled=True)
image_struct_schema.add_field(field_name='filename',
                              datatype=DataType.VARCHAR, max_length=20000)
image_struct_schema.add_field(field_name='image_index_created',
                              datatype=DataType.VARCHAR, max_length=20000)

schema.add_field("images", datatype=DataType.ARRAY, element_type=DataType.STRUCT,
                 struct_schema=image_struct_schema, max_capacity=1000)


struct_schema = MilvusClient.create_struct_field_schema()
struct_schema.add_field(
    "feature", DataType.VARCHAR, max_length=65535)
struct_schema.add_field(
    "feature_vector", DataType.FLOAT_VECTOR, mmap_enabled=True, dim=512)
struct_schema.add_field(field_name='feature_index_created',
                                datatype=DataType.VARCHAR, max_length=20000)

schema.add_field("features", datatype=DataType.ARRAY, element_type=DataType.STRUCT,
                    struct_schema=struct_schema, max_capacity=1000)

index_params = milvus_client.prepare_index_params()

index_params.add_index(
    field_name="item_id",
    index_type="AUTOINDEX"
)

index_params.add_index(
    field_name="images[image_vector]",
    index_type="AUTOINDEX",
    metric_type="MAX_SIM_L2",
)

index_params.add_index(
    field_name="parent_item_info",
    index_type="AUTOINDEX",
    index_name="parent_item_info_index"
)
index_params.add_index(
    field_name="vechile_info",
    index_type="AUTOINDEX",
    index_name="vechile_info_index"
)

index_params.add_index(
                field_name="features[feature_vector]",
                index_type="AUTOINDEX",
                metric_type="MAX_SIM_L2",
            )

connection_name = 'test7'
milvus_client.drop_collection(connection_name)
milvus_client.create_collection(
    collection_name=connection_name,
    schema=schema,
    index_params=index_params
)


class NewPartsImageIndex(BaseModel):
    item_id: int = 0
    id: int = 0
    images: list[ImageIndex] = []
    vechile_info: list[int] = []
    parent_item_info: list[int] = []
    created_at: str | None 


async def insert_data():
    index_list = await MilvusManager.list_item_index([1557989033974435840,1557989344063524864,1595250724919922688,1595250753344720896])

    for _,index in index_list.items():
        # new_index = NewPartsImageIndex()
        # new_index.item_id = index.item_id
        # new_index.id = index.id 
        # new_index.images = index.images
        # new_index.created_at = index.created_at
        if len(index.features)  ==0:
            fake_data = '124124'
            fake_vector_data = await MilvusManager.embedding_encode(fake_data)
            index.features.append(
                FeaturesIndex(
                    feature=fake_data,
                    feature_vector=fake_vector_data,
                    feature_index_created='2025-12-31'
                )
            )
        milvus_client.insert(
            connection_name, index.dict()
        )
from anyio import run 

run(insert_data)