"""长算力任务调度技术方案 → Word 文档生成脚本

运行方式: uv run python gen_schedule_word.py
输出文件: docs/3D重建长算力任务调度技术方案.docx
"""

import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

from docx import Document
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

# ---------------------------------------------------------------------------
# 颜色定义
# ---------------------------------------------------------------------------
C_BG      = '#1B2838'      # 深蓝背景
C_TEAL    = '#26A69A'       # 青色
C_CYAN    = '#4DD0E1'       # 浅青
C_ORANGE  = '#FF8A65'       # 暖橙
C_RED     = '#EF5350'       # 红
C_PURPLE  = '#AB47BC'       # 紫
C_GREEN   = '#66BB6A'       # 绿
C_BLUE    = '#42A5F5'       # 蓝
C_GRAY    = '#78909C'       # 灰蓝
C_WHITE   = '#ECEFF1'       # 白
C_LGRAY   = '#B0BEC5'       # 淡灰


def _setup_font():
    """设置 matplotlib 中文字体"""
    for name in ['Microsoft YaHei', 'SimHei', 'DengXian', 'Arial Unicode MS']:
        try:
            matplotlib.font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams['font.sans-serif'] = [name, 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
            return name
        except Exception:
            continue
    plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    return 'SimHei'


def _rounded_box(ax, x, y, w, h, text, fc, fontsize=11, fontcolor='white',
                 radius=0.15, lw=0, ec='none', sub_text=None, bold=False):
    """画一个圆角矩形 + 居中文字"""
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=fc, edgecolor=ec, linewidth=lw,
        transform=ax.transData, zorder=2
    )
    ax.add_patch(box)
    weight = 'bold' if bold else 'normal'
    ax.text(x + w/2, y + h/2 + (0.12 if sub_text else 0), text,
            ha='center', va='center', fontsize=fontsize, color=fontcolor,
            weight=weight, zorder=3)
    if sub_text:
        ax.text(x + w/2, y + h/2 - 0.18, sub_text,
                ha='center', va='center', fontsize=8, color=fontcolor,
                alpha=0.8, zorder=3)
    return box


def _arrow_down(ax, x, y1, y2, color=C_LGRAY, lw=2):
    """画向下箭头"""
    ax.annotate('', xy=(x, y2), xytext=(x, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=lw),
                zorder=1)


