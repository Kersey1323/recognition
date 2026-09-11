#!/usr/bin/env python3
"""从当前询码文本索引构建 BGE-M3 微调、验证和样本外测试数据集。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "tmp/bge_finetune_dataset_20260910"
DEFAULT_EXTERNAL_TEST = (
    PROJECT_ROOT / "tmp/bge_new_online_vehicle_prefilter_candidates_20260910.json"
)


class InquiryRecord(NamedTuple):
    history_id: int
    inquiry_num: str
    vehicle: str
    item_code: str
    description: str
    inquiry_time: datetime


def normalize_key_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", normalized).strip().upper()


def normalize_display_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", normalized).strip()


def find_ambiguous_vehicle_descriptions(
    records: list[InquiryRecord],
) -> set[tuple[str, str]]:
    codes_by_description: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in records:
        key = (
            normalize_key_text(record.vehicle),
            normalize_key_text(record.description),
        )
        codes_by_description[key].add(normalize_key_text(record.item_code))
    return {
        key for key, item_codes in codes_by_description.items() if len(item_codes) > 1
    }


def find_globally_ambiguous_descriptions(
    records: list[InquiryRecord],
) -> set[str]:
    codes_by_description: dict[str, set[str]] = defaultdict(set)
    for record in records:
        codes_by_description[normalize_key_text(record.description)].add(
            normalize_key_text(record.item_code)
        )
    return {
        description
        for description, item_codes in codes_by_description.items()
        if len(item_codes) > 1
    }


def _clean_supervised_records(
    records: list[InquiryRecord], *, global_ambiguity: bool = False
) -> list[InquiryRecord]:
    ambiguous_by_vehicle = find_ambiguous_vehicle_descriptions(records)
    globally_ambiguous = (
        find_globally_ambiguous_descriptions(records) if global_ambiguity else set()
    )
    selected: dict[tuple[str, str, str], InquiryRecord] = {}
    for record in sorted(records, key=lambda row: (row.inquiry_time, row.history_id)):
        vehicle = normalize_key_text(record.vehicle)
        item_code = normalize_key_text(record.item_code)
        description = normalize_key_text(record.description)
        if not vehicle or not item_code or not description:
            continue
        if (vehicle, description) in ambiguous_by_vehicle:
            continue
        if description in globally_ambiguous:
            continue
        selected.setdefault((vehicle, item_code, description), record)
    return list(selected.values())


def _select_query_records(
    records: list[InquiryRecord], max_queries_per_code: int
) -> tuple[list[InquiryRecord], dict[str, list[InquiryRecord]]]:
    records_by_code: dict[str, list[InquiryRecord]] = defaultdict(list)
    for record in records:
        records_by_code[normalize_key_text(record.item_code)].append(record)

    positive_pool: dict[str, list[InquiryRecord]] = {}
    selected_queries: list[InquiryRecord] = []
    for item_code in sorted(records_by_code):
        # 一个编码的相同描述只保留最早样本，正样本必须是另一种自然语言表达。
        by_description: dict[str, InquiryRecord] = {}
        for record in sorted(
            records_by_code[item_code], key=lambda row: (row.inquiry_time, row.history_id)
        ):
            by_description.setdefault(normalize_key_text(record.description), record)
        candidates = list(by_description.values())
        if len(candidates) < 2:
            continue
        positive_pool[item_code] = candidates
        selected_queries.extend(candidates[:max_queries_per_code])
    return selected_queries, positive_pool


def _mine_negative_records(
    queries: list[InquiryRecord],
    corpus: list[InquiryRecord],
    vectors: dict[int, np.ndarray],
    *,
    hard_negative_count: int,
    random_negative_count: int,
    seed: int,
) -> dict[int, list[InquiryRecord]]:
    corpus_by_vehicle: dict[str, list[InquiryRecord]] = defaultdict(list)
    queries_by_vehicle: dict[str, list[InquiryRecord]] = defaultdict(list)
    for record in corpus:
        if record.history_id in vectors:
            corpus_by_vehicle[normalize_key_text(record.vehicle)].append(record)
    for record in queries:
        if record.history_id in vectors:
            queries_by_vehicle[normalize_key_text(record.vehicle)].append(record)

    negatives_by_query: dict[int, list[InquiryRecord]] = {}
    for vehicle, vehicle_queries in queries_by_vehicle.items():
        candidates = sorted(
            corpus_by_vehicle.get(vehicle, []),
            key=lambda row: (
                normalize_key_text(row.item_code),
                normalize_key_text(row.description),
                row.history_id,
            ),
        )
        if not candidates:
            continue
        candidate_matrix = np.asarray(
            [vectors[record.history_id] for record in candidates], dtype=np.float32
        )
        for offset in range(0, len(vehicle_queries), 128):
            batch = vehicle_queries[offset : offset + 128]
            query_matrix = np.asarray(
                [vectors[record.history_id] for record in batch], dtype=np.float32
            )
            similarities = query_matrix @ candidate_matrix.T
            for query, scores in zip(batch, similarities):
                order = np.argsort(-scores, kind="stable")
                ranked: list[InquiryRecord] = []
                seen_codes: set[str] = set()
                query_code = normalize_key_text(query.item_code)
                query_description = normalize_key_text(query.description)
                for candidate_index in order:
                    candidate = candidates[int(candidate_index)]
                    code = normalize_key_text(candidate.item_code)
                    if code == query_code or code in seen_codes:
                        continue
                    if normalize_key_text(candidate.description) == query_description:
                        continue
                    seen_codes.add(code)
                    ranked.append(candidate)

                hard = ranked[:hard_negative_count]
                remaining = ranked[hard_negative_count:]
                rng = random.Random(f"{seed}:{query.history_id}")
                random_count = min(random_negative_count, len(remaining))
                sampled = rng.sample(remaining, random_count) if random_count else []
                negatives_by_query[query.history_id] = hard + sampled
    return negatives_by_query


def build_training_examples(
    records: list[InquiryRecord],
    vectors: dict[int, np.ndarray],
    *,
    max_queries_per_code: int = 5,
    positive_count: int = 2,
    hard_negative_count: int = 6,
    random_negative_count: int = 2,
    seed: int = 20260910,
) -> tuple[list[dict], list[dict]]:
    clean_records = _clean_supervised_records(records)
    queries, positive_pool = _select_query_records(
        clean_records, max_queries_per_code
    )
    negatives_by_query = _mine_negative_records(
        queries,
        clean_records,
        vectors,
        hard_negative_count=hard_negative_count,
        random_negative_count=random_negative_count,
        seed=seed,
    )

    examples: list[dict] = []
    metadata: list[dict] = []
    for query in queries:
        item_code = normalize_key_text(query.item_code)
        query_description = normalize_key_text(query.description)
        positives = [
            record
            for record in positive_pool[item_code]
            if normalize_key_text(record.description) != query_description
        ]
        # 同车型表达优先作为正样本，不足时再使用同编码的跨车型真实描述。
        positives.sort(
            key=lambda row: (
                normalize_key_text(row.vehicle) != normalize_key_text(query.vehicle),
                row.inquiry_time,
                row.history_id,
            )
        )
        positives = positives[:positive_count]
        negatives = negatives_by_query.get(query.history_id, [])
        if not positives or not negatives:
            continue
        examples.append(
            {
                "query": normalize_display_text(query.description),
                "pos": [normalize_display_text(row.description) for row in positives],
                "neg": [normalize_display_text(row.description) for row in negatives],
            }
        )
        metadata.append(
            {
                "query_history_id": query.history_id,
                "inquiry_num": query.inquiry_num,
                "vehicle": normalize_key_text(query.vehicle),
                "item_code": item_code,
                "positive_history_ids": [row.history_id for row in positives],
                "negative_history_ids": [row.history_id for row in negatives],
                "negative_item_codes": [
                    normalize_key_text(row.item_code) for row in negatives
                ],
            }
        )
    return examples, metadata


def _character_bigrams(value: str) -> set[str]:
    compact = "".join(re.findall(r"[\w]", normalize_key_text(value)))
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[index : index + 2] for index in range(len(compact) - 1)}


def _lexical_similarity(left: str, right: str) -> float:
    left_grams = _character_bigrams(left)
    right_grams = _character_bigrams(right)
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / len(left_grams | right_grams)


def build_mixed_training_examples(
    records: list[InquiryRecord],
    vectors: dict[int, np.ndarray],
    *,
    global_rankings: dict[int, list[InquiryRecord]],
    max_queries_per_code: int = 5,
    positive_count: int = 2,
    same_vehicle_hard_count: int = 4,
    cross_vehicle_hard_count: int = 4,
    lexical_hard_count: int = 2,
    random_negative_count: int = 2,
    seed: int = 20260910,
) -> tuple[list[dict], list[dict]]:
    # 无车型检索无法消解同一描述对应多个编码的冲突，此类样本不参与监督训练。
    clean_records = _clean_supervised_records(records, global_ambiguity=True)
    queries, positive_pool = _select_query_records(
        clean_records, max_queries_per_code
    )
    same_vehicle_negatives = _mine_negative_records(
        queries,
        clean_records,
        vectors,
        hard_negative_count=same_vehicle_hard_count,
        random_negative_count=0,
        seed=seed,
    )
    random_pool = sorted(
        clean_records,
        key=lambda row: (
            normalize_key_text(row.item_code),
            normalize_key_text(row.description),
            row.history_id,
        ),
    )

    examples: list[dict] = []
    metadata: list[dict] = []
    for query in queries:
        item_code = normalize_key_text(query.item_code)
        vehicle = normalize_key_text(query.vehicle)
        query_description = normalize_key_text(query.description)
        positives = [
            record
            for record in positive_pool[item_code]
            if normalize_key_text(record.description) != query_description
        ]
        # 跨车型正例优先，使同一配件在不同车型下的真实描述保持接近。
        positives.sort(
            key=lambda row: (
                normalize_key_text(row.vehicle) == vehicle,
                row.inquiry_time,
                row.history_id,
            )
        )
        positives = positives[:positive_count]

        negatives: list[InquiryRecord] = []
        negative_types: list[str] = []
        seen_codes: set[str] = {item_code}
        seen_descriptions: set[str] = {query_description}

        def add_negative(record: InquiryRecord, negative_type: str) -> bool:
            code = normalize_key_text(record.item_code)
            description = normalize_key_text(record.description)
            if code in seen_codes or description in seen_descriptions:
                return False
            seen_codes.add(code)
            seen_descriptions.add(description)
            negatives.append(record)
            negative_types.append(negative_type)
            return True

        for record in same_vehicle_negatives.get(query.history_id, []):
            if len(negative_types) >= same_vehicle_hard_count:
                break
            add_negative(record, "same_vehicle_dense")

        global_candidates = global_rankings.get(query.history_id, [])
        added_cross = 0
        for record in global_candidates:
            if normalize_key_text(record.vehicle) == vehicle:
                continue
            if add_negative(record, "cross_vehicle_dense"):
                added_cross += 1
                if added_cross >= cross_vehicle_hard_count:
                    break

        lexical_candidates = sorted(
            global_candidates,
            key=lambda row: (
                -_lexical_similarity(query.description, row.description),
                row.history_id,
            ),
        )
        added_lexical = 0
        for record in lexical_candidates:
            if _lexical_similarity(query.description, record.description) <= 0:
                break
            if add_negative(record, "lexical_hard"):
                added_lexical += 1
                if added_lexical >= lexical_hard_count:
                    break

        random_candidates = list(random_pool)
        random.Random(f"{seed}:{query.history_id}:global").shuffle(random_candidates)
        added_random = 0
        for record in random_candidates:
            if add_negative(record, "global_random"):
                added_random += 1
                if added_random >= random_negative_count:
                    break

        if not positives or not negatives:
            continue
        examples.append(
            {
                "query": normalize_display_text(query.description),
                "pos": [normalize_display_text(row.description) for row in positives],
                "neg": [normalize_display_text(row.description) for row in negatives],
            }
        )
        metadata.append(
            {
                "query_history_id": query.history_id,
                "inquiry_num": query.inquiry_num,
                "vehicle": vehicle,
                "item_code": item_code,
                "positive_history_ids": [row.history_id for row in positives],
                "negative_history_ids": [row.history_id for row in negatives],
                "negative_item_codes": [
                    normalize_key_text(row.item_code) for row in negatives
                ],
                "negative_types": negative_types,
            }
        )
    return examples, metadata


def build_validation_queries(
    records: list[InquiryRecord],
    cutoff: datetime,
    excluded_query_targets: set[tuple[str, str]] | None = None,
    global_ambiguity: bool = False,
) -> list[dict]:
    excluded_query_targets = {
        (normalize_key_text(query), normalize_key_text(item_code))
        for query, item_code in (excluded_query_targets or set())
    }
    ambiguous = find_ambiguous_vehicle_descriptions(records)
    globally_ambiguous = (
        find_globally_ambiguous_descriptions(records) if global_ambiguity else set()
    )
    training = [record for record in records if record.inquiry_time < cutoff]
    validation = [record for record in records if record.inquiry_time >= cutoff]
    # 验证时会先按车型强过滤，因此只有同车型下已进入语料库的编码才是可召回目标。
    known_descriptions_by_target: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in training:
        target = (
            normalize_key_text(record.vehicle),
            normalize_key_text(record.item_code),
        )
        known_descriptions_by_target[target].add(
            normalize_key_text(record.description)
        )

    selected: dict[tuple[str, str, str], dict] = {}
    for record in sorted(validation, key=lambda row: (row.inquiry_time, row.history_id)):
        vehicle = normalize_key_text(record.vehicle)
        item_code = normalize_key_text(record.item_code)
        description = normalize_key_text(record.description)
        if not vehicle or not item_code or not description:
            continue
        if (vehicle, description) in ambiguous:
            continue
        if description in globally_ambiguous:
            continue
        # BGE 只接收描述文本；即使车型不同，训练阶段见过同一描述也会造成验证泄漏。
        if (description, item_code) in excluded_query_targets:
            continue
        known_descriptions = known_descriptions_by_target.get((vehicle, item_code))
        if not known_descriptions or description in known_descriptions:
            continue
        selected.setdefault(
            (vehicle, item_code, description),
            {
                "history_id": record.history_id,
                "inquiry_num": record.inquiry_num,
                "vehicle": vehicle,
                "query": normalize_display_text(record.description),
                "target_item_code": item_code,
            },
        )
    return list(selected.values())


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _corpus_rows(records: list[InquiryRecord]) -> list[dict]:
    return [
        {
            "history_id": record.history_id,
            "inquiry_num": record.inquiry_num,
            "vehicle": normalize_key_text(record.vehicle),
            "item_code": normalize_key_text(record.item_code),
            "description": normalize_display_text(record.description),
            "inquiry_time": record.inquiry_time.isoformat(),
        }
        for record in sorted(records, key=lambda row: (row.inquiry_time, row.history_id))
    ]


def _external_test_queries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        {
            "inquiry_num": row["inquiry_num"],
            "vehicle": normalize_key_text(row["vehicle"]),
            "query": normalize_display_text(row["query"]),
            "target_item_code": normalize_key_text(row["target_item_code"]),
        }
        for row in payload.get("experiments", [])
        if row.get("is_novel_description_code_pair")
    ]


def _load_index_rows(client, collection_name: str) -> list[dict]:
    iterator = client.query_iterator(
        collection_name=collection_name,
        batch_size=1000,
        filter="",
        output_fields=["history_id", "item_code", "description", "text_vector"],
    )
    rows: list[dict] = []
    try:
        while True:
            batch = iterator.next()
            if not batch:
                return rows
            rows.extend(dict(row) for row in batch)
    finally:
        iterator.close()


def _mine_global_rankings_from_milvus(
    queries: list[InquiryRecord],
    candidate_records: list[InquiryRecord],
    vectors: dict[int, np.ndarray],
    collection_name: str,
    *,
    search_limit: int,
    search_batch_size: int = 32,
) -> dict[int, list[InquiryRecord]]:
    from pymilvus import MilvusClient

    client = MilvusClient(
        uri=f"http://{os.getenv('MILVUS_HOST', 'localhost')}:{os.getenv('MILVUS_PORT', '19530')}"
    )
    records_by_id = {record.history_id: record for record in candidate_records}
    searchable_queries = [record for record in queries if record.history_id in vectors]
    rankings: dict[int, list[InquiryRecord]] = {}
    for offset in range(0, len(searchable_queries), search_batch_size):
        batch = searchable_queries[offset : offset + search_batch_size]
        results = client.search(
            collection_name=collection_name,
            data=[vectors[record.history_id].tolist() for record in batch],
            anns_field="text_vector",
            limit=search_limit,
            output_fields=["history_id"],
            search_params={
                "metric_type": "COSINE",
                "params": {"ef": max(64, search_limit)},
            },
        )
        for query, hits in zip(batch, results):
            ranked: list[InquiryRecord] = []
            seen_history_ids: set[int] = set()
            for hit in hits:
                history_id = int(hit.get("entity", {}).get("history_id", 0) or 0)
                candidate = records_by_id.get(history_id)
                if candidate is None or history_id in seen_history_ids:
                    continue
                seen_history_ids.add(history_id)
                ranked.append(candidate)
            rankings[query.history_id] = ranked
        print(
            json.dumps(
                {
                    "global_negative_queries": min(
                        offset + len(batch), len(searchable_queries)
                    ),
                    "total": len(searchable_queries),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return rankings


async def _load_history_metadata(history_ids: list[int]) -> dict[int, dict]:
    from sqlalchemy import select

    from csrcqsf.infra.db.main_db import SessionLocal
    from csrcqsf.models.orm.item_inquiry_history import ItemInquiryHistory

    metadata: dict[int, dict] = {}
    async with SessionLocal() as session:
        for offset in range(0, len(history_ids), 1000):
            result = await session.execute(
                select(
                    ItemInquiryHistory.id,
                    ItemInquiryHistory.inquiry_num,
                    ItemInquiryHistory.vehicle_batch,
                    ItemInquiryHistory.vehicle,
                    ItemInquiryHistory.inquiry_time,
                ).where(ItemInquiryHistory.id.in_(history_ids[offset : offset + 1000]))
            )
            for row in result.all():
                metadata[int(row.id)] = dict(row._mapping)
    return metadata


def _load_records_and_vectors() -> tuple[list[InquiryRecord], dict[int, np.ndarray], str]:
    from dotenv import load_dotenv
    from pymilvus import MilvusClient

    load_dotenv(PROJECT_ROOT / ".env", override=True)
    client = MilvusClient(
        uri=f"http://{os.getenv('MILVUS_HOST', 'localhost')}:{os.getenv('MILVUS_PORT', '19530')}"
    )
    collection_name = os.getenv(
        "INQUIRY_TEXT_COLLECTION_ALIAS", "PARTS_INQUIRY_BGE_M3_CURRENT"
    )
    index_rows = _load_index_rows(client, collection_name)
    history_ids = [int(row["history_id"]) for row in index_rows]
    metadata = asyncio.run(_load_history_metadata(history_ids))

    records: list[InquiryRecord] = []
    vectors: dict[int, np.ndarray] = {}
    for row in index_rows:
        history_id = int(row["history_id"])
        source = metadata.get(history_id)
        if source is None or source["inquiry_time"] is None:
            continue
        vehicle = normalize_key_text(source["vehicle_batch"] or source["vehicle"])
        item_code = normalize_key_text(row["item_code"])
        description = normalize_display_text(row["description"])
        if not vehicle or not item_code or not description:
            continue
        records.append(
            InquiryRecord(
                history_id=history_id,
                inquiry_num=normalize_display_text(source["inquiry_num"]),
                vehicle=vehicle,
                item_code=item_code,
                description=description,
                inquiry_time=source["inquiry_time"],
            )
        )
        vectors[history_id] = np.asarray(row["text_vector"], dtype=np.float32)
    return records, vectors, collection_name


def build_dataset(args: argparse.Namespace) -> dict:
    cutoff = datetime.fromisoformat(args.validation_cutoff)
    records, vectors, collection_name = _load_records_and_vectors()
    training_records = [record for record in records if record.inquiry_time < cutoff]
    if args.negative_strategy == "mixed-global":
        clean_training_records = _clean_supervised_records(
            training_records, global_ambiguity=True
        )
        mixed_queries, _positive_pool = _select_query_records(
            clean_training_records, args.max_queries_per_code
        )
        global_rankings = _mine_global_rankings_from_milvus(
            mixed_queries,
            clean_training_records,
            vectors,
            collection_name,
            search_limit=args.global_search_limit,
        )
        train_examples, train_metadata = build_mixed_training_examples(
            training_records,
            vectors,
            global_rankings=global_rankings,
            max_queries_per_code=args.max_queries_per_code,
            positive_count=args.positive_count,
            same_vehicle_hard_count=args.same_vehicle_hard_count,
            cross_vehicle_hard_count=args.cross_vehicle_hard_count,
            lexical_hard_count=args.lexical_hard_count,
            random_negative_count=args.global_random_negative_count,
            seed=args.seed,
        )
    else:
        train_examples, train_metadata = build_training_examples(
            training_records,
            vectors,
            max_queries_per_code=args.max_queries_per_code,
            positive_count=args.positive_count,
            hard_negative_count=args.hard_negative_count,
            random_negative_count=args.random_negative_count,
            seed=args.seed,
        )
    train_query_pairs = {
        (normalize_key_text(row["query"]), metadata["item_code"])
        for row, metadata in zip(train_examples, train_metadata)
    }
    validation_queries = build_validation_queries(
        records,
        cutoff,
        excluded_query_targets=train_query_pairs,
        global_ambiguity=args.negative_strategy == "mixed-global",
    )
    validation_corpus = _corpus_rows(training_records)
    test_queries = _external_test_queries(args.external_test_source)
    test_corpus = _corpus_rows(records)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "train": args.output_dir / "bge_finetune_train.jsonl",
        "train_metadata": args.output_dir / "bge_finetune_train_metadata.jsonl",
        "validation_queries": args.output_dir
        / "bge_finetune_validation_queries.jsonl",
        "validation_corpus": args.output_dir
        / "bge_finetune_validation_corpus.jsonl",
        "test_queries": args.output_dir / "bge_finetune_test_queries.jsonl",
        "test_corpus": args.output_dir / "bge_finetune_test_corpus.jsonl",
    }
    _write_jsonl(outputs["train"], train_examples)
    _write_jsonl(outputs["train_metadata"], train_metadata)
    _write_jsonl(outputs["validation_queries"], validation_queries)
    _write_jsonl(outputs["validation_corpus"], validation_corpus)
    _write_jsonl(outputs["test_queries"], test_queries)
    _write_jsonl(outputs["test_corpus"], test_corpus)

    validation_pairs = {
        (normalize_key_text(row["query"]), row["target_item_code"])
        for row in validation_queries
    }
    test_pairs = {
        (normalize_key_text(row["query"]), row["target_item_code"])
        for row in test_queries
    }
    ambiguous_count = len(find_ambiguous_vehicle_descriptions(records))
    globally_ambiguous_count = len(find_globally_ambiguous_descriptions(records))
    negative_type_counts = Counter(
        negative_type
        for metadata in train_metadata
        for negative_type in metadata.get("negative_types", [])
    )
    report = {
        "collection_alias": collection_name,
        "validation_cutoff": cutoff.isoformat(),
        "configuration": {
            "negative_strategy": args.negative_strategy,
            "max_queries_per_code": args.max_queries_per_code,
            "positive_count": args.positive_count,
            "hard_negative_count": args.hard_negative_count,
            "random_negative_count": args.random_negative_count,
            "same_vehicle_hard_count": args.same_vehicle_hard_count,
            "cross_vehicle_hard_count": args.cross_vehicle_hard_count,
            "lexical_hard_count": args.lexical_hard_count,
            "global_random_negative_count": args.global_random_negative_count,
            "global_search_limit": args.global_search_limit,
            "seed": args.seed,
            "use_in_batch_negatives": False,
        },
        "counts": {
            "indexed_records_with_vehicle_and_time": len(records),
            "training_period_records": len(training_records),
            "ambiguous_vehicle_description_groups": ambiguous_count,
            "globally_ambiguous_descriptions": globally_ambiguous_count,
            "training_examples": len(train_examples),
            "negative_type_counts": dict(sorted(negative_type_counts.items())),
            "validation_queries": len(validation_queries),
            "validation_corpus_documents": len(validation_corpus),
            "external_test_queries": len(test_queries),
            "external_test_corpus_documents": len(test_corpus),
        },
        "leakage_checks": {
            "train_validation_query_target_overlap": len(
                train_query_pairs & validation_pairs
            ),
            "train_external_test_query_target_overlap": len(
                train_query_pairs & test_pairs
            ),
        },
        "outputs": {name: str(path) for name, path in outputs.items()},
    }
    report_path = args.output_dir / "dataset_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--external-test-source", type=Path, default=DEFAULT_EXTERNAL_TEST)
    parser.add_argument("--validation-cutoff", default="2026-01-15")
    parser.add_argument(
        "--negative-strategy",
        choices=("vehicle", "mixed-global"),
        default="vehicle",
    )
    parser.add_argument("--max-queries-per-code", type=int, default=5)
    parser.add_argument("--positive-count", type=int, default=2)
    parser.add_argument("--hard-negative-count", type=int, default=6)
    parser.add_argument("--random-negative-count", type=int, default=2)
    parser.add_argument("--same-vehicle-hard-count", type=int, default=4)
    parser.add_argument("--cross-vehicle-hard-count", type=int, default=4)
    parser.add_argument("--lexical-hard-count", type=int, default=2)
    parser.add_argument("--global-random-negative-count", type=int, default=2)
    parser.add_argument("--global-search-limit", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260910)
    return parser.parse_args()


if __name__ == "__main__":
    sys.path.insert(0, str(PROJECT_ROOT))
    build_dataset(parse_args())
