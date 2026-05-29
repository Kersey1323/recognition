from pathlib import Path


def test_phase_ten_parts_search_service_module_exists():
    assert Path(
        "csrcqsf/modules/railway_parts/services/parts_search_service.py"
    ).exists()


def test_phase_ten_parts_service_keeps_public_manager_entrypoint_and_delegates_search_logic():
    text = Path(
        "csrcqsf/modules/railway_parts/services/parts_service.py"
    ).read_text(encoding="utf-8")

    assert "class RailwayPartsManager" in text
    assert "parts_search_service.search_v2_by_text" in text
    assert "parts_search_service.submit_v2_search_feedback" in text


def test_phase_ten_routes_still_import_public_manager_from_parts_service():
    for relative_path in [
        "csrcqsf/modules/railway_parts/routes/search_routes.py",
        "csrcqsf/modules/railway_parts/routes/review_ticket_routes.py",
    ]:
        text = Path(relative_path).read_text(encoding="utf-8")
        assert (
            "from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager"
            in text
        ), relative_path


def test_phase_ten_parts_service_line_count_is_reduced_after_search_split():
    line_count = len(
        Path("csrcqsf/modules/railway_parts/services/parts_service.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert line_count < 1500, line_count
