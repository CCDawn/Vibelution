"""Shared counts for graph writeback and downstream readiness."""

from collections.abc import Mapping
from typing import Any


def evidence_graph_gap_counts(graph: Mapping[str, Any]) -> tuple[int, int]:
    links = list(graph.get("missingLinks") or [])
    summary = graph.get("summary") or {}
    missing = max(len(links), int(summary.get("missingLinkCount") or 0))
    # A summary from an earlier graph cannot waive the current graph's gaps.
    waived = sum(
        1 for link in links
        if isinstance(link, Mapping) and (
            bool(link.get("waived"))
            or str(link.get("status") or "").strip().lower() in {"waived", "accepted"}
            or isinstance(link.get("waiver"), Mapping)
        )
    )
    return missing, waived
