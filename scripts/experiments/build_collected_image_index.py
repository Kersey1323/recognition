"""Build a separate image-only experiment collection, reusing verified vectors."""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from pymilvus import DataType, MilvusClient
import requests


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def encode(session, url, paths):
    rows = []
    # 主服务单图检索使用 pooler 特征；当前批量接口取值不同，实验建库沿用单图路径。
    for path in paths:
        response = session.post(url + '/api/v1/siglip/image-features', json={
            'image_base64': base64.b64encode(path.read_bytes()).decode(),
        }, timeout=180)
        response.raise_for_status()
        rows.append(response.json()['vector'])
    vectors = np.asarray(rows, dtype=np.float32)
    assert vectors.shape == (len(paths), 1152) and np.isfinite(vectors).all()
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors


def warm_downloads(args):
    previous = read(args.previous_index / 'catalog.json')
    known = {im['sha256'] for im in previous['images']}
    cache = args.output / 'image_feature_cache'
    cache.mkdir(parents=True, exist_ok=True)
    progress = args.dataset / 'download_progress.jsonl'
    session = requests.Session()
    count = 0
    with progress.open() as stream:
        while True:
            line = stream.readline()
            if not line:
                if (args.dataset / 'summary.json').exists():
                    break
                time.sleep(2)
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            digest = row.get('sha256')
            if row.get('status') != 'ok' or not digest or digest in known:
                continue
            destination = cache / (digest + '.npy')
            if not destination.exists():
                vector = encode(session, args.model_url,
                                [args.dataset / row['local_path']])[0]
                temporary = destination.with_suffix('.warming.tmp')
                with temporary.open('wb') as output:
                    np.save(output, vector)
                temporary.replace(destination)
                count += 1
                if count % 100 == 0:
                    print(json.dumps({'phase': 'new_image_features', 'encoded': count}), flush=True)
            known.add(digest)
    print(json.dumps({'phase': 'precompute_complete', 'encoded': count}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--previous-index', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--collection', required=True)
    parser.add_argument('--model-url', default='http://127.0.0.1:5555')
    parser.add_argument('--warm-downloads', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.warm_downloads:
        warm_downloads(args)
        return
    manifest = read(args.dataset / 'manifest.json')
    metadata = {p['item_code']: p for p in read(args.dataset / 'local_business_metadata.json')}
    parts, images = [], []
    for row in manifest:
        usable = [im for im in row['gallery_images'] if im.get('download_status') == 'ok']
        if not usable:
            raise ValueError('Part has no downloaded gallery images: ' + row['item_code'])
        if len(usable) != len(row['gallery_images']):
            raise ValueError('Part has failed gallery downloads: ' + row['item_code'])
        local = metadata[row['item_code']]
        part_index = len(parts)
        parts.append({'item_code': row['item_code'], 'item_name': local['item_name'],
            'item_id': local['local_item_id'] or row['item_id'],
            'online_item_id': row['item_id'], 'vehicle_batches': local['vehicle_batches']})
        for im in usable:
            assert im['image_source_type'] in {'BASEINFO', 'CREATEBYSELF'}
            images.append({'part_index': part_index, 'item_code': row['item_code'],
                'image_id': str(im['image_id']), 'source_type': im['image_source_type'],
                'local_path': im['local_path'], 'sha256': im['sha256']})
    catalog = {'dataset': str(args.dataset.resolve()), 'parts': parts, 'images': images}
    fingerprint = hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()
    state_path = args.output / 'image_build_state.json'
    state = read(state_path) if state_path.exists() else {
        'fingerprint': fingerprint, 'completed': 0, 'reused': 0, 'encoded': 0,
        'collection': args.collection, 'collection_created': False,
    }
    assert state['fingerprint'] == fingerprint and state['collection'] == args.collection
    save(args.output / 'catalog.json', catalog)
    previous = read(args.previous_index / 'catalog.json')
    previous_vectors = np.load(args.previous_index / 'image_vectors.npy', mmap_mode='r')
    reusable = {im['sha256']: i for i, im in enumerate(previous['images'])}
    session = requests.Session()
    # 缓存向量只有在当前模型输出一致时才复用，防止不同模型的向量混入同一个实验库。
    probes = [i for i, im in enumerate(images) if im['sha256'] in reusable]
    selected = [probes[0], probes[len(probes)//2], probes[-1]]
    actual = encode(session, args.model_url, [args.dataset / images[i]['local_path'] for i in selected])
    expected = np.asarray([previous_vectors[reusable[images[i]['sha256']]] for i in selected])
    similarities = (actual * expected).sum(axis=1)
    if not np.all(similarities > .99999):
        raise ValueError('Current image encoder differs from cached encoder: ' + str(similarities))
    print(json.dumps({'phase': 'encoder_check', 'cosine': similarities.tolist()}), flush=True)
    vector_path = args.output / 'image_vectors.npy'
    vectors = np.lib.format.open_memmap(
        vector_path, mode='r+' if vector_path.exists() else 'w+',
        dtype=np.float32, shape=(len(images), 1152),
    )
    for start in range(state['completed'], len(images), 32):
        end = min(start + 32, len(images))
        pending = []
        for i in range(start, end):
            old = reusable.get(images[i]['sha256'])
            if old is not None:
                vectors[i] = previous_vectors[old]
                state['reused'] += 1
            else:
                cached = args.output / 'image_feature_cache' / (images[i]['sha256'] + '.npy')
                if cached.exists():
                    vector = np.load(cached)
                    assert vector.shape == (1152,) and np.isfinite(vector).all()
                    vectors[i] = vector
                    state['encoded'] += 1
                else:
                    pending.append(i)
        for offset in range(0, len(pending), 4):
            batch = pending[offset:offset + 4]
            batch_vectors = encode(session, args.model_url,
                                   [args.dataset / images[i]['local_path'] for i in batch])
            for i, vector in zip(batch, batch_vectors):
                vectors[i] = vector
                cached = args.output / 'image_feature_cache' / (images[i]['sha256'] + '.npy')
                cached.parent.mkdir(parents=True, exist_ok=True)
                temporary = cached.with_suffix('.builder.tmp')
                with temporary.open('wb') as output:
                    np.save(output, vector)
                temporary.replace(cached)
            state['encoded'] += len(batch)
        vectors.flush()
        state['completed'] = end
        save(state_path, state)
        if end % 256 == 0 or end == len(images):
            print(json.dumps({'phase': 'vectors', 'completed': end, 'total': len(images),
                              'reused': state['reused'], 'encoded': state['encoded']}), flush=True)
    assert np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4)
    client = MilvusClient(uri='http://localhost:19530')
    if not client.has_collection(collection_name=args.collection):
        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        for field in ['id', 'item_id', 'image_id']:
            schema.add_field(field, DataType.INT64, **({'is_primary': True} if field == 'id' else {}))
        for field, length in [('item_name', 200), ('item_code', 100), ('image_variant', 32),
                              ('image_url', 500), ('description', 1000), ('created_at', 50)]:
            schema.add_field(field, DataType.VARCHAR, max_length=length)
        schema.add_field('image_vector', DataType.FLOAT_VECTOR, dim=1152)
        params = client.prepare_index_params()
        params.add_index(field_name='image_vector', index_type='FLAT', metric_type='COSINE')
        client.create_collection(collection_name=args.collection, schema=schema,
                                 index_params=params, consistency_level='Strong')
        state['collection_created'] = True
        save(state_path, state)
    elif not state['collection_created']:
        raise ValueError('Refusing to overwrite an existing collection: ' + args.collection)
    now = datetime.now(timezone.utc).isoformat()
    for start in range(0, len(images), 128):
        records = []
        for i in range(start, min(start + 128, len(images))):
            im = images[i]
            part = parts[im['part_index']]
            records.append({'id': i + 1, 'item_id': int(part['item_id']),
                'item_name': part['item_name'], 'item_code': part['item_code'],
                'image_id': int(im['image_id']), 'image_variant': 'original',
                'image_url': str(Path(im['local_path']).relative_to('images')),
                'description': part['item_name'], 'created_at': now,
                'image_vector': vectors[i].tolist()})
        client.upsert(collection_name=args.collection, data=records)
    client.flush(collection_name=args.collection)
    client.load_collection(collection_name=args.collection)
    count = client.query(collection_name=args.collection, filter='', output_fields=['count(*)'])[0]['count(*)']
    assert count == len(images)
    iterator = client.query_iterator(collection_name=args.collection, batch_size=1000,
                                     output_fields=['id', 'item_id', 'item_code', 'image_id'])
    verified = set()
    try:
        while True:
            rows = iterator.next()
            if not rows:
                break
            for row in rows:
                im = images[int(row['id']) - 1]
                part = parts[im['part_index']]
                assert row['item_code'] == part['item_code'] and row['item_id'] == int(part['item_id'])
                assert row['image_id'] == int(im['image_id'])
                verified.add(row['id'])
    finally:
        iterator.close()
    assert len(verified) == len(images)
    verification = {'status': 'verified', 'collection': args.collection, 'parts': len(parts),
        'images': len(images), 'reused_vectors': state['reused'], 'encoded_vectors': state['encoded'],
        'encoder_cache_check_cosine': similarities.tolist(), 'dimension': 1152,
        'inquiry_images_indexed': 0, 'text_embeddings_built': 0,
        'verified_at': datetime.now(timezone.utc).isoformat()}
    save(args.output / 'image_index_verification.json', verification)
    print(json.dumps({'phase': 'complete', **verification}), flush=True)


if __name__ == '__main__':
    main()
