from csrcqsf.biz.railwayparts.local_upload_storage import LocalUploadStorage


def test_local_upload_storage_writes_part_and_meta(tmp_path):
    storage = LocalUploadStorage(base_dir=tmp_path)
    session_dir = storage.ensure_session_dirs(9001)

    storage.write_part(session_dir, 2, b"world")
    meta = storage.load_meta(session_dir)

    assert (session_dir / "parts" / "part-00002").read_bytes() == b"world"
    assert meta["uploaded_parts"] == [2]


def test_local_upload_storage_merges_parts_in_order(tmp_path):
    storage = LocalUploadStorage(base_dir=tmp_path)
    session_dir = storage.ensure_session_dirs(9002)
    storage.write_part(session_dir, 1, b"abc")
    storage.write_part(session_dir, 2, b"def")

    merged_path = storage.merge_parts(
        session_dir=session_dir,
        total_parts=2,
        output_file_name="demo.mp4",
    )

    assert merged_path.read_bytes() == b"abcdef"
