from csrcqsf.core import settings


def test_viewer360_defaults_match_capture_protocol():
    assert settings.viewer360_enabled is True
    assert settings.viewer360_auto_create_after_video_upload is False
    assert settings.viewer360_max_concurrent_tasks == 1
    assert settings.viewer360_row_count == 4
    assert settings.viewer360_row_directions == (1, -1, 1, -1)
    assert settings.viewer360_transition_seconds == 2.0
    assert settings.viewer360_frames_per_row == 72


def test_viewer360_runtime_stays_cpu_only():
    import inspect
    from csrcqsf.modules.railway_parts.services import viewer360_pipeline

    source = inspect.getsource(viewer360_pipeline)
    assert "import torch" not in source
    assert "from torch" not in source
    assert "auto_segmentation" not in source
