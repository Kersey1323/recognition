from csrcqsf.modules.railway_parts.services.assets_service import (
    AssetAuthError,
    authorize_asset_request,
)


def test_authorize_asset_request_accepts_supported_asset_path():
    result = authorize_asset_request(
        method="GET",
        path="/bfr-reconstruction-files/results/1001/demo.ply",
    )
    assert result["bucket"] == "bfr-reconstruction-files"
    assert result["object_name"] == "results/1001/demo.ply"


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
            )
        except AssetAuthError as exc:
            assert exc.status_code == expected
        else:
            raise AssertionError("request should be rejected")
