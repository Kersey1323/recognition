from pathlib import Path


def test_phase_fourteen_source_video_and_upload_service_modules_exist():
    assert Path(
        "csrcqsf/modules/railway_parts/services/source_video_service.py"
    ).exists()
    assert Path(
        "csrcqsf/modules/railway_parts/services/upload_service.py"
    ).exists()


def test_phase_fourteen_reconstruction_video_service_keeps_shared_helpers_and_delegates_domain_logic():
    text = Path(
        "csrcqsf/modules/railway_parts/services/reconstruction_video_service.py"
    ).read_text(encoding="utf-8")

    assert "def bind_runtime_dependencies" in text
    assert "source_video_service.upload_source_video" in text
    assert "source_video_service.delete_source_video" in text
    assert "upload_service.init_source_video_multipart_upload" in text
    assert "upload_service.check_minio_and_sync_local_uploads" in text


def test_phase_fourteen_reconstruction_video_service_line_count_is_reduced_after_domain_split():
    line_count = len(
        Path("csrcqsf/modules/railway_parts/services/reconstruction_video_service.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert line_count < 800, line_count
