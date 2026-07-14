#!/usr/bin/env python3
"""
generate_source_pdfs.py — Source code to PDF converter

任意のディレクトリ配下のソースファイルを、シンタックスハイライト・
行番号付きの統合 PDF に変換する。複数拡張子に対応。

使用例:
    python generate_source_pdfs.py ../stockChecker
    python generate_source_pdfs.py ../webapp -e .py,.js,.tsx -o webapp.pdf
    python generate_source_pdfs.py . --exclude-dir node_modules,venv --title "My Project"
"""

import os
import argparse
from pathlib import Path
from datetime import datetime

from fpdf import FPDF
from pygments import lex
from pygments.lexers import get_lexer_for_filename, PythonLexer
from pygments.token import Token


# ── 定数 ──────────────────────────────────────────────────────────

TOKEN_COLORS = {
    Token.Comment.Special:     (0, 0, 0),
    Token.Comment.Preproc:     (128, 0, 0),
    Token.Comment:             (64, 128, 128),
    Token.String.Doc:          (64, 128, 128),
    Token.String:              (186, 33, 33),
    Token.Number:              (0, 100, 0),
    Token.Keyword.Type:        (128, 128, 0),
    Token.Keyword.Constant:    (128, 128, 0),
    Token.Keyword.Declaration: (0, 80, 0),
    Token.Keyword.Namespace:   (0, 80, 0),
    Token.Keyword.Reserved:    (0, 80, 0),
    Token.Keyword:             (0, 80, 0),
    Token.Name.Function:       (0, 0, 200),
    Token.Name.Class:          (0, 0, 200),
    Token.Name.Decorator:      (128, 0, 128),
    Token.Name.Builtin:        (0, 128, 128),
    Token.Name.Exception:      (180, 100, 0),
    Token.Operator:            (80, 80, 80),
    Token.Punctuation:         (80, 80, 80),
}

DEFAULT_EXCLUDE = {
    "__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "venv", ".venv", ".env", "env",
    "node_modules", ".svn", ".hg", "dist", "build", ".tox",
}

MARGIN_TOP    = 18
MARGIN_BOTTOM = 18
MARGIN_LEFT   = 16
MARGIN_RIGHT  = 16
LINENO_WIDTH  = 9


def get_token_color(token_type):
    for pattern, color in TOKEN_COLORS.items():
        if token_type in pattern:
            return color
    return (0, 0, 0)


def is_token_bold(token_type):
    return (
        token_type in Token.Keyword
        or token_type in Token.Name.Function
        or token_type in Token.Name.Class
        or token_type in Token.Name.Decorator
    )


def get_lexer_for_file(filename):
    try:
        return get_lexer_for_filename(filename, stripall=True)
    except Exception:
        return PythonLexer(stripall=True)


def collect_files(target_dir, extensions, exclude_dirs):
    exclude = set(exclude_dirs) | DEFAULT_EXCLUDE
    collected = []
    root = Path(target_dir).resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude]
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in extensions:
                collected.append(os.path.join(dirpath, f))
    collected.sort()
    return collected


# ── PDF 生成 ──────────────────────────────────────────────────────

