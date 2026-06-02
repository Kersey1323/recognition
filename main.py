import os

import uvicorn


DEFAULT_APP_PORT = 65432


def get_app_port() -> int:
    raw_port = os.getenv("APP_PORT", str(DEFAULT_APP_PORT)).strip()
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_APP_PORT


def main() -> None:
    from csrcqsf.core.app import app

    uvicorn.run(app, host="0.0.0.0", loop="asyncio", port=get_app_port())

if __name__ == '__main__':
    main()
