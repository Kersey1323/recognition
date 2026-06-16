import asyncio
import importlib
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.modules.railway_parts.utils.local_upload_storage import LocalUploadStorage
from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _UploadFileStub:
    def __init__(self, data: bytes, filename: str = "part.bin"):
        self._data = data
        self.filename = filename
        self.file = BytesIO(data)
        self.closed = False

    async def read(self):
        return self._data

    async def close(self):
        self.closed = True


def test_choose_multipart_part_size_matches_reference_guide():
    mb = 1024 * 1024
    gb = 1024 * 1024 * 1024

    assert ReconstructionManager._choose_multipart_part_size(100 * mb) == 10 * mb
    assert ReconstructionManager._choose_multipart_part_size(101 * mb) == 20 * mb
    assert ReconstructionManager._choose_multipart_part_size(2 * gb) == 50 * mb
    assert ReconstructionManager._choose_multipart_part_size(6 * gb) >= 5 * mb


def test_init_source_video_multipart_upload_rejects_existing_source_video():
    service_module = importlib.import_module(
        "csrcqsf.modules.railway_parts.services.reconstruction_service"
    )
    existing_item = SimpleNamespace(id=101, source_video_path="bfr-3d-videos/existing.mp4")

    with patch.object(ReconstructionManager, "_require_item_exists", AsyncMock(return_value=existing_item)):
        try:
            asyncio.run(
                ReconstructionManager.init_source_video_multipart_upload(
                    item_id=101,
                    file_name="demo.mp4",
                    file_size=1024,
                    content_type="video/mp4",
                )
            )
        except service_module.ReconstructionBusinessError as exc:
            assert "已存在原始视频" in str(exc)
        else:
            raise AssertionError("expected multipart init to reject existing source video")


def test_init_source_video_multipart_upload_returns_session_and_urls():
    item = SimpleNamespace(id=101, source_video_path=None)
    session = AsyncMock()
    created = {}

    async def _capture_create(_session, record):
        record.id = 9001
        created["record"] = record
        return record

    with patch.object(ReconstructionManager, "_require_item_exists", AsyncMock(return_value=item)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionVideoUploadSession.get_active_by_item_id", AsyncMock(return_value=None)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionVideoUploadSession.create_session", AsyncMock(side_effect=_capture_create)), \
         patch.object(ReconstructionManager, "_create_multipart_upload", AsyncMock(return_value="upload-1")), \
         patch.object(ReconstructionManager, "_generate_multipart_upload_urls", AsyncMock(return_value=[
             {"part_number": 1, "url": "/bfr-3d-videos/upload-1?partNumber=1&uploadId=upload-1", "expires_at": "2026-05-20T10:00:00"}
         ])), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.datetime") as datetime_mock:
        now = datetime(2026, 5, 13, 10, 0, 0)
        datetime_mock.now.return_value = now
        datetime_mock.utcnow.return_value = now

        result = asyncio.run(
            ReconstructionManager.init_source_video_multipart_upload(
                item_id=101,
                file_name="demo.mp4",
                file_size=1024,
                content_type="video/mp4",
            )
        )

    assert result["upload_session_id"] == 9001
    assert result["upload_id"] == "upload-1"
    assert result["video_path"].startswith("bfr-3d-videos/raw-videos/101/20260513/")
    assert result["upload_urls"][0]["url"].startswith("/bfr-3d-videos/")
    assert created["record"].total_parts == 1
    session.commit.assert_awaited_once()


def test_init_source_video_multipart_upload_local_mode_does_not_create_minio_upload():
    item = SimpleNamespace(id=101, source_video_path=None)

    with patch.object(ReconstructionManager, "_require_item_exists", AsyncMock(return_value=item)), \
         patch.object(ReconstructionManager, "_init_local_source_video_upload", AsyncMock(return_value={"upload_session_id": 2, "part_size": 10, "total_parts": 1, "upload_urls": []})) as local_mock, \
         patch.object(ReconstructionManager, "_init_remote_source_video_upload", AsyncMock()) as remote_mock:
        result = asyncio.run(
            ReconstructionManager.init_source_video_multipart_upload(
                item_id=101,
                file_name="demo.mp4",
                file_size=1024,
                content_type="video/mp4",
                storage_mode="local",
            )
        )

    local_mock.assert_awaited_once()
    remote_mock.assert_not_awaited()
    assert result["upload_session_id"] == 2


