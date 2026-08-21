import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_logging_probe(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["APP_LOG_DIR"] = str(tmp_path / "logs")
    env["TEMP_DIR"] = str(tmp_path / "temp")
    env["STATE_DIR"] = str(tmp_path / "state")
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_package_logger_keeps_console_source_location(tmp_path):
    result = _run_logging_probe(
        tmp_path,
        "from csrcqsf.core.logging_config import logger; "
        "logger.info('probe-message')",
    )

    assert result.returncode == 0, result.stderr
    assert "INFO" in result.stdout
    assert "probe-message" in result.stdout
    assert "<string>" in result.stdout


def test_package_logger_writes_daily_file_sink(tmp_path):
    result = _run_logging_probe(
        tmp_path,
        "from csrcqsf.core.logging_config import logger; "
        "logger.debug('file-probe'); logger.complete()",
    )

    assert result.returncode == 0, result.stderr
    log_files = list((tmp_path / "logs" / "app").glob("app_*.log"))
    assert len(log_files) == 1
    assert "file-probe" in log_files[0].read_text(encoding="utf-8")


def test_configure_logging_is_idempotent(tmp_path):
    result = _run_logging_probe(
        tmp_path,
        "from csrcqsf.core.logging_config import configure_logging, logger; "
        "before=len(logger._core.handlers); configure_logging(); "
        "after=len(logger._core.handlers); print(f'HANDLERS={before}:{after}')",
    )

    assert result.returncode == 0, result.stderr
    assert "HANDLERS=2:2" in result.stdout


def test_file_sink_failure_keeps_console_logging(tmp_path):
    blocked_log_path = tmp_path / "blocked"
    blocked_log_path.write_text("not-a-directory", encoding="utf-8")
    env = os.environ.copy()
    env["APP_LOG_DIR"] = str(blocked_log_path)
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from csrcqsf.core.logging_config import logger; "
            "logger.info('console-still-available')",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "文件日志初始化失败" in result.stdout
    assert "console-still-available" in result.stdout
