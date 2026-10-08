"""Replay the four original retrieval routes with a supplier prefilter only."""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from PIL import Image
from sqlalchemy import select, func, or_

from csrcqsf.infra.db.main_db import SessionLocal, engine
from csrcqsf.models.orm.item import ItemSupplier
from csrcqsf.models.orm.search_history import SearchParameters
from csrcqsf.modules.railway_parts.services import parts_service, search_service, contextual_search_service as context_service
from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import get_inquiry_semantic_index_service

sys.path.insert(0, '/home/ubuntu/project-train/searchCode-agent/src')
from searchcode_agent.evaluation import _parse_sample


ROUTES = ('search_text_vectors', 'vl_generated_text_vectors', 'search_with_context', 'search_images')
VARIANTS = ('baseline', 'supplier_filtered')


def flatten_items(items):
    # 与工具适配器一致：按名称组展开成员，再按编码保留首次出现的位置。
    by_code = {}
    for rank, item in enumerate(items, 1):
        for member in item.get('group_members') or [item]:
            code = str(member.get('item_code') or '').strip()
            if code:
                by_code.setdefault(code, dict(item_code=code, item_name=member.get('item_name'),
                    group_rank=rank if item.get('group_members') else None))
    return list(by_code.values())


def metrics(samples):
    result = {}
    for variant in VARIANTS:
        result[variant] = {'evaluated': len(samples), 'tools': {}}
        for route in ROUTES:
            rows = [s['results'][route][variant] for s in samples]
            result[variant]['tools'][route] = {
                'errors': sum('error' in r for r in rows),
                **{f'hits@{k}': sum(r.get('rank') is not None and r['rank'] <= k for r in rows) for k in (1,5,10,20)},
            }
        result[variant]['union'] = {
            f'hits@{k}': sum(any(s['results'][route][variant].get('rank') is not None and s['results'][route][variant]['rank'] <= k for route in ROUTES) for s in samples)
            for k in (1,5,10,20)
        }
    return result


