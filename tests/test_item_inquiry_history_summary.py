import asyncio
from datetime import datetime

from sqlalchemy.dialects import mysql

from csrcqsf.models.orm.item_inquiry_history import ItemInquiryHistory


def test_inquiry_summary_batches_all_numbers_for_current_page_item_ids():
    class Rows:
        @staticmethod
        def all():
            return [
                (101, "CX20260802001", datetime(2026, 8, 20, 10, 0), 3),
                (101, "CX20260729001", datetime(2026, 7, 29, 10, 0), 2),
                (101, "CX20260729001", datetime(2026, 7, 29, 9, 0), 1),
                (101, None, datetime(2026, 7, 28, 10, 0), 5),
                (102, "CX20260801001", datetime(2026, 8, 1, 10, 0), 4),
            ]

    class Session:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Rows()

    session = Session()
    result = asyncio.run(
        ItemInquiryHistory.list_summary_by_item_ids(session, [101, 102])
    )

    assert result == [
        (101, ["CX20260802001", "CX20260729001"], 2),
        (102, ["CX20260801001"], 1),
    ]
    compiled = str(
        session.statement.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "item_inquiry_history.item_id IN (101, 102)" in compiled
    assert "OVER (PARTITION BY" not in compiled
    assert "ORDER BY item_inquiry_history.item_id, item_inquiry_history.inquiry_time DESC" in compiled


def test_inquiry_summary_skips_query_for_empty_page():
    class Session:
        async def execute(self, statement):
            raise AssertionError("empty page must not query inquiry history")

    result = asyncio.run(
        ItemInquiryHistory.list_summary_by_item_ids(Session(), [])
    )

    assert result == []
