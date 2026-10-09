"""Offline RRF of five sampled-name retrievals, preserving repeated votes."""

import argparse
import json
import re
import unicodedata
from pathlib import Path


def normalize(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value or '')).strip().casefold()


def fuse(sample, constant=60):
    candidates = {}
    # 五次采样分别投票，同名重复采样重复贡献；单路同一标准名称仅计一次。
    for occurrence, query in enumerate(sample['sampled_names'], 1):
        seen = set()
        for rank, item in enumerate(sample['per_sampled_query'][query][:20], 1):
            key = normalize(item['name'])
            if key in seen:
                continue
            seen.add(key)
            entry = candidates.setdefault(key, dict(name=item['name'], codes=set(), rrf_score=0.0, votes=[]))
            entry['codes'].update(item['codes'])
            entry['rrf_score'] += 1.0 / (constant + rank)
            entry['votes'].append(dict(occurrence=occurrence, query=query, rank=rank))
    # 稳定排序使同分时沿用首次出现顺序，不使用人工答案破同分。
    ordered = sorted(candidates.values(), key=lambda item: -item['rrf_score'])[:20]
    return [dict(item, codes=sorted(item['codes'])) for item in ordered]


def run(args):
    source = json.loads(args.input.read_text())
    results = []
    for sample in source['samples']:
        assert len(sample['sampled_names']) == 5
        items = fuse(sample)
        name_rank = next((i for i, item in enumerate(items, 1)
                          if normalize(item['name']) == normalize(sample['expected_name'])), None)
        code_rank = next((i for i, item in enumerate(items, 1)
                          if sample['expected_code'] in item['codes']), None)
        results.append(dict(inquiry_id=sample['inquiry_id'], inquiry_num=sample['inquiry_num'],
                            expected_name=sample['expected_name'], expected_code=sample['expected_code'],
                            sampled_names=sample['sampled_names'], returned_names=items,
                            name_rank=name_rank, code_group_rank=code_rank,
                            previous_max_hit20=sample['hits']['sampled_five_max']['name']['20'],
                            expanded_code_count=len({code for item in items for code in item['codes']})))
    metrics = {kind: {f'recall@{k}': sum(r[field] is not None and r[field] <= k for r in results)/len(results)
                     for k in (1, 5, 10, 20)}
               for kind, field in [('name', 'name_rank'), ('code', 'code_group_rank')]}
    gained = [r['inquiry_id'] for r in results if r['name_rank'] is not None and not r['previous_max_hit20']]
    lost = [r['inquiry_id'] for r in results if r['name_rank'] is None and r['previous_max_hit20']]
    report = dict(source_report=str(args.input), corpus_sha256=source['corpus_sha256'],
                  method='RRF sum(1/(60+rank)), five sampling occurrences including duplicates; each list depth 20; final 20 unique names; stable first-seen tie break.',
                  notes='Code metrics are coverage after expanding K name groups, not top-K individual codes. No new inference or retrieval.',
                  evaluated=len(results), metrics=metrics, baseline_metrics=source['metrics'],
                  gained_vs_max_at20=gained, lost_vs_max_at20=lost,
                  mean_expanded_codes=sum(r['expanded_code_count'] for r in results)/len(results), samples=results)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    lines = ['# 五次采样候选 RRF 融合', '',
             '每次采样贡献 1/(60+排名)，重复采样重复投票，每路Top20，最终保留20个标准名称。',
             '编码指标为名称组展开后的覆盖率，不是编码TopK。', '',
             '| 方式 | 名称Top1 | Top5 | Top10 | Top20 |', '| --- | --- | --- | --- | --- |']
    for label, values in [('单次VL',source['metrics']['greedy_vl']),
                          ('五次最高相似度',source['metrics']['sampled_five_max']), ('五次RRF',metrics)]:
        lines.append('| '+label+' | '+' | '.join(f'{values["name"][f"recall@{k}"]:.0%}' for k in (1,5,10,20))+' |')
    lines += ['', '| 询码单 | 人工名称 | 五次生成名称 | RRF名称排名 | 原最高分Top20命中 | RRF前五名称 |',
              '| --- | --- | --- | --- | --- | --- |']
    def esc(value):
        return str(value).replace('|','\\|').replace('\n','<br>')
    for r in results:
        lines.append('| '+' | '.join(map(esc,[r['inquiry_num'],r['expected_name'],
            ' / '.join(r['sampled_names']),r['name_rank'],r['previous_max_hit20'],
            ' / '.join(x['name'] for x in r['returned_names'][:5])]))+' |')
    args.output.with_suffix('.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('samples','baseline_metrics')},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
