"""Knowledge sideflow dead-turn recovery: reconcile exception + auto re-ensure.

Covers the 2026-09-10 run-f9bf7be5985e deadlock (external restart marked a
sideflow child turn ``interrupted``; the blocked child deliberately never
turned its invocation terminal, so the ensure offer stayed locked forever):

- reconcile_run fails an invocation fail-closed from the child's durable
  ``blocked_problem_json`` ONLY for the ``agent_turn_terminal_failed`` +
  failure-terminal ``terminalStatus`` shape (interrupted/failed); every
  other blocked reason (budget, non-terminal turn status) must not move the
  invocation;
- the maintenance sweep drives the parent reconcile automatically so a
  restart self-heals without a manual click;
- the failed invocation is re-ensured through the normal command service
  while the knowledge retry budget (``DEFAULT_STAGE_BUDGET_MAX_RETRIES``)
  lasts, and declined once it is exhausted.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import (
    register_or_resolve,
    reset_registry_for_tests,
)
from core.research.workflow.knowledge_sideflow_definition import (
    KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
)
from core.research.workflow.ledger.records import KnowledgeInvocationRecord

from core.web.services.team_workflow.research_runtime.command_service import (
    WorkflowCommandService,
)
from core.web.services.team_workflow.research_runtime.knowledge_capability import (
    DEFAULT_STAGE_BUDGET_MAX_RETRIES,
)
from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import (
    dead_agent_turn_block_problem,
    record_knowledge_sideflow_child_failure,
)
from core.web.services.team_workflow.research_runtime.readiness import NodeReadinessService
from core.web.services.team_workflow.research_runtime.readiness.common import RunSnapshot

from tests._support.readiness_fakes import FakeDomainContext
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_run_record,
    open_ledger_store,
)


_PINNED = register_or_resolve(build_challenge_cup_workflow_definition())

_DEAD_TURN_PROBLEM = {
    "code": "agent_turn_terminal_failed",
    "sessionId": "sess-dead-turn",
    "turnId": "turn-dead-turn",
    "terminalStatus": "interrupted",
    "completionSource": "turn_journal",
    "failureClass": "terminal_non_success",
}

_BUDGET_PROBLEM = {
    "code": "budget_precheck_insufficient",
    "detail": "stage budget exhausted",
    "stageId": "evidence",
    "stageLimitTokens": 1000,
    "suggestedExtensionTokens": 500,
}


@pytest.fixture(autouse=True)
def _isolated_registry():
    reset_registry_for_tests()
    register_or_resolve(build_challenge_cup_workflow_definition())
    yield
    reset_registry_for_tests()


# --------------------------------------------------------------------------
# Pure parser: fail-closed dead-turn proof
# --------------------------------------------------------------------------


def test_dead_turn_parser_accepts_only_failure_terminal_turn_problems() -> None:
    assert dead_agent_turn_block_problem(json.dumps(_DEAD_TURN_PROBLEM)) is not None
    failed = dict(_DEAD_TURN_PROBLEM, terminalStatus="failed")
    assert dead_agent_turn_block_problem(json.dumps(failed)) is not None


@pytest.mark.parametrize(
    "problem",
    [
        # 其他 blocked 原因（预算）一律不动。
        _BUDGET_PROBLEM,
        # code 对但 turn 仍非终态（可能复活）→ 不算死 turn。
        dict(_DEAD_TURN_PROBLEM, terminalStatus="running"),
        dict(_DEAD_TURN_PROBLEM, terminalStatus=""),
        # 完全不同的 blocked 形状。
        {"code": "auto_advance_not_ready", "detail": "knowledge_package_not_materialized"},
    ],
)
def test_dead_turn_parser_rejects_other_blocked_shapes(problem: dict) -> None:
    assert dead_agent_turn_block_problem(json.dumps(problem)) is None


@pytest.mark.parametrize("raw", ["", None, "not-json", "[1,2]"])
def test_dead_turn_parser_rejects_malformed_payloads(raw: str | None) -> None:
    assert dead_agent_turn_block_problem(raw) is None


# --------------------------------------------------------------------------
# record_knowledge_sideflow_child_failure: failed_dead_turn outcome
# --------------------------------------------------------------------------


def _seed_sideflow_family(
    store,
    *,
    run_id: str = "run-parent",
    child_run_id: str = "run-child",
    child_status: str = "blocked",
    child_problem: dict[str, Any] | None = None,
    invocation_status: str = "running",
):
    parent = replace(
        build_run_record(
            run_id=run_id,
            workflow_version_id=_PINNED.workflowVersionId,
            status="blocked",
            run_version=3,
            last_event_sequence=8,
        ),
        structure_hash=_PINNED.structureHash,
        active_node_id="hypothesis_design",
        blocked_problem_json=json.dumps(
            {
                "code": "auto_advance_not_ready",
                "detail": "knowledge_package_not_materialized",
            },
            ensure_ascii=False,
        ),
    )
    child = replace(
        build_run_record(
            run_id=child_run_id,
            workflow_version_id=_PINNED.workflowVersionId,
            status=child_status,
            run_version=2,
            last_event_sequence=4,
            parent_run_id=run_id,
        ),
        structure_hash=_PINNED.structureHash,
        workflow_id=KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
        active_node_id="evidence_relations",
        blocked_problem_json=(
            json.dumps(child_problem, ensure_ascii=False)
            if child_problem is not None
            else None
        ),
    )
    invocation = KnowledgeInvocationRecord(
        invocation_id=f"ki-{child_run_id}",
        parent_run_id=run_id,
        parent_node_id="hypothesis_design",
        parent_node_run_id=f"nr-{run_id}-hypothesis_design-a1",
        parent_attempt=1,
        question_id="SCI-096",
        scope_hash="scope",
        request_hash=f"req-{child_run_id}",
        search_envelope_hash="env",
        requirements_hash="req-hash",
        source_policy_version="2",
        knowledge_child_run_id=child_run_id,
        status=invocation_status,
        knowledge_package_ref=None,
        package_content_hash=None,
        handoff_state="pending",
        error_json=None,
        created_at_ms=FIXED_NOW_MS - 1_000,
        updated_at_ms=FIXED_NOW_MS,
    )

    def seed(uow):
        uow.repository.insert_run(parent)
        uow.repository.insert_command(
            build_command_record(
                command_id=f"cmd-{run_id}",
                run_id=run_id,
                idempotency_key=f"key:{run_id}",
                node_id="hypothesis_design",
            )
        )
        uow.repository.insert_run(child)
        uow.repository.insert_command(
            build_command_record(
                command_id=f"cmd-{child_run_id}",
                run_id=child_run_id,
                idempotency_key=f"key:{child_run_id}",
                node_id="knowledge_ingestion",
            )
        )
        uow.repository.insert_knowledge_invocation(invocation)

    store.submit(seed, force_flush=True).result(timeout=10)
    return parent, child, invocation


def _build_command_service(store) -> WorkflowCommandService:
    def run_source(run_id: str) -> RunSnapshot | None:
        record = store.get_run(run_id)
        if record is None:
            return None
        return RunSnapshot(
            run_id=record.run_id,
            team_id=record.team_id,
            workflow_id=record.workflow_id,
            workflow_version_id=record.workflow_version_id,
            project_id=record.project_id,
            question_id=record.question_id,
            status=record.status,
            run_version=record.run_version,
            input_snapshot_hash=record.input_snapshot_hash,
        )

    def attempt_count_source(run_id: str, node_id: str) -> int:
        latest = store.latest_attempt(run_id, node_id)
        return 1 if latest is not None and latest.status in (
            "starting", "dispatching", "running", "waiting_human",
        ) else 0

    return WorkflowCommandService(
        store=store,
        readiness_service=NodeReadinessService(
            run_source=run_source,
            attempt_count_source=attempt_count_source,
        ),
        readiness_context=lambda: FakeDomainContext(),
        clock=lambda: FIXED_NOW_MS + 1000,
        wake_worker=lambda: None,
    )


def _invocation_row(store, invocation_id: str):
    return store.read(
        lambda repo: repo.get_knowledge_invocation(invocation_id)
    )


def _submit_reconcile(store, service: WorkflowCommandService, run_id: str) -> None:
    run = store.get_run(run_id)
    from core.research.workflow.contracts import ActorRef, CommandRequest
    from core.web.services.team_workflow.research_runtime.operator_authorization import (
        server_operator_scope,
    )

    with server_operator_scope(
        "test:reconcile",
        display_name="Test reconcile",
        roles=("operator",),
    ):
        service.submit(
            CommandRequest(
                command_id="cmd-client-placeholder",
                run_id=run_id,
                team_id=run.team_id,
                command=WorkflowCommandKind.RECONCILE_RUN,
                node_id=None,
                expected_run_version=int(run.run_version),
                idempotency_key=f"ui:reconcile:{run_id}",
                payload={},
                # system actor：与服务端 operator 上下文不冲突（user/operator
                # body actor 必须与 server operator id 一致）。
                requested_by=ActorRef("system", "test:reconcile"),
                requested_at_ms=FIXED_NOW_MS,
            )
        )


def test_reconcile_marks_dead_turn_blocked_child_invocation_failed(
    tmp_path: Path,
) -> None:
    """父 run 对账把死 turn blocked 子 run 的 invocation 标 FAILED（含审计字段）。"""
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_sideflow_family(
            store,
            run_id="run-parent-dead",
            child_run_id="run-child-dead",
            child_status="blocked",
            child_problem=_DEAD_TURN_PROBLEM,
            invocation_status="running",
        )
        service = _build_command_service(store)
        _submit_reconcile(store, service, "run-parent-dead")

        invocation = _invocation_row(store, "ki-run-child-dead")
        assert invocation.status == "failed"
        error = json.loads(str(invocation.error_json))
        assert error["code"] == "knowledge_sideflow_child_failed_dead_turn"
        dead_turn = error["deadTurn"]
        # 原始 code/terminalStatus/sessionId/turnId 留存审计。
        assert dead_turn["code"] == "agent_turn_terminal_failed"
        assert dead_turn["terminalStatus"] == "interrupted"
        assert dead_turn["sessionId"] == "sess-dead-turn"
        assert dead_turn["turnId"] == "turn-dead-turn"
    finally:
        store.close()


@pytest.mark.parametrize(
    "child_problem",
    [
        _BUDGET_PROBLEM,
        dict(_DEAD_TURN_PROBLEM, terminalStatus="running"),
        {"code": "auto_advance_not_ready", "detail": "knowledge_package_not_materialized"},
    ],
)
def test_reconcile_leaves_non_dead_turn_blocked_children_alive(
    tmp_path: Path, child_problem: dict
) -> None:
    """fail-closed：非死 turn 的 blocked 子 run 不动 invocation（留操作员修复）。"""
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_sideflow_family(
            store,
            run_id="run-parent-alive",
            child_run_id="run-child-alive",
            child_status="blocked",
            child_problem=child_problem,
            invocation_status="running",
        )
        service = _build_command_service(store)
        _submit_reconcile(store, service, "run-parent-alive")

        invocation = _invocation_row(store, "ki-run-child-alive")
        assert invocation.status == "running"
        assert invocation.error_json is None
    finally:
        store.close()


def test_record_failure_rejects_unknown_outcome(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_sideflow_family(store, run_id="run-parent-x", child_run_id="run-child-x")
        now = FIXED_NOW_MS + 5_000
        rejected = store.submit(
            lambda uow: record_knowledge_sideflow_child_failure(
                uow, run_id="run-child-x", outcome="blocked", now_ms=now,
            ),
            force_flush=True,
        ).result(timeout=10)
        assert rejected is None
        # blocked 故意非终态：invocation 保持 live。
        assert _invocation_row(store, "ki-run-child-x").status == "running"
    finally:
        store.close()


# --------------------------------------------------------------------------
# Maintenance sweep: restart self-healing + budgeted auto re-ensure
# --------------------------------------------------------------------------


def _seed_problem_artifact(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_id: str) -> None:
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "config.settings.get_config",
        lambda: SimpleNamespace(
            research=SimpleNamespace(knowledge_sideflow=SimpleNamespace(mode="on"))
        ),
    )
    workflow_artifact_store.put_workflow_artifact(
        "research-team",
        kind="problem_understanding",
        workflow_run_id=run_id,
        source_collection_run_id=f"source-{run_id}",
        artifact_identity=f"nr-{run_id}-problem_understanding-a1",
        payload={
            "scope": "Evaluate predictive coding for redundant spike reduction.",
            "subquestions": ["Which redundancy metrics change?"],
            "assumptions": ["Comparable encoding budget"],
            "known_unknowns": ["Energy benefit under sparse workloads"],
            "human_gate": {
                "required": True,
                "decision": "approved",
                "rationale": "Scope is testable.",
            },
        },
    )


def _build_runtime(tmp_path: Path):
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        build_workflow_runtime,
    )

    return build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "checkpoints.sqlite3",
    )


def _seed_blocked_parent_with_dead_turn_child(store, *, tmp_artifact_seeded: bool = True):
    """Parent blocked on missing knowledge + live invocation + dead-turn child."""
    run_id = "run-deadlock"
    child_run_id = "run-deadlock-child"
    problem = json.dumps(
        {
            "code": "auto_advance_not_ready",
            "detail": "knowledge_package_not_materialized",
        },
        ensure_ascii=False,
    )
    parent = replace(
        build_run_record(
            run_id=run_id,
            workflow_version_id=_PINNED.workflowVersionId,
            status="blocked",
            run_version=2,
            last_event_sequence=2,
        ),
        structure_hash=_PINNED.structureHash,
        active_node_id="hypothesis_design",
        blocked_problem_json=problem,
    )
    problem_attempt = replace(
        build_attempt_record(
            node_run_id=f"nr-{run_id}-problem_understanding-a1",
            run_id=run_id,
            node_id="problem_understanding",
            status="succeeded",
            command_id="cmd-problem",
        ),
        finished_at_ms=FIXED_NOW_MS + 1000,
    )
    hypothesis_attempt = build_attempt_record(
        node_run_id=f"nr-{run_id}-hypothesis_design-a1",
        run_id=run_id,
        node_id="hypothesis_design",
        status="blocked",
        command_id="cmd-hypothesis",
        problem_json=problem,
    )
    child = replace(
        build_run_record(
            run_id=child_run_id,
            workflow_version_id=_PINNED.workflowVersionId,
            status="blocked",
            run_version=2,
            last_event_sequence=4,
            parent_run_id=run_id,
        ),
        structure_hash=_PINNED.structureHash,
        workflow_id=KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
        active_node_id="evidence_relations",
        blocked_problem_json=json.dumps(_DEAD_TURN_PROBLEM, ensure_ascii=False),
    )
    invocation = KnowledgeInvocationRecord(
        invocation_id="ki-deadlock",
        parent_run_id=run_id,
        parent_node_id="hypothesis_design",
        parent_node_run_id=f"nr-{run_id}-hypothesis_design-a1",
        parent_attempt=1,
        question_id="SCI-096",
        scope_hash="scope",
        request_hash="req-deadlock",
        search_envelope_hash="env",
        requirements_hash="req-hash",
        source_policy_version="2",
        knowledge_child_run_id=child_run_id,
        status="running",
        knowledge_package_ref=None,
        package_content_hash=None,
        handoff_state="pending",
        error_json=None,
        created_at_ms=FIXED_NOW_MS - 1_000,
        updated_at_ms=FIXED_NOW_MS,
    )

    def seed(uow):
        uow.repository.insert_run(parent)
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-problem",
                run_id=run_id,
                idempotency_key="deadlock:problem",
                node_id="problem_understanding",
            )
        )
        uow.repository.insert_attempt(problem_attempt)
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-hypothesis",
                run_id=run_id,
                idempotency_key="deadlock:hypothesis",
                node_id="hypothesis_design",
            )
        )
        uow.repository.insert_attempt(hypothesis_attempt)
        uow.repository.insert_run(child)
        uow.repository.insert_command(
            build_command_record(
                command_id=f"cmd-{child_run_id}",
                run_id=child_run_id,
                idempotency_key=f"key:{child_run_id}",
                node_id="evidence_relations",
            )
        )
        uow.repository.insert_knowledge_invocation(invocation)

    store.submit(seed, force_flush=True).result(timeout=10)
    return run_id


def test_maintenance_sweep_clears_dead_turn_deadlock_and_reensures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重启后无需人工点击：sweep 先对账清死 turn，再在预算内自动重新发起。"""
    _seed_problem_artifact(monkeypatch, tmp_path, "run-deadlock")
    runtime = _build_runtime(tmp_path)
    try:
        run_id = _seed_blocked_parent_with_dead_turn_child(runtime.store)

        runtime.run_maintenance_once(limit=4)

        invocations = runtime.store.read(
            lambda repo: repo.list_knowledge_invocations_for_parent(run_id)
        )
        by_id = {item.invocation_id: item for item in invocations}
        # A：原 invocation 被对账标 FAILED（dead turn 审计留存）。
        original = by_id["ki-deadlock"]
        assert original.status == "failed"
        error = json.loads(str(original.error_json))
        assert error["code"] == "knowledge_sideflow_child_failed_dead_turn"
        assert error["deadTurn"]["terminalStatus"] == "interrupted"
        # B：预算内自动重新发起 → 全新 invocation（新 request_hash）。
        retries = [
            item for item in invocations if item.invocation_id != "ki-deadlock"
        ]
        assert len(retries) == 1
        retry = retries[0]
        assert retry.request_hash != original.request_hash
        assert retry.status in {"pending", "child_created", "running"}
        retry_child = runtime.store.get_run(retry.knowledge_child_run_id or "")
        assert retry_child is not None
        assert retry_child.workflow_id == KNOWLEDGE_SIDEFLOW_WORKFLOW_ID

        # 幂等：第二遍 sweep 不产生第三次请求。
        runtime.run_maintenance_once(limit=4)
        invocations_after = runtime.store.read(
            lambda repo: repo.list_knowledge_invocations_for_parent(run_id)
        )
        assert len(invocations_after) == 2
    finally:
        runtime.close()


