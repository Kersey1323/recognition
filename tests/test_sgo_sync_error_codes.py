from csrcqsf.modules.sgo.error_codes import failure_error_code
from csrcqsf.modules.sgo.sync_task_repository import _with_error_code


def test_business_validation_errors_have_distinct_codes():
    assert failure_error_code("source_validation", "InvalidSourceData", "配件名称为空") == "SOURCE_ITEM_NAME_EMPTY"
    assert failure_error_code("source_validation", "InvalidSourceData", "物料编码为空") == "SOURCE_ITEM_CODE_EMPTY"
    assert failure_error_code("source_validation", "InvalidSourceData", "配件 ID 不是有效整数") == "SOURCE_ITEM_ID_INVALID"
    assert failure_error_code("source_validation", "ItemNotFound", "配件不存在于主业务库") == "ITEM_NOT_FOUND"


def test_dynamic_exception_messages_do_not_affect_classification():
    assert failure_error_code("minio_upload", "ConnectionError", "raw_url=a: timeout") == "MINIO_UPLOAD_FAILED"
    assert failure_error_code("minio_upload", "ConnectionError", "raw_url=b: timeout") == "MINIO_UPLOAD_FAILED"
    assert failure_error_code("sgo_download", "SgoImageRetryableError", "SGO 文件服务返回 500") == "SGO_DOWNLOAD_FAILED"
    assert failure_error_code("zip_extract", "SgoImageZipError", "数量不一致") == "ZIP_EXTRACT_FAILED"
    assert failure_error_code("unknown_stage", "NewException", "message") == "SYNC_FAILURE_UNKNOWN"


def test_sgo_source_file_error_has_non_retryable_business_code():
    assert failure_error_code(
        "sgo_download",
        "SgoImageSourceFileError",
        "SGO 文件服务返回 HTTP 500; message=文件下载失败！platform：sftp-1",
    ) == "SGO_SOURCE_FILE_UNAVAILABLE"


def test_repository_populates_code_without_changing_original_error_detail():
    failure = {
        "item_id": "101", "stage": "minio_upload", "error_type": "ConnectionError",
        "error_message": "raw_url=photo-a: timeout",
    }
    persisted = _with_error_code(failure)
    assert persisted == {**failure, "error_code": "MINIO_UPLOAD_FAILED"}
    assert "error_code" not in failure
