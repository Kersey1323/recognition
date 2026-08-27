import asyncio
from unittest.mock import patch

import pytest

from csrcqsf.modules.railway_parts.integrations.reconstruction_client import (
    ReconstructionServiceClient,
    ReconstructionServiceClientError,
    _sanitize_content_disposition,
)


class _FakeContent:
    def __init__(self, chunks=None, body=b"", error=None):
        self.chunks = chunks or []
        self.body = body
        self.error = error
        self.chunk_size = None

    async def iter_chunked(self, size):
        self.chunk_size = size
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error

    async def read(self, size=-1):
        return self.body[:size]


class _FakeResponse:
    def __init__(self, *, status=200, headers=None, content=None):
        self.status = status
        self.headers = headers or {}
        self.content = content or _FakeContent()
        self.closed = False

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, response, recorder):
        self.response = response
        self.recorder = recorder
        self.closed = False

    async def request(self, method, url, **kwargs):
        self.recorder.update(method=method, url=url, kwargs=kwargs)
        return self.response

    async def close(self):
        self.closed = True


async def _collect(stream):
    return [chunk async for chunk in stream.iter_bytes()]


def test_stream_lifecycle_chunking_and_safe_headers():
    content = _FakeContent(chunks=[b"a", b"b"])
    response = _FakeResponse(
        headers={
            "Content-Type": "application/zip",
            "Content-Disposition": 'attachment; filename="../diagnostics.zip"',
            "Content-Length": "2",
            "Content-Encoding": "gzip",
            "Set-Cookie": "secret=value",
        },
        content=content,
    )
    recorder = {}
    session = _FakeSession(response, recorder)
    client = ReconstructionServiceClient(base_url="http://reconstruction:8000")

    with patch("aiohttp.ClientSession", return_value=session):
        stream = asyncio.run(client.stream_diagnostics_archive("task-1"))
        assert not response.closed
        assert not session.closed
        chunks = asyncio.run(_collect(stream))

    assert chunks == [b"a", b"b"]
    assert content.chunk_size == 64 * 1024
    assert response.closed
    assert session.closed
    assert stream.content_type == "application/zip"
    assert stream.content_disposition == 'attachment; filename="diagnostics.zip"'
    assert stream.content_length is None
    assert "Content-Encoding" not in stream.safe_headers
    assert "Content-Length" not in stream.safe_headers
    assert "Set-Cookie" not in stream.safe_headers


def test_stream_closes_resources_when_upstream_read_fails():
    response = _FakeResponse(content=_FakeContent(error=RuntimeError("read failed")))
    session = _FakeSession(response, {})
    client = ReconstructionServiceClient(base_url="http://reconstruction:8000")

    with patch("aiohttp.ClientSession", return_value=session):
        stream = asyncio.run(client.stream_task_log("task-1"))
        with pytest.raises(RuntimeError, match="read failed"):
            asyncio.run(_collect(stream))

    assert response.closed
    assert session.closed


def test_stream_closes_resources_when_iteration_is_cancelled():
    response = _FakeResponse(content=_FakeContent(chunks=[b"first", b"second"]))
    session = _FakeSession(response, {})
    client = ReconstructionServiceClient(base_url="http://reconstruction:8000")

    async def consume_one_and_close():
        stream = await client.stream_task_log("task-1")
        iterator = stream.iter_bytes()
        assert await iterator.__anext__() == b"first"
        await iterator.aclose()

    with patch("aiohttp.ClientSession", return_value=session):
        asyncio.run(consume_one_and_close())

    assert response.closed
    assert session.closed


def test_stream_remote_error_is_not_exposed_as_file_bytes():
    response = _FakeResponse(
        status=404,
        headers={"Content-Type": "application/json"},
        content=_FakeContent(body=b'{"detail":"log not found"}'),
    )
    session = _FakeSession(response, {})
    client = ReconstructionServiceClient(base_url="http://reconstruction:8000")

    with patch("aiohttp.ClientSession", return_value=session):
        with pytest.raises(ReconstructionServiceClientError) as exc_info:
            asyncio.run(client.stream_task_log("task-1"))

    assert exc_info.value.status_code == 404
    assert "log not found" in exc_info.value.detail
    assert response.closed
    assert session.closed


def test_artifact_stream_uses_query_params_instead_of_path_concatenation():
    response = _FakeResponse()
    recorder = {}
    session = _FakeSession(response, recorder)
    client = ReconstructionServiceClient(base_url="http://reconstruction:8000")

    with patch("aiohttp.ClientSession", return_value=session):
        stream = asyncio.run(
            client.stream_diagnostic_artifact("task-1", "train/render 1.png")
        )
        asyncio.run(_collect(stream))

    assert recorder["url"].endswith(
        "/reconstruction/tasks/task-1/diagnostics/artifacts/download"
    )
    assert recorder["kwargs"]["params"] == {"path": "train/render 1.png"}


def test_content_disposition_encodes_non_ascii_filename_as_ascii_header():
    value = _sanitize_content_disposition('attachment; filename="诊断包.zip"')

    assert value == "attachment; filename*=UTF-8''%E8%AF%8A%E6%96%AD%E5%8C%85.zip"
    value.encode("ascii")


def test_stream_keeps_valid_content_length_when_body_is_not_encoded():
    response = _FakeResponse(headers={"Content-Length": "12"})
    session = _FakeSession(response, {})
    client = ReconstructionServiceClient(base_url="http://reconstruction:8000")

    with patch("aiohttp.ClientSession", return_value=session):
        stream = asyncio.run(client.stream_task_log("task-1"))
        asyncio.run(_collect(stream))

    assert stream.content_length == 12
    assert stream.safe_headers["Content-Length"] == "12"
