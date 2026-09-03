import asyncio
import json

import aiohttp
import pytest

from csrcqsf.core.auth.errors import AuthError
from csrcqsf.core.auth.providers import MockAuthProvider, SgoAuthProvider


class _FakeResponse:
    def __init__(self, status: int, payload):
        self.status = status
        self._text = payload if isinstance(payload, str) else json.dumps(payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def text(self):
        return self._text


class _FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.params = None
        self.url = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def get(self, url, *, params):
        self.url = url
        self.params = params
        if self.error:
            raise self.error
        return self.response


def _provider(session):
    return SgoAuthProvider(
        auth_url="https://sgo.example.com/uc/sso/auth",
        service="sgo",
        sso_mode="",
        timeout_seconds=3,
        session_factory=lambda *, timeout: session,
    )


def test_sgo_provider_sends_ticket_code_and_maps_principal():
    session = _FakeSession(
        _FakeResponse(
            200,
            {
                "loginStatus": True,
                "userId": "10086",
                "account": "zhangsan",
                "username": "张三",
                "userAttrs": {"tenantId": "-1"},
                "expiration": 43200,
            },
        )
    )

    principal = asyncio.run(_provider(session).verify("secret-token"))

    assert session.params == {
        "ticket": "secret-token",
        "code": "secret-token",
        "service": "sgo",
    }
    assert principal.user_id == "10086"
    assert principal.tenant_id == "-1"
    assert principal.provider_expiration_seconds == 43200


def test_sgo_provider_rejects_success_response_without_user_identity():
    provider = _provider(
        _FakeSession(
            _FakeResponse(
                200,
                {
                    "loginStatus": True,
                    "account": "missing-user-id",
                    "userAttrs": {"tenantId": "-1"},
                },
            )
        )
    )

    with pytest.raises(AuthError) as captured:
        asyncio.run(provider.verify("token"))

    assert captured.value.status_code == 503
    assert captured.value.code == "AUTH_SERVICE_UNAVAILABLE"


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("JWT expired at 2026-09-01", "AUTH_TOKEN_EXPIRED"),
        ("invalid JWT signature", "AUTH_TOKEN_INVALID"),
        ("Token 无效", "AUTH_TOKEN_INVALID"),
    ],
)
def test_sgo_provider_maps_token_failures_to_401(message, code):
    provider = _provider(_FakeSession(_FakeResponse(500, {"state": False, "message": message})))

    with pytest.raises(AuthError) as captured:
        asyncio.run(provider.verify("bad-token"))

    assert captured.value.status_code == 401
    assert captured.value.code == code


def test_sgo_provider_maps_own_missing_parameter_failure_to_500():
    provider = _provider(
        _FakeSession(
            _FakeResponse(500, {"state": False, "message": "ticket parameter is required"})
        )
    )

    with pytest.raises(AuthError) as captured:
        asyncio.run(provider.verify("token"))

    assert captured.value.status_code == 500
    assert captured.value.code == "AUTH_INTERNAL_ERROR"


@pytest.mark.parametrize(
    "response",
    [
        _FakeResponse(500, {"message": "database unavailable"}),
        _FakeResponse(200, "not-json"),
        _FakeResponse(502, {"state": False}),
    ],
)
def test_sgo_provider_maps_unexpected_responses_to_503(response):
    with pytest.raises(AuthError) as captured:
        asyncio.run(_provider(_FakeSession(response)).verify("token"))

    assert captured.value.status_code == 503
    assert captured.value.code == "AUTH_SERVICE_UNAVAILABLE"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (asyncio.TimeoutError(), "AUTH_SERVICE_TIMEOUT"),
        (aiohttp.ClientConnectionError("dns failed"), "AUTH_SERVICE_UNAVAILABLE"),
    ],
)
def test_sgo_provider_maps_transport_failures_to_503(error, code):
    with pytest.raises(AuthError) as captured:
        asyncio.run(_provider(_FakeSession(error=error)).verify("token"))

    assert captured.value.status_code == 503
    assert captured.value.code == code


def test_mock_provider_only_accepts_configured_development_token():
    provider = MockAuthProvider("recognition-dev-token")

    principal = asyncio.run(provider.verify("recognition-dev-token"))
    assert principal.user_id == "local-debug"

    with pytest.raises(AuthError) as captured:
        asyncio.run(provider.verify("wrong-token"))
    assert captured.value.code == "AUTH_TOKEN_INVALID"
