"""Durable audit records for reconstruction recovery and output cleanup."""

from __future__ import annotations

from sqlalchemy import BIGINT, Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from csrcqsf.infra.db.main_db import Base


class ReconstructionOperationAudit(Base):
    __tablename__ = "reconstruction_operation_audit"
    __table_args__ = (
        Index(
            "ix_reconstruction_operation_audit_task_created",
            "task_id",
            "time_created",
        ),
        Index(
            "ix_reconstruction_operation_audit_operation_created",
            "operation",
            "time_created",
        ),
    )

    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    operator_id: Mapped[str] = mapped_column(String(100), nullable=False)
    task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    item_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    request_summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    response_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
