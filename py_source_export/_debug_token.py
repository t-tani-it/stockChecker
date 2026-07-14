#!/usr/bin/env python3
"""Test if token-by-token rendering causes font size drift"""
import os, re, zlib
from fpdf import FPDF

wf = os.environ.get('SystemRoot', 'C:\\Windows') + '\\Fonts'

class TestPDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

def test(font_name, font_path):
    pdf = TestPDF()
    pdf.add_page()
    for s in ['', 'B', 'I', 'BI']:
        pdf.add_font('Code', s, font_path)
    
    MARGIN_LEFT = 16
    code_x = 25
    line_h = 3.36
    
    # Simulate multiple lines with multiple tokens each
    for lineno in range(1, 20):
        if pdf.get_y() > 279:
            pdf.add_page()
        
        pdf.set_x(MARGIN_LEFT)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(190, 190, 190)
        pdf.cell(9, line_h, f"{lineno:>4d}")
        
        pdf.set_x(code_x)
        
        # Multiple tokens per line (simulating pygments highlighting)
        styles_texts = [
            ("", "    "),
            ("B", "def"),
            ("", " "),
            ("", "test_function"),
            ("B", "():"),
        ]
        for style, txt in styles_texts:
            pdf.set_font("Code", style, 8)
            pdf.set_text_color(0, 80, 0)
            tw = pdf.get_string_width(txt)
            if pdf.get_x() - code_x + tw < (210 - 16 - 16 - 9):
                pdf.cell(tw, line_h, txt)
            else:
                break
        
        pdf.ln(line_h)
    
    out = os.path.join(os.path.dirname(__file__), f"_debug_{font_name}_tokens.pdf")
    pdf.output(out)
    
    with open(out, 'rb') as f:
        content = f.read()
    streams = list(re.finditer(rb'stream\s(.+?)\nendstream', content, re.DOTALL))
    for si, sm in enumerate(streams):
        raw = sm.group(1).strip()
        try:
            data = zlib.decompress(raw)
        except:
            data = raw
        sizes = {}
        for m in re.finditer(rb'/(F\d+)\s+([\d.]+)\s+Tf', data):
            fid = m.group(1).decode()
            sz = float(m.group(2))
            if fid not in sizes or sz != sizes[fid][-1]:
                sizes.setdefault(fid, []).append(sz)
        for fid, szlist in sizes.items():
            if len(set(szlist)) > 1:
                print(f'{font_name}: {fid} sizes = {szlist[:5]}')
                break
        else:
            print(f'{font_name}: all sizes consistent')
        break  # only first stream

test('msgothic', os.path.join(wf, 'msgothic.ttc'))
test('consolas', os.path.join(wf, 'consola.ttf'))
test('yumin', os.path.join(wf, 'yumin.ttf'))
