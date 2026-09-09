"""Collect evidence after problem understanding without inventing approval."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from core.research.workflow.contracts import (
    ActorRef,
    CommandRequest,
    WorkflowCommandKind,
)
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID, SCHEMA_VERSION
from core.research.workflow.definition_registry import resolve_definition_for_run_record
from core.research.workflow.stage_one_definition import STAGE_ONE_SCHEMA_VERSION
from core.research.workflow.knowledge_sideflow_definition import (
    KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
)
from core.research.workflow.ledger import WorkflowLedgerStore

from .human_gate_artifacts import canonical_sha256
from .knowledge_sideflow_service import DEFAULT_SOURCE_POLICY_VERSION

CHALLENGE_CUP_TEAM_ID = "research-team"
RECOVERABLE_BLOCK_CODE = "auto_advance_not_ready"
MISSING_KNOWLEDGE_BLOCKER = "knowledge_package_not_materialized"
QUOTE_ANCHOR_RETRY_NODE_ID = "source_extraction"
QUOTE_ANCHOR_MISSING_ARTIFACT = "evidence_card_batch"


class KnowledgeSideflowTrigger:
    """Ensure one child after completed problem understanding, then return."""

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
        if definition.schemaVersion not in (SCHEMA_VERSION, STAGE_ONE_SCHEMA_VERSION):
            # Stage-one runs pin the trimmed 3.1 main flow whose nodes this
            # trigger joins; both sanctioned schema versions are canonical.
            return {"status": "not_canonical"}

        artifact = problem_artifact_for_collection(
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
                    "requirements": {"trigger": "problem_understanding_completed"},
                    "sourcePolicyVersion": DEFAULT_SOURCE_POLICY_VERSION,
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

    def recover_missing(self, *, limit: int = 4) -> int:
        """Replay lost problem-understanding callbacks from durable facts.

        The normal path invokes :meth:`on_node_succeeded` after the graph
        transaction commits.  That callback is deliberately best-effort, so a
        process interruption can leave a parent blocked at hypothesis design
        even though its problem artifact and successful attempt are durable.
        Only that exact state is eligible here; the existing trigger remains
        the sole writer for knowledge invocation creation.
        """
        remaining = max(0, int(limit))
        if remaining == 0:
            return 0

        def load_candidates(repo: Any) -> list[tuple[Any, str]]:
            candidates: list[tuple[Any, str]] = []
            for run in repo.list_runs_for_team(
                CHALLENGE_CUP_TEAM_ID,
                CHALLENGE_CUP_WORKFLOW_ID,
            ):
                if len(candidates) >= remaining:
                    break
                if (
                    str(run.status or "").strip() != "blocked"
                    or str(run.active_node_id or "").strip() != "hypothesis_design"
                    or not _has_missing_knowledge_blocker(run.blocked_problem_json)
                ):
                    continue
                if repo.list_knowledge_invocations_for_parent(run.run_id):
                    continue
                attempt = repo.latest_attempt(run.run_id, "problem_understanding")
                if (
                    attempt is None
                    or str(attempt.status or "").strip() != "succeeded"
                    or not str(attempt.node_run_id or "").strip()
                ):
                    continue
                candidates.append((run, str(attempt.node_run_id).strip()))
            return candidates

        candidates = self._store.read(load_candidates)
        recovered = 0
        for run, node_run_id in candidates:
            try:
                result = self.on_node_succeeded(
                    run_id=run.run_id,
                    node_id="problem_understanding",
                    node_run_id=node_run_id,
                )
            except Exception as exc:  # noqa: BLE001 - one stale run must not stop the sweep
                self._record("failed", run, error=type(exc).__name__)
                continue
            if str(result.get("status") or "") in {"submitted", "replayed"}:
                recovered += 1
        return recovered

    def recover_blocked_quote_anchor_extractions(self, *, limit: int = 4) -> int:
        """Retry only knowledge children blocked after correctable quote review.

        The node blocker alone is insufficient: the matching canonical stage
        task must still carry the exact automatic quote-anchor remediation.
        The retry uses the normal command service and an attempt-scoped
        idempotency key, so maintenance replays cannot create a second retry.
        """

        remaining = max(0, int(limit))
        if remaining == 0:
            return 0

        def load_candidates(repo: Any) -> list[tuple[Any, Any, str]]:
            candidates: list[tuple[Any, Any, str]] = []
            for run in repo.list_runs_for_team(
                CHALLENGE_CUP_TEAM_ID,
                KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
            ):
                if len(candidates) >= remaining:
                    break
                if (
                    str(run.status or "").strip() != "blocked"
                    or str(run.active_node_id or "").strip()
                    != QUOTE_ANCHOR_RETRY_NODE_ID
                    or not _has_quote_anchor_artifact_blocker(run.blocked_problem_json)
                ):
                    continue
                attempt = repo.latest_attempt(run.run_id, QUOTE_ANCHOR_RETRY_NODE_ID)
                if (
                    attempt is None
                    or str(attempt.status or "").strip() != "blocked"
                    or bool(str(attempt.retry_of_node_run_id or "").strip())
                    or not _has_quote_anchor_artifact_blocker(attempt.problem_json)
                ):
                    continue
                try:
                    snapshot = json.loads(str(run.input_snapshot_json or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                source_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
                if source_run_id:
                    candidates.append((run, attempt, source_run_id))
            return candidates

        candidates = self._store.read(load_candidates)
        recovered = 0
        from .stage_task_remediation import (
            extraction_quote_anchor_remediation,
            source_stage_task_for_node_run,
        )

        for run, attempt, source_run_id in candidates:
            try:
                task = source_stage_task_for_node_run(
                    team_id=run.team_id,
                    source_run_id=source_run_id,
                    node_run_id=attempt.node_run_id,
                )
                if not extraction_quote_anchor_remediation(task):
                    continue
                fresh = self._store.get_run(run.run_id)
                if (
                    fresh is None
                    or str(fresh.status or "").strip() != "blocked"
                    or int(fresh.run_version) != int(run.run_version)
                ):
                    continue
                identity_hash = canonical_sha256(
                    {
                        "runId": run.run_id,
                        "nodeId": QUOTE_ANCHOR_RETRY_NODE_ID,
                        "nodeRunId": attempt.node_run_id,
                        "reason": "quote_anchor_remediation",
                    }
                )
                self._command_service.submit(
                    CommandRequest(
                        command_id=f"cmd-knowledge-retry-{identity_hash[:24]}",
                        run_id=run.run_id,
                        team_id=run.team_id,
                        command=WorkflowCommandKind.RETRY_NODE,
                        node_id=QUOTE_ANCHOR_RETRY_NODE_ID,
                        expected_run_version=int(fresh.run_version),
                        idempotency_key=f"knowledge-auto-quote-retry:{identity_hash}",
                        payload={
                            "reason": "quote_anchor_remediation",
                            "retryOfNodeRunId": attempt.node_run_id,
                        },
                        requested_by=ActorRef(
                            "system", "knowledge-sideflow-remediation"
                        ),
                        requested_at_ms=self._now(),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - isolate one stale child
                self._record_quote_retry("failed", run, error=type(exc).__name__)
                continue
            recovered += 1
            self._record_quote_retry("submitted", run, node_run_id=attempt.node_run_id)
        return recovered

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

    @staticmethod
    def _record_quote_retry(
        status: str,
        run: Any,
        *,
        node_run_id: str = "",
        error: str = "",
    ) -> None:
        try:
            from core.web.services.runtime_scene_service import (
                record_runtime_scene_event_quietly,
            )

            record_runtime_scene_event_quietly(
                "team_workflow_orchestration",
                "knowledge_sideflow_trigger",
                "knowledge_sideflow.quote_anchor_retry",
                level="warning" if status == "failed" else "info",
                outcome=status,
                fields={
                    "runId": str(run.run_id or ""),
                    "nodeRunId": str(node_run_id or ""),
                    "error": error,
                },
            )
        except Exception:  # noqa: BLE001, S110 - telemetry cannot break recovery
            pass


def problem_artifact_for_collection(
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
        # Evidence collection is preparation for review, not an approval of
        # the hypothesis or permission to execute an experiment. Keep the
        # original gate untouched; rejected/revision-requested scopes stop.
        and item["payload"]["human_gate"].get("decision") in {"pending", "approved"}
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


def _has_missing_knowledge_blocker(raw_problem: str | None) -> bool:
    try:
        problem = json.loads(str(raw_problem or "") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(problem, Mapping):
        return False
    if str(problem.get("code") or "").strip() != RECOVERABLE_BLOCK_CODE:
        return False
    blockers = {
        item.strip()
        for item in str(problem.get("detail") or "").split(";")
        if item.strip()
    }
    return MISSING_KNOWLEDGE_BLOCKER in blockers


def _has_quote_anchor_artifact_blocker(raw_problem: str | None) -> bool:
    try:
        problem = json.loads(str(raw_problem or "") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(problem, Mapping):
        return False
    return (
        str(problem.get("code") or "").strip() == "required_artifact_missing"
        and QUOTE_ANCHOR_MISSING_ARTIFACT in str(problem.get("detail") or "")
    )


__all__ = ["KnowledgeSideflowTrigger", "problem_artifact_for_collection"]
