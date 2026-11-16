"""Normalize canonical relation-stage output without inventing evidence."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any


DIRECT_COUNTER_DISPOSITION = "challenges_ontology"
COUNTER_REF_KEYS = ("counterEvidenceRefs", "counter_evidence_refs")
COUNTER_ID_KEYS = ("evidenceRef", "evidence_ref", "refId")
_DIRECT_COUNTER_OPTION_LIMIT = 12


def is_direct_counter(item: Mapping[str, Any]) -> bool:
    return str(item.get("disposition") or "").strip().lower() == DIRECT_COUNTER_DISPOSITION


def direct_counter_anchors(cards: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        str(card["claimEvidenceId"]): card
        for card in cards
        if str(card.get("claimEvidenceId") or "").startswith("ce-")
        and card.get("supportLevel") == "contradicts"
        and card.get("originalSourceUrl")
        and card.get("quote")
    }


def direct_counter_options(cards: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Provide copyable refs and exact originals separately from graph endpoints."""
    return [
        {
            "evidenceRef": ref,
            "candidateId": str(card.get("candidateId") or ""),
            "sourceUrl": str(card["originalSourceUrl"]),
            "quote": str(card["quote"]),
        }
        for ref, card in list(direct_counter_anchors(cards).items())[:_DIRECT_COUNTER_OPTION_LIMIT]
    ]


def iter_counter_reference_lists(
    result: Mapping[str, Any],
) -> Iterator[tuple[str, str, list[Any]]]:
    for container, prefix in (
        (result, ""),
        (result.get("candidateGraph"), "candidateGraph."),
        (result.get("candidate_graph"), "candidate_graph."),
    ):
        if isinstance(container, Mapping):
            for key in COUNTER_REF_KEYS:
                if isinstance(container.get(key), list):
                    yield prefix, key, container[key]


def _canonical_counter_collections(result: dict[str, Any]) -> dict[str, Any]:
    """Give graph materialization and task readback the same collection names."""
    normalized = dict(result)

    def merge_counters(container: dict[str, Any], value: Any) -> None:
        current = container.get("counterEvidenceRefs")
        if current is None:
            container["counterEvidenceRefs"] = value
        elif isinstance(current, list):
            # Preserve a malformed alias for the existing shape guard.
            container["counterEvidenceRefs"] = [*current, *value] if isinstance(value, list) else value

    def fold_alias(container: dict[str, Any]) -> None:
        if "counter_evidence_refs" in container:
            merge_counters(container, container.pop("counter_evidence_refs"))

    fold_alias(normalized)
    legacy = normalized.pop("candidate_graph", None)
    graph = normalized.get("candidateGraph") or legacy
    if isinstance(graph, dict):
        original = graph
        graph = normalized["candidateGraph"] = dict(graph)
        fold_alias(graph)
        if isinstance(legacy, dict) and legacy is not original:
            for key in COUNTER_REF_KEYS:
                if key in legacy:
                    merge_counters(graph, legacy[key])
    return normalized


def resolve_direct_counter_refs(
    result: dict[str, Any], cards: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Reject unsupported direct refs; resolve a source alias only with one exact card."""
    result = _canonical_counter_collections(result)
    direct = direct_counter_anchors(cards)
    canonical = {str(card.get("claimEvidenceId") or "") for card in cards}
    aliases: dict[str, dict[str, Mapping[str, Any]]] = {}
    for card in cards:
        ref = str(card.get("claimEvidenceId") or "")
        if ref:
            for field in ("candidateId", "recordId"):
                if alias := str(card.get(field) or ""):
                    aliases.setdefault(alias, {})[ref] = card

    normalized = dict(result)
    findings: list[dict[str, str]] = []
    for prefix, key, items in iter_counter_reference_lists(result):
        updated = list(items)
        for index, item in enumerate(items):
            if not isinstance(item, Mapping) or not is_direct_counter(item):
                continue
            field = next((field for field in COUNTER_ID_KEYS if field in item), "evidenceRef")
            ref = str(item.get(field) or "").strip()
            matches = aliases.get(ref, {}) if ref not in canonical else {}
            quote = str(item.get("quote") or "").strip()
            if quote and matches:
                matches = {ident: card for ident, card in matches.items() if card.get("quote") == quote}
            resolved = next(iter(matches)) if len(matches) == 1 else ref
            path = f"{prefix}{key}[{index}]"
            if resolved not in direct or (quote and direct[resolved]["quote"] != quote):
                findings.append({
                    "finding": "unbound_direct_counter_evidence",
                    "path": f"{path}.{field}",
                    "value": ref,
                    "detail": "直接反证必须绑定本轮带原文回执的 contradicts 证据卡；无法唯一匹配时使用 directCounterEvidence。",
                })
            elif not isinstance(item.get("claim"), str) or not item["claim"].strip():
                findings.append({
                    "finding": "missing_challenged_claim",
                    "path": f"{path}.claim",
                    "detail": "请根据选中证据卡的原文写清它直接反驳的命题。",
                })
            elif (
                field != "evidenceRef"
                or resolved != item.get(field)
                or item.get("disposition") != DIRECT_COUNTER_DISPOSITION
            ):
                updated[index] = {
                    **{k: v for k, v in item.items() if k not in COUNTER_ID_KEYS},
                    "evidenceRef": resolved,
                    "disposition": DIRECT_COUNTER_DISPOSITION,
                }
        if updated != items:
            container = normalized
            if prefix:
                parent = prefix[:-1]
                container = normalized[parent] = dict(normalized[parent])
            container[key] = updated
    return normalized, findings


def _items(*values: object) -> list[Any]:
    for value in values:
        if isinstance(value, list) and value:
            return list(value)
    return []


def build_evidence_relation_artifact(result: dict[str, Any]) -> dict[str, Any]:
    graph = dict(result.get("candidateGraph") or {})
    return {
        **result,
        **graph,
        "evidenceGaps": _items(
            result.get("evidenceGaps"),
            graph.get("evidenceGaps"),
            result.get("missingLinks"),
            graph.get("missingLinks"),
            graph.get("gaps"),
        ),
        "counterEvidenceRefs": [
            *_items(graph.get("counterEvidenceRefs")),
            *_items(result.get("counterEvidenceRefs")),
        ],
    }