def test_maintenance_sweep_declines_when_retry_budget_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """预算耗尽（失败请求数超过 DEFAULT_STAGE_BUDGET_MAX_RETRIES）时不动作。"""
    _seed_problem_artifact(monkeypatch, tmp_path, "run-exhausted")
    runtime = _build_runtime(tmp_path)
    try:
        run_id = "run-exhausted"
        problem = json.dumps(
            {
                "code": "auto_advance_not_ready",
                "detail": "knowledge_package_not_materialized",
            },
            ensure_ascii=False,
        )
        parent = replace(
            build_run_record(
                run_id=run_id,
                workflow_version_id=_PINNED.workflowVersionId,
                status="blocked",
                run_version=2,
                last_event_sequence=2,
            ),
            structure_hash=_PINNED.structureHash,
            active_node_id="hypothesis_design",
            blocked_problem_json=problem,
        )
        problem_attempt = replace(
            build_attempt_record(
                node_run_id=f"nr-{run_id}-problem_understanding-a1",
                run_id=run_id,
                node_id="problem_understanding",
                status="succeeded",
                command_id="cmd-problem",
            ),
            finished_at_ms=FIXED_NOW_MS + 1000,
        )

        def seed(uow):
            uow.repository.insert_run(parent)
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-problem",
                    run_id=run_id,
                    idempotency_key="exhausted:problem",
                    node_id="problem_understanding",
                )
            )
            uow.repository.insert_attempt(problem_attempt)

        runtime.store.submit(seed, force_flush=True).result(timeout=10)
        # 已有 max+1 个失败请求（原请求 + 预算内重试都已失败）。
        for index in range(DEFAULT_STAGE_BUDGET_MAX_RETRIES + 1):
            runtime.store.submit(
                lambda uow, index=index: uow.repository.insert_knowledge_invocation(
                    KnowledgeInvocationRecord(
                        invocation_id=f"ki-exhausted-{index}",
                        parent_run_id=run_id,
                        parent_node_id="hypothesis_design",
                        parent_node_run_id=f"nr-{run_id}-hypothesis_design-a1",
                        parent_attempt=1,
                        question_id="SCI-096",
                        scope_hash="scope",
                        request_hash=f"req-exhausted-{index}",
                        search_envelope_hash="env",
                        requirements_hash=f"req-hash-{index}",
                        source_policy_version="2",
                        knowledge_child_run_id=None,
                        status="failed",
                        knowledge_package_ref=None,
                        package_content_hash=None,
                        handoff_state="pending",
                        error_json=None,
                        created_at_ms=FIXED_NOW_MS - 10_000 + index,
                        updated_at_ms=FIXED_NOW_MS - 10_000 + index,
                    )
                ),
                force_flush=True,
            ).result(timeout=10)

        runtime.run_maintenance_once(limit=4)

        invocations = runtime.store.read(
            lambda repo: repo.list_knowledge_invocations_for_parent(run_id)
        )
        assert len(invocations) == DEFAULT_STAGE_BUDGET_MAX_RETRIES + 1
        assert all(item.status == "failed" for item in invocations)
    finally:
        runtime.close()