def draw_architecture(output_path):
    """绘制整体架构图"""
    fig, ax = plt.subplots(1, 1, figsize=(10, 12))
    fig.patch.set_facecolor(C_BG)
    ax.set_facecolor(C_BG)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 12)
    ax.axis('off')

    # 标题
    ax.text(5, 11.5, '3D重建任务调度系统 · 整体架构', ha='center', va='center',
            fontsize=18, color=C_WHITE, weight='bold')

    # --- 第1层: 任务提交 ---
    _rounded_box(ax, 2.5, 10.2, 5, 0.9, '任务提交入口', C_TEAL, fontsize=14,
                 sub_text='Web端  /  工装上传  /  定时触发', bold=True)

    _arrow_down(ax, 5, 10.2, 9.7)

    # --- 第2层: RocketMQ ---
    # 外框
    queue_box = FancyBboxPatch(
        (1, 7.8), 8, 1.8,
        boxstyle="round,pad=0,rounding_size=0.2",
        facecolor='#263238', edgecolor=C_LGRAY, linewidth=1.5,
        transform=ax.transData, zorder=1
    )
    ax.add_patch(queue_box)
    ax.text(5, 9.35, 'RocketMQ 消息队列', ha='center', va='center',
            fontsize=13, color=C_WHITE, weight='bold')

    _rounded_box(ax, 1.5, 8.1, 2, 0.9, '高优先级', '#E53935', fontsize=11,
                 sub_text='紧急件', bold=True)
    _rounded_box(ax, 4, 8.1, 2, 0.9, '普通优先级', C_BLUE, fontsize=11,
                 sub_text='增量更新', bold=True)
    _rounded_box(ax, 6.5, 8.1, 2, 0.9, '低优先级', C_GRAY, fontsize=11,
                 sub_text='全量补录', bold=True)

    _arrow_down(ax, 5, 7.8, 7.3)

    # --- 第3层: 调度器 + 监控 ---
    _rounded_box(ax, 2, 6.3, 2.8, 0.8, '调 度 器', C_PURPLE, fontsize=13,
                 sub_text='Scheduler', bold=True)
    _rounded_box(ax, 5.2, 6.3, 2.8, 0.8, '监控面板', C_GREEN, fontsize=13,
                 sub_text='Dashboard', bold=True)

    # 调度器和监控面板之间虚线
    ax.plot([4.8, 5.2], [6.7, 6.7], '--', color=C_LGRAY, lw=1, zorder=1)

    # 调度器到Worker的箭头
    _arrow_down(ax, 2.5, 6.3, 5.8)
    _arrow_down(ax, 5.0, 6.3, 5.8)
    _arrow_down(ax, 7.5, 6.3, 5.8)

    # --- 第4层: Worker ---
    worker_data = [
        (1.2, 'Worker 0', 'GPU : 0'),
        (3.7, 'Worker 1', 'GPU : 1'),
        (6.2, 'Worker N', 'GPU : N'),
    ]
    for wx, name, gpu in worker_data:
        # Worker外框
        wbox = FancyBboxPatch(
            (wx, 3.5), 2.6, 2.2,
            boxstyle="round,pad=0,rounding_size=0.15",
            facecolor='#37474F', edgecolor=C_ORANGE, linewidth=1.5,
            transform=ax.transData, zorder=1
        )
        ax.add_patch(wbox)
        ax.text(wx + 1.3, 5.4, name, ha='center', va='center',
                fontsize=12, color=C_ORANGE, weight='bold')
        ax.text(wx + 1.3, 5.1, gpu, ha='center', va='center',
                fontsize=9, color=C_LGRAY)

        # Worker内部四个步骤
        steps = [('COLMAP', C_GREEN), ('2DGS训练', C_BLUE), ('网格提取', C_TEAL), ('特征提取', C_PURPLE)]
        for i, (s, c) in enumerate(steps):
            _rounded_box(ax, wx + 0.15, 4.55 - i * 0.35, 2.3, 0.28,
                         s, c, fontsize=9, radius=0.08)

    # Worker到存储的箭头
    _arrow_down(ax, 2.5, 3.5, 3.0)
    _arrow_down(ax, 5.0, 3.5, 3.0)
    _arrow_down(ax, 7.5, 3.5, 3.0)

    # --- 第5层: 结果存储 ---
    _rounded_box(ax, 2.5, 2.0, 5, 0.85, '结果存储', C_TEAL, fontsize=14,
                 sub_text='MinIO / OSS / Milvus', bold=True)

    # 层标签
    labels = [
        (10.65, '提交层', C_TEAL),
        (8.6, '队列层', C_BLUE),
        (6.7, '调度层', C_PURPLE),
        (4.75, '执行层', C_ORANGE),
        (2.7, '存储层', C_TEAL),
    ]
    for ly, lt, lc in labels:
        ax.text(9.6, ly, lt, ha='center', va='center',
                fontsize=9, color=lc, alpha=0.7, style='italic')

    fig.tight_layout(pad=0.5)
    fig.savefig(output_path, dpi=180, bbox_inches='tight',
                facecolor=C_BG, edgecolor='none')
    plt.close(fig)
    print(f'  架构图 → {output_path}')


