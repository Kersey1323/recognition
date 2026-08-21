import json
from pathlib import Path


def test_resolve_source_mount_detects_exact_mount(tmp_path):
    from csrcqsf.core.source_mount import resolve_source_mount

    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "36 29 8:1 /src /app/csrcqsf ro,relatime - ext4 /dev/sdb1 rw\n",
        encoding="utf-8",
    )

    result = resolve_source_mount(
        container_path=Path("/app/csrcqsf"),
        mountinfo_path=mountinfo,
    )

    assert result.source_type == "external-mount"
    assert result.container_path == "/app/csrcqsf"
    assert result.mount_root == "/src"
    assert result.filesystem == "ext4"
    assert result.mount_source == "/dev/sdb1"
    assert result.diagnostic is None


def test_resolve_source_mount_does_not_treat_parent_mount_as_source_mount(tmp_path):
    from csrcqsf.core.source_mount import resolve_source_mount

    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "36 29 8:1 /src /app rw,relatime - ext4 /dev/sdb1 rw\n",
        encoding="utf-8",
    )

    result = resolve_source_mount(
        container_path=Path("/app/csrcqsf"),
        mountinfo_path=mountinfo,
    )

    assert result.source_type == "image-layer"


def test_resolve_source_mount_decodes_mountinfo_paths(tmp_path):
    from csrcqsf.core.source_mount import resolve_source_mount

    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "36 29 8:1 /source\\040dir /app/source\\040code ro - ext4 /dev/sdb1 rw\n",
        encoding="utf-8",
    )

    result = resolve_source_mount(
        container_path=Path("/app/source code"),
        mountinfo_path=mountinfo,
    )

    assert result.source_type == "external-mount"
    assert result.mount_root == "/source dir"


def test_resolve_source_mount_degrades_when_mountinfo_is_unavailable(tmp_path):
    from csrcqsf.core.source_mount import resolve_source_mount

    result = resolve_source_mount(
        container_path=Path("/app/csrcqsf"),
        mountinfo_path=tmp_path / "missing-mountinfo",
    )

    assert result.source_type == "image-layer"
    assert "No such file" in (result.diagnostic or "")


def test_record_source_mount_appends_json_line(monkeypatch, tmp_path):
    from csrcqsf.core.runtime_paths import resolve_runtime_paths
    from csrcqsf.core.source_mount import record_source_mount

    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "36 29 8:1 /host/source /app/csrcqsf ro - ext4 /dev/sdb1 rw\n",
        encoding="utf-8",
    )
    paths = resolve_runtime_paths({}, app_root=tmp_path)
    paths.log_dir.mkdir(parents=True)
    monkeypatch.setenv("RECOGNITION_MAIN_SOURCE_HOST_PATH", "/host/source")

    result = record_source_mount(
        paths,
        container_path=Path("/app/csrcqsf"),
        mountinfo_path=mountinfo,
    )

    payload = json.loads((paths.log_dir / "source_mount.log").read_text(encoding="utf-8"))
    assert result.source_type == "external-mount"
    assert payload["event"] == "source_mount_resolution"
    assert payload["service"] == "recognition-service"
    assert payload["source_type"] == "external-mount"
    assert payload["host_path"] == "/host/source"
    assert isinstance(payload["pid"], int)
    assert isinstance(payload["argv"], list)


def test_record_source_mount_can_be_disabled(monkeypatch, tmp_path):
    from csrcqsf.core.runtime_paths import resolve_runtime_paths
    from csrcqsf.core.source_mount import record_source_mount

    paths = resolve_runtime_paths({}, app_root=tmp_path)
    monkeypatch.setenv("RECOGNITION_MAIN_SOURCE_LOG_ENABLED", "0")

    result = record_source_mount(paths)

    assert result is None
    assert not (paths.log_dir / "source_mount.log").exists()
