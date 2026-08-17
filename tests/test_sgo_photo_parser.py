from csrcqsf.modules.sgo.photo_parser import extract_photo_raw_urls


def test_extract_photo_raw_urls_reads_current_json_format():
    value = (
        '[{"url":"/portal/file/getFileById_1001"},'
        '{"url":"/portal/file/getFileById_1002"}]'
    )

    assert extract_photo_raw_urls(value) == ["1001", "1002"]


def test_extract_photo_raw_urls_ignores_legacy_path_format():
    value = "file/question/20230727/a.jpg,file/question/20230727/b.jpg"

    assert extract_photo_raw_urls(value) == []


def test_extract_photo_raw_urls_ignores_malformed_json_items():
    value = '[{"url": null}, "invalid", {}, {"url":"missingseparator"}]'

    assert extract_photo_raw_urls(value) == []
