"""Post-commit trigger for the Challenge Cup 3.0 knowledge sideflow."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from core.research.workflow.contracts import (
    ActorRef,
    CommandRequest,
    WorkflowCommandKind,
)
from core.research.workflow.definition_registry import (
    resolve_definition_for_run_record,
)
from core.research.workflow.knowledge_sideflow_definition import (
    CHALLENGE_CUP_RESEARCH_SCHEMA_VERSION_V3,
)
from core.research.workflow.ledger import WorkflowLedgerStore

from .human_gate_artifacts import canonical_sha256


class KnowledgeSideflowTrigger:
    """Ensure one child after accepted problem understanding, then return."""

    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        command_service: Any,
        now_provider: Callable[[], int],
    ) -> None:
        self._store = store
        self._command_service = command_service
        self._now = now_provider

    def on_node_succeeded(
        self,
        *,
        run_id: str,
        node_id: str,
        node_run_id: str,
    ) -> dict[str, Any]:
        if str(node_id or "").strip() != "problem_understanding":
            return {"status": "ignored"}
        from .knowledge_rollout import knowledge_ensure_enabled

        if not knowledge_ensure_enabled():
            return {"status": "disabled"}
        run = self._store.get_run(str(run_id or "").strip())
        if run is None:
            return {"status": "unknown_run"}
        try:
            definition = resolve_definition_for_run_record(
                {
                    "runId": run.run_id,
                    "workflowId": run.workflow_id,
                    "workflowVersionId": run.workflow_version_id,
                    "structureHash": run.structure_hash,
                    "completedNodeIds": ["problem_understanding"],
                    "runtimeCurrentNodeIds": [],
                },
                expected_node_ids=["problem_understanding", "hypothesis_design"],
            )
        except Exception as exc:
            self._record("failed", run, error=type(exc).__name__)
            return {"status": "failed", "error": "definition_resolution_failed"}
        if definition.schemaVersion != CHALLENGE_CUP_RESEARCH_SCHEMA_VERSION_V3:
            return {"status": "not_v3"}

        artifact = _accepted_problem_artifact(
            team_id=run.team_id,
            run_id=run.run_id,
            node_run_id=str(node_run_id or "").strip(),
        )
        if artifact is None:
            self._record("failed", run, error="problem_understanding_missing")
            return {"status": "failed", "error": "problem_understanding_missing"}
        problem = dict(artifact["payload"])
        keywords = _problem_keywords(problem)
        if not keywords:
            self._record("failed", run, error="problem_keywords_missing")
            return {"status": "failed", "error": "problem_keywords_missing"}
        try:
            snapshot = json.loads(str(run.input_snapshot_json or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            snapshot = {}
        raw_roots = (
            snapshot.get("managedSourceRootIds")
            if isinstance(snapshot, Mapping)
            else []
        )
        if not isinstance(raw_roots, (list, tuple)):
            raw_roots = []
        roots = [
            str(item).strip()
            for item in raw_roots
            if str(item).strip()
        ]
        identity_hash = canonical_sha256(
            {
                "runId": run.run_id,
                "nodeRunId": str(node_run_id or ""),
                "artifactHash": str(artifact.get("contentHash") or ""),
                "keywords": keywords,
            }
        )
        receipt = self._command_service.submit(
            CommandRequest(
                command_id=f"cmd-knowledge-auto-{identity_hash[:24]}",
                run_id=run.run_id,
                team_id=run.team_id,
                command=WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION,
                node_id="hypothesis_design",
                expected_run_version=int(run.run_version),
                idempotency_key=f"knowledge-auto-ensure:{identity_hash}",
                payload={
                    "questionId": run.question_id,
                    "searchEnvelope": {
                        "keywords": keywords,
                        "evidenceTypes": [],
                        "timeWindow": {},
                    },
                    "requirements": {"trigger": "problem_understanding_accepted"},
                    "sourcePolicyVersion": "1",
                    "managedSourceRootIds": roots,
                    "triggerNodeRunId": str(node_run_id or ""),
                },
                requested_by=ActorRef("system", "knowledge-sideflow-trigger"),
                requested_at_ms=self._now(),
            )
        )
        result = dict(receipt.result or {})
        status = "replayed" if result.get("replayed") else "submitted"
        self._record(status, run, result=result)
        return {
            "status": status,
            "invocationId": str(result.get("invocationId") or ""),
            "childRunId": str(result.get("childRunId") or ""),
        }

    @staticmethod
    def _record(
        status: str,
        run: Any,
        *,
        result: Mapping[str, Any] | None = None,
        error: str = "",
    ) -> None:
        try:
            from core.web.services.runtime_scene_service import (
                record_runtime_scene_event_quietly,
            )

            record_runtime_scene_event_quietly(
                "team_workflow_orchestration",
                "knowledge_sideflow_trigger",
                (
                    "knowledge_sideflow.auto_ensure_replayed"
                    if status == "replayed"
                    else "knowledge_sideflow.auto_ensure_submitted"
                    if status == "submitted"
                    else "knowledge_sideflow.auto_ensure_failed"
                ),
                level="warning" if status == "failed" else "info",
                outcome=status,
                fields={
                    "runId": str(run.run_id or ""),
                    "invocationId": str((result or {}).get("invocationId") or ""),
                    "childRunId": str((result or {}).get("childRunId") or ""),
                    "error": error,
                },
            )
        except Exception:
            pass


def _accepted_problem_artifact(
    *,
    team_id: str,
    run_id: str,
    node_run_id: str,
) -> dict[str, Any] | None:
    from .workflow_artifact_store import list_workflow_artifacts

    records = list_workflow_artifacts(
        team_id,
        kind="problem_understanding",
        workflow_run_id=run_id,
    )
    matches = [
        dict(item)
        for item in records
        if isinstance(item, Mapping)
        and str(item.get("recordId") or "").strip() == node_run_id
        and isinstance(item.get("payload"), Mapping)
        and isinstance(item["payload"].get("human_gate"), Mapping)
        and item["payload"]["human_gate"].get("decision") == "approved"
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _problem_keywords(problem: Mapping[str, Any]) -> list[str]:
    candidates = [
        problem.get("scope"),
        *list(problem.get("subquestions") or []),
        *list(problem.get("known_unknowns") or []),
    ]
    keywords: list[str] = []
    for item in candidates:
        value = str(item or "").strip()[:120]
        if value and value not in keywords:
            keywords.append(value)
        if len(keywords) >= 8:
            break
    return keywords


__all__ = ["KnowledgeSideflowTrigger"]
