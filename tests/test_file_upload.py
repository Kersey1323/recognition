import asyncio
import importlib
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI, UploadFile
import httpx
import pytest
from starlette.datastructures import Headers


def _upload_service():
    return importlib.import_module(
        "csrcqsf.modules.railway_parts.services.file_upload_service"
    )


@pytest.mark.parametrize(
    "filename,content_type,body",
    [
        ("photo.jpg", "image/jpeg", b"photo-data"),
        ("video.mp4", "video/mp4", b"video-data"),
        ("report.bin", None, b"binary-data"),
    ],
)
def test_file_upload_streams_content_and_returns_unique_oss_path(
    monkeypatch, filename, content_type, body
):
    service = _upload_service()
    uploads = []

    def put_object(bucket, object_name, stream, length, content_type):
        uploads.append((bucket, object_name, stream.read(), length, content_type))

    monkeypatch.setattr(service, "minio_bucket", "test-files")
    monkeypatch.setattr(
        service, "minio_instance", SimpleNamespace(client=SimpleNamespace(put_object=put_object))
    )
    monkeypatch.setattr(service, "ensure_minio_bucket", Mock())
    files = [
        UploadFile(
            filename=f"../folder/{filename}",
            file=io.BytesIO(body),
            headers=Headers({"content-type": content_type}) if content_type else Headers(),
        )
        for _ in range(2)
    ]
    for file in files:
        file.read = AsyncMock(side_effect=AssertionError("must use the upload stream"))

    async def run():
        return [await service.upload_file_to_oss(file) for file in files]

    paths = asyncio.run(run())
    assert paths[0] != paths[1]
    for path, uploaded in zip(paths, uploads):
        assert path == f"test-files/{uploaded[1]}"
        assert uploaded[1].startswith("uploads/")
        assert ".." not in uploaded[1]
        assert uploaded[1].endswith(filename)
        assert uploaded[2:] == (body, len(body), content_type or "application/octet-stream")
    assert all(file.file.closed for file in files)


def test_empty_upload_is_rejected_before_storage_write(monkeypatch):
    service = _upload_service()
    storage = Mock()
    monkeypatch.setattr(service, "minio_instance", SimpleNamespace(client=storage))
    monkeypatch.setattr(service, "ensure_minio_bucket", Mock())
    file = UploadFile(filename="empty.mp4", file=io.BytesIO())

    with pytest.raises(service.EmptyFileError):
        asyncio.run(service.upload_file_to_oss(file))

    storage.put_object.assert_not_called()
    service.ensure_minio_bucket.assert_not_called()
    assert file.file.closed


def test_storage_error_closes_upload_and_returns_no_address(monkeypatch):
    service = _upload_service()
    storage = Mock()
    storage.put_object.side_effect = OSError("storage unavailable")
    monkeypatch.setattr(service, "minio_instance", SimpleNamespace(client=storage))
    monkeypatch.setattr(service, "ensure_minio_bucket", Mock())
    file = UploadFile(filename="video.mp4", file=io.BytesIO(b"video"))

    with pytest.raises(OSError, match="storage unavailable"):
        asyncio.run(service.upload_file_to_oss(file))
    assert file.file.closed


def test_upload_route_accepts_only_required_file_and_returns_address(monkeypatch):
    from csrcqsf.core import settings

    settings.ai_settings.sgo_mysql_port = "3306"
    settings.ai_settings.sgo_kingbase_port = "54321"
    from csrcqsf.modules.railway_parts.routes import parts_routes

    app = FastAPI()
    app.include_router(parts_routes.parts_router)
    assert "/railway/parts/upload_file" in {route.path for route in app.routes}
    upload = AsyncMock(return_value="test-files/uploads/example.mp4")
    monkeypatch.setattr(parts_routes, "upload_file_to_oss", upload)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await client.post(
                "/railway/parts/upload_file",
                files={"file": ("video.mp4", b"video", "video/mp4")},
            )
            missing = await client.post("/railway/parts/upload_file")
            upload.side_effect = parts_routes.EmptyFileError("上传文件不能为空")
            empty = await client.post(
                "/railway/parts/upload_file", files={"file": ("empty.mp4", b"")}
            )
            return result, missing, empty

    result, missing, empty = asyncio.run(run())
    assert result.status_code == 200
    assert result.json() == {"oss_url": "test-files/uploads/example.mp4"}
    assert missing.status_code == 422
    assert empty.status_code == 400
    schema = app.openapi()
    multipart = schema["paths"]["/railway/parts/upload_file"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
    body = schema["components"]["schemas"][multipart["$ref"].split("/")[-1]]
    assert list(body["properties"]) == ["file"]
    assert body["required"] == ["file"]
