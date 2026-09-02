import asyncio
from pathlib import Path

import numpy as np
from PIL import Image

from csrcqsf.infra.external.model_client import ModelServiceClient


def _jpeg(path: Path) -> None:
    Image.fromarray(np.full((6, 8, 3), 100, dtype=np.uint8)).save(path, "JPEG")


def test_segment_video_frames_posts_expected_multipart_and_writes_response(
    tmp_path: Path,
    monkeypatch,
):
    frame = tmp_path / "frame.jpg"
    _jpeg(frame)
    captured = {}
    client = ModelServiceClient("http://model")

    async def fake_request(path, *, data, destination, timeout_seconds):
        frames_field = next(
            field for field in data._fields if field[0].get("name") == "frames"
        )
        captured.update(
            path=path,
            data=data,
            destination=destination,
            timeout_seconds=timeout_seconds,
            archive_closed_during_request=frames_field[2].closed,
        )
        destination.write_bytes(b"zip-response")
        return destination

    monkeypatch.setattr(client, "_request_binary_to_file", fake_request)
    destination = tmp_path / "response.zip"

    result = asyncio.run(
        client.segment_video_frames(
            [frame],
            request_id="task-1",
            angle_id="angle_01",
            destination=destination,
            timeout_seconds=321,
        )
    )

    assert result == destination
    assert destination.read_bytes() == b"zip-response"
    assert captured["path"] == "/api/v1/segmentation/video"
    assert captured["timeout_seconds"] == 321
    assert captured["destination"].name == "response.zip.tmp"
    assert captured["archive_closed_during_request"] is False
    field_names = [field[0].get("name") for field in captured["data"]._fields]
    assert field_names == ["frames", "request_id", "angle_id"]
