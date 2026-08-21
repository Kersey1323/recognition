import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_get_app_port_reads_environment(monkeypatch):
    from csrcqsf.__main__ import get_app_port

    monkeypatch.setenv("APP_PORT", "7001")
    assert get_app_port() == 7001


def test_get_app_port_uses_default_for_invalid_value(monkeypatch):
    from csrcqsf.__main__ import DEFAULT_APP_PORT, get_app_port

    monkeypatch.setenv("APP_PORT", "invalid")
    assert get_app_port() == DEFAULT_APP_PORT == 65432


def test_importing_package_entrypoint_does_not_import_fastapi_app(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import csrcqsf.__main__; "
            "print('APP_IMPORTED=' + str('csrcqsf.core.app' in sys.modules))",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "APP_IMPORTED=False" in result.stdout
