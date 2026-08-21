from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from csrcqsf.core.runtime_paths import default_app_root


def load_explicit_env_file(*, app_root: Path | None = None) -> Path | None:
    raw_path = os.getenv("RECOGNITION_ENV_FILE", "").strip()
    if not raw_path:
        return None

    root = (app_root or default_app_root()).resolve()
    env_path = Path(raw_path)
    if not env_path.is_absolute():
        env_path = root / env_path
    env_path = env_path.resolve()
    load_dotenv(env_path, override=False)
    return env_path
