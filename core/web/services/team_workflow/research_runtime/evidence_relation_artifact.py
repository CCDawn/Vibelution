"""Normalize canonical relation-stage output without inventing evidence."""

from __future__ import annotations

from typing import Any


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
        "counterEvidenceRefs": _items(
            result.get("counterEvidenceRefs"),
            graph.get("counterEvidenceRefs"),
        ),
    }
