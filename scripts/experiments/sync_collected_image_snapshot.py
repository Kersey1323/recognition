"""Download a dated, read-only snapshot of collected online gallery images."""

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path

from dotenv import dotenv_values
import requests
from sqlalchemy import bindparam, text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous-index', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('snapshot_helpers', args.previous / 'sync_dataset.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.ROOT = args.output.resolve()
    helper.ROOT.mkdir(parents=True, exist_ok=True)
    cfg = dotenv_values('.env')
    auth = requests.post(
        (cfg.get('SGO_API_URL') or 'https://sgo.4dlp.com.cn') + '/uc/sfsso/authByAccount',
        params={'tenantId': cfg.get('SGO_TENANT_ID') or '1463844437338755072'},
        json={key: cfg.get('SGO_' + key.upper()) or default for key, default in {
            'username': 'wrps', 'password': 'REMOVED_CREDENTIAL',
            'encryption': 'REMOVED_CREDENTIAL',
        }.items()}, timeout=20,
    )
    auth.raise_for_status()
    os.environ['SGO_SNAPSHOT_TOKEN'] = auth.json()['token']
    snapshot_path = helper.ROOT / 'parts_snapshot.json'
    if snapshot_path.exists():
        items = json.loads(snapshot_path.read_text())['items']
    else:
        # 采集人员仍在更新列表；分页出现重复时重新取快照，不把重复行当成新配件。
        for attempt in range(3):
            items, page = [], 1
            while True:
                data = helper.api('/railway/parts/list_items', {
                    'page': page, 'pageSize': 100, 'has_images': 1,
                    'has_source_video': 1, 'has_inquery_code': 0, 'only_has_index': 0,
                })
                items.extend(data['items'])
                if not data['items'] or len(items) >= data['total']:
                    break
                page += 1
            if len(items) == len({str(i['id']) for i in items}) == data['total']:
                break
        else:
            raise RuntimeError('Online pagination changed repeatedly; no stable snapshot')
        helper.save_json(snapshot_path, {
            'created_at': datetime.now(timezone.utc).isoformat(), 'source': helper.BASE,
            'filters': {'has_images': 1, 'has_source_video': 1}, 'items': items,
        })
    print(json.dumps({'phase': 'snapshot', 'parts': len(items)}), flush=True)

    def fetch(item):
        response = helper.cached_api(
            helper.ROOT / 'metadata' / 'images' / (str(item['id']) + '.json'),
            '/railway/parts/list_item_images', {'item_id': str(item['id'])},
        )
        return item, response['items']

    parts = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, item) for item in items]
        for index, future in enumerate(as_completed(futures), 1):
            item, image_rows = future.result()
            gallery = [row for row in image_rows if
                       row.get('image_source_type') in {'BASEINFO', 'CREATEBYSELF'}
                       or 'manual-upload/' in str(row.get('image_url'))]
            parts.append((item, gallery))
            if index % 20 == 0 or index == len(items):
                print(json.dumps({'phase': 'metadata', 'completed': index,
                                  'total': len(items)}), flush=True)
    paths = sorted({helper.asset_path(im['image_url']) for _, rows in parts for im in rows})
    print(json.dumps({'phase': 'downloads', 'unique_gallery_images': len(paths)}), flush=True)
    previous_images = {im['local_path']: im for im in json.loads(
        (args.previous_index / 'catalog.json').read_text())['images']}
    previous_downloads = {d['local_path']: d for d in json.loads(
        (args.previous / 'downloads.json').read_text()) if d['status'] == 'ok'}
    progress_path = helper.ROOT / 'download_progress.jsonl'
    completed = {}
    if progress_path.exists():
        for line in progress_path.read_text().splitlines():
            try:
                row = json.loads(line)
                if row['status'] == 'ok':
                    completed[row['object_path']] = row
            except (ValueError, KeyError):
                continue

    def download(path):
        target = helper.ROOT / 'images' / path
        previous = args.previous / 'images' / path
        relative = str(Path('images') / path)
        cached = completed.get(path)
        if cached and target.is_file() and target.stat().st_size == cached.get('bytes'):
            return {**cached, 'resumed_existing_file': True}
        reused = False
        if previous.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(previous, target)
            reused = True
        old = previous_images.get(relative)
        info = previous_downloads.get(relative)
        # 已核验的旧图片用硬链接复用；大小和修改时间均未变化时直接沿用原摘要。
        if old and info and target.is_file() and previous.is_file():
            stat = previous.stat()
            if (stat.st_size == info['bytes'] and stat.st_mtime_ns == old['mtime_ns']
                    and target.stat().st_ino == stat.st_ino):
                return {**info, 'reused_previous_file': True}
        return {**helper.download(path), 'reused_previous_file': reused}

    downloads = []
    with (helper.ROOT / 'download_progress.jsonl').open('a') as log:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(download, path) for path in paths]
            for index, future in enumerate(as_completed(futures), 1):
                row = future.result()
                downloads.append(row)
                log.write(json.dumps(row, ensure_ascii=False) + '\n')
                log.flush()
                if index % 100 == 0 or index == len(paths):
                    print(json.dumps({'phase': 'downloads', 'completed': index,
                        'total': len(paths), 'failed': sum(d['status'] != 'ok' for d in downloads),
                        'reused': sum(d['reused_previous_file'] for d in downloads),
                        'gallery_gib': round(sum(d.get('bytes', 0) for d in downloads) / 1024**3, 3),
                    }), flush=True)
    helper.save_json(helper.ROOT / 'downloads.json', downloads)
    lookup = {d['object_path']: d for d in downloads}
    failures = [d for d in downloads if d['status'] != 'ok']
    helper.save_json(helper.ROOT / 'download_failures.json', failures)

    async def read_local_metadata():
        from csrcqsf.infra.db.main_db import SessionLocal, engine
        async with SessionLocal() as session:
            statement = text('SELECT id,item_code,item_name,vehicle_batch FROM item_info '
                             'WHERE item_code IN :codes').bindparams(bindparam('codes', expanding=True))
            rows = (await session.execute(statement, {'codes': [i['item_code'] for i in items]})).all()
        await engine.dispose()
        return {r.item_code: r for r in rows}

    local = asyncio.run(read_local_metadata())
    manifest, metadata = [], []
    for item, rows in sorted(parts, key=lambda pair: str(pair[0]['id'])):
        gallery = []
        for im in rows:
            d = lookup[helper.asset_path(im['image_url'])]
            gallery.append({**im, 'local_path': d.get('local_path') if d['status'] == 'ok' else None,
                            'sha256': d.get('sha256'), 'download_status': d['status'],
                            'image_source_type': ('CREATEBYSELF' if 'manual-upload/' in str(im['image_url'])
                                                  else im['image_source_type'])})
        manifest.append({'item_id': str(item['id']), 'item_code': item['item_code'],
            'item_name': item['item_name'], 'vehicle_batch': item.get('vehicle_batch'),
            'inquiry_nums': item.get('inquiry_nums') or [], 'gallery_images': gallery})
        row = local.get(item['item_code'])
        metadata.append({'item_code': item['item_code'],
            'item_name': row.item_name if row else item['item_name'],
            'online_item_id': str(item['id']), 'local_item_id': str(row.id) if row else None,
            'present_in_business_db': row is not None,
            'vehicle_batch': item.get('vehicle_batch'),
            'vehicle_batches': [s for s in str(item.get('vehicle_batch') or '').split(',') if s]})
    helper.save_json(helper.ROOT / 'manifest.json', manifest)
    helper.save_json(helper.ROOT / 'local_business_metadata.json', metadata)
    old_manifest = json.loads((args.previous / 'manifest.json').read_text())
    old_codes = {p['item_code'] for p in old_manifest}
    summary = {'snapshot_parts': len(items), 'gallery_images': len(paths),
        'downloaded_images': len(paths) - len(failures), 'image_download_failures': len(failures),
        'new_parts': len({i['item_code'] for i in items} - old_codes),
        'old_parts_no_longer_in_snapshot': sorted(old_codes - {i['item_code'] for i in items}),
        'missing_local_business_parts': sum(not m['present_in_business_db'] for m in metadata),
        'videos_downloaded': False, 'inquiry_images_indexed': 0,
        'created_at': datetime.now(timezone.utc).isoformat()}
    helper.save_json(helper.ROOT / 'summary.json', summary)
    print(json.dumps({'phase': 'complete', **summary}, ensure_ascii=False), flush=True)
    if failures:
        raise RuntimeError(f'{len(failures)} gallery images could not be downloaded; inspect download_failures.json')


if __name__ == '__main__':
    main()
