"""工装采集软件方案 → Word 文档生成脚本（精简版）

运行方式: uv run python gen_capture_word.py
输出文件: docs/配件360度全景采集工装软件方案.docx
"""

import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from docx import Document
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

C_BG     = '#1B2838'
C_TEAL   = '#26A69A'
C_CYAN   = '#4DD0E1'
C_ORANGE = '#FF8A65'
C_PURPLE = '#AB47BC'
C_GREEN  = '#66BB6A'
C_BLUE   = '#42A5F5'
C_GRAY   = '#78909C'
C_WHITE  = '#ECEFF1'
C_LGRAY  = '#B0BEC5'
C_AMBER  = '#FFA726'
FONT = 'Microsoft YaHei'


def _setup_font():
    for name in ['Microsoft YaHei', 'SimHei', 'DengXian']:
        try:
            matplotlib.font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams['font.sans-serif'] = [name, 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
            return
        except Exception:
            continue
    plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False


def _box(ax, x, y, w, h, text, fc, fontsize=11, fontcolor='white',
         radius=0.15, ec='none', lw=0, sub=None, bold=False):
    p = FancyBboxPatch((x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=fc, edgecolor=ec, linewidth=lw, zorder=2)
    ax.add_patch(p)
    wt = 'bold' if bold else 'normal'
    ax.text(x+w/2, y+h/2+(0.12 if sub else 0), text,
            ha='center', va='center', fontsize=fontsize,
            color=fontcolor, weight=wt, zorder=3)
    if sub:
        ax.text(x+w/2, y+h/2-0.18, sub, ha='center', va='center',
                fontsize=8, color=fontcolor, alpha=0.75, zorder=3)


def _arrow(ax, x, y1, y2, color=C_LGRAY, lw=2):
    ax.annotate('', xy=(x, y2), xytext=(x, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=lw), zorder=1)


def draw_architecture(out):
    """技术架构图"""
    fig, ax = plt.subplots(figsize=(10, 9))
    fig.patch.set_facecolor(C_BG); ax.set_facecolor(C_BG)
    ax.set_xlim(0, 10); ax.set_ylim(0, 9); ax.axis('off')

    ax.text(5, 8.5, '工装采集软件 · 技术架构', ha='center',
            fontsize=18, color=C_WHITE, weight='bold')

    # 前端
    outer = FancyBboxPatch((0.5, 5.8), 9, 2.2,
        boxstyle="round,pad=0,rounding_size=0.2",
        facecolor='#263238', edgecolor=C_BLUE, linewidth=1.5, zorder=1)
    ax.add_patch(outer)
    ax.text(5, 7.7, 'Vue 3 + TailwindCSS  (WebView2)', ha='center',
            fontsize=13, color=C_BLUE, weight='bold')
    views = [('采集界面', C_TEAL), ('采集记录', C_GREEN),
             ('上传管理', C_AMBER), ('系统设置', C_GRAY)]
    for i, (name, c) in enumerate(views):
        _box(ax, 1+i*2.1, 6.05, 1.8, 0.7, name, c, fontsize=11, bold=True, radius=0.1)

    ax.text(5, 5.5, '▼  Tauri IPC (invoke / event)  ▼', ha='center',
            fontsize=10, color=C_LGRAY, alpha=0.7)

    # 后端
    outer2 = FancyBboxPatch((0.5, 2.2), 9, 2.8,
        boxstyle="round,pad=0,rounding_size=0.2",
        facecolor='#263238', edgecolor=C_ORANGE, linewidth=1.5, zorder=1)
    ax.add_patch(outer2)
    ax.text(5, 4.7, 'Tauri Rust 后端', ha='center',
            fontsize=13, color=C_ORANGE, weight='bold')
    modules = [
        ('设备驱动', C_PURPLE, 'serialport\ncamera SDK'),
        ('视频处理', C_BLUE, 'ffmpeg'),
        ('网络通信', C_TEAL, 'reqwest\ntokio'),
        ('本地存储', C_GREEN, 'rusqlite'),
        ('日志', C_GRAY, 'tracing'),
    ]
    for i, (name, c, sub) in enumerate(modules):
        bx = 0.8 + i*1.75
        _box(ax, bx, 3.5, 1.5, 0.7, name, c, fontsize=10, bold=True, radius=0.1)
        ax.text(bx+0.75, 3.1, sub, ha='center', va='center',
                fontsize=7.5, color=C_LGRAY, alpha=0.8)

    # 外部设备
    devices = [
        (1.5, '串口设备', '转盘 / 灯光', C_PURPLE),
        (4.0, '摄像头', 'USB / 工业相机', C_BLUE),
        (6.5, '服务器', 'REST API', C_TEAL),
    ]
    for dx, name, sub, c in devices:
        _box(ax, dx, 0.5, 2, 0.8, name, c, fontsize=11, bold=True, sub=sub, radius=0.12)
        _arrow(ax, dx+1, 2.2, 1.3+0.8, color=c, lw=1.5)

    fig.tight_layout(pad=0.5)
    fig.savefig(out, dpi=180, bbox_inches='tight', facecolor=C_BG, edgecolor='none')
    plt.close(fig)
    print(f'  架构图 → {out}')


def draw_workflow(out):
    """采集流程图"""
    fig, ax = plt.subplots(figsize=(10, 8))
    fig.patch.set_facecolor(C_BG); ax.set_facecolor(C_BG)
    ax.set_xlim(0, 10); ax.set_ylim(0, 8); ax.axis('off')

    ax.text(5, 7.5, '标准采集流程', ha='center',
            fontsize=18, color=C_WHITE, weight='bold')

    steps = [
        ('① 选择待采集配件', C_BLUE),
        ('② 点击"开始采集"', C_TEAL),
        ('③ 灯光开→转盘转→录制', C_ORANGE),
        ('④ 360°完成→停止录制', C_GREEN),
        ('⑤ 视频回放 · 确认', C_AMBER),
        ('⑥ 提交上传', C_PURPLE),
    ]

    # 上排3个，下排3个，Z字型
    positions = []
    for i in range(3):
        positions.append((0.8 + i*3.0, 5.8))
    for i in range(3):
        positions.append((0.8 + (2-i)*3.0, 4.2))

    for i, ((sx, sy), (text, color)) in enumerate(zip(positions, steps)):
        _box(ax, sx, sy, 2.5, 0.6, text, color, fontsize=11, bold=True, radius=0.1)
        if i < len(steps) - 1:
            nx, ny = positions[i+1]
            if i < 2:
                ax.annotate('', xy=(nx, sy+0.3), xytext=(sx+2.5, sy+0.3),
                    arrowprops=dict(arrowstyle='->', color=C_LGRAY, lw=2), zorder=1)
            elif i == 2:
                ax.annotate('', xy=(nx+1.25, ny+0.6), xytext=(sx+1.25, sy),
                    arrowprops=dict(arrowstyle='->', color=C_LGRAY, lw=2,
                                    connectionstyle='arc3,rad=0.3'), zorder=1)
            else:
                ax.annotate('', xy=(nx+2.5, ny+0.3), xytext=(sx, ny+0.3),
                    arrowprops=dict(arrowstyle='->', color=C_LGRAY, lw=2), zorder=1)

    # 循环
    ax.annotate('', xy=(1.8, 5.8), xytext=(1.8, 4.2),
        arrowprops=dict(arrowstyle='->', color=C_LGRAY, lw=1.5,
                        linestyle='dashed', connectionstyle='arc3,rad=-0.8'),
        zorder=1)
    ax.text(0.15, 5.0, '循环', fontsize=9, color=C_LGRAY, alpha=0.7,
            rotation=90, ha='center', va='center')

    # 标注
    ax.text(5, 3.2, '单件 ≈ 40~60秒    产能 ≈ 60~80件/小时',
            ha='center', fontsize=13, color=C_WHITE, weight='bold',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='#37474F',
                      edgecolor=C_TEAL, linewidth=1.5))

    ax.text(5, 2.4, '■ 蓝色 = 手动操作    ■ 暖色 = 自动执行    ■ 紫色 = 后台处理',
            ha='center', fontsize=9, color=C_LGRAY, alpha=0.7)

    fig.tight_layout(pad=0.5)
    fig.savefig(out, dpi=180, bbox_inches='tight', facecolor=C_BG, edgecolor='none')
    plt.close(fig)
    print(f'  流程图 → {out}')


# ===========================================================================
# Word
# ===========================================================================

def _cell_bg(cell, color_hex):
    s = OxmlElement('w:shd')
    s.set(qn('w:fill'), color_hex.lstrip('#'))
    s.set(qn('w:val'), 'clear')
    cell._tc.get_or_add_tcPr().append(s)

def _table(doc, headers, rows, col_widths=None, header_bg='1565C0'):
    t = doc.add_table(rows=1+len(rows), cols=len(headers))
    t.style = 'Table Grid'; t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]; c.text = ''
        p = c.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(h); r.bold = True; r.font.size = Pt(10)
        r.font.color.rgb = RGBColor(0xFF,0xFF,0xFF)
        r.font.name = FONT; r.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
        _cell_bg(c, header_bg)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            c = t.rows[ri+1].cells[ci]; c.text = ''
            p = c.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(str(val)); r.font.size = Pt(10)
            r.font.name = FONT; r.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
            if ri % 2 == 1: _cell_bg(c, 'F5F5F5')
    if col_widths:
        for i, w in enumerate(col_widths):
            for row in t.rows: row.cells[i].width = Cm(w)
    return t

