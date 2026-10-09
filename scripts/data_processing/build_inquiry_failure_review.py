"""Build a portable, image-embedded review document from existing experiments."""

import base64
import html
import io
import json
from pathlib import Path
from collections import Counter

from PIL import Image, ImageOps

ROOT = Path('/home/ubuntu/project-train/searchCode-agent/outputs')
VL = Path('/home/ubuntu/project-train/CodeQueryVL')
OUT = ROOT / 'failure_review20_20261008'


def main():
    OUT.mkdir(exist_ok=True)
    baseline = json.loads((ROOT/'retrieval_tools_grouped_1000_vl_name_context_no_images_test_100.json').read_text())['samples']
    manifest = {r['inquiry_id']: r for r in json.loads((VL/'data/inquiry_online/manifest_time_split.json').read_text())}
    sampling = {r['inquiry_id']: r for r in map(json.loads, (VL/'outputs/qwen3_vl_4b_online_visual_time_split_v2_3epoch/sampling_diversity_retrieval100x5_20261008.jsonl').read_text().splitlines())}
    pilot = {r['inquiry_id']: r for r in json.loads((ROOT/'unique_name_vector_pilot20_20261008/report.json').read_text())['samples']}
    chosen = []
    for row in baseline:
        p = pilot.get(row['inquiry_id'])
        if p and not p['hits']['sampled_five_union']['name']['20']:
            chosen.append((row, '五次检索并集仍未命中', '检查图片目标和名称映射；并集未命中不能单独证明视觉识别错误。'))
        elif p and p['hits']['sampled_five_union']['name']['20'] and not p['hits']['sampled_five_max']['name']['20']:
            chosen.append((row, '单路命中，最高相似度融合后丢失', '已有直接排序损失证据；先确认目标对应，再检查正确候选被哪些名称挤出。'))
    selected = {r['inquiry_id'] for r,_,_ in chosen}
    # 补充前20条以外的失败案例，交替选择名称已召回和名称未召回两类。
    buckets = [[], []]
    for r in baseline:
        if r['inquiry_id'] in selected or r['inquiry_id'] in pilot:
            continue
        if any(t.get('rank') is not None and t['rank'] <= 20 for t in r['tools'].values()):
            continue
        has_name = any(t.get('name_rank') is not None and t['name_rank'] <= 20 for t in r['tools'].values())
        buckets[int(has_name)].append(r)
    while len(chosen) < 20:
        before = len(chosen)
        for index, bucket in enumerate(buckets):
            if bucket and len(chosen) < 20:
                r = bucket.pop(0)
                label = '旧工具名称命中，但编码Top20未命中' if index else '旧工具名称和编码Top20均未命中'
                chosen.append((r, label, '五次名称已生成，但尚无五次名称检索结果；先审核目标、标签和生成名称。编码Top20未命中不等于候选全集没有该编码。'))
        assert len(chosen) > before, 'Not enough failed samples'
    assert len(chosen) == 20
    esc = lambda x: html.escape(str(x if x is not None else '未提供'))
    sections, records = [], []
    image_count = 0
    for number, (row, group, note) in enumerate(chosen, 1):
        iid = row['inquiry_id']; m = manifest[iid]; v = sampling[iid]; p = pilot.get(iid)
        record = dict(number=number, inquiry_id=iid, inquiry_num=m['metadata']['inquiry_num'], selection_group=group,
                      preliminary_note=note, source_input=m['input'], expected_name=row['expected_name'], expected_code=row['expected_code'],
                      sampled_names=v['runs'], greedy_name=v['greedy_name'], images=m['images'], tools=row['tools'],
                      pilot_results=p, review=dict(target='', label='', causes=[], evidence='', action='', reviewer=''))
        records.append(record)
        s = [f'<section id="case-{number}" data-id="{iid}"><h2>{number:02d} · {esc(record["inquiry_num"])}</h2>',
             f'<p class="tag">{esc(group)}</p><p><b>初步观察（待人工核实）：</b>{esc(note)}</p>',
             f'<p><b>询码ID：</b>{iid}<br><b>人工返回：</b>{esc(row["expected_name"])} · {esc(row["expected_code"])}</p>',
             '<table><tr><th>输入字段</th><th>原始内容</th></tr>']
        for key, label in [('inquiry_item_name','名称描述'),('remark','备注'),('vehicle','车型 vehicle'),('vehicle_batch','车型批次 vehicle_batch'),('train_no','车号'),('car_num','车厢'),('subordinate_component','隶属部件')]:
            s.append(f'<tr><td>{label}</td><td>{esc(m["input"].get(key))}</td></tr>')
        s += ['</table><h3>询码图片</h3><p>保留完整画面，仅缩放预览；点击图片放大。原图路径列在图片下方。超过前6张的图片不属于本次VL输入。</p><div class="images">']
        for j, im in enumerate(m['images'], 1):
            path = Path(im['path'])
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image).convert('RGB')
                image.thumbnail((1400,1400))
                buf = io.BytesIO(); image.save(buf,format='JPEG',quality=88)
            encoded = base64.b64encode(buf.getvalue()).decode()
            s.append(f'<figure><img loading="lazy" src="data:image/jpeg;base64,{encoded}" alt="{esc(record["inquiry_num"])} 图片{j}" onclick="showImage(this)"><figcaption>图片{j} · {"VL输入" if j<=6 else "额外图片"}<br><small>{esc(path)}</small></figcaption></figure>')
            image_count += 1
        s += ['</div><h3>名称生成</h3>',f'<p>原贪心名称：{esc(v["greedy_name"])}</p><ol>']
        s += [f'<li>{esc(name)}</li>' for name in v['runs']]
        s += ['</ol><h3>旧100条工具实验</h3><p>编码排名与名称排名是不同口径；以下结果不与新名称库混为一次实验。</p><table><tr><th>工具</th><th>编码排名</th><th>名称排名</th><th>返回的前5个不同名称</th></tr>']
        for tool, t in row['tools'].items():
            names = list(dict.fromkeys(x['item_name'] for x in t['returned_items']))[:5]
            s.append(f'<tr><td>{esc(tool)}</td><td>{esc(t.get("rank"))}</td><td>{esc(t.get("name_rank"))}</td><td>{esc(" / ".join(names))}</td></tr>')
        s.append('</table><p>排名“未提供”表示报告未记录命中排名，不代表所有物料中不存在该配件。</p>')
        if p:
            s.append('<h3>新名称库：五次采样检索证据</h3>')
            s.append(f'<p>五路各Top20并集命中：{p["hits"]["sampled_five_union"]["name"]["20"]}；最高相似度融合Top20命中：{p["hits"]["sampled_five_max"]["name"]["20"]}。此处均为名称命中。</p>')
            lists = {'最高相似度融合': p['variants']['sampled_five_max'], **p['per_sampled_query']}
            for name, items in lists.items():
                s.append(f'<details><summary>{esc(name)}：展开Top20名称和编码</summary><ol>')
                s += [f'<li>{esc(x["name"])} · 相似度 {x["score"]:.5f}<br><small>{esc(", ".join(x["codes"]))}</small></li>' for x in items]
                s.append('</ol></details>')
        else:
            s.append('<p class="notice">本条未执行五次采样名称库检索，请勿据此判断五次检索全部失败。</p>')
        s.append('<h3>你的审核意见</h3>')
        for key, label in [('target','图中真正要询码的是哪个部件？是否清晰可见？'),('label','人工返回名称是否与图片对应？是否存在疑问？'),('evidence','哪些生成名称合理？哪些规格没有依据？请写出具体证据。'),('action','下一步建议：裁剪目标 / 加历史案例 / 禁止猜规格 / 检查排序 / 补充业务信息'),('reviewer','审核人')]:
            s.append(f'<label>{label}<textarea data-field="{key}" rows="2"></textarea></label>')
        s.append('<fieldset><legend>可能原因（可多选，不确定可只选待确认）</legend>')
        for cause in ['看错目标','图片信息不足','不懂标准名称','猜测了无依据规格','检索或排序损失','同名编码难区分','人工标签存疑','待确认']:
            s.append(f'<label class="check"><input type="checkbox" value="{cause}" data-cause>{cause}</label>')
        s.append('</fieldset></section>'); sections.append(''.join(s))
    counts = dict(Counter(r['selection_group'] for r in records))
    head = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>询码失败样本审核 · 20条</title>
