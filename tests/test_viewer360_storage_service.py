import asyncio
from pathlib import Path
from types import SimpleNamespace

from csrcqsf.modules.railway_parts.services.viewer360_storage_service import (
    Viewer360StorageService,
)


class FakeMinio:
    def __init__(self):
        self.calls = []
        self.objects = set()

    def fget_object(self, bucket, object_name, destination):
        self.calls.append(("download", bucket, object_name))
        Path(destination).write_bytes(b"video")

    def fput_object(self, bucket, object_name, source, content_type=None):
        self.calls.append(("upload", bucket, object_name, content_type))
        self.objects.add((bucket, object_name))

    def stat_object(self, bucket, object_name):
        self.calls.append(("stat", bucket, object_name))
        if (bucket, object_name) not in self.objects:
            raise RuntimeError("missing")
        return SimpleNamespace(object_name=object_name)

    def copy_object(self, bucket, object_name, source):
        self.calls.append(("copy", bucket, object_name, source.bucket_name, source.object_name))
        self.objects.add((bucket, object_name))

    def list_objects(self, bucket, prefix, recursive):
        return [
            SimpleNamespace(object_name=name)
            for stored_bucket, name in sorted(self.objects)
            if stored_bucket == bucket and name.startswith(prefix)
        ]

    def remove_object(self, bucket, object_name):
        self.calls.append(("remove", bucket, object_name))
        self.objects.discard((bucket, object_name))


def _publish_dir(root: Path) -> Path:
    output = root / "viewer360"
    row = output / "images" / "row_01"
    row.mkdir(parents=True)
    (row / "frame_0001.webp").write_bytes(b"webp")
    (output / "manifest.json").write_text("{}", encoding="utf-8")
    return output


def test_publish_uploads_manifest_last_and_returns_object_name(tmp_path: Path):
    client = FakeMinio()
    service = Viewer360StorageService(client=client, result_bucket="results")

    manifest = asyncio.run(service.publish(_publish_dir(tmp_path), item_id=12, task_id="task-a"))

    uploads = [call for call in client.calls if call[0] == "upload"]
    assert [call[2] for call in uploads] == [
        "viewer360/12/task-a/images/row_01/frame_0001.webp",
        "viewer360/12/task-a/manifest.json",
    ]
    assert manifest == "viewer360/12/task-a/manifest.json"
    assert service.public_url(manifest) == "/results/viewer360/12/task-a/manifest.json"


def test_copy_row_uses_server_side_object_copy():
    client = FakeMinio()
    service = Viewer360StorageService(client=client, result_bucket="results")

    copied = asyncio.run(
        service.copy_row(
            source_item_id=12,
            source_task_id="old",
            target_item_id=12,
            target_task_id="new",
            row_index=2,
            frame_count=2,
        )
    )

    assert copied == 2
    copies = [call for call in client.calls if call[0] == "copy"]
    assert copies[0][2:] == (
        "viewer360/12/new/images/row_02/frame_0001.webp",
        "results",
        "viewer360/12/old/images/row_02/frame_0001.webp",
    )


def test_delete_result_prefix_is_idempotent():
    client = FakeMinio()
    client.objects.update(
        {
            ("results", "viewer360/12/task-a/manifest.json"),
            ("results", "viewer360/12/task-a/images/row_01/frame_0001.webp"),
        }
    )
    service = Viewer360StorageService(client=client, result_bucket="results")

    assert asyncio.run(service.delete_result(item_id=12, task_id="task-a")) == 2
    assert asyncio.run(service.delete_result(item_id=12, task_id="task-a")) == 0


def test_download_source_video_parses_bucket_path(tmp_path: Path):
    client = FakeMinio()
    service = Viewer360StorageService(
        client=client,
        result_bucket="results",
        video_bucket="videos",
    )

    result = asyncio.run(
        service.download_source_video("videos/source/12.mp4", tmp_path / "source.mp4")
    )

    assert result.read_bytes() == b"video"
    assert client.calls == [("download", "videos", "source/12.mp4")]


def test_ensure_source_readable_stats_the_parsed_object():
    client = FakeMinio()
    client.objects.add(("videos", "source/12.mp4"))
    service = Viewer360StorageService(
        client=client,
        result_bucket="results",
        video_bucket="videos",
    )

    result = asyncio.run(service.ensure_source_readable("videos/source/12.mp4"))

    assert result == ("videos", "source/12.mp4")
    assert client.calls == [("stat", "videos", "source/12.mp4")]
