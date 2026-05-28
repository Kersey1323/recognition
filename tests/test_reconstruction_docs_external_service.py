from pathlib import Path


def test_readme_no_longer_mentions_embedded_reconstruction_server_path():
    text = Path("README.md").read_text(encoding="utf-8")

    assert "csrcqsf/biz/railwayparts/reconstruction_server" not in text
    assert "RECONSTRUCTION_SERVER_URL" in text
    assert "/home/ubuntu/project-train/reconstruction_server" in text


def test_deployment_doc_no_longer_uses_embedded_reconstruction_server_cd_path():
    text = Path("部署文档.md").read_text(encoding="utf-8")

    assert "cd /home/ubuntu/project-train/recognition/csrcqsf/biz/railwayparts/reconstruction_server" not in text
    assert "/home/ubuntu/project-train/reconstruction_server" in text


def test_main_repo_no_longer_ships_reconstruction_server_deployment_assets():
    assert not Path("docker/reconstruction-server").exists()
    assert not Path("scripts/deployment/run_reconstruction_server.sh").exists()
