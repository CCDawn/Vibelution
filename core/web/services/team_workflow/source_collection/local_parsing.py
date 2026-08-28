"""Secure local parsing chain for managed desktop source roots.

Claim scope: MD/TXT/JSON/HTML/PDF/DOCX/PPTX/XLSX/ZIP/图片 的结构化解析与
安全检测（magic 伪装、宏/OLE、路径逃逸、压缩炸弹、XML 实体、prompt injection
标记）。只做只读解析，不执行任何宏/公式/脚本，不触网。

依赖边界：pypdf + lxml + stdlib zipfile。OOXML 用 stdlib zipfile 取 part，
lxml 实体安全 parser（resolve_entities=False / no_network=True / 拒绝 DTD）。
所有失败以结构化 blocked/warning 返回，绝不抛出未捕获异常崩掉导入链。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

PARSER_VERSION = "managed-local-parsing/1"

MAX_BLOCK_TEXT_CHARS = 4000
MAX_BLOCKS = 400
MAX_SUMMARY_CHARS = 2400
MAX_JSON_DEPTH = 64
MAX_PDF_PAGES = 500
MAX_PDF_PAGE_CHARS = 20_000
MAX_HTML_LINKS = 200
MAX_ZIP_ENTRIES = 500
MAX_ZIP_ENTRY_DEPTH = 16
MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100
MAX_ARCHIVE_PARSE_DEPTH = 3
MAX_XLSX_CELLS_PER_SHEET = 5000
MAX_XLSX_SHEETS = 64
MAX_MEDIA_REFS = 100
MAX_TEXT_CHARS = 200_000

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DRAWING_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
SPREADSHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
OFFICE_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PACKAGE_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

TEXT_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".ndjson", ".html", ".htm"}
OOXML_SUFFIXES = {".docx", ".pptx", ".xlsx"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}

# 二进制可执行/容器 magic；文本类扩展名命中这些一律视为类型伪装。
_EXECUTABLE_MAGIC_KINDS = {"pe_executable", "elf_executable", "ole", "zip", "pdf", "gzip", "rar", "seven_zip", "macho"}

_PROMPT_INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?i)ignore\s+(?:all\s+|any\s+|previous\s+|prior\s+|above\s+|earlier\s+)*(?:instructions?|prompts?|rules?|directions)", "ignore_instructions"),
    (r"(?i)disregard\s+(?:all\s+|previous\s+|above\s+|prior\s+)*(?:instructions?|prompts?|rules?|guidance)", "disregard_instructions"),
    (r"(?i)(?:system|developer|assistant)\s+(?:prompt|message|instructions?)", "system_prompt_reference"),
    (r"(?i)(?:reveal|print|repeat|expose)\s+(?:your\s+|the\s+)?(?:system\s+)?prompt", "prompt_extraction"),
    (r"(?i)(?:忽略|无视|忘记)(?:之前|以上|前面|先前)?(?:的)?(?:指令|指示|提示词|提示|规则|设定)", "ignore_instructions_zh"),
    (r"(?i)jailbreak|developer\s+mode\b|DAN\s+mode\b", "jailbreak_marker"),
)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u00ad]")
_RTL_OVERRIDE_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069]")

_ZIP_WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


class LocalParsingBlocked(Exception):
    """Raised internally when a file must be blocked for security or integrity reasons."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


def _blocked_result(reason: str, detail: str = "") -> dict[str, Any]:
    return {
        "status": "blocked",
        "kind": "",
        "blockedReason": reason,
        "blockedDetail": str(detail)[:500],
        "warnings": [],
        "summaryText": "",
        "blocks": [],
        "meta": {},
        "extracted": [],
    }


def detect_magic_kind(head: bytes) -> str:
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(OLE_MAGIC):
        return "ole"
    if head.startswith(b"MZ"):
        return "pe_executable"
    if head.startswith(b"\x7fELF"):
        return "elf_executable"
    if head.startswith((b"\xfe\xed\xfa\xce", b"\xcf\xfa\xed\xfe")):
        return "macho"
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head.startswith(b"BM"):
        return "bmp"
    if head.startswith(b"\x1f\x8b"):
        return "gzip"
    if head.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "seven_zip"
    if head.startswith(b"%!PS"):
        return "postscript"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "text"
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped.startswith((b"{", b"[")):
        return "json_like"
    sample = head[:512]
    if b"\x00" not in sample:
        return "text"
    # UTF-16 类文本 NUL 密度约 50%；零星 NUL 控制字符仍是文本（交由规范化+告警处理）。
    if sample.count(0) > len(sample) * 0.3:
        return "binary"
    return "text"


def _expected_magic_kinds(suffix: str) -> set[str] | None:
    """返回该扩展名的合法 magic 集合；None 表示只要不是可执行/容器即可。"""

    if suffix == ".pdf":
        return {"pdf"}
    if suffix == ".zip":
        return {"zip"}
    if suffix in OOXML_SUFFIXES:
        return {"zip"}
    if suffix == ".png":
        return {"png"}
    if suffix in {".jpg", ".jpeg"}:
        return {"jpeg"}
    if suffix == ".gif":
        return {"gif"}
    if suffix == ".bmp":
        return {"bmp"}
    return None


