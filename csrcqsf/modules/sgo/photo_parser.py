"""询码照片字段解析。"""

import json


def extract_photo_raw_urls(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        file_descriptions = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        # 历史询码照片使用逗号分隔对象路径，没有文件 ID，保留原字段但不参与 MinIO 映射。
        return []
    if not isinstance(file_descriptions, list):
        return []

    raw_urls: list[str] = []
    for file_item in file_descriptions:
        if not isinstance(file_item, dict):
            continue
        url = file_item.get("url")
        if not isinstance(url, str):
            continue
        url_parts = url.split("_")
        if len(url_parts) < 2 or not url_parts[1]:
            continue
        raw_urls.append(url_parts[1])
    return raw_urls