<style>body{font-family:"Noto Sans CJK SC",sans-serif;background:#f3f5f7;color:#23313e;margin:0;line-height:1.65}main{max-width:1180px;margin:auto;padding:24px}header,section{background:white;padding:26px;margin-bottom:24px;border-radius:12px}h1,h2{color:#124c64}table{border-collapse:collapse;width:100%;overflow-wrap:anywhere}td,th{border:1px solid #dce3e8;padding:9px;text-align:left}th{background:#eef4f6}.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}figure{margin:0}img{width:100%;height:320px;object-fit:contain;background:#edf0f2;cursor:zoom-in}small{overflow-wrap:anywhere;color:#526776}textarea{display:block;box-sizing:border-box;width:100%;padding:10px;margin:6px 0 16px;font:inherit}label{display:block}.check{display:inline-block;margin:6px 16px 6px 0}.tag,.notice{background:#fff4d9;padding:10px}button{background:#124c64;color:white;border:0;padding:12px 18px;border-radius:6px;cursor:pointer;margin:5px}nav a{display:inline-block;margin:4px 10px}details{padding:8px;border-bottom:1px solid #ddd}dialog{width:90vw;max-width:1500px}dialog img{height:80vh;cursor:default}@media print{button,textarea{display:none}section{break-before:page}details{display:block}}</style><main><header><h1>询码失败样本审核 · 20条</h1>
<p>审核目标：看清输入、生成与检索在哪一步出现偏差。初步观察只依据已有记录，并非已经确认的视觉归因。样本为分层挑选，不用于估计100条整体错误比例。</p>
<p>图片已内嵌，文件可离线打开。填写后点击“导出审核意见”，保留下载的JSON。浏览器本地自动保存仅为辅助，跨浏览器或清理缓存后不保证保留。</p>
<button onclick="exportReview()">导出审核意见 JSON</button><button onclick="window.print()">打印 / 保存PDF</button><span id="save-status"></span>
'''
    nav = '<p>'+esc(json.dumps(counts,ensure_ascii=False))+'</p><nav>'+''.join(f'<a href="#case-{r["number"]}">{r["number"]:02d} {esc(r["inquiry_num"])}</a>' for r in records)+'</nav></header>'
    script = '''</main><dialog id="viewer"><button onclick="this.parentElement.close()">关闭</button><img id="large"></dialog><script>
const key='inquiry-failure-review20-20261008';
function showImage(img){document.getElementById('large').src=img.src;document.getElementById('viewer').showModal()}
function collect(){return [...document.querySelectorAll('section')].map(s=>({inquiry_id:s.dataset.id,fields:Object.fromEntries([...s.querySelectorAll('textarea')].map(t=>[t.dataset.field,t.value])),causes:[...s.querySelectorAll('[data-cause]:checked')].map(c=>c.value)}))}
function save(){try{localStorage.setItem(key,JSON.stringify(collect()));document.getElementById('save-status').textContent='已暂存到本浏览器，请导出留档'}catch(e){document.getElementById('save-status').textContent='本地保存不可用，请导出留档'}}
document.addEventListener('input',save);
try{const saved=JSON.parse(localStorage.getItem(key)||'[]');for(const r of saved){const s=document.querySelector('section[data-id="'+r.inquiry_id+'"]');if(!s)continue;for(const t of s.querySelectorAll('textarea'))t.value=r.fields[t.dataset.field]||'';for(const c of s.querySelectorAll('[data-cause]'))c.checked=r.causes.includes(c.value)}}catch(e){}
function exportReview(){const blob=new Blob([JSON.stringify({source:key,exported_at:new Date().toISOString(),reviews:collect()},null,2)],{type:'application/json'});const u=URL.createObjectURL(blob);const a=document.createElement('a');a.href=u;a.download='inquiry_failure_review20_answers.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}
</script></html>'''
    (OUT/'review.html').write_text(head+nav+''.join(sections)+script)
    (OUT/'samples.json').write_text(json.dumps(dict(selection_counts=counts, notes='Stratified review selection, not representative error prevalence. No new inference or retrieval.', samples=records),ensure_ascii=False,indent=2))
    md = ['# 20条询码失败样本审核', '', '[打开带图片和填写栏的审核页面](./review.html)', '',
          '页面图片已内嵌，可离线使用。填写后请导出审核意见JSON。抽样用于诊断，不代表全部100条的原因占比。', '',
          '| 序号 | 询码单 | 人工返回名称 | 入选原因 |', '| --- | --- | --- | --- |']
    md += [f'| {r["number"]} | {r["inquiry_num"]} | {r["expected_name"]} | {r["selection_group"]} |' for r in records]
    (OUT/'README.md').write_text('\n'.join(md)+'\n')
    print(json.dumps(dict(samples=len(records),images=image_count,selection=counts,html_bytes=(OUT/'review.html').stat().st_size),ensure_ascii=False))


if __name__ == '__main__':
    main()
