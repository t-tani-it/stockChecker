#!/usr/bin/env python3
"""Debug font sizing for MS Gothic and alternatives"""
import os, re, zlib
from fpdf import FPDF

wf = os.environ.get('SystemRoot', 'C:\\Windows') + '\\Fonts'

fonts_to_try = [
    ('msgothic.ttc', 'MSGothic'),
    ('meiryo.ttc', 'Meiryo'),
    ('consola.ttf', 'Consolas'),
    ('yumin.ttf', 'Yumin'),
]

for fname, ffamily in fonts_to_try:
    p = os.path.join(wf, fname)
    if not os.path.exists(p):
        print(f'{fname}: not found')
        continue
    
    pdf = FPDF()
    pdf.add_page()
    try:
        pdf.add_font('Code', '', p)
        pdf.set_font('Code', '', 8)
        w = pdf.get_string_width('import streamlit')
        print(f'{fname} ({ffamily}): string_width(import streamlit) = {w:.2f}')
        
        # Render 5 lines
        for i in range(5):
            pdf.set_font('Helvetica', '', 8)  # line number
            pdf.cell(9, 3, f'{i+1:>4d}')
            pdf.set_font('Code', '', 8)  # code
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 3, f'Line {i+1}: import streamlit')
            pdf.ln(4)
        
        outpath = os.path.join(os.path.dirname(__file__), f'_debug_{ffamily}.pdf')
        pdf.output(outpath)
        
        # Check font sizes in stream
        with open(outpath, 'rb') as f:
            content = f.read()
        streams = list(re.finditer(rb'stream\s(.+?)\nendstream', content, re.DOTALL))
        for si, sm in enumerate(streams):
            raw = sm.group(1).strip()
            try:
                data = zlib.decompress(raw)
            except:
                data = raw
            for m in re.finditer(rb'/(F\d+)\s+([\d.]+)\s+Tf', data):
                print(f'  Stream {si}: {m.group(1).decode()} size={m.group(2).decode()}pt')
        print()
    except Exception as e:
        print(f'{fname}: ERROR {e}')
