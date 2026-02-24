import os
import re
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT

def create_clean_word_doc():
    md_path = 'docs/clean_technical_solution.md'
    doc_path = 'docs/动车配件图像识别与三维数字孪生系统技术方案.docx'
    
    if os.path.exists(doc_path):
        os.remove(doc_path)
    
    doc = Document()
    
    # Global font set to SimSun (Songti) for Chinese
    style = doc.styles['Normal']
    style.font.name = 'SimSun'
    style.element.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')
    style.font.size = Pt(12)
    
    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Remove bold markdown asterisks for plain text processing
        line_clean = line.replace('**', '').replace('`', '')
            
        if line.startswith('# '):
            h = doc.add_heading(line_clean[2:], level=0)
            h.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
        elif line.startswith('## '):
            doc.add_heading(line_clean[3:], level=1)
        elif line.startswith('### '):
            doc.add_heading(line_clean[4:], level=2)
        elif line.startswith('- ') or line.startswith('* '):
            p = doc.add_paragraph(line_clean[2:], style='List Bullet')
        elif re.match(r'^\d+\.\s', line):
            # Matches "1. ", "2. ", etc.
            match = re.match(r'^(\d+\.\s)(.*)', line_clean)
            if match:
                p = doc.add_paragraph(match.group(2), style='List Number')
        else:
            doc.add_paragraph(line_clean)

    # Re-append the comparison table at the end
    doc.add_page_break()
    heading = doc.add_heading('附录：视觉大模型横向对比', level=1)
    heading.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    
    p = doc.add_paragraph('系统底层支持热插拔配置（Plugin-and-Play）多种特征流基座模型，对其特性对比如下：')
    
    table = doc.add_table(rows=6, cols=5)
    table.style = 'Table Grid'
    
    # Define headers
    hdr_cells = table.rows[0].cells
    headers = ['模型名称', '主干架构', '特征维度', '技术特点', '适配场景']
    for i, text in enumerate(headers):
        hdr_cells[i].text = text
        for run in hdr_cells[i].paragraphs[0].runs:
            run.font.bold = True

    model_data = [
        ('ResNet-34/50', 'CNN', '512 / 2048', '计算占用低，推理延迟亚毫秒级', '零配件粗筛，CPU部署环境'),
        ('DINOv2 (Large)', 'ViT', '1024', '自监督学习，特征正交与局部鲁棒性强', '核心检索，克服反光油污遮挡'),
        ('ConvNeXt V2', '现代理想CNN', '768', '具备CNN和ViT双重优势', '高吞吐量混合测算线'),
        ('OpenAI CLIP', 'ViT + Text', '512 / 768', '对齐图像与文本特征，支持零样本跨模态', '非标准件文本/语言模糊指令召回'),
        ('Swin-Transformer', '移动窗口Transformer', '1024', '处理超高分辨率图像不引发显存爆炸', '超高清全局影像(4K探伤)特征提取')
    ]

    for idx, data_row in enumerate(model_data):
        row_cells = table.rows[idx + 1].cells
        for col_idx, text in enumerate(data_row):
            row_cells[col_idx].text = text

    doc.save(doc_path)
    print(f"Generated clean document: {doc_path}")

if __name__ == '__main__':
    create_clean_word_doc()
