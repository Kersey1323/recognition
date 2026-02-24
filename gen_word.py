import os
import re
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

def create_docx():
    files = [
        'docs/technical_detailed_solution.md',
        'docs/technical_extension_p1.md',
        'docs/technical_extension_p2.md'
    ]
    
    doc = Document()
    
    # Setup document style for Chinese characters
    style = doc.styles['Normal']
    style.font.name = 'SimSun'
    style.element.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')
    style.font.size = Pt(12)
    
    for file_path in files:
        if not os.path.exists(file_path):
            continue
            
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        in_code_block = False
        
        for line in lines:
            line = line.strip('\n')
            
            # Handle code blocks manually
            if line.startswith('```'):
                in_code_block = not in_code_block
                continue
                
            if in_code_block:
                p = doc.add_paragraph(line)
                p.style.font.name = 'Consolas'
                continue
                
            stripped_line = line.strip()
            
            if not stripped_line:
                continue
                
            # Headers parsing
            if stripped_line.startswith('# '):
                doc.add_heading(stripped_line[2:], level=1)
            elif stripped_line.startswith('## '):
                doc.add_heading(stripped_line[3:], level=2)
            elif stripped_line.startswith('### '):
                doc.add_heading(stripped_line[4:], level=3)
            elif stripped_line.startswith('#### '):
                doc.add_heading(stripped_line[5:], level=4)
            elif stripped_line.startswith('- ') or stripped_line.startswith('* '):
                # Apply bold processing on list items
                p = doc.add_paragraph(style='List Bullet')
                text = stripped_line[2:]
                add_formatted_text(p, text)
            else:
                p = doc.add_paragraph()
                add_formatted_text(p, stripped_line)
                
    output_path = 'docs/动车配件图像识别与三维数字孪生系统技术方案.docx'
    doc.save(output_path)
    print(f"Document saved to {output_path}")

def add_formatted_text(paragraph, text):
    """Basic markdown bold '**' or '__' and code '`' parser to docx runs"""
    # Split text by bold markers
    parts = re.split(r'(\*\*.*?\*\*|`.*?`)', text)
    for part in parts:
        if part.startswith('**') and part.endswith('**'):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith('`') and part.endswith('`'):
            run = paragraph.add_run(part[1:-1])
            run.font.name = 'Consolas'
        else:
            p_text = part.replace('*', '') # strip leftover asterisks
            paragraph.add_run(p_text)

if __name__ == '__main__':
    create_docx()
