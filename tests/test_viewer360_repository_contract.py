from datetime import datetime

from csrcqsf.models.orm.viewer360_task import Viewer360Task
from csrcqsf.modules.railway_parts.repositories.viewer360_repository import (
    viewer360_task_to_dict,
)


def test_viewer360_task_mapping_preserves_json_and_timestamps():
    now = datetime.now()
    record = Viewer360Task(
        task_id="task-1",
        root_task_id="task-1",
        item_id=12,
        source_video_object="videos/12.mp4",
        rebuild_existing=False,
        retry_mode="none",
        retry_rows_json=[2, 4],
        status="pending",
        current_stage="preparing",
        row_states_json=[{"row_index": 1, "status": "pending"}],
        output_bucket="results",
        output_prefix="viewer360/12/task-1",
        heartbeat_at=now,
    )

    payload = viewer360_task_to_dict(record)

    assert payload["task_id"] == "task-1"
    assert payload["retry_rows_json"] == [2, 4]
    assert payload["row_states_json"][0]["status"] == "pending"
    assert payload["heartbeat_at"] == now
