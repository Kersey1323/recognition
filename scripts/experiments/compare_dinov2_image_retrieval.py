"""Compare DINOv2 global features with a fixed, verified SigLIP experiment."""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image
import requests


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def encode(model_url, path, query=False):
    started = time.monotonic()
    if query:
        # 询码图沿用主服务的 JPEG 编码；图库沿用已有 SigLIP 建库时的原始文件。
        with Image.open(path) as image:
            buffer = io.BytesIO()
            image.convert('RGB').save(buffer, format='JPEG', quality=90, optimize=True)
            raw = buffer.getvalue()
    else:
        raw = path.read_bytes()
    payload = {'image_base64': base64.b64encode(raw).decode()}
    response = requests.post(model_url + '/api/v1/dinov2/global-vector',
                             json=payload, timeout=180)
    response.raise_for_status()
    vector = np.asarray(response.json()['vector'], dtype=np.float32)
    if vector.ndim != 1 or not np.isfinite(vector).all() or np.linalg.norm(vector) <= 0:
        raise ValueError('Invalid DINOv2 feature: ' + str(path))
    vector /= np.linalg.norm(vector)
    return vector, time.monotonic() - started


def build_index(args, catalog):
    fingerprint = hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()
    state_path = args.index / 'build_state.json'
    root = Path(catalog['dataset'])
    probe_indexes = [0, len(catalog['images']) // 2, len(catalog['images']) - 1]
    probes = np.asarray([encode(args.model_url, root / catalog['images'][i]['local_path'])[0]
                         for i in probe_indexes])
    dimension = probes.shape[1]
    if state_path.exists():
        state = read(state_path)
        if state['fingerprint'] != fingerprint or state['model_url'] != args.model_url:
            raise ValueError('Existing index belongs to another dataset or service')
        previous_probes = np.load(args.index / 'encoder_probes.npy')
        if previous_probes.shape != probes.shape or not np.all(
                (probes * previous_probes).sum(axis=1) > .99999):
            raise ValueError('Model output changed; use a new experiment directory')
    else:
        state = {'fingerprint': fingerprint, 'model_url': args.model_url,
                 'dimension': dimension, 'completed': 0, 'model': 'dinov2_global_cls',
                 'started_at': datetime.now(timezone.utc).isoformat()}
        np.save(args.index / 'encoder_probes.npy', probes)
        save(args.index / 'catalog.json', catalog)
        save(state_path, state)
    path = args.index / 'image_vectors.npy'
    if state['completed'] and not path.exists():
        raise ValueError('Index checkpoint exists but vector file is missing')
    vectors = np.lib.format.open_memmap(path, mode='r+' if path.exists() else 'w+',
        dtype=np.float32, shape=(len(catalog['images']), dimension))
    started = time.monotonic()
    initial_completed = state['completed']
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for start in range(state['completed'], len(catalog['images']), 32):
            end = min(start + 32, len(catalog['images']))
            paths = [root / im['local_path'] for im in catalog['images'][start:end]]
            rows = list(executor.map(lambda p: encode(args.model_url, p)[0], paths))
            vectors[start:end] = rows
            vectors.flush()
            state['completed'] = end
            save(state_path, state)
            elapsed = time.monotonic() - started
            speed = (end - initial_completed) / max(elapsed, .001)
            print(json.dumps({'phase': 'gallery_features', 'completed': end,
                'total': len(vectors), 'images_per_second': round(speed, 2),
                'remaining_seconds': round((len(vectors) - end) / speed)}, ensure_ascii=False),
                flush=True)
    if not np.isfinite(vectors).all() or not np.allclose(
            np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
        raise ValueError('Gallery contains invalid vectors')
    # 随机位置以外再核对三张固定图片，避免断点恢复后图片顺序与向量错位。
    checks = (vectors[probe_indexes] * probes).sum(axis=1)
    if not np.all(checks > .99999):
        raise ValueError('Gallery vector positions do not match the catalog')
    state.update(completed_at=datetime.now(timezone.utc).isoformat(),
                 probe_cosines=checks.tolist(), parts=len(catalog['parts']),
                 images=len(vectors), verified=True)
    save(state_path, state)
    return vectors, fingerprint


def rank_parts(query_vectors, gallery, part_indexes):
    scores = query_vectors @ gallery.T
    # 同一配件的所有图库图片、同一询码的所有图片，只保留最高相似度。
    # 因此多图配件不会占掉其他配件的名额，也不使用名称或车型参与排序。
    best_by_image = scores.max(axis=0)
    part_scores = np.asarray([best_by_image[indexes].max() for indexes in part_indexes])
    winners = np.asarray([indexes[best_by_image[indexes].argmax()] for indexes in part_indexes])
    ranking = np.argsort(-part_scores, kind='stable')
    return ranking, part_scores, winners


def metrics(samples):
    total = len(samples)
    result = {'evaluated': total, 'successful_requests': sum(
        sample['status'] == 'succeeded' for sample in samples), 'errors': sum(
        sample['status'] == 'error' for sample in samples)}
    for k in (1, 5, 10, 20):
        hits = sum(s['rank'] is not None and s['rank'] <= k for s in samples)
        result[f'hits@{k}'] = hits
        result[f'recall@{k}'] = round(hits / total, 6) if total else 0
    result['mrr@20'] = round(sum(1 / s['rank'] for s in samples
        if s['rank'] and s['rank'] <= 20) / total, 6) if total else 0
    return result


def evaluate(args, catalog, gallery, fingerprint):
    baseline = read(args.baseline)
    old_samples = baseline['samples']
    if not old_samples or any(s['status'] != 'succeeded' for s in old_samples):
        raise ValueError('Expected a nonempty, successful SigLIP baseline')
    codes = [p['item_code'] for p in catalog['parts']]
    if len(set(codes)) != len(codes):
        raise ValueError('Gallery must contain one group per item code')
    indexes = [np.asarray([i for i, im in enumerate(catalog['images'])
                           if im['part_index'] == part], dtype=np.int64)
               for part in range(len(codes))]
    if any(not len(ix) for ix in indexes):
        raise ValueError('Gallery contains an empty item group')
    query_paths = list(dict.fromkeys(p for s in old_samples for p in s['query_images']))
    cache = args.index / f'query_features_{len(old_samples)}.npz'
    if cache.exists():
        with np.load(cache) as data:
            if data['paths'].tolist() != query_paths or str(data['fingerprint']) != fingerprint:
                raise ValueError('Query cache belongs to another experiment')
            query_vectors = data['vectors']
    else:
        rows = []
        for i, path in enumerate(query_paths):
            rows.append(encode(args.model_url, Path(path), query=True)[0])
            if (i + 1) % 25 == 0 or i + 1 == len(query_paths):
                print(f'Query features: {i + 1}/{len(query_paths)}', flush=True)
        query_vectors = np.asarray(rows)
        np.savez(cache, paths=np.asarray(query_paths), vectors=query_vectors,
                 fingerprint=np.asarray(fingerprint))
    if query_vectors.shape != (len(query_paths), gallery.shape[1]) or not np.isfinite(query_vectors).all():
        raise ValueError('Invalid query features')
    path_index = {path: i for i, path in enumerate(query_paths)}
    gallery_hashes = {im['sha256'] for im in catalog['images']}
    overlapping = [p for p in query_paths if hashlib.sha256(Path(p).read_bytes()).hexdigest()
                   in gallery_hashes]
    report = {'baseline': str(args.baseline.resolve()), 'index': str(args.index.resolve()),
        'configuration': {'model': 'dinov2_global_cls', 'model_url': args.model_url,
            'parts': len(codes), 'gallery_images': len(gallery), 'dimension': gallery.shape[1],
            'query_images': len(query_paths), 'metric': 'cosine', 'top_k': 20,
            'grouping': 'maximum score per item over all gallery and query images',
            'search': 'exhaustive over the complete gallery', 'text_or_vehicle_sent': False,
            'agent_used': False, 'patch_reranking': False, 'exact_query_gallery_overlap': overlapping,
            'timing_note': 'Cached features and local search; not comparable to API latency'},
        # 旧接口会合并多张询码图的前二十名，结果可能超过二十个；两边统一只计前二十。
        'samples': [], 'metrics': {}, 'siglip_metrics': metrics(old_samples),
        'baseline_original_metrics': baseline['metrics']}
    for i, old in enumerate(old_samples, 1):
        started = time.monotonic()
        selected = query_vectors[[path_index[p] for p in old['query_images']]]
        ranking, scores, winners = rank_parts(selected, gallery, indexes)
        top20 = ranking[:20]
        returned_codes = [codes[j] for j in top20]
        # 标准编码仅在检索完成后用于评分，不进入图片模型或候选选择。
        expected = old['expected_code']
        rank = returned_codes.index(expected) + 1 if expected in returned_codes else None
        expected_full_rank = next((r + 1 for r, j in enumerate(ranking) if codes[j] == expected), None)
        sample = {key: old[key] for key in ('inquiry_id', 'inquiry_num', 'expected_code',
            'expected_name', 'image_count', 'query_images')}
        sample.update(status='succeeded', rank=rank, full_gallery_rank=expected_full_rank,
            siglip_rank=old['rank'], returned_codes=returned_codes,
            elapsed_search_seconds=round(time.monotonic() - started, 4),
            returned_items=[{'item_code': codes[j], 'item_name': catalog['parts'][j]['item_name'],
                'rate': float(scores[j]), 'matched_image': catalog['images'][int(winners[j])],
                'matched_query_image': old['query_images'][int(np.argmax(
                    selected @ gallery[winners[j]]))]} for j in top20])
        # 用逐配件矩阵单独复算全部得分，检查分组和矩阵索引是否一致。
        reference = np.asarray([(selected @ gallery[ix].T).max() for ix in indexes])
        if not np.allclose(scores, reference, atol=1e-6):
            raise ValueError('Independent grouped-score check failed: ' + old['inquiry_num'])
        sample['grouped_score_verified'] = True
        report['samples'].append(sample)
        report['metrics'] = metrics(report['samples'])
        save(args.output, report)
        print(f'[{i}/{len(old_samples)}] {old["inquiry_num"]} DINO rank={rank} '
              f'SigLIP rank={old["rank"]} hits@20={report["metrics"]["hits@20"]}/{i}', flush=True)
    report['comparison'] = {}
    for k in (1, 5, 10, 20):
        dino = {s['inquiry_num'] for s in report['samples'] if s['rank'] and s['rank'] <= k}
        siglip = {s['inquiry_num'] for s in old_samples if s['rank'] and s['rank'] <= k}
        report['comparison'][f'top{k}'] = {'dinov2_only': sorted(dino - siglip),
            'siglip_only': sorted(siglip - dino), 'both': sorted(dino & siglip),
            'neither': sorted({s['inquiry_num'] for s in old_samples} - dino - siglip)}
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    report['verified'] = all(s['grouped_score_verified'] for s in report['samples'])
    save(args.output, report)
    print(json.dumps({'dinov2': report['metrics'], 'siglip': report['siglip_metrics'],
                      'report': str(args.output), 'verified': report['verified']}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-url', default='http://127.0.0.1:5555')
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error('workers must be positive')
    args.index.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() and read(args.output).get('completed_at'):
        parser.error('Completed report already exists; choose another output path')
    catalog = read(args.catalog)
    gallery, fingerprint = build_index(args, catalog)
    evaluate(args, catalog, gallery, fingerprint)


if __name__ == '__main__':
    main()
