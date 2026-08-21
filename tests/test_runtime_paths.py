import os
from pathlib import Path
import subprocess
import sys


def test_resolve_runtime_paths_uses_app_root_defaults(tmp_path):
    from csrcqsf.core.runtime_paths import resolve_runtime_paths

    paths = resolve_runtime_paths({}, app_root=tmp_path)

    assert paths.app_root == tmp_path
    assert paths.log_dir == tmp_path / "logs"
    assert paths.app_log_dir == tmp_path / "logs" / "app"
    assert paths.temp_dir == tmp_path / "temp"
    assert paths.state_dir == tmp_path / "state"
    assert paths.patch_tokens_dir == tmp_path / "state" / "vector_db" / "patch_tokens"
    assert paths.indexing_checkpoint_file == tmp_path / "state" / "vector_db" / "checkpoint.json"
    assert paths.indexing_log_dir == tmp_path / "logs" / "vector_db"
    assert paths.reconstruction_state_dir == tmp_path / "state" / "reconstruction"


def test_relative_overrides_are_resolved_against_app_root(tmp_path):
    from csrcqsf.core.runtime_paths import resolve_runtime_paths

    paths = resolve_runtime_paths(
        {
            "APP_LOG_DIR": "runtime/logs",
            "TEMP_DIR": "runtime/temp",
            "STATE_DIR": "runtime/state",
            "DINOV2_PATCH_TOKENS_DIR": "runtime/patches",
            "INDEXING_CHECKPOINT_FILE": "runtime/checkpoint.json",
            "INDEXING_LOG_DIR": "runtime/index-logs",
        },
        app_root=tmp_path,
    )

    assert paths.log_dir == tmp_path / "runtime" / "logs"
    assert paths.temp_dir == tmp_path / "runtime" / "temp"
    assert paths.state_dir == tmp_path / "runtime" / "state"
    assert paths.patch_tokens_dir == tmp_path / "runtime" / "patches"
    assert paths.indexing_checkpoint_file == tmp_path / "runtime" / "checkpoint.json"
    assert paths.indexing_log_dir == tmp_path / "runtime" / "index-logs"


def test_absolute_overrides_are_preserved(tmp_path):
    from csrcqsf.core.runtime_paths import resolve_runtime_paths

    absolute_log_dir = tmp_path / "absolute-logs"
    paths = resolve_runtime_paths(
        {"APP_LOG_DIR": str(absolute_log_dir)},
        app_root=tmp_path / "app",
    )

    assert paths.log_dir == absolute_log_dir


def test_ensure_runtime_directories_only_creates_writable_runtime_paths(tmp_path):
    from csrcqsf.core.runtime_paths import (
        ensure_runtime_directories,
        resolve_runtime_paths,
    )

    paths = resolve_runtime_paths({}, app_root=tmp_path)
    ensure_runtime_directories(paths)

    assert paths.app_log_dir.is_dir()
    assert paths.indexing_log_dir.is_dir()
    assert paths.temp_dir.is_dir()
    assert paths.patch_tokens_dir.is_dir()
    assert paths.reconstruction_state_dir.is_dir()
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "models").exists()
    assert not (tmp_path / "tests").exists()


def test_load_explicit_env_file_uses_app_root_and_does_not_override(monkeypatch, tmp_path):
    from csrcqsf.core.environment import load_explicit_env_file

    env_file = tmp_path / "local.env"
    env_file.write_text(
        "RUNTIME_PATH_TEST_FROM_FILE=from-file\n"
        "RUNTIME_PATH_TEST_EXISTING=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RECOGNITION_ENV_FILE", "local.env")
    monkeypatch.setenv("RUNTIME_PATH_TEST_EXISTING", "from-process")
    monkeypatch.delenv("RUNTIME_PATH_TEST_FROM_FILE", raising=False)

    loaded_path = load_explicit_env_file(app_root=tmp_path)

    assert loaded_path == env_file
    assert os.getenv("RUNTIME_PATH_TEST_FROM_FILE") == "from-file"
    assert os.getenv("RUNTIME_PATH_TEST_EXISTING") == "from-process"


def test_load_explicit_env_file_is_disabled_by_default(monkeypatch, tmp_path):
    from csrcqsf.core.environment import load_explicit_env_file

    monkeypatch.delenv("RECOGNITION_ENV_FILE", raising=False)
    (tmp_path / ".env").write_text("SHOULD_NOT_LOAD=yes\n", encoding="utf-8")
    monkeypatch.delenv("SHOULD_NOT_LOAD", raising=False)

    assert load_explicit_env_file(app_root=tmp_path) is None
    assert os.getenv("SHOULD_NOT_LOAD") is None


def test_default_application_root_is_parent_of_package():
    from csrcqsf.core.runtime_paths import default_app_root

    assert default_app_root() == Path(__file__).resolve().parents[1]


def test_settings_does_not_load_cwd_dotenv_without_explicit_file(tmp_path):
    (tmp_path / ".env").write_text("IMPLICIT_DOTENV_PROBE=loaded\n", encoding="utf-8")
    env = os.environ.copy()
    env.pop("RECOGNITION_ENV_FILE", None)
    env.pop("IMPLICIT_DOTENV_PROBE", None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; import csrcqsf.core.settings; "
            "print(os.getenv('IMPLICIT_DOTENV_PROBE', 'missing'))",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("missing")


def test_settings_loads_only_explicit_env_file(tmp_path):
    env_file = tmp_path / "runtime.env"
    env_file.write_text("EXPLICIT_DOTENV_PROBE=loaded\n", encoding="utf-8")
    env = os.environ.copy()
    env["RECOGNITION_ENV_FILE"] = str(env_file)
    env.pop("EXPLICIT_DOTENV_PROBE", None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; import csrcqsf.core.settings; "
            "print(os.getenv('EXPLICIT_DOTENV_PROBE', 'missing'))",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("loaded")
