import os

from csrcqsf.core.settings import reconstruction_server_env_configured


GPU_DISABLED_MESSAGE = "当前无GPU，无法使用"
MODEL_DISABLED_MESSAGE = "当前未配置模型，无法使用"
CPU_SAFE_MODE_DISABLED_MESSAGE = "当前为CPU联调模式，CPU模式下已禁用该接口"
RECONSTRUCTION_SERVER_DISABLED_MESSAGE = "未配置重构服务，当前无法使用三维重构能力"


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def cpu_safe_mode_enabled() -> bool:
    return env_flag("ENABLE_CPU_SAFE_MODE", False)


def gpu_reconstruction_enabled() -> bool:
    return env_flag("ENABLE_GPU_RECONSTRUCTION", True)


def segment_model_enabled() -> bool:
    return env_flag("ENABLE_SEGMENT_MODEL", True)


def vector_models_enabled() -> bool:
    return env_flag("ENABLE_VECTOR_MODELS", True)


def ocr_model_enabled() -> bool:
    return env_flag("ENABLE_OCR_MODEL", True)


def reconstruction_execution_enabled() -> bool:
    # 三维重构由独立服务执行，仅在部署方显式提供地址后开放入口。
    return reconstruction_server_env_configured()


def ensure_gpu_reconstruction_enabled() -> None:
    if not reconstruction_execution_enabled():
        raise Exception(RECONSTRUCTION_SERVER_DISABLED_MESSAGE)


def ensure_segment_model_enabled() -> None:
    if not segment_model_enabled():
        raise Exception(MODEL_DISABLED_MESSAGE)


def ensure_vector_models_enabled() -> None:
    # CPU 联调模式会主动禁用高开销向量能力，即使模型开关保持默认开启。
    if cpu_safe_mode_enabled():
        raise Exception(CPU_SAFE_MODE_DISABLED_MESSAGE)
    if not vector_models_enabled():
        raise Exception(MODEL_DISABLED_MESSAGE)


def ensure_ocr_model_enabled() -> None:
    if not ocr_model_enabled():
        raise Exception(MODEL_DISABLED_MESSAGE)
