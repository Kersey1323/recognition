"""带业务条件的图片/描述检索与最近两次结果窗口。"""

from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
import io
import re
from typing import Any

from PIL import Image

from csrcqsf.models.orm.search_history import (
    SearchParameters,
    SearchResults,
    SearchSnapshot,
)
from csrcqsf.modules.railway_parts.schemas.search import SearchItem
from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
    get_inquiry_semantic_index_service,
)


FINAL_SCORE_WEIGHTS = {
    "image_score": 0.50,
    "name_score": 0.30,
    "history_context_score": 0.15,
    "exact_match_score": 0.05,
}


class ContextualSearchBusinessError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _runtime():
    from csrcqsf.modules.railway_parts.services import parts_service

    return parts_service._runtime_context()


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value)).casefold()


def _text_similarity(left: Any, right: Any) -> float:
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def _bounded_vector_score(value: float | int | None) -> float:
    if value is None:
        return 0.0
    score = float(value)
    if score < 0:
        score = (score + 1.0) / 2.0
    return max(0.0, min(1.0, score))


def _candidate_names(item_name: str | None, history_rows: list[Any]) -> list[str]:
    names = [item_name]
    for row in history_rows:
        names.extend(
            [
                getattr(row, "inquiry_item_name", None),
                getattr(row, "return_item_name", None),
            ]
        )
    return [str(name) for name in names if _normalize_text(name)]


def _history_frequency(
    history_rows: list[Any],
    parameters: SearchParameters,
) -> int:
    count = 0
    for row in history_rows:
        vehicle_matches = not parameters.vehicle_batch or (
            _normalize_text(getattr(row, "vehicle_batch", None))
            == _normalize_text(parameters.vehicle_batch)
        )
        names = _candidate_names(None, [row])
        name_matches = not parameters.item_description or any(
            _text_similarity(parameters.item_description, name) >= 0.8 for name in names
        )
        if vehicle_matches and name_matches:
            count += 1
    return count


def _history_context_base(
    history_rows: list[Any],
    parameters: SearchParameters,
) -> tuple[dict[str, float], int]:
    field_specs = (
        ("subordinate_component", parameters.subordinate_component, 0.40),
        ("car_num", parameters.car_num, 0.25),
        ("train_no", parameters.train_no, 0.20),
    )
    component_scores: dict[str, float] = {}
    for field_name, query_value, _ in field_specs:
        if not _normalize_text(query_value):
            continue
        component_scores[field_name] = max(
            (
                _text_similarity(query_value, getattr(row, field_name, None))
                for row in history_rows
            ),
            default=0.0,
        )
    return component_scores, _history_frequency(history_rows, parameters)


