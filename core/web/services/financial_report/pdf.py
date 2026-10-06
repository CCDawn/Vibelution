"""Bounded local PDF rendering for completed financial research reports."""

from __future__ import annotations

import os
import re
import threading
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape as escape_xml

MAX_PDF_TEXT_CHARS = 250_000
MAX_PDF_METADATA_CHARS = 400
MAX_PDF_BYTES = 1_500_000
MAX_PDF_PAGES = 200
MAX_PDF_BLOCKS = 10_000
MAX_PDF_TABLE_COLUMNS = 16
MAX_PDF_TABLE_ROWS = 5_000

_FONT_LOCK = threading.Lock()
_FONT_VARIANTS = (
    ("msyh.ttc", 0, "VibelutionFinancialReportYaHei"),
    ("simsun.ttc", 0, "VibelutionFinancialReportSong"),
    ("simhei.ttf", 0, "VibelutionFinancialReportHei"),
    ("Deng.ttf", 0, "VibelutionFinancialReportDeng"),
)
_EMOJI_FONT = ("seguiemj.ttf", 0, "VibelutionFinancialReportEmoji")
_INLINE = re.compile(
    r"(?P<code>`[^`\n]+`)|(?P<strong>\*\*.+?\*\*|__.+?__)|"
    r"(?P<strike>~~.+?~~)|(?P<em>\*[^*\n]+\*|_[^_\n]+_)|"
    r"(?P<link>\[[^\]\n]{1,500}\]\(https?://[^\s)<>]{1,2048}\))"
)
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_UNORDERED = re.compile(r"^\s{0,3}[-+*]\s+(.+)$")
_ORDERED = re.compile(r"^\s{0,3}(\d+)[.)]\s+(.+)$")


class FinancialPdfUnavailable(ValueError):
    """The local environment cannot render a readable financial report PDF."""


class FinancialPdfTooLarge(ValueError):
    """The report exceeds the bounded PDF renderer's content or output budget."""


def _font_candidates() -> tuple[tuple[Path, int, str], ...]:
    windows_root = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if not windows_root:
        return ()
    fonts = Path(windows_root) / "Fonts"
    return tuple(
        (fonts / filename, subfont_index, font_name)
        for filename, subfont_index, font_name in _FONT_VARIANTS
    )


def _ensure_fonts(required_text: str) -> tuple[str, str | None, frozenset[str]]:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFError, TTFont
    except ImportError:
        raise FinancialPdfUnavailable("本机未安装 PDF 排版组件") from None

    with _FONT_LOCK:
        registered = set(pdfmetrics.getRegisteredFontNames())
        for path, subfont_index, font_name in _font_candidates():
            try:
                if not path.is_file():
                    continue
                if font_name in registered:
                    font = pdfmetrics.getFont(font_name)
                else:
                    font = TTFont(font_name, str(path), subfontIndex=subfont_index)
                    pdfmetrics.registerFont(font)
                    registered.add(font_name)
                char_widths = getattr(font.face, "charWidths", {})
                missing = frozenset(
                    character
                    for character in required_text
                    if character not in "\r\n\t " and ord(character) not in char_widths
                )
                pdfmetrics.registerFontFamily(
                    font_name,
                    normal=font_name,
                    bold=font_name,
                    italic=font_name,
                    boldItalic=font_name,
                )
                if not missing:
                    return font_name, None, frozenset()

                emoji_path = path.parent / _EMOJI_FONT[0]
                emoji_name = _EMOJI_FONT[2]
                if emoji_name not in registered and emoji_path.is_file():
                    emoji_font = TTFont(
                        emoji_name, str(emoji_path), subfontIndex=_EMOJI_FONT[1]
                    )
                    pdfmetrics.registerFont(emoji_font)
                    registered.add(emoji_name)
                if emoji_name in registered:
                    emoji_font = pdfmetrics.getFont(emoji_name)
                    emoji_widths = getattr(emoji_font.face, "charWidths", {})
                    if all(ord(character) in emoji_widths for character in missing):
                        return font_name, emoji_name, missing
            except (OSError, ValueError, KeyError, TypeError, TTFError):
                continue
    raise FinancialPdfUnavailable(
        "未找到覆盖报告字符的可嵌入中文字体，无法生成可读 PDF"
    ) from None


def _validate_text(value: str) -> str:
    for character in value:
        codepoint = ord(character)
        valid_xml = (
            codepoint in {0x09, 0x0A, 0x0D}
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        ) and codepoint & 0xFFFF not in {0xFFFE, 0xFFFF}
        if not valid_xml:
            raise FinancialPdfUnavailable("PDF 报告包含无法安全排版的控制字符")
    return value


def _escape_fragment(value: str) -> str:
    return escape_xml(value).replace("\t", "&#160;&#160;&#160;&#160;")


