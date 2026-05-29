from pathlib import Path


def test_phase_twelve_reconstruction_task_service_module_exists():
    assert Path(
        "csrcqsf/modules/railway_parts/services/reconstruction_task_service.py"
    ).exists()


def test_phase_twelve_reconstruction_service_keeps_public_manager_entrypoint_and_task_wrapper_installer():
    text = Path(
        "csrcqsf/modules/railway_parts/services/reconstruction_service.py"
    ).read_text(encoding="utf-8")

    assert "class ReconstructionManager" in text
    assert "reconstruction_task_service" in text
    assert "_install_reconstruction_task_service_methods" in text
    assert '"submit_video_task"' in text
    assert '"get_task_status"' in text
    assert '"upload_reconstruction_result"' in text


def test_phase_twelve_routes_still_import_public_manager_from_reconstruction_service():
    text = Path(
        "csrcqsf/modules/railway_parts/routes/reconstruction_routes.py"
    ).read_text(encoding="utf-8")

    assert (
        "from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager"
        in text
    )


def test_phase_twelve_reconstruction_service_line_count_is_reduced_after_task_split():
    line_count = len(
        Path("csrcqsf/modules/railway_parts/services/reconstruction_service.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert line_count < 900, line_count
