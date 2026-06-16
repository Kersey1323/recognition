from pathlib import Path


def test_local_upload_debug_page_exists_and_uses_file_slice():
    path = Path("tools/reconstruct_local_upload_debug.html")
    assert path.exists()

    text = path.read_text(encoding="utf-8")
    assert 'id="storageMode"' in text
    assert 'value="local"' in text
    assert 'value="remote"' in text
    assert "storage_mode: getStorageMode()" in text
    assert "服务端会立即把当前分片代理上传到 MinIO multipart upload" in text
    assert "file.slice(" in text
    assert "/recognition_api/railway/parts/v2/reconstruct/video/upload/init" in text
    assert "/recognition_api/railway/parts/v2/reconstruct/video/upload/part" in text
    assert "/recognition_api/railway/parts/v2/reconstruct/video/upload/progress" in text
    assert "/recognition_api/railway/parts/v2/reconstruct/video/upload/complete" in text
