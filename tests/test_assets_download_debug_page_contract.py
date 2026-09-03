from pathlib import Path


def test_assets_download_debug_page_uses_bearer_without_logging_token():
    path = Path("tools/assets_download_debug.html")
    assert path.exists()

    text = path.read_text(encoding="utf-8")
    assert 'id="baseUrl"' in text
    assert 'id="assetPath"' in text
    assert 'id="authToken"' in text
    assert 'id="previewBtn"' in text
    assert 'id="downloadBtn"' in text
    assert 'headers["Authorization"] = `Bearer ${token}`' in text
    assert 'log("请求文件", { url })' in text
    assert 'log("请求文件", { url, headers })' not in text
    assert 'fetch(url, {' in text
    assert '"/bfr-3d-videos/' in text
    assert "URL.createObjectURL(blob)" in text
    assert "previewImageEl.src = objectUrl" in text
    assert "previewVideoEl.src = objectUrl" in text
