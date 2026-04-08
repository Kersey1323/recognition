import os
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

def append_dinov2_justification():
    doc_path = 'docs/动车配件图像识别与三维数字孪生系统技术方案.docx'
    
    if os.path.exists(doc_path):
        doc = Document(doc_path)
    else:
        print(f"Error: {doc_path} not found.")
        return

    # Apply global font styling for appended text
    style = doc.styles['Normal']
    style.font.name = 'SimSun'
    style.element.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')
    style.font.size = Pt(12)

    doc.add_heading('三、核心视觉基座：DINOv2 在强干扰工况下的适配性论证', level=2)
    
    p = doc.add_paragraph()
    p.add_run('针对动车段/运用所内维修工位的复杂物理环境，本架构最终选定 Meta 提出的 DINOv2 (Self-Supervised Vision Transformer) 作为核心鉴别基座。相较于传统基于监督学习的 CNN（如 ResNet）方案，DINOv2 在以下三个核心工程维度展现出具有绝对优势的零样本（Zero-Shot）泛化能力：\n\n')
    
    p.add_run('1. 强特征正交与密集视角鲁棒性\n').bold = True
    p.add_run('传统的分类类神经网络容易过度拟合于特定的视角特征。因为 DINOv2 采用图像块级（Patch-level）自监督学习，模型内生学习了三维物体的物理几何属性。当维修工人每次拍摄同一配件时产生剧烈的平移、旋转及空间透视畸变时，DINOv2 提取的 1024 维全局 [CLS] Token 依然能在高维流形空间中保持绝对收敛，确保向量点积（或余弦相似度）不发生突变。\n\n')
    
    p.add_run('2. 无惧反光与油污遮挡的注意力机制\n').bold = True
    p.add_run('动车金属零配件（如轴承、法兰、紧固件）本质上是具有高反射率的硬质几何体。现场复杂的点光源极易产生严重的高光白斑（Specular Highlights），且配件经常附着黑色碳垢与油液。DINOv2 所依赖的 Transformer 多头自注意力机制（Multi-Head Self-Attention）能够在推断时动态规避被高光或油污破坏的无效像素块，将特征计算权重强制集中在其特有的机械倒角、螺牙和沟槽等深层次结构纹理上，从而避免了传统 CNN 因局部高光导致特征分布完全崩塌的风险。\n\n')
    
    p.add_run('3. 细粒度检索与“同类异构件”区分\n').bold = True
    p.add_run('高铁不同型号列车的配件在宏观外形上几乎完全一致（例如两种垫片可能仅存在内径 2mm 的公差或螺纹密度的细微差异）。这些微米级的特征差异无法通过传统的图像层级分类器捕获。DINOv2 的预训练模式赋予了其极高的细粒度（Fine-grained）感知阈值，其提取出的密集向量能够直接在微小局部差异上形成数学正交，配合后端 Milvus 的 L2 距离测算，能实现超过常规模型基准的精准型号鉴别。')

    doc.save(doc_path)
    print(f"Successfully appended DINOv2 Justification to {doc_path}")

if __name__ == '__main__':
    append_dinov2_justification()
