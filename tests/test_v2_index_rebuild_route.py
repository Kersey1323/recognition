from pathlib import Path


def test_v2_index_rebuild_route_accepts_rebuild_existing_flag():
    text = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    assert "async def rebuild_v2_index(" in text
    assert "rebuild_existing: bool = False" in text


def test_v2_index_rebuild_route_passes_rebuild_existing_to_background_and_sync_paths():
    text = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    assert "rebuild_existing=rebuild_existing" in text
    assert "'rebuild_existing': rebuild_existing" in text
    assert "rebuild_existing=rebuild_existing," in text
