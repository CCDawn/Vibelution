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

    def recover_dead_turn_children(self, *, limit: int = 4) -> int:
        """Drive the parent reconcile for knowledge children with dead turns.

        Restart recovery for the 2026-09-10 run-f9bf7be5985e deadlock: an
        external restart marks a sideflow child turn ``interrupted`` (durable
        turn-journal fact), the child lands ``blocked`` with the canonical
        ``agent_turn_terminal_failed`` problem, and because ``blocked`` is
        deliberately non-terminal the invocation stays live forever — the
        ensure offer is permanently locked and no operator surface can repair
        the dead turn.  The repair contract already exists: the parent
        ``reconcile_run`` handler fails such invocations fail-closed from the
        child's durable ``blocked_problem_json`` (dead-turn exception) and
        cascades the ledger replan into the child.  This pass is its automated
        driver: only children whose durable problem proves the dead turn AND
        whose invocation is still live are eligible, the reconcile is
        submitted through the normal command service (operator-scoped system
        actor — reconcile_run is operator-only), and the deterministic
        idempotency key (child + problem hash) makes replays converge.
        Fail-closed: any other blocked reason is never touched here.
        """
        remaining = max(0, int(limit))
        if remaining == 0:
            return 0

        from .knowledge_sideflow_service import dead_agent_turn_block_problem

        def load_candidates(repo: Any) -> list[tuple[Any, Any, dict[str, Any]]]:
            candidates: list[tuple[Any, Any, dict[str, Any]]] = []
            for run in repo.list_runs_for_team(
                CHALLENGE_CUP_TEAM_ID,
                KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
            ):
                if len(candidates) >= remaining:
                    break
                if str(run.status or "").strip() != "blocked":
                    continue
                dead_turn = dead_agent_turn_block_problem(run.blocked_problem_json)
                if dead_turn is None:
                    # 预算、围栏、waiting 等其他 blocked 原因不归本 pass 管。
                    continue
                invocation = repo.find_knowledge_invocation_by_child_run(run.run_id)
                if invocation is None:
                    continue
                if str(getattr(invocation, "status", "") or "") in (
                    "completed",
                    "failed",
                    "cancelled",
                ):
                    # 已终态：无死锁可清，子 run 剩余 blocked 归重试/父对账。
                    continue
                parent = repo.get_run(str(invocation.parent_run_id or ""))
                if parent is None or str(parent.status or "").strip() in {
                    "succeeded", "failed", "cancelled", "archived",
                }:
                    continue
                candidates.append((run, parent, dead_turn))
            return candidates

        try:
            candidates = self._store.read(load_candidates)
        except Exception as exc:  # noqa: BLE001 - one read failure must not stop the sweep
            self._record_dead_turn("failed", error=type(exc).__name__)
            return 0

        recovered = 0
        for child, parent, dead_turn in candidates:
            try:
                identity_hash = canonical_sha256(
                    {
                        "childRunId": child.run_id,
                        "parentRunId": parent.run_id,
                        "code": str(dead_turn.get("code") or ""),
                        "terminalStatus": str(dead_turn.get("terminalStatus") or ""),
                    }
                )
                from .operator_authorization import server_operator_scope

                with server_operator_scope(
                    "system:knowledge-dead-turn-recovery",
                    display_name="Knowledge sideflow dead-turn recovery",
                    roles=("operator",),
                ):
                    self._command_service.submit(
                        CommandRequest(
                            command_id=f"cmd-knowledge-dead-turn-{identity_hash[:24]}",
                            run_id=parent.run_id,
                            team_id=parent.team_id,
                            command=WorkflowCommandKind.RECONCILE_RUN,
                            node_id=None,
                            expected_run_version=int(parent.run_version),
                            idempotency_key=(
                                f"knowledge-auto-dead-turn-reconcile:{identity_hash}"
                            ),
                            payload={
                                "reason": "knowledge_sideflow_dead_turn",
                                "childRunId": child.run_id,
                            },
                            requested_by=ActorRef(
                                "system", "knowledge-sideflow-dead-turn-recovery"
                            ),
                            requested_at_ms=self._now(),
                        )
                    )
            except Exception as exc:  # noqa: BLE001 - one stale child must not stop the sweep
                self._record_dead_turn(
                    "failed", run=child, error=type(exc).__name__
                )
                continue
            recovered += 1
            self._record_dead_turn("submitted", run=child, parent_run_id=parent.run_id)
        return recovered

    def recover_failed_invocations(self, *, limit: int = 4) -> int:
        """Re-ensure knowledge collections whose invocation failed terminally.

        Auto-advance closure for the failed-invocation leg of the knowledge
        sideflow.  A parent blocked on ``knowledge_package_not_materialized``
        whose latest invocation is ``failed`` (typically after the dead-turn
        reconcile above) is machine-recoverable while the knowledge retry
        budget lasts: this pass re-submits ``ensure_knowledge_collection``
        through the normal command service.  The retry references the failed
        invocation in its requirements marker, so the request hash moves and
        ``ensure_knowledge_invocation`` creates a FRESH invocation instead of
        replaying the terminal one (the same mechanism that keeps the original
        trigger's request distinct from a manual click).

        Budget authority: ``DEFAULT_STAGE_BUDGET_MAX_RETRIES`` from
        ``knowledge_capability`` — the exact constant that separates
        ``retry_within_budget`` (auto_allowed) from ``retry_over_budget``
        (human gate).  Once that many automated retries have already failed
        for the node, the stop stays human-visible and this pass declines.
        """
        remaining = max(0, int(limit))
        if remaining == 0:
            return 0

        from .knowledge_capability import DEFAULT_STAGE_BUDGET_MAX_RETRIES

        def load_candidates(repo: Any) -> list[tuple[Any, Any]]:
            candidates: list[tuple[Any, Any]] = []
            for run in repo.list_runs_for_team(
                CHALLENGE_CUP_TEAM_ID,
                CHALLENGE_CUP_WORKFLOW_ID,
            ):
                if len(candidates) >= remaining:
                    break
                if (
                    str(run.status or "").strip() != "blocked"
                    or not _has_missing_knowledge_blocker(run.blocked_problem_json)
                ):
                    continue
                invocations = list(
                    repo.list_knowledge_invocations_for_parent(run.run_id)
                )
                if not invocations:
                    # 无 invocation 的缺口归 recover_missing 管。
                    continue
                if any(
                    str(getattr(item, "status", "") or "")
                    in {"pending", "child_created", "running", "awaiting_handoff"}
                    for item in invocations
                ):
                    continue
                invocations.sort(
                    key=lambda item: (
                        int(getattr(item, "created_at_ms", 0) or 0),
                        str(getattr(item, "invocation_id", "") or ""),
                    )
                )
                latest = invocations[-1]
                if str(getattr(latest, "status", "") or "") != "failed":
                    continue
                candidates.append((run, latest))
            return candidates

        try:
            candidates = self._store.read(load_candidates)
        except Exception as exc:  # noqa: BLE001 - one read failure must not stop the sweep
            self._record_failed_retry("failed", error=type(exc).__name__)
            return 0

        recovered = 0
        for run, failed_invocation in candidates:
            run_id = str(run.run_id or "")
            try:
                node_id = str(failed_invocation.parent_node_id or "").strip()
                failed_count = sum(
                    1
                    for item in self._store.read(
                        lambda repo, parent_run_id=run_id: list(
                            repo.list_knowledge_invocations_for_parent(parent_run_id)
                        )
                    )
                    if str(getattr(item, "status", "") or "") == "failed"
                    and str(getattr(item, "parent_node_id", "") or "") == node_id
                )
                if failed_count > max(0, int(DEFAULT_STAGE_BUDGET_MAX_RETRIES)):
                    # 预算耗尽：留给人工按钮，不动作。
                    self._record_failed_retry(
                        "declined",
                        run=run,
                        reason="knowledge_retry_budget_exhausted",
                        fields={
                            "failedInvocations": failed_count,
                            "maxRetries": int(DEFAULT_STAGE_BUDGET_MAX_RETRIES),
                        },
                    )
                    continue
                attempt = self._store.read(
                    lambda repo, parent_run_id=run_id: repo.latest_attempt(
                        parent_run_id, "problem_understanding"
                    )
                )
                if (
                    attempt is None
                    or str(attempt.status or "").strip() != "succeeded"
                    or not str(attempt.node_run_id or "").strip()
                ):
                    self._record_failed_retry(
                        "skipped", run=run, reason="problem_artifact_unavailable",
                    )
                    continue
                artifact = problem_artifact_for_collection(
                    team_id=run.team_id,
                    run_id=run.run_id,
                    node_run_id=str(attempt.node_run_id or "").strip(),
                )
                if artifact is None:
                    self._record_failed_retry(
                        "skipped", run=run, reason="problem_artifact_unavailable",
                    )
                    continue
                keywords = _problem_keywords(artifact["payload"])
                if not keywords:
                    self._record_failed_retry(
                        "skipped", run=run, reason="problem_keywords_missing",
                    )
                    continue
                try:
                    snapshot = json.loads(str(run.input_snapshot_json or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    snapshot = {}
                raw_roots = (
                    snapshot.get("managedSourceRootIds")
                    if isinstance(snapshot, Mapping)
                    else []
                )
                roots = [
                    str(item).strip()
                    for item in (raw_roots if isinstance(raw_roots, (list, tuple)) else [])
                    if str(item).strip()
                ]
                identity_hash = canonical_sha256(
                    {
                        "runId": run.run_id,
                        "nodeId": node_id,
                        "retriesOfInvocationId": str(
                            failed_invocation.invocation_id or ""
                        ),
                    }
                )
                receipt = self._command_service.submit(
                    CommandRequest(
                        command_id=f"cmd-knowledge-retry-{identity_hash[:24]}",
                        run_id=run.run_id,
                        team_id=run.team_id,
                        command=WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION,
                        node_id=node_id,
                        expected_run_version=int(run.run_version),
                        idempotency_key=f"knowledge-auto-retry:{identity_hash}",
                        payload={
                            "questionId": run.question_id,
                            "searchEnvelope": {
                                "keywords": keywords,
                                "evidenceTypes": [],
                                "timeWindow": {},
                            },
                            # retry 引用被重试的 invocation：requestHash 随之
                            # 移动，ensure 幂等不会重放终态 invocation，而是
                            # 创建全新请求；对同一失败 invocation 的重复提交
                            # 仍收敛到同一次重试。
                            "requirements": {
                                "trigger": "knowledge_failed_auto_retry",
                                "retriesOfInvocationId": str(
                                    failed_invocation.invocation_id or ""
                                ),
                            },
                            "sourcePolicyVersion": DEFAULT_SOURCE_POLICY_VERSION,
                            "managedSourceRootIds": roots,
                            "triggerNodeRunId": str(attempt.node_run_id or ""),
                        },
                        requested_by=ActorRef(
                            "system", "knowledge-sideflow-failed-retry"
                        ),
                        requested_at_ms=self._now(),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one stale parent must not stop the sweep
                self._record_failed_retry("failed", run=run, error=type(exc).__name__)
                continue
            result = dict(receipt.result or {})
            status = "replayed" if result.get("replayed") else "submitted"
            recovered += 1
            self._record_failed_retry(status, run=run, result=result)
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
    def _record_dead_turn(
        status: str,
        run: Any = None,
        *,
        parent_run_id: str = "",
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
                    "knowledge_sideflow.dead_turn_reconcile_failed"
                    if status == "failed"
                    else "knowledge_sideflow.dead_turn_reconcile_submitted"
                ),
                level="warning" if status == "failed" else "info",
                outcome=status,
                fields={
                    "childRunId": str(getattr(run, "run_id", "") or ""),
                    "parentRunId": str(parent_run_id),
                    "error": error,
                },
            )
        except Exception:  # noqa: BLE001, S110 - telemetry cannot break recovery
            pass

    @staticmethod
    def _record_failed_retry(
        status: str,
        run: Any = None,
        *,
        result: Mapping[str, Any] | None = None,
        reason: str = "",
        fields: Mapping[str, Any] | None = None,
        error: str = "",
    ) -> None:
        try:
            from core.web.services.runtime_scene_service import (
                record_runtime_scene_event_quietly,
            )

            record_runtime_scene_event_quietly(
                "team_workflow_orchestration",
                "knowledge_sideflow_trigger",
                f"knowledge_sideflow.failed_retry_{status}",
                level="warning" if status in {"failed", "declined"} else "info",
                outcome=status,
                fields={
                    "runId": str(getattr(run, "run_id", "") or ""),
                    "invocationId": str((result or {}).get("invocationId") or ""),
                    "childRunId": str((result or {}).get("childRunId") or ""),
                    "reason": reason,
                    **dict(fields or {}),
                    "error": error,
                },
            )
        except Exception:  # noqa: BLE001, S110 - telemetry cannot break recovery
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
