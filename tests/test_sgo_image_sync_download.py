import asyncio
import io
import json
import threading
import time
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from csrcqsf.modules.sgo import services as sgo_services
from csrcqsf.modules.sgo.schemas import ImageSourceType
from csrcqsf.modules.sgo.services import (
    ImageSyncCandidate,
    SGOBiz,
    SgoImageDownloadError,
    SgoImageSourceFileError,
    SgoImageZipError,
    SgoZipTooLargeError,
)


class FakeResponse:
    def __init__(self, status, chunks=(), data=b"", headers=None):
        self.status = status
        self._chunks = list(chunks)
        self.data = data
        self.headers = headers or {}
        self.released = False

    def stream(self, _amount):
        yield from self._chunks

    def release_conn(self):
        self.released = True


class FakePool:
    def __init__(self, responses):
        self.responses = list(responses)
        self.request_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def request(self, *_args, **_kwargs):
        response = self.responses[self.request_count]
        self.request_count += 1
        return response


def build_zip(file_count):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index in range(file_count):
            archive.writestr(f"image-{index}.jpg", f"image-{index}".encode())
    return buffer.getvalue()


def test_get_token_records_safe_http_failure_details():
    response = FakeResponse(
        401,
        data=b'{"code":401,"message":"account rejected"}',
        headers={"Content-Type": "application/json"},
    )
    pool = FakePool([response])

    with patch.object(sgo_services, "PoolManager", return_value=pool):
        SGOBiz.token = ""
        SGOBiz._token_error_detail = ""
        result = SGOBiz.get_token()

    assert result is False
    assert SGOBiz.token == ""
    assert "http_status=401" in SGOBiz._token_error_detail
    assert "account rejected" in SGOBiz._token_error_detail
    assert "username_configured=True" in SGOBiz._token_error_detail
    assert SGOBiz._password not in SGOBiz._token_error_detail
    assert SGOBiz._encryption not in SGOBiz._token_error_detail


def test_download_images_fetches_missing_token_on_demand():
    response = FakeResponse(200, [b"zip-data"])
    pool = FakePool([response])

    def fetch_token():
        SGOBiz.token = "new-token"
        SGOBiz._token_error_detail = ""
        return True

    with patch.object(sgo_services, "PoolManager", return_value=pool), patch.object(
        SGOBiz,
        "get_token",
        side_effect=fetch_token,
    ) as get_token:
        SGOBiz.token = ""
        result = SGOBiz.download_images_from_sgo(["file-1"])

    assert result == b"zip-data"
    get_token.assert_called_once()


def test_download_images_exposes_token_failure_details():
    def fail_to_fetch_token():
        SGOBiz._token_error_detail = (
            "endpoint=https://sgo.example/auth; http_status=503; "
            "exception=ReadTimeoutError"
        )
        return False

    with patch.object(
        SGOBiz,
        "get_token",
        side_effect=fail_to_fetch_token,
    ):
        SGOBiz.token = ""
        with pytest.raises(
            SgoImageDownloadError,
            match="http_status=503.*ReadTimeoutError",
        ):
            SGOBiz.download_images_from_sgo(["file-1"])


def test_download_images_does_not_retry_server_error_and_exposes_message():
    response = FakeResponse(
        500,
        data=json.dumps(
            {
                "state": False,
                "message": (
                    "文件下载失败！platform：sftp-1,"
                    "fileInfo：FileInfo(...)"
                ),
                "logId": "2100119211291447296",
            },
            ensure_ascii=False,
        ).encode(),
        headers={"Content-Type": "application/json;charset=UTF-8"},
    )
    pool = FakePool([response])

    with patch.object(sgo_services, "PoolManager", return_value=pool), patch.object(
        sgo_services.time,
        "sleep",
    ) as sleep:
        SGOBiz.token = "token"
        with pytest.raises(SgoImageSourceFileError) as exc_info:
            SGOBiz.download_images_from_sgo(["file-1"])

    error_message = str(exc_info.value)
    assert pool.request_count == 1
    assert "platform：sftp-1,fileInfo：FileInfo(...)" in error_message
    assert "logId=2100119211291447296" in error_message
    sleep.assert_not_called()
    assert response.released is True


