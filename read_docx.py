import zipfile
import re
import os

folder = 'docs/中车条件和方案'
files = os.listdir(folder)
target = [f for f in files if '技术条件' in f and not f.startswith('~')][0]
path = os.path.join(folder, target)

with zipfile.ZipFile(path) as z:
    xml = z.read('word/document.xml').decode('utf-8')
    text = re.sub(r'<[^>]+>', '', xml)
    idx = text.find('实施内容')
    if idx != -1:
        with open('impl.txt', 'w', encoding='utf-8') as f:
            f.write(text[idx:idx+4000])
