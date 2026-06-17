from pathlib import Path


def test_assets_proxy_docker_script_contains_nginx_run_command():
    path = Path("scripts/deployment/run_assets_proxy_debug.sh")
    assert path.exists()

    text = path.read_text(encoding="utf-8")
    assert "docker run -d" in text
    assert "--name recognition-assets-proxy-debug" in text
    assert "-p 8080:8080" in text
    assert "--add-host host.docker.internal:host-gateway" in text
    assert "nginx-assets-proxy-example.conf" in text
    assert "assets_download_debug.html" in text
