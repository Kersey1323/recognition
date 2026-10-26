"""Build and serve a visual review of inquiries found by only one image model."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
import uvicorn


def read(path):
    return json.loads(path.read_text())


def hit(sample):
    return sample['rank'] is not None and sample['rank'] <= 20


def select_cases(rows, count, seed):
    shuffled = rows.copy()
    random.Random(seed).shuffle(shuffled)
    selected, seen = [], set()
    # 人工看图时先覆盖不同配件，避免同一编码的多条询码挤满审核页面。
    for row in shuffled:
        if row['expected_code'] not in seen:
            selected.append(row)
            seen.add(row['expected_code'])
        if len(selected) == count:
            break
    return sorted(selected, key=lambda s: s['inquiry_num'])


def build(args):
    report = read(args.report)
    baseline = read(Path(report['baseline']))
    catalog = read(Path(report['index']) / 'catalog.json')
    metadata = {s['inquiry_id']: s for s in read(args.manifest)}
    siglip = {s['inquiry_id']: s for s in baseline['samples']}
    groups = {
        'dino': [s for s in report['samples'] if hit(s) and not hit(siglip[s['inquiry_id']])],
        'siglip': [s for s in report['samples'] if not hit(s) and hit(siglip[s['inquiry_id']])],
    }
    dataset = Path(catalog['dataset']).resolve()
    images, private_paths = {}, {}
    gallery_by_path = {im['local_path']: im for im in catalog['images']}
    gallery_by_code = defaultdict(list)
    for im in catalog['images']:
        gallery_by_code[im['item_code']].append(im)

    def add_image(path, source):
        path = path.resolve()
        if not path.is_file() or not path.is_relative_to(dataset):
            raise ValueError('Missing or invalid review image: ' + str(path))
        key = hashlib.sha256(str(path).encode()).hexdigest()[:24]
        if key not in images:
            with Image.open(path) as image:
                width, height = image.size
            images[key] = {'filename': path.name, 'source': source,
                           'width': width, 'height': height}
            private_paths[key] = str(path)
        return key

    def gallery_image(info):
        return add_image(dataset / info['local_path'], info['source_type'])

    def dino_candidates(sample):
        return [{'rank': i, 'item_code': item['item_code'], 'item_name': item['item_name'],
                 'score': item['rate'], 'images': [gallery_image(item['matched_image'])],
                 'query_indexes': [sample['query_images'].index(item['matched_query_image'])],
                 'image_query_indexes': [[sample['query_images'].index(item['matched_query_image'])]]}
                for i, item in enumerate(sample['returned_items'][:20], 1)]

    def siglip_candidates(sample):
        result = []
        for i, item in enumerate(sample['returned_items'][:20], 1):
            matches = item.get('matched_images') or [{'image_url': item['image_url']}]
            matches = sorted(matches, key=lambda im: -float(im.get('rate', item['rate'])))
            keys, query_indexes, associations = [], [], []
            for im in matches:
                info = gallery_by_path['images/' + im['image_url']]
                key = gallery_image(info)
                if key not in keys:
                    keys.append(key)
                    associations.append(im.get('matched_query_indexes') or [])
                query_indexes.extend(im.get('matched_query_indexes') or [])
            result.append({'rank': i, 'item_code': item['item_code'],
                           'item_name': item['item_name'], 'score': item['rate'],
                           'images': keys, 'image_query_indexes': associations,
                           'query_indexes': sorted(set(query_indexes))})
        return result

    samples = []
    for group, rows in groups.items():
        selected = select_cases(rows, args.per_group, args.seed)
        if len(selected) != args.per_group:
            raise ValueError('Not enough distinct parts in review group: ' + group)
        for sample in selected:
            old = siglip[sample['inquiry_id']]
            assert hit(sample) != hit(old)
            source = metadata[sample['inquiry_id']]
            inputs = source['input']
            samples.append({
                'inquiry_id': sample['inquiry_id'], 'inquiry_num': sample['inquiry_num'],
                'group': group, 'expected_code': sample['expected_code'],
                'expected_name': sample['expected_name'],
                'description': inputs.get('inquiry_item_name') or '',
                'vehicle': inputs.get('vehicle_batch') or inputs.get('vehicle') or '',
                'remark': inputs.get('remark') or '',
                'component': inputs.get('subordinate_component') or '',
                'inquiry_time': source['metadata'].get('inquiry_time') or '',
                'query_images': [add_image(Path(p), 'QUERY') for p in sample['query_images']],
                # 正确配件参考图独立于实际候选展示，不将人工答案混入检索结果。
                'reference_images': [gallery_image(im) for im in gallery_by_code[sample['expected_code']]],
                'dino': {'rank': sample['rank'], 'full_rank': sample['full_gallery_rank'],
                         'candidates': dino_candidates(sample)},
                'siglip': {'rank': old['rank'], 'full_rank': None,
                           'candidates': siglip_candidates(old)},
            })
    data = {'samples': samples, 'images': images,
            'available': {key: len(rows) for key, rows in groups.items()},
            'selected_per_group': args.per_group, 'total_inquiries': len(report['samples']),
            'gallery_parts': len(catalog['parts']), 'gallery_images': len(catalog['images']),
            'selection': '每组打乱顺序后选取不同正确编码，固定随机种子 ' + str(args.seed)}
    template = Path(__file__).with_name('image_model_comparison.html').read_text()
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    args.output.mkdir(parents=True, exist_ok=True)
    page = args.output / 'index.html'
    page.write_text(template.replace('__REVIEW_DATA__', payload))
    (args.output / 'selection.json').write_text(json.dumps({
        'report': str(args.report), 'selection': data['selection'],
        'available': data['available'], 'samples': [
            {key: s[key] for key in ('inquiry_id', 'inquiry_num', 'group', 'expected_code')}
            for s in samples]}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'page': str(page), 'samples': len(samples), 'images': len(images),
                      'available': data['available']}, ensure_ascii=False), flush=True)
    return page, private_paths


def create_app(page, paths, output):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    thumbnails = output / 'thumbnails'
    thumbnails.mkdir(parents=True, exist_ok=True)

    @app.get('/')
    def index():
        return FileResponse(page, media_type='text/html', headers={'Cache-Control': 'no-cache'})

    @app.get('/images/{key}')
    def image(key: str, original: bool = False):
        # 网页仅能访问本次审核涉及的图片，不开放任意本地路径或目录浏览。
        if key not in paths:
            raise HTTPException(404, 'Image not included in this review')
        path = Path(paths[key])
        if not original:
            path = thumbnails / (key + '.jpg')
            if not path.exists():
                with Image.open(paths[key]) as source:
                    preview = ImageOps.exif_transpose(source).convert('RGB')
                    preview.thumbnail((720, 540), Image.Resampling.LANCZOS)
                    # 同一图片可能同时显示在参考图库和候选列表，避免读到写入一半的缩略图。
                    import tempfile
                    with tempfile.NamedTemporaryFile(dir=thumbnails, suffix='.jpg', delete=False) as temp:
                        preview.save(temp, format='JPEG', quality=83, optimize=True)
                        temporary = Path(temp.name)
                    temporary.replace(path)
        return FileResponse(path, headers={'Cache-Control': 'public, max-age=86400'})

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--per-group', type=int, default=25)
    parser.add_argument('--seed', type=int, default=20261023)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=65435)
    args = parser.parse_args()
    if not 1 <= args.per_group <= 25:
        parser.error('per-group must be between 1 and 25 (at most 50 inquiries)')
    page, paths = build(args)
    uvicorn.run(create_app(page, paths, args.output), host=args.host, port=args.port)


if __name__ == '__main__':
    main()
