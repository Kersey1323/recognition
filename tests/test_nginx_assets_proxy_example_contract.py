from pathlib import Path


def test_nginx_assets_proxy_example_contains_required_locations():
    path = Path("docs/deployment/nginx-assets-proxy-example.conf")
    assert path.exists()

    text = path.read_text(encoding="utf-8")
    assert "location / {" in text
    assert "location /railway/parts/" in text
    assert "bfr-ai-files" in text
    assert "bfr-3d-videos" in text
    assert "bfr-reconstruction-files" in text
    assert "bfr-search-history-files" in text
    assert "location ^~ /recognition_oss/" in text
    assert "internal;" in text
    assert 'set $args "";' in text
    assert "proxy_pass http://host.docker.internal:65432;" in text
    assert "proxy_pass http://192.168.100.2:9000/;" in text
    assert "proxy_set_header Authorization $http_authorization;" in text
    assert "U-Token" not in text
    assert "X-Asset-Proxy-Skip-Auth" not in text
    assert "try_files $uri $uri/ =404;" in text
