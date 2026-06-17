from csrcqsf.modules.railway_parts.services.assets_service import (
    AssetAuthError,
    authorize_asset_request,
)


class _FakeUserClient:
    def __init__(self, status="success", user_id=101, message="bad token"):
        self.status = status
        self.user_id = user_id
        self.message = message

    def check_token(self, token: str):
        if self.status == "success":
            return {"status": "success", "data": {"id": self.user_id}}
        return {"status": "fail", "message": self.message}


def test_authorize_asset_request_accepts_valid_u_token():
    result = authorize_asset_request(
        method="GET",
        path="/bfr-reconstruction-files/results/1001/demo.ply",
        u_token="ok",
        user_client=_FakeUserClient(),
    )
    assert result["user_id"] == 101


def test_authorize_asset_request_rejects_missing_token():
    try:
        authorize_asset_request(
            method="GET",
            path="/bfr-reconstruction-files/results/1001/demo.ply",
            u_token="",
            user_client=_FakeUserClient(),
        )
    except AssetAuthError as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("missing token should be rejected")


def test_authorize_asset_request_rejects_invalid_path_and_method():
    for method, path, expected in [
        (
            "POST",
            "/bfr-reconstruction-files/results/1001/demo.ply",
            403,
        ),
        ("GET", "/not-allowed/demo.bin", 403),
        (
            "GET",
            "/bfr-reconstruction-files/../secret.txt",
            403,
        ),
    ]:
        try:
            authorize_asset_request(
                method=method,
                path=path,
                u_token="ok",
                user_client=_FakeUserClient(),
            )
        except AssetAuthError as exc:
            assert exc.status_code == expected
        else:
            raise AssertionError("request should be rejected")


def test_authorize_asset_request_allows_skip_auth_in_local_debug_mode():
    result = authorize_asset_request(
        method="GET",
        path="/bfr-reconstruction-files/results/1001/demo.ply",
        u_token="",
        user_client=None,
        skip_auth=True,
    )
    assert result["user_id"] == "local-debug"
    assert result["bucket"] == "bfr-reconstruction-files"
