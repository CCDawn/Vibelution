"""Deep-research report synthesis: pure assembly over knowledge items.

Domain layer, no I/O and no LLM calls. Given a bounded list of knowledge
items (title / summary / source refs) plus stage artifacts, this module
drafts the report skeleton — section mapping, citation anchoring
(``[KI-xxx]`` markers resolvable back to item ids) and an integrity check
that flags assertions without sources. The LLM prose pass and the
workflow node live in the web/orchestration layers and must consume this
skeleton so citations stay machine-checkable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Dict, List

REPORT_SYNTHESIS_CONTRACT_VERSION = 1
REPORT_SECTIONS = ("概述", "方法", "证据", "开放问题", "局限")
MAX_ITEMS_PER_REPORT = 60


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def normalize_report_items(raw: Sequence[Mapping[str, Any]] | None) -> List[Dict[str, Any]]:
    """Normalize knowledge items to ``{itemId,title,summary,sourceRefs,section}``."""

    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for record in raw or []:
        if not isinstance(record, Mapping):
            continue
        item_id = _text(record.get("itemId"))
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        sources = record.get("sourceRefs")
        source_refs = [
            _text(source) for source in (sources if isinstance(sources, list) else []) if _text(source)
        ]
        items.append(
            {
                "itemId": item_id,
                "title": _text(record.get("title")) or item_id,
                "summary": _text(record.get("summary")),
                "sourceRefs": source_refs,
                "section": _text(record.get("section")) or "证据",
            }
        )
        if len(items) >= MAX_ITEMS_PER_REPORT:
            break
    return items


def build_report_skeleton(
    items: Sequence[Mapping[str, Any]],
    *,
    report_id: str,
    topic: str,
) -> Dict[str, Any]:
    """Group items into the report sections with citation anchors."""

    normalized = normalize_report_items(items)
    sections: Dict[str, List[Dict[str, Any]]] = {section: [] for section in REPORT_SECTIONS}
    for item in normalized:
        section = item["section"] if item["section"] in sections else "证据"
        sections[section].append(
            {
                "anchor": f"[KI-{item['itemId']}]",
                "itemId": item["itemId"],
                "title": item["title"],
                "summary": item["summary"],
                "sourceRefs": item["sourceRefs"],
            }
        )
    ordered_sections = [
        {"section": section, "entries": entries}
        for section, entries in sections.items()
        if entries
    ]
    return {
        "schemaVersion": REPORT_SYNTHESIS_CONTRACT_VERSION,
        "reportId": _text(report_id),
        "topic": _text(topic),
        "itemCount": len(normalized),
        "sections": ordered_sections,
        "citationIndex": {
            f"KI-{item['itemId']}": {
                "itemId": item["itemId"],
                "title": item["title"],
                "sourceRefs": item["sourceRefs"],
            }
            for item in normalized
        },
    }


def render_skeleton_markdown(skeleton: Mapping[str, Any]) -> str:
    """Render the skeleton as citation-anchored markdown for the LLM prose pass."""

    lines: List[str] = [f"# {_text(skeleton.get('topic')) or '研究综述'}"]
    for section in skeleton.get("sections") or []:
        if not isinstance(section, Mapping):
            continue
        lines.append("")
        lines.append(f"## {section.get('section')}")
        for entry in section.get("entries") or []:
            if not isinstance(entry, Mapping):
                continue
            sources = ", ".join(str(source) for source in entry.get("sourceRefs") or [])
            source_note = f"（来源：{sources}）" if sources else "（无来源标注）"
            lines.append(
                f"- {entry.get('anchor')} {entry.get('title')}：{entry.get('summary')} {source_note}"
            )
    return "\n".join(lines) + "\n"


def check_citation_integrity(skeleton: Mapping[str, Any]) -> List[str]:
    """Flag items cited without any source reference (empty list = clean)."""

    problems: List[str] = []
    for anchor, record in dict(skeleton.get("citationIndex") or {}).items():
        if not isinstance(record, Mapping):
            continue
        if not [source for source in record.get("sourceRefs") or [] if _text(source)]:
            problems.append(f"{anchor} has no source reference")
    return problems
