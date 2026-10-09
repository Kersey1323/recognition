"""Portable human review of failed original-text retrievals; no new inference."""

import base64
import argparse
import html
import io
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path('/home/ubuntu/project-train/searchCode-agent/outputs')
OUT = ROOT / 'original_text_failure_review_20261009'


def main(tool='search_text_vectors', limit=None):
    global OUT
    contextual = tool == 'search_with_context'
    if contextual:
        OUT = ROOT / 'contextual_failure_review_20261009'
    elif limit == 40:
        OUT = ROOT / 'original_text_failure_review_first40_20261009'
    OUT.mkdir(exist_ok=True)
    source = ROOT/'retrieval_tools_grouped_1000_vl_name_context_no_images_test_100.json'
    rows = json.loads(source.read_text())['samples']
    if limit is not None:
        rows = rows[:limit]
    manifest = {r['inquiry_id']: r for r in json.loads(Path('/home/ubuntu/project-train/CodeQueryVL/data/inquiry_online/manifest_time_split.json').read_text())}
    failures = [r for r in rows if r['tools'][tool].get('rank') is None or r['tools'][tool]['rank'] > 20]
    esc = lambda v: html.escape(str(v if v is not None else '未提供'))
    records, sections, missing = [], [], []
    image_count = 0
    for number, row in enumerate(failures, 1):
        iid = row['inquiry_id']; m = manifest[iid]; t = row['tools'][tool]
        name_hit = t.get('name_rank') is not None and t['name_rank'] <= 20
        group = '名称已找到，编码前20未命中' if name_hit else '名称与编码前20均未命中'
        returned = t['returned_items']
        exact_codes = [x for x in returned if x['item_code'] == row['expected_code']]
        code_note = ('正确编码出现在完整返回结果中：'+str([x.get('rank') for x in exact_codes])) if exact_codes else '正确编码未出现在这次保存的返回列表中；不代表业务库没有该编码。'
        questions = ('名称方向已对。请确认同名配件有哪些规格、车型或安装位置差异，原始询码是否提供了这些信息。' if name_hit else '请确认原描述是否足以叫出这个配件，人工返回名称是否对应图片，以及是否存在别名或信息缺失。')
        record = dict(number=number,inquiry_id=iid,inquiry_num=row['inquiry_num'],group=group,
                      input=m['input'],expected_name=row['expected_name'],expected_code=row['expected_code'],
                      tool_result=t,images=m['images'],observation=code_note,review_questions=questions)
        records.append(record)
        s = [f'<section id="case-{number}" data-id="{iid}" data-group="{int(name_hit)}"><h2>{number:02d} · {esc(row["inquiry_num"])}</h2>',
             f'<p class="tag">{group}</p><p><b>人工返回：</b>{esc(row["expected_name"])} · {esc(row["expected_code"])}</p>',
             f'<p><b>询码ID：</b>{iid}<br><b>核查问题：</b>{questions}<br><b>已知事实：</b>{code_note}</p>',
             '<table><tr><th>询码输入</th><th>原始内容</th></tr>']
        for key,label in [('inquiry_item_name','原始名称描述（本次文本查询）'),('remark','备注'),('vehicle','车型'),('vehicle_batch','车型批次'),('train_no','车号'),('car_num','车厢'),('subordinate_component','隶属部件')]:
            s.append(f'<tr><td>{label}</td><td>{esc(m["input"].get(key))}</td></tr>')
        s += ['</table><h3>原始询码图片</h3><p>图片供人工理解目标；本页分析的文本检索没有使用这些图片及车型条件。预览未裁剪，可点击放大。</p><div class="images">']
        for j, img in enumerate(m['images'],1):
            path = Path(img['path'])
            if not path.exists():
                missing.append(str(path));s.append(f'<p>图片缺失：{esc(path)}</p>');continue
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((1400,1400))
                buf=io.BytesIO();im.save(buf,format='JPEG',quality=85)
            data=base64.b64encode(buf.getvalue()).decode()
            s.append(f'<figure><img loading="lazy" src="data:image/jpeg;base64,{data}" alt="{esc(row["inquiry_num"])} 图片{j}" onclick="showImage(this)"><figcaption>图片{j}<br><small>{esc(path)}</small></figcaption></figure>')
            image_count+=1
        s += ['</div><h3>只用原始描述的检索结果</h3>',
              f'<p>名称排名：{t.get("name_rank") if t.get("name_rank") is not None else "未命中"}；编码排名：{t.get("rank") if t.get("rank") is not None else "未命中"}。</p>',
              '<p>名称排名按名称分组计算；编码排名按展开后的列表计算，两者不同。下表展示编码前20，折叠区保留全部返回结果。</p>']
        def table(items):
            parts=['<table><tr><th>编码排名</th><th>名称组排名</th><th>召回名称</th><th>召回编码</th></tr>']
            for item in items:
                hit=item['item_code']==row['expected_code']
                parts.append(f'<tr class="{"hit" if hit else ""}"><td>{esc(item.get("rank"))}</td><td>{esc(item.get("group_rank"))}</td><td>{esc(item["item_name"])}</td><td>{esc(item["item_code"])}{"（正确编码）" if hit else ""}</td></tr>')
            return ''.join(parts)+'</table>'
        s.append(table(returned[:20]))
        if len(returned)>20:s.append(f'<details><summary>展开全部{len(returned)}条返回结果</summary>{table(returned)}</details>')
        s += ['<h3>你的审核意见</h3><fieldset><legend>可能的问题（可多选，尚未确定请选待确认）</legend>']
        for cause in ['描述与标准名称叫法不同','描述缺少关键规格或位置','检索偏离了描述','同名配件编码没找到','正确候选排序靠后','人工返回名称或图片存疑','必须结合图片才可判断','待确认']:
            s.append(f'<label class="check"><input type="checkbox" data-cause value="{cause}">{cause}</label>')
        s.append('</fieldset>')
        for key,label in [('target','图片里实际询问哪个部件？'),('label','人工返回名称和编码是否可信？'),('description','原始描述是否合理？你会用什么名称查询？'),('evidence','失败原因与依据（不确定可写待确认）'),('next_step','还需要什么信息，或建议怎么改？'),('reviewer','审核人')]:
            s.append(f'<label>{label}<textarea rows="2" data-field="{key}"></textarea></label>')
        s.append('</section>');sections.append(''.join(s))
    counts=dict(Counter(r['group'] for r in records))
    header='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>原始描述检索失败审核</title><style>