def _escape_with_fallback(
    value: str,
    fallback_font_name: str | None,
    fallback_characters: frozenset[str],
    *,
    nonbreaking_spaces: bool = False,
) -> str:
    if not fallback_font_name or not fallback_characters:
        escaped = _escape_fragment(value)
        return escaped.replace(" ", "&#160;") if nonbreaking_spaces else escaped

    parts: list[str] = []
    run: list[str] = []
    in_fallback = False

    def flush() -> None:
        if not run:
            return
        escaped = _escape_fragment("".join(run))
        if nonbreaking_spaces:
            escaped = escaped.replace(" ", "&#160;")
        parts.append(
            f'<font name="{fallback_font_name}">{escaped}</font>'
            if in_fallback
            else escaped
        )
        run.clear()

    for character in value:
        character_uses_fallback = character in fallback_characters
        if run and character_uses_fallback != in_fallback:
            flush()
        in_fallback = character_uses_fallback
        run.append(character)
    flush()
    return "".join(parts)


def _inline_markup(
    value: str,
    font_name: str,
    fallback_font_name: str | None,
    fallback_characters: frozenset[str],
) -> str:
    escape_text = lambda text: _escape_with_fallback(
        text, fallback_font_name, fallback_characters
    )
    parts: list[str] = []
    offset = 0
    for match in _INLINE.finditer(value):
        parts.append(escape_text(value[offset : match.start()]))
        token = match.group(0)
        if match.lastgroup == "code":
            code = _escape_with_fallback(
                token[1:-1],
                fallback_font_name,
                fallback_characters,
                nonbreaking_spaces=True,
            )
            parts.append(f'<font name="{font_name}">{code}</font>')
        elif match.lastgroup == "strong":
            parts.append(f"<b>{escape_text(token[2:-2])}</b>")
        elif match.lastgroup == "strike":
            parts.append(f"<strike>{escape_text(token[2:-2])}</strike>")
        elif match.lastgroup == "em":
            parts.append(f"<i>{escape_text(token[1:-1])}</i>")
        else:
            link = re.fullmatch(r"\[([^\]]+)\]\((https?://[^\s)<>]+)\)", token)
            if link:
                label, url = link.groups()
                parts.append(f"{escape_text(label)} ({escape_text(url)})")
            else:
                parts.append(escape_text(token))
        offset = match.end()
    parts.append(escape_text(value[offset:]))
    return "".join(parts)


