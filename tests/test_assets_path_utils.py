from csrcqsf.modules.railway_parts.utils.assets import (
    asset_url_from_internal_path,
    build_internal_accel_redirect,
    parse_public_asset_url,
)


def test_asset_url_from_internal_path_maps_supported_buckets():
    assert asset_url_from_internal_path(
        "bfr-3d-videos/raw-videos/1001/demo.mp4"
    ) == "bfr-3d-videos/raw-videos/1001/demo.mp4"
    assert asset_url_from_internal_path(
        "bfr-reconstruction-files/results/1001/demo.ply"
    ) == "bfr-reconstruction-files/results/1001/demo.ply"
    assert asset_url_from_internal_path(
        "bfr-search-history-files/query-images/20260616/demo.png"
    ) == "bfr-search-history-files/query-images/20260616/demo.png"


def test_asset_url_from_internal_path_keeps_unsupported_paths():
    assert asset_url_from_internal_path("") is None
    assert asset_url_from_internal_path(None) is None
    assert (
        asset_url_from_internal_path("/railway/parts/assets/reconstruction/files/a.ply")
        == "/railway/parts/assets/reconstruction/files/a.ply"
    )
    assert (
        asset_url_from_internal_path("/bfr-reconstruction-files/results/a.ply")
        == "bfr-reconstruction-files/results/a.ply"
    )
    assert asset_url_from_internal_path("other-bucket/demo.bin") == "other-bucket/demo.bin"


def test_parse_public_asset_url_recovers_bucket_and_object_name():
    assert parse_public_asset_url(
        "/bfr-3d-videos/raw-videos/1001/demo.mp4"
    ) == (
        "bfr-3d-videos",
        "raw-videos/1001/demo.mp4",
    )
    assert parse_public_asset_url(
        "/bfr-reconstruction-files/results/1001/demo.ply"
    ) == (
        "bfr-reconstruction-files",
        "results/1001/demo.ply",
    )
    assert parse_public_asset_url(
        "/bfr-search-history-files/query-images/20260616/demo.png"
    ) == (
        "bfr-search-history-files",
        "query-images/20260616/demo.png",
    )
    assert parse_public_asset_url("bfr-reconstruction-files/results/1001/demo.ply") == (
        "bfr-reconstruction-files",
        "results/1001/demo.ply",
    )


def test_internal_accel_redirect_encodes_non_ascii_object_name():
    assert build_internal_accel_redirect(
        "bfr-ai-files",
        "manual-upload/金鱼 01.png",
    ) == "/recognition_oss/bfr-ai-files/manual-upload/%E9%87%91%E9%B1%BC%2001.png"
