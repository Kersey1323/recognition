#!/usr/bin/env python3
"""离线验证文本嵌入模型对历史询码描述的配件召回效果。"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_DATASET = Path("/tmp/recognition_inquiry_embedding_samples.jsonl")
DEFAULT_REPORT = Path("/tmp/recognition_inquiry_embedding_report.json")
DEFAULT_MODEL = Path.home() / "CV/models/bge-m3"
DEFAULT_THRESHOLDS = (0.45, 0.50, 0.55, 0.60, 0.65)


@dataclass(frozen=True)
class InquirySample:
    record_id: str
    item_id: int
    item_code: str | None
    inquiry_id: str
    description: str
    return_item_name: str | None
    inquiry_time: str | None


def normalize_description(value: str) -> str:
    """统一全半角和空白，避免格式差异被误判为不同询码描述。"""
    normalized = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", " ", normalized).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="从主库导出有效询码样本")
    export_parser.add_argument("--output", type=Path, default=DEFAULT_DATASET)
    export_parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[2] / ".env",
    )

    evaluate_parser = subparsers.add_parser("evaluate", help="执行非自匹配语义召回评测")
    evaluate_parser.add_argument("--input", type=Path, default=DEFAULT_DATASET)
    evaluate_parser.add_argument(
        "--backend",
        choices=("local", "openai-api"),
        default="local",
    )
    evaluate_parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    evaluate_parser.add_argument("--api-base-url", default="http://127.0.0.1:9997/v1")
    evaluate_parser.add_argument("--api-model", default="Qwen3-Embedding-0.6B")
    evaluate_parser.add_argument("--api-batch-size", type=int, default=64)
    evaluate_parser.add_argument("--api-timeout", type=float, default=120.0)
    evaluate_parser.add_argument(
        "--query-instruction",
        default="",
        help="仅添加到查询文本，语料文本保持原样",
    )
    evaluate_parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    evaluate_parser.add_argument("--device", default="cuda")
    evaluate_parser.add_argument("--batch-size", type=int, default=32)
    evaluate_parser.add_argument("--max-seq-length", type=int, default=128)
    evaluate_parser.add_argument("--max-queries", type=int, default=0)
    evaluate_parser.add_argument("--seed", type=int, default=20260828)
    evaluate_parser.add_argument(
        "--labeled-queries",
        type=Path,
        default=None,
        help=(
            "可选 JSONL 标注集，每行包含 query 和 expected_item_ids；"
            "expected_item_ids 为空表示负样本"
        ),
    )
    evaluate_parser.add_argument(
        "--threshold",
        type=float,
        action="append",
        default=[],
        help="候选相似度阈值，可重复传入；评测始终包含 0.55",
    )
    evaluate_parser.add_argument(
        "--mode",
        choices=("temporal-holdout", "leave-one-out"),
        default="temporal-holdout",
        help="时间留出评测，或全样本逐条排除自身后的留一评测",
    )
    evaluate_parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="附加查看一条业务描述的 Top 结果，可重复传入",
    )
    return parser.parse_args()


async def export_dataset(output: Path, env_file: Path) -> None:
    from dotenv import load_dotenv

    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    load_dotenv(env_file, override=True)

    from sqlalchemy import text

    from csrcqsf.infra.db.main_db import engine

    statement = text(
        """
        SELECT id,
               item_id,
               item_code,
               inquiry_id,
               inquiry_item_name,
               return_item_name,
               inquiry_time
        FROM item_inquiry_history
        WHERE item_id IS NOT NULL
          AND inquiry_item_name IS NOT NULL
          AND TRIM(inquiry_item_name) <> ''
        ORDER BY item_id ASC, inquiry_time ASC, id ASC
        """
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    exported = 0
    try:
        async with engine.connect() as connection:
            with output.open("w", encoding="utf-8") as file:
                rows = await connection.stream(statement)
                async for row in rows:
                    mapping = row._mapping
                    description = normalize_description(mapping["inquiry_item_name"])
                    if not description:
                        continue
                    inquiry_time = mapping["inquiry_time"]
                    payload = {
                        "record_id": str(mapping["id"]),
                        "item_id": int(mapping["item_id"]),
                        "item_code": mapping["item_code"],
                        "inquiry_id": str(mapping["inquiry_id"]),
                        "description": description,
                        "return_item_name": mapping["return_item_name"],
                        "inquiry_time": inquiry_time.isoformat() if inquiry_time else None,
                    }
                    file.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    exported += 1
    finally:
        await engine.dispose()

    print(f"已导出 {exported} 条询码样本: {output}")


def load_samples(path: Path) -> list[InquirySample]:
    samples: list[InquirySample] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                payload["description"] = normalize_description(payload["description"])
                samples.append(InquirySample(**payload))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"数据集第 {line_number} 行无效: {exc}") from exc
    return samples


def load_labeled_queries(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                query = normalize_description(str(payload["query"]))
                expected_item_ids = sorted(
                    {int(item_id) for item_id in payload["expected_item_ids"]}
                )
                if not query:
                    raise ValueError("query 不能为空")
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"标注集第 {line_number} 行无效: {exc}") from exc
            cases.append(
                {
                    "query": query,
                    "expected_item_ids": expected_item_ids,
                }
            )
    return cases


def evaluate_labeled_thresholds(
    cases: list[dict[str, Any]],
    *,
    thresholds: list[float] | tuple[float, ...],
) -> list[dict[str, Any]]:
    normalized_thresholds = sorted({0.55, *(float(value) for value in thresholds)})
    if any(value < -1 or value > 1 for value in normalized_thresholds):
        raise ValueError("相似度阈值必须在 [-1, 1] 范围内")

    reports = []
    for threshold in normalized_thresholds:
        true_positive = false_positive = true_negative = false_negative = 0
        for case in cases:
            expected = {int(item_id) for item_id in case["expected_item_ids"]}
            top_result = next(
                (
                    result
                    for result in case.get("top_results", [])
                    if float(result.get("score", 0)) >= threshold
                ),
                None,
            )
            predicted_item_id = (
                int(top_result["item_id"])
                if top_result is not None
                else None
            )
            if expected:
                if predicted_item_id in expected:
                    true_positive += 1
                else:
                    false_negative += 1
                    if predicted_item_id is not None:
                        false_positive += 1
            elif predicted_item_id is None:
                true_negative += 1
            else:
                false_positive += 1

        precision_denominator = true_positive + false_positive
        recall_denominator = true_positive + false_negative
        negative_denominator = false_positive + true_negative
        reports.append(
            {
                "threshold": threshold,
                "true_positive": true_positive,
                "false_positive": false_positive,
                "true_negative": true_negative,
                "false_negative": false_negative,
                "precision": (
                    true_positive / precision_denominator
                    if precision_denominator
                    else 0.0
                ),
                "recall": (
                    true_positive / recall_denominator
                    if recall_denominator
                    else 0.0
                ),
                "false_positive_rate": (
                    false_positive / negative_denominator
                    if negative_denominator
                    else 0.0
                ),
            }
        )
    return reports


def _sample_order(sample: InquirySample) -> tuple[str, str]:
    return sample.inquiry_time or "", sample.record_id


def build_temporal_holdout(
    samples: list[InquirySample],
    *,
    max_queries: int,
    seed: int,
) -> tuple[list[InquirySample], list[InquirySample], dict[str, int]]:
    by_item: dict[int, list[InquirySample]] = defaultdict(list)
    for sample in samples:
        by_item[sample.item_id].append(sample)

    corpus: list[InquirySample] = []
    queries: list[InquirySample] = []
    duplicate_rows = 0
    for item_samples in by_item.values():
        # 同一配件的相同描述只保留时间最早的一条，防止重复录入抬高评测结果。
        unique_descriptions: dict[str, InquirySample] = {}
        for sample in sorted(item_samples, key=_sample_order):
            if sample.description in unique_descriptions:
                duplicate_rows += 1
                continue
            unique_descriptions[sample.description] = sample

        unique_samples = sorted(unique_descriptions.values(), key=_sample_order)
        if len(unique_samples) < 2:
            corpus.extend(unique_samples)
            continue

        # 用该配件时间最晚的新描述模拟线上新询码，其余历史描述进入知识库。
        queries.append(unique_samples[-1])
        corpus.extend(unique_samples[:-1])

    if max_queries > 0 and len(queries) > max_queries:
        random.Random(seed).shuffle(queries)
        queries = queries[:max_queries]

    stats = {
        "raw_samples": len(samples),
        "distinct_items": len(by_item),
        "duplicate_same_item_descriptions_removed": duplicate_rows,
        "corpus_samples": len(corpus),
        "corpus_items": len({sample.item_id for sample in corpus}),
        "evaluation_queries": len(queries),
    }
    return corpus, queries, stats


def build_leave_one_out(
    samples: list[InquirySample],
    *,
    max_queries: int,
    seed: int,
) -> tuple[list[InquirySample], list[InquirySample], dict[str, int]]:
    by_item: dict[int, list[InquirySample]] = defaultdict(list)
    for sample in samples:
        by_item[sample.item_id].append(sample)

    corpus: list[InquirySample] = []
    queries: list[InquirySample] = []
    duplicate_rows = 0
    for item_samples in by_item.values():
        unique_descriptions: dict[str, InquirySample] = {}
        for sample in sorted(item_samples, key=_sample_order):
            if sample.description in unique_descriptions:
                duplicate_rows += 1
                continue
            unique_descriptions[sample.description] = sample

        unique_samples = sorted(unique_descriptions.values(), key=_sample_order)
        corpus.extend(unique_samples)
        if len(unique_samples) >= 2:
            queries.extend(unique_samples)

    if max_queries > 0 and len(queries) > max_queries:
        random.Random(seed).shuffle(queries)
        queries = queries[:max_queries]

    stats = {
        "raw_samples": len(samples),
        "distinct_items": len(by_item),
        "duplicate_same_item_descriptions_removed": duplicate_rows,
        "corpus_samples": len(corpus),
        "corpus_items": len({sample.item_id for sample in corpus}),
        "evaluation_queries": len(queries),
    }
    return corpus, queries, stats


def _aggregate_item_hits(
    sample_hits: list[dict[str, Any]],
    corpus: list[InquirySample],
    *,
    excluded_record_id: str | None = None,
) -> list[dict[str, Any]]:
    item_hits: dict[int, dict[str, Any]] = {}
    for hit in sample_hits:
        sample = corpus[int(hit["corpus_id"])]
        if excluded_record_id is not None and sample.record_id == excluded_record_id:
            continue
        score = float(hit["score"])
        previous = item_hits.get(sample.item_id)
        if previous is None or score > previous["score"]:
            item_hits[sample.item_id] = {
                "item_id": sample.item_id,
                "item_code": sample.item_code,
                "return_item_name": sample.return_item_name,
                "matched_description": sample.description,
                "score": score,
            }
    return sorted(item_hits.values(), key=lambda item: item["score"], reverse=True)


def _round_scores(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list):
        return [_round_scores(item) for item in value]
    if isinstance(value, dict):
        return {key: _round_scores(item) for key, item in value.items()}
    return value


def _empty_metrics() -> dict[str, Any]:
    return {
        "query_count": 0,
        "recall_hits": {1: 0, 5: 0, 10: 0},
        "reciprocal_rank_at_10_sum": 0.0,
    }


def _record_rank(metrics: dict[str, Any], rank: int | None) -> None:
    metrics["query_count"] += 1
    for cutoff in metrics["recall_hits"]:
        if rank is not None and rank <= cutoff:
            metrics["recall_hits"][cutoff] += 1
    if rank is not None and rank <= 10:
        metrics["reciprocal_rank_at_10_sum"] += 1.0 / rank


def _finalize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    query_count = metrics["query_count"]
    if query_count == 0:
        return {
            "query_count": 0,
            "recall_at_1": 0.0,
            "recall_at_5": 0.0,
            "recall_at_10": 0.0,
            "mrr_at_10": 0.0,
        }
    return {
        "query_count": query_count,
        "recall_at_1": metrics["recall_hits"][1] / query_count,
        "recall_at_5": metrics["recall_hits"][5] / query_count,
        "recall_at_10": metrics["recall_hits"][10] / query_count,
        "mrr_at_10": metrics["reciprocal_rank_at_10_sum"] / query_count,
    }


def _iter_semantic_search_batches(
    query_embeddings: Any,
    corpus_embeddings: Any,
    *,
    top_k: int,
    query_chunk_size: int = 128,
):
    import torch

    for start in range(0, len(query_embeddings), query_chunk_size):
        query_chunk = query_embeddings[start : start + query_chunk_size]
        scores = query_chunk @ corpus_embeddings.T
        values, indices = torch.topk(scores, k=top_k, dim=1, largest=True, sorted=True)
        values = values.detach().cpu().tolist()
        indices = indices.detach().cpu().tolist()
        yield [
            [
                {"corpus_id": corpus_id, "score": score}
                for corpus_id, score in zip(row_indices, row_values, strict=True)
            ]
            for row_indices, row_values in zip(indices, values, strict=True)
        ]


def _encode_with_openai_api(
    texts: list[str],
    *,
    base_url: str,
    model: str,
    batch_size: int,
    timeout: float,
    device: str,
    query_instruction: str = "",
):
    import numpy as np
    import torch

    endpoint = f"{base_url.rstrip('/')}/embeddings"
    embeddings: np.ndarray | None = None
    total_batches = math.ceil(len(texts) / batch_size)
    for batch_number, start in enumerate(range(0, len(texts), batch_size), start=1):
        batch = texts[start : start + batch_size]
        if query_instruction:
            batch = [
                f"Instruct: {query_instruction}\nQuery: {text}"
                for text in batch
            ]
        request = urllib.request.Request(
            endpoint,
            data=json.dumps({"model": model, "input": batch}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    payload = json.load(response)
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt == 3:
                    raise RuntimeError(
                        f"嵌入接口调用失败: batch={batch_number}/{total_batches}, error={exc}"
                    ) from exc
                time.sleep(attempt)
        else:
            raise RuntimeError(f"嵌入接口调用失败: {last_error}")

        ordered = sorted(payload.get("data", []), key=lambda item: int(item["index"]))
        if len(ordered) != len(batch):
            raise RuntimeError(
                f"嵌入接口返回数量不一致: expected={len(batch)}, actual={len(ordered)}"
            )
        batch_embeddings = np.asarray(
            [item["embedding"] for item in ordered],
            dtype=np.float32,
        )
        if embeddings is None:
            embeddings = np.empty((len(texts), batch_embeddings.shape[1]), dtype=np.float32)
        embeddings[start : start + len(batch)] = batch_embeddings
        if batch_number == 1 or batch_number % 25 == 0 or batch_number == total_batches:
            print(f"API 编码进度: {batch_number}/{total_batches}")

    if embeddings is None:
        raise RuntimeError("没有可编码的文本")
    tensor = torch.from_numpy(embeddings).to(device)
    return torch.nn.functional.normalize(tensor, p=2, dim=1)


def evaluate(args: argparse.Namespace) -> None:
    import torch

    samples = load_samples(args.input)
    labeled_cases = (
        load_labeled_queries(args.labeled_queries)
        if args.labeled_queries is not None
        else []
    )
    if args.mode == "leave-one-out":
        corpus, queries, dataset_stats = build_leave_one_out(
            samples,
            max_queries=args.max_queries,
            seed=args.seed,
        )
    else:
        corpus, queries, dataset_stats = build_temporal_holdout(
            samples,
            max_queries=args.max_queries,
            seed=args.seed,
        )
    if not corpus:
        raise RuntimeError("没有可用于建立语料库的询码描述")
    if not queries:
        raise RuntimeError("没有同一配件的不同历史描述，无法执行非自匹配评测")

    model_load_started = time.perf_counter()
    if args.backend == "local":
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(str(args.model), device=args.device)
        model.max_seq_length = args.max_seq_length
    else:
        model = None
    model_load_seconds = time.perf_counter() - model_load_started

    encode_started = time.perf_counter()
    corpus_texts = [sample.description for sample in corpus]
    query_texts = [sample.description for sample in queries]
    custom_texts = [normalize_description(query) for query in args.query]
    labeled_texts = [case["query"] for case in labeled_cases]
    if model is not None:
        corpus_embeddings = model.encode(
            corpus_texts,
            batch_size=args.batch_size,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        query_embeddings = model.encode(
            query_texts,
            batch_size=args.batch_size,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        custom_embeddings = (
            model.encode(
                custom_texts,
                batch_size=args.batch_size,
                convert_to_tensor=True,
                normalize_embeddings=True,
            )
            if custom_texts
            else None
        )
        labeled_embeddings = (
            model.encode(
                labeled_texts,
                batch_size=args.batch_size,
                convert_to_tensor=True,
                normalize_embeddings=True,
            )
            if labeled_texts
            else None
        )
    else:
        api_options = {
            "base_url": args.api_base_url,
            "model": args.api_model,
            "batch_size": args.api_batch_size,
            "timeout": args.api_timeout,
            "device": args.device,
        }
        corpus_embeddings = _encode_with_openai_api(corpus_texts, **api_options)
        query_embeddings = _encode_with_openai_api(
            query_texts,
            query_instruction=args.query_instruction,
            **api_options,
        )
        custom_embeddings = (
            _encode_with_openai_api(
                custom_texts,
                query_instruction=args.query_instruction,
                **api_options,
            )
            if custom_texts
            else None
        )
        labeled_embeddings = (
            _encode_with_openai_api(
                labeled_texts,
                query_instruction=args.query_instruction,
                **api_options,
            )
            if labeled_texts
            else None
        )
    encode_seconds = time.perf_counter() - encode_started

    search_started = time.perf_counter()
    # 先多取样本再按 item_id 聚合，避免一个配件的多条历史描述挤占结果位。
    sample_top_k = min(len(corpus), 200)

    metrics_by_group = {
        "all": _empty_metrics(),
        "description_unique_across_items": _empty_metrics(),
        "description_conflicts_across_items": _empty_metrics(),
    }
    self_lookup_metrics = _empty_metrics()
    evaluated: list[dict[str, Any]] = []
    corpus_description_items: dict[str, set[int]] = defaultdict(set)
    for sample in corpus:
        corpus_description_items[sample.description].add(sample.item_id)

    query_offset = 0
    for result_batch in _iter_semantic_search_batches(
        query_embeddings,
        corpus_embeddings,
        top_k=sample_top_k,
    ):
        query_batch = queries[query_offset : query_offset + len(result_batch)]
        query_offset += len(result_batch)
        for query, sample_hits in zip(query_batch, result_batch, strict=True):
            if args.mode == "leave-one-out":
                self_rank = next(
                    (
                        index
                        for index, hit in enumerate(sample_hits, start=1)
                        if corpus[int(hit["corpus_id"])].record_id == query.record_id
                    ),
                    None,
                )
                _record_rank(self_lookup_metrics, self_rank)
            excluded_record_id = query.record_id if args.mode == "leave-one-out" else None
            item_hits = _aggregate_item_hits(
                sample_hits,
                corpus,
                excluded_record_id=excluded_record_id,
            )
            rank = next(
                (
                    index
                    for index, hit in enumerate(item_hits, start=1)
                    if hit["item_id"] == query.item_id
                ),
                None,
            )
            has_cross_item_conflict = any(
                item_id != query.item_id
                for item_id in corpus_description_items.get(query.description, set())
            )
            _record_rank(metrics_by_group["all"], rank)
            group = (
                "description_conflicts_across_items"
                if has_cross_item_conflict
                else "description_unique_across_items"
            )
            _record_rank(metrics_by_group[group], rank)
            evaluated.append(
                {
                    "query": asdict(query),
                    "target_rank": rank,
                    "description_conflicts_across_items": has_cross_item_conflict,
                    "top_results": item_hits[:5],
                }
            )
    search_seconds = time.perf_counter() - search_started

    finalized_metrics = {
        group: _finalize_metrics(metrics)
        for group, metrics in metrics_by_group.items()
    }
    summary = {
        "model": str(args.model) if model is not None else args.api_model,
        "backend": args.backend,
        "query_instruction": args.query_instruction or None,
        "evaluation_mode": args.mode,
        "device": args.device,
        "embedding_dimension": int(corpus_embeddings.shape[1]),
        "dataset": dataset_stats,
        "metrics": finalized_metrics,
        "model_load_seconds": model_load_seconds,
        "encode_seconds": encode_seconds,
        "search_seconds": search_seconds,
    }
    if args.mode == "leave-one-out":
        summary["self_lookup_sanity"] = _finalize_metrics(self_lookup_metrics)

    def failure_order(result: dict[str, Any]) -> tuple[bool, float]:
        rank = result["target_rank"]
        return rank is None, float(rank if rank is not None else math.inf)

    hardest = sorted(evaluated, key=failure_order, reverse=True)[:20]
    custom_results = []
    if custom_embeddings is not None:
        custom_sample_results = next(
            _iter_semantic_search_batches(
                custom_embeddings,
                corpus_embeddings,
                top_k=sample_top_k,
            )
        )
        for query_text, hits in zip(args.query, custom_sample_results, strict=True):
            custom_results.append(
                {
                    "query": query_text,
                    "top_results": _aggregate_item_hits(hits, corpus)[:10],
                }
            )

    threshold_evaluation = []
    if labeled_embeddings is not None:
        labeled_sample_results = next(
            _iter_semantic_search_batches(
                labeled_embeddings,
                corpus_embeddings,
                top_k=sample_top_k,
            )
        )
        evaluated_cases = []
        for case, hits in zip(labeled_cases, labeled_sample_results, strict=True):
            evaluated_cases.append(
                {
                    **case,
                    "top_results": _aggregate_item_hits(hits, corpus),
                }
            )
        threshold_evaluation = evaluate_labeled_thresholds(
            evaluated_cases,
            thresholds=args.threshold or DEFAULT_THRESHOLDS,
        )

    report = _round_scores(
        {
            "summary": summary,
            "hardest_queries": hardest,
            "custom_queries": custom_results,
            "threshold_evaluation": threshold_evaluation,
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(_round_scores(summary), ensure_ascii=False, indent=2))
    print(f"完整报告: {args.report}")
    if torch.cuda.is_available():
        print(f"GPU 峰值显存: {torch.cuda.max_memory_allocated() / 1024**3:.2f} GiB")


def main() -> None:
    args = parse_args()
    if args.command == "export":
        asyncio.run(export_dataset(args.output, args.env_file))
    else:
        evaluate(args)


if __name__ == "__main__":
    main()
