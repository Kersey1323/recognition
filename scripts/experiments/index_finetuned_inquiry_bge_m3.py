#!/usr/bin/env python3
"""将现有询码文档使用微调 BGE-M3 重编码到独立 Milvus Collection。"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from dotenv import load_dotenv
from pymilvus import DataType, MilvusClient
from transformers import AutoModel, AutoTokenizer


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = Path.home() / "CV/models/bge-m3-inquiry-v1/best"
DEFAULT_TARGET_COLLECTION = "PARTS_INQUIRY_BGE_M3_1024D_FINETUNED_20260910_V1"
SOURCE_FIELDS = [
    "document_key",
    "history_id",
    "inquiry_id",
    "item_id",
    "item_code",
    "description",
    "content_hash",
    "updated_at",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--source-collection", default="")
    parser.add_argument("--target-collection", default=DEFAULT_TARGET_COLLECTION)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument(
        "--verify-existing",
        action="store_true",
        help="不写入数据，只核对已存在目标库与源库的有效主键",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "tmp/bge_m3_finetuned_milvus_index_report.json",
    )
    return parser.parse_args()


def create_collection(client: MilvusClient, collection_name: str) -> None:
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(
        field_name="document_key",
        datatype=DataType.VARCHAR,
        max_length=64,
        is_primary=True,
    )
    schema.add_field(field_name="history_id", datatype=DataType.INT64)
    schema.add_field(
        field_name="inquiry_id", datatype=DataType.VARCHAR, max_length=100
    )
    schema.add_field(field_name="item_id", datatype=DataType.INT64)
    schema.add_field(field_name="item_code", datatype=DataType.VARCHAR, max_length=100)
    schema.add_field(
        field_name="description", datatype=DataType.VARCHAR, max_length=1000
    )
    schema.add_field(
        field_name="content_hash", datatype=DataType.VARCHAR, max_length=64
    )
    schema.add_field(
        field_name="text_vector", datatype=DataType.FLOAT_VECTOR, dim=1024
    )
    schema.add_field(
        field_name="updated_at", datatype=DataType.VARCHAR, max_length=50
    )

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="text_vector",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )
    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params,
    )


def iter_source_batches(
    client: MilvusClient,
    collection_name: str,
    batch_size: int,
):
    iterator = client.query_iterator(
        collection_name=collection_name,
        batch_size=batch_size,
        filter="",
        output_fields=SOURCE_FIELDS,
    )
    try:
        while True:
            rows = iterator.next()
            if not rows:
                return
            yield [dict(row) for row in rows]
    finally:
        iterator.close()


def encode(model, tokenizer, texts: list[str], max_length: int) -> np.ndarray:
    inputs = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    inputs = {name: value.cuda(non_blocking=True) for name, value in inputs.items()}
    with torch.inference_mode(), torch.autocast(
        device_type="cuda", dtype=torch.bfloat16
    ):
        outputs = model(**inputs)
        vectors = F.normalize(outputs.last_hidden_state[:, 0], p=2, dim=1)
    return vectors.float().cpu().numpy()


def load_document_keys(client: MilvusClient, collection_name: str) -> set[str]:
    keys: set[str] = set()
    iterator = client.query_iterator(
        collection_name=collection_name,
        batch_size=1000,
        filter="",
        output_fields=["document_key"],
    )
    try:
        while True:
            rows = iterator.next()
            if not rows:
                return keys
            keys.update(str(row["document_key"]) for row in rows)
    finally:
        iterator.close()


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0 or args.max_length <= 0:
        raise ValueError("batch-size 和 max-length 必须大于 0")
    if not torch.cuda.is_available():
        raise RuntimeError("全量重编码需要可用的 CUDA GPU")

    load_dotenv(args.env_file, override=True)
    client = MilvusClient(
        uri=f"http://{os.getenv('MILVUS_HOST', 'localhost')}:{os.getenv('MILVUS_PORT', '19530')}"
    )
    source = args.source_collection or os.getenv(
        "INQUIRY_TEXT_COLLECTION_ALIAS", "PARTS_INQUIRY_BGE_M3_CURRENT"
    )
    target = args.target_collection.strip()
    source_description = client.describe_collection(source)
    source_physical_name = str(source_description["collection_name"])
    if not target or target in {source, source_physical_name}:
        raise ValueError("目标 Collection 必须与当前询码索引物理库和 Alias 不同")
    target_exists = client.has_collection(target)
    if target_exists and not args.verify_existing:
        raise FileExistsError(f"目标 Collection 已存在，拒绝覆盖: {target}")

    if args.verify_existing:
        if not target_exists:
            raise FileNotFoundError(f"待核验的目标 Collection 不存在: {target}")
        client.flush(collection_name=target)
        client.load_collection(collection_name=target)
        source_keys = load_document_keys(client, source)
        target_keys = load_document_keys(client, target)
        missing_keys = source_keys - target_keys
        extra_keys = target_keys - source_keys
        if missing_keys or extra_keys:
            raise RuntimeError(
                "源库与目标库有效主键不一致: "
                f"source={len(source_keys)}, target={len(target_keys)}, "
                f"missing={len(missing_keys)}, extra={len(extra_keys)}"
            )
        report = {
            "source_alias": source,
            "source_collection": source_physical_name,
            "target_collection": target,
            "model_dir": str(args.model_dir),
            "source_effective_documents": len(source_keys),
            "target_effective_documents": len(target_keys),
            "document_keys_equal": True,
            "alias_switched": False,
            "index": client.describe_index(target, "text_vector"),
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return

    create_collection(client, target)
    client.load_collection(collection_name=target)
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir)
    model = AutoModel.from_pretrained(args.model_dir).cuda().eval()

    estimated_count = int(client.get_collection_stats(source)["row_count"])
    indexed_count = 0
    source_keys: set[str] = set()
    started_at = time.perf_counter()
    try:
        for batch in iter_source_batches(client, source, args.batch_size):
            source_keys.update(str(row["document_key"]) for row in batch)
            vectors = encode(
                model,
                tokenizer,
                [str(row["description"]) for row in batch],
                args.max_length,
            )
            records = []
            for row, vector in zip(batch, vectors):
                record = {field: row[field] for field in SOURCE_FIELDS}
                record["text_vector"] = vector.tolist()
                records.append(record)
            result = client.insert(collection_name=target, data=records)
            indexed_count += int(result.get("insert_count", len(records)))
            print(
                json.dumps(
                    {
                        "indexed": indexed_count,
                        "estimated": estimated_count,
                        "progress": round(indexed_count * 100 / estimated_count, 2),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        client.flush(collection_name=target)
        client.load_collection(collection_name=target)
        target_keys = load_document_keys(client, target)
        if indexed_count != len(source_keys) or target_keys != source_keys:
            raise RuntimeError(
                "索引有效主键不一致: "
                f"source={len(source_keys)}, inserted={indexed_count}, "
                f"target={len(target_keys)}"
            )
    except Exception:
        # 失败库保留现场，避免无确认删除 Milvus 数据；重试时应使用新的目标库名。
        raise

    report = {
        "source_alias": source,
        "source_collection": source_physical_name,
        "target_collection": target,
        "model_dir": str(args.model_dir),
        "source_stats_row_count": estimated_count,
        "effective_document_count": len(source_keys),
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "alias_switched": False,
        "index": {
            "type": "HNSW",
            "metric_type": "COSINE",
            "M": 16,
            "efConstruction": 200,
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
