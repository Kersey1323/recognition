"""当前在线询码语义索引的本地文档镜像。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BIGINT, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from csrcqsf.infra.db.main_db import PlainBase


class InquiryTextIndexDocument(PlainBase):
    """记录当前 Milvus 别名实际可检索的询码描述。"""

    __tablename__ = "inquiry_text_index_document"
    __table_args__ = (
        Index("ix_inquiry_text_index_document_item", "item_id"),
        Index("ix_inquiry_text_index_document_task", "index_task_id"),
    )

    document_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    history_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    inquiry_id: Mapped[str] = mapped_column(String(64), nullable=False)
    item_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    item_code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    index_task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
