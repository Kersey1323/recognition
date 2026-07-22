import importlib
import sys


def test_settings_exposes_reconstruction_file_bucket():
    from csrcqsf.core.settings import minio_reconstruction_file_bucket

    assert minio_reconstruction_file_bucket == "bfr-reconstruction-files"


def test_parse_minio_path_recognizes_reconstruction_file_bucket():
    from csrcqsf.infra.storage.minio import parse_minio_path

    bucket, object_name = parse_minio_path(
        "bfr-reconstruction-files/results/1935558010375340032/task-id/point_cloud.ply"
    )

    assert bucket == "bfr-reconstruction-files"
    assert object_name == "results/1935558010375340032/task-id/point_cloud.ply"


def test_settings_no_longer_exposes_local_model_path_fields(monkeypatch):
    monkeypatch.setenv("MODEL_DIR", "/tmp/models-root")
    monkeypatch.setenv("SAM_MODEL_PATH", "legacy-sam/model.pth")
    monkeypatch.setenv("SAM3_MODEL_PATH", "sam3")

    sys.modules.pop("csrcqsf.core.settings", None)
    settings = importlib.import_module("csrcqsf.core.settings")

    assert not hasattr(settings, "model_dir")
    assert not hasattr(settings, "sam3_model_path")
    assert not hasattr(settings, "SAM_MODEL")
