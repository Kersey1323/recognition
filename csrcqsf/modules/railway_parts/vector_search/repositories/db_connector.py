"""
数据库连接器
"""
from typing import List, Dict, Optional
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from csrcqsf.modules.railway_parts.vector_search.utils.logger import setup_logger

logger = setup_logger(__name__)


class DatabaseConnector:
    """PostgreSQL 数据库连接器"""

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str
    ):
        """
        初始化数据库连接

        Args:
            host: 数据库主机
            port: 数据库端口
            database: 数据库名称
            user: 用户名
            password: 密码
        """
        # URL 编码用户名和密码，处理特殊字符
        encoded_user = quote_plus(user)
        encoded_password = quote_plus(password)
        connection_string = f"postgresql://{encoded_user}:{encoded_password}@{host}:{port}/{database}"
        self.engine = create_engine(connection_string, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine)
        logger.info(f"Database connection established: {host}:{port}/{database}")

    def fetch_items_with_images(
        self,
        item_ids: Optional[List[int]] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        读取零件信息及其关联图像

        Args:
            item_ids: 指定零件 ID 列表（可选）
            limit: 限制返回数量（可选）

        Returns:
            零件信息列表，每个零件包含其关联的图像列表
        """
        session = self.SessionLocal()
        try:
            # 构建查询 - 使用实际的 schema 和表名
            query = """
                SELECT
                    i.id as item_id,
                    i.item_name,
                    i.item_code,
                    COALESCE(i.item_name, '') as description,
                    img.id as image_id,
                    img.image_url
                FROM parts.item_info i
                LEFT JOIN parts.sgo_item_image_info img ON i.id = img.item_id
                WHERE img.image_url IS NOT NULL
                  AND img.is_deleted = 0
            """

            # 添加过滤条件
            if item_ids:
                placeholders = ','.join([':id' + str(i) for i in range(len(item_ids))])
                query += f" AND i.id IN ({placeholders})"

            query += " ORDER BY i.id, img.id"

            # 添加限制
            if limit:
                query += f" LIMIT :limit"

            # 执行查询
            params = {}
            if item_ids:
                for i, item_id in enumerate(item_ids):
                    params[f'id{i}'] = item_id
            if limit:
                params['limit'] = limit

            result = session.execute(text(query), params)
            rows = result.fetchall()

            # 组织数据结构
            items_dict = {}
            for row in rows:
                item_id = row.item_id
                if item_id not in items_dict:
                    items_dict[item_id] = {
                        'item_id': item_id,
                        'item_name': row.item_name or '',
                        'item_code': row.item_code or '',
                        'description': row.description or '',
                        'images': []
                    }

                if row.image_id:
                    items_dict[item_id]['images'].append({
                        'image_id': row.image_id,
                        'image_url': row.image_url
                    })

            items_list = list(items_dict.values())
            logger.info(f"Fetched {len(items_list)} items with images")
            return items_list

        finally:
            session.close()

    def mark_images_indexed(self, image_ids: List[int]):
        """
        标记图像已索引（可选功能，用于跟踪索引状态）

        Args:
            image_ids: 图像 ID 列表
        """
        if not image_ids:
            return

        session = self.SessionLocal()
        try:
            # 这里可以添加一个字段来标记图像已索引
            # 例如：UPDATE sgo_item_images SET indexed = true WHERE id IN (...)
            # 目前暂不实现，保留接口
            logger.debug(f"Marked {len(image_ids)} images as indexed")
        finally:
            session.close()

    def close(self):
        """关闭数据库连接"""
        self.engine.dispose()
        logger.info("Database connection closed")
