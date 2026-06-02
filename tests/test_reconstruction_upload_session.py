from csrcqsf.models.orm.reconstruction_upload import ReconstructionVideoUploadSession


def test_reconstruction_video_upload_session_has_expected_columns():
    columns = set(ReconstructionVideoUploadSession.__table__.columns.keys())

    assert {
        "id",
        "item_id",
        "bucket",
        "object_name",
        "video_path",
        "upload_id",
        "file_name",
        "file_size",
        "content_type",
        "part_size",
        "total_parts",
        "height",
        "length",
        "width",
        "weight",
        "status",
        "expires_at",
        "completed_at",
        "time_created",
        "time_updated",
    }.issubset(columns)


def test_reconstruction_video_upload_session_uses_expected_table_name():
    assert ReconstructionVideoUploadSession.__tablename__ == "reconstruction_video_upload_session"


def test_reconstruction_video_upload_session_includes_dual_mode_columns():
    columns = set(ReconstructionVideoUploadSession.__table__.columns.keys())

    assert {
        "storage_mode",
        "local_status",
        "remote_status",
        "local_dir",
        "merged_file_path",
        "remote_upload_id",
        "remote_object_name",
        "remote_video_path",
        "sync_attempts",
        "last_sync_error",
        "synced_at",
    }.issubset(columns)
