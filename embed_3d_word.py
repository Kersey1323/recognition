from docx import Document
from docx.shared import Inches, Pt
from docx.oxml.ns import qn

doc = Document()
style = doc.styles['Normal']
style.font.name = 'SimSun'
style.element.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')
style.font.size = Pt(12)

doc.add_heading('3D高斯可微渲染(2DGS)与三维重建生产流水线', 0)
doc.add_paragraph('以下为从原始连续照片输入到最终提取可用于 WebGL 渲染的标准化 .obj 数字孪生物料的全链条流程图：')
doc.add_picture('diagram_3d.png', width=Inches(6.0))

doc.add_heading('一、2D Gaussian Splatting (2DGS) 技术原理解析', level=2)
p = doc.add_paragraph()
p.add_run('核心痛点：').bold = True
p.add_run('原生的 3D 高斯软性体积渲染 (3DGS) 虽然在逼真度和渲染速度上具有跨时代意义，但在工业界遇到了致命瓶颈——它生成的不是真实的物理表面，而是无数团雾状的“椭球云”。这导致无法应用传统的物理光照，并且使用移动立方体 (Marching Cubes) 提取网格时，表面会像月球坑一样坑洼不平（内部被掏空）。\n\n')
p.add_run('2DGS 的数学破局：').bold = True
p.add_run('2DGS （如 SuGaR 工作流）不再使用全维度的 3D 椭球，而是强制将代表粒子的高斯体')
p.add_run('“拍扁”成极其轻薄的 2D 椭圆面片').bold = True
p.add_run('。它引入了极强的几何约束方程：\n')
p.add_run('1. 深度正则化 (Depth Distortion Loss)：约束光线穿过像素时，所有相关的 2D 高斯体必须在极其狭窄的深度范围内重叠，强制高斯体收缩、贴合到真实的物体硬表面上。\n')
p.add_run('2. 法向量一致性 (Normal Consistency)：要求高斯面的法向量与光学深度梯度的法向量保持一致，从而消除了杂乱无章的方向。')

doc.add_heading('二、关于 .ply 高斯原语数据结构的解析', level=2)
p = doc.add_paragraph()
p.add_run('在图中第二个子图结束时，导出的核心产物就是 .ply 文件：\n')
p.add_run('1. 什么是 PLY：').bold = True
p.add_run('多边形文件格式（Polygon File Format），传统上它只用于存储点云（X,Y,Z坐标）。\n')
p.add_run('2. 3DGS 中的 PLY 变体：').bold = True
p.add_run('在这个管线中，导出的 .ply 是被“超载定义”的。除了千万个微小点云的三维坐标外，文件里还深度序列化了该坐标点绑定的 ')
p.add_run('球谐函数系数 (Spherical Harmonics, SH，用于模拟随视角变化的反射金属光泽)、缩放矩阵协方差 (3维)、旋转四元数 (4维) 以及不透明度 (Opacity, 1维)').bold = True
p.add_run('。\n')
p.add_run('3. 最终桥接转化：').bold = True
p.add_run('由于含有几十万维这样的点阵，裸体 .ply 文件动辄上百兆且无法进行碰撞检测。所以必须引入第三方算子（如泊松表面重建 Poisson Surface Reconstruction），把这些高度贴合表面的 .ply 锚点像“拉保鲜膜”一样蒙皮，最后才会生成带材质信息的低内存 `.obj / .mtl` 真正三维游戏/工业级资产。')

output_path = 'docs/3D高斯可微渲染技术解析与流图.docx'
doc.save(output_path)
print(f'Document saved to {output_path}')