def test_get_source_video_upload_progress_returns_uploaded_parts():
    upload_session = SimpleNamespace(
        id=9001,
        item_id=101,
        storage_mode="remote",
        upload_id="upload-1",
        bucket="bfr-3d-videos",
        object_name="raw-videos/101/20260513/demo.mp4",
        video_path="bfr-3d-videos/raw-videos/101/20260513/demo.mp4",
        part_size=10485760,
        total_parts=2,
        status="initiated",
    )

    with patch.object(ReconstructionManager, "_require_upload_session", AsyncMock(return_value=upload_session)), \
         patch.object(ReconstructionManager, "_list_multipart_uploaded_parts", AsyncMock(return_value=[
             {"part_number": 1, "size": 10485760, "etag": "etag-1"}
         ])):
        result = asyncio.run(ReconstructionManager.get_source_video_upload_progress(upload_session_id=9001))

    assert result["upload_session_id"] == 9001
    assert result["uploaded_parts"][0]["etag"] == "etag-1"


def test_get_source_video_upload_urls_returns_requested_part_urls():
    upload_session = SimpleNamespace(
        id=9001,
        item_id=101,
        storage_mode="remote",
        upload_id="upload-1",
        bucket="bfr-3d-videos",
        object_name="raw-videos/101/20260513/demo.mp4",
        video_path="bfr-3d-videos/raw-videos/101/20260513/demo.mp4",
        part_size=10485760,
        total_parts=2,
        status="initiated",
    )

    with patch.object(ReconstructionManager, "_require_upload_session", AsyncMock(return_value=upload_session)), \
         patch.object(ReconstructionManager, "_generate_multipart_upload_urls", AsyncMock(return_value=[
             {"part_number": 1, "url": "/bfr-3d-videos/demo.mp4?partNumber=1", "expires_at": "2026-05-20T10:00:00"}
         ])) as generate_mock:
        result = asyncio.run(
            ReconstructionManager.get_source_video_upload_urls(
                upload_session_id=9001,
                part_numbers=[1],
            )
        )

    generate_mock.assert_awaited_once_with(
        bucket="bfr-3d-videos",
        object_name="raw-videos/101/20260513/demo.mp4",
        upload_id="upload-1",
        part_numbers=[1],
    )
    assert result == {
        "upload_session_id": 9001,
        "upload_urls": [
            {"part_number": 1, "url": "/bfr-3d-videos/demo.mp4?partNumber=1", "expires_at": "2026-05-20T10:00:00"}
        ],
    }


def test_complete_multipart_upload_is_callable_as_classmethod():
    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service._get_minio_helpers") as helpers_mock, \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.run_sync", AsyncMock(side_effect=lambda fn: fn())):
        minio_instance = SimpleNamespace(client=SimpleNamespace(_complete_multipart_upload=lambda **_kwargs: None))
        helpers_mock.return_value = (None, None, minio_instance, None, None)

        asyncio.run(
            ReconstructionManager._complete_multipart_upload(
                bucket="bfr-3d-videos",
                object_name="raw-videos/101/demo.mp4",
                upload_id="upload-1",
                parts=[{"part_number": 1, "etag": "etag-1"}],
                total_parts=1,
            )
        )


def test_complete_source_video_multipart_upload_persists_item_after_complete():
    upload_session = SimpleNamespace(
        id=9001,
        item_id=101,
        storage_mode="remote",
        upload_id="upload-1",
        bucket="bfr-3d-videos",
        object_name="raw-videos/101/20260513/demo.mp4",
        video_path="bfr-3d-videos/raw-videos/101/20260513/demo.mp4",
        file_name="demo.mp4",
        file_size=1024,
        content_type="video/mp4",
        height=1.0,
        length=2.0,
        width=3.0,
        weight=4.0,
        total_parts=1,
        status="initiated",
    )
    persisted_item = SimpleNamespace(
        id=101,
        item_name="配件A",
        item_code="A001",
        height=1.0,
        long=2.0,
        width=3.0,
        weight=4.0,
        source_video_path="bfr-3d-videos/raw-videos/101/20260513/demo.mp4",
        source_video_filename="demo.mp4",
        source_video_size=1024,
        source_video_content_type="video/mp4",
        source_video_updated_at=datetime(2026, 5, 13, 10, 0, 0),
    )
    session = AsyncMock()

    with patch.object(ReconstructionManager, "_require_upload_session", AsyncMock(return_value=upload_session)), \
         patch.object(ReconstructionManager, "_list_multipart_uploaded_parts", AsyncMock(return_value=[
             {"part_number": 1, "size": 1024, "etag": "etag-1"}
         ])) as list_parts_mock, \
         patch.object(ReconstructionManager, "_complete_multipart_upload", AsyncMock()) as complete_mock, \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionVideoUploadSession.get_by_id", AsyncMock(return_value=upload_session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.update_source_video", AsyncMock()) as update_source_video_mock, \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionVideoUploadSession.mark_completed", AsyncMock()) as mark_completed_mock, \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.get_item_by_id", AsyncMock(return_value=persisted_item)):
        result = asyncio.run(
            ReconstructionManager.complete_source_video_multipart_upload(
                upload_session_id=9001,
            )
        )

    list_parts_mock.assert_awaited_once_with(
        bucket="bfr-3d-videos",
        object_name="raw-videos/101/20260513/demo.mp4",
        upload_id="upload-1",
    )
    complete_mock.assert_awaited_once()
    update_source_video_mock.assert_awaited_once()
    mark_completed_mock.assert_awaited_once()
    assert result["video_path"] == "bfr-3d-videos/raw-videos/101/20260513/demo.mp4"


