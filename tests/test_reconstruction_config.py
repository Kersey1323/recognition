from pathlib import Path


def test_settings_exposes_reconstruction_file_bucket_and_sam3_path():
    from csrcqsf.settings import minio_reconstruction_file_bucket, sam3_model_path

    assert minio_reconstruction_file_bucket == "bfr-reconstruction-files"
    assert Path(sam3_model_path).is_absolute()
    assert str(sam3_model_path).endswith("/sam3")


def test_parse_minio_path_recognizes_reconstruction_file_bucket():
    from csrcqsf.data.minio import parse_minio_path

    bucket, object_name = parse_minio_path(
        "bfr-reconstruction-files/results/1935558010375340032/task-id/point_cloud.ply"
    )

    assert bucket == "bfr-reconstruction-files"
    assert object_name == "results/1935558010375340032/task-id/point_cloud.ply"
