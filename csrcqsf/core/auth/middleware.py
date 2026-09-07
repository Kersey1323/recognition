from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from starlette.middleware.base import BaseHTTPMiddleware

from csrcqsf.core.logging_config import logger
from csrcqsf.core.settings import AuthSettings

from .cache import RedisTokenCache
from .errors import AuthError, auth_error_response, parse_bearer_token
from .providers import MockAuthProvider, SgoAuthProvider
from .service import AuthService


class GlobalAuthMiddleware(BaseHTTPMiddleware):
    """在业务路由执行前统一校验 SGO Bearer Token。"""

    def __init__(self, app, *, settings: AuthSettings, auth_service: AuthService | None):
        super().__init__(app)
        self._settings = settings
        self._auth_service = auth_service

    async def dispatch(self, request: Request, call_next):
        if not self._settings.enabled or self._is_public_request(request):
            return await call_next(request)

        try:
            token = parse_bearer_token(request.headers.get("Authorization"))
            if self._auth_service is None:
                raise AuthError(
                    500,
                    "AUTH_INTERNAL_ERROR",
                    "系统暂时无法完成登录验证，请稍后重试",
                )
            request.state.user = await self._auth_service.authenticate(token)
        except AuthError as exc:
            return auth_error_response(
                exc,
                request_id=getattr(request.state, "request_id", None),
            )
        except Exception as exc:
            # 未知异常只记录类型，不记录请求头和原始 Token。
            logger.exception("全局 Token 鉴权发生未知异常: error_type={}", type(exc).__name__)
            return auth_error_response(
                AuthError(
                    500,
                    "AUTH_INTERNAL_ERROR",
                    "系统暂时无法完成登录验证，请稍后重试",
                ),
                request_id=getattr(request.state, "request_id", None),
            )
        return await call_next(request)

    def _is_public_request(self, request: Request) -> bool:
        if request.method.upper() == "OPTIONS" or request.url.path == "/health":
            return True
        if not self._settings.docs_public:
            return False
        return request.url.path in {"/docs", "/redoc", "/openapi.json"} or request.url.path.startswith(
            "/docs/"
        )


def build_auth_service(
    settings: AuthSettings,
) -> tuple[AuthService | None, RedisTokenCache | None]:
    if not settings.enabled:
        return None, None

    if settings.provider == "mock":
        provider = MockAuthProvider(settings.mock_token)
    else:
        provider = SgoAuthProvider(
            auth_url=settings.sgo_auth_url,
            service=settings.sgo_service,
            sso_mode=settings.sgo_mode,
            timeout_seconds=settings.sgo_timeout_seconds,
        )
    cache = RedisTokenCache(settings.redis_url) if settings.redis_url else None
    return (
        AuthService(
            provider,
            cache,
            settings.token_cache_ttl_seconds,
            settings.invalid_token_cache_ttl_seconds,
        ),
        cache,
    )


def configure_openapi_security(app: FastAPI, *, health_path: str) -> None:
    """为 Swagger 增加统一 Bearer 输入，并仅标记健康检查为公开接口。"""

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "SGO Token",
        }
        schema["security"] = [{"BearerAuth": []}]
        health_operation = schema.get("paths", {}).get(health_path, {}).get("get")
        if health_operation is not None:
            health_operation["security"] = []
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