def test_abort_source_video_multipart_upload_marks_session_aborted():
    upload_session = SimpleNamespace(
        id=9001,
        item_id=101,
        storage_mode="remote",
        upload_id="upload-1",
        bucket="bfr-3d-videos",
        object_name="raw-videos/101/20260513/demo.mp4",
        status="initiated",
    )
    session = AsyncMock()

    with patch.object(ReconstructionManager, "_require_upload_session", AsyncMock(return_value=upload_session)), \
         patch.object(ReconstructionManager, "_abort_multipart_upload", AsyncMock()) as abort_mock, \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionVideoUploadSession.mark_aborted", AsyncMock()) as mark_aborted_mock:
        result = asyncio.run(ReconstructionManager.abort_source_video_multipart_upload(upload_session_id=9001))

    abort_mock.assert_awaited_once()
    mark_aborted_mock.assert_awaited_once()
    assert result == {"item_id": 101, "message": "原始视频分片上传已取消"}


def test_complete_local_source_video_upload_does_not_bind_item_info(tmp_path):
    upload_session = SimpleNamespace(
        id=9001,
        item_id=101,
        storage_mode="local",
        local_status="uploading",
        remote_status="pending",
        local_dir=str(tmp_path / "9001"),
        file_name="demo.mp4",
        total_parts=2,
        status="initiated",
    )

    with patch.object(ReconstructionManager, "_require_upload_session", AsyncMock(return_value=upload_session)), \
         patch.object(ReconstructionManager, "_complete_local_source_video_upload", AsyncMock(return_value={"item_id": 101, "message": "本地分片合并完成，等待 MinIO 同步"})) as complete_mock:
        result = asyncio.run(
            ReconstructionManager.complete_source_video_multipart_upload(upload_session_id=9001)
        )

    complete_mock.assert_awaited_once_with(upload_session)
    assert "等待 MinIO 同步" in result["message"]


def test_upload_source_video_local_part_allows_unexpected_part_size(tmp_path):
    storage = LocalUploadStorage(tmp_path)
    storage.ensure_session_dirs(9001)
    upload_session = SimpleNamespace(
        id=9001,
        item_id=101,
        storage_mode="local",
        total_parts=3,
        part_size=10,
        file_size=25,
        local_dir=str(tmp_path / "9001"),
    )
    upload_file = _UploadFileStub(b"x" * 25)
    session = AsyncMock()

    with patch.object(ReconstructionManager, "_require_upload_session", AsyncMock(return_value=upload_session)), \
         patch.object(ReconstructionManager, "_get_local_upload_storage", return_value=storage), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionVideoUploadSession.update_sync_state", AsyncMock()) as update_state_mock:
        result = asyncio.run(
            ReconstructionManager.upload_source_video_local_part(
                upload_session_id=9001,
                part_number=1,
                file=upload_file,
            )
        )

    update_state_mock.assert_awaited_once()
    assert result["size"] == 25


