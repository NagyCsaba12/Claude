"""Dokumentum olvasás és készítés.

Olvasás: txt, md, csv, json, html, py/kód, pdf*, docx*, xlsx*, pptx*
Írás:    md, html, txt, docx*   (* opcionális csomag: pypdf, python-docx, openpyxl, python-pptx)
"""
from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path

from tecf.tools import tool

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".ini", ".cfg", ".log", ".py", ".js",
            ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".php", ".rb", ".sh", ".ps1", ".bat",
            ".sql", ".css", ".conf", ".toml", ".kt", ".swift", ".lua", ".pl", ".r", ".vb"}


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|nav|footer|header|svg)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|pre)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\xa0]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n\n", raw).strip()


def _xml_text(data: bytes, tag: str) -> str:
    """Office XML szöveg kinyerése külső csomag nélkül."""
    s = data.decode("utf-8", "replace")
    s = re.sub(rf"</{tag}>", "\n", s)
    return html.unescape(re.sub(r"<[^>]+>", "", s))


def extract_text(path: str | Path) -> str:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in TEXT_EXT:
        return p.read_text(encoding="utf-8", errors="replace")
    if ext in (".html", ".htm"):
        return html_to_text(p.read_text(encoding="utf-8", errors="replace"))
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError("PDF olvasáshoz: pip install pypdf") from e
        return "\n\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    if ext == ".docx":
        with zipfile.ZipFile(p) as z:
            return _xml_text(z.read("word/document.xml"), "w:p")
    if ext == ".pptx":
        with zipfile.ZipFile(p) as z:
            slides = sorted(n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml", n))
            return "\n\n".join(f"--- {n} ---\n" + _xml_text(z.read(n), "a:p") for n in slides)
    if ext == ".xlsx":
        try:
            import openpyxl
        except ImportError as e:
            raise RuntimeError("Excel olvasáshoz: pip install openpyxl") from e
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            out.append(f"--- {ws.title} ---")
            for row in ws.iter_rows(values_only=True):
                out.append("\t".join("" if v is None else str(v) for v in row))
        return "\n".join(out)
    raise RuntimeError(f"Nem támogatott formátum: {ext}")


@tool("Dokumentum beolvasása szövegként (pdf, docx, xlsx, pptx, html, txt, kód...).")
def read_document(path: str, max_chars: int = 30000) -> str:
    return extract_text(path)[:max_chars]


@tool("Dokumentum készítése Markdown tartalomból. Formátum a kiterjesztés alapján: .md, .html, .txt, .docx")
def create_document(path: str, markdown: str, title: str = "") -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ext = p.suffix.lower()
    if ext in (".md", ".txt"):
        p.write_text(markdown, encoding="utf-8")
    elif ext == ".html":
        p.write_text(markdown_to_html(markdown, title or p.stem), encoding="utf-8")
    elif ext == ".docx":
        try:
            import docx
        except ImportError as e:
            raise RuntimeError("Word készítéshez: pip install python-docx") from e
        d = docx.Document()
        if title:
            d.add_heading(title, 0)
        for line in markdown.splitlines():
            m = re.match(r"^(#{1,6})\s+(.*)", line)
            if m:
                d.add_heading(m.group(2), len(m.group(1)))
            elif re.match(r"^\s*[-*]\s+", line):
                d.add_paragraph(re.sub(r"^\s*[-*]\s+", "", line), style="List Bullet")
            elif line.strip():
                d.add_paragraph(line)
        d.save(str(p))
    else:
        raise RuntimeError(f"Nem támogatott kimeneti formátum: {ext}")
    return f"Dokumentum elkészült: {p}"


def markdown_to_html(md: str, title: str) -> str:
    out, in_code, in_list = [], False, False
    for line in md.splitlines():
        if line.startswith("```"):
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        esc = html.escape(line)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)
        esc = re.sub(r"`(.+?)`", r"<code>\1</code>", esc)
        m = re.match(r"^(#{1,6})\s+(.*)", esc)
        li = re.match(r"^\s*[-*]\s+(.*)", esc)
        if li and not in_list:
            out.append("<ul>")
            in_list = True
        if not li and in_list:
            out.append("</ul>")
            in_list = False
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{m.group(2)}</h{n}>")
        elif li:
            out.append(f"<li>{li.group(1)}</li>")
        elif esc.strip():
            out.append(f"<p>{esc}</p>")
    if in_list:
        out.append("</ul>")
    body = "\n".join(out)
    return (f"<!doctype html><html lang='hu'><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            "<style>body{font-family:Segoe UI,sans-serif;max-width:860px;margin:2rem auto;line-height:1.5}"
            "pre{background:#f4f4f4;padding:1rem;overflow:auto}</style></head>"
            f"<body>\n{body}\n</body></html>")
