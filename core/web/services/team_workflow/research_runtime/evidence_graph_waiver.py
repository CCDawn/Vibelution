"""Human missing-link waiver surface for the evidence relation graph (缺陷⑪).

The knowledge_ingestion readiness gate blocks on unwaived ``missingLinks``
(``readiness_providers.fetch_evidence_graph_stats`` already counts waivers on
the read side); this module is the missing write path.  A waiver is a human
quality decision: it requires an explicit confirmation plus a non-empty
justification (audited on the graph record), it never removes the missing
link itself, and it never loosens the gate — ``missingLinkCount`` stays
untouched while ``summary.waiverCount`` moves.

The graph authority is the scoped ``candidate_graph`` record(s) in the
candidate store (same scope semantics as
``artifact_readback_registry._load_scoped_relation_graph``); all writes go
through the knowledge kernel's canonical candidate-store write surface, never
direct file edits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .operator_authorization import ServerOperatorContext

_WAIVER_JUSTIFICATION_MIN_CHARS = 8


class EvidenceGraphWaiverError(RuntimeError):
    """Domain error mapped to an HTTP status by the thin route."""

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class MissingLinkWaiverConfirmationError(RuntimeError):
    """Human decision content missing (confirmation / justification)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MissingLinkWaiverResult:
    outcome: str
    already_waived: bool
    team_id: str
    run_id: str
    source_collection_run_id: str
    waiver_count: int
    missing_link_count: int
    graph_candidate_ids: list[str] = field(default_factory=list)
    waiver: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "waived",
            "alreadyWaived": self.already_waived,
            "teamId": self.team_id,
            "runId": self.run_id,
            "sourceCollectionRunId": self.source_collection_run_id,
            "waiverCount": self.waiver_count,
            "missingLinkCount": self.missing_link_count,
            "graphCandidateIds": list(self.graph_candidate_ids),
            "waiver": dict(self.waiver),
        }
        if self.already_waived:
            payload["status"] = "already_waived"
        return payload


def assert_missing_link_waiver_confirmation(
    *,
    confirmed: bool,
    justification: str,
) -> None:
    """Fail closed when the human decision content is missing.

    豁免是人工质量决策：显式 ``confirmed=true`` 与 ≥8 字符的理由都是强制
    审计内容；缺失直接拒绝（428 语义，绝不静默执行）。
    """

    if not confirmed:
        raise MissingLinkWaiverConfirmationError(
            "waiver_confirmation_required",
            "missing-link waiver requires explicit confirmed=true",
        )
    text = str(justification or "").strip()
    if len(text) < _WAIVER_JUSTIFICATION_MIN_CHARS:
        raise MissingLinkWaiverConfirmationError(
            "waiver_justification_required",
            "missing-link waiver requires a justification of at least "
            f"{_WAIVER_JUSTIFICATION_MIN_CHARS} characters",
        )


def waive_missing_link(
    *,
    run_id: str,
    source_candidate_id: str,
    target_candidate_id: str,
    relation: str,
    justification: str,
    operator: ServerOperatorContext | None = None,
    team_id: str = "",
) -> MissingLinkWaiverResult:
    """Apply one confirmed missing-link waiver on the scoped graph authority.

    The run must exist (404 otherwise); ``teamId`` optionally narrows the
    scope and mismatches map to 404 ``team_scope_mismatch`` like the other
    run-scoped endpoints.  The authority SC run id comes from the run's frozen
    input snapshot — without one there is no scoped graph to waive (404
    ``graph_not_found``).
    """

    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        raise EvidenceGraphWaiverError(
            "run_not_found", "run not found: <empty>", status_code=404
        )
    from .formal_write_runtime import FormalWriteRuntimeUnavailable, get_write_store

    try:
        run = get_write_store().get_run(normalized_run_id)
    except FormalWriteRuntimeUnavailable as exc:
        raise EvidenceGraphWaiverError(
            "workflow_ledger_unavailable", str(exc), status_code=503
        ) from exc
    if run is None:
        raise EvidenceGraphWaiverError(
            "run_not_found", f"run not found: {normalized_run_id}", status_code=404
        )
    requested_team = str(team_id or "").strip()
    run_team = str(getattr(run, "team_id", "") or "").strip()
    if requested_team and run_team and requested_team != run_team:
        raise EvidenceGraphWaiverError(
            "team_scope_mismatch",
            "teamId does not match run scope",
            status_code=404,
        )
    resolved_team = requested_team or run_team
    try:
        snapshot = json.loads(str(getattr(run, "input_snapshot_json", "") or "{}"))
    except (TypeError, ValueError):
        snapshot = {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    authority_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    if not authority_run_id:
        raise EvidenceGraphWaiverError(
            "graph_not_found",
            f"run {normalized_run_id} has no sourceCollectionRunId in its input snapshot",
            status_code=404,
        )

    from ..knowledge_kernel import apply_missing_link_waiver

    operator_id = str(getattr(operator, "operator_id", "") or "").strip() or (
        "local-control-operator"
    )
    outcome = apply_missing_link_waiver(
        resolved_team,
        authority_run_id=authority_run_id,
        source_candidate_id=source_candidate_id,
        target_candidate_id=target_candidate_id,
        relation=relation,
        justification=justification,
        operator_id=operator_id,
        workflow_run_id=normalized_run_id,
    )
    kind = str(outcome.get("outcome") or "")
    if kind == "graph_not_found":
        raise EvidenceGraphWaiverError(
            "graph_not_found",
            "no scoped candidate_graph record for this run",
            status_code=404,
        )
    if kind == "missing_link_not_found":
        raise EvidenceGraphWaiverError(
            "missing_link_not_found",
            "no matching missingLink in the scoped graph",
            status_code=404,
        )
    return MissingLinkWaiverResult(
        outcome=kind,
        already_waived=bool(outcome.get("alreadyWaived")),
        team_id=str(outcome.get("teamId") or resolved_team),
        run_id=normalized_run_id,
        source_collection_run_id=str(outcome.get("sourceCollectionRunId") or authority_run_id),
        waiver_count=int(outcome.get("waiverCount") or 0),
        missing_link_count=int(outcome.get("missingLinkCount") or 0),
        graph_candidate_ids=list(outcome.get("graphCandidateIds") or []),
        waiver=dict(outcome.get("waiver") or {}),
    )