def rank_contextual_candidates(
    *,
    item_ids: list[int],
    image_scores: dict[int, float],
    text_scores: dict[int, float],
    item_names: dict[int, str],
    histories_by_item: dict[int, list[Any]],
    parameters: SearchParameters,
) -> list[dict[str, float | int]]:
    """按图片、名称和询码上下文融合候选；无历史数据的候选仍保留。"""

    context_parts: dict[int, dict[str, float]] = {}
    history_frequencies: dict[int, int] = {}
    for item_id in item_ids:
        parts, frequency = _history_context_base(
            histories_by_item.get(item_id, []), parameters
        )
        context_parts[item_id] = parts
        history_frequencies[item_id] = frequency

    max_frequency = max(history_frequencies.values(), default=0)
    has_context_query = any(
        _normalize_text(value)
        for value in (
            parameters.subordinate_component,
            parameters.car_num,
            parameters.train_no,
        )
    )
    has_name_query = bool(_normalize_text(parameters.item_description))

    ranked: list[dict[str, float | int]] = []
    for item_id in dict.fromkeys(int(value) for value in item_ids):
        history_rows = histories_by_item.get(item_id, [])
        names = _candidate_names(item_names.get(item_id), history_rows)
        lexical_score = max(
            (_text_similarity(parameters.item_description, name) for name in names),
            default=0.0,
        )
        vector_name_score = _bounded_vector_score(text_scores.get(item_id))
        if item_id in text_scores and names:
            name_score = 0.60 * vector_name_score + 0.40 * lexical_score
        elif item_id in text_scores:
            name_score = vector_name_score
        else:
            name_score = lexical_score

        normalized_query_name = _normalize_text(parameters.item_description)
        exact_match_score = float(
            bool(normalized_query_name)
            and any(_normalize_text(name) == normalized_query_name for name in names)
        )

        inner_components: list[tuple[float, float]] = []
        component_weights = {
            "subordinate_component": 0.40,
            "car_num": 0.25,
            "train_no": 0.20,
        }
        for field_name, component_score in context_parts[item_id].items():
            inner_components.append((component_weights[field_name], component_score))
        if max_frequency and (parameters.vehicle_batch or parameters.item_description):
            inner_components.append(
                (0.15, history_frequencies[item_id] / max_frequency)
            )
        inner_weight = sum(weight for weight, _ in inner_components)
        history_context_score = (
            sum(weight * score for weight, score in inner_components) / inner_weight
            if inner_weight
            else 0.0
        )

        scores = {
            "image_score": _bounded_vector_score(image_scores.get(item_id)),
            "name_score": name_score,
            "history_context_score": history_context_score,
            "exact_match_score": exact_match_score,
        }
        active_layers = ["image_score"] if image_scores else []
        if has_name_query:
            active_layers.extend(["name_score", "exact_match_score"])
        if has_context_query:
            active_layers.append("history_context_score")
        active_weight = sum(FINAL_SCORE_WEIGHTS[layer] for layer in active_layers)
        final_score = (
            sum(FINAL_SCORE_WEIGHTS[layer] * scores[layer] for layer in active_layers)
            / active_weight
            if active_weight
            else 0.0
        )
        ranked.append(
            {
                "item_id": item_id,
                **{key: round(value, 6) for key, value in scores.items()},
                "final_score": round(final_score, 6),
            }
        )

    ranked.sort(
        key=lambda row: (
            -float(row["final_score"]),
            -float(row["image_score"]),
            int(row["item_id"]),
        )
    )
    return ranked


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _history_query_images(history) -> list[str]:
    query_images = [
        str(path)
        for path in list(getattr(history, "query_images_json", None) or [])
        if path
    ]
    if query_images:
        return query_images
    query_image = getattr(history, "query_image", None)
    return [str(query_image)] if query_image else []


def _safe_query_filename(filename: str | None) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", (filename or "query.jpg").strip())
    return safe_name or "query.jpg"


async def _prepare_uploaded_query_images(
    history_id: int,
    files: list,
    *,
    runtime=None,
) -> tuple[list[str], list[Image.Image]]:
    runtime = runtime or _runtime()
    prepared: list[tuple[str, bytes, Image.Image]] = []
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert("RGB")
            image.load()
        except Exception as exc:
            raise ContextualSearchBusinessError(422, "上传文件不是有效图片") from exc
        prepared.append((_safe_query_filename(getattr(file, "filename", None)), contents, image))

    ensure_minio_bucket, minio_instance, _ = runtime._get_minio_helpers()
    ensure_minio_bucket(runtime.minio_search_history_bucket)
    uploaded_paths: list[str] = []
    try:
        for filename, contents, _ in prepared:
            unique_id = runtime.get_id()
            date_prefix = runtime.datetime.now().strftime("%Y%m%d")
            object_name = (
                f"query-images/{date_prefix}/{history_id}/{unique_id}_{filename}"
            )
            await runtime.run_sync(
                minio_instance.client.put_object,
                runtime.minio_search_history_bucket,
                object_name,
                io.BytesIO(contents),
                len(contents),
            )
            uploaded_paths.append(
                f"{runtime.minio_search_history_bucket}/{object_name}"
            )
    except Exception:
        await _delete_query_images(uploaded_paths, runtime=runtime)
        raise
    return uploaded_paths, [image for _, _, image in prepared]


async def _load_query_images(
    query_paths: list[str],
    *,
    runtime=None,
) -> list[Image.Image]:
    runtime = runtime or _runtime()
    _, minio_instance, parse_minio_path = runtime._get_minio_helpers()
    loaded_images: list[Image.Image] = []
    for query_path in query_paths:
        bucket, object_name = parse_minio_path(
            query_path,
            default_bucket=runtime.minio_search_history_bucket,
        )

        def _download() -> bytes:
            response = minio_instance.client.get_object(bucket, object_name)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        contents = await runtime.run_sync(_download)
        image = Image.open(io.BytesIO(contents)).convert("RGB")
        image.load()
        loaded_images.append(image)
    return loaded_images


