from __future__ import annotations

import io
from collections.abc import Callable

from anyio.to_thread import run_sync
from bfrcommon.snowflake import get_id
from PIL import Image

from csrcqsf.core.settings import minio_bucket
from csrcqsf.infra.storage.minio import minio_instance, parse_minio_path
from csrcqsf.models.orm.sgo import SegmentedImage
from csrcqsf.modules.sgo.schemas import SegmentStatus


class SegmentedImageService:
    def __init__(
        self,
        session,
        *,
        minio_client=None,
        bucket: str = minio_bucket,
        id_factory: Callable[[], int] = get_id,
    ) -> None:
        self.session = session
        self.minio_client = minio_client or minio_instance.client
        self.bucket = bucket
        self.id_factory = id_factory

    async def get_latest_success(
        self,
        item_id: int,
        source_image_id: int,
    ) -> SegmentedImage | None:
        return await SegmentedImage.get_latest_success(
            self.session,
            item_id,
            source_image_id,
        )

    async def persist_success(
        self,
        *,
        item_id: int,
        source_image_id: int,
        source_image_url: str,
        image: Image.Image,
        bbox: tuple[int, int, int, int],
        mask_area: int,
    ) -> SegmentedImage:
        record = SegmentedImage(
            id=self.id_factory(),
            item_id=item_id,
            source_image_id=source_image_id,
            source_image_url=source_image_url,
            status=SegmentStatus.PENDING,
            is_indexed=0,
        )
        self.session.add(record)
        await self.session.flush()

        object_name = f"segmented/{item_id}/{source_image_id}/{record.id}.png"
        stream = io.BytesIO()
        image.convert("RGB").save(stream, format="PNG")
        content = stream.getvalue()

        def upload() -> None:
            self.minio_client.put_object(
                self.bucket,
                object_name,
                io.BytesIO(content),
                len(content),
                content_type="image/png",
            )

        try:
            await run_sync(upload)
        except Exception as exc:
            record.status = SegmentStatus.FAILED
            record.error_message = str(exc)
            await self.session.flush()
            raise

        record.segmented_image_url = f"{self.bucket}/{object_name}"
        record.status = SegmentStatus.SUCCESS
        record.mask_area = mask_area
        record.bbox_x, record.bbox_y, record.bbox_w, record.bbox_h = bbox
        await self.session.flush()
        return record

    async def mark_indexed(self, record: SegmentedImage) -> None:
        record.is_indexed = 1
        await self.session.flush()

    async def persist_failure(
        self,
        *,
        item_id: int,
        source_image_id: int,
        source_image_url: str,
        error: str,
    ) -> SegmentedImage:
        record = SegmentedImage(
            id=self.id_factory(),
            item_id=item_id,
            source_image_id=source_image_id,
            source_image_url=source_image_url,
            status=SegmentStatus.FAILED,
            is_indexed=0,
            error_message=error,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def load_image(self, record: SegmentedImage) -> Image.Image:
        if not record.segmented_image_url:
            raise ValueError(f"分割记录缺少对象路径: record_id={record.id}")
        bucket, object_name = parse_minio_path(
            record.segmented_image_url,
            default_bucket=self.bucket,
        )

        def download() -> bytes:
            response = self.minio_client.get_object(bucket, object_name)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        content = await run_sync(download)
        return Image.open(io.BytesIO(content)).convert("RGB")

    async def remove_source_artifacts(
        self,
        item_id: int,
        source_image_id: int,
    ) -> int:
        records = await SegmentedImage.list_by_source_image(
            self.session,
            item_id,
            source_image_id,
        )
        for record in records:
            if not record.segmented_image_url:
                continue
            bucket, object_name = parse_minio_path(
                record.segmented_image_url,
                default_bucket=self.bucket,
            )
            await run_sync(self.minio_client.remove_object, bucket, object_name)
        await SegmentedImage.delete_by_source_image(
            self.session,
            item_id,
            source_image_id,
        )
        return len(records)
