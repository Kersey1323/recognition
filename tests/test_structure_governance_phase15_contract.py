from pathlib import Path


def test_phase_fifteen_reconstruction_result_service_module_exists():
    assert Path(
        "csrcqsf/modules/railway_parts/services/reconstruction_result_service.py"
    ).exists()


def test_phase_fifteen_reconstruction_task_service_keeps_status_logic_and_delegates_result_logic():
    text = Path(
        "csrcqsf/modules/railway_parts/services/reconstruction_task_service.py"
    ).read_text(encoding="utf-8")

    assert "def bind_runtime_dependencies" in text
    assert "reconstruction_result_service.persist_task_result_by_task_id" in text
    assert "reconstruction_result_service.upload_reconstruction_result" in text
    assert "reconstruction_result_service.delete_reconstruction_result" in text


def test_phase_fifteen_reconstruction_task_service_line_count_is_reduced_after_result_split():
    line_count = len(
        Path("csrcqsf/modules/railway_parts/services/reconstruction_task_service.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert line_count < 800, line_count