def draw_deployment(output_path):
    """绘制多机部署拓扑图"""
    fig, ax = plt.subplots(1, 1, figsize=(10, 7))
    fig.patch.set_facecolor(C_BG)
    ax.set_facecolor(C_BG)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 7)
    ax.axis('off')

    ax.text(5, 6.6, '多机部署拓扑', ha='center', va='center',
            fontsize=18, color=C_WHITE, weight='bold')

    # 管理节点
    mgr = FancyBboxPatch(
        (3, 4.8), 4, 1.4,
        boxstyle="round,pad=0,rounding_size=0.2",
        facecolor='#263238', edgecolor=C_BLUE, linewidth=2,
        transform=ax.transData, zorder=2
    )
    ax.add_patch(mgr)
    ax.text(5, 5.95, '管理节点', ha='center', va='center',
            fontsize=14, color=C_BLUE, weight='bold')
    items_mgr = ['RocketMQ', 'Redis (状态)', 'Grafana 监控']
    for i, item in enumerate(items_mgr):
        ax.text(5, 5.55 - i * 0.25, item, ha='center', va='center',
                fontsize=10, color=C_LGRAY)

    # 内网横条
    ax.fill_between([1.5, 8.5], 4.2, 4.4, color=C_GRAY, alpha=0.4, zorder=1)
    ax.text(5, 4.3, '─── 内  网 ───', ha='center', va='center',
            fontsize=10, color=C_WHITE, alpha=0.7)

    # 管理节点到内网
    _arrow_down(ax, 5, 4.8, 4.4)

    # 计算节点
    nodes = [
        (0.8, '计算节点 A'),
        (3.6, '计算节点 B'),
        (6.4, '计算节点 C'),
    ]
    for nx, name in nodes:
        node_box = FancyBboxPatch(
            (nx, 1.2), 2.8, 2.6,
            boxstyle="round,pad=0,rounding_size=0.2",
            facecolor='#263238', edgecolor=C_ORANGE, linewidth=2,
            transform=ax.transData, zorder=2
        )
        ax.add_patch(node_box)
        ax.text(nx + 1.4, 3.5, name, ha='center', va='center',
                fontsize=12, color=C_ORANGE, weight='bold')

        # GPU卡
        for i in range(4):
            gx = nx + 0.2 + i * 0.65
            gpu_box = FancyBboxPatch(
                (gx, 2.6), 0.55, 0.5,
                boxstyle="round,pad=0,rounding_size=0.06",
                facecolor=C_TEAL, edgecolor='none', linewidth=0, alpha=0.8,
                transform=ax.transData, zorder=3
            )
            ax.add_patch(gpu_box)
            ax.text(gx + 0.275, 2.85, '5090', ha='center', va='center',
                    fontsize=7, color='white', weight='bold', zorder=4)

        ax.text(nx + 1.4, 2.2, '4 × RTX 5090', ha='center', va='center',
                fontsize=10, color=C_WHITE)
        ax.text(nx + 1.4, 1.8, 'Worker × 4', ha='center', va='center',
                fontsize=10, color=C_LGRAY)
        ax.text(nx + 1.4, 1.45, '独立进程 · 一卡一任务', ha='center', va='center',
                fontsize=8, color=C_LGRAY, alpha=0.6)

        # 内网到节点的箭头
        _arrow_down(ax, nx + 1.4, 4.2, 3.8)

    fig.tight_layout(pad=0.5)
    fig.savefig(output_path, dpi=180, bbox_inches='tight',
                facecolor=C_BG, edgecolor='none')
    plt.close(fig)
    print(f'  部署图 → {output_path}')