class SourceCodePDF(FPDF):
    def __init__(self, font_size=8, show_lineno=True, page_size="A4"):
        super().__init__("P", "mm", page_size)
        self.font_size_pt = font_size  # font_size 引数は pt 単位
        self.show_lineno = show_lineno
        self.line_h = font_size * 0.42  # pt → mm 変換済み行高
        self.content_w = self.w - MARGIN_LEFT - MARGIN_RIGHT
        self.code_x = MARGIN_LEFT + (LINENO_WIDTH if show_lineno else 0)
        self.code_w = self.content_w - (LINENO_WIDTH if show_lineno else 0)
        self.c_h = self.h - MARGIN_TOP - MARGIN_BOTTOM

        self.set_auto_page_break(False)
        self.set_margins(MARGIN_LEFT, MARGIN_TOP, MARGIN_RIGHT)
        # MS Gothic (等幅) — ASCII / 日本語両対応で確実に表示
        win_fonts = os.environ.get("SystemRoot", "C:\\Windows") + "\\Fonts"
        self.code_font = "Courier"
        msgothic_path = os.path.join(win_fonts, "msgothic.ttc")
        if os.path.exists(msgothic_path):
            for style_key in ["", "B", "I", "BI"]:
                self.add_font("CodeFont", style_key, msgothic_path)
            self.code_font = "CodeFont"

    def _add_cover(self, title, file_count, date_str, cmd_line):
        self.add_page()
        self.ln(60)
        cw = self.content_w
        self.set_font("Helvetica", "B", 24)
        self.set_text_color(30, 60, 120)
        self.multi_cell(cw, 12, title, align="C")
        self.ln(8)
        self.set_font("Helvetica", "", 11)
        self.set_text_color(100, 100, 100)
        self.multi_cell(cw, 7, f"Generated: {date_str}", align="C")
        self.multi_cell(cw, 7, f"Files: {file_count}", align="C")
        self.ln(6)
        self.set_font(self.code_font, "", 8)
        self.set_text_color(80, 80, 80)
        self.multi_cell(cw, 5, cmd_line, align="C")

    def _add_toc(self, file_list):
        self.add_page()
        cw = self.content_w
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(30, 60, 120)
        self.cell(cw, 10, "Contents", new_x="LMARGIN", new_y="NEXT")
        self.ln(4)
        self.set_draw_color(210, 210, 210)
        self.line(MARGIN_LEFT, self.get_y(), self.w - MARGIN_RIGHT, self.get_y())
        self.ln(4)

        self.set_font(self.code_font, "", 7)
        self.set_text_color(50, 50, 50)
        for i, fpath in enumerate(file_list, 1):
            if self.get_y() > self.c_h - 6:
                self.add_page()
            self.set_x(MARGIN_LEFT + 3)
            self.cell(0, 4.5, f"{fpath}")

    def _file_header(self, rel_path, line_count, byte_count):
        cw = self.content_w
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(30, 60, 120)
        self.cell(cw, 8, os.path.basename(rel_path), new_x="LMARGIN", new_y="NEXT")
        self.set_font(self.code_font, "", 7)
        self.set_text_color(130, 130, 130)
        self.cell(cw, 4.5, rel_path, new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 7)
        self.cell(cw, 4, f"{line_count} lines  |  {byte_count:,} bytes", new_x="LMARGIN", new_y="NEXT")
        self.ln(1.5)
        self.set_draw_color(210, 210, 210)
        self.line(MARGIN_LEFT, self.get_y(), self.w - MARGIN_RIGHT, self.get_y())
        self.ln(2.5)

    def _render_line(self, tokens):
        """1 行分のトークンを色付きで書き出す。"""
        x0 = self.get_x()
        for token_type, text in tokens:
            r, g, b = get_token_color(token_type)
            self.set_text_color(r, g, b)
            style = "B" if is_token_bold(token_type) else ""
            self.set_font(self.code_font, style, self.font_size_pt)

            remaining = self.code_w - (self.get_x() - x0)
            if remaining <= 0:
                break

            tw = self.get_string_width(text)
            if tw <= remaining:
                self.cell(tw, self.line_h, text)
            else:
                for j in range(len(text)):
                    if self.get_string_width(text[:j] + "...") > remaining:
                        self.cell(0, self.line_h, text[:max(j - 1, 0)] + "...")
                        break
                else:
                    self.cell(0, self.line_h, text)
                break

    def _code_break(self):
        if self.get_y() > self.h - MARGIN_BOTTOM - self.line_h:
            self.add_page()
            return True
        return False

    def add_source_file(self, filepath, rel_path):
        """1 ファイルを PDF に追加し、開始・終了ページ番号を返す。"""
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()

        self.add_page()
        cw = self.content_w
        start_page = self.page_no()

        lines = source.split("\n")
        line_count = len(lines)
        byte_count = os.path.getsize(filepath)
        self._file_header(rel_path, line_count, byte_count)

        lexer = get_lexer_for_file(filepath)
        all_tokens = list(lex(source, lexer))

        lineno = 0
        buf = []

        def flush():
            nonlocal lineno
            lineno += 1
            self._code_break()
            self.set_x(MARGIN_LEFT)
            if self.show_lineno:
                self.set_font("Helvetica", "", self.font_size_pt)
                self.set_text_color(190, 190, 190)
                self.cell(LINENO_WIDTH, self.line_h, f"{lineno:>4d}", align="R")
            self.set_x(self.code_x)
            if buf:
                self._render_line(buf)
            self.ln(self.line_h)

        for tt, txt in all_tokens:
            for i, part in enumerate(txt.split("\n")):
                if i > 0:
                    flush()
                    buf.clear()
                if part:
                    buf.append((tt, part))

        if buf or lineno < line_count:
            flush()

        end_page = self.page_no()
        return start_page, end_page

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def _add_index(self, file_pages):
        self.add_page()
        cw = self.content_w
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(30, 60, 120)
        self.cell(cw, 10, "File Index", new_x="LMARGIN", new_y="NEXT")
        self.ln(4)
        self.set_draw_color(210, 210, 210)
        self.line(MARGIN_LEFT, self.get_y(), self.w - MARGIN_RIGHT, self.get_y())
        self.ln(4)

        for fpath, (sp, ep) in file_pages:
            if self.get_y() > self.c_h - 6:
                self.add_page()
                cw = self.content_w
                self.set_font("Helvetica", "B", 14)
                self.set_text_color(30, 60, 120)
                self.cell(cw, 8, "File Index (cont.)", new_x="LMARGIN", new_y="NEXT")
                self.ln(3)
            self.set_x(MARGIN_LEFT + 3)
            self.set_font(self.code_font, "", 7)
            self.set_text_color(50, 50, 50)
            label_w = self.content_w - 14
            self.cell(label_w, 4.5, fpath)
            self.set_font("Helvetica", "", 7)
            self.set_text_color(150, 150, 150)
            page_str = f"{sp}" if sp == ep else f"{sp}-{ep}"
            self.cell(10, 4.5, page_str, align="R", new_x="LMARGIN", new_y="NEXT")


