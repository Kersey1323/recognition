import json

import pytest

from csrcqsf.core.auth.errors import AuthError, auth_error_response, parse_bearer_token


@pytest.mark.parametrize(
    ("header", "code"),
    [
        (None, "AUTH_TOKEN_MISSING"),
        ("", "AUTH_TOKEN_MISSING"),
        ("Token abc", "AUTH_TOKEN_MALFORMED"),
        ("Bearer", "AUTH_TOKEN_MALFORMED"),
        ("Bearer   ", "AUTH_TOKEN_MALFORMED"),
        ("Bearer abc extra", "AUTH_TOKEN_MALFORMED"),
    ],
)
def test_parse_bearer_token_rejects_missing_or_malformed_header(header, code):
    with pytest.raises(AuthError) as captured:
        parse_bearer_token(header)

    assert captured.value.status_code == 401
    assert captured.value.code == code


def test_parse_bearer_token_accepts_case_insensitive_scheme():
    assert parse_bearer_token("bearer example-token") == "example-token"


def test_unauthorized_response_uses_real_status_and_bearer_challenge():
    response = auth_error_response(
        AuthError(401, "AUTH_TOKEN_EXPIRED", "SGO 登录已过期，请重新登录"),
        request_id="request-123",
    )
    body = json.loads(response.body)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert body == {
        "status": "fail",
        "code": "AUTH_TOKEN_EXPIRED",
        "message": "SGO 登录已过期，请重新登录",
        "data": None,
        "requestID": "request-123",
        "datetime": body["datetime"],
    }


def test_service_unavailable_response_has_no_bearer_challenge():
    response = auth_error_response(
        AuthError(503, "AUTH_SERVICE_UNAVAILABLE", "SGO 认证服务暂时不可用")
    )

    assert response.status_code == 503
    assert "WWW-Authenticate" not in response.headers
