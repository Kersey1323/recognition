import os
from pathlib import Path
import subprocess
import sys


def test_health_endpoint_returns_ok() -> None:
    # 应用模块会在导入时创建连接池；健康检查只需合法占位配置，不会连接数据库。
    env = {
        "MAIN_DB_HOST": "127.0.0.1",
        "MAIN_DB_PORT": "3306",
        "MAIN_DB_USER": "test",
        "MAIN_DB_PASSWORD": "test",
        "MAIN_DB_DATABASE": "test",
        "SGO_DATABASE_TYPE": "mysql",
        "SGO_MYSQL_HOST": "127.0.0.1",
        "SGO_MYSQL_PORT": "3306",
        "SGO_MYSQL_USER": "test",
        "SGO_MYSQL_PASSWORD": "test",
        "SGO_MYSQL_DATABASE": "test",
    }
    process_env = os.environ.copy()
    process_env.update(env)
    process_env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    script = """
import anyio
from csrcqsf.core.app import app

route = next(route for route in app.routes if getattr(route, 'path', '') == '/health')
print(anyio.run(route.endpoint))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=process_env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "{'status': 'ok', 'service': 'recognition'}" in result.stdout
