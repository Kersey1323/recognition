from pathlib import Path


def test_phase_sixteen_item_and_index_service_modules_exist():
    assert Path("csrcqsf/modules/railway_parts/services/item_service.py").exists()
    assert Path("csrcqsf/modules/railway_parts/services/parts_index_service.py").exists()


def test_phase_sixteen_parts_service_keeps_compat_facade_and_delegates_item_and_index_logic():
    text = Path("csrcqsf/modules/railway_parts/services/parts_service.py").read_text(
        encoding="utf-8"
    )

    assert "def _runtime_context" in text
    assert "item_service.bind_runtime_dependencies" in text
    assert "item_service.list_item" in text
    assert "item_service.get_item_detail" in text
    assert "parts_index_service.bind_runtime_dependencies" in text
    assert "parts_index_service.rebuild_v2_index" in text
    assert "parts_index_service.statistics" in text


def test_phase_sixteen_parts_service_line_count_is_reduced_after_item_and_index_split():
    line_count = len(
        Path("csrcqsf/modules/railway_parts/services/parts_service.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert line_count < 700, line_count
