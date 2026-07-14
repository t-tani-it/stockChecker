#!/usr/bin/env python3
"""Reproduce font size bug with full source rendering"""
import os, re, zlib
from fpdf import FPDF

MARGIN_TOP = 18
MARGIN_BOTTOM = 18
MARGIN_LEFT = 16
MARGIN_RIGHT = 16
LINENO_WIDTH = 9
content_w = 210 - MARGIN_LEFT - MARGIN_RIGHT
code_x = MARGIN_LEFT + LINENO_WIDTH
code_w = content_w - LINENO_WIDTH
font_size = 8
line_h = font_size * 0.42
c_h = 297 - MARGIN_TOP - MARGIN_BOTTOM

wf = os.environ.get('SystemRoot', 'C:\\Windows') + '\\Fonts'

class TestPDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

pdf = TestPDF()
pdf.add_page()
pdf.add_font('Code', '', os.path.join(wf, 'msgothic.ttc'))

# File header
pdf.set_font("Helvetica", "B", 13)
pdf.set_text_color(30, 60, 120)
pdf.cell(content_w, 8, "app.py", new_x="LMARGIN", new_y="NEXT")
pdf.set_font("Code", "", 7)
pdf.set_text_color(130, 130, 130)
pdf.cell(content_w, 4.5, "stockChecker\\app.py", new_x="LMARGIN", new_y="NEXT")
pdf.set_font("Helvetica", "", 7)
pdf.cell(content_w, 4, "125 lines  |  5,081 bytes", new_x="LMARGIN", new_y="NEXT")
pdf.ln(1.5)
pdf.set_draw_color(210, 210, 210)
pdf.line(MARGIN_LEFT, pdf.get_y(), 210 - MARGIN_RIGHT, pdf.get_y())
pdf.ln(2.5)

# Simulate 200 lines of code
for lineno in range(1, 201):
    # Check page break
    if pdf.get_y() > 297 - MARGIN_BOTTOM - line_h:
        pdf.add_page()
    
    pdf.set_x(MARGIN_LEFT)
    # Line number
    pdf.set_font("Helvetica", "", font_size)
    pdf.set_text_color(190, 190, 190)
    pdf.cell(LINENO_WIDTH, line_h, f"{lineno:>4d}", align="R")
    
    # Code
    pdf.set_x(code_x)
    pdf.set_font("Code", "", font_size)
    pdf.set_text_color(0, 0, 0)
    
    text = f"import streamlit as st  # line {lineno}"
    tw = pdf.get_string_width(text)
    pdf.cell(tw, line_h, text)
    
    pdf.ln(line_h)

pdf.output(os.path.join(os.path.dirname(__file__), '_debug_full.pdf'))

# Check font sizes
with open(os.path.join(os.path.dirname(__file__), '_debug_full.pdf'), 'rb') as f:
    content = f.read()
streams = list(re.finditer(rb'stream\s(.+?)\nendstream', content, re.DOTALL))

print(f'Total streams: {len(streams)}')
for si, sm in enumerate(streams):
    raw = sm.group(1).strip()
    try:
        data = zlib.decompress(raw)
    except:
        data = raw
    # Find font sizes
    sizes = set()
    for m in re.finditer(rb'/(F\d+)\s+([\d.]+)\s+Tf', data):
        sizes.add(float(m.group(2)))
    if sizes:
        print(f'Stream {si}: font sizes = {sorted(sizes)}')