def check_type_consistency(suffix: str, head: bytes) -> tuple[str, str]:
    """magic bytes vs 扩展名一致性检测；返回 (magicKind, mismatchReason)。"""

    magic_kind = detect_magic_kind(head)
    expected = _expected_magic_kinds(suffix)
    if expected is not None:
        if magic_kind not in expected:
            return magic_kind, "extension_magic_mismatch"
        return magic_kind, ""
    if magic_kind in _EXECUTABLE_MAGIC_KINDS or magic_kind == "binary":
        return magic_kind, "extension_magic_mismatch"
    return magic_kind, ""


def decode_text_bytes(data: bytes) -> tuple[str, list[str]]:
    """编码探测先例链：utf-8-sig → utf-8 → gb18030 → ignore。"""

    warnings: list[str] = []
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), warnings
        except UnicodeDecodeError:
            warnings.append("text_decode_lossy")
            return data.decode("utf-16", errors="ignore"), warnings
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding), warnings
        except UnicodeDecodeError:
            continue
    warnings.append("text_decode_lossy")
    return data.decode("utf-8", errors="ignore"), warnings


def normalize_text_safety(text: str) -> tuple[str, list[str]]:
    """控制字符规范化与不可见字符清理；返回 (normalized, warnings)。"""

    warnings: list[str] = []
    control_hits = len(_CONTROL_CHARS_RE.findall(text))
    zero_width_hits = len(_ZERO_WIDTH_RE.findall(text))
    rtl_hits = len(_RTL_OVERRIDE_RE.findall(text))
    normalized = _CONTROL_CHARS_RE.sub(" ", text)
    normalized = _ZERO_WIDTH_RE.sub("", normalized)
    normalized = _RTL_OVERRIDE_RE.sub("", normalized)
    if control_hits:
        warnings.append(f"control_chars_normalized:{control_hits}")
    if zero_width_hits:
        warnings.append(f"zero_width_chars_removed:{zero_width_hits}")
    if rtl_hits:
        warnings.append(f"rtl_override_chars_removed:{rtl_hits}")
    return normalized, warnings


def scan_prompt_injection(text: str) -> list[str]:
    """可疑指令标记：只标 warning，不删除内容。"""

    warnings: list[str] = []
    for pattern, name in _PROMPT_INJECTION_PATTERNS:
        match = re.search(pattern, text)
        if match:
            snippet = re.sub(r"\s+", " ", match.group(0))[:80]
            warnings.append(f"prompt_injection_suspicion:{name}:{snippet}")
            if len(warnings) >= 8:
                break
    return warnings


def _safe_xml_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        recover=False,
    )


def _safe_xml_frombytes(data: bytes, *, label: str) -> etree._Element:
    head = data[:65536]
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise LocalParsingBlocked("xml_dtd_rejected", f"{label} declares a DTD or entities")
    try:
        root = etree.fromstring(data, _safe_xml_parser())
    except etree.XMLSyntaxError as exc:
        raise LocalParsingBlocked("xml_parse_failed", f"{label}: {exc}") from exc
    if root is None:
        raise LocalParsingBlocked("xml_parse_failed", f"{label}: empty document")
    return root


def _element_text(element: Any) -> str:
    return " ".join("".join(element.itertext()).split())


def _trim_block_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:MAX_BLOCK_TEXT_CHARS]


def _append_block(blocks: list[dict[str, str]], locator: str, text: str) -> bool:
    cleaned = _trim_block_text(text)
    if not cleaned:
        return False
    if len(blocks) >= MAX_BLOCKS:
        return False
    blocks.append({"locator": locator, "text": cleaned})
    return True


def _summary_from_blocks(blocks: list[dict[str, str]]) -> str:
    parts: list[str] = []
    total = 0
    for block in blocks:
        text = block.get("text", "")
        if not text:
            continue
        parts.append(text)
        total += len(text) + 1
        if total >= MAX_SUMMARY_CHARS:
            break
    return (" ".join(parts))[:MAX_SUMMARY_CHARS]


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path, *, cap_bytes: int = 64 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    read = 0
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            read += len(chunk)
            if read >= cap_bytes:
                break
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Text / JSON / HTML parsers
# ---------------------------------------------------------------------------


