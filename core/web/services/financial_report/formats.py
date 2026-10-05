"""Bounded, dependency-free renderers for financial research exports."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from urllib.parse import urlsplit

_INLINE = re.compile(
    r"(?P<code>`[^`\n]+`)|(?P<strong>\*\*.+?\*\*|__.+?__)|"
    r"(?P<strike>~~.+?~~)|(?P<em>\*[^*\n]+\*|_[^_\n]+_)|"
    r"(?P<link>\[[^\]\n]{1,500}\]\(https?://[^\s)<>]{1,2048}\))"
)
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_UNORDERED = re.compile(r"^\s{0,3}[-+*]\s+(.+)$")
_ORDERED = re.compile(r"^\s{0,3}\d+[.)]\s+(.+)$")

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("w", W)


def _safe_http_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc) and not parsed.username and not parsed.password
    except (TypeError, ValueError):
        return False


def _inline_html(value: str) -> str:
    parts: list[str] = []
    offset = 0
    for match in _INLINE.finditer(value):
        parts.append(html.escape(value[offset : match.start()]))
        token = match.group(0)
        if match.lastgroup == "code":
            parts.append(f"<code>{html.escape(token[1:-1])}</code>")
        elif match.lastgroup == "strong":
            parts.append(f"<strong>{html.escape(token[2:-2])}</strong>")
        elif match.lastgroup == "strike":
            parts.append(f"<del>{html.escape(token[2:-2])}</del>")
        elif match.lastgroup == "em":
            parts.append(f"<em>{html.escape(token[1:-1])}</em>")
        else:
            link = re.fullmatch(r"\[([^\]]+)\]\((https?://[^\s)<>]+)\)", token)
            if link and _safe_http_url(link.group(2)):
                label, url = link.groups()
                parts.append(
                    f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                    f'rel="noopener noreferrer">{html.escape(label)}</a>'
                )
            else:
                parts.append(html.escape(token))
        offset = match.end()
    parts.append(html.escape(value[offset:]))
    return "".join(parts)


def _table_cells(line: str) -> list[str]:
    value = line.strip()
    value = value.removeprefix("|")
    value = value.removesuffix("|")
    return [cell.strip() for cell in value.split("|")]


def _is_table_separator(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def render_print_html(text: str, *, title: str, completed_at: str) -> str:
    """Render a safe standalone printable HTML document; raw HTML is escaped."""

    lines = str(text or "").splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    list_kind = ""
    table_rows: list[list[str]] = []
    table_header_count = 0
    code_lines: list[str] | None = None

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{'<br>\n'.join(_inline_html(line) for line in paragraph)}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            output.append(f"</{list_kind}>")
            list_kind = ""

    def flush_table() -> None:
        nonlocal table_rows, table_header_count
        if not table_rows:
            return
        output.append("<table><thead><tr>")
        for cell in table_rows[0]:
            output.append(f"<th>{_inline_html(cell)}</th>")
        output.append("</tr></thead><tbody>")
        for row in table_rows[1:]:
            output.append("<tr>")
            for index in range(max(len(row), len(table_rows[0]))):
                cell = row[index] if index < len(row) else ""
                output.append(f"<td>{_inline_html(cell)}</td>")
            output.append("</tr>")
        output.append("</tbody></table>")
        table_rows = []
        table_header_count = 0

    def flush_code() -> None:
        nonlocal code_lines
        if code_lines is not None:
            output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
            code_lines = None

    index = 0
    while index < len(lines):
        line = lines[index]
        if code_lines is not None:
            if line.strip().startswith("```"):
                flush_code()
            else:
                code_lines.append(line)
            index += 1
            continue
        if line.strip().startswith("```"):
            flush_paragraph(); close_list(); flush_table(); code_lines = []
            index += 1
            continue
        if "|" in line and index + 1 < len(lines) and _is_table_separator(lines[index + 1]):
            flush_paragraph(); close_list(); flush_table()
            table_rows = [_table_cells(line)]
            table_header_count = 1
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_rows.append(_table_cells(lines[index])); index += 1
            flush_table()
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_paragraph(); close_list(); flush_table()
            level = len(heading.group(1))
            output.append(f"<h{level}>{_inline_html(heading.group(2))}</h{level}>")
        elif _UNORDERED.match(line) or _ORDERED.match(line):
            flush_paragraph(); flush_table()
            kind = "ul" if _UNORDERED.match(line) else "ol"
            if list_kind != kind:
                close_list(); output.append(f"<{kind}>"); list_kind = kind
            item = (_UNORDERED.match(line) or _ORDERED.match(line)).group(1)
            output.append(f"<li>{_inline_html(item)}</li>")
        elif line.startswith(">"):
            flush_paragraph(); close_list(); flush_table()
            output.append(f"<blockquote>{_inline_html(line.lstrip()[1:].lstrip())}</blockquote>")
        elif re.fullmatch(r"\s{0,3}([-*_]\s*){3,}", line):
            flush_paragraph(); close_list(); flush_table(); output.append("<hr>")
        elif not line.strip():
            flush_paragraph(); close_list(); flush_table()
        else:
            close_list(); flush_table(); paragraph.append(line)
        index += 1
    flush_code(); flush_paragraph(); close_list(); flush_table()

    safe_title = html.escape(title, quote=True)
    safe_completed_at = html.escape(completed_at)
    body = "\n".join(output)
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
        f"<title>{safe_title}</title><style>"
        "@page{size:A4;margin:16mm 15mm}*{box-sizing:border-box}body{color:#17202a;font:11pt/1.65 'Microsoft YaHei','Noto Sans CJK SC',sans-serif;margin:0}"
        "main{max-width:900px;margin:0 auto}h1,h2,h3,h4,h5,h6{line-height:1.3;margin:1.5em 0 .55em;page-break-after:avoid}"
        "h1{font-size:21pt;border-bottom:1px solid #d7dce2;padding-bottom:.25em}h2{font-size:16pt}h3{font-size:13pt}"
        "p{margin:.45em 0;orphans:3;widows:3}ul,ol{padding-left:1.5em}li{margin:.25em 0}blockquote{border-left:3px solid #8895a7;margin:1em 0;padding:.1em .8em;color:#485466}"
        "table{border-collapse:collapse;width:100%;margin:1em 0;font-size:9.5pt;page-break-inside:auto}tr{page-break-inside:avoid}th,td{border:1px solid #bac3ce;padding:5px 7px;text-align:left;vertical-align:top}th{background:#edf1f5}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f7;border:1px solid #dce1e7;padding:9px}code{font-family:Consolas,monospace}a{color:#245fa6;overflow-wrap:anywhere}hr{border:0;border-top:1px solid #c8cfd8;margin:1.2em 0}"
        "header{color:#667085;font-size:9pt;border-bottom:1px solid #d7dce2;padding-bottom:8px;margin-bottom:22px}@media screen{body{padding:28px;background:#eef1f4}main{background:white;padding:28px;box-shadow:0 3px 15px #18212b18}}"
        "</style></head><body><main><header>完成时间："
        f"{safe_completed_at}</header>{body}</main></body></html>"
    )


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _append_run(paragraph: ET.Element, value: str, *, bold: bool = False, italic: bool = False, code: bool = False) -> None:
    if not value:
        return
    run = ET.SubElement(paragraph, _w("r"))
    properties = ET.SubElement(run, _w("rPr"))
    fonts = ET.SubElement(properties, _w("rFonts"), {_w("ascii"): "Aptos", _w("hAnsi"): "Aptos", _w("eastAsia"): "Microsoft YaHei"})
    if bold:
        ET.SubElement(properties, _w("b"))
    if italic:
        ET.SubElement(properties, _w("i"))
    if code:
        fonts.set(_w("ascii"), "Consolas"); fonts.set(_w("hAnsi"), "Consolas")
        ET.SubElement(properties, _w("color"), {_w("val"): "475467"})
    text = ET.SubElement(run, _w("t"))
    text.set(f"{{{XML}}}space", "preserve")
    text.text = value


def _append_inline(paragraph: ET.Element, value: str) -> None:
    offset = 0
    for match in _INLINE.finditer(value):
        _append_run(paragraph, value[offset : match.start()])
        token = match.group(0)
        if match.lastgroup == "code":
            _append_run(paragraph, token[1:-1], code=True)
        elif match.lastgroup == "strong":
            _append_run(paragraph, token[2:-2], bold=True)
        elif match.lastgroup == "em":
            _append_run(paragraph, token[1:-1], italic=True)
        elif match.lastgroup == "strike":
            _append_run(paragraph, token[2:-2])
        else:
            link = re.fullmatch(r"\[([^\]]+)\]\((https?://[^\s)<>]+)\)", token)
            if link and _safe_http_url(link.group(2)):
                _append_run(paragraph, f"{link.group(1)} ({link.group(2)})")
            else:
                _append_run(paragraph, token)
        offset = match.end()
    _append_run(paragraph, value[offset:])


def _paragraph(parent: ET.Element, text: str = "", *, heading: int = 0, indent: int = 0, bullet: str = "", code: bool = False) -> ET.Element:
    paragraph = ET.SubElement(parent, _w("p"))
    ppr = ET.SubElement(paragraph, _w("pPr"))
    ET.SubElement(ppr, _w("spacing"), {_w("after"): "100", _w("line"): "300", _w("lineRule"): "auto"})
    if heading:
        ET.SubElement(ppr, _w("keepNext"))
        ET.SubElement(ppr, _w("outlineLvl"), {_w("val"): str(min(8, heading - 1))})
        ET.SubElement(ppr, _w("spacing"), {_w("before"): "220", _w("after"): "100", _w("line"): "300", _w("lineRule"): "auto"})
    if indent:
        ET.SubElement(ppr, _w("ind"), {_w("left"): str(indent)})
    if bullet:
        _append_run(paragraph, bullet + " ", bold=True)
    if code:
        ET.SubElement(ppr, _w("shd"), {_w("fill"): "F2F4F7"})
        ET.SubElement(ppr, _w("ind"), {_w("left"): "160", _w("right"): "160"})
        _append_run(paragraph, text, code=True)
    elif heading:
        run = ET.SubElement(paragraph, _w("r"))
        rpr = ET.SubElement(run, _w("rPr"))
        ET.SubElement(rpr, _w("b"))
        ET.SubElement(rpr, _w("color"), {_w("val"): "1C4778"})
        ET.SubElement(rpr, _w("sz"), {_w("val"): str(max(22, 34 - 3 * heading))})
        ET.SubElement(rpr, _w("rFonts"), {_w("ascii"): "Aptos Display", _w("hAnsi"): "Aptos Display", _w("eastAsia"): "Microsoft YaHei"})
        t = ET.SubElement(run, _w("t")); t.text = text
    else:
        _append_inline(paragraph, text)
    return paragraph


def _append_table(parent: ET.Element, rows: list[list[str]]) -> None:
    if not rows:
        return
    width = max(len(row) for row in rows)
    table = ET.SubElement(parent, _w("tbl"))
    properties = ET.SubElement(table, _w("tblPr"))
    ET.SubElement(properties, _w("tblW"), {_w("w"): "0", _w("type"): "auto"})
    borders = ET.SubElement(properties, _w("tblBorders"))
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        ET.SubElement(borders, _w(edge), {_w("val"): "single", _w("sz"): "4", _w("space"): "0", _w("color"): "B8C2CE"})
    grid = ET.SubElement(table, _w("tblGrid"))
    for _ in range(width):
        ET.SubElement(grid, _w("gridCol"), {_w("w"): str(9360 // width)})
    for row_index, row in enumerate(rows):
        tr = ET.SubElement(table, _w("tr"))
        for column in range(width):
            cell = ET.SubElement(tr, _w("tc"))
            tcpr = ET.SubElement(cell, _w("tcPr"))
            ET.SubElement(tcpr, _w("tcW"), {_w("w"): str(9360 // width), _w("type"): "dxa"})
            if row_index == 0:
                ET.SubElement(tcpr, _w("shd"), {_w("fill"): "EAF0F6"})
            paragraph = ET.SubElement(cell, _w("p"))
            ET.SubElement(paragraph, _w("pPr"))
            _append_inline(paragraph, row[column] if column < len(row) else "")


def render_docx(text: str, *, completed_at: str) -> bytes:
    """Build a standards-compatible OOXML .docx using only the Python stdlib."""

    root = ET.Element(_w("document"))
    body = ET.SubElement(root, _w("body"))
    lines = str(text or "").splitlines()
    paragraph: list[str] = []
    code_lines: list[str] | None = None
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            _paragraph(body, "\n".join(paragraph))
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        if code_lines is not None:
            if line.strip().startswith("```"):
                for code_line in code_lines:
                    _paragraph(body, code_line, code=True)
                code_lines = None
            else:
                code_lines.append(line)
            index += 1
            continue
        if line.strip().startswith("```"):
            flush_paragraph(); code_lines = []; index += 1; continue
        if "|" in line and index + 1 < len(lines) and _is_table_separator(lines[index + 1]):
            flush_paragraph()
            rows = [_table_cells(line)]; index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_table_cells(lines[index])); index += 1
            _append_table(body, rows)
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_paragraph(); _paragraph(body, heading.group(2), heading=len(heading.group(1)))
        elif _UNORDERED.match(line):
            flush_paragraph(); _paragraph(body, _UNORDERED.match(line).group(1), indent=360, bullet="•")
        elif _ORDERED.match(line):
            flush_paragraph(); _paragraph(body, _ORDERED.match(line).group(1), indent=360, bullet="1.")
        elif line.startswith(">"):
            flush_paragraph(); _paragraph(body, line.lstrip()[1:].lstrip(), indent=360)
        elif not line.strip():
            flush_paragraph()
        elif re.fullmatch(r"\s{0,3}([-*_]\s*){3,}", line):
            flush_paragraph(); _paragraph(body, "─" * 28)
        else:
            paragraph.append(line)
        index += 1
    if code_lines is not None:
        for code_line in code_lines:
            _paragraph(body, code_line, code=True)
    flush_paragraph()
    ET.SubElement(body, _w("sectPr"))
    sect = body.find(_w("sectPr"))
    if sect is not None:
        ET.SubElement(sect, _w("pgSz"), {_w("w"): "11906", _w("h"): "16838"})
        ET.SubElement(sect, _w("pgMar"), {_w("top"): "850", _w("right"): "850", _w("bottom"): "850", _w("left"): "850", _w("header"): "425", _w("footer"): "425", _w("gutter"): "0"})

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    )
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", relationships)
        package.writestr("word/document.xml", ET.tostring(root, encoding="utf-8", xml_declaration=True))
    return output.getvalue()
