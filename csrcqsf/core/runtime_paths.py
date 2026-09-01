from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    app_root: Path
    log_dir: Path
    app_log_dir: Path
    temp_dir: Path
    state_dir: Path
    patch_tokens_dir: Path
    indexing_checkpoint_file: Path
    indexing_log_dir: Path
    reconstruction_state_dir: Path


def default_app_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_path(raw_value: str | None, default: Path, app_root: Path) -> Path:
    # 相对路径统一基于应用根目录，避免容器工作目录变化后数据写到未知位置。
    candidate = Path(raw_value.strip()) if raw_value and raw_value.strip() else default
    if not candidate.is_absolute():
        candidate = app_root / candidate
    return candidate.resolve()


def resolve_runtime_paths(
    env: Mapping[str, str] | None = None,
    *,
    app_root: Path | None = None,
) -> RuntimePaths:
    """集中解析日志、临时文件和持久化状态目录。"""
    values = os.environ if env is None else env
    root = (app_root or default_app_root()).resolve()
    log_dir = _resolve_path(values.get("APP_LOG_DIR"), root / "logs", root)
    temp_dir = _resolve_path(values.get("TEMP_DIR"), root / "temp", root)
    state_dir = _resolve_path(values.get("STATE_DIR"), root / "state", root)

    return RuntimePaths(
        app_root=root,
        log_dir=log_dir,
        app_log_dir=log_dir / "app",
        temp_dir=temp_dir,
        state_dir=state_dir,
        patch_tokens_dir=_resolve_path(
            values.get("DINOV2_PATCH_TOKENS_DIR"),
            state_dir / "vector_db" / "patch_tokens",
            root,
        ),
        indexing_checkpoint_file=_resolve_path(
            values.get("INDEXING_CHECKPOINT_FILE"),
            state_dir / "vector_db" / "checkpoint.json",
            root,
        ),
        indexing_log_dir=_resolve_path(
            values.get("INDEXING_LOG_DIR"),
            log_dir / "vector_db",
            root,
        ),
        reconstruction_state_dir=state_dir / "reconstruction",
    )


_runtime_paths: RuntimePaths | None = None


def get_runtime_paths(*, refresh: bool = False) -> RuntimePaths:
    # 配置加载完成后可强制刷新一次，后续调用共享同一组确定路径。
    global _runtime_paths
    if refresh or _runtime_paths is None:
        _runtime_paths = resolve_runtime_paths()
    return _runtime_paths


def ensure_runtime_directories(
    paths: RuntimePaths | None = None,
    *,
    include_log_dirs: bool = True,
) -> RuntimePaths:
    """在业务启动前创建会被索引和重构流程写入的目录。"""
    resolved = paths or get_runtime_paths()
    directories = [
        resolved.temp_dir,
        resolved.patch_tokens_dir,
        resolved.indexing_checkpoint_file.parent,
        resolved.reconstruction_state_dir,
    ]
    if include_log_dirs:
        directories[:0] = [resolved.app_log_dir, resolved.indexing_log_dir]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    return resolved
