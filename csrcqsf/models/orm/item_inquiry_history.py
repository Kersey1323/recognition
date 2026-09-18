"""配件询码历史模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BIGINT, DateTime, Index, String, Text, UniqueConstraint, func, select
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

    @staticmethod
    def normalized_vehicle_batch_expr():
        """车型候选归一化表达式：优先归一化车型字段，旧数据回退原始车型文本。

        条件检索与配件列表的车型过滤共用该表达式，避免两处规则漂移。
        """
        return func.upper(
            func.coalesce(
                func.nullif(func.trim(ItemInquiryHistory.vehicle_batch), ""),
                func.trim(ItemInquiryHistory.vehicle),
            )
        )

    @classmethod
    async def list_summary_by_item_ids(cls, session, item_id_list: list[int]):
        if not item_id_list:
            return []

        # 当前页关联的询码记录一次取回并按时间倒序聚合，供列表展示全部询码流水号。
        # 同一流水号只展示一次，空流水号不计入询码数量。
        stmt = (
            select(cls.item_id, cls.inquiry_num, cls.inquiry_time, cls.id)
            .where(cls.item_id.in_(list(dict.fromkeys(item_id_list))))
            .order_by(cls.item_id, cls.inquiry_time.desc(), cls.id.desc())
        )
        rows = (await session.execute(stmt)).all()
        inquiry_nums_by_item: dict[int, list[str]] = {}
        seen_nums_by_item: dict[int, set[str]] = {}
        for item_id, inquiry_num, _inquiry_time, _history_id in rows:
            if not inquiry_num:
                continue
            inquiry_nums = inquiry_nums_by_item.setdefault(item_id, [])
            seen_nums = seen_nums_by_item.setdefault(item_id, set())
            if inquiry_num in seen_nums:
                continue
            seen_nums.add(inquiry_num)
            inquiry_nums.append(inquiry_num)
        return [
            (item_id, inquiry_nums, len(inquiry_nums))
            for item_id, inquiry_nums in inquiry_nums_by_item.items()
        ]