async def _delete_query_images(
    query_paths: list[str],
    *,
    runtime=None,
) -> None:
    runtime = runtime or _runtime()
    if not query_paths:
        return
    _, minio_instance, parse_minio_path = runtime._get_minio_helpers()
    for query_path in dict.fromkeys(query_paths):
        try:
            bucket, object_name = parse_minio_path(
                query_path,
                default_bucket=runtime.minio_search_history_bucket,
            )
            await runtime.run_sync(
                minio_instance.client.remove_object,
                bucket,
                object_name,
            )
        except Exception as exc:
            runtime.logger.warning(
                "清理条件检索窗口外查询图失败: path=%s, error=%s",
                query_path,
                exc,
            )


def _stored_results(search_items: list[SearchItem], *, runtime=None) -> SearchResults:
    runtime = runtime or _runtime()
    return runtime.SearchResults(
        items=[
            runtime.SearchResultItem(
                item_id=str(item.item_id),
                item_code=item.item_code,
                item_name=item.item_name,
                similar=item.rate,
                image_url=item.image_url,
                matched_images=[
                    runtime.MatchedImage(
                        image_url=matched.image_url,
                        rate=matched.rate,
                        matched_query_indexes=list(matched.matched_query_indexes or []),
                    )
                    for matched in item.matched_images
                ],
                matched_description=getattr(item, "matched_description", None),
                matched_inquiry_id=getattr(item, "matched_inquiry_id", None),
            )
            for item in search_items
        ]
    )


def _previous_snapshot(history, *, runtime=None) -> SearchSnapshot:
    runtime = runtime or _runtime()
    return runtime.SearchSnapshot(
        query_images=_history_query_images(history),
        parameters=getattr(history, "search_parameter", None)
        or runtime.SearchParameters(search_mode="siglip"),
        results=getattr(history, "search_results", None)
        or runtime.SearchResults(items=[]),
        searched_at=(
            getattr(history, "time_updated", None)
            or getattr(history, "time_created", None)
            or runtime.datetime.now()
        ),
    )


def _snapshot_response(snapshot: SearchSnapshot, *, runtime=None):
    runtime = runtime or _runtime()
    return runtime.ContextualSearchSnapshotRes(
        query_images=list(snapshot.query_images),
        parameters=snapshot.parameters,
        searched_at=snapshot.searched_at.strftime("%Y-%m-%d %H:%M:%S"),
        data=[
            runtime.SearchItem(
                item_id=str(item.item_id),
                item_code=item.item_code,
                item_name=item.item_name or "",
                image_url=item.image_url or "",
                rate=float(item.similar),
                matched_images=[
                    runtime.MatchedImage(
                        image_url=matched.image_url,
                        rate=matched.rate,
                        matched_query_indexes=list(matched.matched_query_indexes or []),
                    )
                    for matched in item.matched_images
                ],
                matched_description=getattr(item, "matched_description", None),
                matched_inquiry_id=getattr(item, "matched_inquiry_id", None),
            )
            for item in snapshot.results.items
        ],
    )


def _current_response(
    *,
    query_images: list[str],
    parameters: SearchParameters,
    search_items: list[SearchItem],
    searched_at: datetime,
    runtime=None,
):
    runtime = runtime or _runtime()
    return runtime.ContextualSearchSnapshotRes(
        query_images=query_images,
        parameters=parameters,
        searched_at=searched_at.strftime("%Y-%m-%d %H:%M:%S"),
        data=search_items,
    )


async def _vehicle_candidate_item_ids(
    vehicle_batch: str | None,
    *,
    runtime=None,
) -> list[int] | None:
    runtime = runtime or _runtime()
    if not vehicle_batch:
        return None
    async with runtime.sgo_sessionLocal() as source_session:
        item_codes = await runtime.ContextualSearchRepository.list_vehicle_item_codes(
            source_session, vehicle_batch
        )
    async with runtime.SessionLocal() as session:
        return await runtime.ContextualSearchRepository.list_item_ids_by_codes(
            session, item_codes
        )


