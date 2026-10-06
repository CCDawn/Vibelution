"""Hide ungrounded amounts in a financial research conclusion.

The stored Session answer stays unchanged. A conclusion amount stays only when
the same number is on a filing page the report cites, or when the conclusion
writes an arithmetic expression whose operands are those page numbers and this
module evaluates to the written result.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, ROUND_HALF_UP

from core.chat.turn_journal import EVENT_TOOL_RESULT

MISSING_FIGURE = "没有这一项"
_MAX_DIGITS = 40
_FAILED_TOOL_STATUSES = {
    "failed",
    "error",
    "timeout",
    "timed_out",
    "blocked",
    "cancelled",
    "canceled",
    "interrupted",
}
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,3}[ \t]+(?P<title>.+?)[ \t]*$")
_CONCLUSION_TITLE = re.compile(r"结论|摘要|简报|summary|conclusion", re.IGNORECASE)
_PAGE = re.compile(
    r"第\s*(\d{1,6})\s*页|PDF\s*(\d{1,6})\s*页|\b(?:p\.|page\s+)(\d{1,6})\b",
    re.IGNORECASE,
)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_UNIT = r"(?:%|％|万亿|亿元|万元|港元|美元|元|股)"
_NUMBER = r"(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?"
_AMOUNT = re.compile(
    rf"(?<![\d.])(?P<sign>[+-])?(?P<number>{_NUMBER})(?![\d.])(?P<unit>\s*{_UNIT})?"
)
_SCIENCE = re.compile(r"(?<![\d.])[+-]?\d+(?:\.\d+)?[eE][+-]?\d+(?![\d])")
_OPERATOR_GAP = re.compile(r"\s*([+＋×*/／÷]|[-－−])\s*")
_EQUALS_GAP = re.compile(r"\s*(?:=|＝|≈|约等于|约为)\s*")
_OPERATORS = {
    "+": "+",
    "＋": "+",
    "-": "-",
    "－": "-",
    "−": "-",
    "*": "*",
    "×": "*",
    "/": "/",
    "／": "/",
    "÷": "/",
}


def ground_report_text(report_text: str, excerpts: list[tuple[int, str]]) -> str:
    """Return the report with ungrounded conclusion amounts replaced."""

    original = str(report_text or "")
    text = original.translate(_FULLWIDTH_DIGITS)
    if not text:
        return original
    pages = _cited_pages(text)
    allowed: set[str] = set()
    for page, excerpt in excerpts:
        if page in pages and excerpt:
            allowed |= _numbers_in_text(excerpt)
    spans = _conclusion_spans(text)
    if not spans:
        return original
    fences = [(match.start(), match.end()) for match in _FENCE.finditer(text)]
    page_numbers = set(allowed)
    computed = set(page_numbers)
    kept: list[tuple[int, int]] = []
    for start, end in spans:
        known = set(computed)
        for _ in range(4):
            added, positions = _confirmed_results(text[start:end], known, start, fences, text)
            if added <= known:
                break
            known |= added
            kept.extend((start + left, start + right) for left, right in positions)
        computed = known
    return _replace_amounts(original, text, spans, page_numbers, kept, fences)


def ground_completed_report(report_text: str, items: list, events: list) -> str:
    """Ground one completed Turn without reading anything outside that Turn."""

    return ground_report_text(report_text, excerpts_from_turn(items, events))


def excerpts_from_turn(items: list, events: list) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for name, output, status in _tool_records(items, events):
        if status.strip().lower() in _FAILED_TOOL_STATUSES:
            continue
        found.extend(filing_excerpts_from_tool_output(name, output))
    return found


def filing_excerpts_from_tool_output(tool_name: str, output: str) -> list[tuple[int, str]]:
    """Read page excerpts only from reviewed local filing search results."""

    if str(tool_name or "").strip() != "financial_evidence_search_tool":
        return []
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError, ValueError, UnicodeError):
        return []
    if not isinstance(payload, dict):
        return []
    pages_by_item: dict[str, list[int]] = {}
    for citation in payload.get("citations") or []:
        if not isinstance(citation, dict):
            continue
        item_id = str(citation.get("knowledgeItemId") or "")
        pages = [
            page
            for meta in citation.get("financialEvidence") or []
            if isinstance(meta, dict)
            for page in [_page(meta.get("page"))]
            if page is not None
        ]
        if item_id and pages:
            pages_by_item[item_id] = pages
    found: list[tuple[int, str]] = []
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        excerpt = str(row.get("excerpt") or "")
        if not excerpt.strip():
            continue
        for page in pages_by_item.get(str(row.get("knowledgeItemId") or ""), []):
            found.append((page, excerpt))
    return found


def _page(value: object) -> int | None:
    if type(value) is int and 1 <= value <= 100_000:
        return value
    if isinstance(value, str) and value.isdigit():
        page = int(value)
        if 1 <= page <= 100_000:
            return page
    return None


def _tool_records(items: list, events: list) -> list[tuple[str, str, str]]:
    records: list[tuple[str, str, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or item.get("kind") or "") != "tool_call":
            continue
        name = str(item.get("toolName") or "")
        output = str(item.get("output") or "")
        if name and output:
            records.append((name, output, str(item.get("status") or "")))
    for event in events or []:
        if str(getattr(event, "event_type", "") or "") != EVENT_TOOL_RESULT:
            continue
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            continue
        tool_call = payload.get("toolCall") or payload.get("tool_call") or payload
        if not isinstance(tool_call, dict):
            continue
        name = str(
            tool_call.get("name")
            or tool_call.get("toolName")
            or tool_call.get("tool_name")
            or ""
        )
        output = str(tool_call.get("result") or tool_call.get("output") or "")
        status = str(tool_call.get("status") or getattr(event, "status", "") or "")
        if name and output:
            records.append((name, output, status))
    return records


def _cited_pages(text: str) -> set[int]:
    pages: set[int] = set()
    for match in _PAGE.finditer(text):
        raw = next(group for group in match.groups() if group)
        page = int(raw)
        if 1 <= page <= 100_000:
            pages.add(page)
    return pages


def _conclusion_spans(text: str) -> list[tuple[int, int]]:
    headings = list(_HEADING.finditer(text))
    spans: list[tuple[int, int]] = []
    for index, heading in enumerate(headings):
        if not _CONCLUSION_TITLE.search(heading.group("title")):
            continue
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        spans.append((start, end))
    if spans:
        return spans
    if headings:
        return []
    return [(0, len(text))]


def _numbers_in_text(text: str) -> set[str]:
    found: set[str] = set()
    for match in _AMOUNT.finditer(str(text or "").translate(_FULLWIDTH_DIGITS)):
        canonical = _canonical(match)
        if canonical is not None:
            found.add(canonical)
    return found


def _is_amount(match: re.Match[str]) -> bool:
    number = match.group("number") or ""
    digits = re.sub(r"\D", "", number)
    if not digits or len(digits) > _MAX_DIGITS:
        return False
    return bool(match.group("unit")) or any(mark in number for mark in (".", ",", "，"))


def _canonical_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _canonical(match: re.Match[str]) -> str | None:
    if not _is_amount(match):
        return None
    try:
        return _canonical_decimal(_decimal_from_match(match))
    except (ArithmeticError, ValueError):
        return None


def _keeps_amount(match: re.Match[str], known: set[str], chunk: str) -> bool:
    canonical = _canonical(match)
    if canonical is None or canonical in known:
        return True
    if match.group("sign") != "-":
        return False
    absolute = _absolute_key(match)
    if absolute not in known:
        return False
    previous = chunk[match.start() - 1] if match.start() else ""
    return previous == "" or previous.isspace()


def _absolute_key(match: re.Match[str]) -> str | None:
    try:
        return _canonical_decimal(abs(_decimal_from_match(match)))
    except (ArithmeticError, ValueError):
        return None


def _decimal_from_match(match: re.Match[str]) -> Decimal:
    raw = (match.group("number") or "").replace(",", "").replace("，", "")
    value = Decimal(raw)
    if match.group("sign") == "-":
        value = -value
    return value


def _written_places(match: re.Match[str]) -> int:
    number = (match.group("number") or "").replace(",", "").replace("，", "")
    if "." not in number:
        return 0
    return len(number.split(".", 1)[1])


def _is_percent(match: re.Match[str]) -> bool:
    unit = match.group("unit") or ""
    return "%" in unit or "％" in unit


def _rounds_to(computed: Decimal, match: re.Match[str]) -> bool:
    places = _written_places(match)
    quantum = Decimal(1).scaleb(-places)
    return computed.quantize(quantum, rounding=ROUND_HALF_UP) == _decimal_from_match(match)


def _inside_url(text: str, index: int) -> bool:
    window = text[max(0, index - 300) : index]
    start = max(window.rfind("http://"), window.rfind("https://"))
    if start < 0:
        return False
    return not any(char.isspace() for char in window[start:])


def _inside(spans: list[tuple[int, int]], index: int) -> bool:
    return any(start <= index < end for start, end in spans)


def _operator(text: str) -> str | None:
    match = _OPERATOR_GAP.fullmatch(text)
    if match is None:
        return None
    return _OPERATORS.get(match.group(1))


def _right_operand(chunk: str, left: re.Match[str], right: re.Match[str]) -> tuple[str, Decimal] | None:
    gap = chunk[left.end() : right.start()]
    operator = _operator(gap)
    value = _decimal_from_match(right)
    if operator is not None:
        return operator, value
    # "1.50 - 2.50" puts the minus on the second amount. That is subtraction.
    if right.group("sign") == "-" and gap.strip() == "":
        return "-", abs(value)
    return None


def _confirmed_results(
    chunk: str,
    known: set[str],
    base: int,
    fences: list[tuple[int, int]],
    full: str,
) -> tuple[set[str], list[tuple[int, int]]]:
    amounts: list[re.Match[str]] = []
    for match in _AMOUNT.finditer(chunk):
        if _canonical(match) is None:
            continue
        absolute = base + match.start()
        if _inside_url(full, absolute) or _inside(fences, absolute):
            continue
        amounts.append(match)
    found: set[str] = set()
    positions: list[tuple[int, int]] = []
    for index in range(len(amounts) - 2):
        left, right, result = amounts[index : index + 3]
        parsed = _right_operand(chunk, left, right)
        if parsed is None or not _EQUALS_GAP.fullmatch(chunk[right.end() : result.start()]):
            continue
        operator, right_value = parsed
        left_key = _canonical(left)
        subtracted = (
            operator == "-"
            and right.group("sign") == "-"
            and chunk[left.end() : right.start()].strip() == ""
        )
        right_key = _absolute_key(right) if subtracted else _canonical(right)
        if left_key not in known or right_key not in known:
            continue
        written = _confirm_math(left, operator, right_value, result)
        if written:
            found.add(written)
            positions.extend((item.start(), item.end()) for item in (left, right, result))
    return found, positions


def _confirm_math(
    left: re.Match[str],
    operator: str,
    right_value: Decimal,
    result: re.Match[str],
) -> str | None:
    left_value = _decimal_from_match(left)
    try:
        if operator == "+":
            computed = left_value + right_value
        elif operator == "-":
            computed = left_value - right_value
        elif operator == "*":
            computed = left_value * right_value
        else:
            if right_value == 0:
                return None
            computed = left_value / right_value
    except (ArithmeticError, ValueError):
        return None
    candidate = computed * 100 if _is_percent(result) else computed
    if not _rounds_to(candidate, result):
        return None
    return _canonical(result)


def _replace_amounts(
    original: str,
    normalized: str,
    spans: list[tuple[int, int]],
    known: set[str],
    kept: list[tuple[int, int]],
    fences: list[tuple[int, int]],
) -> str:
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        pieces.append(original[cursor:start])
        pieces.append(
            _replace_span(
                original[start:end],
                normalized[start:end],
                start,
                known,
                [(left - start, right - start) for left, right in kept if start <= left and right <= end],
                fences,
                normalized,
            )
        )
        cursor = end
    pieces.append(original[cursor:])
    return "".join(pieces)


def _replace_span(
    original_chunk: str,
    chunk: str,
    base: int,
    known: set[str],
    kept: list[tuple[int, int]],
    fences: list[tuple[int, int]],
    full: str,
) -> str:
    spans: list[tuple[int, int]] = []
    for match in _AMOUNT.finditer(chunk):
        if _keeps_amount(match, known, chunk) or (match.start(), match.end()) in kept:
            continue
        absolute = base + match.start()
        if _inside_url(full, absolute) or _inside(fences, absolute):
            continue
        spans.append((match.start(), match.end()))
    for match in _SCIENCE.finditer(chunk):
        absolute = base + match.start()
        if _inside_url(full, absolute) or _inside(fences, absolute):
            continue
        spans.append((match.start(), match.end()))
    spans.sort(key=lambda item: (item[0], item[0] - item[1]))
    chosen: list[tuple[int, int]] = []
    occupied = -1
    for start, end in spans:
        if start < occupied:
            continue
        chosen.append((start, end))
        occupied = end
    pieces: list[str] = []
    cursor = 0
    for start, end in chosen:
        pieces.append(original_chunk[cursor:start])
        pieces.append(MISSING_FIGURE)
        cursor = end
    pieces.append(original_chunk[cursor:])
    return "".join(pieces)
