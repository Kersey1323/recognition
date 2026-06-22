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


def test_auto_processor_service_defers_segment_anything_import():
    text = Path(
        "csrcqsf/modules/railway_parts/services/auto_processor_service.py"
    ).read_text(encoding="utf-8")

    lines = text.splitlines()
    assert not any(
        line.strip() == "from segment_anything import SamAutomaticMaskGenerator"
        for line in lines[:30]
    )


def test_cpu_dockerfile_no_longer_installs_local_torch_runtime():
    text = Path("docker/Dockerfile.cpu").read_text(encoding="utf-8")

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
        'CMD ["python", "main.py"]',
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
