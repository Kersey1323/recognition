import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from csrcqsf.modules.railway_parts.services import item_service


class _SessionContext:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DetailResponse:
    def __init__(self, **values):
        self.__dict__.update(values)
        self.images_index_list = []
        self.images = []


async def _empty_images(**_kwargs):
    if False:
        yield None


@pytest.mark.parametrize(
    "agent_running, expected_filter",
    [
        (False, {}),
        (
            True,
            {
                "exclude_inquiry_id": "current-inquiry",
                "before_inquiry_time": datetime(2026, 3, 5, 10, 30, 26),
            },
        ),
    ],
)
def test_get_item_detail_only_filters_features_during_agent_runs(
    agent_running,
    expected_filter,
):
    cutoff = datetime(2026, 3, 5, 10, 30, 26)
    feature_repository = SimpleNamespace(
        list_features_by_item_ids=AsyncMock(return_value={101: ["门控器"]})
    )
    runtime = SimpleNamespace(
        SessionLocal=_SessionContext,
        Items=SimpleNamespace(
            get_item_by_id=AsyncMock(
                return_value=SimpleNamespace(
                    id=101,
                    obj_url=None,
                    height=None,
                    width=None,
                    long=None,
                    weight=None,
                    source_video_path=None,
                    item_name="门控器",
                    item_code="40002067288",
                    time_created=None,
                    time_updated=None,
                    size_str=None,
                )
            )
        ),
        SgoItemImages=SimpleNamespace(get_images=_empty_images),
        SegmentedImage=SimpleNamespace(list_by_item_id=AsyncMock(return_value=[])),
        InquiryTextIndexDocumentRepository=feature_repository,
        SegmentStatus=SimpleNamespace(SUCCESS="success"),
        GetItemDetailRes=_DetailResponse,
        ItemImageIndexInfo=SimpleNamespace,
        ItemImageItem=SimpleNamespace,
        date_to_str=lambda value: value,
    )

    with patch.object(item_service, "agent_running", agent_running):
        asyncio.run(
            item_service.get_item_detail(
                None,
                item_id=101,
                source_inquiry_id="current-inquiry",
                source_inquiry_time=cutoff,
                runtime=runtime,
            )
        )

    feature_repository.list_features_by_item_ids.assert_awaited_once()
    assert feature_repository.list_features_by_item_ids.await_args.args[1] == [101]
    assert feature_repository.list_features_by_item_ids.await_args.kwargs == expected_filter
