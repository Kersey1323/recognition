"""Cross-check image API results against exhaustive cosine search on saved vectors."""

import argparse
import asyncio
import json
from pathlib import Path

import numpy as np
from PIL import Image

from csrcqsf.infra.external.model_client import ModelServiceClient


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--query-cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    catalog = json.loads((args.index / 'catalog.json').read_text())
    gallery = np.load(args.index / 'image_vectors.npy', mmap_mode='r')
    gallery = gallery / np.linalg.norm(gallery, axis=1, keepdims=True)
    paths = list(dict.fromkeys(p for s in report['samples'] for p in s['query_images']))
    if args.query_cache.exists():
        cached = np.load(args.query_cache)
        assert cached['paths'].tolist() == paths
        vectors = cached['vectors']
    else:
        model = ModelServiceClient(base_url='http://127.0.0.1:5555')
        rows = []
        for i, path in enumerate(paths):
            with Image.open(path) as image:
                rows.append(await model.siglip_image_features(image.convert('RGB')))
            if (i + 1) % 25 == 0:
                print(f'Encoded {i + 1}/{len(paths)} query images', flush=True)
        vectors = np.asarray(rows, dtype=np.float32)
        np.savez(args.query_cache, paths=np.asarray(paths), vectors=vectors)
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    scores = vectors @ gallery.T
    path_indexes = {p: i for i, p in enumerate(paths)}
    part_indexes = [[i for i, im in enumerate(catalog['images']) if im['part_index'] == part]
                    for part in range(len(catalog['parts']))]
    part_scores = np.column_stack([scores[:, indexes].max(axis=1) for indexes in part_indexes])
    per_query_codes = []
    for row in part_scores:
        best = np.argsort(-row, kind='stable')[:20]
        per_query_codes.append({catalog['parts'][int(i)]['item_code']: float(row[i]) for i in best})
    samples = []
    for sample in report['samples']:
        merged = {}
        for path in sample['query_images']:
            for code, score in per_query_codes[path_indexes[path]].items():
                merged[code] = max(merged.get(code, -1), score)
        codes = sorted(merged, key=lambda code: -merged[code])
        returned = sample['returned_codes']
        # 两种浮点实现可能交换几乎同分的候选；保留严格比较，同时单独记录微小分差。
        order_differences = [
            {'rank': i + 1, 'api_code': actual, 'exhaustive_code': expected,
             'score_gap': abs(merged.get(actual, -2) - merged[expected])}
            for i, (actual, expected) in enumerate(zip(returned[:20], codes[:20]))
            if actual != expected
        ]
        same_top20_with_tolerance = (
            len(returned[:20]) == len(codes[:20])
            and all(difference['score_gap'] <= 1e-6 for difference in order_differences)
        )
        errors = []
        for item in sample['returned_items']:
            code = item['item_code']
            if code not in merged or abs(item['rate'] - merged[code]) > 2e-5:
                errors.append({'code': code, 'api_score': item['rate'],
                               'exhaustive_score': merged.get(code)})
        samples.append({'inquiry_num': sample['inquiry_num'], 'api_rank': sample['rank'],
            'exhaustive_rank': codes.index(sample['expected_code']) + 1 if sample['expected_code'] in codes else None,
            'same_top20_codes': codes[:20] == returned[:20],
            'same_top20_with_tolerance': same_top20_with_tolerance,
            'order_differences': order_differences,
            'same_candidate_set': set(codes) == set(returned), 'score_errors': errors})
    result = {'report': str(args.report), 'index': str(args.index), 'query_images': len(paths),
        'ranking_score_tolerance': 1e-6,
        'strict_top20_order_verified': all(s['same_top20_codes'] for s in samples),
        'samples': samples, 'verified': all(s['same_top20_with_tolerance'] and s['same_candidate_set']
            and s['api_rank'] == s['exhaustive_rank'] and not s['score_errors'] for s in samples)}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'verified': result['verified'], 'samples': len(samples),
                      'differences': [s for s in samples if not s['same_top20_codes']
                                      or not s['same_candidate_set'] or s['score_errors']]}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
