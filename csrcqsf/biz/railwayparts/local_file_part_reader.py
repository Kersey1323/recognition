from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path


@dataclass(frozen=True)
class FilePart:
    part_number: int
    start: int
    end: int
    size: int


class LocalFilePartReader:
    def __init__(self, file_path: str, part_size: int):
        self.file_path = Path(file_path)
        self.part_size = part_size
        self.file_size = self.file_path.stat().st_size

    def list_parts(self) -> list[FilePart]:
        parts: list[FilePart] = []
        total_parts = ceil(self.file_size / self.part_size)
        for index in range(total_parts):
            start = index * self.part_size
            end = min(start + self.part_size, self.file_size)
            parts.append(
                FilePart(
                    part_number=index + 1,
                    start=start,
                    end=end,
                    size=end - start,
                )
            )
        return parts

    def read_part(self, part: FilePart) -> bytes:
        with self.file_path.open("rb") as file:
            file.seek(part.start)
            return file.read(part.size)
