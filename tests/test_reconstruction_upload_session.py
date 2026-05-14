from csrcqsf.models.reconstruction_upload import ReconstructionVideoUploadSession


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
