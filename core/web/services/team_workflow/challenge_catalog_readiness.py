"""Server-owned readiness projection for the formal 125-question catalog.

The endpoint deliberately has one source of result truth: the persisted
``real-125`` envelope.  The envelope is restored through the real-batch
service, which revalidates durable catalog authorization and the authorized
model-policy snapshot, then the canonical result set and readiness contract do
the remaining projection.  Legacy Challenge Program counts, client payloads,
and frontend claims never participate in this report.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from core.research.competition.catalog_execution import (
    build_result_set,
)
from core.research.competition.catalog_hypothesis_flow_ready import (
    build_catalog_hypothesis_flow_readiness_report,
)
from core.research.competition.real_control_batch import new_real_batch_state
from core.research.competition.resources import (
    CATALOG_POLICY_VERSION,
    CORE_BEHAVIOR_HASH,
    CORE_POLICY_HASH,
    PROGRAM_CONTRACT_VERSION,
)
from core.research.workflow.contracts.catalog_hypothesis_flow_readiness import (
    CATALOG_HYPOTHESIS_FLOW_REPAIR_ACTION,
    CatalogHypothesisFlowReadinessReport,
    catalog_hypothesis_flow_report_hash,
)
from core.web.services.team_workflow.challenge_cup_dev_controls import (
    get_challenge_cup_dev_control_snapshot,
)
from core.web.services.team_workflow.challenge_cup_real_batch import (
    RealBatchStorageError,
    get_real_batch_catalog_state,
)

REAL_CATALOG_PLAN_ID = "real-125"
_EVIDENCE_IDS = ("r0", "r1", "api", "frontend", "browser")
_GATE_BY_EVIDENCE_ID = {
    "r0": "r0_source_integrity",
    "r1": "r1_clean_clone",
}


class CatalogReadinessStorageError(RuntimeError):
    """The canonical real-batch storage could not be read safely."""


def _empty_evidence() -> dict[str, dict[str, str]]:
    return {evidence_id: {"status": "MISSING", "locator": ""} for evidence_id in _EVIDENCE_IDS}


def _evidence_from_server_snapshot(snapshot: Mapping[str, Any] | None) -> dict[str, dict[str, str]]:
    """Project only explicitly recorded server evidence.

    Current DEV readiness records expose gate statuses and, where available,
    an explicit evidence map.  Gate details are not promoted to locators: a
    human-readable detail is not durable evidence identity, and READY must
    remain closed until a real locator is recorded.  API/frontend/browser are
    therefore MISSING until a dedicated server-side record exists.
    """

    evidence = _empty_evidence()
    if not isinstance(snapshot, Mapping):
        return evidence
    raw_report = snapshot.get("report")
    if not isinstance(raw_report, Mapping):
        raw_report = snapshot.get("readinessReport")
    if not isinstance(raw_report, Mapping):
        return evidence

    raw_evidence = raw_report.get("evidence")
    if not isinstance(raw_evidence, Mapping):
        raw_evidence = raw_report.get("evidenceMap")
    if isinstance(raw_evidence, Mapping):
        for evidence_id in _EVIDENCE_IDS:
            item = raw_evidence.get(evidence_id)
            if not isinstance(item, Mapping):
                continue
            status = str(item.get("status") or "MISSING").strip().upper()
            locator = str(item.get("locator") or "").strip()
            if status not in {"PASS", "FAIL", "BLOCKED", "MISSING"}:
                status = "MISSING"
            evidence[evidence_id] = {"status": status, "locator": locator}

    raw_gates = raw_report.get("gates")
    if isinstance(raw_gates, list):
        gates = {
            str(item.get("gateId") or "").strip(): item
            for item in raw_gates
            if isinstance(item, Mapping)
        }
        for evidence_id, gate_id in _GATE_BY_EVIDENCE_ID.items():
            gate = gates.get(gate_id)
            if not isinstance(gate, Mapping):
                continue
            status = str(gate.get("status") or "MISSING").strip().upper()
            if status not in {"PASS", "FAIL", "BLOCKED", "MISSING"}:
                status = "MISSING"
            # Keep a previously recorded locator, but never derive one from
            # an unstructured gate detail.
            locator = evidence[evidence_id]["locator"]
            evidence[evidence_id] = {"status": status, "locator": locator}
    return evidence


def _server_readiness_snapshot(team_id: str) -> Mapping[str, Any] | None:
    """Read existing server evidence without creating a new evidence source."""

    try:
        snapshot = get_challenge_cup_dev_control_snapshot(team_id)
    except Exception:  # noqa: BLE001 - missing/stale evidence is fail-closed.
        return None
    return snapshot if isinstance(snapshot, Mapping) else None


def _server_contracts(snapshot: Mapping[str, Any] | None) -> tuple[dict[str, str], dict[str, str], str]:
    program = {
        "version": PROGRAM_CONTRACT_VERSION,
        "coreBehaviorHash": CORE_BEHAVIOR_HASH,
    }
    policy = {
        "version": CATALOG_POLICY_VERSION,
        "corePolicyHash": CORE_POLICY_HASH,
    }
    source_commit = ""
    if not isinstance(snapshot, Mapping):
        return program, policy, source_commit
    raw_report = snapshot.get("report")
    if not isinstance(raw_report, Mapping):
        raw_report = snapshot.get("readinessReport")
    if not isinstance(raw_report, Mapping):
        return program, policy, source_commit
    raw_program = raw_report.get("programContract")
    raw_policy = raw_report.get("catalogPolicy")
    if isinstance(raw_program, Mapping):
        program = {
            "version": str(raw_program.get("version") or "").strip(),
            "coreBehaviorHash": str(raw_program.get("coreBehaviorHash") or "").strip(),
        }
    if isinstance(raw_policy, Mapping):
        policy = {
            "version": str(raw_policy.get("version") or "").strip(),
            "corePolicyHash": str(raw_policy.get("corePolicyHash") or "").strip(),
        }
    source_commit = str(raw_report.get("sourceCommit") or "").strip().lower()
    return program, policy, source_commit


def _append_blocker(report: Mapping[str, Any], blocker: str) -> dict[str, Any]:
    """Add a service-level storage blocker and re-seal the report hash."""

    payload = deepcopy(dict(report))
    blockers = [str(item).strip() for item in payload.get("blockers") or [] if str(item).strip()]
    if blocker not in blockers:
        blockers.append(blocker)
    payload["status"] = "NOT_READY"
    payload["nextLegalAction"] = CATALOG_HYPOTHESIS_FLOW_REPAIR_ACTION
    payload["blockers"] = blockers
    payload["readinessReportSha256"] = catalog_hypothesis_flow_report_hash(payload)
    return CatalogHypothesisFlowReadinessReport.from_dict(payload).to_dict()


def get_catalog_hypothesis_flow_readiness(team_id: str) -> dict[str, Any]:
    """Return the server-owned formal catalog readiness report for one team."""

    snapshot = _server_readiness_snapshot(team_id)
    contracts = _server_contracts(snapshot)
    evidence = _evidence_from_server_snapshot(snapshot)
    try:
        loaded = get_real_batch_catalog_state(team_id, plan_id=REAL_CATALOG_PLAN_ID)
    except RealBatchStorageError as exc:
        raise CatalogReadinessStorageError(str(exc)) from exc

    if loaded is None:
        # Use the frozen formal plan only to produce a typed empty result set;
        # this branch is explicitly sealed NOT_READY below and never asserts a
        # durable run or a model policy that was not authorized.
        state = new_real_batch_state(REAL_CATALOG_PLAN_ID)
        model_policy_sha256 = ""
        missing_blocker = "real_batch_missing"
    else:
        state, model_policy_sha256 = loaded
        missing_blocker = ""

    try:
        result_set = build_result_set(state)
        report = build_catalog_hypothesis_flow_readiness_report(
            result_set,
            model_policy_sha256=model_policy_sha256,
            source_commit=contracts[2],
            program_contract=contracts[0],
            catalog_policy=contracts[1],
            evidence=evidence,
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise CatalogReadinessStorageError(
            f"The real-125 catalog result set is not projectable: {exc}"
        ) from exc
    if missing_blocker:
        report = _append_blocker(report, missing_blocker)
    return report


__all__ = [
    "REAL_CATALOG_PLAN_ID",
    "CatalogReadinessStorageError",
    "get_catalog_hypothesis_flow_readiness",
]
