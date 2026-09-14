#!/usr/bin/env python3
"""比较询码历史车型过滤与物料车型关联过滤的 BGE 配件召回率。"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = PROJECT_ROOT / "temp/bge_tmp/bge_sparse_hybrid_corpus_20260910.jsonl"
DEFAULT_QUERIES = PROJECT_ROOT / "temp/bge_tmp/bge_sparse_hybrid_queries_20260910.jsonl"
DEFAULT_VECTORS = PROJECT_ROOT / "temp/bge_tmp/bge_sparse_hybrid_snapshot_20260910.npz"
DEFAULT_REPORT = PROJECT_ROOT / "temp/bge_tmp/bge_vehicle_filter_comparison_20260914.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--vectors", type=Path, default=DEFAULT_VECTORS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--document-limit", type=int, default=200)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    return parser.parse_args()


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().upper()


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


async def load_item_relation_codes(vehicles: set[str]) -> dict[str, set[str]]:
    """按生产接口的查询路径获取车型关联且已进入本地主库的物料编码。"""
    from sqlalchemy import select

    from csrcqsf.infra.db.main_db import SessionLocal, engine
    from csrcqsf.infra.db.mdp_db import sgo_engine, sgo_sessionLocal
    from csrcqsf.models.orm.item import Items
    from csrcqsf.modules.railway_parts.repositories.contextual_search_repository import (
        ContextualSearchRepository,
    )

    source_codes_by_vehicle: dict[str, set[str]] = {}
    try:
        async with sgo_sessionLocal() as session:
            for vehicle in sorted(vehicles):
                source_codes_by_vehicle[vehicle] = {
                    normalize(code)
                    for code in await ContextualSearchRepository.list_vehicle_item_codes(
                        session,
                        vehicle,
                    )
                    if normalize(code)
                }

        all_source_codes = sorted(set().union(*source_codes_by_vehicle.values()))
        local_codes: set[str] = set()
        async with SessionLocal() as session:
            for offset in range(0, len(all_source_codes), 1000):
                batch = all_source_codes[offset : offset + 1000]
                rows = await session.execute(
                    select(Items.item_code).where(Items.item_code.in_(batch))
                )
                local_codes.update(
                    normalize(code)
                    for (code,) in rows.all()
                    if normalize(code)
                )
        return {
            vehicle: codes & local_codes
            for vehicle, codes in source_codes_by_vehicle.items()
        }
    finally:
        await sgo_engine.dispose()
        await engine.dispose()


def rank_items(
    scores: np.ndarray,
    candidate_indices: np.ndarray,
    corpus_codes: np.ndarray,
    *,
    document_limit: int,
) -> list[str]:
    if candidate_indices.size == 0:
        return []
    candidate_scores = scores[candidate_indices]
    limit = min(document_limit, candidate_indices.size)
    if limit < candidate_indices.size:
        selected = np.argpartition(candidate_scores, -limit)[-limit:]
        candidate_indices = candidate_indices[selected]
        candidate_scores = candidate_scores[selected]
    ordered = np.lexsort((corpus_codes[candidate_indices], -candidate_scores))

    # 与线上服务一致：同一配件的多条询码描述只保留最高相似度结果。
    return list(dict.fromkeys(corpus_codes[candidate_indices[ordered]].tolist()))


def rank_of(ranking: list[str], target: str) -> int | None:
    try:
        return ranking.index(target) + 1
    except ValueError:
        return None


def summarize(ranks: list[int | None]) -> dict[str, float | int]:
    total = len(ranks)
    result: dict[str, float | int] = {"queries": total}
    for cutoff in (1, 5, 10, 20, 50):
        result[f"recall_at_{cutoff}"] = (
            sum(rank is not None and rank <= cutoff for rank in ranks) / total
            if total
            else 0.0
        )
    result["mrr_at_10"] = (
        sum(1.0 / rank for rank in ranks if rank is not None and rank <= 10) / total
        if total
        else 0.0
    )
    return result


def percentile(values: list[int], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q)) if values else 0.0


def evaluate(args: argparse.Namespace) -> dict:
    corpus = load_jsonl(args.corpus)
    queries = load_jsonl(args.queries)
    snapshot = np.load(args.vectors)
    corpus_vectors = np.asarray(snapshot["corpus_vectors"], dtype=np.float32)
    query_vectors = np.asarray(snapshot["query_vectors"], dtype=np.float32)
    if len(corpus) != len(corpus_vectors) or len(queries) != len(query_vectors):
        raise ValueError("语料、查询元数据与向量快照数量不一致")

    corpus_codes = np.asarray([normalize(row["item_code"]) for row in corpus], dtype=object)
    corpus_vehicles = np.asarray([normalize(row["vehicle"]) for row in corpus], dtype=object)
    query_vehicles = {normalize(row["vehicle"]) for row in queries}
    relation_codes = asyncio.run(load_item_relation_codes(query_vehicles))

    history_indices = {
        vehicle: np.flatnonzero(corpus_vehicles == vehicle)
        for vehicle in query_vehicles
    }
    relation_indices = {
        vehicle: np.flatnonzero(np.isin(corpus_codes, sorted(relation_codes[vehicle])))
        for vehicle in query_vehicles
    }
    union_indices = {
        vehicle: np.union1d(history_indices[vehicle], relation_indices[vehicle])
        for vehicle in query_vehicles
    }
    all_scores = query_vectors @ corpus_vectors.T

    ranks: dict[str, list[int | None]] = defaultdict(list)
    covered_ranks: dict[str, list[int | None]] = defaultdict(list)
    candidate_documents: dict[str, list[int]] = defaultdict(list)
    candidate_items: dict[str, list[int]] = defaultdict(list)
    details = []
    coverage_matrix = defaultdict(int)

    for query, scores in zip(queries, all_scores, strict=True):
        vehicle = normalize(query["vehicle"])
        target = normalize(query["target_item_code"])
        query_result = {}
        coverage = {}

        for name, indices_by_vehicle in (
            ("history_vehicle", history_indices),
            ("item_relation", relation_indices),
            ("history_or_item_relation", union_indices),
        ):
            indices = indices_by_vehicle[vehicle]
            ranking = rank_items(
                scores,
                indices,
                corpus_codes,
                document_limit=args.document_limit,
            )
            rank = rank_of(ranking, target)
            target_covered = bool(np.any(corpus_codes[indices] == target))
            ranks[name].append(rank)
            if target_covered:
                covered_ranks[name].append(rank)
            candidate_documents[name].append(int(indices.size))
            candidate_items[name].append(len(set(corpus_codes[indices].tolist())))
            coverage[name] = target_covered
            query_result[name] = {
                "target_covered": target_covered,
                "target_rank": rank,
                "top_10_item_codes": ranking[:10],
            }

        coverage_key = (
            f"history_{'yes' if coverage['history_vehicle'] else 'no'}__"
            f"relation_{'yes' if coverage['item_relation'] else 'no'}"
        )
        coverage_matrix[coverage_key] += 1
        details.append(
            {
                "inquiry_num": query["inquiry_num"],
                "vehicle": vehicle,
                "query": query["query"],
                "target_item_code": target,
                **query_result,
            }
        )

    methods = {}
    for name in ("history_vehicle", "item_relation", "history_or_item_relation"):
        covered = len(covered_ranks[name])
        methods[name] = {
            "target_candidate_coverage": {
                "covered": covered,
                "total": len(queries),
                "rate": covered / len(queries) if queries else 0.0,
            },
            "overall_metrics": summarize(ranks[name]),
            "metrics_when_target_covered": summarize(covered_ranks[name]),
            "candidate_size": {
                "documents_mean": float(np.mean(candidate_documents[name])),
                "documents_p50": percentile(candidate_documents[name], 50),
                "documents_p95": percentile(candidate_documents[name], 95),
                "items_mean": float(np.mean(candidate_items[name])),
                "items_p50": percentile(candidate_items[name], 50),
                "items_p95": percentile(candidate_items[name], 95),
            },
        }

    return {
        "experiment": "history_vehicle_vs_item_relation_prefilter",
        "query_snapshot": "2026-09-10 strict unseen description-item pairs",
        "item_relation_observed_at": "2026-09-14",
        "retrieval": {
            "model": "BGE-M3 dense vectors from the saved experiment snapshot",
            "document_limit": args.document_limit,
            "aggregation": "maximum-scoring description per item_code",
            "query_count": len(queries),
            "corpus_documents": len(corpus),
        },
        "methods": methods,
        "item_relation_code_counts": {
            vehicle: len(codes)
            for vehicle, codes in sorted(relation_codes.items())
        },
        "coverage_matrix": dict(sorted(coverage_matrix.items())),
        "queries": details,
    }


def main() -> None:
    args = parse_args()
    if args.document_limit <= 0:
        raise ValueError("document-limit 必须大于 0")
    sys.path.insert(0, str(PROJECT_ROOT))
    load_dotenv(args.env_file, override=True)
    report = evaluate(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report["methods"], ensure_ascii=False, indent=2))
    print(json.dumps(report["coverage_matrix"], ensure_ascii=False, indent=2))
    print(f"完整报告: {args.report}")


if __name__ == "__main__":
    main()
