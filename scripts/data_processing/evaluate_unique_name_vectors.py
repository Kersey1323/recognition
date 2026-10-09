"""Read-only pilot: unique material-name vectors and sampled VL query names."""

import argparse
import asyncio
import hashlib
import json
import re
import unicodedata
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv(Path(__file__).resolve().parents[2] / '.env')
from csrcqsf.infra.db.main_db import SessionLocal, engine
from csrcqsf.infra.external.model_client import ModelServiceClient


def normalize(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value or '')).strip().casefold()


def unit(vectors):
    vectors = np.asarray(vectors, dtype=np.float32)
    assert np.isfinite(vectors).all()
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    assert (norms > 0).all()
    return vectors / norms


async def run(args):
    args.output.mkdir(parents=True, exist_ok=True)
    source = json.loads(args.baseline.read_text())['samples'][:args.limit]
    sampled = {r['inquiry_id']: r for r in map(json.loads, args.sampling.read_text().splitlines())}
    assert all(len(sampled[s['inquiry_id']]['runs']) == 5 for s in source)
    async with SessionLocal() as session:
        rows = (await session.execute(text("SELECT item_code, item_name FROM item_info WHERE TRIM(item_name) != ''"))).all()
    groups = {}
    # 仅合并格式差异，型号、左右件和宽窄门等信息仍保留在标准名称中。
    for code, name in rows:
        group = groups.setdefault(normalize(name), {'name': name.strip(), 'codes': set()})
        group['codes'].add(str(code).strip())
    keys = sorted(groups)
    corpus = [dict(key=key, name=groups[key]['name'], codes=sorted(groups[key]['codes'])) for key in keys]
    payload = json.dumps(corpus, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    corpus_path = args.output / 'corpus.json'
    if corpus_path.exists():
        assert corpus_path.read_text() == payload, 'Corpus changed; use a new output directory'
    else:
        corpus_path.write_text(payload)
    client = ModelServiceClient()
    print(f'corpus={len(corpus)} items={len(rows)} samples={len(source)}', flush=True)
    blocks = []
    for start in range(0, len(corpus), 128):
        cache = args.output / f'vectors_{start:06d}.npy'
        if cache.exists():
            block = np.load(cache)
        else:
            block = unit(await client.text_embeddings([r['name'] for r in corpus[start:start+128]]))
            np.save(cache, block)
        assert block.shape == (len(corpus[start:start+128]), 1024)
        blocks.append(block)
        if start % 1280 == 0:
            print(f'embedded={min(start+128,len(corpus))}/{len(corpus)}', flush=True)
    matrix = np.concatenate(blocks)
    names = [r['name'] for r in corpus]
    def ranked(scores):
        order = np.argsort(-scores, kind='stable')[:20]
        return [dict(name=names[i], codes=corpus[i]['codes'], score=float(scores[i])) for i in order]
    results = []
    for i, s in enumerate(source, 1):
        vl = sampled[s['inquiry_id']]
        queries = list(dict.fromkeys([vl['original_name'], vl['greedy_name'], *vl['runs']]))
        vectors = unit(await client.text_embeddings(queries))
        similarities = vectors @ matrix.T
        lookup = dict(zip(queries, similarities))
        # 多采样统一取最高余弦相似度，输出仍限制为20个名称；另报每路TopK并集覆盖率。
        variants = {
            'original': ranked(lookup[vl['original_name']]),
            'greedy_vl': ranked(lookup[vl['greedy_name']]),
            'sampled_five_max': ranked(np.max([lookup[q] for q in vl['runs']], axis=0)),
        }
        per_query = {q: ranked(lookup[q]) for q in dict.fromkeys(vl['runs'])}
        truth_name, truth_code = normalize(s['expected_name']), s['expected_code']
        def hit(items, kind):
            return any(normalize(r['name']) == truth_name if kind == 'name' else truth_code in r['codes'] for r in items)
        scores = {}
        for variant, items in variants.items():
            scores[variant] = {kind: {str(k): hit(items[:k], kind) for k in (1,5,10,20)} for kind in ('name','code')}
        scores['sampled_five_union'] = {kind: {str(k): any(hit(items[:k],kind) for items in per_query.values()) for k in (1,5,10,20)} for kind in ('name','code')}
        results.append(dict(inquiry_id=s['inquiry_id'], inquiry_num=s.get('inquiry_num'), expected_name=s['expected_name'], expected_code=truth_code,
                            original_name=vl['original_name'], greedy_name=vl['greedy_name'], sampled_names=vl['runs'], variants=variants,
                            per_sampled_query=per_query, hits=scores,
                            expanded_code_counts={v: len({c for r in items for c in r['codes']}) for v,items in variants.items()}))
        print(f'evaluated={i}/{len(source)}', flush=True)
    metrics = {v: {kind: {f'recall@{k}': sum(r['hits'][v][kind][str(k)] for r in results)/len(results) for k in (1,5,10,20)} for kind in ('name','code')} for v in results[0]['hits']}
    demo = ranked((unit(await client.text_embeddings(['同步带'])) @ matrix.T)[0])
    report = dict(corpus_sha256=digest, corpus_names=len(corpus), corpus_items=len(rows), model_service=client.base_url,
                  sampling_file=str(args.sampling), baseline_file=str(args.baseline), evaluated=len(results),
                  notes='Current item_info name-only corpus. No inquiry history, vehicle or supplier filters. Code metrics measure coverage after expanding K name groups, NOT top-K codes. Five-route union may have up to 5K groups. Existing baseline is historical, not a paired live replay.',
                  metrics=metrics, synchronization_belt_example=demo, samples=results)
    report['historical_name_metrics'] = {
        route: {f'recall@{k}': sum(s['tools'][route].get('name_rank') is not None and s['tools'][route]['name_rank'] <= k for s in source)/len(source)
                for k in (1,5,10,20)}
        for route in ('search_text_vectors', 'vl_generated_text_vectors')
    }
    report['candidate_sizes_at20'] = {
        v: {'mean_codes': float(np.mean([s['expanded_code_counts'][v] for s in results])),
            'max_codes': max(s['expanded_code_counts'][v] for s in results)}
        for v in results[0]['variants']
    }
    (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    def esc(value):
        return str(value).replace('|', '\\|').replace('\n', '<br>')
    lines = ['# Unique-name vector pilot: 20 inquiries', '',
             f'Corpus: {len(corpus)} unique names from {len(rows)} current items.',
             'Name normalization: NFKC, whitespace, case folding; no specification removal.',
             'Code coverage expands all codes per name group. It is not top-K code recall.',
             'Five-query union includes up to 100 names at K=20; max-score fusion retains 20 names.', '',
             '| Method | Name @1 | @5 | @10 | @20 |', '| --- | --- | --- | --- | --- |']
    for variant, values in metrics.items():
        lines.append('| ' + variant + ' | ' + ' | '.join(f'{values["name"][f"recall@{k}"]:.0%}' for k in (1,5,10,20)) + ' |')
    lines += ['', '## Per-inquiry results', '',
              '| Inquiry | Expected name | Five generated names | Greedy @20 | Fused @20 | Union @20 | Fused top5 |',
              '| --- | --- | --- | --- | --- | --- | --- |']
    for s in results:
        values = [s['inquiry_num'],s['expected_name'],' / '.join(s['sampled_names']),
                  *[s['hits'][v]['name']['20'] for v in ('greedy_vl','sampled_five_max','sampled_five_union')],
                  ' / '.join(r['name'] for r in s['variants']['sampled_five_max'][:5])]
        lines.append('| ' + ' | '.join(map(esc, values)) + ' |')
    (args.output/'review.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)


async def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--sampling', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--limit', type=int, default=20)
    args = p.parse_args()
    try:
        await run(args)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