def draw_worker_flow(output_path):
    """绘制Worker执行流程图"""
    fig, ax = plt.subplots(1, 1, figsize=(8, 12))
    fig.patch.set_facecolor(C_BG)
    ax.set_facecolor(C_BG)
    ax.set_xlim(0, 8)
    ax.set_ylim(0, 12)
    ax.axis('off')

    ax.text(4, 11.5, 'Worker 执行流程', ha='center', va='center',
            fontsize=18, color=C_WHITE, weight='bold')

    # 流程步骤定义: (y, 文字, 颜色, 注释)
    steps = [
        (10.5, 'RocketMQ 消费任务', C_BLUE, None),
        (9.5,  '下载图片到本地', C_CYAN, None),
        (8.3,  'COLMAP 稀疏重建', C_GREEN, 'CPU密集 ≈5min'),
        (7.1,  '2DGS 训练', C_ORANGE, 'GPU密集 ≈10min'),
        (5.9,  '网格提取 + 导出OBJ', C_ORANGE, 'GPU ≈2min'),
        (4.9,  '视觉特征提取', C_PURPLE, 'GPU ≈3min'),
        (3.5,  '上传结果 + 清理', C_TEAL, None),
    ]

    bw, bh = 3.2, 0.6
    cx = 4

    for i, (sy, text, color, note) in enumerate(steps):
        _rounded_box(ax, cx - bw/2, sy, bw, bh, text, color,
                     fontsize=11, radius=0.12, bold=True)
        if note:
            ax.text(cx + bw/2 + 0.3, sy + bh/2, note,
                    ha='left', va='center', fontsize=9, color=color, alpha=0.8,
                    style='italic')
        # 箭头到下一个
        if i < len(steps) - 1:
            next_y = steps[i + 1][0]
            gap = sy - next_y - bh
            if gap > 0.15:
                _arrow_down(ax, cx, sy, next_y + bh)

    # 成功/失败分支 (在特征提取后)
    # 菱形判断
    dy = 4.15
    diamond = plt.Polygon(
        [[cx, dy + 0.35], [cx + 0.5, dy], [cx, dy - 0.35], [cx - 0.5, dy]],
        facecolor='#FFA726', edgecolor='white', linewidth=1.5, zorder=3
    )
    ax.add_patch(diamond)
    ax.text(cx, dy, '成功?', ha='center', va='center',
            fontsize=10, color='white', weight='bold', zorder=4)

    # 成功 → 下
    _arrow_down(ax, cx, dy - 0.35, 3.5 + bh)
    ax.text(cx + 0.15, dy - 0.52, '是', fontsize=9, color=C_GREEN)

    # 失败 → 右 → 重试
    ax.annotate('', xy=(6.5, dy), xytext=(cx + 0.5, dy),
                arrowprops=dict(arrowstyle='->', color=C_RED, lw=2), zorder=1)
    ax.text(5.5, dy + 0.15, '否', fontsize=9, color=C_RED)

    _rounded_box(ax, 5.8, dy - 0.28, 1.8, 0.56, '重试/失败', C_RED,
                 fontsize=10, radius=0.1, bold=True)

    # 重试箭头回到顶部
    ax.annotate('', xy=(7.2, 10.8), xytext=(7.2, dy),
                arrowprops=dict(arrowstyle='->', color=C_RED, lw=1.5,
                                linestyle='dashed'),
                zorder=1)
    ax.annotate('', xy=(cx + bw/2, 10.8), xytext=(7.2, 10.8),
                arrowprops=dict(arrowstyle='->', color=C_RED, lw=1.5,
                                linestyle='dashed'),
                zorder=1)

    # 循环箭头：上传结果 → 回到取任务
    ax.annotate('', xy=(1.2, 10.8), xytext=(1.2, 3.8),
                arrowprops=dict(arrowstyle='->', color=C_LGRAY, lw=1.5,
                                linestyle='dotted'),
                zorder=1)
    ax.annotate('', xy=(cx - bw/2, 10.8), xytext=(1.2, 10.8),
                arrowprops=dict(arrowstyle='->', color=C_LGRAY, lw=1.5,
                                linestyle='dotted'),
                zorder=1)
    ax.text(0.8, 7.5, '循环', fontsize=9, color=C_LGRAY, alpha=0.7,
            rotation=90, ha='center', va='center')

    # 连接 特征提取→菱形 的箭头
    _arrow_down(ax, cx, 4.9, dy + 0.35)

    fig.tight_layout(pad=0.5)
    fig.savefig(output_path, dpi=180, bbox_inches='tight',
                facecolor=C_BG, edgecolor='none')
    plt.close(fig)
    print(f'  流程图 → {output_path}')


# ===========================================================================
# Word 文档生成
# ===========================================================================

def _set_cell_bg(cell, color_hex):
    """设置表格单元格背景色"""
    from docx.oxml import OxmlElement
    shading = OxmlElement('w:shd')
    shading.set(qn('w:fill'), color_hex.lstrip('#'))
    shading.set(qn('w:val'), 'clear')
    cell._tc.get_or_add_tcPr().append(shading)


def _add_table(doc, headers, rows, col_widths=None, header_bg='1B5E20'):
    """添加格式化表格"""
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # 表头
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ''
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(h)
        run.bold = True
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        run.font.name = 'Microsoft YaHei'
        run.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
        _set_cell_bg(cell, header_bg)

    # 数据行
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = table.rows[ri + 1].cells[ci]
            cell.text = ''
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(str(val))
            run.font.size = Pt(10)
            run.font.name = 'Microsoft YaHei'
            run.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
            if ri % 2 == 1:
                _set_cell_bg(cell, 'F5F5F5')

    # 列宽
    if col_widths:
        for i, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Cm(w)

    return table


def _add_para(doc, text, bold=False, size=12, color=None, alignment=None,
              space_after=6, font_name='Microsoft YaHei'):
    """添加段落"""
    p = doc.add_paragraph()
    if alignment:
        p.alignment = alignment
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.font.name = font_name
    run.element.rPr.rFonts.set(qn('w:eastAsia'), font_name)
    run.bold = bold
    if color:
        run.font.color.rgb = color
    return p


def _add_code_block(doc, code_text):
    """添加代码块（灰色背景 Consolas 字体）"""
    from docx.oxml import OxmlElement
    for line in code_text.strip().split('\n'):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        run = p.add_run(line)
        run.font.size = Pt(9)
        run.font.name = 'Consolas'
        # 灰背景
        shading = OxmlElement('w:shd')
        shading.set(qn('w:fill'), 'ECEFF1')
        shading.set(qn('w:val'), 'clear')
        p._p.get_or_add_pPr().append(shading)


