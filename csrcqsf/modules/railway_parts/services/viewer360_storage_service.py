"""Viewer360 源视频下载和版本化结果发布。"""

from __future__ import annotations

from functools import partial
import json
import mimetypes
from pathlib import Path

import anyio
from minio.commonconfig import CopySource

from csrcqsf.core.settings import (
    minio_reconstruction_file_bucket,
    minio_reconstruction_video_bucket,
)
from csrcqsf.infra.storage.minio import minio_instance, parse_minio_path


class Viewer360StorageService:
    def __init__(
        self,
        *,
        client=None,
        result_bucket: str | None = None,
        video_bucket: str | None = None,
    ) -> None:
        self.client = client or minio_instance.client
        self.result_bucket = result_bucket or minio_reconstruction_file_bucket
        self.video_bucket = video_bucket or minio_reconstruction_video_bucket

    @staticmethod
    def result_prefix(item_id: int, task_id: str) -> str:
        return f"viewer360/{item_id}/{task_id}"

    def public_url(self, object_name: str) -> str:
        return f"/{self.result_bucket}/{object_name.lstrip('/')}"

    async def ensure_source_readable(self, source_path: str) -> tuple[str, str]:
        """创建任务前确认源视频仍存在，避免不可执行任务长期停留在队列中。"""
        bucket, object_name = parse_minio_path(
            source_path,
            default_bucket=self.video_bucket,
        )
        await anyio.to_thread.run_sync(
            self.client.stat_object,
            bucket,
            object_name,
        )
        return bucket, object_name

    async def download_source_video(self, source_path: str, destination: Path) -> Path:
        bucket, object_name = parse_minio_path(
            source_path,
            default_bucket=self.video_bucket,
        )
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await anyio.to_thread.run_sync(
            self.client.fget_object,
            bucket,
            object_name,
            str(destination),
        )
        return destination

    async def _upload_file(self, source: Path, object_name: str) -> None:
        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        await anyio.to_thread.run_sync(
            partial(
                self.client.fput_object,
                self.result_bucket,
                object_name,
                str(source),
                content_type=content_type,
            )
        )
        await anyio.to_thread.run_sync(
            self.client.stat_object,
            self.result_bucket,
            object_name,
        )

    async def publish(self, publish_dir: Path, *, item_id: int, task_id: str) -> str:
        """先发布所有 WebP，最后发布 Manifest 作为完整版本入口。"""
        publish_dir = Path(publish_dir)
        manifest = publish_dir / "manifest.json"
        image_files = sorted((publish_dir / "images").glob("row_*/frame_*.webp"))
        if not manifest.is_file() or not image_files:
            raise ValueError("Viewer360 publish directory is incomplete")
        prefix = self.result_prefix(item_id, task_id)
        for source in image_files:
            relative = source.relative_to(publish_dir).as_posix()
            await self._upload_file(source, f"{prefix}/{relative}")
        manifest_object = f"{prefix}/manifest.json"
        await self._upload_file(manifest, manifest_object)
        return manifest_object

    async def copy_row(
        self,
        *,
        source_item_id: int,
        source_task_id: str,
        target_item_id: int,
        target_task_id: str,
        row_index: int,
        frame_count: int,
    ) -> int:
        """质量重做时在 OSS 内复制未选角度，避免图片下载后再次上传。"""
        source_prefix = self.result_prefix(source_item_id, source_task_id)
        target_prefix = self.result_prefix(target_item_id, target_task_id)
        for frame_index in range(1, frame_count + 1):
            relative = f"images/row_{row_index:02d}/frame_{frame_index:04d}.webp"
            source_object = f"{source_prefix}/{relative}"
            target_object = f"{target_prefix}/{relative}"
            await anyio.to_thread.run_sync(
                self.client.copy_object,
                self.result_bucket,
                target_object,
                CopySource(self.result_bucket, source_object),
            )
            await anyio.to_thread.run_sync(
                self.client.stat_object,
                self.result_bucket,
                target_object,
            )
        return frame_count

    async def read_json(self, object_name: str) -> dict:
        def read_object() -> dict:
            response = self.client.get_object(self.result_bucket, object_name)
            try:
                return json.loads(response.read().decode("utf-8"))
            finally:
                response.close()
                response.release_conn()

        return await anyio.to_thread.run_sync(read_object)

    async def verify_manifest_objects(self, manifest_object: str, manifest: dict) -> int:
        prefix = manifest_object.rsplit("/", 1)[0]
        image_paths = manifest.get("image_list_grid")
        if not isinstance(image_paths, list) or not image_paths:
            raise ValueError("Viewer360 manifest contains no images")
        for relative in image_paths:
            if not isinstance(relative, str) or not relative.startswith("images/"):
                raise ValueError("Viewer360 manifest contains an invalid image path")
            await anyio.to_thread.run_sync(
                self.client.stat_object,
                self.result_bucket,
                f"{prefix}/{relative}",
            )
        await anyio.to_thread.run_sync(
            self.client.stat_object,
            self.result_bucket,
            manifest_object,
        )
        return len(image_paths)

    async def delete_result(self, *, item_id: int, task_id: str) -> int:
        prefix = f"{self.result_prefix(item_id, task_id)}/"

        def list_names() -> list[str]:
            return [
                item.object_name
                for item in self.client.list_objects(
                    self.result_bucket,
                    prefix=prefix,
                    recursive=True,
                )
            ]

        names = await anyio.to_thread.run_sync(list_names)
        for object_name in names:
            await anyio.to_thread.run_sync(
                self.client.remove_object,
                self.result_bucket,
                object_name,
            )
        return len(names)
