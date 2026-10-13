#!/usr/bin/env python3
"""Restore missing objects referenced by the current has_images item list."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import io
import json
from pathlib import Path
import time
import zipfile

from sqlalchemy import text

from csrcqsf.core.scheduler import scheduler
from csrcqsf.infra.db.main_db import engine
from csrcqsf.infra.storage.minio import minio_bucket, minio_instance, parse_minio_path
from csrcqsf.modules.sgo import services
from csrcqsf.modules.sgo.services import SGOBiz


async def load_records() -> list[dict]:
    async with engine.connect() as conn:
        rows = await conn.execute(text("""
            SELECT im.id AS image_id, im.item_id, it.item_code, it.item_name,
                   im.image_url, im.raw_url, im.image_source
            FROM sgo_item_image_info im
            JOIN item_info it ON it.id = im.item_id
            WHERE im.is_deleted = 0
            ORDER BY it.time_created DESC, it.id DESC, im.id ASC
        """))
        return [dict(row) for row in rows.mappings()]


def ordered_objects(records: list[dict]) -> tuple[list[dict], list[dict]]:
    by_object: dict[str, dict] = {}
    unsupported = []
    item_rank = {}
    per_item = Counter()
    for record in records:
        item_id = record["item_id"]
        item_rank.setdefault(item_id, len(item_rank))
        try:
            bucket, object_name = parse_minio_path(record["image_url"])
            if bucket != minio_bucket:
                raise ValueError("image references a different bucket")
        except ValueError as exc:
            unsupported.append({**record, "error_message": str(exc)})
            continue
        if object_name in by_object:
            continue
        # Restore one image per item before additional images to maximize page coverage.
        rank = per_item[item_id]
        per_item[item_id] += 1
        by_object[object_name] = {
            **record,
            "object_name": object_name,
            "priority": (rank, item_rank[item_id]),
        }
    return sorted(by_object.values(), key=lambda row: row["priority"]), unsupported


async def restore(args) -> dict:
    if scheduler.running:
        scheduler.shutdown(wait=False)
    # A standalone recovery must not occupy download workers for repeated long timeouts.
    services.sgo_image_download_timeout_seconds = args.download_timeout
    services.sgo_image_download_retries = 1
    client = minio_instance.client
    records = await load_records()
    objects, unsupported = ordered_objects(records)
    exists = await asyncio.to_thread(client.bucket_exists, minio_bucket)
    existing = {}
    if exists:
        existing = await asyncio.to_thread(
            lambda: {
                obj.object_name: obj.size
                for obj in client.list_objects(minio_bucket, recursive=True)
            }
        )
    missing = [row for row in objects if not existing.get(row["object_name"], 0)]
    unavailable = [row for row in missing if not row["raw_url"] or row["image_source"] not in {"BASEINFO", "INQUERY"}]
    recoverable = [
        row for row in missing
        if row["raw_url"] and row["image_source"] in {"BASEINFO", "INQUERY"}
    ]
    if args.limit:
        recoverable = recoverable[:args.limit]
    summary = {
        "status": "preview" if args.dry_run else "running",
        "items": len({row["item_id"] for row in records}),
        "image_records": len(records),
        "unique_objects": len(objects),
        "existing_objects": len(objects) - len(missing),
        "recoverable_missing": len(recoverable),
        "unrecoverable_missing": len(unavailable) + len(unsupported),
        "bucket_initial_bytes": sum(existing.values()),
        "max_bucket_bytes": int(args.max_gib * 1024 ** 3),
        "restored_objects": 0,
        "restored_bytes": 0,
        "failed_objects": 0,
        "processed_objects": 0,
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if args.dry_run:
        return summary
    args.output.mkdir(parents=True, exist_ok=True)
    summary_path = args.output / "summary.json"
    events_path = args.output / "events.jsonl"
    (args.output / "unrecoverable.json").write_text(
        json.dumps(unavailable + unsupported, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    started = time.monotonic()
    stop = asyncio.Event()
    budget_lock = asyncio.Lock()
    reserved_bytes = 0
    failures_by_type = Counter()

    def save_summary():
        summary["elapsed_seconds"] = round(time.monotonic() - started, 2)
        summary["failure_types"] = dict(failures_by_type)
        summary["remaining_recoverable"] = len(recoverable) - summary["restored_objects"]
        temporary = summary_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(summary_path)

    def event(row, status, **details):
        with events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "image_id": str(row["image_id"]),
                "item_id": str(row["item_id"]),
                "item_code": row["item_code"],
                "item_name": row["item_name"],
                "object_name": row["object_name"],
                "status": status,
                **details,
            }, ensure_ascii=False) + "\n")

    if summary["bucket_initial_bytes"] >= summary["max_bucket_bytes"]:
        summary["status"] = "space_limit"
        save_summary()
        return summary
    if recoverable:
        authenticated = await asyncio.to_thread(SGOBiz.get_token)
        if not authenticated:
            raise RuntimeError("SGO authentication failed; no files were written")
        if not exists:
            await asyncio.to_thread(client.make_bucket, minio_bucket)
    queue = iter(recoverable)

    async def worker():
        nonlocal reserved_bytes
        while not stop.is_set():
            row = next(queue, None)
            if row is None:
                return
            reservation = 0
            try:
                payload = await asyncio.to_thread(SGOBiz.download_images_from_sgo, [row["raw_url"]])
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                    if len(entries) != 1:
                        raise ValueError(f"expected one image, received {len(entries)}")
                    content = archive.read(entries[0])
                if not content:
                    raise ValueError("SGO returned an empty image")
                async with budget_lock:
                    # Reserve upload bytes before starting concurrent writes to enforce the cap.
                    usage = summary["bucket_initial_bytes"] + summary["restored_bytes"] + reserved_bytes
                    if usage + len(content) > summary["max_bucket_bytes"]:
                        stop.set()
                        event(row, "space_limit", image_bytes=len(content))
                        continue
                    reservation = len(content)
                    reserved_bytes += reservation
                await asyncio.to_thread(
                    client.put_object, minio_bucket, row["object_name"],
                    io.BytesIO(content), len(content),
                )
                # A successful write consumes space even if its subsequent verification fails.
                async with budget_lock:
                    summary["restored_bytes"] += len(content)
                    reserved_bytes -= reservation
                    reservation = 0
                stat = await asyncio.to_thread(client.stat_object, minio_bucket, row["object_name"])
                if stat.size != len(content):
                    raise ValueError("uploaded object size does not match source")
                summary["restored_objects"] += 1
                event(row, "restored", size_bytes=len(content))
            except Exception as exc:
                summary["failed_objects"] += 1
                failures_by_type[type(exc).__name__] += 1
                event(row, "failed", error_type=type(exc).__name__, error_message=str(exc))
            finally:
                if reservation:
                    async with budget_lock:
                        reserved_bytes -= reservation
                summary["processed_objects"] += 1
                save_summary()

    async def progress():
        while True:
            await asyncio.sleep(10)
            print(
                f"processed={summary['processed_objects']}/{len(recoverable)} "
                f"restored={summary['restored_objects']} failed={summary['failed_objects']} "
                f"uploaded_gib={summary['restored_bytes'] / 1024**3:.3f}",
                flush=True,
            )

    save_summary()
    reporter = asyncio.create_task(progress())
    try:
        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        summary["status"] = "space_limit" if stop.is_set() else "completed"
    except BaseException:
        summary["status"] = "interrupted"
        raise
    finally:
        reporter.cancel()
        save_summary()
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-gib", type=float, default=10)
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--download-timeout", type=int, default=45)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_gib <= 0 or args.download_timeout <= 0 or args.limit < 0:
        parser.error("limits and timeouts must be positive")

    async def run():
        try:
            await restore(args)
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
