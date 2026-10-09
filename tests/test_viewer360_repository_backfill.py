from __future__ import annotations

import os

os.environ["SGO_KINGBASE_PORT"] = "54321"
os.environ["SGO_MYSQL_PORT"] = "3306"

from csrcqsf.modules.railway_parts.repositories.viewer360_repository import (
    Viewer360Repository,
)


def test_backfill_candidate_statement_excludes_current_and_active_only():
    stmt = Viewer360Repository._backfill_candidate_stmt(limit=100)
    compiled = stmt.compile()
    sql = str(compiled)
    collection_values = [
        value
        for value in compiled.params.values()
        if isinstance(value, (list, tuple, set))
    ]
    statuses = next(value for value in collection_values if "pending" in value)

    assert "source_video_path" in sql
    assert "item_viewer360_current" in sql
    assert "viewer360_task" in sql
    assert "source_video_updated_at ASC" in sql
    assert "item_info.id ASC" in sql
    assert set(statuses) == {"pending", "running", "cancelling"}
    assert not {"failed", "cancelled", "interrupted"}.intersection(statuses)
    assert compiled.params["param_1"] == 100