def test_download_images_refreshes_token_on_401():
    responses = [
        FakeResponse(401),
        FakeResponse(200, [b"zip-data"]),
    ]
    pool = FakePool(responses)

    def refresh_token():
        SGOBiz.token = "new-token"

    with patch.object(sgo_services, "PoolManager", return_value=pool), patch.object(
        SGOBiz,
        "get_token",
        side_effect=refresh_token,
    ) as get_token, patch.object(sgo_services.time, "sleep"):
        SGOBiz.token = "old-token"
        result = SGOBiz.download_images_from_sgo(["file-1"])

    assert result == b"zip-data"
    assert pool.request_count == 2
    get_token.assert_called_once()
    assert all(response.released for response in responses)


def test_download_images_rejects_response_over_memory_limit():
    response = FakeResponse(200, [b"1234", b"5678"])
    pool = FakePool([response])
    with patch.object(sgo_services, "PoolManager", return_value=pool), patch.object(
        sgo_services,
        "sgo_image_zip_max_bytes",
        6,
    ):
        SGOBiz.token = "token"
        with pytest.raises(SgoZipTooLargeError, match="ZIP 响应超过限制"):
            SGOBiz.download_images_from_sgo(["file-1"])

    assert response.released is True


def test_store_zip_candidates_rejects_missing_archive_entries():
    candidates = [
        ImageSyncCandidate("file-1", "101", ImageSourceType.BASEINFO),
        ImageSyncCandidate("file-2", "102", ImageSourceType.BASEINFO),
    ]
    with patch.object(
        SGOBiz,
        "download_images_from_sgo",
        return_value=build_zip(1),
    ):
        with pytest.raises(SgoImageZipError, match="文件数量不一致"):
            asyncio.run(SGOBiz._store_zip_candidates(candidates))


def test_store_zip_candidates_limits_minio_upload_concurrency():
    candidates = [
        ImageSyncCandidate(
            raw_url=f"file-{index}",
            item_id=str(100 + index),
            image_source=ImageSourceType.BASEINFO,
        )
        for index in range(6)
    ]
    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def put_object(*_args, **_kwargs):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1

    with patch.object(
        SGOBiz,
        "download_images_from_sgo",
        return_value=build_zip(len(candidates)),
    ), patch.object(
        sgo_services.minio_instance.client,
        "put_object",
        side_effect=put_object,
    ), patch.object(
        SGOBiz,
        "_commit_images",
        AsyncMock(return_value=6),
    ) as commit_images, patch.object(
        sgo_services,
        "sgo_image_upload_concurrency",
        2,
    ):
        synced_count, failures = asyncio.run(
            SGOBiz._store_zip_candidates(candidates)
        )

    assert synced_count == 6
    assert failures == []
    assert maximum_active == 2
    assert len(commit_images.await_args.args[0]) == 6


def test_commit_images_rechecks_raw_url_before_insert():
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def commit(self):
            return None

    images = [
        SimpleNamespace(raw_url="existing-file"),
        SimpleNamespace(raw_url="new-file"),
    ]
    with patch.object(
        sgo_services,
        "SessionLocal",
        return_value=FakeSession(),
    ), patch.object(
        sgo_services.SgoItemImages,
        "list_item_images_by_raw_url",
        AsyncMock(return_value=[SimpleNamespace(raw_url="existing-file")]),
    ) as list_existing, patch.object(
        sgo_services.SgoItemImages,
        "create_item_images",
        AsyncMock(),
    ) as create_images:
        created_count = asyncio.run(SGOBiz._commit_images(images))

    assert created_count == 1
    list_existing.assert_awaited_once()
    assert list_existing.await_args.kwargs["include_deleted"] is True
    assert create_images.await_args.args[1] == [images[1]]