def _para(doc, text, bold=False, size=11, color=None, align=None, after=6):
    p = doc.add_paragraph()
    if align: p.alignment = align
    p.paragraph_format.space_after = Pt(after)
    r = p.add_run(text); r.font.size = Pt(size)
    r.font.name = FONT; r.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
    r.bold = bold
    if color: r.font.color.rgb = color

def _bullet(doc, items):
    for item in items:
        p = doc.add_paragraph(item, style='List Bullet')
        for r in p.runs:
            r.font.name = FONT; r.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)

def _code(doc, text):
    for line in text.strip().split('\n'):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0); p.paragraph_format.space_before = Pt(0)
        r = p.add_run(line); r.font.size = Pt(9); r.font.name = 'Consolas'
        s = OxmlElement('w:shd')
        s.set(qn('w:fill'), 'ECEFF1'); s.set(qn('w:val'), 'clear')
        p._p.get_or_add_pPr().append(s)


def build(arch_img, flow_img, output):
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = FONT; style.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
    style.font.size = Pt(11)
    for lv in range(1, 5):
        hs = doc.styles[f'Heading {lv}']
        hs.font.name = FONT; hs.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
        hs.font.color.rgb = RGBColor(0x15, 0x65, 0xC0)

    # 封面
    for _ in range(6): doc.add_paragraph()
    _para(doc, '配件360度全景采集', bold=True, size=26,
          align=WD_ALIGN_PARAGRAPH.CENTER, after=4, color=RGBColor(0x15,0x65,0xC0))
    _para(doc, '工装软件方案', bold=True, size=26,
          align=WD_ALIGN_PARAGRAPH.CENTER, after=16, color=RGBColor(0x15,0x65,0xC0))
    _para(doc, 'Tauri 2.x + Vue 3 + TailwindCSS', size=13,
          align=WD_ALIGN_PARAGRAPH.CENTER, after=30, color=RGBColor(0x60,0x60,0x60))
    _para(doc, '2026年2月', size=12, align=WD_ALIGN_PARAGRAPH.CENTER,
          color=RGBColor(0x90,0x90,0x90))
    doc.add_page_break()

    # 一、背景
    doc.add_heading('一、背景与目标', level=1)
    _para(doc,
        '为配合3D重建产线，需要一套运行在 Windows 11 工控机上的工装软件，'
        '控制采集设备（摄像头、转盘/机械臂）对配件做360度视频拍摄，'
        '拍完后上传到服务器触发3D重建和特征提取。')
    _para(doc, '选 Tauri 而不是 Electron：', bold=True)
    _bullet(doc, [
        '包体积小（~10MB），工控机部署方便',
        '内存占用低，不抢占计算资源',
        'Rust 后端直接走串口/USB，无需额外 Native 模块',
        'Win11 自带 WebView2，免装运行时',
    ])

    # 二、功能模块
    doc.add_heading('二、功能模块', level=1)
    _table(doc,
        ['模块', '核心功能'],
        [
            ['设备控制', '转盘启停/调速、灯光开关、设备状态监测'],
            ['视频采集', '摄像头预览、录制控制、视频回放'],
            ['任务管理', '从后端拉取配件列表、选择配件、采集记录、上传管理'],
            ['系统设置', '服务器地址、串口参数、摄像头配置、存储路径'],
        ],
        col_widths=[3, 12])

    # 三、采集流程
    doc.add_heading('三、采集流程', level=1)
    if os.path.exists(flow_img):
        doc.add_picture(flow_img, width=Inches(5.5))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    _para(doc, '操作步骤：', bold=True)
    steps = [
        '从系统中选择待采集的配件（后端接口拉取列表，按物料编码检索）',
        '点击"开始采集"',
        '[自动] 补光灯开启 → 转盘启动 → 摄像头录制',
        '[自动] 转盘完成360° → 停止录制 → 灯光关闭',
        '视频回放，操作员确认质量',
        '确认提交 → 进入上传队列 → 后台上传到服务器',
        '继续下一个配件',
    ]
    for i, s in enumerate(steps, 1):
        p = doc.add_paragraph(f'{i}. {s}')
        for r in p.runs:
            r.font.name = FONT; r.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)

    _para(doc, '单件采集约40~60秒，操作员每小时可完成60~80件。', bold=True)

    # 四、技术架构
    doc.add_heading('四、技术架构', level=1)
    if os.path.exists(arch_img):
        doc.add_picture(arch_img, width=Inches(5.5))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    _para(doc, '前端：Vue 3 + Pinia + Vue Router，四个页面对应四个功能模块。')
    _para(doc, '后端：Rust 负责串口通信、视频采集、分片上传、本地SQLite存储。'
               '所有硬件操作走 Tauri Command 暴露给前端。')
    _para(doc, '与服务器交互：', bold=True)
    _bullet(doc, [
        '拉取配件列表：GET /api/items',
        '上传视频：POST /api/capture/upload（分片上传）',
        '查询重建进度：GET /api/reconstruction/{task_id}/status',
    ])

    # 五、项目结构
    doc.add_heading('五、项目结构', level=1)
    _code(doc,
        'capture-station/\n'
        '├── src-tauri/                 # Rust 后端\n'
        '│   ├── src/\n'
        '│   │   ├── main.rs\n'
        '│   │   ├── commands/          # 设备控制 / 采集 / 上传\n'
        '│   │   ├── device/            # 转盘、摄像头、灯光驱动\n'
        '│   │   ├── video/             # 录制\n'
        '│   │   ├── upload/            # 上传队列、分片续传\n'
        '│   │   └── db.rs              # SQLite\n'
        '│   └── Cargo.toml\n'
        '├── src/                       # Vue 3 前端\n'
        '│   ├── views/                 # 四个主页面\n'
        '│   ├── components/\n'
        '│   ├── stores/\n'
        '│   └── main.ts\n'
        '├── package.json\n'
        '└── tailwind.config.js')

    # 六、排期
    doc.add_heading('六、开发排期', level=1)
    _table(doc,
        ['阶段', '内容', '周期'],
        [
            ['第1周', 'Tauri项目搭建、页面框架、路由', '5天'],
            ['第2周', '串口通信（转盘控制）、摄像头预览', '5天'],
            ['第3周', '视频录制、本地存储', '5天'],
            ['第4周', '上传队列、分片上传、与服务器联调', '5天'],
            ['第5周', '整体联调、操作员试用、bug修复', '5天'],
        ],
        col_widths=[2.5, 8, 2])
    _para(doc, '总计约5周，1~2人。', bold=True)

    os.makedirs(os.path.dirname(output), exist_ok=True)
    doc.save(output)
    print(f'\n✅ Word 文档已生成: {output}')


def main():
    _setup_font()
    d = 'docs'
    os.makedirs(d, exist_ok=True)
    arch = os.path.join(d, 'capture_architecture.png')
    flow = os.path.join(d, 'capture_workflow.png')
    print('正在绘制图表...')
    draw_architecture(arch)
    draw_workflow(flow)
    print('正在生成 Word 文档...')
    build(arch, flow, os.path.join(d, '配件360度全景采集工装软件方案.docx'))

if __name__ == '__main__':
    main()
