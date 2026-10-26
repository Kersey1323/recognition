"""Import the collected-parts experiment into separate main-service collections."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np


DEFAULT_INDEX = Path('/home/ubuntu/project-train/CodeQueryVL/outputs/online_collected_parts_20261019_grouped')
TEXT_COLLECTION = 'COLLECTED_PARTS_20261019_BGE_M3_297_V1'
IMAGE_COLLECTION = 'COLLECTED_PARTS_20261019_SIGLIP_5777_V1'
SIGLIP_MODEL = '/home/ubuntu/CV/models/siglip2-so400m-patch14-384'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def encode_siglip_names(index):
    import torch
    from transformers import AutoModel, AutoTokenizer

    parts = read_json(index / 'catalog.json')['parts']
    tokenizer = AutoTokenizer.from_pretrained(SIGLIP_MODEL, local_files_only=True)
    model = AutoModel.from_pretrained(SIGLIP_MODEL, local_files_only=True).to('cuda').eval()
    vectors = []
    for start in range(0, len(parts), 32):
        inputs = tokenizer(
            [part['item_name'] for part in parts[start:start + 32]],
            padding='max_length', truncation=True, max_length=64, return_tensors='pt',
        ).to('cuda')
        with torch.inference_mode():
            output = model.get_text_features(**inputs)
            features = output if isinstance(output, torch.Tensor) else output.pooler_output
            features = torch.nn.functional.normalize(features.float(), dim=-1)
        vectors.append(features.cpu().numpy())
    vectors = np.concatenate(vectors)
    assert vectors.shape == (len(parts), 1152)
    np.save(index / 'siglip_name_vectors.npy', vectors)
    print(json.dumps({'siglip_name_vectors': list(vectors.shape)}), flush=True)


def text_records(parts, vectors, now):
    for part, vector in zip(parts, vectors):
        name = part['item_name']
        yield {
            # 基础名称与历史询码明确区分，防泄露过滤仍只检查历史询码文档。
            'document_key': 'catalog:' + part['item_code'], 'history_id': 0,
            'inquiry_id': '', 'item_id': int(part['item_id']),
            'item_code': part['item_code'], 'description': name,
            'content_hash': hashlib.sha256(name.encode()).hexdigest(),
            'text_vector': vector.tolist(), 'updated_at': now,
        }


def image_records(catalog, vectors, name_vectors, now):
    for row_index, (image, vector) in enumerate(zip(catalog['images'], vectors)):
        part_index = image['part_index']
        part = catalog['parts'][part_index]
        relative = Path(image['local_path'])
        if relative.parts[0] != 'images':
            raise ValueError('Gallery image must have an images/ relative path')
        yield {
            'id': row_index + 1, 'item_id': int(part['item_id']),
            'item_name': part['item_name'], 'item_code': part['item_code'],
            'image_id': int(image['image_id']), 'image_variant': 'original',
            'image_url': str(Path(*relative.parts[1:])), 'description': part['item_name'],
            'image_vector': vector.tolist(), 'text_vector': name_vectors[part_index].tolist(),
            'created_at': now,
        }


def encode_service_names(index, base_url, output):
    from urllib.request import Request, urlopen

    parts = read_json(index / 'catalog.json')['parts']
    vectors = []
    for start in range(0, len(parts), 32):
        texts = [part['item_name'] for part in parts[start:start + 32]]
        request = Request(base_url.rstrip('/') + '/api/v1/text/embeddings',
                          data=json.dumps({'texts': texts}).encode(),
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=120) as response:
            payload = json.load(response)
        batch = np.asarray(payload['vectors'], dtype=np.float32)
        assert batch.shape == (len(texts), 1024)
        vectors.append(batch)
    vectors = np.concatenate(vectors)
    assert np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4)
    np.save(output, vectors)
    print(json.dumps({'service_name_vectors': list(vectors.shape), 'output': str(output)}), flush=True)


def create_collections(client, text_name, image_name, *, text_only=False):
    from pymilvus import DataType

    text = client.create_schema(auto_id=False, enable_dynamic_field=False)
    text.add_field('document_key', DataType.VARCHAR, is_primary=True, max_length=64)
    text.add_field('history_id', DataType.INT64)
    text.add_field('inquiry_id', DataType.VARCHAR, max_length=100)
    text.add_field('item_id', DataType.INT64)
    text.add_field('item_code', DataType.VARCHAR, max_length=100)
    text.add_field('description', DataType.VARCHAR, max_length=1000)
    text.add_field('content_hash', DataType.VARCHAR, max_length=64)
    text.add_field('text_vector', DataType.FLOAT_VECTOR, dim=1024)
    text.add_field('updated_at', DataType.VARCHAR, max_length=50)

    image = client.create_schema(auto_id=False, enable_dynamic_field=False)
    image.add_field('id', DataType.INT64, is_primary=True)
    for field in ('item_id', 'image_id'):
        image.add_field(field, DataType.INT64)
    for field, length in [('item_name', 200), ('item_code', 100), ('image_variant', 32),
                          ('image_url', 500), ('description', 1000), ('created_at', 50)]:
        image.add_field(field, DataType.VARCHAR, max_length=length)
    for field in ('image_vector', 'text_vector'):
        image.add_field(field, DataType.FLOAT_VECTOR, dim=1152)

    # 小样本库使用全量精确比较，便于核对本地文件索引与服务检索结果。
    collections = [(text_name, text, ['text_vector'])]
    if not text_only:
        collections.append((image_name, image, ['image_vector', 'text_vector']))
    for name, schema, fields in collections:
        indexes = client.prepare_index_params()
        for field in fields:
            indexes.add_index(field_name=field, index_type='FLAT', metric_type='COSINE')
        client.create_collection(collection_name=name, schema=schema, index_params=indexes,
                                 consistency_level='Strong')


def insert_batches(client, collection, records):
    batch, total = [], 0
    for record in records:
        batch.append(record)
        if len(batch) == 128:
            client.insert(collection_name=collection, data=batch)
            total += len(batch)
            batch = []
    if batch:
        client.insert(collection_name=collection, data=batch)
        total += len(batch)
    client.flush(collection_name=collection)
    print(json.dumps({'collection': collection, 'inserted': total}), flush=True)


def verify_import(client, catalog, text_vectors, image_vectors, text_name, image_name):
    parts, images = catalog['parts'], catalog['images']
    counts = {}
    for name, expected in [(text_name, len(parts)), (image_name, len(images))]:
        actual = client.query(collection_name=name, filter='', output_fields=['count(*)'])[0]['count(*)']
        if actual != expected:
            raise ValueError(f'{name}: expected {expected} records, got {actual}')
        counts[name] = actual
    iterator = client.query_iterator(collection_name=image_name, batch_size=1000,
                                     output_fields=['id', 'item_id', 'item_code', 'image_id'])
    seen = set()
    try:
        while True:
            rows = iterator.next()
            if not rows:
                break
            for row in rows:
                index = int(row['id']) - 1
                image = images[index]
                part = parts[image['part_index']]
                assert row['item_id'] == int(part['item_id'])
                assert row['item_code'] == part['item_code']
                assert row['image_id'] == int(image['image_id'])
                seen.add(index)
    finally:
        iterator.close()
    assert len(seen) == len(images)

    checks = []
    for index in [0, len(images) // 2, len(images) - 1]:
        vector = image_vectors[index]
        results = client.search(collection_name=image_name, data=[vector.tolist()],
                                anns_field='image_vector', limit=20, group_by_field='item_id',
                                search_params={'metric_type': 'COSINE', 'params': {}},
                                output_fields=['item_id', 'item_code'])[0]
        scores = image_vectors @ vector
        maximums = np.full(len(parts), -np.inf, dtype=np.float32)
        np.maximum.at(maximums, [image['part_index'] for image in images], scores)
        assert len(results) == 20
        assert len({row['entity']['item_code'] for row in results}) == 20
        by_code = {p['item_code']: i for i, p in enumerate(parts)}
        for hit in results:
            assert abs(hit['distance'] - maximums[by_code[hit['entity']['item_code']]]) < 1e-4
        assert min(hit['distance'] for hit in results) >= sorted(maximums, reverse=True)[19] - 1e-4
        checks.append({'gallery_row': index, 'distinct_parts': 20, 'max_scores_match': True})
    text_rows = client.query(collection_name=text_name, filter='history_id == 0',
                             output_fields=['item_id', 'item_code', 'description', 'inquiry_id', 'document_key', 'text_vector'])
    assert len(text_rows) == len(parts)
    expected_text = {part['item_code']: part for part in parts}
    vectors_by_code = {part['item_code']: vector for part, vector in zip(parts, text_vectors)}
    for row in text_rows:
        part = expected_text[row['item_code']]
        assert row['item_id'] == int(part['item_id'])
        assert row['description'] == part['item_name'] and row['inquiry_id'] == ''
        assert row['document_key'] == 'catalog:' + part['item_code']
        assert np.allclose(row['text_vector'], vectors_by_code[row['item_code']], atol=1e-6)
    hits = client.search(collection_name=text_name, data=[text_vectors[0].tolist()],
                         anns_field='text_vector', limit=20, output_fields=['item_code'],
                         search_params={'metric_type': 'COSINE', 'params': {}})[0]
    assert len(hits) == 20 and hits[0]['distance'] > 0.999
    return {'status': 'verified', 'counts': counts, 'image_checks': checks,
            'text_documents_checked': len(text_rows), 'text_smoke_top1_score': hits[0]['distance']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=DEFAULT_INDEX)
    parser.add_argument('--uri', default='http://localhost:19530')
    parser.add_argument('--text-collection', default=TEXT_COLLECTION)
    parser.add_argument('--image-collection', default=IMAGE_COLLECTION)
    parser.add_argument('--encode-siglip-names', action='store_true')
    parser.add_argument('--encode-service-names', action='store_true')
    parser.add_argument('--model-service-url', default='http://localhost:5555')
    parser.add_argument('--text-vectors', default='text_vectors.npy')
    parser.add_argument('--text-only', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.encode_siglip_names:
        encode_siglip_names(args.index)
        return
    if args.encode_service_names:
        encode_service_names(args.index, args.model_service_url, args.index / args.text_vectors)
        return
    from pymilvus import MilvusClient

    catalog = read_json(args.index / 'catalog.json')
    state = read_json(args.index / 'state.json')
    if state['status'] != 'verified':
        raise ValueError('Local index must pass verification before import')
    text_vectors = np.load(args.index / args.text_vectors)
    image_vectors = np.load(args.index / 'image_vectors.npy')
    assert text_vectors.shape == (len(catalog['parts']), 1024)
    assert image_vectors.shape == (len(catalog['images']), 1152)
    for vectors in [text_vectors, image_vectors]:
        assert np.isfinite(vectors).all()
        assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4)
    client = MilvusClient(uri=args.uri)
    if not args.verify_only:
        for name in ([args.text_collection] if args.text_only else [args.text_collection, args.image_collection]):
            if client.has_collection(collection_name=name):
                raise ValueError(f'Refusing to overwrite existing collection: {name}')
        names = np.load(args.index / 'siglip_name_vectors.npy')
        assert names.shape == (len(catalog['parts']), 1152)
        assert np.isfinite(names).all() and np.allclose(np.linalg.norm(names, axis=1), 1, atol=1e-4)
        create_collections(client, args.text_collection, args.image_collection, text_only=args.text_only)
        now = datetime.now(timezone.utc).isoformat()
        insert_batches(client, args.text_collection, text_records(catalog['parts'], text_vectors, now))
        if not args.text_only:
            insert_batches(client, args.image_collection, image_records(catalog, image_vectors, names, now))
    for name in [args.text_collection, args.image_collection]:
        client.load_collection(collection_name=name)
    report = verify_import(client, catalog, text_vectors, image_vectors, args.text_collection, args.image_collection)
    report['verified_at'] = datetime.now(timezone.utc).isoformat()
    report['text_vectors_file'] = args.text_vectors
    save_json(args.index / 'milvus_import_report.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