async def run(args):
    original = json.loads(args.input.read_text())
    source = original['samples'][:args.limit]
    manifest = {str(s['inquiry_id']): s for s in json.loads(args.manifest.read_text())}
    async with SessionLocal() as session:
        allowed = set(await session.scalars(select(ItemSupplier.item_id).where(
            ItemSupplier.item_id.is_not(None), ItemSupplier.supplier_name.is_not(None),
            func.trim(ItemSupplier.supplier_name) != '',
            or_(ItemSupplier.enable_status.is_(None), ItemSupplier.enable_status == 'normal'),
        ).distinct()))
    if not allowed:
        raise ValueError('Empty supplier allowlist')
    service = get_inquiry_semantic_index_service()
    batches = service.search_candidate_batches
    embed = service.model_client.text_embeddings
    text_cache = {}
    image_manager = parts_service._get_milvus_manager_v2_cls()()
    image_embed = image_manager.model_client.siglip_image_features
    image_cache = {}
    manager = parts_service.RailwayPartsManager
    no_history = SimpleNamespace(_persist_v2_search_history=AsyncMock())

    async def text_embeddings(texts):
        k = tuple(texts)
        if k not in text_cache:
            text_cache[k] = await embed(texts)
        return text_cache[k]

    async def image_embeddings(image):
        k = id(image)
        if k not in image_cache:
            image_cache[k] = await image_embed(image)
        return image_cache[k]

    async def filtered_batches(*a, **kw):
        existing = kw.get('item_ids')
        # 原车型候选由 contextual 自身计算，只追加供应商交集。
        kw['item_ids'] = sorted(allowed if existing is None else allowed.intersection(existing))
        async for batch in batches(*a, **kw):
            yield batch

    report = dict(source_report=str(args.input), original_code_metrics=original.get('code_metrics'),
                  method='Original four routes, paired replay. Only supplier prefilter differs. Context uses original historical-inquiry vehicle scope, no images; image route uses SigLIP global multi-image fusion. Text/context exclude current and future inquiries. No history writes.',
                  supplier_allowed_items=len(allowed), samples=[])
    if args.resume and args.output.exists():
        old = json.loads(args.output.read_text())
        if old['source_report'] != str(args.input):
            raise ValueError('Resume input mismatch')
        report['samples'] = old['samples']
    done = {s['inquiry_id'] for s in report['samples']}
    def save():
        report['metrics'] = metrics(report['samples'])
        report['updated_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')

    with patch.object(search_service, 'agent_running', True), patch.object(context_service, 'agent_running', True), patch.object(service.model_client, 'text_embeddings', text_embeddings), patch.object(image_manager.model_client, 'siglip_image_features', image_embeddings):
        for i, old in enumerate(source, 1):
            if old['inquiry_id'] in done:
                continue
            sample = _parse_sample(manifest[str(old['inquiry_id'])], max_images=10)
            if not sample.inquiry_time:
                raise ValueError('Missing inquiry time')
            row = {k: old.get(k) for k in ('inquiry_id','inquiry_num','expected_code','expected_name','generated_name')}
            row.update(vehicle_batch=sample.vehicle_batch, source_inquiry_time=sample.inquiry_time, results={})
            images = []
            for path in sample.image_paths:
                with Image.open(path) as image:
                    images.append(image.convert('RGB'))
            image_cache.clear()
            for route in ROUTES:
                row['results'][route] = {}
                for variant in VARIANTS:
                    try:
                        async def retrieve():
                            if route in ('search_text_vectors','vl_generated_text_vectors'):
                                query = sample.name_description if route == 'search_text_vectors' else old['generated_name']
                                res = await search_service.search_v2_by_text(no_history, query_text=query, top_k=20,
                                    source_inquiry_id=sample.inquiry_id, source_inquiry_time=sample.inquiry_time, runtime=parts_service)
                                return res.data
                            if route == 'search_with_context':
                                params = SearchParameters(item_description=sample.name_description,
                                    vehicle_batch=sample.vehicle_batch, train_no=sample.train_no,
                                    car_num=sample.car_num, subordinate_component=sample.subordinate_component,
                                    source_inquiry_id=sample.inquiry_id, source_inquiry_time=sample.inquiry_time, search_mode='siglip')
                                items, _ = await context_service._execute_contextual_search(manager, query_images=[], parameters=params, runtime=parts_service)
                                return items
                            per_image = []
                            for image in images:
                                per_image.append(await image_manager.search_by_image(image=image, top_k=20, mode='siglip', coarse_top_k=50, alpha=0.6,
                                    item_ids=sorted(allowed) if variant=='supplier_filtered' else None))
                            fused = manager._fuse_multi_image_search_results(per_image)
                            return manager._aggregate_v2_search_items([manager._build_search_item_from_hit(h) for h in fused])
                        with patch.object(service, 'search_candidate_batches', filtered_batches if variant=='supplier_filtered' else batches):
                            items = await asyncio.wait_for(retrieve(), timeout=300)
                        hits = flatten_items([item.dict() for item in items])
                        codes = [h['item_code'] for h in hits]
                        result = dict(rank=next((j for j,c in enumerate(codes,1) if c==sample.expected_code),None),
                                      returned_codes=codes, returned_items=hits)
                    except Exception as exc:
                        import traceback
                        traceback.print_exc()
                        result = dict(rank=None,error=f'{type(exc).__name__}: {exc}')
                        if not report['samples']:
                            report['preflight_error'] = result['error']
                            save()
                            raise
                    row['results'][route][variant] = result
                    print(f'[{i}/{len(source)}] {sample.inquiry_num} {route}/{variant} rank={result["rank"]} error={result.get("error", "")}',flush=True)
            report['samples'].append(row)
            save()
    print(json.dumps(report['metrics'],ensure_ascii=False,indent=2),flush=True)
    await engine.dispose()


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=Path('/home/ubuntu/project-train/searchCode-agent/outputs/retrieval_tools_grouped_1000_vl_name_context_no_images_test_100.json'))
    p.add_argument('--manifest',type=Path,default=Path('/home/ubuntu/project-train/CodeQueryVL/data/inquiry_online/manifest_time_split.json'))
    p.add_argument('--output',type=Path,default=Path('/home/ubuntu/project-train/searchCode-agent/outputs/four_tools_supplier_prefilter_100_20261008.json'))
    p.add_argument('--limit',type=int,default=100)
    p.add_argument('--resume',action='store_true')
    asyncio.run(run(p.parse_args()))
