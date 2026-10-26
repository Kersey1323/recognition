"""Download confirmed inquiry queries for an existing collected-parts gallery."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import time

from dotenv import dotenv_values
import requests


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--max-images', type=int, default=10)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('snapshot_helpers', args.previous / 'sync_dataset.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.ROOT = args.dataset.resolve()
    cfg = dotenv_values('.env')
    response = requests.post(cfg['SGO_API_URL'].rstrip('/') + '/uc/sfsso/authByAccount',
        params={'tenantId': cfg['SGO_TENANT_ID']},
        json={key: cfg['SGO_' + key.upper()] for key in ('username', 'password', 'encryption')}, timeout=20)
    response.raise_for_status()
    os.environ['SGO_SNAPSHOT_TOKEN'] = response.json()['token']
    items = read(args.dataset / 'parts_snapshot.json')['items']
    by_code = {str(item['item_code']): item for item in items}
    linked_numbers = {n for item in items for n in item.get('inquiry_nums') or []}
    pending = [item for item in items if item.get('inquiry_nums')]
    print(json.dumps({'phase': 'inquiry_snapshot', 'parts_with_inquiries': len(pending),
                      'linked_inquiry_numbers': len(linked_numbers)}), flush=True)

    def cached_inquiries(path, payload):
        cached = read(path) if path.exists() else None
        if isinstance(cached, dict) and isinstance(cached.get('items'), list) and 'total' in cached:
            return cached
        # 线上业务错误也可能返回 HTTP 200；缺少列表结构时必须重试，不能当作零条记录。
        if cached is not None:
            archive = path.parent / 'invalid_responses' / path.name
            if not archive.exists():
                helper.save_json(archive, cached)
        for attempt in range(7):
            data = helper.api('/sgo/sgo/inquery/list', payload)
            if isinstance(data.get('items'), list) and 'total' in data:
                helper.save_json(path, data)
                return data
            # 失败连接可能固定落到报错的服务进程，重新建立连接后再读取同一份数据。
            helper.session().close()
            del helper.LOCAL.session
            if attempt < 6:
                time.sleep(1)
        raise RuntimeError('Online inquiry API returned a business error instead of a list')

    def fetch(item):
        expected = set(item['inquiry_nums'])
        records = []
        page = 1
        while True:
            data = cached_inquiries(args.dataset / 'metadata' / 'inquiry_search' /
                f"{item['id']}_code_{page}.json",
                {'page': page, 'per_page': 100, 'pageSize': 100,
                 'query': item['item_code'], 'has_indexed': 0})
            batch = data.get('items', [])
            records.extend(batch)
            if not batch or page * 100 >= int(data.get('total', 0)):
                break
            page += 1
        found = {r.get('inquiry_num') for r in records}
        for number in sorted(expected - found):
            data = cached_inquiries(args.dataset / 'metadata' / 'inquiry_search' /
                f"{item['id']}_number_{number}.json",
                {'page': 1, 'per_page': 100, 'pageSize': 100, 'query': number, 'has_indexed': 0})
            records.extend(data.get('items', []))
        return [row for row in records if row.get('inquiry_num') in expected]

    records, failures = {}, []
    for pass_no in range(1, 5):
        failures, retry_items = [], []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fetch, item): item for item in pending}
            for i, future in enumerate(as_completed(futures), 1):
                item = futures[future]
                try:
                    for row in future.result():
                        records[str(row['id'])] = row
                except Exception as exc:
                    failures.append({'item_code': item['item_code'], 'error_type': type(exc).__name__})
                    retry_items.append(item)
                if i % 20 == 0 or i == len(pending):
                    print(json.dumps({'phase': 'inquiry_metadata', 'pass': pass_no, 'completed_parts': i,
                        'total_parts': len(pending), 'unique_inquiries': len(records),
                        'failed_parts': len(failures)}), flush=True)
        if not retry_items:
            break
        pending = retry_items
    helper.save_json(args.dataset / 'inquiry_records_full.json', list(records.values()))
    helper.save_json(args.dataset / 'inquiry_metadata_failures.json', failures)
    if failures:
        raise RuntimeError(f'{len(failures)} parts could not be queried; resume after checking connection')
    eligible, excluded, paths = [], [], set()
    for row in sorted(records.values(), key=lambda r: str(r['id'])):
        code = str(row.get('return_item_code') or '').strip()
        if code not in by_code:
            excluded.append({'inquiry_id': str(row['id']), 'reason': 'returned_code_not_in_gallery'})
            continue
        refs = []
        # 与前 50 条实验一致，先取详情图，再取铭牌图，每条最多使用 10 张。
        for field, role in [('detailed_photos_urls', 'detail'), ('nameplate_photos_urls', 'nameplate')]:
            for value in row.get(field) or []:
                try:
                    path = helper.asset_path(value)
                except ValueError:
                    continue
                if path not in {ref['remote_path'] for ref in refs}:
                    refs.append({'remote_path': path, 'role': role})
        refs = refs[:args.max_images]
        if not refs:
            excluded.append({'inquiry_id': str(row['id']), 'reason': 'no_query_image_references'})
            continue
        eligible.append((row, refs))
        paths.update(r['remote_path'] for r in refs)
    previous_downloads = {d['object_path']: d for d in read(args.previous / 'downloads.json')
                          if d['status'] == 'ok'}
    gallery_downloads = {d['object_path']: d for d in read(args.dataset / 'downloads.json')
                         if d['status'] == 'ok'}
    progress = args.dataset / 'inquiry_download_progress.jsonl'
    completed = {}
    if progress.exists():
        for line in progress.read_text().splitlines():
            row = json.loads(line)
            if row['status'] == 'ok':
                completed[row['object_path']] = row

    def download(path):
        target = args.dataset / 'images' / path
        old = args.previous / 'images' / path
        cached = completed.get(path) or gallery_downloads.get(path)
        if cached and target.is_file() and target.stat().st_size == cached['bytes']:
            return {**cached, 'reused': True}
        cached = previous_downloads.get(path)
        if cached and old.is_file() and old.stat().st_size == cached['bytes']:
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.link(old, target)
            if target.stat().st_ino == old.stat().st_ino:
                return {**cached, 'reused': True}
        return {**helper.download(path), 'reused': False}

    downloads = []
    with progress.open('a') as log, ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(download, path) for path in sorted(paths)]
        for i, future in enumerate(as_completed(futures), 1):
            row = future.result()
            downloads.append(row)
            log.write(json.dumps(row, ensure_ascii=False) + '\n')
            log.flush()
            if i % 100 == 0 or i == len(paths):
                print(json.dumps({'phase': 'inquiry_images', 'completed': i, 'total': len(paths),
                    'failed': sum(d['status'] != 'ok' for d in downloads),
                    'reused': sum(d['reused'] for d in downloads)}), flush=True)
    helper.save_json(args.dataset / 'inquiry_downloads.json', downloads)
    lookup = {d['object_path']: d for d in downloads}
    gallery_hashes = {d['sha256'] for d in gallery_downloads.values()}
    manifest = []
    for row, refs in eligible:
        images = []
        for ref in refs:
            downloaded = lookup[ref['remote_path']]
            if downloaded['status'] == 'ok':
                images.append({**ref, 'path': str((args.dataset / downloaded['local_path']).resolve()),
                    'sha256': downloaded['sha256'], 'bytes': downloaded['bytes'],
                    'exists_in_gallery': downloaded['sha256'] in gallery_hashes})
        if not images:
            excluded.append({'inquiry_id': str(row['id']), 'reason': 'all_query_downloads_failed'})
            continue
        part = by_code[str(row['return_item_code']).strip()]
        manifest.append({'inquiry_id': str(row['id']), 'partition': 'test',
            'input': {'inquiry_item_name': row.get('item_name') or '',
                'remark': row.get('remark') or '', 'vehicle': row.get('vehicle'),
                'train_no': row.get('train_no'), 'car_num': row.get('car_num'),
                'subordinate_component': row.get('subordinate_component')},
            'metadata': {'inquiry_num': row['inquiry_num'], 'inquiry_time': row.get('submission_date'),
                'item_id': str(part['id']), 'return_item_code': str(row['return_item_code']).strip(),
                'return_item_name': row.get('return_item_name') or part['item_name'],
                'gallery_overlap': any(im['exists_in_gallery'] for im in images)},
            'images': images})
    helper.save_json(args.dataset / 'inquiry_manifest_full.json', manifest)
    helper.save_json(args.dataset / 'inquiry_excluded.json', excluded)
    summary = {'created_at': datetime.now(timezone.utc).isoformat(), 'gallery_parts': len(items),
        'linked_inquiry_numbers': len(linked_numbers), 'resolved_unique_records': len(records),
        'unresolved_inquiry_numbers': sorted(linked_numbers - {r['inquiry_num'] for r in records.values()}),
        'eligible_before_download': len(eligible), 'valid_queries': len(manifest),
        'query_parts': len({m['metadata']['return_item_code'] for m in manifest}),
        'query_image_references': sum(len(m['images']) for m in manifest),
        'unique_query_images': len(paths), 'image_download_failures': sum(d['status'] != 'ok' for d in downloads),
        'queries_with_exact_gallery_overlap': sum(m['metadata']['gallery_overlap'] for m in manifest),
        'max_images': args.max_images, 'gallery_modified': False}
    helper.save_json(args.dataset / 'inquiry_full_summary.json', summary)
    print(json.dumps({'phase': 'complete', **summary}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