def parse_text(data: bytes, *, suffix: str) -> dict[str, Any]:
    text, warnings = decode_text_bytes(data[:MAX_TEXT_CHARS])
    if len(data) > MAX_TEXT_CHARS:
        warnings.append("text_truncated_by_parser")
    normalized, safety_warnings = normalize_text_safety(text)
    warnings.extend(safety_warnings)
    blocks: list[dict[str, str]] = []
    if suffix == ".md":
        for index, line in enumerate(normalized.splitlines()[:MAX_BLOCKS], start=1):
            _append_block(blocks, f"line:{index}", line)
    else:
        paragraph_index = 0
        for paragraph in re.split(r"\n\s*\n", normalized):
            if not paragraph.strip():
                continue
            paragraph_index += 1
            if not _append_block(blocks, f"paragraph:{paragraph_index}", paragraph):
                break
    warnings.extend(scan_prompt_injection(normalized))
    return {
        "status": "parsed",
        "kind": "text",
        "warnings": warnings,
        "blocks": blocks,
        "meta": {"encoding": "detected", "suffix": suffix},
        "summaryText": _summary_from_blocks(blocks),
    }


def _json_depth(value: Any, depth: int = 0) -> int:
    if depth > MAX_JSON_DEPTH:
        return depth
    if isinstance(value, dict):
        return max((_json_depth(item, depth + 1) for item in value.values()), default=depth)
    if isinstance(value, list):
        return max((_json_depth(item, depth + 1) for item in value[:64]), default=depth)
    return depth


def parse_json(data: bytes) -> dict[str, Any]:
    warnings: list[str] = []
    text, decode_warnings = decode_text_bytes(data[:MAX_TEXT_CHARS])
    warnings.extend(decode_warnings)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LocalParsingBlocked("json_invalid", str(exc)) from exc
    depth = _json_depth(payload)
    if depth > MAX_JSON_DEPTH:
        raise LocalParsingBlocked("json_depth_exceeded", f"depth={depth}")
    blocks: list[dict[str, str]] = []
    if isinstance(payload, dict):
        for key, value in list(payload.items())[:MAX_BLOCKS]:
            rendered = json.dumps(value, ensure_ascii=False)[:MAX_BLOCK_TEXT_CHARS] if not isinstance(value, str) else value[:MAX_BLOCK_TEXT_CHARS]
            _append_block(blocks, f"key:{key}", rendered)
    elif isinstance(payload, list):
        for index, item in enumerate(payload[:MAX_BLOCKS], start=1):
            rendered = json.dumps(item, ensure_ascii=False)[:MAX_BLOCK_TEXT_CHARS] if not isinstance(item, str) else item[:MAX_BLOCK_TEXT_CHARS]
            _append_block(blocks, f"item:{index}", rendered)
    else:
        _append_block(blocks, "value:1", str(payload))
    warnings.extend(scan_prompt_injection(text))
    return {
        "status": "parsed",
        "kind": "json",
        "warnings": warnings,
        "blocks": blocks,
        "meta": {"depth": depth},
        "summaryText": _summary_from_blocks(blocks),
    }


def parse_jsonl(data: bytes) -> dict[str, Any]:
    warnings: list[str] = []
    text, decode_warnings = decode_text_bytes(data[:MAX_TEXT_CHARS])
    warnings.extend(decode_warnings)
    blocks: list[dict[str, str]] = []
    line_count = 0
    parse_errors = 0
    depth = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        line_count += 1
        if line_count > MAX_BLOCKS:
            warnings.append("jsonl_line_cap_reached")
            break
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        depth = max(depth, _json_depth(payload))
        rendered = json.dumps(payload, ensure_ascii=False)[:MAX_BLOCK_TEXT_CHARS]
        _append_block(blocks, f"line:{line_count}", rendered)
    if parse_errors:
        warnings.append(f"jsonl_parse_errors:{parse_errors}")
    if depth > MAX_JSON_DEPTH:
        raise LocalParsingBlocked("json_depth_exceeded", f"depth={depth}")
    warnings.extend(scan_prompt_injection(text[:MAX_TEXT_CHARS]))
    return {
        "status": "parsed",
        "kind": "jsonl",
        "warnings": warnings,
        "blocks": blocks,
        "meta": {"lineCount": line_count, "parseErrors": parse_errors},
        "summaryText": _summary_from_blocks(blocks),
    }


def parse_html(data: bytes) -> dict[str, Any]:
    import lxml.html

    warnings: list[str] = []
    decoded_text, decode_warnings = decode_text_bytes(data[:MAX_TEXT_CHARS])
    warnings.extend(decode_warnings)
    try:
        document = lxml.html.document_fromstring(decoded_text)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise LocalParsingBlocked("html_parse_failed", str(exc)) from exc
    if document is None:
        raise LocalParsingBlocked("html_parse_failed", "empty document")
    script_count = len(document.xpath("//script"))
    if script_count:
        warnings.append(f"html_script_tags_removed:{script_count}")
    for element in document.xpath("//script|//style|//iframe|//object|//embed"):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
    title = ""
    title_nodes = document.xpath("//title")
    if title_nodes:
        title = _element_text(title_nodes[0])[:240]
    body_text = document.text_content()
    normalized, safety_warnings = normalize_text_safety(body_text)
    warnings.extend(safety_warnings)
    blocks: list[dict[str, str]] = []
    if title:
        _append_block(blocks, "title", title)
    paragraph_index = 0
    for paragraph in re.split(r"\n\s*\n", normalized):
        if not paragraph.strip():
            continue
        paragraph_index += 1
        if not _append_block(blocks, f"paragraph:{paragraph_index}", paragraph):
            break
    links: list[dict[str, str]] = []
    for anchor in document.xpath("//a[@href]")[:MAX_HTML_LINKS]:
        href = str(anchor.get("href") or "").strip()
        if not href or href.lower().startswith("javascript:"):
            continue
        links.append({"text": _element_text(anchor)[:200], "href": href[:500]})
    warnings.extend(scan_prompt_injection(normalized))
    return {
        "status": "parsed",
        "kind": "html",
        "warnings": warnings,
        "blocks": blocks,
        "meta": {"title": title, "links": links, "scriptCount": script_count},
        "summaryText": _summary_from_blocks(blocks),
    }