def build_word(arch_img, deploy_img, flow_img, output_path):
    """构建完整 Word 文档"""
    doc = Document()

    # ====== 全局样式 ======
    style = doc.styles['Normal']
    style.font.name = 'Microsoft YaHei'
    style.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    style.font.size = Pt(11)
    style.paragraph_format.space_after = Pt(6)

    for level in range(1, 5):
        hs = doc.styles[f'Heading {level}']
        hs.font.name = 'Microsoft YaHei'
        hs.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
        hs.font.color.rgb = RGBColor(0x1B, 0x5E, 0x20)

    # ====== 封面 ======
    for _ in range(6):
        doc.add_paragraph()
    _add_para(doc, '3D重建长算力任务调度技术方案', bold=True, size=26,
              alignment=WD_ALIGN_PARAGRAPH.CENTER, space_after=12,
              color=RGBColor(0x1B, 0x5E, 0x20))
    _add_para(doc, '—— 2万配件全量重建与年度增量调度规划 ——', size=14,
              alignment=WD_ALIGN_PARAGRAPH.CENTER, space_after=30,
              color=RGBColor(0x60, 0x60, 0x60))
    _add_para(doc, '2026年2月', size=12,
              alignment=WD_ALIGN_PARAGRAPH.CENTER,
              color=RGBColor(0x90, 0x90, 0x90))

    doc.add_page_break()

    # ====== 一、业务背景 ======
    doc.add_heading('一、业务背景', level=1)
    _add_para(doc,
        '目前需要对约 2万个 配件完成3D重建，后续每年有约 5000个 配件更新需要重新重建。'
        '单个配件从多角度照片到最终OBJ模型的完整重建流程耗时约 20分钟'
        '（含COLMAP点云估计、2DGS训练、网格提取、视觉特征提取四个阶段），'
        '算力卡规格按 RTX 5090 级别规划。')
    _add_para(doc,
        '核心诉求：在合理的时间窗口内消化初始存量和年度增量任务，'
        '同时保证重建服务的可用性和GPU利用率。', bold=True)

    # ====== 二、算力需求测算 ======
    doc.add_heading('二、算力需求测算', level=1)

    doc.add_heading('2.1 工时估算', level=2)
    _add_table(doc,
        ['场景', '配件数量', '单件耗时', '总GPU工时', '折合天数(24h)'],
        [
            ['初始全量重建', '20,000', '20 min', '6,667 h', '278 天'],
            ['年度增量重建', '5,000', '20 min', '1,667 h', '69 天'],
        ],
        col_widths=[4, 3, 2.5, 3, 3.5])
    doc.add_paragraph()

    doc.add_heading('2.2 卡数规划', level=2)
    _add_para(doc, '初始全量阶段 —— 目标在30个自然日内完成：', bold=True)
    _add_code_block(doc, '所需卡数 = 6667h ÷ (30天 × 24h) ≈ 9.3 → 取 10 张卡')
    _add_para(doc,
        '考虑到实际运行中存在任务调度间隙、COLMAP占CPU等开销，'
        '建议按 10~12张 5090 规划。如果工期放宽到60天，5~6张卡也能跑完。')

    _add_para(doc, '年度增量阶段 —— 假设全年均匀分布，月均约420件：', bold=True)
    _add_code_block(doc,
        '月度GPU工时 = 420 × 20min ≈ 140h\n'
        '单卡月可用 = 30 × 24 × 0.85（利用率）≈ 612h')
    _add_para(doc,
        '年度常态只需1张卡即可消化增量。但考虑到增量任务往往集中在几个月份，'
        '以及日常调试和模型迭代的需要，建议常态保留2~3张卡。')

    doc.add_heading('2.3 推荐配置', level=2)
    _add_table(doc,
        ['阶段', 'GPU数量', '预计周期', '备注'],
        [
            ['初始全量（赶工期）', '10~12张 5090', '30天', '可租用云GPU，用完即退'],
            ['年度常态', '2~3张 5090', '全年', '自建或长租，兼顾开发测试'],
        ],
        col_widths=[4, 3, 2.5, 6])
    _add_para(doc,
        '注：初始全量如果没有时间压力，也可以用3~4张卡跑2~3个月慢慢消化，节省成本。',
        size=10, color=RGBColor(0x78, 0x78, 0x78))

    # ====== 三、整体架构 ======
    doc.add_heading('三、整体架构', level=1)
    _add_para(doc,
        '整个系统分四层：任务提交 → 队列缓冲 → 调度分发 → Worker执行。'
        '各层松耦合，Worker可以灵活扩缩。')
    if os.path.exists(arch_img):
        doc.add_picture(arch_img, width=Inches(5.5))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    # ====== 四、核心模块设计 ======
    doc.add_heading('四、核心模块设计', level=1)

    doc.add_heading('4.1 消息队列（RocketMQ）', level=2)
    _add_para(doc,
        '选用 RocketMQ 作为任务队列，原因：')
    for reason in [
        '支持消息优先级和延迟消息',
        '单机吞吐量高，消息堆积能力强（百万级）',
        '支持事务消息，保证任务不丢',
        '原生支持消费组，天然适配多Worker消费',
    ]:
        p = doc.add_paragraph(reason, style='List Bullet')
        for run in p.runs:
            run.font.name = 'Microsoft YaHei'
            run.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

    _add_para(doc, 'Topic 设计：', bold=True)
    _add_code_block(doc,
        'recon-task-high      # 紧急任务\n'
        'recon-task-normal    # 日常增量\n'
        'recon-task-low       # 全量补录\n'
        'recon-task-result    # 任务完成通知')

    _add_para(doc, '消息体：', bold=True)
    _add_code_block(doc,
        '{\n'
        '    "task_id": "uuid",\n'
        '    "item_id": 12345,\n'
        '    "image_source": "oss://bucket/items/12345/photos/",\n'
        '    "priority": "normal",\n'
        '    "trainer_type": "2dgs",\n'
        '    "iterations": 7000,\n'
        '    "created_at": "2026-02-24T10:00:00"\n'
        '}')
    _add_para(doc,
        '消费模式：Worker以集群消费（Clustering）模式消费，'
        '同一条消息只被一个Worker处理，天然实现负载均衡。')

    doc.add_heading('4.2 调度器', level=2)
    _add_para(doc,
        '调度器角色相对轻量，因为RocketMQ本身已经提供了消费负载均衡。调度器主要负责：')
    for item in [
        '任务去重：同一 item_id 不会同时存在两个运行中的任务，通过Redis记录',
        'Worker健康检查：通过心跳监控Worker状态',
        '任务状态管理：在Redis中维护任务状态供外部查询',
    ]:
        p = doc.add_paragraph(item, style='List Bullet')
        for run in p.runs:
            run.font.name = 'Microsoft YaHei'
            run.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

    doc.add_heading('4.3 Worker进程', level=2)
    _add_para(doc, '每个Worker是一个独立Python进程，启动时指定GPU编号：')
    _add_code_block(doc,
        'python -m recon_worker --gpu 0 --worker-id worker-0 '
        '--namesrv 10.0.0.1:9876')

    if os.path.exists(flow_img):
        doc.add_picture(flow_img, width=Inches(4.2))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    _add_para(doc, '视觉特征提取阶段：', bold=True)
    for item in [
        '对重建使用的多角度图片提取 DINOv2 / ResNet 特征向量',
        '特征向量写入 Milvus 向量数据库，用于后续的配件视觉检索',
        '同时提取代表性视角的缩略图用于前端展示',
    ]:
        p = doc.add_paragraph(item, style='List Bullet')
        for run in p.runs:
            run.font.name = 'Microsoft YaHei'
            run.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

    doc.add_heading('4.4 重试与容错', level=2)

    _add_para(doc, '消息级重试：', bold=True)
    for item in [
        'RocketMQ 自带消费重试机制，消费失败后自动重投（间隔递增）',
        '超过最大重试次数进入死信队列（DLQ），人工介入',
        '常见失败原因：OOM、COLMAP匹配点过少、图片数量不足',
    ]:
        p = doc.add_paragraph(item, style='List Bullet')
        for run in p.runs:
            run.font.name = 'Microsoft YaHei'
            run.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

    _add_para(doc, 'Worker级容错：', bold=True)
    for item in [
        'Worker进程崩溃后由 systemd / supervisor 自动拉起',
        'RocketMQ消费侧有ACK机制，未确认的消息会被重新投递',
        '多机部署时某台机器宕机不影响其他机器继续工作',
    ]:
        p = doc.add_paragraph(item, style='List Bullet')
        for run in p.runs:
            run.font.name = 'Microsoft YaHei'
            run.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

    # ====== 五、任务批量导入与触发策略 ======
    doc.add_heading('五、任务批量导入与触发策略', level=1)

    doc.add_heading('5.1 初始全量导入', level=2)
    _add_para(doc,
        '全量2万个配件分批写入RocketMQ：')
    _add_code_block(doc,
        '总量 20,000 件\n'
        '每批 500 件，共 40 批\n'
        '每批间隔：上一批消费过半后导入下一批')
    _add_para(doc,
        '导入脚本从数据库拉取未重建的配件列表，'
        '按 item_id 分页，逐批发送到 recon-task-low。')

    doc.add_heading('5.2 增量更新触发', level=2)
    _add_para(doc, '实时触发：', bold=True)
    _add_para(doc,
        '工装上传视频后，服务端自动发送消息到 recon-task-normal。')
    _add_para(doc, '定时批量：', bold=True)
    _add_para(doc,
        '每天凌晨扫描「有照片变更但未重建」的配件，批量导入。')

    doc.add_heading('5.3 优先级场景', level=2)
    _add_table(doc,
        ['优先级', '场景', 'Topic'],
        [
            ['高', '客户催单、临时需求', 'recon-task-high'],
            ['普通', '日常增量更新', 'recon-task-normal'],
            ['低', '全量补录、历史数据', 'recon-task-low'],
        ],
        col_widths=[3, 5, 5])

    # ====== 六、监控与运维 ======
    doc.add_heading('六、监控与运维', level=1)

    doc.add_heading('6.1 监控指标', level=2)
    _add_para(doc, '用 Prometheus + Grafana 搭监控面板，核心关注以下指标：')

    _add_para(doc, '核心指标：', bold=True)
    for item in [
        'RocketMQ 各Topic消息堆积量',
        '任务完成速率（件/小时）',
        '各Worker状态和GPU利用率',
        '失败率与死信队列堆积量',
    ]:
        p = doc.add_paragraph(item, style='List Bullet')
        for run in p.runs:
            run.font.name = 'Microsoft YaHei'
            run.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')



    doc.add_heading('6.2 告警规则', level=2)
    _add_table(doc,
        ['告警', '触发条件', '处理方式'],
        [
            ['Worker离线', '心跳超时 90s', '检查进程，必要时重启'],
            ['消息堆积', '堆积>500 且持续30分钟', '检查Worker，考虑扩容'],
            ['死信队列', 'DLQ有新消息', '人工排查失败原因'],
            ['磁盘不足', '剩余空间 < 50GB', '清理临时文件'],
        ],
        col_widths=[3, 5, 6],
        header_bg='BF360C')

    # ====== 七、多机部署方案 ======
    doc.add_heading('七、多机部署方案', level=1)
    _add_para(doc,
        '如果卡数超过单台服务器的PCI-E插槽数（一般4~8张），就需要多机部署。')

    if os.path.exists(deploy_img):
        doc.add_picture(deploy_img, width=Inches(5.5))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    doc.add_heading('7.1 共享存储', level=2)
    _add_para(doc, '方案A —— MinIO/OSS对象存储（推荐）：', bold=True)
    for item in [
        'Worker从OSS下载图片到本地处理，完成后上传结果',
        '各机器无需共享文件系统',
        '网络带宽按每配件50~100MB图片估算，千兆内网够用',
    ]:
        p = doc.add_paragraph(item, style='List Bullet')
        for run in p.runs:
            run.font.name = 'Microsoft YaHei'
            run.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

    doc.add_heading('7.2 伸缩策略', level=2)
    _add_table(doc,
        ['操作', '方式', '说明'],
        [
            ['扩容', '新机器启动Worker加入同一消费组', '自动加入集群'],
            ['缩容', '停止Worker，RocketMQ自动重新分配分区', '任务流向其余Worker'],
            ['云GPU临时扩容', '租用云实例，统一镜像', '全量阶段用完释放'],
        ],
        col_widths=[3.5, 5, 5])

    # ====== 八、与现有Pipeline对接 ======
    doc.add_heading('八、与现有Pipeline的对接', level=1)
    _add_para(doc,
        '当前项目的 ReconstructionPipeline 已经实现了完整的重建流程，'
        '包括任务状态管理和多种训练器支持（OpenSplat、SuGaR、2DGS等）。'
        '调度系统需要在此基础上做包装，而不是重写。')

    doc.add_heading('8.1 改造要点', level=2)
    changes = [
        '新增Worker入口 recon_worker.py，使用RocketMQ消费端SDK',
        '重建完成后增加特征提取步骤，调用 DINOv2/ResNet 提取特征写入Milvus',
        '任务状态写入Redis供外部查询',
        '现有Web接口保持兼容，发送消息到RocketMQ',
    ]
    for i, item in enumerate(changes, 1):
        p = doc.add_paragraph(f'{i}. {item}')
        for run in p.runs:
            run.font.name = 'Microsoft YaHei'
            run.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')



    # ====== 九、时间节奏规划 ======
    doc.add_heading('九、时间节奏规划', level=1)

    doc.add_heading('9.1 开发排期', level=2)
    _add_table(doc,
        ['阶段', '内容', '周期'],
        [
            ['第1周', 'RocketMQ部署、消息协议、Worker框架', '5天'],
            ['第2周', '调度器、批量导入、特征提取集成', '5天'],
            ['第3周', '监控面板、告警、多机部署测试', '5天'],
            ['第4周', '联调测试、小批量验证（500件）', '5天'],
        ],
        col_widths=[2.5, 8, 2])

    doc.add_heading('9.2 全量执行排期', level=2)
    _add_para(doc, '假设10张卡，每天可处理约720件（10卡 × 3件/小时 × 24h）：')
    _add_table(doc,
        ['周次', '累计完成', '说明'],
        [
            ['第1周', '~5,000', '初期会有一些环境调优'],
            ['第2周', '~10,000', '稳定运行'],
            ['第3周', '~15,000', '中途检查失败任务并补跑'],
            ['第4周', '~20,000', '收尾，处理剩余失败件'],
        ],
        col_widths=[2.5, 3, 8])

    # ====== 十、成本估算 ======
    doc.add_heading('十、成本估算', level=1)

    doc.add_heading('10.1 自建方案', level=2)
    _add_table(doc,
        ['项目', '单价（参考）', '数量', '总价'],
        [
            ['RTX 5090', '¥16,000', '3张（常态）', '¥48,000'],
            ['服务器（双路CPU+128G内存）', '¥25,000', '1台', '¥25,000'],
            ['合计', '', '', '¥73,000'],
        ],
        col_widths=[5, 4, 3, 3])

    doc.add_heading('10.2 云GPU租用（初始全量阶段）', level=2)
    _add_para(doc, '以AutoDL等平台为参考，5090级别约 ¥3~5/卡/小时：')
    _add_code_block(doc, '10张卡 × 30天 × 24小时 × ¥4/h = ¥28,800')
    _add_para(doc,
        '初始全量阶段租用云GPU，全量跑完后释放，'
        '后续用自建的2~3张卡处理增量，是比较经济的做法。')

    # ====== 十一、风险与应对 ======
    doc.add_heading('十一、风险与应对', level=1)
    _add_table(doc,
        ['风险', '影响', '应对措施'],
        [
            ['部分配件图片质量差', 'COLMAP失败，该配件重建失败',
             '记录失败原因，人工补拍后重试'],
            ['GPU长时间满载过热降频', '单件耗时增加',
             '控制GPU温度，必要时降低功耗墙'],
            ['网络不稳致图片下载失败', '任务失败',
             '重试机制 + 本地缓存'],
            ['中间文件撑爆磁盘', 'Worker无法运行',
             '定时清理 + 磁盘告警'],
            ['训练器版本更新致结果不一致', '新旧模型质量差异',
             '锁定训练器版本，统一镜像'],
        ],
        col_widths=[4.5, 4.5, 5],
        header_bg='B71C1C')

    # ====== 保存 ======
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.save(output_path)
    print(f'\n✅ Word 文档已生成: {output_path}')


# ===========================================================================
# 主入口
# ===========================================================================

def main():
    _setup_font()

    img_dir = 'docs'
    os.makedirs(img_dir, exist_ok=True)

    arch_img = os.path.join(img_dir, 'sched_architecture.png')
    deploy_img = os.path.join(img_dir, 'sched_deployment.png')
    flow_img = os.path.join(img_dir, 'sched_worker_flow.png')

    print('正在绘制架构图...')
    draw_architecture(arch_img)
    draw_deployment(deploy_img)
    draw_worker_flow(flow_img)

    print('正在生成 Word 文档...')
    output = os.path.join(img_dir, '3D重建长算力任务调度技术方案.docx')
    build_word(arch_img, deploy_img, flow_img, output)


if __name__ == '__main__':
    main()
