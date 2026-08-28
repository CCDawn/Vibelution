"""Knowledge invocation badge projection over ``knowledge_invocations`` rows.

Pure read-model functions: the snapshot builder feeds already-loaded
``KnowledgeInvocationRecord`` rows (or equivalent mappings) and gets the
per-parent-node aggregates that canvas badges and the node Inspector consume.
Nothing here writes and nothing here reaches into a child run's ledger.

The "current knowledge node" is derived, not stored: invocation rows carry
lifecycle facts only, so the fixed five-node sideflow chain order
(``KNOWLEDGE_SIDEFLOW_NODE_IDS``) plus the invocation status decide which
sideflow node is live.  Derivation stays honest by never inventing a middle
node: a running invocation is reported at the chain entry, an
``awaiting_handoff`` invocation at the terminal handoff gate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.research.workflow.knowledge_sideflow_definition import (
    KNOWLEDGE_SIDEFLOW_NODE_IDS,
)

SIDEFLOW_ENTRY_NODE_ID = KNOWLEDGE_SIDEFLOW_NODE_IDS[0]
SIDEFLOW_HANDOFF_NODE_ID = KNOWLEDGE_SIDEFLOW_NODE_IDS[-1]

_STATUS_RUNNING = frozenset({"pending", "child_created", "running"})
_STATUS_AWAITING_HANDOFF = frozenset({"awaiting_handoff"})
# "absorbed" = the parent consumed the package; only a completed invocation
# proves that.  handoff_state alone (accepted) is not a write-back fact.
_STATUS_ABSORBED = frozenset({"completed"})


def current_knowledge_node_id(status: str | None) -> str | None:
    """Map one invocation status to the live sideflow node (or None)."""
    normalized = str(status or "").strip().lower()
    if normalized in _STATUS_RUNNING:
        return SIDEFLOW_ENTRY_NODE_ID
    if normalized in _STATUS_AWAITING_HANDOFF:
        return SIDEFLOW_HANDOFF_NODE_ID
    if normalized in _STATUS_ABSORBED:
        return SIDEFLOW_HANDOFF_NODE_ID
    return None


def _record_field(record: Any, name: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(name)
    return getattr(record, name, None)


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _error_summary(record: Any) -> str | None:
    raw = _record_field(record, "error_json")
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        code = str(raw.get("code") or raw.get("detail") or "").strip()
        return code or None
    text = str(raw).strip()
    if not text or text in {"{}", "null"}:
        return None
    return text[:200]


def invocation_summary(record: Any) -> dict[str, Any]:
    """One recent-invocation summary row (canvas Inspector lineage)."""
    status = str(_record_field(record, "status") or "").strip().lower() or None
    return {
        "invocationId": _as_optional_str(_record_field(record, "invocation_id")) or "",
        "parentNode_id": _as_optional_str(_record_field(record, "parent_node_id")) or "",
        "knowledgeChildRunId": _as_optional_str(
            _record_field(record, "knowledge_child_run_id")
        ),
        "status": status,
        "handoffState": str(_record_field(record, "handoff_state") or "").strip().lower() or None,
        "currentKnowledgeNodeId": current_knowledge_node_id(status),
        "knowledgePackageRef": _as_optional_str(
            _record_field(record, "knowledge_package_ref")
        ),
        "packageContentHash": _as_optional_str(
            _record_field(record, "package_content_hash")
        ),
        "errorSummary": _error_summary(record),
        "createdAtMs": _as_int(_record_field(record, "created_at_ms")),
        "updatedAtMs": _as_int(_record_field(record, "updated_at_ms")),
    }


def project_knowledge_invocation_badges(
    records: Sequence[Any],
) -> dict[str, dict[str, Any]]:
    """Aggregate invocation rows into per-parent-node badge payloads.

    Keyed by ``parent_node_id`` so the canvas can decorate each main-chain
    node with its knowledge-request counters without a second query.
    """
    by_node: dict[str, list[Any]] = {}
    for record in records:
        node_id = _as_optional_str(_record_field(record, "parent_node_id"))
        if not node_id:
            continue
        by_node.setdefault(node_id, []).append(record)

    badges: dict[str, dict[str, Any]] = {}
    for node_id, node_records in by_node.items():
        counters = {
            "total": 0,
            "running": 0,
            "awaiting_handoff": 0,
            "absorbed": 0,
            "failed": 0,
        }
        for record in node_records:
            status = str(_record_field(record, "status") or "").strip().lower()
            counters["total"] += 1
            if status in _STATUS_RUNNING:
                counters["running"] += 1
            elif status in _STATUS_AWAITING_HANDOFF:
                counters["awaiting_handoff"] += 1
            elif status in _STATUS_ABSORBED:
                counters["absorbed"] += 1
            elif status in {"failed", "cancelled"}:
                counters["failed"] += 1
        latest = max(
            node_records,
            key=lambda item: (
                _as_int(_record_field(item, "updated_at_ms")),
                str(_record_field(item, "invocation_id") or ""),
            ),
        )
        badges[node_id] = {
            "nodeId": node_id,
            "totalCount": counters["total"],
            "runningCount": counters["running"],
            "awaitingHandoffCount": counters["awaiting_handoff"],
            "absorbedCount": counters["absorbed"],
            "failedCount": counters["failed"],
            "latest": invocation_summary(latest),
        }
    return badges


__all__ = [
    "current_knowledge_node_id",
    "invocation_summary",
    "project_knowledge_invocation_badges",
]
