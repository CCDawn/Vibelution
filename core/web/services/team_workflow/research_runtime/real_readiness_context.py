"""Production DomainReadinessContext implementation (P1-3 / T5.1-3).

Reads the frozen run input snapshot from the Workflow Ledger and queries the
real domain authorities via readiness_providers. service_overrides remain
unit-test only and must not be required for production composition.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from core.research.workflow.definition import (
    build_challenge_cup_workflow_definition,
)
from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.models import ActorKind

from . import readiness_providers
from .human_gate_artifacts import canonical_sha256
from .readiness.common import (
    BudgetLimitsSnapshot,
    HandoffSnapshot,
)


class RealDomainReadinessContext:
    """Ledger-backed domain context; tests may inject overrides."""

    def __init__(
        self,
        store: WorkflowLedgerStore,
        *,
        adapter_registry: Any | None = None,
        service_overrides: Mapping[str, Any] | None = None,
    ) -> None:
        self._store = store
        self._registry = adapter_registry
        self._overrides = dict(service_overrides or {})

    # --------------------------------------------------------- run access

    def _run(self, run_id: str) -> Any:
        return self._store.get_run(run_id)

    def _input_snapshot(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        if run is None or not run.input_snapshot_json:
            return {}
        try:
            snapshot = json.loads(run.input_snapshot_json)
        except (TypeError, ValueError):
            return {}
        return snapshot if isinstance(snapshot, dict) else {}

    def _query(self, key: str, *args: Any) -> Any:
        if key in self._overrides:
            fn = self._overrides[key]
            return fn(*args) if callable(fn) else fn
        return None

    def _artifact(self, kind: str, team_id: str, run_id: str) -> dict[str, Any] | None:
        snapshot = self._input_snapshot(run_id)
        authority_run_id = str(snapshot.get("sourceCollectionRunId") or run_id).strip()
        return _artifact_payload(
            kind,
            team_id,
            run_id,
            authority_run_id=authority_run_id,
        )

    # ---------------------------------------------------- protocol methods

    def domain_revision_vector(self, team_id: str, run_id: str) -> Mapping[str, str]:
        override = self._query("domain_revision_vector", team_id, run_id)
        if override is not None:
            return dict(override)
        return readiness_providers.build_domain_revision_vector(
            team_id,
            run_id,
            input_snapshot=self._input_snapshot(run_id),
            ledger_store=self._store,
        )

    def question_snapshot(
        self,
        team_id: str,
        question_id: str,
        *,
        run_id: str | None = None,
    ) -> Mapping[str, Any] | None:
        snapshot = self._query("question_snapshot", team_id, question_id)
        if snapshot is not None:
            return snapshot
        preferred = str(run_id or "").strip()
        for candidate_run_id in _run_ids_for(
            self._store, team_id, preferred_run_id=preferred or None
        ):
            run_snapshot = self._input_snapshot(candidate_run_id)
            objective = run_snapshot.get("researchObjectiveContract") or {}
            if str(objective.get("question") or "") and str(
                run_snapshot.get("questionId") or ""
            ) == str(question_id):
                return {
                    "questionId": question_id,
                    "question": str(objective.get("question") or ""),
                    "fromInputSnapshot": True,
                    "runId": candidate_run_id,
                }
        return None

    def candidate_stats(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        override = self._query("candidate_stats", team_id, run_id)
        if override is not None:
            return override
        return readiness_providers.fetch_candidate_stats(
            team_id,
            run_id,
            input_snapshot=self._input_snapshot(run_id),
        )

    def evidence_cards_stats(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        override = self._query("evidence_cards_stats", team_id, run_id)
        if override is not None:
            return override
        return readiness_providers.fetch_evidence_cards_stats(
            team_id,
            run_id,
            input_snapshot=self._input_snapshot(run_id),
        )

    def evidence_graph_stats(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        override = self._query("evidence_graph_stats", team_id, run_id)
        if override is not None:
            return override
        return readiness_providers.fetch_evidence_graph_stats(
            team_id,
            run_id,
            input_snapshot=self._input_snapshot(run_id),
        )

    def knowledge_package_draft(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("knowledge_package_draft", team_id, run_id) or self._artifact(
            "knowledge_package_draft", team_id, run_id
        )

    def knowledge_package(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        if "knowledge_package" in self._overrides:
            return self._query("knowledge_package", team_id, run_id)
        from .human_acceptance_artifact import (
            load_accepted_knowledge_package_from_receipt,
        )

        return load_accepted_knowledge_package_from_receipt(
            self._store,
            team_id=team_id,
            run_id=run_id,
        )

    def hypothesis_set(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("hypothesis_set", team_id, run_id) or self._artifact(
            "hypothesis_set", team_id, run_id
        )

    def protocol_draft(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("protocol_draft", team_id, run_id) or self._artifact(
            "protocol_draft", team_id, run_id
        )

    def protocol_review(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("protocol_review", team_id, run_id) or self._artifact(
            "protocol_review_report", team_id, run_id
        )

    def frozen_protocol(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("frozen_protocol", team_id, run_id) or self._artifact(
            "frozen_protocol", team_id, run_id
        )

    def smoke_evidence(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        override = self._query("smoke_evidence", team_id, run_id)
        if override is not None:
            return override
        evidence = self._artifact("smoke_evidence", team_id, run_id)
        if evidence is None:
            return None
        release = self._artifact("smoke_release", team_id, run_id)
        evidence_smoke_id = str(evidence.get("smokeRunId") or "").strip()
        release_smoke_id = str((release or {}).get("smokeRunId") or "").strip()
        evidence_plan_id = str(evidence.get("planId") or "").strip()
        release_plan_id = str((release or {}).get("planId") or "").strip()
        released = bool(
            release
            and str(evidence.get("status") or "").lower() == "passed"
            and str(release.get("decision") or "").lower() == "accept"
            and str(release.get("resolvedBy") or "").strip()
            and evidence_smoke_id
            and evidence_smoke_id == release_smoke_id
            and evidence_plan_id
            and evidence_plan_id == release_plan_id
        )
        return {**evidence, "released": released, "release": release}

    def controlled_run(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        override = self._query("controlled_run", team_id, run_id)
        if override is not None:
            return override
        artifact = self._artifact("run_artifacts", team_id, run_id)
        if artifact is None:
            return None
        execution = artifact.get("execution") if isinstance(artifact.get("execution"), dict) else {}
        result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
        return {
            **artifact,
            "terminal": str(execution.get("status") or "").lower()
            in {"completed", "succeeded", "failed", "cancelled"},
            "logs": result.get("logs") or execution.get("logs"),
            "metrics": result.get("metrics") or execution.get("metrics"),
            "artifact_hash": result.get("artifactHash")
            or execution.get("artifactHash")
            or artifact.get("_contentHash"),
        }

    def evaluation_report(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("evaluation_report", team_id, run_id) or self._artifact(
            "evaluation_report", team_id, run_id
        )

    def iteration_decision(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("iteration_decision", team_id, run_id) or self._artifact(
            "iteration_decision", team_id, run_id
        )

    def version_governance(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("version_governance", team_id, run_id) or self._artifact(
            "version_governance_record", team_id, run_id
        )

    def promotion_proposal(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        return self._query("promotion_proposal", team_id, run_id) or self._artifact(
            "promotion_proposal", team_id, run_id
        )

    def result_package(self, team_id: str, run_id: str) -> Mapping[str, Any] | None:
        override = self._query("result_package", team_id, run_id)
        if override is not None:
            return override
        artifact = self._artifact("research_result_package", team_id, run_id)
        if artifact is None:
            return None
        package = artifact.get("package") if isinstance(artifact.get("package"), dict) else artifact
        traceability = package.get("traceability") if isinstance(package.get("traceability"), dict) else {}
        return {
            **package,
            "required_artifacts": bool(
                traceability.get("artifactRefs") or package.get("deliverables")
            ),
            "pending_human_tasks": int(package.get("pendingHumanTasks") or 0),
            "terminal_reason": str(package.get("terminalReason") or "").strip(),
        }

    def budget_limits(self, team_id: str, run_id: str) -> BudgetLimitsSnapshot:
        _ = team_id
        snapshot = self._input_snapshot(run_id)
        budget_policy = snapshot.get("budgetPolicy") or {}
        stage_budgets = budget_policy.get("stageBudgets") or {}
        tokens = _first_positive_limit(stage_budgets, "tokens") or int(
            budget_policy.get("tokens") or 250_000
        )
        tool_calls = _first_positive_limit(stage_budgets, "toolCalls") or int(
            budget_policy.get("toolCalls") or 300
        )
        consumed = _budget_consumed_from_ledger(self._store, run_id)
        return BudgetLimitsSnapshot(
            policy_hash=_policy_hash(budget_policy),
            stage_tokens_limit=tokens,
            stage_tokens_consumed=int(consumed.get("tokens") or 0),
            max_tool_calls=tool_calls,
            tool_calls_consumed=int(consumed.get("toolCalls") or 0),
            max_seconds=int(budget_policy.get("wallClockSeconds") or 21_600),
            seconds_consumed=int(consumed.get("seconds") or 0),
            auto_retries=int(budget_policy.get("autoRetries") or 2),
            retries_consumed=int(consumed.get("retries") or 0),
        )

    def binding_snapshot(self, run_id: str, node_id: str) -> Mapping[str, Any] | None:
        snapshot = self._input_snapshot(run_id)
        for binding in snapshot.get("agentBindingSnapshot") or []:
            if not isinstance(binding, Mapping):
                continue
            if str(binding.get("nodeId") or "") == node_id:
                return dict(binding)
        return None

    def agent_resolvable(self, agent_id: str) -> bool:
        override = self._query("agent_resolvable", agent_id)
        if override is not None:
            return bool(override)
        return readiness_providers.is_agent_resolvable(agent_id)

    def recovery_blocker_codes(self, run_id: str) -> Sequence[str]:
        rows = self._store.submit(
            lambda uow: uow.repository.execute(
                "SELECT problem_code FROM recovery_records "
                "WHERE run_id = ? AND status = 'open'",
                (run_id,),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        return [str(row[0]) for row in rows]

    def adapter_registered(self, node_id: str) -> bool:
        if self._registry is None:
            return True
        definition = build_challenge_cup_workflow_definition()
        node = next(
            (n for n in definition.nodes if n.nodeId == node_id), None
        )
        if node is None:
            return False
        if node.actorKind == ActorKind.AGENT:
            kind = "start_agent_task"
        elif node.actorKind == ActorKind.SYSTEM:
            kind = f"system_action:{node_id}"
        else:
            kind = f"human_task:{node_id}"
        return self._registry.get(kind) is not None

    def incoming_handoffs(self, run_id: str, node_id: str) -> Sequence[HandoffSnapshot]:
        rows = self._store.submit(
            lambda uow: uow.repository.list_handoffs_for_node(run_id, node_id),
            force_flush=True,
        ).result(timeout=10)
        return [
            HandoffSnapshot(
                handoff_id=str(row[0]),
                from_node_run_id=str(row[3]) if row[3] else "",
                status=str(row[8]) if len(row) > 8 else "",
            )
            for row in rows
        ]


def _artifact_payload(
    kind: str,
    team_id: str,
    run_id: str,
    *,
    authority_run_id: str,
) -> dict[str, Any] | None:
    """Load readiness facts from the formal scoped artifact authority only.

    Never reads ``data/domain_artifacts`` (parallel store forbidden) and never
    picks "latest file" across runs.
    """
    from .artifact_readback_registry import load_scoped_artifact_payload

    envelope = load_scoped_artifact_payload(
        kind,
        team_id=team_id,
        authority_run_id=authority_run_id,
        workflow_run_id=run_id,
    )
    if envelope is None:
        return None
    raw_payload = envelope.get("payload")
    payload = dict(raw_payload) if isinstance(raw_payload, dict) else dict(envelope)
    return {
        **payload,
        "runId": run_id,
        "teamId": team_id,
        "_contentHash": canonical_sha256(envelope),
    }


def _budget_consumed_from_ledger(store: WorkflowLedgerStore, run_id: str) -> dict[str, int]:
    try:
        rows = store.submit(
            lambda uow: uow.repository.execute(
                "SELECT reserved_json, status FROM budget_receipts WHERE run_id = ?",
                (run_id,),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
    except Exception:
        return {}
    tokens = 0
    tool_calls = 0
    seconds = 0
    retries = 0
    for reserved_json, status in rows:
        if str(status or "") not in {"reserved", "settled", "consumed"}:
            continue
        try:
            reserved = json.loads(reserved_json or "{}")
        except (TypeError, ValueError):
            reserved = {}
        if not isinstance(reserved, dict):
            reserved = {}
        inner = reserved.get("reserved") if isinstance(reserved.get("reserved"), dict) else reserved
        tokens += int(inner.get("estimatedTokens") or inner.get("tokens") or 0)
        tool_calls += int(inner.get("toolCalls") or 0)
        seconds += int(inner.get("seconds") or inner.get("wallClockSeconds") or 0)
        retries += int(inner.get("retries") or 0)
    return {
        "tokens": tokens,
        "toolCalls": tool_calls,
        "seconds": seconds,
        "retries": retries,
    }


def _run_ids_for(
    store: WorkflowLedgerStore,
    team_id: str,
    *,
    preferred_run_id: str | None = None,
) -> list[str]:
    """Return team run ids, preferring the caller's current run when provided."""
    preferred = str(preferred_run_id or "").strip()
    rows = store.submit(
        lambda uow: uow.repository.execute(
            "SELECT run_id FROM workflow_runs WHERE team_id = ? "
            "ORDER BY created_at_ms DESC LIMIT 50",
            (team_id,),
        ).fetchall(),
        force_flush=True,
    ).result(timeout=10)
    run_ids = [str(row[0]) for row in rows]
    if not preferred:
        return run_ids
    ordered = [preferred]
    for rid in run_ids:
        if rid != preferred:
            ordered.append(rid)
    return ordered


def _first_positive_limit(stage_budgets: Mapping[str, Any], key: str) -> int | None:
    if not isinstance(stage_budgets, Mapping):
        return None
    for _stage, limits in stage_budgets.items():
        if isinstance(limits, Mapping) and int(limits.get(key) or 0) > 0:
            return int(limits[key])
    return None


def _policy_hash(budget_policy: Mapping[str, Any]) -> str:
    if not budget_policy:
        return ""
    raw = json.dumps(budget_policy, sort_keys=True, separators=(",", ":")).encode()
    import hashlib

    return hashlib.sha256(raw).hexdigest()
