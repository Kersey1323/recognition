import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from csrcqsf.infra.external.model_client import ModelServiceError
from csrcqsf.models.orm.item import Items
from csrcqsf.models.orm.sgo import SgoItemImages
from csrcqsf.modules.railway_parts.services import parts_index_service
from test_v2_index_auto_segmentation import AsyncSessionContext, build_scenario


def test_rebuild_awaits_progress_callback_and_persists_part_checkpoint():
    async def scenario():
        image = SimpleNamespace(
            id=9001,
            image_url="bfr-ai-files/a.jpg",
            image_source="BASEINFO",
        )
        test_case = build_scenario([image])
        test_case.item.time_created = datetime(2026, 8, 1, 10, 0, 0)
        snapshots = []

        async def progress_callback(snapshot):
            snapshots.append(dict(snapshot))

        result = await parts_index_service.rebuild_v2_index(
            test_case.railway_manager,
            item_id=101,
            limit=1,
            rebuild_existing=False,
            progress_callback=progress_callback,
            initial_completed_item_count=4,
            initial_success_count=2,
            initial_fail_count=1,
            initial_segmented_count=1,
            initial_fallback_count=0,
            total_items_override=5,
            runtime=test_case.runtime,
        )

        checkpoint = snapshots[-1]
        assert checkpoint["progress"] == 100
        assert checkpoint["completed_item_count"] == 5
        assert checkpoint["processed_items"] == 5
        assert checkpoint["last_completed_item_id"] == 101
        assert checkpoint["last_completed_item_created_at"] == datetime(
            2026, 8, 1, 10, 0, 0
        )
        assert result["success_count"] == 3
        assert result["fail_count"] == 1

    asyncio.run(scenario())


def test_rebuild_does_not_checkpoint_part_cancelled_during_image_processing():
    async def scenario():
        image = SimpleNamespace(
            id=9001,
            image_url="bfr-ai-files/a.jpg",
            image_source="BASEINFO",
        )
        test_case = build_scenario([image])
        test_case.item.time_created = datetime(2026, 8, 1, 10, 0, 0)
        test_case.railway_manager.get_image_from_oss.side_effect = asyncio.CancelledError()
        snapshots = []

        async def progress_callback(snapshot):
            snapshots.append(dict(snapshot))

        with pytest.raises(asyncio.CancelledError):
            await parts_index_service.rebuild_v2_index(
                test_case.railway_manager,
                item_id=101,
                progress_callback=progress_callback,
                runtime=test_case.runtime,
            )

        assert all("last_completed_item_id" not in snapshot for snapshot in snapshots)
        assert snapshots[-1]["completed_item_count"] == 0

    asyncio.run(scenario())


def test_batch_retry_applies_stable_part_cursor_before_limit():
    async def scenario():
        session = AsyncMock()
        session.scalars.return_value = []
        model_client = SimpleNamespace(
            require_indexing_extract_capability=AsyncMock(),
        )
        runtime = SimpleNamespace(
            SessionLocal=lambda: AsyncSessionContext(session),
            Items=Items,
            SgoItemImages=SgoItemImages,
            select=select,
            get_model_client=lambda: model_client,
            ModelServiceError=ModelServiceError,
            _get_milvus_manager_v2_cls=lambda: lambda: SimpleNamespace(),
            _get_milvus_state_manager_v2_cls=lambda: lambda: SimpleNamespace(),
            logger=MagicMock(),
        )

        await parts_index_service.rebuild_v2_index(
            SimpleNamespace(),
            item_id=None,
            limit=5,
            rebuild_existing=True,
            resume_after_created_at=datetime(2026, 8, 1, 10, 0, 0),
            resume_after_item_id=1004,
            runtime=runtime,
        )

        statement = session.scalars.await_args.args[0]
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "item_info.time_created < '2026-08-01 10:00:00'" in sql
        assert "item_info.id < 1004" in sql
        assert "LIMIT 5" in sql

    asyncio.run(scenario())


def test_batch_rebuild_selects_items_with_unindexed_images():
    async def scenario():
        session = AsyncMock()
        session.scalars.return_value = []
        model_client = SimpleNamespace(
            require_indexing_extract_capability=AsyncMock(),
        )
        runtime = SimpleNamespace(
            SessionLocal=lambda: AsyncSessionContext(session),
            Items=Items,
            SgoItemImages=SgoItemImages,
            select=select,
            get_model_client=lambda: model_client,
            ModelServiceError=ModelServiceError,
            _get_milvus_manager_v2_cls=lambda: lambda: SimpleNamespace(),
            _get_milvus_state_manager_v2_cls=lambda: lambda: SimpleNamespace(),
            logger=MagicMock(),
        )

        await parts_index_service.rebuild_v2_index(
            SimpleNamespace(),
            item_id=None,
            limit=500,
            rebuild_existing=False,
            runtime=runtime,
        )

        statement = session.scalars.await_args.args[0]
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "sgo_item_image_info.is_indexed != 1" in sql
        assert "item_info.has_v2_index = 0" not in sql
        assert "LIMIT 500" in sql

    asyncio.run(scenario())
