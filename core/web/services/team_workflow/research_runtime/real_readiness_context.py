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
from .budget_authority_adapter import _stage_admitted_tokens
from .human_gate_artifacts import canonical_sha256
from .smoke_release_artifact import smoke_observation_is_releasable
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

    def hypothesis_first_flow(self, team_id: str, run_id: str) -> bool:
        """True when the run's input snapshot carries the hypothesis-first marker."""
        from core.web.services.team_workflow.research_runtime import (
            hypothesis_first_chain,
        )

        run = self._store.get_run(run_id)
        if run is None or run.team_id != team_id:
            return False
        return hypothesis_first_chain.is_hypothesis_first_snapshot(
            hypothesis_first_chain._input_snapshot(run)
        )

    def accepted_knowledge_invocations(
        self, team_id: str, run_id: str
    ) -> list[Mapping[str, Any]]:
        """Knowledge sideflow invocations absorbed into this run (v7 ledger).

        Read-only window over ``knowledge_invocations``; the readiness gate
        in ``readiness.experiment`` applies its own completed/accepted/hash
        filters, so this returns the raw invocation facts.
        """
        try:
            records = self._store.submit(
                lambda uow: uow.repository.list_knowledge_invocations_for_parent(
                    run_id
                ),
                force_flush=True,
            ).result(timeout=10)
        except Exception:  # noqa: BLE001 - unreadable ledger fails closed
            return []
        try:
            delivery_payloads = self._store.read(
                lambda repo: repo.list_knowledge_delivery_event_payloads(run_id)
            )
        except Exception:  # noqa: BLE001 - unreadable events fail closed
            delivery_payloads = []
        delivered: set[tuple[str, str]] = set()
        for raw_payload in delivery_payloads or []:
            try:
                payload = json.loads(str(raw_payload or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(payload, Mapping):
                continue
            delivered.add(
                (
                    str(payload.get("invocationId") or "").strip(),
                    str(payload.get("packageContentHash") or "").strip().lower(),
                )
            )
        views: list[Mapping[str, Any]] = []
        for record in records or []:
            if record is None:
                continue
            if str(record.parent_run_id) != run_id:
                continue
            views.append(
                {
                    "invocationId": str(record.invocation_id),
                    "parentRunId": str(record.parent_run_id),
                    "parentNodeId": str(record.parent_node_id),
                    "status": str(record.status),
                    "handoffState": str(record.handoff_state),
                    "packageContentHash": str(record.package_content_hash or ""),
                    "knowledgePackageRef": str(record.knowledge_package_ref or ""),
                    "absorbed": (
                        str(record.invocation_id),
                        str(record.package_content_hash or "").lower(),
                    )
                    in delivered,
                }
            )
        return views

    def hypothesis_first_chain_state(
        self, team_id: str, question_id: str, workflow_run_id: str
    ) -> Mapping[str, Any] | None:
        from core.web.services.team_workflow.research_runtime import (
            hypothesis_first_chain,
        )

        return hypothesis_first_chain.chain_state(
            team_id,
            question_id,
            workflow_run_id=workflow_run_id,
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
            and smoke_observation_is_releasable(evidence.get("status"))
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
        metrics = (
            result.get("metrics")
            or execution.get("metrics")
            or artifact.get("metrics")
            or result.get("aggregate")
        )
        artifact_hash = (
            result.get("artifactHash")
            or execution.get("artifactHash")
            or artifact.get("artifactHash")
        )
        if not artifact_hash:
            runs = result.get("runs") if isinstance(result.get("runs"), list) else []
            for record in runs:
                if not isinstance(record, dict):
                    continue
                seed_hash = str(record.get("artifactHash") or "").strip()
                if seed_hash:
                    artifact_hash = seed_hash
                    break
        if not artifact_hash:
            artifact_hash = artifact.get("_contentHash")
        logs = (
            result.get("logs")
            or execution.get("logs")
            or artifact.get("logs")
            or result.get("logRef")
            or execution.get("logRef")
        )
        if not logs and (metrics or artifact_hash):
            logs = (
                execution.get("decisionHint")
                or execution.get("formalRunnerUnavailable")
                or artifact.get("formalRunnerUnavailable")
                or f"adapter={execution.get('adapterId') or execution.get('runnerId') or artifact.get('adapterId') or ''} "
                f"status={execution.get('status') or artifact.get('status') or ''}"
            ).strip()
        status = str(execution.get("status") or artifact.get("status") or "").lower()
        terminal = status in {"completed", "succeeded", "failed", "cancelled"}
        if not terminal:
            from .readiness.common import is_bounded_controlled_run

            terminal = is_bounded_controlled_run({**artifact, **execution}) and bool(
                metrics or artifact_hash or logs
            )
        return {
            **artifact,
            "terminal": terminal,
            "logs": logs,
            "metrics": metrics,
            "artifact_hash": artifact_hash,
            "runnerMode": execution.get("runnerMode") or artifact.get("runnerMode"),
            "formalRunnerUnavailable": execution.get("formalRunnerUnavailable")
            or artifact.get("formalRunnerUnavailable"),
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
        max_seconds = int(budget_policy.get("wallClockSeconds") or 21_600)
        consumed = _budget_consumed_from_ledger(self._store, run_id)
        # The operator-owned safety-limits extension (extend_budget) is part
        # of the effective budget window, exactly as the admission authority
        # (budget_authority_adapter._policy_limits) applies it: only-widen,
        # per-run, never the frozen contract or a global default.  Without
        # this mirror, a mid-run budget exhaustion would keep failing the
        # readiness gate (and retry/start with 412) even after the operator
        # raised the ceiling — leaving run abandonment as the only exit.
        override = _safety_limits_override(self._run(run_id))
        stage_token_override = _max_positive_mapping_int(
            override.get("stageTokens") if isinstance(override, Mapping) else None
        )
        if stage_token_override is not None:
            tokens = max(tokens, stage_token_override)
        tool_override = _positive_override_int(override.get("toolCalls"))
        if tool_override is not None:
            tool_calls = max(tool_calls, tool_override)
        seconds_override = _positive_override_int(override.get("wallClockSeconds"))
        if seconds_override is not None:
            max_seconds = max(max_seconds, seconds_override)
        return BudgetLimitsSnapshot(
            policy_hash=_policy_hash(budget_policy),
            stage_tokens_limit=tokens,
            stage_tokens_consumed=int(consumed.get("tokens") or 0),
            max_tool_calls=tool_calls,
            tool_calls_consumed=int(consumed.get("toolCalls") or 0),
            max_seconds=max_seconds,
            seconds_consumed=int(consumed.get("seconds") or 0),
            auto_retries=int(
                budget_policy.get("autoRetries")
                or budget_policy.get("maxRetries")
                or 2
            ),
            retries_consumed=int(consumed.get("retries") or 0),
        )

    def binding_snapshot(self, run_id: str, node_id: str) -> Mapping[str, Any] | None:
        snapshot = self._input_snapshot(run_id)
        frozen: dict[str, Any] | None = None
        for binding in snapshot.get("agentBindingSnapshot") or []:
            if not isinstance(binding, Mapping):
                continue
            if str(binding.get("nodeId") or "") == node_id:
                frozen = dict(binding)
                break
        if frozen and str(frozen.get("agentId") or "").strip():
            return frozen
        healed = _heal_binding(snapshot, node_id)
        return healed or frozen

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


def _heal_binding(snapshot: Mapping[str, Any], node_id: str) -> dict[str, Any] | None:
    from .team_role_source import (
        heal_agent_binding_for_node,
        heal_agent_binding_from_sibling_freeze,
    )

    team_id = str(snapshot.get("teamId") or "").strip()
    node_key = str(node_id or "").strip()
    if not node_key:
        return None
    if team_id:
        healed = heal_agent_binding_for_node(team_id, node_key)
        if healed:
            return dict(healed)
    sibling = heal_agent_binding_from_sibling_freeze(snapshot, node_key)
    return dict(sibling) if sibling else None


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
        envelope = _readiness_artifact_envelope(
            kind,
            team_id=team_id,
            run_id=run_id,
            authority_run_id=authority_run_id,
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


def _readiness_artifact_envelope(
    kind: str,
    *,
    team_id: str,
    run_id: str,
    authority_run_id: str,
) -> dict[str, Any] | None:
    """Recover a same-run record when authority/run ids drifted in compact restore."""
    from .workflow_artifact_store import list_workflow_artifacts

    workflow = str(run_id or "").strip()
    team = str(team_id or "").strip()
    if not team or not workflow:
        return None
    rows = list_workflow_artifacts(team, kind=kind, workflow_run_id=workflow)
    authority = str(authority_run_id or "").strip()
    if not rows and authority and authority != workflow:
        rows = [
            item
            for item in list_workflow_artifacts(
                team, kind=kind, source_collection_run_id=authority
            )
            if str(item.get("workflowRunId") or "") in {workflow, authority}
        ]
    for latest in reversed(rows):
        payload = latest.get("payload")
        if isinstance(payload, dict) and payload:
            return {
                "teamId": team,
                "kind": kind,
                "workflowRunId": str(latest.get("workflowRunId") or workflow),
                "sourceCollectionRunId": str(
                    latest.get("sourceCollectionRunId") or authority or workflow
                ),
                "payload": payload,
            }
    return None


def _budget_consumed_from_ledger(store: WorkflowLedgerStore, run_id: str) -> dict[str, int]:
    try:
        rows = store.submit(
            lambda uow: uow.repository.execute(
                "SELECT reserved_json, settled_json, status FROM budget_receipts "
                "WHERE run_id = ?",
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
    for reserved_json, settled_json, status in rows:
        normalized_status = str(status or "")
        if normalized_status in {"released", "voided", "failed"}:
            continue
        try:
            reserved = json.loads(reserved_json or "{}")
        except (TypeError, ValueError):
            reserved = {}
        if not isinstance(reserved, dict):
            reserved = {}
        inner = reserved.get("reserved") if isinstance(reserved.get("reserved"), dict) else reserved
        # Token consumption mirrors the admission authority's semantics
        # (budget_authority_adapter._stage_admitted_tokens): a live reservation
        # occupies its estimate, a settled attempt occupies its real usage, and
        # "settled usage is the authority" — completion releases the estimate
        # weight so a serial successor stays admissible. Parse failures stay
        # conservative and count the full estimate (gate can only over-block).
        try:
            tokens += _stage_admitted_tokens(
                {
                    "status": normalized_status,
                    "reserved_json": reserved_json,
                    "settled_json": settled_json,
                }
            )
        except (TypeError, ValueError):
            tokens += int(inner.get("estimatedTokens") or inner.get("tokens") or 0)
        if normalized_status not in {"reserved", "settled", "consumed"}:
            continue
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


def _safety_limits_override(run: Any) -> dict[str, Any]:
    """Decode the run's operator-owned safety-limits extension (tolerant)."""

    raw = getattr(run, "safety_limits_json", None) if run is not None else None
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _positive_override_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return int(value)


def _max_positive_mapping_int(value: object) -> int | None:
    """Largest positive int in a stage->limit mapping (adapter semantics)."""

    if not isinstance(value, Mapping):
        return None
    widest: int | None = None
    for item in value.values():
        normalized = _positive_override_int(item)
        if normalized is not None and (widest is None or normalized > widest):
            widest = normalized
    return widest


def _policy_hash(budget_policy: Mapping[str, Any]) -> str:
    if not budget_policy:
        return ""
    raw = json.dumps(budget_policy, sort_keys=True, separators=(",", ":")).encode()
    import hashlib

    return hashlib.sha256(raw).hexdigest()