# ── CLI ───────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Convert source code files into a syntax-highlighted PDF.",
    )
    p.add_argument(
        "target_dir", nargs="?", default=".",
        help="Target directory (default: current directory)",
    )
    p.add_argument(
        "-e", "--ext", default=".py",
        help="Comma-separated file extensions (default: .py)",
    )
    p.add_argument(
        "-o", "--output", default="source_code.pdf",
        help="Output PDF path (default: source_code.pdf)",
    )
    p.add_argument(
        "--exclude-dir", default="",
        help="Additional directories to exclude (comma-separated)",
    )
    p.add_argument(
        "--title", default="Source Code Documentation",
        help="Cover page title",
    )
    p.add_argument(
        "--font-size", type=int, default=8,
        help="Code font size in points (default: 8)",
    )
    p.add_argument(
        "--page-size", default="A4",
        help="PDF page size (default: A4)",
    )
    p.add_argument(
        "--no-line-numbers", action="store_true",
        help="Hide line numbers",
    )
    return p.parse_args()


def main():
    args = parse_args()

    extensions = {e.strip().lower() for e in args.ext.split(",") if e.strip()}
    exclude = [d.strip() for d in args.exclude_dir.split(",") if d.strip()] if args.exclude_dir else []

    files = collect_files(args.target_dir, extensions, exclude)
    if not files:
        print("No matching files found.")
        return

    print(f"Collected {len(files)} file(s)")

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    cmd_line = f"$ generate_source_pdfs.py {args.target_dir} -e {args.ext} -o {args.output}"

    pdf = SourceCodePDF(
        font_size=args.font_size,
        show_lineno=not args.no_line_numbers,
        page_size=args.page_size,
    )
    pdf.alias_nb_pages()

    # 1) Cover
    pdf._add_cover(args.title, len(files), date_str, cmd_line)

    # 2) TOC (file names only, no page numbers)
    rel_list = []
    root = Path(args.target_dir).resolve()
    for fp in files:
        rel_list.append(os.path.relpath(fp, root.parent))
    pdf._add_toc(rel_list)

    # 3) Source files — track actual page numbers
    file_pages = []
    for fp in files:
        rel = os.path.relpath(fp, root.parent)
        print(f"  {rel}")
        sp, ep = pdf.add_source_file(fp, rel)
        file_pages.append((rel, (sp, ep)))

    # 4) File index at end (with actual page numbers)
    pdf._add_index(file_pages)

    pdf.output(args.output)
    print(f"\nDone! {len(files)} files, {pdf.page_no()} pages -> {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
