from csrcqsf.infra.external.error_response import format_remote_error


def test_format_remote_error_keeps_service_metadata_for_cross_service_debugging():
    message = format_remote_error(
        {
            "detail": "RuntimeError: Redis 连接失败",
            "error_type": "RuntimeError",
            "request_id": "remote-request-1",
            "service": "reconstruction-server",
        }
    )

    assert "Redis 连接失败" in message
    assert "error_type=RuntimeError" in message
    assert "request_id=remote-request-1" in message
    assert "service=reconstruction-server" in message


def test_format_remote_error_redacts_credentials_from_legacy_plain_text_errors():
    message = format_remote_error("mysql://root:secret@db/demo password=other-secret")

    assert "secret" not in message
    assert "other-secret" not in message
    assert message.count("[REDACTED]") == 2
