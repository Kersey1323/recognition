import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.dialects import mysql


def test_text_index_document_model_has_item_and_task_indexes():
    from csrcqsf.models.orm.inquiry_text_index_document import (
        InquiryTextIndexDocument,
    )

    columns = InquiryTextIndexDocument.__table__.columns
    assert columns.document_key.primary_key is True
    assert columns.item_id.nullable is False
    assert columns.description.nullable is False
    assert {index.name for index in InquiryTextIndexDocument.__table__.indexes} == {
        "ix_inquiry_text_index_document_item",
        "ix_inquiry_text_index_document_task",
    }


def test_list_features_deduplicates_descriptions_per_item():
    from csrcqsf.modules.railway_parts.repositories.inquiry_text_index_document_repository import (
        InquiryTextIndexDocumentRepository,
    )

    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=[
                (101, "残疾人厕所镜子"),
                (101, "残疾人厕所镜子"),
                (101, "厕所内镜子"),
                (102, "电热开水器"),
            ]
        )
    )

    result = asyncio.run(
        InquiryTextIndexDocumentRepository.list_features_by_item_ids(
            session,
            [101, 102],
        )
    )

    assert result == {
        101: ["残疾人厕所镜子", "厕所内镜子"],
        102: ["电热开水器"],
    }


def test_list_features_filters_current_and_future_inquiries_for_agent():
    from csrcqsf.modules.railway_parts.repositories.inquiry_text_index_document_repository import (
        InquiryTextIndexDocumentRepository,
    )

    session = SimpleNamespace(execute=AsyncMock(return_value=[]))
    cutoff = datetime(2026, 3, 5, 10, 30, 26)

    asyncio.run(
        InquiryTextIndexDocumentRepository.list_features_by_item_ids(
            session,
            [101],
            exclude_inquiry_id="current-inquiry",
            before_inquiry_time=cutoff,
        )
    )

    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "item_inquiry_history" in sql
    assert "item_inquiry_history.inquiry_id != 'current-inquiry'" in sql
    assert "item_inquiry_history.inquiry_time < '2026-03-05 10:30:26'" in sql
