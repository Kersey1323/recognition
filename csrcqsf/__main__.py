from __future__ import annotations

import os


DEFAULT_APP_PORT = 65432


def get_app_port() -> int:
    raw_port = os.getenv("APP_PORT", str(DEFAULT_APP_PORT)).strip()
    try:
        port = int(raw_port)
    except ValueError:
        return DEFAULT_APP_PORT
    if not 1 <= port <= 65535:
        return DEFAULT_APP_PORT
    return port


def main() -> None:
    from csrcqsf.core.environment import load_explicit_env_file

    load_explicit_env_file()

    from csrcqsf.core.runtime_paths import (
        ensure_runtime_directories,
        get_runtime_paths,
    )

    paths = get_runtime_paths(refresh=True)

    from csrcqsf.core.logging_config import configure_logging, logger

    configure_logging(paths, reset=True)
    ensure_runtime_directories(paths, include_log_dirs=False)

    from csrcqsf.core.source_mount import record_source_mount

    record_source_mount(paths)

    port = get_app_port()
    raw_port = os.getenv("APP_PORT", str(DEFAULT_APP_PORT)).strip()
    if raw_port != str(port):
        logger.warning("APP_PORT={} 无效，使用默认端口 {}", raw_port, port)

    from csrcqsf.core.app import app
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", loop="asyncio", port=port)


if __name__ == "__main__":
    main()
