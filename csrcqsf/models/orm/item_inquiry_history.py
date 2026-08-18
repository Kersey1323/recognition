"""配件询码历史模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BIGINT, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from csrcqsf.infra.db.main_db import Base


class ItemInquiryHistory(Base):
    """SGO 询码结果沉淀到主业务库后的配件历史上下文。"""

    __tablename__ = "item_inquiry_history"
    __table_args__ = (
        UniqueConstraint(
            "inquiry_id",
            "return_item_code",
            "source",
            name="uq_item_inquiry_history_source_return",
        ),
        Index("idx_item_inquiry_history_item_id", "item_id"),
        Index("idx_item_inquiry_history_item_code", "item_code"),
        Index(
            "idx_item_inquiry_history_vehicle_name",
            "vehicle_batch",
            "inquiry_item_name",
        ),
        Index("idx_item_inquiry_history_train_car", "train_no", "car_num"),
    )

    item_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    item_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    inquiry_id: Mapped[str] = mapped_column(String(64), nullable=False)
    inquiry_num: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vehicle_batch: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vehicle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    train_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    car_num: Mapped[str | None] = mapped_column(String(100), nullable=True)
    inquiry_item_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subordinate_component: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_item_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    return_item_code: Mapped[str] = mapped_column(String(100), nullable=False)
    inquiry_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="sgo")

