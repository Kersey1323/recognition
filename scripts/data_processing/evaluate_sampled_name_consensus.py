"""Select one sampled name by occurrence-weighted BGE cosine consensus."""

import argparse
import asyncio
import json
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / '.env')
from csrcqsf.infra.external.model_client import ModelServiceClient
from evaluate_unique_name_vectors import normalize, unit


def select_consensus(vectors, names):
    # 每次采样都是一票，重复名称不去重；仅排除每个位置与自身的相似度。
    pairwise = np.clip(unit(vectors) @ unit(vectors).T, -1, 1)
    scores = (pairwise.sum(axis=1) - pairwise.diagonal()) / (len(names) - 1)
    # 浮点误差范围内同分时优先出现次数更多的名称，再按采样顺序确定。
    tied = np.flatnonzero(np.isclose(scores, scores.max(), rtol=0, atol=1e-7))
    winner = max(tied, key=lambda i: (names.count(names[i]), -int(i)))
    return int(winner), scores.tolist(), pairwise.tolist()


async def run(args):
    source = json.loads(args.input.read_text())
    client = ModelServiceClient()
    results = []
    for row in source['samples']:
        names = row['sampled_names']
        assert len(names) == 5
        winner, scores, matrix = select_consensus(await client.text_embeddings(names), names)
        selected = names[winner]
        # 名称及语料库不变，复用上一轮该名称的真实Top20结果，避免重复检索。
        items = row['per_sampled_query'][selected]
        hits = {kind: {str(k): any(
            normalize(item['name']) == normalize(row['expected_name']) if kind == 'name'
            else row['expected_code'] in item['codes'] for item in items[:k])
            for k in (1,5,10,20)} for kind in ('name', 'code')}
        results.append(dict(inquiry_id=row['inquiry_id'], inquiry_num=row['inquiry_num'],
                            expected_name=row['expected_name'], expected_code=row['expected_code'],
                            sampled_names=names, selected_name=selected, selected_index=winner,
                            mean_similarity=scores, pairwise_similarity=matrix,
                            returned_names=items, hits=hits))
    metrics = {kind: {f'recall@{k}': sum(r['hits'][kind][str(k)] for r in results)/len(results)
                     for k in (1,5,10,20)} for kind in ('name','code')}
    report = dict(source_report=str(args.input), corpus_sha256=source['corpus_sha256'],
                  method='Mean cosine to other four sampling occurrences; duplicates retained. Tie: occurrence count, then sampling order.',
                  evaluated=len(results), metrics=metrics, baseline_metrics=source['metrics'], samples=results)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    def esc(value):
        return str(value).replace('|', '\\|').replace('\n', '<br>')
    lines = ['# 五次采样名称一致性选择', '',
             '重复名称按采样次数计入。得分为与其余四个位置的平均余弦相似度，排除自身。',
             '编码指标是名称分组展开后的覆盖率，不是编码TopK。', '',
             '| 询码单 | 人工名称 | 五次采样 | 平均相似度 | 选中名称 | 名称Top20命中 |',
             '| --- | --- | --- | --- | --- | --- |']
    for r in results:
        lines.append('| ' + ' | '.join(map(esc, [r['inquiry_num'],r['expected_name'],
            ' / '.join(r['sampled_names']), ' / '.join(f'{v:.6f}' for v in r['mean_similarity']),
            r['selected_name'],r['hits']['name']['20']])) + ' |')
    args.output.with_suffix('.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    asyncio.run(run(p.parse_args()))
