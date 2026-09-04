from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import numpy as np
import pytest
from PIL import Image

from csrcqsf.modules.railway_parts.services.viewer360_archive import (
    Viewer360ArchiveError,
    create_frame_archive,
    extract_segmentation_archive,
)


def _write_jpeg(path: Path, value: int) -> None:
    Image.fromarray(np.full((8, 10, 3), value, dtype=np.uint8)).save(path, "JPEG")


def _result_archive(path: Path, *, frame_count: int = 2) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", '{"frame_count": 2}')
        for index in range(1, frame_count + 1):
            payload = np.zeros((8, 10), dtype=np.uint8)
            payload[2:6, 3:7] = 255
            image_path = path.parent / f"payload-{index}.png"
            Image.fromarray(payload).save(image_path)
            archive.write(image_path, f"masks/frame_{index:04d}.png")


def test_create_frame_archive_uses_contiguous_root_names(tmp_path: Path):
    frames = []
    for index in range(1, 3):
        path = tmp_path / f"source-{index}.jpg"
        _write_jpeg(path, index * 30)
        frames.append(path)

    archive_path = create_frame_archive(frames, tmp_path / "frames.zip")

    with ZipFile(archive_path) as archive:
        assert archive.namelist() == ["frame_0001.jpg", "frame_0002.jpg"]


def test_extract_segmentation_archive_returns_required_sequences(tmp_path: Path):
    archive_path = tmp_path / "result.zip"
    _result_archive(archive_path)

    result = extract_segmentation_archive(archive_path, tmp_path / "result", expected_frames=2)

    assert [path.name for path in result.mask_paths] == ["frame_0001.png", "frame_0002.png"]
    assert result.manifest_path.is_file()


def test_extract_segmentation_archive_rejects_path_traversal(tmp_path: Path):
    archive_path = tmp_path / "unsafe.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("../escaped.txt", "unsafe")

    with pytest.raises(Viewer360ArchiveError, match="unsafe path"):
        extract_segmentation_archive(archive_path, tmp_path / "result", expected_frames=1)


def test_extract_segmentation_archive_rejects_symlink(tmp_path: Path):
    archive_path = tmp_path / "symlink.zip"
    info = ZipInfo("masks/frame_0001.png")
    info.external_attr = 0o120777 << 16
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(info, "target")

    with pytest.raises(Viewer360ArchiveError, match="symbolic link"):
        extract_segmentation_archive(archive_path, tmp_path / "result", expected_frames=1)


def test_extract_segmentation_archive_rejects_missing_frames(tmp_path: Path):
    archive_path = tmp_path / "result.zip"
    _result_archive(archive_path, frame_count=1)

    with pytest.raises(Viewer360ArchiveError, match="expected 2"):
        extract_segmentation_archive(archive_path, tmp_path / "result", expected_frames=2)