async def _item_name_candidate_item_ids(
    item_name: str | None,
    *,
    runtime=None,
) -> list[int] | None:
    runtime = runtime or _runtime()
    if not item_name:
        return None
    async with runtime.SessionLocal() as session:
        item_ids = await runtime.ContextualSearchRepository.list_item_ids_by_exact_name(
            session,
            item_name,
        )
    # 配件名称仅在主库存在完全相等项时强过滤；输入可能有错字，无精确项则保留原召回。
    return item_ids or None


async def _execute_contextual_search(
    cls,
    *,
    query_images: list[Image.Image],
    parameters: SearchParameters,
    runtime=None,
) -> tuple[list[SearchItem], str | None]:
    runtime = runtime or _runtime()
    vehicle_filter = await _vehicle_candidate_item_ids(
        parameters.vehicle_batch, runtime=runtime
    )
    if vehicle_filter == []:
        return [], f"车型 {parameters.vehicle_batch} 下没有可检索配件"

    item_name_filter = await _item_name_candidate_item_ids(
        parameters.item_name,
        runtime=runtime,
    )
    if vehicle_filter is None:
        candidate_filter = item_name_filter
    elif item_name_filter is None:
        candidate_filter = vehicle_filter
    else:
        candidate_filter = sorted(set(vehicle_filter) & set(item_name_filter))
        if not candidate_filter:
            return [], f"车型 {parameters.vehicle_batch} 下没有名称为 {parameters.item_name} 的配件"

    per_query_results: list[list[dict]] = []
    if query_images:
        manager = runtime._get_milvus_manager_v2_cls()()
        for image in query_images:
            per_query_results.append(
                await manager.search_by_image(
                    image=image,
                    top_k=100,
                    mode=parameters.search_mode,
                    coarse_top_k=100,
                    alpha=0.6,
                    item_ids=candidate_filter,
                )
            )

    if not per_query_results:
        image_hits = []
    elif len(per_query_results) == 1:
        image_hits = per_query_results[0]
    else:
        image_hits = cls._fuse_multi_image_search_results(per_query_results)

    text_hits = []
    if parameters.item_description:
        text_hits = await get_inquiry_semantic_index_service().search(
            parameters.item_description,
            top_k=100,
            item_ids=candidate_filter,
        )

    image_scores: dict[int, float] = {}
    text_scores: dict[int, float] = {}
    visual_hits_by_item: dict[int, list[dict]] = {}
    text_hits_by_item: dict[int, list[dict]] = {}
    for hit in image_hits:
        entity = hit.get("entity", {})
        if entity.get("item_id") is None:
            continue
        item_id = int(entity["item_id"])
        score = float(hit.get("best_similarity", hit.get("distance", 0)) or 0)
        image_scores[item_id] = max(score, image_scores.get(item_id, float("-inf")))
        visual_hits_by_item.setdefault(item_id, []).append(hit)
    for hit in text_hits:
        entity = hit.get("entity", {})
        if entity.get("item_id") is None:
            continue
        item_id = int(entity["item_id"])
        score = float(hit.get("distance", 0) or 0)
        text_scores[item_id] = max(score, text_scores.get(item_id, float("-inf")))
        text_hits_by_item.setdefault(item_id, []).append(hit)

    recalled_item_ids = list(dict.fromkeys([*image_scores, *text_scores]))
    if not recalled_item_ids:
        return [], None

    async with runtime.SessionLocal() as session:
        items = await runtime.ContextualSearchRepository.list_items_by_ids(
            session, recalled_item_ids
        )
        history_rows = await runtime.ContextualSearchRepository.list_histories_by_item_ids(
            session, recalled_item_ids
        )
        text_only_item_ids = [
            item_id
            for item_id in recalled_item_ids
            if item_id in text_scores and item_id not in image_scores
        ]
        first_images = (
            await runtime.ContextualSearchRepository.list_first_images_by_item_ids(
                session, text_only_item_ids
            )
            if text_only_item_ids
            else []
        )

    item_map = {int(item.id): item for item in items}
    first_image_by_item = {
        int(image.item_id): image.image_url
        for image in first_images
    }
    histories_by_item: dict[int, list[Any]] = {}
    for row in history_rows:
        if row.item_id is not None:
            histories_by_item.setdefault(int(row.item_id), []).append(row)

    ranked = rank_contextual_candidates(
        item_ids=recalled_item_ids,
        image_scores=image_scores,
        text_scores=text_scores,
        item_names={item_id: item.item_name for item_id, item in item_map.items()},
        histories_by_item=histories_by_item,
        parameters=parameters,
    )

    search_items: list[SearchItem] = []
    for score_row in ranked[:10]:
        item_id = int(score_row["item_id"])
        item = item_map.get(item_id)
        visual_hits = visual_hits_by_item.get(item_id, [])
        visual_hits.sort(
            key=lambda hit: -float(
                hit.get("best_similarity", hit.get("distance", 0)) or 0
            )
        )
        fallback_text_hits = text_hits_by_item.get(item_id, [])
        fallback_text_hits.sort(
            key=lambda hit: -float(hit.get("distance", 0) or 0)
        )
        representative_hit = (
            visual_hits[0]
            if visual_hits
            else (fallback_text_hits[0] if fallback_text_hits else {})
        )
        representative = representative_hit.get("entity", {})
        if item is None and not representative:
            continue
        matched_images = []
        seen_urls = set()
        # 描述召回只参与语义评分；matched_images 仅表达图片与图片的匹配关系。
        for hit in visual_hits:
            entity = hit.get("entity", {})
            image_url = entity.get("image_url", "") or ""
            if not image_url or image_url in seen_urls:
                continue
            seen_urls.add(image_url)
            matched_images.append(
                runtime.MatchedImage(
                    image_url=image_url,
                    rate=float(
                        hit.get("best_similarity", hit.get("distance", 0)) or 0
                    ),
                    matched_query_indexes=list(
                        hit.get("matched_query_indexes", []) or []
                    ),
                )
            )
        best_text_hit = fallback_text_hits[0] if fallback_text_hits else {}
        best_text_entity = best_text_hit.get("entity", {})
        search_items.append(
            runtime.SearchItem(
                item_id=str(item_id),
                item_code=(item.item_code if item else representative.get("item_code", "")),
                item_name=(item.item_name if item else representative.get("item_name", "")),
                image_url=(
                    representative.get("image_url", "")
                    or first_image_by_item.get(item_id, "")
                    or ""
                ),
                rate=float(score_row["final_score"]),
                matched_images=matched_images,
                matched_description=best_text_entity.get("description"),
                matched_inquiry_id=(
                    str(best_text_entity["inquiry_id"])
                    if best_text_entity.get("inquiry_id") is not None
                    else None
                ),
            )
        )
    return search_items, None


