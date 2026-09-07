from __future__ import annotations

from urllib.parse import urlencode

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
    """统一校验 SGO Token，文件代理额外兼容受限的查询参数入口。"""

    def __init__(
        self,
        app,
        *,
        settings: AuthSettings,
        auth_service: AuthService | None,
        asset_query_token_prefixes: tuple[str, ...] = (),
    ):
        super().__init__(app)
        self._settings = settings
        self._auth_service = auth_service
        self._asset_query_token_prefixes = asset_query_token_prefixes

    async def dispatch(self, request: Request, call_next):
        if not self._settings.enabled or self._is_public_request(request):
            return await call_next(request)

        try:
            supports_query_token = self._supports_asset_query_token(request)
            try:
                token = self._read_request_token(
                    request,
                    supports_query_token=supports_query_token,
                )
            finally:
                if supports_query_token:
                    self._remove_asset_query_token(request)
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

    def _read_request_token(
        self,
        request: Request,
        *,
        supports_query_token: bool,
    ) -> str:
        authorization = request.headers.get("Authorization")
        if authorization is not None and authorization.strip() != "":
            # 同时传入两种凭证时以请求头为准，避免攻击者用 Query 覆盖用户身份。
            return parse_bearer_token(authorization)

        if not supports_query_token:
            return parse_bearer_token(authorization)

        query_tokens = request.query_params.getlist("token")
        if len(query_tokens) > 1:
            raise AuthError(401, "AUTH_TOKEN_MALFORMED", "登录信息异常，请重新登录")
        if not query_tokens or query_tokens[0].strip() == "":
            return parse_bearer_token(None)
        return query_tokens[0].strip()

    @staticmethod
    def _remove_asset_query_token(request: Request) -> None:
        # SGO Token 只用于本层鉴权，不能继续进入文件路由、MinIO 或应用访问日志。
        sanitized_items = [
            (key, value)
            for key, value in request.query_params.multi_items()
            if key != "token"
        ]
        request.scope["query_string"] = urlencode(sanitized_items).encode("utf-8")

    def _supports_asset_query_token(self, request: Request) -> bool:
        if request.method.upper() not in {"GET", "HEAD"}:
            return False
        return any(
            request.url.path.startswith(prefix)
            for prefix in self._asset_query_token_prefixes
        )

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
