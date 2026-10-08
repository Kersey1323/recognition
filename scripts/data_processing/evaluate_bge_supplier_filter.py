"""Compare BGE retrieval with and without a supplier allowlist, without history writes."""

import argparse
import asyncio
from datetime import datetime
import json
import re
import traceback
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from sqlalchemy import select, func, or_
from csrcqsf.infra.db.main_db import SessionLocal, engine
from csrcqsf.models.orm.item import ItemSupplier, Items
from csrcqsf.modules.railway_parts.repositories.contextual_search_repository import ContextualSearchRepository
from csrcqsf.modules.railway_parts.schemas.search import SearchItem, SearchRes
from csrcqsf.modules.railway_parts.services import search_service
from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import get_inquiry_semantic_index_service


def normalize_name(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value or '')).strip().casefold()


async def run(args):
    source = json.loads(args.input.read_text())['samples'][:args.limit]
    manifest = {str(s['inquiry_id']): s for s in json.loads(args.manifest.read_text())}
    async with SessionLocal() as session:
        allowed = list(await session.scalars(select(ItemSupplier.item_id).where(
            ItemSupplier.item_id.is_not(None), ItemSupplier.supplier_name.is_not(None),
            func.trim(ItemSupplier.supplier_name) != '',
            or_(ItemSupplier.enable_status.is_(None), ItemSupplier.enable_status == 'normal'),
        ).distinct()))
    if not allowed:
        raise RuntimeError('Supplier allowlist is empty')
    allowed_set = set(allowed)
    variants = ('baseline', 'supplier_filtered', 'vehicle_filtered', 'vehicle_supplier_filtered') if args.with_vehicle else ('baseline', 'supplier_filtered')
    vehicle_cache = {}
    selected_allowlist = allowed
    print(f'allowed_items={len(allowed)} samples={len(source)}', flush=True)
    service = get_inquiry_semantic_index_service()
    original_batches = service.search_candidate_batches
    original_embeddings = service.model_client.text_embeddings
    embedding_cache = {}

    async def embeddings(texts):
        key = tuple(texts)
        if key not in embedding_cache:
            embedding_cache[key] = await original_embeddings(texts)
        return embedding_cache[key]

    async def filtered_batches(**kwargs):
        kwargs['item_ids'] = selected_allowlist
        async for batch in original_batches(**kwargs):
            yield batch

    report = dict(input=str(args.input), method='Paired current BGE searches; supplier allowlist applied inside Milvus before top1000; top20 name groups; inquiry ID/time exclusion enabled; no history persistence', allowed_items=len(allowed), samples=[])
    report['variants'] = list(variants)
    report['vehicle_filter'] = 'Exact FIND_IN_SET on item_info.vehicle_batch; input vehicle_batch or vehicle prefix before underscore; missing vehicle leaves scope unchanged' if args.with_vehicle else None
    if args.resume and args.output.exists():
        old = json.loads(args.output.read_text())
        if old['input'] != str(args.input):
            raise ValueError('Resume input mismatch')
        if old.get('variants', ['baseline', 'supplier_filtered']) != list(variants):
            raise ValueError('Resume variants mismatch')
        report['samples'] = old['samples']
    completed = {r['inquiry_id'] for r in report['samples']}
    no_history = SimpleNamespace(_persist_v2_search_history=AsyncMock())
    runtime = SimpleNamespace(get_id=lambda: 0, SessionLocal=SessionLocal,
                              ContextualSearchRepository=ContextualSearchRepository,
                              SearchItem=SearchItem, SearchRes=SearchRes)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        metrics = {}
        for route in ('original', 'vl'):
            for variant in variants:
                rs = [s['results'][route][variant] for s in report['samples']]
                metrics[f'{route}_{variant}'] = dict(
                    evaluated=len(rs), errors=sum('error' in r for r in rs),
                    **{f'code_hits@{k}': sum(r.get('rank') is not None and r['rank'] <= k for r in rs) for k in (1,5,10,20)},
                    **{f'name_hits@{k}': sum(r.get('name_rank') is not None and r['name_rank'] <= k for r in rs) for k in (1,5,10,20)},
                )
        report['metrics'] = metrics
        report['union_code_hits'] = {
            variant: {f'hits@{k}': sum(any(
                s['results'][route][variant].get('rank') is not None
                and s['results'][route][variant]['rank'] <= k
                for route in ('original', 'vl')
            ) for s in report['samples']) for k in (1, 5, 10, 20)}
            for variant in variants
        }
        report['updated_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')

    with patch.object(search_service, 'agent_running', True), patch.object(service.model_client, 'text_embeddings', embeddings):
        for i, sample in enumerate(source, 1):
            if sample['inquiry_id'] in completed:
                continue
            m = manifest[str(sample['inquiry_id'])]
            when = m['metadata']['inquiry_time']
            if not when:
                raise ValueError('Missing inquiry time')
            record = {k: sample.get(k) for k in ('inquiry_id','inquiry_num','expected_code','expected_name','generated_name')}
            record['source_inquiry_time'] = when
            if args.with_vehicle:
                inp = m['input']
                vehicle = str(inp.get('vehicle_batch') or '').strip()
                if not vehicle:
                    vehicle = str(inp.get('vehicle') or '').split('_', 1)[0].strip()
                vehicle = vehicle.upper()
                if vehicle and vehicle not in vehicle_cache:
                    async with SessionLocal() as session:
                        vehicle_cache[vehicle] = (await session.execute(select(
                            Items.id, Items.item_code,
                        ).where(func.find_in_set(vehicle, Items.vehicle_batch) > 0))).all()
                matched = vehicle_cache.get(vehicle, [])
                vehicle_ids = sorted({row.id for row in matched}) if vehicle else None
                combined_ids = sorted(set(vehicle_ids) & allowed_set) if vehicle else allowed
                record.update(vehicle_batch=vehicle or None, vehicle_filter_applied=bool(vehicle),
                              vehicle_candidate_count=len(vehicle_ids) if vehicle else None,
                              combined_candidate_count=len(combined_ids),
                              expected_code_in_vehicle_scope=any(str(row.item_code).strip()==sample['expected_code'] for row in matched) if vehicle else None)
            record['results'] = {}
            for route, query in [('original', m['input']['inquiry_item_name']), ('vl', sample['generated_name'])]:
                record['results'][route] = {}
                for variant in variants:
                    try:
                        selected_allowlist = vehicle_ids if variant == 'vehicle_filtered' else combined_ids if variant == 'vehicle_supplier_filtered' else allowed
                        batches = original_batches if variant == 'baseline' else filtered_batches
                        with patch.object(service, 'search_candidate_batches', batches):
                            res = await asyncio.wait_for(search_service.search_v2_by_text(
                                no_history, query_text=query, top_k=20,
                                source_inquiry_id=str(sample['inquiry_id']),
                                source_inquiry_time=when,
                                runtime=runtime,
                            ), timeout=180)
                        items=[]
                        for group_rank, group in enumerate(res.data, 1):
                            for item in (group.group_members or [group]):
                                items.append(dict(item_code=item.item_code, item_name=item.item_name, group_rank=group_rank))
                        rank = next((j for j,item in enumerate(items,1) if item['item_code']==sample['expected_code']),None)
                        name_rank = next((item['group_rank'] for item in items if normalize_name(item['item_name'])==normalize_name(sample['expected_name'])),None)
                        result = dict(rank=rank, name_rank=name_rank, items=items)
                    except Exception as exc:
                        traceback.print_exc()
                        result = dict(error=f'{type(exc).__name__}: {exc}',rank=None,name_rank=None)
                    record['results'][route][variant]=result
                    print(f'[{i}/{len(source)}] {sample.get("inquiry_num")} {route}/{variant} rank={result.get("rank")} error={result.get("error", "")}',flush=True)
                    if 'error' in result and not report['samples']:
                        report['preflight_error']=result['error']
                        save()
                        raise RuntimeError(result['error'])
            report['samples'].append(record)
            save()
    print(json.dumps(report['metrics'],ensure_ascii=False,indent=2),flush=True)
    await engine.dispose()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=Path('/home/ubuntu/project-train/searchCode-agent/outputs/retrieval_tools_grouped_1000_vl_name_context_no_images_test_100.json'))
    parser.add_argument('--manifest',type=Path,default=Path('/home/ubuntu/project-train/CodeQueryVL/data/inquiry_online/manifest_time_split.json'))
    parser.add_argument('--output',type=Path,default=Path('/home/ubuntu/project-train/searchCode-agent/outputs/bge_supplier_prefilter_100_20261008.json'))
    parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--with-vehicle',action='store_true')
    asyncio.run(run(parser.parse_args()))
