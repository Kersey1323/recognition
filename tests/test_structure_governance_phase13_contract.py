from pathlib import Path


def test_phase_thirteen_search_and_review_service_modules_exist():
    assert Path(
        "csrcqsf/modules/railway_parts/services/search_service.py"
    ).exists()
    assert Path(
        "csrcqsf/modules/railway_parts/services/review_ticket_service.py"
    ).exists()


def test_phase_thirteen_parts_search_service_keeps_shared_helpers_and_delegates_domain_logic():
    text = Path(
        "csrcqsf/modules/railway_parts/services/parts_search_service.py"
    ).read_text(encoding="utf-8")

    assert "def bind_runtime_dependencies" in text
    assert "search_service.search_v2_by_text" in text
    assert "search_service.submit_v2_search_feedback" in text
    assert "review_ticket_service.list_v2_search_review_tickets" in text
    assert "review_ticket_service.update_v2_search_review_ticket" in text


def test_phase_thirteen_parts_search_service_line_count_is_reduced_after_domain_split():
    line_count = len(
        Path("csrcqsf/modules/railway_parts/services/parts_search_service.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert line_count < 900, line_count