# ---------------------------------------------------------------------------
# PDF / image parsers
# ---------------------------------------------------------------------------


def parse_pdf(path: Path) -> dict[str, Any]:
    from pypdf import PdfReader

    warnings: list[str] = []
    blocks: list[dict[str, str]] = []
    meta: dict[str, Any] = {"pageCount": 0, "readable": True}
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 - pypdf raises assorted error types
        warnings.append(f"pdf_corrupt:{type(exc).__name__}")
        meta["readable"] = False
        return {
            "status": "parsed",
            "kind": "pdf",
            "warnings": warnings,
            "blocks": [],
            "meta": meta,
            "summaryText": "",
        }
    if reader.is_encrypted:
        decrypted = False
        try:
            decrypted = bool(reader.decrypt(""))
        except Exception:  # noqa: BLE001
            decrypted = False
        if not decrypted:
            warnings.append("pdf_encrypted_metadata_only")
            meta["readable"] = False
            try:
                meta["pageCount"] = len(reader.pages)
            except Exception:  # noqa: BLE001
                meta["pageCount"] = 0
            return {
                "status": "parsed",
                "kind": "pdf",
                "warnings": warnings,
                "blocks": [],
                "meta": meta,
                "summaryText": "",
            }
        warnings.append("pdf_decrypted_with_empty_password")
    try:
        page_count = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"pdf_corrupt:{type(exc).__name__}")
        meta["readable"] = False
        return {
            "status": "parsed",
            "kind": "pdf",
            "warnings": warnings,
            "blocks": [],
            "meta": meta,
            "summaryText": "",
        }
    meta["pageCount"] = page_count
    if page_count > MAX_PDF_PAGES:
        warnings.append(f"pdf_page_cap_reached:{MAX_PDF_PAGES}")
    for index, page in enumerate(reader.pages[:MAX_PDF_PAGES], start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"pdf_page_extract_failed:{index}:{type(exc).__name__}")
            continue
        normalized, safety = normalize_text_safety(page_text[:MAX_PDF_PAGE_CHARS])
        warnings.extend(safety)
        for locator_index, paragraph in enumerate(re.split(r"\n\s*\n", normalized), start=1):
            if not paragraph.strip():
                continue
            if not _append_block(blocks, f"page:{index}:paragraph:{locator_index}", paragraph):
                break
    warnings.extend(scan_prompt_injection(" ".join(block["text"] for block in blocks[:50])))
    return {
        "status": "parsed",
        "kind": "pdf",
        "warnings": warnings,
        "blocks": blocks,
        "meta": meta,
        "summaryText": _summary_from_blocks(blocks),
    }


def _image_dimensions(head: bytes, magic_kind: str) -> dict[str, int]:
    dims: dict[str, int] = {}
    try:
        if magic_kind == "png" and len(head) >= 24:
            dims = {"width": int.from_bytes(head[16:20], "big"), "height": int.from_bytes(head[20:24], "big")}
        elif magic_kind == "gif" and len(head) >= 10:
            dims = {"width": int.from_bytes(head[6:8], "little"), "height": int.from_bytes(head[8:10], "little")}
        elif magic_kind == "bmp" and len(head) >= 26:
            dims = {"width": int.from_bytes(head[18:22], "little"), "height": int.from_bytes(head[22:26], "little")}
        elif magic_kind == "jpeg":
            offset = 2
            while offset + 9 < len(head):
                if head[offset] != 0xFF:
                    break
                marker = head[offset + 1]
                if marker in {0xC0, 0xC1, 0xC2, 0xC3}:
                    dims = {
                        "height": int.from_bytes(head[offset + 5 : offset + 7], "big"),
                        "width": int.from_bytes(head[offset + 7 : offset + 9], "big"),
                    }
                    break
                segment_length = int.from_bytes(head[offset + 2 : offset + 4], "big")
                offset += 2 + max(segment_length, 2)
    except (ValueError, IndexError):
        return {}
    return {key: value for key, value in dims.items() if value > 0}


