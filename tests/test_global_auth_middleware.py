import asyncio

import httpx
from fastapi import FastAPI, Request

from csrcqsf.core.auth.errors import AuthError
from csrcqsf.core.auth.middleware import GlobalAuthMiddleware
from csrcqsf.core.auth.models import AuthPrincipal
from csrcqsf.core.settings import AuthSettings


class _AuthService:
    def __init__(self, error=None):
        self.error = error
        self.tokens = []

    async def authenticate(self, token):
        self.tokens.append(token)
        if self.error:
            raise self.error
        return AuthPrincipal("1", "tester", "测试用户", "tenant")


def _settings(*, enabled=True, docs_public=False):
    return AuthSettings(
        app_env="development",
        enabled=enabled,
        provider="mock",
        mock_token="dev-token",
        docs_public=docs_public,
        allowed_origins=("*",),
        sgo_auth_url="",
        sgo_service="sgo",
        sgo_mode="",
        sgo_timeout_seconds=5,
        redis_url="",
        token_cache_ttl_seconds=300,
        invalid_token_cache_ttl_seconds=10,
    )


def _app(service, *, settings=None):
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/business")
    async def business(request: Request):
        return {"account": request.state.user.account}

    @app.options("/business")
    async def business_options():
        return {"status": "ok"}

    @app.get("/bfr-ai-files/{asset_path:path}")
    async def asset(asset_path: str, request: Request):
        return {
            "asset_path": asset_path,
            "account": request.state.user.account,
            "query": dict(request.query_params),
        }

    app.add_middleware(
        GlobalAuthMiddleware,
        settings=settings or _settings(),
        auth_service=service,
        asset_query_token_prefixes=("/bfr-ai-files/",),
    )
    return app


async def _request(app, method, path, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_health_and_options_are_public():
    service = _AuthService()
    app = _app(service)

    assert asyncio.run(_request(app, "GET", "/health")).status_code == 200
    assert asyncio.run(_request(app, "OPTIONS", "/business")).status_code == 200
    assert service.tokens == []


def test_business_route_requires_bearer_and_sets_request_user():
    service = _AuthService()
    app = _app(service)

    missing = asyncio.run(_request(app, "GET", "/business"))
    accepted = asyncio.run(
        _request(app, "GET", "/business", headers={"Authorization": "Bearer dev-token"})
    )

    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert accepted.status_code == 200
    assert accepted.json() == {"account": "tester"}
    assert service.tokens == ["dev-token"]


def test_provider_failure_keeps_real_503_status():
    app = _app(
        _AuthService(
            AuthError(503, "AUTH_SERVICE_UNAVAILABLE", "SGO 认证服务暂时不可用")
        )
    )

    response = asyncio.run(
        _request(app, "GET", "/business", headers={"Authorization": "Bearer token"})
    )

    assert response.status_code == 503
    assert response.json()["code"] == "AUTH_SERVICE_UNAVAILABLE"


def test_development_can_expose_docs_without_token():
    response = asyncio.run(
        _request(_app(_AuthService(), settings=_settings(docs_public=True)), "GET", "/docs")
    )

    assert response.status_code == 200


def test_asset_get_accepts_query_token_but_business_route_does_not():
    service = _AuthService()
    app = _app(service)

    asset_response = asyncio.run(
        _request(
            app,
            "GET",
            "/bfr-ai-files/demo.jpg?width=150&token=query-token",
        )
    )
    business_response = asyncio.run(
        _request(app, "GET", "/business?token=query-token")
    )

    assert asset_response.status_code == 200
    assert asset_response.json() == {
        "asset_path": "demo.jpg",
        "account": "tester",
        "query": {"width": "150"},
    }
    assert business_response.status_code == 401
    assert business_response.json()["code"] == "AUTH_TOKEN_MISSING"
    assert service.tokens == ["query-token"]


def test_asset_authorization_header_takes_precedence_over_query_token():
    service = _AuthService()
    app = _app(service)

    response = asyncio.run(
        _request(
            app,
            "GET",
            "/bfr-ai-files/demo.jpg?token=query-token",
            headers={"Authorization": "Bearer header-token"},
        )
    )

    assert response.status_code == 200
    assert service.tokens == ["header-token"]


def test_asset_rejects_ambiguous_query_tokens():
    service = _AuthService()
    app = _app(service)

    response = asyncio.run(
        _request(
            app,
            "GET",
            "/bfr-ai-files/demo.jpg?token=first&token=second",
        )
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_TOKEN_MALFORMED"
    assert service.tokens == []


def test_asset_query_token_is_not_accepted_for_write_methods():
    service = _AuthService()
    app = _app(service)

    response = asyncio.run(
        _request(app, "POST", "/bfr-ai-files/demo.jpg?token=query-token")
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_TOKEN_MISSING"
    assert service.tokens == []