def test_upload_source_video_local_part_accepts_expected_last_part_size(tmp_path):
    storage = LocalUploadStorage(tmp_path)
    storage.ensure_session_dirs(9001)
    upload_session = SimpleNamespace(
        id=9001,
        item_id=101,
        storage_mode="local",
        total_parts=3,
        part_size=10,
        file_size=25,
        local_dir=str(tmp_path / "9001"),
    )
    upload_file = _UploadFileStub(b"x" * 5)
    session = AsyncMock()

    with patch.object(ReconstructionManager, "_require_upload_session", AsyncMock(return_value=upload_session)), \
         patch.object(ReconstructionManager, "_get_local_upload_storage", return_value=storage), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionVideoUploadSession.update_sync_state", AsyncMock()) as update_state_mock:
        result = asyncio.run(
            ReconstructionManager.upload_source_video_local_part(
                upload_session_id=9001,
                part_number=3,
                file=upload_file,
            )
        )

    update_state_mock.assert_awaited_once()
    assert result["size"] == 5


def test_upload_source_video_part_local_keeps_legacy_behavior():
    upload_session = SimpleNamespace(
        id=9001,
        item_id=101,
        storage_mode="local",
        total_parts=3,
        part_size=10,
        file_size=25,
        local_dir="/tmp/demo",
    )
    upload_file = _UploadFileStub(b"x" * 5)

    with patch.object(ReconstructionManager, "_require_upload_session", AsyncMock(return_value=upload_session)), \
         patch.object(ReconstructionManager, "upload_source_video_local_part", AsyncMock(return_value={
        "upload_session_id": 9001,
        "part_number": 3,
        "size": 5,
        "etag": "",
        "message": "分片上传成功",
    })) as local_mock:
        result = asyncio.run(
            ReconstructionManager.upload_source_video_part(
                upload_session_id=9001,
                part_number=3,
                file=upload_file,
            )
        )

    local_mock.assert_awaited_once()
    assert result["etag"] == ""


def test_upload_source_video_part_remote_proxies_bytes_to_minio():
    upload_session = SimpleNamespace(
        id=9001,
        item_id=101,
        storage_mode="remote",
        total_parts=3,
        part_size=10,
        file_size=25,
        upload_id="upload-1",
        bucket="bfr-3d-videos",
        object_name="raw-videos/101/demo.mp4",
        expires_at=datetime(2026, 6, 20, 10, 0, 0),
    )
    upload_file = _UploadFileStub(b"x" * 10)
    session = AsyncMock()

    with patch.object(ReconstructionManager, "_require_upload_session", AsyncMock(return_value=upload_session)), \
         patch.object(ReconstructionManager, "_upload_part", AsyncMock(return_value="etag-1")) as upload_part_mock, \
         patch.object(ReconstructionManager, "_get_local_upload_storage") as local_storage_mock, \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionVideoUploadSession.update_sync_state", AsyncMock()) as update_state_mock, \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.datetime") as datetime_mock:
        datetime_mock.utcnow.return_value = datetime(2026, 6, 16, 10, 0, 0)

        result = asyncio.run(
            ReconstructionManager.upload_source_video_part(
                upload_session_id=9001,
                part_number=1,
                file=upload_file,
            )
        )

    upload_part_mock.assert_awaited_once_with(
        bucket="bfr-3d-videos",
        object_name="raw-videos/101/demo.mp4",
        upload_id="upload-1",
        part_number=1,
        data=b"x" * 10,
    )
    update_state_mock.assert_awaited_once()
    local_storage_mock.assert_not_called()
    assert result["etag"] == "etag-1"


def test_check_minio_and_sync_local_uploads_returns_unavailable_when_env_missing():
    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.minio_env_configured", return_value=False):
        result = asyncio.run(ReconstructionManager.check_minio_and_sync_local_uploads())

    assert result["available"] is False
    assert result["total_pending"] == 0


def test_check_minio_and_sync_local_uploads_binds_item_after_remote_sync():
    pending_session = SimpleNamespace(
        id=9001,
        item_id=101,
        storage_mode="local",
        local_status="completed",
        remote_status="pending",
        merged_file_path="/tmp/demo.mp4",
        part_size=10,
        file_name="demo.mp4",
        file_size=20,
        content_type="video/mp4",
        height=1.0,
        length=2.0,
        width=3.0,
        weight=4.0,
    )
    session = AsyncMock()

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.minio_env_configured", return_value=True), \
         patch.object(ReconstructionManager, "_minio_health_check", AsyncMock(return_value=True)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionVideoUploadSession.list_local_sessions_pending_remote_sync", AsyncMock(return_value=[pending_session])), \
         patch.object(ReconstructionManager, "_sync_local_session_to_remote", AsyncMock(return_value=True)) as sync_mock:
        result = asyncio.run(ReconstructionManager.check_minio_and_sync_local_uploads())

    sync_mock.assert_awaited_once_with(pending_session, session)
    assert result["available"] is True
    assert result["synced_count"] == 1