def _repair_reportlab_tounicode(pdf_bytes: bytes) -> bytes:
    """Repair ReportLab's odd-length supplementary-codepoint CMap destinations."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        raise FinancialPdfUnavailable("本机未安装 PDF 文本映射组件") from None

    mapping_line = re.compile(
        rb"^(?P<prefix>[ \t]*<[0-9A-Fa-f]{1,4}>[ \t]+)<(?P<destination>[0-9A-Fa-f]{5,6})>(?P<suffix>[ \t]*(?:%[^\r\n]*)?)$"
    )

    def patch_cmap(data: bytes) -> tuple[bytes, bool]:
        in_bfchar = False
        changed = False
        lines: list[bytes] = []
        for line in data.splitlines(keepends=True):
            raw_line = line.rstrip(b"\r\n")
            ending = line[len(raw_line) :]
            if re.search(rb"\bbeginbfchar\b", raw_line):
                in_bfchar = True
            if in_bfchar:
                match = mapping_line.fullmatch(raw_line)
                if match:
                    codepoint = int(match.group("destination"), 16)
                    if 0x10000 <= codepoint <= 0x10FFFF:
                        adjusted = codepoint - 0x10000
                        destination = f"{0xD800 + (adjusted >> 10):04X}{0xDC00 + (adjusted & 0x3FF):04X}".encode(
                            "ascii"
                        )
                        raw_line = (
                            match.group("prefix")
                            + b"<"
                            + destination
                            + b">"
                            + match.group("suffix")
                        )
                        changed = True
            lines.append(raw_line + ending)
            if re.search(rb"\bendbfchar\b", raw_line):
                in_bfchar = False
        return b"".join(lines), changed

    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    changed_any = False
    seen_streams: set[int] = set()
    for page in writer.pages:
        resources = page.get("/Resources")
        fonts = resources.get("/Font") if resources else None
        if not fonts:
            continue
        for font_reference in fonts.values():
            font = font_reference.get_object()
            cmap_reference = font.get("/ToUnicode")
            if not cmap_reference:
                continue
            cmap = cmap_reference.get_object()
            identity = id(cmap)
            if identity in seen_streams:
                continue
            seen_streams.add(identity)
            patched, changed = patch_cmap(cmap.get_data())
            if changed:
                cmap.set_data(patched)
                changed_any = True
    if not changed_any:
        return pdf_bytes
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _table_cells(line: str) -> list[str]:
    value = line.strip().removeprefix("|").removesuffix("|")
    return [cell.strip() for cell in value.split("|")]


def _is_table_separator(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(
        re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells
    )


def _draw_page_number(
    canvas, document, font_name: str, page_width: float, footer_y: float
) -> None:
    page_number = canvas.getPageNumber()
    if page_number > MAX_PDF_PAGES:
        raise FinancialPdfTooLarge("PDF 页数超过限制")
    canvas.saveState()
    canvas.setFillColorRGB(0.4, 0.44, 0.52)
    canvas.setFont(font_name, 8)
    canvas.drawRightString(
        page_width - document.rightMargin, footer_y, f"第 {page_number} 页"
    )
    canvas.restoreState()


def _build_pdf(safe_body: str, safe_title: str, safe_completed_at: str) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        raise FinancialPdfUnavailable("本机未安装 PDF 排版组件") from None

    font_name, fallback_font_name, fallback_characters = _ensure_fonts(
        f"{safe_body}{safe_title}{safe_completed_at}完成时间：第页0123456789-:\u00a0"
    )

    def escape_text(value: str, *, nonbreaking_spaces: bool = False) -> str:
        return _escape_with_fallback(
            value,
            fallback_font_name,
            fallback_characters,
            nonbreaking_spaces=nonbreaking_spaces,
        )

    def inline_markup(value: str) -> str:
        return _inline_markup(value, font_name, fallback_font_name, fallback_characters)

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=17 * mm,
        bottomMargin=18 * mm,
        title=safe_title,
        author="Vibelution",
    )
    body_style = ParagraphStyle(
        "FinancialReportBody",
        fontName=font_name,
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#17202A"),
        alignment=TA_LEFT,
        wordWrap="CJK",
        splitLongWords=1,
        spaceAfter=5,
        allowWidows=0,
        allowOrphans=0,
    )
    title_style = ParagraphStyle(
        "FinancialReportTitle",
        parent=body_style,
        fontSize=19,
        leading=25,
        textColor=colors.HexColor("#173B63"),
        spaceAfter=5,
    )
    meta_style = ParagraphStyle(
        "FinancialReportMeta",
        parent=body_style,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#667085"),
        spaceAfter=4,
    )
    heading_styles = {
        1: ParagraphStyle(
            "FinancialReportH1",
            parent=body_style,
            fontSize=15,
            leading=20,
            textColor=colors.HexColor("#173B63"),
            spaceBefore=12,
            spaceAfter=6,
            keepWithNext=True,
        ),
        2: ParagraphStyle(
            "FinancialReportH2",
            parent=body_style,
            fontSize=12,
            leading=17,
            textColor=colors.HexColor("#214F7A"),
            spaceBefore=10,
            spaceAfter=5,
            keepWithNext=True,
        ),
        3: ParagraphStyle(
            "FinancialReportH3",
            parent=body_style,
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#344054"),
            spaceBefore=8,
            spaceAfter=4,
            keepWithNext=True,
        ),
    }
    table_style = ParagraphStyle(
        "FinancialReportTable",
        parent=body_style,
        fontSize=8,
        leading=11,
        spaceAfter=0,
        allowWidows=0,
        allowOrphans=0,
    )
    code_style = ParagraphStyle(
        "FinancialReportCode",
        parent=body_style,
        fontSize=8,
        leading=11,
        backColor=colors.HexColor("#F3F5F7"),
        borderColor=colors.HexColor("#DCE1E7"),
        borderWidth=0.4,
        borderPadding=5,
        leftIndent=3,
        rightIndent=3,
        spaceBefore=2,
        spaceAfter=5,
    )

    story = [
        Paragraph(escape_text(safe_title), title_style),
        Paragraph(f"完成时间：{escape_text(safe_completed_at)}", meta_style),
        HRFlowable(
            width="100%", thickness=0.6, color=colors.HexColor("#D0D5DD"), spaceAfter=9
        ),
    ]

    def append_flowable(flowable) -> None:
        if len(story) >= MAX_PDF_BLOCKS:
            raise FinancialPdfTooLarge("PDF 内容块数量超过限制")
        story.append(flowable)

    def add_table(rows: list[list[str]]) -> None:
        width = max((len(row) for row in rows), default=0)
        if not width:
            return
        if width > MAX_PDF_TABLE_COLUMNS or len(rows) > MAX_PDF_TABLE_ROWS:
            raise FinancialPdfTooLarge("PDF 表格超过行列限制")
        cells = [
            [
                Paragraph(
                    inline_markup(row[column] if column < len(row) else ""), table_style
                )
                for column in range(width)
            ]
            for row in rows
        ]
        table = Table(
            cells,
            colWidths=[document.width / width] * width,
            repeatRows=1,
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C2CE")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0F6")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#173B63")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        append_flowable(table)
        append_flowable(Spacer(1, 5))

    lines = safe_body.splitlines()
    paragraph: list[str] = []
    code_lines: list[str] | None = None
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            append_flowable(
                Paragraph(
                    "<br/>".join(inline_markup(line) for line in paragraph), body_style
                )
            )
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        if code_lines is not None:
            if line.strip().startswith("```"):
                for code_line in code_lines:
                    escaped_line = escape_text(code_line, nonbreaking_spaces=True)
                    append_flowable(Paragraph(escaped_line or "&#160;", code_style))
                code_lines = None
            else:
                code_lines.append(line)
            index += 1
            continue
        if line.strip().startswith("```"):
            flush_paragraph()
            code_lines = []
            index += 1
            continue
        if (
            "|" in line
            and index + 1 < len(lines)
            and _is_table_separator(lines[index + 1])
        ):
            flush_paragraph()
            rows = [_table_cells(line)]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_table_cells(lines[index]))
                index += 1
            add_table(rows)
            continue
        heading = _HEADING.match(line)
        unordered = _UNORDERED.match(line)
        ordered = _ORDERED.match(line)
        if heading:
            flush_paragraph()
            level = min(len(heading.group(1)), 3)
            append_flowable(
                Paragraph(inline_markup(heading.group(2)), heading_styles[level])
            )
        elif unordered:
            flush_paragraph()
            append_flowable(
                Paragraph(inline_markup(unordered.group(1)), body_style, bulletText="-")
            )
        elif ordered:
            flush_paragraph()
            append_flowable(
                Paragraph(
                    inline_markup(ordered.group(2)),
                    body_style,
                    bulletText=f"{ordered.group(1)}.",
                )
            )
        elif line.startswith(">"):
            flush_paragraph()
            quoted_style = ParagraphStyle(
                "FinancialReportQuote",
                parent=body_style,
                leftIndent=10,
                textColor=colors.HexColor("#475467"),
                borderColor=colors.HexColor("#98A2B3"),
                borderWidth=2,
                borderPadding=5,
            )
            append_flowable(
                Paragraph(inline_markup(line.lstrip()[1:].lstrip()), quoted_style)
            )
        elif re.fullmatch(r"\s{0,3}([-*_]\s*){3,}", line):
            flush_paragraph()
            append_flowable(
                HRFlowable(
                    width="100%",
                    thickness=0.5,
                    color=colors.HexColor("#D0D5DD"),
                    spaceBefore=4,
                    spaceAfter=7,
                )
            )
        elif not line.strip():
            flush_paragraph()
        else:
            paragraph.append(line)
        index += 1

    if code_lines is not None:
        for code_line in code_lines:
            escaped_line = escape_text(code_line, nonbreaking_spaces=True)
            append_flowable(Paragraph(escaped_line or "&#160;", code_style))
    flush_paragraph()

    def draw_page(canvas, doc) -> None:
        _draw_page_number(canvas, doc, font_name, A4[0], 9 * mm)

    try:
        document.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    except (FinancialPdfTooLarge, FinancialPdfUnavailable):
        raise
    except Exception:  # noqa: BLE001 - hide library-specific renderer errors at the PDF boundary.
        raise FinancialPdfUnavailable("本机无法生成研究报告 PDF") from None
    result = _repair_reportlab_tounicode(output.getvalue())
    if len(result) > MAX_PDF_BYTES:
        raise FinancialPdfTooLarge("生成的 PDF 超过大小限制")
    return result


def render_pdf(text: str, *, title: str, completed_at: str) -> bytes:
    """Build a bounded A4 PDF with embedded local CJK TrueType glyphs."""

    if (
        not isinstance(text, str)
        or not isinstance(title, str)
        or not isinstance(completed_at, str)
    ):
        raise FinancialPdfUnavailable("PDF 报告输入格式无效")
    if len(text) > MAX_PDF_TEXT_CHARS:
        raise FinancialPdfTooLarge("PDF 报告内容超过限制")
    if len(title) + len(completed_at) > MAX_PDF_METADATA_CHARS:
        raise FinancialPdfTooLarge("PDF 报告标题或时间超过限制")
    safe_body = _validate_text(text)
    safe_title = _validate_text(title)
    safe_title = safe_title if safe_title.strip() else "股票研究报告"
    safe_completed_at = _validate_text(completed_at)
    if not safe_body.strip():
        raise FinancialPdfUnavailable("PDF 报告内容为空")

    try:
        return _build_pdf(safe_body, safe_title, safe_completed_at)
    except (FinancialPdfUnavailable, FinancialPdfTooLarge):
        raise
    except Exception:  # noqa: BLE001 - expose one stable, safe error for renderer failures.
        raise FinancialPdfUnavailable("本机无法生成研究报告 PDF") from None
