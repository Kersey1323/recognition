"""
Collection 管理器
"""
from typing import List, Dict
from pymilvus import MilvusClient, DataType

from csrcqsf.modules.railway_parts.vector_search.storage.milvus_client import (
    MilvusConnectionManager,
)
from csrcqsf.modules.railway_parts.vector_search.utils.logger import setup_logger

logger = setup_logger(__name__)


class CollectionManager:
    """Collection 管理器"""

    def __init__(self, host: str = "localhost", port: int = 19530):
        """
        初始化 Collection 管理器

        Args:
            host: Milvus 服务器地址
            port: Milvus 服务器端口
        """
        self.client = MilvusConnectionManager.get_client(host, port)

    def collection_exists(self, collection_name: str) -> bool:
        """
        检查 Collection 是否存在

        Args:
            collection_name: Collection 名称

        Returns:
            是否存在
        """
        return self.client.has_collection(collection_name)

    def get_collection_entity_count(self, collection_name: str) -> int:
        """
        获取 collection 中的实体总数。

        Args:
            collection_name: Collection 名称

        Returns:
            实体总数；如果 collection 不存在则返回 0
        """
        if not self.collection_exists(collection_name):
            return 0

        stats = self.client.get_collection_stats(collection_name=collection_name)
        return int(stats.get("row_count", 0))

    def collection_has_field(self, collection_name: str, field_name: str) -> bool:
        """
        检查 collection schema 是否包含指定字段。

        Args:
            collection_name: Collection 名称
            field_name: 字段名

        Returns:
            是否包含该字段；collection 不存在时返回 False
        """
        if not self.collection_exists(collection_name):
            return False

        description = self.client.describe_collection(collection_name=collection_name)
        for field in description.get("fields", []):
            name = field.get("name") or field.get("field_name")
            if name == field_name:
                return True
        return False

    def iter_collection_item_ids(self, collection_name: str, batch_size: int = 1000) -> set[int]:
        """
        遍历 collection 中所有去重后的 item_id。

        Args:
            collection_name: Collection 名称
            batch_size: 分批查询大小

        Returns:
            item_id 集合；如果 collection 不存在则返回空集合
        """
        if not self.collection_exists(collection_name):
            return set()

        item_ids: set[int] = set()
        iterator = self.client.query_iterator(
            collection_name=collection_name,
            filter="item_id >= 0",
            output_fields=["item_id"],
            batch_size=batch_size,
        )

        try:
            if hasattr(iterator, "next"):
                while True:
                    batch = iterator.next()
                    if len(batch) == 0:
                        break
                    for row in batch:
                        value = row.get("item_id")
                        if value is not None:
                            item_ids.add(int(value))
            else:
                for batch in iterator:
                    for row in batch:
                        value = row.get("item_id")
                        if value is not None:
                            item_ids.add(int(value))
        finally:
            if hasattr(iterator, "close"):
                iterator.close()

        return item_ids

    def get_collection_item_counts(self, collection_name: str, batch_size: int = 1000) -> dict[int, int]:
        """
        统计 collection 中每个 item_id 对应的记录数。

        Args:
            collection_name: Collection 名称
            batch_size: 分批查询大小

        Returns:
            item_id -> 记录数；如果 collection 不存在则返回空字典
        """
        if not self.collection_exists(collection_name):
            return {}

        counts: dict[int, int] = {}
        iterator = self.client.query_iterator(
            collection_name=collection_name,
            filter="item_id >= 0",
            output_fields=["item_id"],
            batch_size=batch_size,
        )

        try:
            if hasattr(iterator, "next"):
                while True:
                    batch = iterator.next()
                    if len(batch) == 0:
                        break
                    for row in batch:
                        value = row.get("item_id")
                        if value is not None:
                            item_id = int(value)
                            counts[item_id] = counts.get(item_id, 0) + 1
            else:
                for batch in iterator:
                    for row in batch:
                        value = row.get("item_id")
                        if value is not None:
                            item_id = int(value)
                            counts[item_id] = counts.get(item_id, 0) + 1
        finally:
            if hasattr(iterator, "close"):
                iterator.close()

        return counts

    def get_collection_item_image_ids(
        self,
        collection_name: str,
        batch_size: int = 1000,
    ) -> dict[int, set[int]]:
        """
        按 item_id 汇总 collection 中的源 image_id 集合。

        同一张源图即使存在多个 image_variant，也只保留一个 image_id。
        """
        if not self.collection_exists(collection_name):
            return {}

        item_images: dict[int, set[int]] = {}
        iterator = self.client.query_iterator(
            collection_name=collection_name,
            filter="item_id >= 0",
            output_fields=["item_id", "image_id"],
            batch_size=batch_size,
        )

        try:
            if hasattr(iterator, "next"):
                while True:
                    batch = iterator.next()
                    if len(batch) == 0:
                        break
                    for row in batch:
                        item_id = row.get("item_id")
                        image_id = row.get("image_id")
                        if item_id is None or image_id is None:
                            continue
                        item_images.setdefault(int(item_id), set()).add(int(image_id))
            else:
                for batch in iterator:
                    for row in batch:
                        item_id = row.get("item_id")
                        image_id = row.get("image_id")
                        if item_id is None or image_id is None:
                            continue
                        item_images.setdefault(int(item_id), set()).add(int(image_id))
        finally:
            if hasattr(iterator, "close"):
                iterator.close()

        return item_images

    def get_collection_image_records(
        self,
        collection_name: str,
        item_id: int,
        batch_size: int = 1000,
    ) -> dict[int, str]:
        """
        查询 collection 中指定 item_id 的 image_id -> image_url 映射。

        Args:
            collection_name: Collection 名称
            item_id: 配件 ID
            batch_size: 分批查询大小

        Returns:
            image_id -> image_url；如果 collection 不存在则返回空字典
        """
        if not self.collection_exists(collection_name):
            return {}

        images: dict[int, str] = {}
        iterator = self.client.query_iterator(
            collection_name=collection_name,
            filter=f"item_id == {int(item_id)}",
            output_fields=["image_id", "image_url"],
            batch_size=batch_size,
        )

        try:
            if hasattr(iterator, "next"):
                while True:
                    batch = iterator.next()
                    if len(batch) == 0:
                        break
                    for row in batch:
                        image_id = row.get("image_id")
                        if image_id is None:
                            continue
                        images[int(image_id)] = row.get("image_url", "")
            else:
                for batch in iterator:
                    for row in batch:
                        image_id = row.get("image_id")
                        if image_id is None:
                            continue
                        images[int(image_id)] = row.get("image_url", "")
        finally:
            if hasattr(iterator, "close"):
                iterator.close()

        return images

    def get_collection_records_by_item_ids(
        self,
        collection_name: str,
        item_ids: list[int],
        *,
        output_fields: list[str],
        batch_size: int = 1000,
    ) -> list[dict]:
        """一次查询多个配件的 collection 记录，供列表页批量聚合索引状态。"""
        normalized_item_ids = sorted({int(item_id) for item_id in item_ids})
        if not normalized_item_ids or not self.collection_exists(collection_name):
            return []

        rows: list[dict] = []
        item_id_filter = ",".join(str(item_id) for item_id in normalized_item_ids)
        iterator = self.client.query_iterator(
            collection_name=collection_name,
            filter=f"item_id IN [{item_id_filter}]",
            output_fields=output_fields,
            batch_size=batch_size,
        )

        try:
            if hasattr(iterator, "next"):
                while True:
                    batch = iterator.next()
                    if len(batch) == 0:
                        break
                    rows.extend(batch)
            else:
                for batch in iterator:
                    rows.extend(batch)
        finally:
            if hasattr(iterator, "close"):
                iterator.close()

        return rows

    def delete_by_item_id(self, collection_name: str, item_id: int) -> int:
        """
        删除指定 item_id 在 collection 中的全部记录。

        Args:
            collection_name: Collection 名称
            item_id: 配件 ID

        Returns:
            删除记录数；如果 collection 不存在则返回 0
        """
        if not self.collection_exists(collection_name):
            return 0

        result = self.client.delete(
            collection_name=collection_name,
            filter=f"item_id == {int(item_id)}",
        )
        return int(result.get("delete_count", 0))

    def delete_by_item_image_id(self, collection_name: str, item_id: int, image_id: int) -> int:
        """
        删除指定 item_id + image_id 在 collection 中的记录。

        Args:
            collection_name: Collection 名称
            item_id: 配件 ID
            image_id: 图片 ID

        Returns:
            删除记录数；如果 collection 不存在则返回 0
        """
        if not self.collection_exists(collection_name):
            return 0

        result = self.client.delete(
            collection_name=collection_name,
            filter=f"item_id == {int(item_id)} and image_id == {int(image_id)}",
        )
        return int(result.get("delete_count", 0))

    def drop_collection(self, collection_name: str):
        """
        删除 Collection（谨慎使用）

        Args:
            collection_name: Collection 名称
        """
        if self.collection_exists(collection_name):
            self.client.drop_collection(collection_name)
            logger.warning(f"Collection dropped: {collection_name}")

    def create_siglip_collection(
        self,
        collection_name: str,
        vector_dim: int = 1152
    ) -> bool:
        """
        创建 SigLIP Collection

        Args:
            collection_name: Collection 名称
            vector_dim: 向量维度

        Returns:
            是否创建成功
        """
        if self.collection_exists(collection_name):
            logger.info(f"Collection already exists: {collection_name}")
            return False

        logger.info(f"Creating SigLIP collection: {collection_name}")

        # 定义 Schema
        schema = MilvusClient.create_schema(
            auto_id=True,
            enable_dynamic_field=False
        )

        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="item_id", datatype=DataType.INT64)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=200)
        schema.add_field(field_name="item_code", datatype=DataType.VARCHAR, max_length=100)
        schema.add_field(field_name="image_id", datatype=DataType.INT64)
        schema.add_field(field_name="image_variant", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="image_url", datatype=DataType.VARCHAR, max_length=500)
        schema.add_field(field_name="description", datatype=DataType.VARCHAR, max_length=1000)
        schema.add_field(field_name="image_vector", datatype=DataType.FLOAT_VECTOR, dim=vector_dim)
        schema.add_field(field_name="text_vector", datatype=DataType.FLOAT_VECTOR, dim=vector_dim)
        schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=50)

        # 定义索引
        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="image_vector",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            params={"nlist": 1024}
        )
        index_params.add_index(
            field_name="text_vector",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            params={"nlist": 1024}
        )

        # 创建 Collection
        self.client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params
        )

        logger.info(f"SigLIP collection created: {collection_name}")
        return True

    def create_dinov2_collection(
        self,
        collection_name: str,
        vector_dim: int = 1024
    ) -> bool:
        """
        创建 DINOv2 Collection

        Args:
            collection_name: Collection 名称
            vector_dim: 向量维度

        Returns:
            是否创建成功
        """
        if self.collection_exists(collection_name):
            logger.info(f"Collection already exists: {collection_name}")
            return False

        logger.info(f"Creating DINOv2 collection: {collection_name}")

        # 定义 Schema
        schema = MilvusClient.create_schema(
            auto_id=True,
            enable_dynamic_field=False
        )

        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="item_id", datatype=DataType.INT64)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=200)
        schema.add_field(field_name="item_code", datatype=DataType.VARCHAR, max_length=100)
        schema.add_field(field_name="image_id", datatype=DataType.INT64)
        schema.add_field(field_name="image_variant", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="image_url", datatype=DataType.VARCHAR, max_length=500)
        schema.add_field(field_name="global_vector", datatype=DataType.FLOAT_VECTOR, dim=vector_dim)
        schema.add_field(field_name="patch_tokens", datatype=DataType.FLOAT_VECTOR, dim=vector_dim)
        schema.add_field(field_name="patch_token_key", datatype=DataType.VARCHAR, max_length=500)
        schema.add_field(field_name="patch_tokens_path", datatype=DataType.VARCHAR, max_length=500)
        schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=50)

        # 定义索引
        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="global_vector",
            index_type="IVF_FLAT",
            metric_type="L2",
            params={"nlist": 1024}
        )
        index_params.add_index(
            field_name="patch_tokens",
            index_type="IVF_FLAT",
            metric_type="L2",
            params={"nlist": 1024}
        )

        # 创建 Collection
        self.client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params
        )

        logger.info(f"DINOv2 collection created: {collection_name}")
        return True

    def insert_siglip_records(
        self,
        collection_name: str,
        records: List[Dict]
    ) -> List[int]:
        """
        批量插入 SigLIP 记录

        Args:
            collection_name: Collection 名称
            records: 记录列表

        Returns:
            插入的记录 ID 列表
        """
        result = self.client.insert(
            collection_name=collection_name,
            data=records
        )
        logger.debug(f"Inserted {len(records)} records to {collection_name}")
        return result["ids"]

    def insert_dinov2_records(
        self,
        collection_name: str,
        records: List[Dict]
    ) -> List[int]:
        """
        批量插入 DINOv2 记录

        Args:
            collection_name: Collection 名称
            records: 记录列表

        Returns:
            插入的记录 ID 列表
        """
        result = self.client.insert(
            collection_name=collection_name,
            data=records
        )
        logger.debug(f"Inserted {len(records)} records to {collection_name}")
        return result["ids"]
