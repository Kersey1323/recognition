"""Viewer360 与模型服务交换 ZIP 时的安全边界。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image, UnidentifiedImageError


@dataclass(frozen=True, slots=True)
class Viewer360ArchiveLimits:
    max_files: int = 800
    max_file_bytes: int = 64 * 1024 * 1024
    max_extracted_bytes: int = 2 * 1024 * 1024 * 1024
    max_archive_bytes: int = 512 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Viewer360SegmentationFiles:
    root: Path
    mask_paths: tuple[Path, ...]
    manifest_path: Path


class Viewer360ArchiveError(ValueError):
    pass


def create_frame_archive(frame_paths: list[Path] | tuple[Path, ...], destination: Path) -> Path:
    if not frame_paths:
        raise Viewer360ArchiveError("frame archive cannot be empty")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for index, path in enumerate(frame_paths, start=1):
            source = Path(path)
            if not source.is_file():
                raise Viewer360ArchiveError(f"frame does not exist: {source}")
            # 模型服务只接受根目录下连续编号的 JPEG，源文件名不参与远端协议。
            archive.write(source, f"frame_{index:04d}.jpg")
    return destination


def _validate_entry(info: ZipInfo, limits: Viewer360ArchiveLimits) -> None:
    raw = info.filename
    path = PurePosixPath(raw)
    if (
        not raw
        or "\\" in raw
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise Viewer360ArchiveError(f"unsafe path in segmentation archive: {raw!r}")
    unix_mode = info.external_attr >> 16
    if unix_mode and stat.S_ISLNK(unix_mode):
        raise Viewer360ArchiveError(f"symbolic link is not allowed: {raw!r}")
    if info.file_size > limits.max_file_bytes:
        raise Viewer360ArchiveError(f"archive file exceeds size limit: {raw!r}")


def _write_entry(archive: ZipFile, info: ZipInfo, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as source, destination.open("wb") as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)


def _required_sequence(root: Path, directory: str, expected_frames: int) -> tuple[Path, ...]:
    paths = tuple(
        root / directory / f"frame_{index:04d}.png"
        for index in range(1, expected_frames + 1)
    )
    actual = tuple(sorted((root / directory).glob("frame_*.png")))
    if actual != paths or not all(path.is_file() for path in paths):
        raise Viewer360ArchiveError(
            f"{directory} contains {len(actual)} frames; expected {expected_frames}"
        )
    for path in paths:
        try:
            with Image.open(path) as image:
                image.verify()
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise Viewer360ArchiveError(f"invalid PNG result: {path.name}: {exc}") from exc
    return paths


def extract_segmentation_archive(
    archive_path: Path,
    destination: Path,
    *,
    expected_frames: int,
    limits: Viewer360ArchiveLimits | None = None,
) -> Viewer360SegmentationFiles:
    """受限解压模型结果，并确认 Mask 与主服务原始帧一一对应。"""
    active_limits = limits or Viewer360ArchiveLimits()
    archive_path = Path(archive_path)
    destination = Path(destination)
    if archive_path.stat().st_size > active_limits.max_archive_bytes:
        raise Viewer360ArchiveError("segmentation archive exceeds upload size limit")
    if destination.exists():
        raise Viewer360ArchiveError(f"segmentation destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-extract-", dir=destination.parent)
    )
    try:
        try:
            with ZipFile(archive_path) as archive:
                infos = archive.infolist()
                if not infos or len(infos) > active_limits.max_files:
                    raise Viewer360ArchiveError("segmentation archive file count is invalid")
                names: set[str] = set()
                expanded = 0
                for info in infos:
                    _validate_entry(info, active_limits)
                    normalized = info.filename.casefold()
                    if normalized in names:
                        raise Viewer360ArchiveError(
                            f"duplicate archive entry: {info.filename!r}"
                        )
                    names.add(normalized)
                    if info.is_dir():
                        continue
                    expanded += info.file_size
                    if expanded > active_limits.max_extracted_bytes:
                        raise Viewer360ArchiveError("segmentation archive expands beyond limit")
                    _write_entry(archive, info, temporary / PurePosixPath(info.filename))
        except BadZipFile as exc:
            raise Viewer360ArchiveError(f"invalid segmentation ZIP: {exc}") from exc

        manifest_path = temporary / "manifest.json"
        if not manifest_path.is_file():
            raise Viewer360ArchiveError("segmentation manifest.json is missing")
        masks = _required_sequence(temporary, "masks", expected_frames)
        os.replace(temporary, destination)
        return Viewer360SegmentationFiles(
            root=destination,
            mask_paths=tuple(destination / path.relative_to(temporary) for path in masks),
            manifest_path=destination / "manifest.json",
        )
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
