from __future__ import annotations

from dataclasses import dataclass
import time
import uuid

from fastapi.responses import JSONResponse


@dataclass
class AuthError(Exception):
    status_code: int
    code: str
    message: str

    def __post_init__(self) -> None:
        super().__init__(self.message)


def parse_bearer_token(authorization: str | None) -> str:
    """只接受标准 Bearer 请求头，避免 Token 出现第二种传递入口。"""
    if authorization is None or authorization.strip() == "":
        raise AuthError(
            401,
            "AUTH_TOKEN_MISSING",
            "未获取到登录信息，请从 SGO 重新进入识别平台",
        )

    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise AuthError(401, "AUTH_TOKEN_MALFORMED", "登录信息异常，请重新登录")
    return parts[1]


def auth_error_response(
    error: AuthError,
    *,
    request_id: str | None = None,
) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None
    return JSONResponse(
        status_code=error.status_code,
        headers=headers,
        content={
            "status": "fail",
            "code": error.code,
            "message": error.message,
            "data": None,
            "requestID": request_id or str(uuid.uuid4()),
            "datetime": int(time.time() * 1000),
        },
    )
