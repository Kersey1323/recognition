from pathlib import Path


def test_phase_eleven_reconstruction_video_service_module_exists():
    assert Path(
        "csrcqsf/modules/railway_parts/services/reconstruction_video_service.py"
    ).exists()


def test_phase_eleven_reconstruction_service_keeps_public_manager_entrypoint_and_delegates_video_logic():
    text = Path(
        "csrcqsf/modules/railway_parts/services/reconstruction_service.py"
    ).read_text(encoding="utf-8")

    assert "class ReconstructionManager" in text
    assert "reconstruction_video_service.init_source_video_multipart_upload" in text
    assert "reconstruction_video_service.check_minio_and_sync_local_uploads" in text
    assert "reconstruction_video_service.delete_source_video" in text


def test_phase_eleven_routes_still_import_public_manager_from_reconstruction_service():
    text = Path(
        "csrcqsf/modules/railway_parts/routes/reconstruction_routes.py"
    ).read_text(encoding="utf-8")

    assert (
        "from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager"
        in text
    )


def test_phase_eleven_reconstruction_service_line_count_is_reduced_after_video_split():
    line_count = len(
        Path("csrcqsf/modules/railway_parts/services/reconstruction_service.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert line_count < 1700, line_count
