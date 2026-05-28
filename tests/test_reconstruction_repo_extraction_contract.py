from pathlib import Path


def test_embedded_reconstruction_server_is_removed_from_main_repo():
    assert not Path("csrcqsf/biz/railwayparts/reconstruction_server").exists()


def test_legacy_reconstruction_package_is_removed_from_main_repo():
    assert not Path("csrcqsf/biz/reconstruction").exists()


def test_main_repo_no_longer_contains_embedded_reconstruction_deployment_assets():
    assert not Path("docker/reconstruction-server").exists()
    assert not Path("scripts/deployment/run_reconstruction_server.sh").exists()
