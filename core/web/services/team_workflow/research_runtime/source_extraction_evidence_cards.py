"""Normalize canonical source-extraction results into evidence cards."""

from __future__ import annotations

import json
from typing import Any

_PARENT_CONTEXT_KEYS = (
    "decision",
    "evidenceStatus",
    "relevance",
)


def _text(value: object) -> str:
    return str(value or "").strip()


def _source_id(item: dict[str, Any], parent: dict[str, Any]) -> str:
    for candidate in (parent, item):
        for key in ("candidateId", "recordId", "sourceId"):
            value = _text(candidate.get(key))
            if value:
                return value
    return ""


def _claim(item: dict[str, Any], parent: dict[str, Any]) -> str:
    for candidate in (item, parent):
        for key in ("claim", "finding", "conclusion", "summary", "valueSummary"):
            value = _text(candidate.get(key))
            if value:
                return value
    return ""


def _has_locator_value(locator: dict[str, Any]) -> bool:
    return any(value not in (None, "") for value in locator.values())


def _direct_citation_locator(item: dict[str, Any]) -> dict[str, Any]:
    locator: dict[str, Any] = {}
    for key in ("evidenceRef", "sourceRef", "locator", "doi"):
        value = item.get(key)
        if value not in (None, ""):
            locator[key] = value
    return locator


def _first_nested_citation_locator(item: dict[str, Any]) -> dict[str, Any]:
    for collection_key in ("claims", "evidenceRefs"):
        for raw in item.get(collection_key) or []:
            if not isinstance(raw, dict):
                continue
            explicit = raw.get("citationLocator")
            if isinstance(explicit, dict) and _has_locator_value(explicit):
                return dict(explicit)
            locator = _direct_citation_locator(raw)
            if _has_locator_value(locator):
                return locator
    return {}


def _source_ref_from_parent(item: dict[str, Any]) -> str:
    for raw in item.get("sourceRefs") or []:
        if isinstance(raw, str) and raw:
            return raw
        if isinstance(raw, dict):
            source_ref = _text(raw.get("sourceRef"))
            if source_ref:
                return source_ref
    return ""


def _citation_locator(item: dict[str, Any]) -> dict[str, Any]:
    explicit = item.get("citationLocator")
    if isinstance(explicit, dict) and _has_locator_value(explicit):
        return dict(explicit)
    locator = _direct_citation_locator(item)
    if _has_locator_value(locator):
        return locator

    nested_locator = _first_nested_citation_locator(item)
    if not _has_locator_value(nested_locator):
        return {}
    if "sourceRef" not in nested_locator:
        source_ref = _source_ref_from_parent(item)
        if source_ref:
            nested_locator["sourceRef"] = source_ref
    return nested_locator


def _parent_context(parent: dict[str, Any]) -> dict[str, Any]:
    return {
        key: parent[key]
        for key in _PARENT_CONTEXT_KEYS
        if parent.get(key) not in (None, "")
    }


def _nested_cards(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    findings = [
        dict(item)
        for item in extraction.get("keyFindings") or []
        if isinstance(item, dict)
    ]
    return [
        {
            "sourceId": _source_id(finding, extraction),
            "claim": _claim(finding, extraction),
            "citationLocator": _citation_locator(finding),
            **_parent_context(extraction),
        }
        for finding in findings
    ]


def _flat_card(extraction: dict[str, Any]) -> dict[str, Any]:
    return {
        **extraction,
        "sourceId": _source_id(extraction, extraction),
        "claim": _claim(extraction, extraction),
        "citationLocator": _citation_locator(extraction),
    }


def build_source_extraction_evidence_cards(
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return stable evidence cards without inventing missing source anchors."""
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("candidateExtractions", "recordExtractions"):
        for raw in result.get(key) or []:
            if not isinstance(raw, dict):
                continue
            extraction = dict(raw)
            normalized = _nested_cards(extraction) or [_flat_card(extraction)]
            for card in normalized:
                identity = json.dumps(
                    card,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                if identity in seen:
                    continue
                seen.add(identity)
                cards.append(card)
    return cards
