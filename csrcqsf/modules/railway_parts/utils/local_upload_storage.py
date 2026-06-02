from __future__ import annotations

import json
import shutil
from pathlib import Path


class LocalUploadStorage:
    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)

    def get_session_dir(self, session_id: int | str) -> Path:
        return self.base_dir / str(session_id)

    def ensure_session_dirs(self, session_id: int | str) -> Path:
        session_dir = self.get_session_dir(session_id)
        (session_dir / "parts").mkdir(parents=True, exist_ok=True)
        (session_dir / "merged").mkdir(parents=True, exist_ok=True)
        meta_path = session_dir / "meta.json"
        if not meta_path.exists():
            meta_path.write_text(
                json.dumps({"uploaded_parts": []}, ensure_ascii=False),
                encoding="utf-8",
            )
        return session_dir

    def load_meta(self, session_dir: Path) -> dict:
        return json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))

    def save_meta(self, session_dir: Path, meta: dict) -> None:
        (session_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def write_part(self, session_dir: Path, part_number: int, data: bytes) -> Path:
        part_path = session_dir / "parts" / f"part-{part_number:05d}"
        part_path.write_bytes(data)
        meta = self.load_meta(session_dir)
        uploaded_parts = sorted(set(meta.get("uploaded_parts", [])) | {part_number})
        meta["uploaded_parts"] = uploaded_parts
        self.save_meta(session_dir, meta)
        return part_path

    def merge_parts(self, session_dir: Path, total_parts: int, output_file_name: str) -> Path:
        merged_path = session_dir / "merged" / output_file_name
        with merged_path.open("wb") as output:
            for part_number in range(1, total_parts + 1):
                output.write((session_dir / "parts" / f"part-{part_number:05d}").read_bytes())
        return merged_path

    def delete_session(self, session_dir: Path) -> None:
        if session_dir.exists():
            shutil.rmtree(session_dir)
