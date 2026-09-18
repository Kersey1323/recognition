from types import SimpleNamespace

import pytest

from csrcqsf.models.orm.search_history import SearchHistory


class _ScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _RecordingSession:
    def __init__(self):
        self.scalar_statements = []

    async def scalar(self, statement):
        return 2

    async def scalars(self, statement):
        self.scalar_statements.append(statement)
        if len(self.scalar_statements) == 1:
            return _ScalarResult([101, 100])
        return _ScalarResult(
            [
                SimpleNamespace(id=100),
                SimpleNamespace(id=101),
            ]
        )


@pytest.mark.asyncio
async def test_history_list_sorts_ids_before_loading_wide_json_rows():
    session = _RecordingSession()

    result = await SearchHistory.list_search_history(
        session,
        page=1,
        per_page=2,
    )

    assert len(session.scalar_statements) == 2
    id_query = str(session.scalar_statements[0])
    row_query = str(session.scalar_statements[1])
    assert "SELECT search_history.id" in id_query
    assert "search_history.search_results" not in id_query
    assert "ORDER BY search_history.time_created DESC, search_history.id DESC" in id_query
    assert "WHERE search_history.id IN" in row_query
    assert [row.id for row in result.data] == [101, 100]
