from pathlib import Path


def test_pyproject_removes_local_model_runtime_dependencies_from_main_service():
    text = Path("pyproject.toml").read_text(encoding="utf-8")

    forbidden_fragments = (
        '"segment-anything"',
        '"scikit-learn>=',
        '"timm>=',
        '"torch>=',
        '"torchvision>=',
        '"transformers>=',
        'name = "pytorch-cu118"',
        'torch = { index = "pytorch-cu118" }',
        'torchvision = { index = "pytorch-cu118" }',
    )

    for fragment in forbidden_fragments:
        assert fragment not in text, fragment


def test_legacy_milvus_compat_module_no_longer_imports_local_model_stack_at_import_time():
    text = Path(
        "csrcqsf/modules/railway_parts/integrations/milvus_state_manager.py"
    ).read_text(encoding="utf-8")

    forbidden_fragments = (
        "import timm",
        "import torch",
        "from PIL import Image",
        "from sklearn.preprocessing import normalize",
        "class DINOv2Extractor",
    )

    for fragment in forbidden_fragments:
        assert fragment not in text, fragment


def test_obsolete_local_sam_auto_processor_is_removed():
    assert not Path(
        "csrcqsf/modules/railway_parts/services/auto_processor_service.py"
    ).exists()

    routes = Path(
        "csrcqsf/modules/railway_parts/routes/parts_routes.py"
    ).read_text(encoding="utf-8")
    assert "auto_processor_service" not in routes
    assert "'/auto_segment'" not in routes
    assert "'/segmented_images/{item_id}'" not in routes


def test_main_service_source_does_not_import_segment_anything():
    source_root = Path("csrcqsf")
    offenders = [
        str(path)
        for path in source_root.rglob("*.py")
        if "segment_anything" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_vector_collection_config_does_not_contain_local_gpu_model_settings():
    text = Path(
        "csrcqsf/modules/railway_parts/vector_search/config/vector_db.ini"
    ).read_text(encoding="utf-8")
    for fragment in ("device =", "model_path =", "[sam3]"):
        assert fragment not in text


def test_main_dockerfile_no_longer_installs_local_torch_runtime():
    text = Path("docker/Dockerfile").read_text(encoding="utf-8")

    forbidden_fragments = (
        "ARG PYTORCH_CPU_INDEX_URL",
        "ARG PYTORCH_CPU_FALLBACK_INDEX_URL",
        "--no-install-package torch",
        "--no-install-package torchvision",
        "torch==2.7.1+cpu",
        "torchvision==0.22.1+cpu",
    )

    for fragment in forbidden_fragments:
        assert fragment not in text, fragment


def test_main_dockerfile_uses_cpu_python_base_for_business_service():
    text = Path("docker/Dockerfile").read_text(encoding="utf-8")

    required_fragments = (
        "FROM python:3.10-slim",
        "ARG APT_MIRROR",
        "ARG PIP_INDEX_URL",
        'CMD ["python", "-m", "csrcqsf"]',
    )
    forbidden_fragments = (
        "nvidia/cuda",
        "/etc/apk/repositories",
        "apk add",
        "torch==",
        "torchvision==",
        "download.pytorch.org",
    )

    for fragment in required_fragments:
        assert fragment in text, fragment

    for fragment in forbidden_fragments:
        assert fragment not in text, fragment


def test_main_dockerfile_keeps_build_tools_out_of_runtime_image():
    text = Path("docker/Dockerfile").read_text(encoding="utf-8")

    required_fragments = (
        "FROM python:3.10-slim AS builder",
        "FROM python:3.10-slim AS runtime",
        "COPY --from=builder /opt/venv /opt/venv",
        "COPY csrcqsf/ /app/csrcqsf/",
    )
    for fragment in required_fragments:
        assert fragment in text, fragment

    runtime_stage = text.split("FROM python:3.10-slim AS runtime", 1)[1]
    for fragment in (" git ", " curl ", "libgl1", "libglib2.0-0", " pip install ", "COPY . /app"):
        assert fragment not in runtime_stage, fragment


def test_docker_context_excludes_non_runtime_project_artifacts():
    text = Path(".dockerignore").read_text(encoding="utf-8")

    for entry in ("docs/", "tests/", "scripts/", "tools/", ".claude/", "dist/"):
        assert entry in text.splitlines(), entry


def test_pyproject_keeps_main_service_runtime_dependencies_needed_by_cpu_business():
    text = Path("pyproject.toml").read_text(encoding="utf-8")

    required_fragments = (
        '"requests>=',
        '"minio>=',
        '"python-dotenv>=',
        '"grpcio>=',
        '"numpy>=',
        '"pillow>=',
        '"opencv-python-headless>=',
        '"pandas>=',
        '"openpyxl>=',
        '"cryptography>=',
    )

    for fragment in required_fragments:
        assert fragment in text, fragment
