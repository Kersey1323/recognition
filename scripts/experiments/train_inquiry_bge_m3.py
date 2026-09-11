#!/usr/bin/env python3
"""使用询码描述正负样本微调 BGE-M3，并执行车型预过滤检索评估。"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModel, AutoTokenizer, get_linear_schedule_with_warmup


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_DIR = PROJECT_ROOT / "tmp/bge_finetune_dataset_20260910"
DEFAULT_MODEL_DIR = Path.home() / "CV/models/bge-m3"
DEFAULT_OUTPUT_DIR = Path.home() / "CV/models/bge-m3-inquiry-v1"
RECALL_KS = (1, 5, 10, 20)


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} 第 {line_number} 行不是有效 JSON") from exc
    return rows


class InquiryContrastiveDataset(Dataset):
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict:
        return self.rows[index]


class GroupCollator:
    def __init__(self, tokenizer, max_length: int):
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __call__(self, examples: list[dict]) -> dict:
        queries: list[str] = []
        documents: list[str] = []
        positive_counts: list[int] = []
        group_sizes: list[int] = []
        for example in examples:
            positives = list(example.get("pos") or [])
            negatives = list(example.get("neg") or [])
            if not positives or not negatives:
                raise ValueError("每条训练样本都必须同时包含正样本和负样本")
            queries.append(str(example["query"]))
            documents.extend([*positives, *negatives])
            positive_counts.append(len(positives))
            group_sizes.append(len(positives) + len(negatives))

        tokenize_kwargs = {
            "padding": True,
            "truncation": True,
            "max_length": self.max_length,
            "return_tensors": "pt",
        }
        return {
            "query_inputs": self.tokenizer(queries, **tokenize_kwargs),
            "document_inputs": self.tokenizer(documents, **tokenize_kwargs),
            "positive_counts": positive_counts,
            "group_sizes": group_sizes,
        }


def normalized_cls_embeddings(model, inputs: dict[str, torch.Tensor]) -> torch.Tensor:
    outputs = model(**inputs)
    return F.normalize(outputs.last_hidden_state[:, 0], p=2, dim=1)


def grouped_contrastive_loss(
    query_embeddings: torch.Tensor,
    document_embeddings: torch.Tensor,
    group_sizes: list[int],
    positive_counts: list[int],
    temperature: float,
) -> torch.Tensor:
    """每条查询只与自身候选组对比，避免其他组的同编码描述成为假负例。"""
    if temperature <= 0:
        raise ValueError("temperature 必须大于 0")
    if not (
        len(group_sizes) == len(positive_counts) == query_embeddings.shape[0]
    ):
        raise ValueError("查询数量与候选组数量不一致")

    losses: list[torch.Tensor] = []
    offset = 0
    for query_index, (group_size, positive_count) in enumerate(
        zip(group_sizes, positive_counts)
    ):
        if positive_count <= 0 or positive_count >= group_size:
            raise ValueError("每个候选组必须至少包含一个正样本和一个负样本")
        group = document_embeddings[offset : offset + group_size]
        scores = (query_embeddings[query_index] @ group.T).float() / temperature
        # 多个真实描述共同贡献正例概率，不强迫同编码描述彼此竞争。
        positive_score = torch.logsumexp(scores[:positive_count], dim=0)
        losses.append(torch.logsumexp(scores, dim=0) - positive_score)
        offset += group_size
    if offset != document_embeddings.shape[0]:
        raise ValueError("候选组大小与文档向量数量不一致")
    return torch.stack(losses).mean()


def move_to_device(inputs: dict[str, torch.Tensor], device: torch.device) -> dict:
    return {name: value.to(device, non_blocking=True) for name, value in inputs.items()}


def encode_texts(
    model,
    tokenizer,
    texts: list[str],
    *,
    device: torch.device,
    batch_size: int,
    max_length: int,
) -> np.ndarray:
    vectors: list[np.ndarray] = []
    model.eval()
    with torch.inference_mode():
        for offset in range(0, len(texts), batch_size):
            inputs = tokenizer(
                texts[offset : offset + batch_size],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            inputs = move_to_device(inputs, device)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                embeddings = normalized_cls_embeddings(model, inputs)
            vectors.append(embeddings.float().cpu().numpy())
    return np.concatenate(vectors, axis=0)


def evaluate_retrieval(
    model,
    tokenizer,
    queries: list[dict],
    corpus: list[dict],
    *,
    device: torch.device,
    batch_size: int,
    max_length: int,
    prefilter_vehicle: bool = True,
) -> dict[str, float | int]:
    started_at = time.perf_counter()
    corpus_vectors = encode_texts(
        model,
        tokenizer,
        [str(row["description"]) for row in corpus],
        device=device,
        batch_size=batch_size,
        max_length=max_length,
    )
    query_vectors = encode_texts(
        model,
        tokenizer,
        [str(row["query"]) for row in queries],
        device=device,
        batch_size=batch_size,
        max_length=max_length,
    )

    corpus_indexes_by_vehicle: dict[str, list[int]] = defaultdict(list)
    if prefilter_vehicle:
        for index, row in enumerate(corpus):
            corpus_indexes_by_vehicle[str(row["vehicle"])].append(index)
    all_indexes = list(range(len(corpus)))

    hits = {k: 0 for k in RECALL_KS}
    evaluated = 0
    for query, query_vector in zip(queries, query_vectors):
        indexes = (
            corpus_indexes_by_vehicle.get(str(query["vehicle"]), [])
            if prefilter_vehicle
            else all_indexes
        )
        if not indexes:
            continue
        candidate_vectors = corpus_vectors[indexes]
        scores = candidate_vectors @ query_vector
        ranking = np.argsort(-scores, kind="stable")
        # 线上接口会按配件聚合历史描述，只保留每个编码的最高分文档。
        ranked_codes: list[str] = []
        seen_codes: set[str] = set()
        for rank in ranking:
            item_code = str(corpus[indexes[int(rank)]]["item_code"])
            if item_code in seen_codes:
                continue
            seen_codes.add(item_code)
            ranked_codes.append(item_code)
            if len(ranked_codes) >= max(RECALL_KS):
                break
        target = str(query["target_item_code"])
        evaluated += 1
        for k in RECALL_KS:
            if target in ranked_codes[:k]:
                hits[k] += 1

    if evaluated != len(queries):
        raise RuntimeError(
            f"仅评估了 {evaluated}/{len(queries)} 条查询，存在没有候选语料的车型"
        )
    return {
        "queries": evaluated,
        "prefilter_vehicle": prefilter_vehicle,
        **{f"recall_at_{k}": hits[k] / evaluated for k in RECALL_KS},
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
    }


def save_checkpoint(
    path: Path,
    *,
    model,
    tokenizer,
    optimizer,
    scheduler,
    epoch: int,
    global_step: int,
    best_recall_at_5: float,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(path, safe_serialization=True)
    tokenizer.save_pretrained(path)
    torch.save(
        {
            "epoch": epoch,
            "global_step": global_step,
            "best_recall_at_5": best_recall_at_5,
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
        },
        path / "training_state.pt",
    )


def save_deployable_model(path: Path, model, tokenizer) -> None:
    path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(path, safe_serialization=True)
    tokenizer.save_pretrained(path)


def write_metrics(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--evaluation-batch-size", type=int, default=128)
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--warmup-ratio", type=float, default=0.1)
    parser.add_argument("--temperature", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--logging-steps", type=int, default=20)
    parser.add_argument("--max-steps", type=int, default=0)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--overwrite-output-dir", action="store_true")
    parser.add_argument("--skip-evaluation", action="store_true")
    parser.add_argument(
        "--validation-retrieval-scope",
        choices=("vehicle", "global"),
        default="vehicle",
        help="验证时按车型过滤候选，或直接在全库候选中检索",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    for name in (
        "epochs",
        "batch_size",
        "gradient_accumulation_steps",
        "evaluation_batch_size",
        "max_length",
        "logging_steps",
    ):
        if getattr(args, name) <= 0:
            raise ValueError(f"{name} 必须大于 0")
    if args.learning_rate <= 0 or not 0 <= args.warmup_ratio < 1:
        raise ValueError("learning_rate 必须大于 0，warmup_ratio 必须位于 [0, 1)")
    if args.temperature <= 0:
        raise ValueError("temperature 必须大于 0")


def main() -> None:
    args = parse_args()
    validate_args(args)
    if not torch.cuda.is_available():
        raise RuntimeError("BGE-M3 全参数微调需要可用的 CUDA GPU")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        if not args.resume_from and not args.overwrite_output_dir:
            raise FileExistsError(
                f"输出目录非空: {args.output_dir}；请更换目录或显式使用 --overwrite-output-dir"
            )
        if args.overwrite_output_dir and not args.resume_from:
            shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.set_float32_matmul_precision("high")
    device = torch.device("cuda")

    train_rows = load_jsonl(args.dataset_dir / "bge_finetune_train.jsonl")
    validation_queries = load_jsonl(
        args.dataset_dir / "bge_finetune_validation_queries.jsonl"
    )
    validation_corpus = load_jsonl(
        args.dataset_dir / "bge_finetune_validation_corpus.jsonl"
    )
    if not train_rows:
        raise ValueError("训练集为空")

    model_source = args.resume_from or args.model_dir
    tokenizer = AutoTokenizer.from_pretrained(model_source)
    model = AutoModel.from_pretrained(model_source)
    model.gradient_checkpointing_enable()
    model.config.use_cache = False
    model.to(device)

    dataset = InquiryContrastiveDataset(train_rows)
    generator = torch.Generator().manual_seed(args.seed)
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=GroupCollator(tokenizer, args.max_length),
        generator=generator,
        pin_memory=True,
    )
    optimizer_steps_per_epoch = math.ceil(
        len(loader) / args.gradient_accumulation_steps
    )
    planned_steps = optimizer_steps_per_epoch * args.epochs
    total_steps = min(planned_steps, args.max_steps) if args.max_steps else planned_steps
    warmup_steps = int(total_steps * args.warmup_ratio)
    try:
        optimizer = AdamW(
            model.parameters(),
            lr=args.learning_rate,
            weight_decay=args.weight_decay,
            fused=True,
        )
    except TypeError:
        optimizer = AdamW(
            model.parameters(),
            lr=args.learning_rate,
            weight_decay=args.weight_decay,
        )
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=warmup_steps,
        num_training_steps=total_steps,
    )

    start_epoch = 1
    global_step = 0
    best_recall_at_5 = -1.0
    history: list[dict] = []
    if args.resume_from:
        state_path = args.resume_from / "training_state.pt"
        state = torch.load(state_path, map_location="cpu", weights_only=False)
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        start_epoch = int(state["epoch"]) + 1
        global_step = int(state["global_step"])
        best_recall_at_5 = float(state["best_recall_at_5"])

    metrics_payload = {
        "configuration": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "dataset": {
            "training_examples": len(train_rows),
            "validation_queries": len(validation_queries),
            "validation_corpus_documents": len(validation_corpus),
        },
        "device": torch.cuda.get_device_name(device),
        "optimizer_steps_per_epoch": optimizer_steps_per_epoch,
        "planned_optimizer_steps": total_steps,
        "history": history,
    }
    metrics_path = args.output_dir / "training_metrics.json"
    validation_prefilter_vehicle = args.validation_retrieval_scope == "vehicle"

    if not args.skip_evaluation and not args.resume_from:
        baseline = evaluate_retrieval(
            model,
            tokenizer,
            validation_queries,
            validation_corpus,
            device=device,
            batch_size=args.evaluation_batch_size,
            max_length=args.max_length,
            prefilter_vehicle=validation_prefilter_vehicle,
        )
        history.append({"stage": "baseline", **baseline})
        best_recall_at_5 = float(baseline["recall_at_5"])
        save_deployable_model(args.output_dir / "best", model, tokenizer)
        write_metrics(metrics_path, metrics_payload)
        print(json.dumps(history[-1], ensure_ascii=False), flush=True)

    stop_training = global_step >= total_steps
    for epoch in range(start_epoch, args.epochs + 1):
        if stop_training:
            break
        model.train()
        optimizer.zero_grad(set_to_none=True)
        accumulated_loss = 0.0
        batches_since_step = 0
        epoch_started_at = time.perf_counter()
        final_window_size = len(loader) % args.gradient_accumulation_steps
        final_window_size = final_window_size or args.gradient_accumulation_steps
        for batch_index, batch in enumerate(loader, start=1):
            query_inputs = move_to_device(batch["query_inputs"], device)
            document_inputs = move_to_device(batch["document_inputs"], device)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                query_embeddings = normalized_cls_embeddings(model, query_inputs)
                document_embeddings = normalized_cls_embeddings(model, document_inputs)
                loss = grouped_contrastive_loss(
                    query_embeddings,
                    document_embeddings,
                    batch["group_sizes"],
                    batch["positive_counts"],
                    args.temperature,
                )
            accumulation_divisor = (
                final_window_size
                if batch_index > len(loader) - final_window_size
                else args.gradient_accumulation_steps
            )
            (loss / accumulation_divisor).backward()
            accumulated_loss += float(loss.detach())
            batches_since_step += 1

            is_accumulation_boundary = (
                batch_index % args.gradient_accumulation_steps == 0
                or batch_index == len(loader)
            )
            if not is_accumulation_boundary:
                continue
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            global_step += 1
            if global_step % args.logging_steps == 0 or global_step == 1:
                print(
                    json.dumps(
                        {
                            "epoch": epoch,
                            "global_step": global_step,
                            "loss": round(accumulated_loss / batches_since_step, 6),
                            "learning_rate": scheduler.get_last_lr()[0],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            accumulated_loss = 0.0
            batches_since_step = 0
            if global_step >= total_steps:
                stop_training = True
                break

        epoch_metrics: dict = {
            "stage": "epoch",
            "epoch": epoch,
            "global_step": global_step,
            "training_elapsed_seconds": round(time.perf_counter() - epoch_started_at, 3),
        }
        if not args.skip_evaluation:
            epoch_metrics.update(
                evaluate_retrieval(
                    model,
                    tokenizer,
                    validation_queries,
                    validation_corpus,
                    device=device,
                    batch_size=args.evaluation_batch_size,
                    max_length=args.max_length,
                    prefilter_vehicle=validation_prefilter_vehicle,
                )
            )
        history.append(epoch_metrics)
        current_recall_at_5 = float(epoch_metrics.get("recall_at_5", -1.0))
        if current_recall_at_5 > best_recall_at_5:
            best_recall_at_5 = current_recall_at_5
            save_deployable_model(args.output_dir / "best", model, tokenizer)
        checkpoint_dir = args.output_dir / f"checkpoint-epoch-{epoch:02d}"
        save_checkpoint(
            checkpoint_dir,
            model=model,
            tokenizer=tokenizer,
            optimizer=optimizer,
            scheduler=scheduler,
            epoch=epoch,
            global_step=global_step,
            best_recall_at_5=best_recall_at_5,
        )
        metrics_payload["best_recall_at_5"] = best_recall_at_5
        write_metrics(metrics_path, metrics_payload)
        print(json.dumps(epoch_metrics, ensure_ascii=False), flush=True)

    save_deployable_model(args.output_dir / "final", model, tokenizer)
    metrics_payload["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    metrics_payload["best_recall_at_5"] = best_recall_at_5
    write_metrics(metrics_path, metrics_payload)
    print(f"训练完成，模型输出目录: {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
