import importlib
import logging
from pathlib import Path
import uuid


def _refresh_runtime_paths():
    from csrcqsf.core.runtime_paths import get_runtime_paths

    return get_runtime_paths(refresh=True)


def test_vector_config_uses_runtime_state_and_log_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("APP_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("DINOV2_PATCH_TOKENS_DIR", raising=False)
    monkeypatch.delenv("INDEXING_CHECKPOINT_FILE", raising=False)
    monkeypatch.delenv("INDEXING_LOG_DIR", raising=False)
    _refresh_runtime_paths()

    from csrcqsf.modules.railway_parts.vector_search.config.env_config import (
        VectorDBConfig,
    )

    config = VectorDBConfig()

    assert config.dinov2_patch_tokens_dir == str(
        tmp_path / "state" / "vector_db" / "patch_tokens"
    )
    assert config.indexing_checkpoint_file == str(
        tmp_path / "state" / "vector_db" / "checkpoint.json"
    )
    assert config.indexing_log_dir == str(tmp_path / "logs" / "vector_db")


def test_vector_logger_defaults_to_runtime_log_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_LOG_DIR", str(tmp_path / "logs"))
    _refresh_runtime_paths()
    logger_module = importlib.import_module(
        "csrcqsf.modules.railway_parts.vector_search.utils.logger"
    )
    logger_name = f"runtime-path-test-{uuid.uuid4()}"

    logger = logger_module.setup_logger(logger_name)

    file_handlers = [
        handler for handler in logger.handlers if isinstance(handler, logging.FileHandler)
    ]
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename).parent == tmp_path / "logs" / "vector_db"
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def test_reconstruction_upload_storage_uses_runtime_state_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    _refresh_runtime_paths()

    from csrcqsf.modules.railway_parts.services.reconstruction_service import (
        ReconstructionManager,
    )

    storage = ReconstructionManager._get_local_upload_storage()

    assert storage.base_dir == tmp_path / "state" / "reconstruction_uploads"
