"""SGO 同步失败的稳定业务分类码。"""

SOURCE_ERROR_CODES = {
    "配件 ID 不是有效整数": "SOURCE_ITEM_ID_INVALID",
    "物料编码为空": "SOURCE_ITEM_CODE_EMPTY",
    "配件名称为空": "SOURCE_ITEM_NAME_EMPTY",
}

STAGE_ERROR_CODES = {
    "base_images": "BASE_IMAGE_METADATA_INVALID",
    "image_metadata": "IMAGE_METADATA_FAILED",
    "sgo_download": "SGO_DOWNLOAD_FAILED",
    "zip_extract": "ZIP_EXTRACT_FAILED",
    "minio_upload": "MINIO_UPLOAD_FAILED",
}


def failure_error_code(stage: str, error_type: str, error_message: str) -> str:
    if stage == "source_validation":
        if error_type == "ItemNotFound":
            return "ITEM_NOT_FOUND"
        return SOURCE_ERROR_CODES.get(error_message, "SOURCE_DATA_INVALID")
    if stage == "sgo_download" and error_type == "SgoImageSourceFileError":
        return "SGO_SOURCE_FILE_UNAVAILABLE"
    return STAGE_ERROR_CODES.get(stage, "SYNC_FAILURE_UNKNOWN")
