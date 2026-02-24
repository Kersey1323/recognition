import os
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT

def append_vision_models_table():
    doc_path = 'docs/动车配件图像识别与三维数字孪生系统技术方案.docx'
    
    # Check if the document exists, if not we will create it (though it should exist from previous steps)
    if os.path.exists(doc_path):
        doc = Document(doc_path)
    else:
        doc = Document()
        print(f"Warning: {doc_path} not found. Creating a new one.")

    # Apply global font styling for appended text
    style = doc.styles['Normal']
    style.font.name = 'SimSun'
    style.element.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')
    style.font.size = Pt(12)

    # Append new section
    doc.add_page_break()
    heading = doc.add_heading('附录：工业视觉基座大模型选型与特性横向对比', level=1)
    heading.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    
    p = doc.add_paragraph()
    p.add_run('针对动车配件识别系统在复杂工况下的泛化约束，本架构预研并兼容了当前工业界主流的多种前沿视觉大模型库。系统底层的特征提取微服务已进行了全量解耦，支持以热插拔配置（Plugin-and-Play）的模式实时切换以下特征流基座模型：\n')

    # Create the comparison table: 6 Rows, 5 Columns
    table = doc.add_table(rows=6, cols=5)
    table.style = 'Table Grid'
    
    # Define headers
    hdr_cells = table.rows[0].cells
    headers = ['模型名称', '主干架构', '输出特征维度', '核心工业优势', '系统适配场景']
    for i, text in enumerate(headers):
        hdr_cells[i].text = text
        # Make headers bold
        for run in hdr_cells[i].paragraphs[0].runs:
            run.font.bold = True

    # Define model data
    model_data = [
        (
            'ResNet-34 / 50', 
            '深层残差卷积网络 (CNN)', 
            '512 / 2048 维', 
            '显存占用极小，前向推断延迟亚毫秒级，针对标准工业刚性几何体有极强的轮廓提取稳定性。', 
            '高频并发的标准化零配件粗粒度初筛，对服务器算力要求严苛的纯 CPU 部署物理机房。'
        ),
        (
            'DINOv2 (Large)', 
            '纯视觉 Transformer (ViT)', 
            '1024 维', 
            '无监督学习王者，强制学习物体的绝对几何深度与细密纹理，对光照、油污、反光产生的遮挡具有极强的特征正交鲁棒性。', 
            '核心主干网络。用于核心库高精度的跨相机位姿图搜图，以及具有严重形变或锈迹的关键紧固件识别。'
        ),
        (
            'ConvNeXt V2', 
            '现代化纯卷积网络 (CNN)', 
            '768 维', 
            '融合了 ViT 宏观特性的现代卷积，同时吸纳了 MAE 掩码自编码器机制。具备 CNN 的高滑动窗口效率与 ViT 的高层级全局感受野。', 
            'DINOv2 的高性价比下位替代。适用于需要高精度且吞吐量要求极高的混合流水线（GPU+CPU协同）。'
        ),
        (
            'OpenAI CLIP', 
            '多模态对比学习 (ViT + Text)', 
            '512 / 768 维', 
            '同时对齐图像与文本两套特征空间。支持零样本（Zero-Shot）跨模态检索。', 
            '非标准配件模糊检索。例如工人直接输入文本指令“带有黑色油污的半圆柱体轴承”，系统即可直接从纯图像向量库中跨位面召回目标。'
        ),
        (
            'Swin-Transformer', 
            '层级移动窗口 Transformer', 
            '1024 维', 
            '基于移动窗口机制，天然具备处理超高分辨率工业原图（如 4K 探伤图）的能力，不随图像尺寸呈平方级显存爆炸。', 
            '接触网或大型转向架的超高清全局影像特征提取，适用于需要密集像素级语义的缺陷检测流。'
        )
    ]

    # Populate the table
    for idx, data_row in enumerate(model_data):
        row_cells = table.rows[idx + 1].cells
        for col_idx, text in enumerate(data_row):
            row_cells[col_idx].text = text

    # Finalizer text
    # p2 = doc.add_paragraph('\n')
    # p2.add_run('注：由于上述各模型的输出特征维度呈现异构性（从 512维 至 2048维不等），系统落库时通过 BaseExtractor 接口层绑定的动态 get_collection_name() 路由，强制将各自的向量物理隔离写入 Milvus 中独立配置的 Collection，确保底层欧氏距离计算的几何流形绝对隔离。')

    doc.save(doc_path)
    print(f"Successfully appended Vision Models Comparison Table to {doc_path}")

if __name__ == '__main__':
    append_vision_models_table()