async def search_v2_contextual(
    cls,
    *,
    history_id: int | None,
    files: list | None,
    vehicle_batch: str | None = None,
    item_name: str | None = None,
    item_description: str | None = None,
    train_no: str | None = None,
    car_num: str | None = None,
    subordinate_component: str | None = None,
    search_mode: str = "siglip",
    search_equipment: str = "web",
    runtime=None,
):
    """融合可选图片和配件描述，并用业务条件过滤后维护最近两轮快照。"""
    runtime = runtime or _runtime()
    files = list(files or [])
    if search_mode not in {"siglip", "dinov2", "hybrid"}:
        raise ContextualSearchBusinessError(422, "search_mode 仅支持 siglip、dinov2、hybrid")

    parameters = runtime.SearchParameters(
        vehicle_batch=_clean_optional(vehicle_batch),
        item_name=_clean_optional(item_name),
        item_description=_clean_optional(item_description),
        train_no=_clean_optional(train_no),
        car_num=_clean_optional(car_num),
        subordinate_component=_clean_optional(subordinate_component),
        search_mode=search_mode,
    )
    has_metadata = any(
        (
            parameters.vehicle_batch,
            parameters.item_name,
            parameters.item_description,
            parameters.train_no,
            parameters.car_num,
            parameters.subordinate_component,
        )
    )

    if history_id is None:
        if not files and not parameters.item_description:
            raise ContextualSearchBusinessError(
                422,
                "首次条件检索至少上传图片或提供配件描述",
            )
        new_history_id = int(runtime.get_id())
        query_paths: list[str] = []
        try:
            if files:
                query_paths, pil_images = await _prepare_uploaded_query_images(
                    new_history_id, files, runtime=runtime
                )
            else:
                pil_images = []
            search_items, message = await _execute_contextual_search(
                cls,
                query_images=pil_images,
                parameters=parameters,
                runtime=runtime,
            )
            searched_at = runtime.datetime.now()
            stored_results = _stored_results(search_items, runtime=runtime)
            top_item = search_items[0] if search_items else None
            async with runtime.SessionLocal() as session:
                session.add(
                    runtime.SearchHistory(
                        id=new_history_id,
                        inquery_id=None,
                        inquery_num=None,
                        search_result_item_name=(top_item.item_name if top_item else None),
                        search_result_item_code=(top_item.item_code if top_item else ""),
                        search_parameter=parameters,
                        query_text=parameters.item_description,
                        query_image=query_paths[0] if len(query_paths) == 1 else None,
                        query_images_json=query_paths if len(query_paths) > 1 else None,
                        search_equipment=search_equipment,
                        verify_status="pending",
                        search_results=stored_results,
                        previous_search_snapshot=None,
                        search_revision=1,
                    )
                )
                await session.commit()
        except Exception:
            await _delete_query_images(query_paths, runtime=runtime)
            raise
        return runtime.ContextualSearchRes(
            history_id=str(new_history_id),
            previous=None,
            current=_current_response(
                query_images=query_paths,
                parameters=parameters,
                search_items=search_items,
                searched_at=searched_at,
                runtime=runtime,
            ),
            message=message,
        )

    async with runtime.SessionLocal() as session:
        history = await runtime.ContextualSearchRepository.get_history(
            session, int(history_id)
        )
    if history is None:
        raise ContextualSearchBusinessError(404, f"history_id={history_id} 的记录不存在")
    if getattr(history, "verify_status", None) != "pending":
        raise ContextualSearchBusinessError(409, "只有 pending 状态允许再次检索")
    if not files and not has_metadata:
        raise ContextualSearchBusinessError(422, "未上传新图片时至少提供一个业务条件")

    current_paths = _history_query_images(history)
    if not files and not current_paths and not parameters.item_description:
        raise ContextualSearchBusinessError(
            422,
            "当前历史没有可复用的查询图片，请提供新图片或配件描述",
        )

    uploaded_paths: list[str] = []
    try:
        if files:
            uploaded_paths, pil_images = await _prepare_uploaded_query_images(
                int(history_id), files, runtime=runtime
            )
            next_paths = uploaded_paths
        elif current_paths:
            next_paths = current_paths
            pil_images = await _load_query_images(current_paths, runtime=runtime)
        else:
            next_paths = []
            pil_images = []

        search_items, message = await _execute_contextual_search(
            cls,
            query_images=pil_images,
            parameters=parameters,
            runtime=runtime,
        )
        searched_at = runtime.datetime.now()
        old_current_snapshot = _previous_snapshot(history, runtime=runtime)
        stored_results = _stored_results(search_items, runtime=runtime)
        top_item = search_items[0] if search_items else None

        async with runtime.SessionLocal() as session:
            updated = await runtime.ContextualSearchRepository.update_history_window(
                session,
                history_id=int(history_id),
                expected_revision=int(getattr(history, "search_revision", 0) or 0),
                previous_snapshot=old_current_snapshot,
                query_images=next_paths,
                parameters=parameters,
                results=stored_results,
                top_item=top_item,
            )
            if not updated:
                await session.rollback()
                raise ContextualSearchBusinessError(409, "检索记录已被其他请求更新，请刷新后重试")
            await session.commit()
    except Exception:
        await _delete_query_images(uploaded_paths, runtime=runtime)
        raise

    old_previous = getattr(history, "previous_search_snapshot", None)
    old_previous_paths = list(getattr(old_previous, "query_images", None) or [])
    retained_paths = set(old_current_snapshot.query_images) | set(next_paths)
    stale_paths = [path for path in old_previous_paths if path not in retained_paths]
    await _delete_query_images(stale_paths, runtime=runtime)

    return runtime.ContextualSearchRes(
        history_id=str(history_id),
        previous=_snapshot_response(old_current_snapshot, runtime=runtime),
        current=_current_response(
            query_images=next_paths,
            parameters=parameters,
            search_items=search_items,
            searched_at=searched_at,
            runtime=runtime,
        ),
        message=message,
    )