def test_maintenance_sweep_keeps_budget_block_children_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """预算阻塞（非死 turn）的子 run：sweep 不提交对账、不标 FAILED。"""
    _seed_problem_artifact(monkeypatch, tmp_path, "run-budget-block")
    runtime = _build_runtime(tmp_path)
    try:
        run_id = "run-budget-block"
        child_run_id = "run-budget-block-child"
        _seed_sideflow_family(
            runtime.store,
            run_id=run_id,
            child_run_id=child_run_id,
            child_status="blocked",
            child_problem=_BUDGET_PROBLEM,
            invocation_status="running",
        )
        # 父 run 的 blocked 原因换成非 missing-knowledge：B pass 不 eligible。
        runtime.store.submit(
            lambda uow: uow.repository.update_run_status(
                run_id,
                "research-team",
                "blocked",
                FIXED_NOW_MS + 100,
                active_node_id="hypothesis_design",
                blocked_problem_json=json.dumps(
                    {"code": "budget_precheck_insufficient", "detail": "stage budget"},
                    ensure_ascii=False,
                ),
            ),
            force_flush=True,
        ).result(timeout=10)

        runtime.run_maintenance_once(limit=4)

        invocation = _invocation_row(runtime.store, f"ki-{child_run_id}")
        assert invocation.status == "running"
        assert invocation.error_json is None
        invocations = runtime.store.read(
            lambda repo: repo.list_knowledge_invocations_for_parent(run_id)
        )
        assert len(invocations) == 1
    finally:
        runtime.close()