body{font-family:"Noto Sans CJK SC",sans-serif;background:#f1f4f5;color:#243642;line-height:1.7;margin:0}main{max-width:1160px;margin:auto;padding:24px}header,section{background:white;padding:24px;margin-bottom:24px;border-radius:10px}h1,h2{color:#15556a}table{border-collapse:collapse;width:100%;overflow-wrap:anywhere}th,td{border:1px solid #d6e0e5;padding:8px;text-align:left}th{background:#edf3f6}.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px}figure{margin:0}img{width:100%;height:320px;object-fit:contain;background:#eef1f2;cursor:zoom-in}small{overflow-wrap:anywhere;color:#526773}.tag{background:#fff2d5;padding:10px}.hit{background:#d8f4e6}textarea{display:block;width:100%;box-sizing:border-box;font:inherit;margin:6px 0 14px;padding:10px}label{display:block}.check{display:inline-block;margin:6px 12px}button,select{padding:10px;margin:5px;font:inherit}button{background:#15556a;color:white;border:0;border-radius:5px;cursor:pointer}nav a{display:inline-block;padding:4px 8px}details{margin:15px 0}dialog{width:90vw;max-width:1500px}dialog img{height:80vh;cursor:default}[hidden]{display:none!important}@media print{button,select{display:none}section{break-before:page}}</style><main><header><h1>原始描述检索失败审核</h1>
<p>范围：原100条报告中，只看 search_text_vectors，即原始名称描述的全局文本检索。未重新调用模型、Agent或数据库。本页不混入VL生成和其他检索方式。</p>
<p>图片已内嵌，可离线使用。初步问题是审核提示，不是已确认结论。填写后点击“导出审核意见”，浏览器暂存不能替代导出备份。</p>
<button onclick="exportReview()">导出审核意见 JSON</button><button onclick="window.print()">打印 / 保存PDF</button><select id="filter" onchange="filterCases()"><option value="all">全部失败记录</option><option value="1">名称已找到，编码未命中</option><option value="0">名称和编码均未命中</option></select><span id="save-status"></span>'''
    nav=f'<p>100条中编码Top20命中{len(rows)-len(failures)}条，未命中{len(failures)}条。分类：{esc(json.dumps(counts,ensure_ascii=False))}。</p><nav>'+''.join(f'<a data-group="{int(r["group"].startswith("名称已找到"))}" href="#case-{r["number"]}">{r["number"]:02d} {esc(r["inquiry_num"])}</a>' for r in records)+'</nav></header>'
    js='''</main><dialog id="viewer"><button onclick="this.parentElement.close()">关闭</button><img id="large"></dialog><script>
const key='original-text-failure-review-20261009';function showImage(img){document.getElementById('large').src=img.src;document.getElementById('viewer').showModal()}
function filterCases(){const f=document.getElementById('filter').value;for(const e of document.querySelectorAll('section,nav a'))e.hidden=f!=='all'&&e.dataset.group!==f}
function collect(){return [...document.querySelectorAll('section')].map(s=>({inquiry_id:s.dataset.id,fields:Object.fromEntries([...s.querySelectorAll('textarea')].map(t=>[t.dataset.field,t.value])),causes:[...s.querySelectorAll('[data-cause]:checked')].map(c=>c.value)}))}
document.addEventListener('input',()=>{try{localStorage.setItem(key,JSON.stringify(collect()));document.getElementById('save-status').textContent='已暂存，请导出留档'}catch(e){document.getElementById('save-status').textContent='暂存不可用，请导出留档'}});
try{for(const r of JSON.parse(localStorage.getItem(key)||'[]')){const s=document.querySelector('section[data-id="'+r.inquiry_id+'"]');if(!s)continue;for(const t of s.querySelectorAll('textarea'))t.value=r.fields[t.dataset.field]||'';for(const c of s.querySelectorAll('[data-cause]'))c.checked=r.causes.includes(c.value)}}catch(e){}
function exportReview(){const blob=new Blob([JSON.stringify({source:key,exported_at:new Date().toISOString(),reviews:collect()},null,2)],{type:'application/json'});const u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download='original_text_failure_review_answers.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}
</script></html>'''
    document = header+nav+''.join(sections)+js
    if limit == 40:
        document = document.replace('原始描述检索失败审核', '前40条：原始描述检索失败审核')
        document = document.replace('范围：原100条报告中', '范围：原100条报告的前40条中')
        document = document.replace('100条中编码Top20命中', '前40条中编码Top20命中')
        document = document.replace('original-text-failure-review-20261009', 'original-text-failure-review-first40-20261009')
        document = document.replace('original_text_failure_review_answers.json', 'original_text_failure_review_first40_answers.json')
    if contextual:
        # 上下文实验使用业务字段及历史时间过滤，图片仅供人工审核，不属于该轮检索输入。
        document = document.replace('原始描述检索失败审核', '结合业务信息检索失败审核（search_with_context）')
        document = document.replace('原始名称描述（本次文本查询）', '原始名称描述')
        document = document.replace('图片供人工理解目标；本页分析的文本检索没有使用这些图片及车型条件。', '图片供人工理解目标；本次检索传入原始描述、车型、车号、车厢、隶属部件及来源询码ID和时间，没有传入图片。')
        document = document.replace('只用原始描述的检索结果', '结合业务信息的实际检索结果')
        document = document.replace('范围：原100条报告中，只看 search_text_vectors，即原始名称描述的全局文本检索。', '范围：原100条报告中，只看 search_with_context。该轮使用原始描述及业务上下文、strict范围，排除当前询码及不满足历史时间条件的记录，不使用图片。')
        document = document.replace('original-text-failure-review-20261009', 'contextual-failure-review-20261009')
        document = document.replace('original_text_failure_review_answers.json', 'contextual_failure_review_answers.json')
    (OUT/'review.html').write_text(document)
    (OUT/'samples.json').write_text(json.dumps(dict(source_report=str(source),source_limit=limit,tool=tool,counts=counts,missing_images=missing,samples=records),ensure_ascii=False,indent=2))
    print(json.dumps(dict(failures=len(records),counts=counts,images=image_count,missing_images=missing,html_bytes=(OUT/'review.html').stat().st_size),ensure_ascii=False))


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tool', choices=['search_text_vectors','search_with_context'], default='search_text_vectors')
    parser.add_argument('--limit', type=int)
    options = parser.parse_args()
    main(options.tool, options.limit)
