"""SGO 库存表中记录的库区与货位。"""

import os
from decimal import Decimal

from sqlalchemy import Numeric, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from csrcqsf.models.orm.sgo_external import Base


STOCK_FACTORY = "3100"
STOCK_WAREHOUSES = ("2514", "JS00")
STOCK_TENANT = os.getenv("SGO_TENANT_ID", "1463844437338755072")


class WmsStockDetail(Base):
    __tablename__ = "wms_stock_detail"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    MATNR: Mapped[str | None] = mapped_column(String(100))
    WERKS: Mapped[str | None] = mapped_column(String(5))
    LGORT: Mapped[str | None] = mapped_column(String(10))
    LGORTD: Mapped[str | None] = mapped_column(String(255))
    GRARD: Mapped[str | None] = mapped_column(String(50))
    CLABS: Mapped[Decimal | None] = mapped_column(Numeric(11, 4))
    tenant_id_: Mapped[str | None] = mapped_column(String(50))

    @classmethod
    async def list_available_locations(cls, session):
        # 库存数量不准确，现场取件清单保留指定库区内全部有货位的物料，不按数量筛选。
        fields = (
            func.trim(cls.MATNR), func.trim(cls.LGORT),
            func.nullif(func.trim(cls.LGORTD), ""), func.trim(cls.GRARD),
        )
        result = await session.execute(
            select(*fields).where(
                cls.WERKS == STOCK_FACTORY,
                cls.LGORT.in_(STOCK_WAREHOUSES),
                cls.tenant_id_ == STOCK_TENANT,
                func.trim(cls.MATNR) != "",
                func.trim(cls.GRARD) != "",
            ).distinct()
        )
        return result.all()