def parse_image(head: bytes, *, size_bytes: int, magic_kind: str) -> dict[str, Any]:
    dims = _image_dimensions(head, magic_kind)
    return {
        "status": "parsed",
        "kind": "image",
        "warnings": ["image_metadata_only"],
        "blocks": [],
        "meta": {"magicKind": magic_kind, "sizeBytes": size_bytes, **({"dimensions": dims} if dims else {})},
        "summaryText": "",
    }


# ---------------------------------------------------------------------------
# OOXML parsers (stdlib zipfile + entity-safe lxml)
# ---------------------------------------------------------------------------


def _zip_names(archive: zipfile.ZipFile) -> list[str]:
    return [info.filename for info in archive.infolist() if not info.is_dir()]


def _reject_ooxml_macros(archive: zipfile.ZipFile, *, label: str) -> None:
    """拒绝 vbaProject 宏与 exe/OLE 可执行嵌入对象（其余嵌入对象仅忽略）。"""

    for name in _zip_names(archive):
        lowered = name.lower()
        if "vbaproject" in lowered:
            raise LocalParsingBlocked(f"{label}_macro_rejected", name)
        if "/embeddings/" in f"/{lowered}":
            with archive.open(name) as handle:
                head = handle.read(8)
            if head.startswith((OLE_MAGIC, b"MZ", b"\x7fELF")):
                raise LocalParsingBlocked(f"{label}_embedded_executable_rejected", name)


def _read_zip_part(archive: zipfile.ZipFile, name: str, *, cap_bytes: int = 32 * 1024 * 1024) -> bytes:
    with archive.open(name) as handle:
        data = handle.read(cap_bytes + 1)
    if len(data) > cap_bytes:
        raise LocalParsingBlocked("zip_part_too_large", name)
    return data


def _docx_blocks(root: Any) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    body = root.find(f"{WORD_NS}body")
    paragraphs = table_count = heading_count = 0
    children = list(body) if body is not None else []
    for child in children:
        tag = child.tag
        if tag == f"{WORD_NS}p":
            paragraphs += 1
            text = _element_text(child)
            style = child.find(f"{WORD_NS}pPr/{WORD_NS}pStyle")
            style_value = str(style.get(f"{WORD_NS}val") or "").lower() if style is not None else ""
            if text:
                if style_value.startswith("heading") or style_value == "title":
                    heading_count += 1
                    _append_block(blocks, f"heading:{heading_count}", text)
                else:
                    _append_block(blocks, f"paragraph:{paragraphs}", text)
        elif tag == f"{WORD_NS}tbl":
            table_count += 1
            for row_index, row in enumerate(child.findall(f"{WORD_NS}tr")[:200], start=1):
                cells = [_element_text(cell)[:400] for cell in row.findall(f"{WORD_NS}tc")[:50]]
                row_text = " | ".join(cell for cell in cells if cell)
                if row_text:
                    _append_block(blocks, f"table:{table_count}:row:{row_index}", row_text)
    return blocks


def parse_docx(path: Path) -> dict[str, Any]:
    warnings: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = _zip_names(archive)
        _reject_ooxml_macros(archive, label="docx")
        if "word/document.xml" not in names:
            raise LocalParsingBlocked("docx_document_part_missing", "word/document.xml not found")
        root = _safe_xml_frombytes(_read_zip_part(archive, "word/document.xml"), label="word/document.xml")
    blocks = _docx_blocks(root)
    warnings.extend(scan_prompt_injection(_summary_from_blocks(blocks)))
    return {
        "status": "parsed",
        "kind": "docx",
        "warnings": warnings,
        "blocks": blocks,
        "meta": {"entryCount": len(names), "paragraphCount": sum(1 for block in blocks if block["locator"].startswith("paragraph:"))},
        "summaryText": _summary_from_blocks(blocks),
    }


def _pptx_slide_files(names: list[str], *, prefix: str) -> list[tuple[int, str]]:
    pattern = re.compile(rf"^{prefix}(\d+)\.xml$")
    entries: list[tuple[int, str]] = []
    for name in names:
        match = pattern.match(name)
        if match:
            entries.append((int(match.group(1)), name))
    return sorted(entries)


def _pptx_texts(root: Any) -> list[str]:
    texts: list[str] = []
    for paragraph in root.iter(f"{DRAWING_NS}p"):
        runs = [_element_text(run) for run in paragraph.iter(f"{DRAWING_NS}t")]
        joined = " ".join(part for part in runs if part).strip()
        if joined:
            texts.append(joined)
    return texts


