from pymilvus.client.embedding_list import EmbeddingList
from pymilvus import AnnSearchRequest, MilvusClient, DataType
from csrcqsf.biz.railwayparts.milvus import ColletionEnum, MilvusManager
from csrcqsf.biz.railwayparts.parts import RailwayPartsManager
from csrcqsf.data.milvus import milvus_client
# schema = MilvusClient.create_schema()

# # add the primary field to the collection
# schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True, auto_id=True)

# # add some scalar fields to the collection
# schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=512)
# schema.add_field(field_name="author", datatype=DataType.VARCHAR, max_length=512)
# schema.add_field(field_name="year_of_publication", datatype=DataType.INT64)

# # add a vector field to the collection
# schema.add_field(field_name="title_vector", datatype=DataType.FLOAT_VECTOR, dim=5)

# # Create a struct schema
# struct_schema = MilvusClient.create_struct_field_schema()

# # add a scalar field to the struct
# struct_schema.add_field("text", DataType.VARCHAR, max_length=65535)
# struct_schema.add_field("chapter", DataType.VARCHAR, max_length=512)

# # add a vector field to the struct with mmap enabled
# struct_schema.add_field("text_vector", DataType.FLOAT_VECTOR, mmap_enabled=True, dim=5)

# # reference the struct schema in an Array field with its
# # element type set to `DataType.STRUCT`
# schema.add_field("chunks", datatype=DataType.ARRAY, element_type=DataType.STRUCT,
#                     struct_schema=struct_schema, max_capacity=1000)

# index_params = MilvusClient.prepare_index_params()

# # Create an index for the vector field in the collection
# index_params.add_index(
#     field_name="title_vector",
#     index_type="AUTOINDEX",
#     metric_type="L2",
# )

# # Create an index for the vector field in the element Struct
# index_params.add_index(
#     field_name="chunks[text_vector]",
#     index_type="AUTOINDEX",
#     metric_type="MAX_SIM_COSINE",
# )

# milvus_client.create_collection(
#     collection_name="my_collection",
#     schema=schema,
#     index_params=index_params
# )

# # Sample data
data = {
    'title': 'ASDASD',
    'title_vector': [0.1, 0.2, 0.3, 0.4, 0.5],
    'author': 'Henry David Thoreau',
    'year_of_publication': 1845,
    'chunks': [
        {
            'text': 'When I wrote the following pages, or rather the bulk of them...',
            'text_vector': [0.3, 0.2, 0.3, 0.2, 0.5],
            'chapter': 'Economy',
        },
        {
            'text': 'I would fain say something, not so much concerning the Chinese and...',
            'text_vector': [0.7, 0.4, 0.2, 0.7, 0.8],
            'chapter': 'Economy'
        }
    ]
}


# # each query embedding list triggers a single search
# embeddingList1 = EmbeddingList()
# embeddingList1.add([0.2, 0.9, 0.4, -0.3, 0.2])

# embeddingList2 = EmbeddingList()
# embeddingList2.add([-0.2, -0.2, 0.5, 0.6, 0.9])
# embeddingList2.add([-0.4, 0.3, 0.5, 0.8, 0.2])

# a search with multiple embedding lists
# results = milvus_client.search(
#     collection_name="test4",
#     data=[ embeddingList1, embeddingList2 ],
#     anns_field="chunks[text_vector]",
#     search_params={"metric_type": "MAX_SIM_COSINE"},
#     limit=3,
#     output_fields=["chunks[text]"]
# )

# print(results)

# # insert data
# milvus_client.insert(
#     collection_name="my_collection",
#     data=[data]
# )


image = RailwayPartsManager.get_image_from_oss(
    "bfr-ai-files/file_1-1991324749434720256.png")
tensor = MilvusManager.extract_image_tensor(image)
query_vector_image = EmbeddingList()
query_vector_image.add(tensor)
from pymilvus import Function, FunctionType
# feature_vector = MilvusManager.embedding_encode("123")
# query_vector_image = EmbeddingList()
# query_vector_image.add(feature_vector)
# a search with a single embedding list

search_request = []
query_vector_feature = EmbeddingList()
query_vector_feature.add(MilvusManager.embedding_encode('123'))
# res = milvus_client.search(
#     collection_name='test3',
#     data=[query_vector_image],
#     anns_field="images[image_vector]",
#     search_params={"metric_type": "MAX_SIM_L2",
#                    "params": {
#                        "nprobe": 64,  # 核心参数，指定要搜索的桶的数量
#                     #    "radius": 1.0,        # 可选：范围搜索的半径
#                     #    "range_filter": 0.8    # 可选：范围搜索的过滤器
#                    }
#                    },
#     limit=3,
#     output_fields=["images[filename]", "item_id"]
# )

search_param_1 = {
                "data": [query_vector_image],
                "anns_field": "images[image_vector]",
                "param": {"nprobe": 10},
                #"param": {"metric_type": "MAX_SIM_L2"},
                 "limit": 10
            }
search_request.append(AnnSearchRequest(**search_param_1))

search_param_2 = {
                "data": [query_vector_feature],
                "anns_field": "features[feature_vector]",
                "param": {"nprobe": 10},
               # "param": {"metric_type": "MAX_SIM_L2"},
                "limit": 10
            }
   
search_request.append(AnnSearchRequest(**search_param_2))
ranker = Function(
        name="rrf",
        input_field_names=[],  # Must be an empty list
        function_type=FunctionType.RERANK,
        params={
            "reranker": "rrf",
            "k": 100  # Optional
        }
    )

res = milvus_client.query('test7',filter='ARRAY_LENGTH(images) == 0',output_fields=["item_id"])

print(res)

# res = milvus_client.hybrid_search(
#             collection_name='test7',
#             reqs=search_request,
#             ranker=ranker,
#             limit=5,
#             output_fields=["item_id"]
# )

# print(res)
