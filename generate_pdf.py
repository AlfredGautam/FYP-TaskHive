"""
Generate TaskHive_Documentation.pdf from TaskHive_Documentation.md
Uses fpdf2 (pure Python, no native deps).
Run:  python generate_pdf.py
"""

import re, textwrap
from fpdf import FPDF

MD_FILE = "TaskHive_Documentation.md"
PDF_FILE = "TaskHive_Documentation.pdf"

# ---------- colours ----------
C_TEAL   = (14, 116, 144)
C_DARK   = (26, 26, 46)
C_GRAY   = (80, 80, 100)
C_WHITE  = (255, 255, 255)
C_LIGHT  = (240, 249, 255)
C_TH_BG  = (14, 116, 144)   # table header
C_CODE   = (30, 41, 59)

class PDF(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 8, "TaskHive - Feature & Workflow Documentation", align="L")
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def chapter_title(self, level, text):
        sizes = {1: 22, 2: 16, 3: 13, 4: 11}
        sz = sizes.get(level, 11)
        self.ln(4 if level > 2 else 8)
        self.set_font("Helvetica", "B", sz)
        self.set_text_color(*C_TEAL if level <= 2 else C_DARK)
        self.multi_cell(0, sz * 0.55, text)
        if level <= 2:
            self.set_draw_color(*C_TEAL)
            self.set_line_width(0.6 if level == 1 else 0.3)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def body_text(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*C_DARK)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def bold_text(self, text):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*C_DARK)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def bullet(self, text, indent=6):
        x = self.get_x()
        self.set_x(x + indent)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*C_DARK)
        w = self.w - self.l_margin - self.r_margin - indent
        self.cell(4, 5.5, chr(8226))
        self.multi_cell(w - 4, 5.5, " " + text)

    def code_block(self, text):
        self.ln(2)
        self.set_fill_color(*C_CODE)
        self.set_text_color(226, 232, 240)
        self.set_font("Courier", "", 8)
        lines = text.split("\n")
        for line in lines:
            safe = line.encode("latin-1", "replace").decode("latin-1")
            self.cell(0, 4.5, "  " + safe, fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*C_DARK)
        self.ln(2)

    def render_table(self, headers, rows):
        self.ln(2)
        col_count = len(headers)
        usable = self.w - self.l_margin - self.r_margin
        col_w = usable / col_count

        # header
        self.set_fill_color(*C_TH_BG)
        self.set_text_color(*C_WHITE)
        self.set_font("Helvetica", "B", 9)
        for h in headers:
            self.cell(col_w, 7, h.strip(), border=1, fill=True, align="L")
        self.ln()

        # rows
        self.set_font("Helvetica", "", 9)
        for i, row in enumerate(rows):
            if i % 2 == 0:
                self.set_fill_color(*C_LIGHT)
            else:
                self.set_fill_color(*C_WHITE)
            self.set_text_color(*C_DARK)
            for cell_text in row:
                safe = cell_text.strip().encode("latin-1", "replace").decode("latin-1")
                self.cell(col_w, 6, safe, border=1, fill=True, align="L")
            self.ln()
        self.ln(2)


def strip_md_formatting(text):
    """Remove basic markdown inline formatting."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    return text.strip()


def parse_and_render(pdf, md_text):
    lines = md_text.split("\n")
    i = 0
    in_code = False
    code_buf = []

    while i < len(lines):
        line = lines[i]

        # fenced code block
        if line.strip().startswith("```"):
            if in_code:
                pdf.code_block("\n".join(code_buf))
                code_buf = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        stripped = line.strip()

        # blank line
        if not stripped:
            i += 1
            continue

        # horizontal rule
        if stripped in ("---", "***", "___"):
            pdf.ln(4)
            pdf.set_draw_color(*C_TEAL)
            pdf.set_line_width(0.5)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(4)
            i += 1
            continue

        # headings
        hm = re.match(r'^(#{1,4})\s+(.+)', stripped)
        if hm:
            level = len(hm.group(1))
            title = strip_md_formatting(hm.group(2))
            pdf.chapter_title(level, title)
            i += 1
            continue

        # table
        if "|" in stripped and i + 1 < len(lines) and re.match(r'^\|[\s\-:|]+\|', lines[i + 1].strip()):
            headers = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2  # skip header + separator
            rows = []
            while i < len(lines) and "|" in lines[i].strip() and lines[i].strip().startswith("|"):
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                # pad row if needed
                while len(row) < len(headers):
                    row.append("")
                rows.append(row[:len(headers)])
                i += 1
            pdf.render_table(headers, rows)
            continue

        # bullet
        bm = re.match(r'^[-*]\s+(.+)', stripped)
        if bm:
            pdf.bullet(strip_md_formatting(bm.group(1)))
            i += 1
            continue

        # numbered list
        nm = re.match(r'^\d+\.\s+(.+)', stripped)
        if nm:
            pdf.bullet(strip_md_formatting(nm.group(1)))
            i += 1
            continue

        # bold-only line
        bold_m = re.match(r'^\*\*(.+)\*\*$', stripped)
        if bold_m:
            pdf.bold_text(strip_md_formatting(bold_m.group(1)))
            i += 1
            continue

        # normal paragraph
        pdf.body_text(strip_md_formatting(stripped))
        i += 1


# ---------- main ----------
with open(MD_FILE, encoding="utf-8") as f:
    md_text = f.read()

pdf = PDF("P", "mm", "A4")
pdf.alias_nb_pages()
pdf.set_auto_page_break(auto=True, margin=18)
pdf.add_page()

# Cover page
pdf.ln(40)
pdf.set_font("Helvetica", "B", 36)
pdf.set_text_color(*C_TEAL)
pdf.cell(0, 16, "TaskHive", align="C", new_x="LMARGIN", new_y="NEXT")

pdf.set_font("Helvetica", "", 14)
pdf.set_text_color(*C_GRAY)
pdf.cell(0, 10, "Complete Feature & Workflow Documentation", align="C", new_x="LMARGIN", new_y="NEXT")

pdf.ln(10)
pdf.set_draw_color(*C_TEAL)
pdf.set_line_width(1)
mid = pdf.w / 2
pdf.line(mid - 40, pdf.get_y(), mid + 40, pdf.get_y())

pdf.ln(15)
pdf.set_font("Helvetica", "", 11)
pdf.set_text_color(*C_GRAY)
pdf.cell(0, 7, "Team Collaboration & Project Management Platform", align="C", new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 7, "Final Year Project", align="C", new_x="LMARGIN", new_y="NEXT")
pdf.ln(5)
pdf.cell(0, 7, "March 2026", align="C", new_x="LMARGIN", new_y="NEXT")

pdf.add_page()
parse_and_render(pdf, md_text)

pdf.output(PDF_FILE)
print(f"PDF generated successfully: {PDF_FILE}")