def parse_pptx(path: Path) -> dict[str, Any]:
    warnings: list[str] = []
    blocks: list[dict[str, str]] = []
    media_refs: list[dict[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        names = _zip_names(archive)
        _reject_ooxml_macros(archive, label="pptx")
        if "ppt/presentation.xml" not in names:
            raise LocalParsingBlocked("pptx_presentation_part_missing", "ppt/presentation.xml not found")
        slide_files = _pptx_slide_files(names, prefix="ppt/slides/slide")
        note_files = dict(_pptx_slide_files(names, prefix="ppt/notesSlides/notesSlide"))
        media_names = [name for name in names if name.startswith("ppt/media/")]
        for slide_number, slide_name in slide_files[:MAX_PDF_PAGES]:
            root = _safe_xml_frombytes(_read_zip_part(archive, slide_name), label=slide_name)
            texts = _pptx_texts(root)
            for paragraph_index, text in enumerate(texts[:100], start=1):
                _append_block(blocks, f"slide:{slide_number}:paragraph:{paragraph_index}", text)
            note_name = note_files.get(slide_number)
            if note_name:
                note_root = _safe_xml_frombytes(_read_zip_part(archive, note_name), label=note_name)
                note_texts = _pptx_texts(note_root)
                if note_texts:
                    _append_block(blocks, f"slide:{slide_number}:notes", " ".join(note_texts[:50]))
        for media_name in media_names[:MAX_MEDIA_REFS]:
            media_refs.append({"entry": media_name, "sha256": _hash_file_bytes(_read_zip_part(archive, media_name, cap_bytes=32 * 1024 * 1024))})
    if len(media_names) > MAX_MEDIA_REFS:
        warnings.append(f"media_ref_cap_reached:{MAX_MEDIA_REFS}")
    warnings.extend(scan_prompt_injection(_summary_from_blocks(blocks)))
    return {
        "status": "parsed",
        "kind": "pptx",
        "warnings": warnings,
        "blocks": blocks,
        "meta": {"slideCount": len(slide_files), "mediaRefs": media_refs},
        "summaryText": _summary_from_blocks(blocks),
    }


def _hash_file_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_xlsx(path: Path) -> dict[str, Any]:
    warnings: list[str] = []
    blocks: list[dict[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        names = _zip_names(archive)
        _reject_ooxml_macros(archive, label="xlsx")
        if "xl/workbook.xml" not in names:
            raise LocalParsingBlocked("xlsx_workbook_part_missing", "xl/workbook.xml not found")
        workbook = _safe_xml_frombytes(_read_zip_part(archive, "xl/workbook.xml"), label="xl/workbook.xml")
        rels_map: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in names:
            rels_root = _safe_xml_frombytes(_read_zip_part(archive, "xl/_rels/workbook.xml.rels"), label="xl/_rels/workbook.xml.rels")
            for rel in rels_root.iter(f"{PACKAGE_REL_NS}Relationship"):
                rel_id = str(rel.get("Id") or "")
                target = str(rel.get("Target") or "").lstrip("/")
                if rel_id and target:
                    if target.startswith("xl/"):
                        rels_map[rel_id] = target
                    else:
                        rels_map[rel_id] = f"xl/{target}"
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in names:
            shared_root = _safe_xml_frombytes(_read_zip_part(archive, "xl/sharedStrings.xml"), label="xl/sharedStrings.xml")
            for si in list(shared_root.iter(f"{SPREADSHEET_NS}si"))[:50000]:
                shared_strings.append("".join(si.itertext()))
        sheets = list(workbook.iter(f"{SPREADSHEET_NS}sheet"))[:MAX_XLSX_SHEETS]
        if len(list(workbook.iter(f"{SPREADSHEET_NS}sheet"))) > MAX_XLSX_SHEETS:
            warnings.append(f"xlsx_sheet_cap_reached:{MAX_XLSX_SHEETS}")
        formula_count = 0
        for sheet_index, sheet in enumerate(sheets, start=1):
            sheet_name = str(sheet.get("name") or f"sheet{sheet_index}")[:120]
            rel_id = str(sheet.get(f"{OFFICE_REL_NS}id") or "")
            part = rels_map.get(rel_id, "")
            if not part or part not in names:
                warnings.append(f"xlsx_sheet_part_missing:{sheet_name}")
                continue
            sheet_root = _safe_xml_frombytes(_read_zip_part(archive, part), label=part)
            cell_count = 0
            for cell in sheet_root.iter(f"{SPREADSHEET_NS}c"):
                cell_count += 1
                if cell_count > MAX_XLSX_CELLS_PER_SHEET:
                    warnings.append(f"xlsx_cell_cap_reached:{sheet_name}")
                    break
                cell_ref = str(cell.get("r") or "")
                cell_type = str(cell.get("t") or "")
                formula_node = cell.find(f"{SPREADSHEET_NS}f")
                value_node = cell.find(f"{SPREADSHEET_NS}v")
                inline_node = cell.find(f"{SPREADSHEET_NS}is")
                value = ""
                if cell_type == "s" and value_node is not None:
                    try:
                        shared_index = int((value_node.text or "0").strip())
                        value = shared_strings[shared_index] if 0 <= shared_index < len(shared_strings) else ""
                    except ValueError:
                        value = ""
                elif cell_type == "inlineStr" and inline_node is not None:
                    value = _element_text(inline_node)
                elif value_node is not None:
                    value = (value_node.text or "").strip()
                formula = (formula_node.text or "").strip() if formula_node is not None else ""
                rendered = f"={formula}" if formula else value
                if not rendered:
                    continue
                if formula:
                    formula_count += 1
                _append_block(blocks, f"sheet:{sheet_name}!{cell_ref}", rendered[:MAX_BLOCK_TEXT_CHARS])
    if formula_count:
        warnings.append(f"xlsx_formulas_recorded_not_evaluated:{formula_count}")
    warnings.extend(scan_prompt_injection(_summary_from_blocks(blocks)))
    return {
        "status": "parsed",
        "kind": "xlsx",
        "warnings": warnings,
        "blocks": blocks,
        "meta": {"sheetCount": len(sheets), "formulaCount": formula_count},
        "summaryText": _summary_from_blocks(blocks),
    }


# ---------------------------------------------------------------------------
# ZIP isolation expansion
# ---------------------------------------------------------------------------


def _zip_entry_issues(name: str, *, is_dir: bool = False) -> str:
    normalized = name.replace("\\", "/")
    if name != normalized and "\\" in name:
        return "zip_entry_backslash"
    if normalized.startswith("/"):
        return "zip_entry_absolute_path"
    if re.match(r"^[A-Za-z]:", normalized):
        return "zip_entry_drive_letter"
    parts = [part for part in normalized.split("/")]
    if any(part in {"..", "."} for part in parts):
        return "zip_entry_traversal"
    if is_dir:
        return ""
    if any(part == "" for part in parts):
        return "zip_entry_empty_segment"
    if len(parts) > MAX_ZIP_ENTRY_DEPTH:
        return "zip_entry_depth_exceeded"
    if len(normalized) > 400:
        return "zip_entry_name_too_long"
    for part in parts:
        if part.split(".")[0].lower() in _ZIP_WINDOWS_RESERVED:
            return "zip_entry_windows_reserved_name"
    if normalized.endswith("/"):
        return "zip_entry_directory"
    return ""


def _zip_entry_is_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def _safe_extract_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as source_handle, open(target, "wb") as target_handle:
        remaining = info.file_size
        while chunk := source_handle.read(min(1024 * 1024, remaining or 1024 * 1024)):
            target_handle.write(chunk)
            remaining -= len(chunk)
            if remaining < 0:
                raise LocalParsingBlocked("zip_entry_size_mismatch", info.filename)


def parse_zip(path: Path, *, depth: int, allowed_extensions: set[str], sha256: str = "") -> dict[str, Any]:
    """ZIP 隔离临时目录展开 + 逐条安全检查；解出文件递归走解析链。"""

    if depth > MAX_ARCHIVE_PARSE_DEPTH:
        raise LocalParsingBlocked("archive_depth_exceeded", f"depth={depth}")
    warnings: list[str] = []
    extracted: list[dict[str, Any]] = []
    temp_dir = Path(tempfile.mkdtemp(prefix="msr-zip-"))
    try:
        with zipfile.ZipFile(path) as archive:
            infos = [info for info in archive.infolist()]
            if any(info.flag_bits & 0x1 for info in infos):
                raise LocalParsingBlocked("zip_encrypted", "encrypted entries present")
            if len(infos) > MAX_ZIP_ENTRIES:
                raise LocalParsingBlocked("zip_entry_limit_exceeded", f"entries={len(infos)}")
            total_uncompressed = 0
            for info in infos:
                total_uncompressed += info.file_size
                if total_uncompressed > MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
                    raise LocalParsingBlocked("zip_total_size_exceeded", f"total={total_uncompressed}")
                if info.compress_size > 0 and info.file_size // info.compress_size > MAX_ZIP_COMPRESSION_RATIO:
                    raise LocalParsingBlocked("zip_compression_bomb_ratio", f"{info.filename}: ratio={info.file_size // max(info.compress_size, 1)}")
                issue = _zip_entry_issues(info.filename, is_dir=info.is_dir())
                if issue:
                    raise LocalParsingBlocked(issue, info.filename)
                if not info.is_dir() and _zip_entry_is_symlink(info):
                    raise LocalParsingBlocked("zip_entry_symlink", info.filename)
            skipped_count = 0
            for info in infos:
                if info.is_dir():
                    continue
                entry_name = info.filename.replace("\\", "/")
                safe_name = entry_name.replace("/", "_")[-120:] or "entry"
                entry_suffix = Path(safe_name).suffix.lower()
                target = temp_dir / f"{_hash_file_bytes(entry_name.encode('utf-8'))[:16]}_{safe_name}"
                try:
                    _safe_extract_entry(archive, info, target)
                except LocalParsingBlocked:
                    raise
                except (OSError, zipfile.BadZipFile) as exc:
                    raise LocalParsingBlocked("zip_entry_extract_failed", f"{entry_name}: {exc}") from exc
                entry_result: dict[str, Any] = {
                    "entryName": entry_name,
                    "suffix": entry_suffix,
                    "sizeBytes": info.file_size,
                    "sha256": _hash_file(target),
                }
                if entry_suffix not in allowed_extensions:
                    skipped_count += 1
                    entry_result["status"] = "skipped"
                    entry_result["reason"] = "unsupported_extension"
                    extracted.append(entry_result)
                    continue
                try:
                    entry_parse = parse_local_file(target, suffix=entry_suffix, depth=depth + 1, allowed_extensions=allowed_extensions)
                    entry_result["status"] = "parsed" if entry_parse.get("status") == "parsed" else "blocked"
                    entry_result["parse"] = entry_parse
                    if entry_parse.get("status") == "blocked":
                        entry_result["reason"] = entry_parse.get("blockedReason", "")
                except LocalParsingBlocked as exc:
                    entry_result["status"] = "blocked"
                    entry_result["reason"] = exc.reason
                extracted.append(entry_result)
            entry_names = [info.filename for info in infos if not info.is_dir()]
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    if skipped_count:
        warnings.append(f"zip_entries_skipped_unsupported:{skipped_count}")
    listing = "; ".join(entry_names[:20])
    return {
        "status": "parsed",
        "kind": "zip",
        "warnings": warnings,
        "blocks": [{"locator": f"entry:{name}", "text": name[:MAX_BLOCK_TEXT_CHARS]} for name in entry_names[:MAX_BLOCKS]],
        "meta": {
            "entryCount": len(entry_names),
            "extractedCount": sum(1 for item in extracted if item.get("status") == "parsed"),
            "skippedCount": skipped_count,
            "parentSha256": sha256,
            "listing": listing,
        },
        "summaryText": f"Archive with {len(entry_names)} entries: {listing}"[:MAX_SUMMARY_CHARS],
        "extracted": extracted,
    }


# ---------------------------------------------------------------------------
# Unified entry
# ---------------------------------------------------------------------------


def parse_local_file(
    path: Path,
    *,
    suffix: str | None = None,
    depth: int = 0,
    allowed_extensions: set[str] | None = None,
) -> dict[str, Any]:
    """统一安全入口：magic 一致性 → 分类型解析 → 结构化结果。

    任何安全阻断以 ``status=blocked`` 返回（不抛异常），并携带结构化 reason。
    """

    normalized_suffix = (suffix or Path(path).suffix or "").lower()
    try:
        data = path.read_bytes()
    except OSError as exc:
        return _blocked_result("read_failed", str(exc))
    magic_kind, mismatch = check_type_consistency(normalized_suffix, data[:1024])
    if mismatch:
        return _blocked_result(mismatch, f"suffix={normalized_suffix} magic={magic_kind}")

    def _stamp(result: dict[str, Any]) -> dict[str, Any]:
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        meta.setdefault("magicKind", magic_kind)
        meta["suffix"] = normalized_suffix
        meta["parserVersion"] = PARSER_VERSION
        meta["sizeBytes"] = len(data)
        result["meta"] = meta
        return result

    allowed = allowed_extensions if allowed_extensions is not None else set()
    try:
        if normalized_suffix == ".pdf" and magic_kind == "pdf":
            return _stamp(parse_pdf(path))
        if normalized_suffix == ".zip" or (normalized_suffix in OOXML_SUFFIXES):
            if normalized_suffix in OOXML_SUFFIXES:
                return _stamp(_parse_ooxml(path, suffix=normalized_suffix, data=data))
            return _stamp(parse_zip(path, depth=depth, allowed_extensions=allowed, sha256=_hash_bytes(data)))
        if normalized_suffix in IMAGE_SUFFIXES or magic_kind in {"png", "jpeg", "gif", "bmp", "webp"}:
            return _stamp(parse_image(data[:64], size_bytes=len(data), magic_kind=magic_kind or "image"))
        if normalized_suffix in {".json"}:
            return _stamp(parse_json(data))
        if normalized_suffix in {".jsonl", ".ndjson"}:
            return _stamp(parse_jsonl(data))
        if normalized_suffix in {".html", ".htm"}:
            return _stamp(parse_html(data))
        if normalized_suffix in TEXT_SUFFIXES or magic_kind in {"text", "json_like"}:
            return _stamp(parse_text(data, suffix=normalized_suffix))
        return _blocked_result("unsupported_binary_content", f"suffix={normalized_suffix} magic={magic_kind}")
    except LocalParsingBlocked as exc:
        return _blocked_result(exc.reason, exc.detail)


def _parse_ooxml(path: Path, *, suffix: str, data: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as probe:
            probe.testzip()
    except (zipfile.BadZipFile, OSError) as exc:
        return _blocked_result("extension_magic_mismatch", f"corrupt OOXML container: {exc}")
    if suffix == ".docx":
        return parse_docx(path)
    if suffix == ".pptx":
        return parse_pptx(path)
    return parse_xlsx(path)
