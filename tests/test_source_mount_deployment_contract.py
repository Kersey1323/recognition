from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "dockerfile", ["Dockerfile", "Dockerfile.vendor", "docker/Dockerfile"]
)
def test_image_uses_package_entry_and_only_copies_business_package(dockerfile):
    text = Path(dockerfile).read_text(encoding="utf-8")

    assert "COPY csrcqsf/ /app/csrcqsf/" in text
    assert 'CMD ["python", "-m", "csrcqsf"]' in text
    assert "COPY . /app" not in text
    assert "uv sync --frozen --active --no-dev\n" not in text


@pytest.mark.parametrize(
    "dockerfile", ["Dockerfile", "Dockerfile.vendor", "docker/Dockerfile"]
)
def test_image_prepares_all_writable_runtime_directories(dockerfile):
    text = Path(dockerfile).read_text(encoding="utf-8")

    for path in (
        "/app/logs/app",
        "/app/logs/vector_db",
        "/app/temp",
        "/app/state/vector_db/patch_tokens",
        "/app/state/reconstruction",
    ):
        assert path in text


def test_deployment_mounts_complete_business_package_read_only():
    text = Path("scripts/deployment/run_docker_deployment.sh").read_text(
        encoding="utf-8"
    )

    assert (
        'HOST_SOURCE_DIR="${HOST_SOURCE_DIR:-/data/recognition-service/csrcqsf}"'
        in text
    )
    assert '[[ -f "${HOST_SOURCE_DIR}/__init__.py" ]]' in text
    assert '"${HOST_SOURCE_DIR}:/app/csrcqsf:ro"' in text
    assert "RECOGNITION_MAIN_SOURCE_HOST_PATH=${HOST_SOURCE_DIR}" in text


def test_deployment_env_uses_absolute_writable_runtime_paths():
    text = Path(".env.deployment").read_text(encoding="utf-8")

    for setting in (
        "APP_LOG_DIR=/app/logs",
        "TEMP_DIR=/app/temp",
        "STATE_DIR=/app/state",
        "DINOV2_PATCH_TOKENS_DIR=/app/state/vector_db/patch_tokens",
        "INDEXING_CHECKPOINT_FILE=/app/state/vector_db/checkpoint.json",
        "INDEXING_LOG_DIR=/app/logs/vector_db",
    ):
        assert setting in text


def test_root_entrypoints_are_removed():
    assert not Path("main.py").exists()
    assert not Path("globals_vars.py").exists()


def test_business_package_has_no_root_module_dependency():
    offenders = [
        path
        for path in Path("csrcqsf").rglob("*.py")
        if "globals_vars" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
