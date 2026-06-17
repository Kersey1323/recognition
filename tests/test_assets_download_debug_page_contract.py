from pathlib import Path


def test_assets_download_debug_page_exists_and_uses_fetch_with_u_token():
    path = Path("tools/assets_download_debug.html")
    assert path.exists()

    text = path.read_text(encoding="utf-8")
    assert 'id="baseUrl"' in text
    assert 'id="assetPath"' in text
    assert 'id="uToken"' in text
    assert 'id="previewBtn"' in text
    assert 'id="downloadBtn"' in text
    assert 'headers["U-Token"] = token' in text
    assert 'fetch(url, {' in text
    assert '"/bfr-3d-videos/' in text
    assert "URL.createObjectURL(blob)" in text
    assert "previewImageEl.src = objectUrl" in text
    assert "previewVideoEl.src = objectUrl" in text
