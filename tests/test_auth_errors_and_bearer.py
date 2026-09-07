import json

import pytest

from csrcqsf.core.auth.errors import AuthError, auth_error_response, parse_bearer_token


@pytest.mark.parametrize(
    ("header", "code", "message"),
    [
        (
            None,
            "AUTH_TOKEN_MISSING",
            "未获取到登录信息，请从 SGO 重新进入识别平台",
        ),
        (
            "",
            "AUTH_TOKEN_MISSING",
            "未获取到登录信息，请从 SGO 重新进入识别平台",
        ),
        ("Token abc", "AUTH_TOKEN_MALFORMED", "登录信息异常，请重新登录"),
        ("Bearer", "AUTH_TOKEN_MALFORMED", "登录信息异常，请重新登录"),
        ("Bearer   ", "AUTH_TOKEN_MALFORMED", "登录信息异常，请重新登录"),
        (
            "Bearer abc extra",
            "AUTH_TOKEN_MALFORMED",
            "登录信息异常，请重新登录",
        ),
    ],
)
def test_parse_bearer_token_rejects_missing_or_malformed_header(header, code, message):
    with pytest.raises(AuthError) as captured:
        parse_bearer_token(header)

    assert captured.value.status_code == 401
    assert captured.value.code == code
    assert captured.value.message == message


def test_parse_bearer_token_accepts_case_insensitive_scheme():
    assert parse_bearer_token("bearer example-token") == "example-token"


def test_unauthorized_response_uses_real_status_and_bearer_challenge():
    response = auth_error_response(
        AuthError(401, "AUTH_TOKEN_EXPIRED", "会话已过期，请重新登录"),
        request_id="request-123",
    )
    body = json.loads(response.body)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert body == {
        "status": "fail",
        "code": "AUTH_TOKEN_EXPIRED",
        "message": "会话已过期，请重新登录",
        "data": None,
        "requestID": "request-123",
        "datetime": body["datetime"],
    }


def test_service_unavailable_response_has_no_bearer_challenge():
    response = auth_error_response(
        AuthError(
            503,
            "AUTH_SERVICE_UNAVAILABLE",
            "登录验证服务暂时不可用，请稍后重试",
        )
    )

    assert response.status_code == 503
    assert "WWW-Authenticate" not in response.headers
