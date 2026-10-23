"""Automated dead-turn redrive: sweep-driven retry_node for dead agent turns.

The repeated production incident (parallel merge → workbench rebuild+refresh
kills the backend mid-turn): the conversation layer mislabels every killed
turn ``stopped``/``stopped_by_user``, the blocked formal run parks forever on
the canonical ``agent_turn_terminal_failed`` problem, and nothing redrives
it.  The new sweep step (step two-seven, between the budget recovery and the
transient ``auto_advance_not_ready`` retry):

- redrives blocked formal nodes (and knowledge sideflow children without a
  live owning invocation) whose latest attempt carries the dead-turn problem,
  through the SAME offer-gated channel as the transient auto-retry
  (``_submit_formal_v2_command`` reuses the offer's own idempotency key);
- a ``stopped`` terminal status only qualifies behind the runtime-stop
  evidence gate (journal lifecycle reason + no ``user_stops`` signal) —
  user-stopped runs are never resurrected (fail-closed);
- at most ``VIBELUTION_AUTO_DEAD_TURN_REDRIVE_MAX`` automated redrives per
  blocked node, counted from the ``recovery_records`` audit trail so the cap
  survives restarts; once spent the step declines and records WHY;
- ``VIBELUTION_AUTO_DEAD_TURN_REDRIVE=0`` disables the step entirely.

No real model, network, or research activity is involved.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from core.research.workflow.knowledge_sideflow_definition import (
    KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
)
from core.research.workflow.ledger.records import KnowledgeInvocationRecord
from core.web.services.team_workflow.research_runtime import (
    formal_read_runtime,
)
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import (
    runtime_factory,
)

from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_run_record,
    open_ledger_store,
)

_TEAM_ID = "research-team"
_QUESTION_ID = "SCI-096"


_INTERRUPTED_DEAD_TURN_PROBLEM = {
    "code": "agent_turn_terminal_failed",
    "sessionId": "sess-killed",
    "turnId": "turn-killed",
    "terminalStatus": "interrupted",
    "completionSource": "turn_journal",
    "terminalReason": "runtime_shutdown",
    "failureClass": "terminal_non_success",
}

_STOPPED_DEAD_TURN_PROBLEM = {
    "code": "agent_turn_terminal_failed",
    "sessionId": "sess-killed",
    "turnId": "turn-killed",
    "terminalStatus": "stopped",
    "completionSource": "turn_journal",
    "terminalReason": "stopped_by_user",
    "failureClass": "terminal_non_success",
}

_BUDGET_PROBLEM = {
    "code": "budget_precheck_insufficient",
    "stageId": "evidence",
    "stageLimitTokens": 1000,
    "suggestedExtensionTokens": 500,
}


def _attempt(
    run_id: str,
    node_id: str,
    attempt: int,
    status: str,
    problem: dict[str, Any] | None,
    updated_at_ms: int = 1_000,
) -> Any:
    record = build_attempt_record(
        node_run_id=f"nrun-{run_id}-{node_id}-{attempt}",
        run_id=run_id,
        node_id=node_id,
        attempt=attempt,
        status=status,
        command_id=f"cmd-{run_id}-{node_id}-{attempt}",
        problem_json=(
            json.dumps(problem, ensure_ascii=False) if problem is not None else None
        ),
        started_at_ms=updated_at_ms - 10,
    )
    return replace(record, updated_at_ms=updated_at_ms)


class _FakeQueryService:
    def __init__(self, runs_by_workflow: dict[str, list[dict[str, Any]]]) -> None:
        self._runs_by_workflow = runs_by_workflow

    def list_runs(self, *, team_id: str, workflow_id: str) -> dict[str, Any]:
        return {
            "workflowId": workflow_id,
            "runs": list(self._runs_by_workflow.get(workflow_id, [])),
        }


class _FakeRuntime:
    def __init__(self, store: Any) -> None:
        self.store = store


def _redrive_env(
    monkeypatch: pytest.MonkeyPatch,
    store: Any,
    runs_by_workflow: dict[str, list[dict[str, Any]]],
) -> None:
    monkeypatch.setattr(
        formal_read_runtime,
        "get_query_service",
        lambda: _FakeQueryService(runs_by_workflow),
    )
    monkeypatch.setattr(
        runtime_factory,
        "production_workflow_runtime",
        lambda: _FakeRuntime(store),
    )


def _blocked_formal_run(run_id: str) -> dict[str, Any]:
    return {
        "runId": run_id,
        "questionId": _QUESTION_ID,
        "status": "blocked",
        "runVersion": 7,
    }


def _seed_attempts(store: Any, attempts: list[Any]) -> None:
    """Seed run + command + attempt rows（满足 attempts 外键约束）。"""
    run_ids = {item.run_id for item in attempts}
    workflow_version_id = "wv-dead-turn-redrive"

    def seed(uow):
        for run_id in sorted(run_ids):
            uow.repository.insert_run(
                replace(
                    build_run_record(
                        run_id=run_id,
                        workflow_version_id=workflow_version_id,
                        status="blocked",
                        run_version=7,
                        last_event_sequence=2,
                        team_id=_TEAM_ID,
                    ),
                    structure_hash="structure-hash",
                )
            )
        for item in attempts:
            uow.repository.insert_command(
                build_command_record(
                    command_id=item.command_id,
                    run_id=item.run_id,
                    team_id=_TEAM_ID,
                    node_id=item.node_id,
                    idempotency_key=f"key:{item.command_id}",
                )
            )
            uow.repository.insert_attempt(item)
        return True

    store.submit(seed, force_flush=True).result(timeout=10)


def _recovery_rows(store: Any, run_id: str) -> list[dict[str, Any]]:
    rows = store.submit(
        lambda uow: uow.repository.execute(
            "SELECT recovery_id, problem_code, evidence_json, status, resolution_json "
            "FROM recovery_records WHERE run_id = ? ORDER BY created_at_ms",
            (run_id,),
        ).fetchall(),
        force_flush=True,
    ).result(timeout=10)
    return [
        {
            "recoveryId": row[0],
            "problemCode": row[1],
            "evidence": json.loads(row[2]),
            "status": row[3],
            "resolution": json.loads(row[4]) if row[4] else None,
        }
        for row in rows or []
    ]


def _seed_turn_stop_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    session_id: str = "sess-killed",
    turn_id: str = "turn-killed",
    reason: str | None,
    user_stops: bool = False,
) -> None:
    """在 tmp 根写入真实 journal/信号 fixture（与生产同一套读写 API）。"""
    from core.chat.conversation_ledger import (
        EVENT_TURN_INTERRUPTED,
        append_conversation_event,
    )
    from core.evaluation.chat_next_state_signals import (
        append_chat_next_state_signal,
    )
    from core.web.services import session_service

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    if reason is not None:
        append_conversation_event(
            tmp_path,
            session_id,
            turn_id,
            EVENT_TURN_INTERRUPTED,
            status="stopped",
            payload={"reason": reason, "summary": "本轮因工作台重启中断。"},
        )
    if user_stops:
        append_chat_next_state_signal(
            project_root=tmp_path,
            session_id=session_id,
            turn_id=turn_id,
            source="user",
            kind="user_stops",
            polarity="negative",
            mode="directive",
            related_event_code="conversation.user_stop_requested",
            summary="用户请求停止当前对话轮次。",
            record_scene=False,
        )


# ---------------------------------------------------------------------------
# (a) interrupted / failed 死回合 → offer 通道 retry_node，确定性幂等键


def test_redrive_submits_offer_gated_retry_for_interrupted_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _redrive_env(
            monkeypatch,
            store,
            {
                chain.CHALLENGE_CUP_WORKFLOW_ID: [_blocked_formal_run("run-dead")],
            },
        )
        _seed_attempts(
            store,
            [
                # 旧的暂态 block 已前移：最新 verdict 是死回合才符合资格。
                _attempt(
                    "run-dead",
                    "source_finding",
                    3,
                    "blocked",
                    {
                        "code": "auto_advance_not_ready",
                        "detail": "meeting_open",
                    },
                    updated_at_ms=1_000,
                ),
                _attempt(
                    "run-dead",
                    "source_finding",
                    4,
                    "blocked",
                    _INTERRUPTED_DEAD_TURN_PROBLEM,
                    updated_at_ms=2_000,
                ),
            ],
        )
        submitted: list[dict[str, Any]] = []
        monkeypatch.setattr(
            chain,
            "_submit_formal_v2_command",
            lambda _team_id, **kwargs: submitted.append(kwargs)
            or {"status": "accepted"},
        )

        summary = chain.auto_redrive_dead_turn_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )

        assert summary == {
            "blockedRuns": 1,
            "redriven": 1,
            "declined": 0,
            "skipped": 0,
            "ineligible": 0,
            "failed": 0,
        }
        assert len(submitted) == 1
        call = submitted[0]
        assert call["run_id"] == "run-dead"
        assert call["node_id"] == "source_finding"
        assert call["command"] == "retry_node"
        assert call["idempotency_key"] == (
            "hf2:auto-dead-turn-redrive:run-dead:source_finding:retry_node:a4"
        )
        # 审计：恰好一条 auto_redrive，actor 可与人工 retry 区分。
        records = _recovery_rows(store, "run-dead")
        assert len(records) == 1
        assert records[0]["evidence"]["action"] == "auto_redrive"
        assert records[0]["evidence"]["actor"] == (
            chain.AUTO_DEAD_TURN_REDRIVE_ACTOR_ID
        )
        assert records[0]["evidence"]["nodeId"] == "source_finding"
        assert records[0]["status"] == "resolved"
        assert chain._count_auto_dead_turn_redrives(
            store, run_id="run-dead", node_id="source_finding"
        ) == 1

        # 幂等：sweep 重跑同一 blocked 形状时复用同一幂等键（offer 键在真实
        # 通道里兜底去重），确定性 recovery_id 不产生重复审计行。
        second = chain.auto_redrive_dead_turn_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )
        assert len(submitted) == 2
        assert submitted[1]["idempotency_key"] == submitted[0]["idempotency_key"]
        assert _recovery_rows(store, "run-dead") == records
        assert second["redriven"] == 1
    finally:
        store.close()


def test_redrive_waits_when_offer_gate_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """readiness 仍挡（offer 不可用）→ 结构化 skipped，且不写审计行。"""
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _redrive_env(
            monkeypatch,
            store,
            {
                chain.CHALLENGE_CUP_WORKFLOW_ID: [_blocked_formal_run("run-dead")],
            },
        )
        _seed_attempts(
            store,
            [
                _attempt(
                    "run-dead",
                    "source_finding",
                    4,
                    "blocked",
                    _INTERRUPTED_DEAD_TURN_PROBLEM,
                    updated_at_ms=2_000,
                )
            ],
        )

        def _offer_unavailable(_team_id: str, **_kwargs: Any) -> dict[str, Any]:
            raise chain.HypothesisFirstChainError(
                "formal node retry offer is unavailable or no longer matches the node"
            )

        monkeypatch.setattr(
            chain, "_submit_formal_v2_command", _offer_unavailable
        )

        summary = chain.auto_redrive_dead_turn_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )

        assert summary["skipped"] == 1
        assert summary["redriven"] == 0
        assert summary["failed"] == 0
        # 结构化等待不是"已恢复"：不消耗 redrive 预算（下一 tick 再试）。
        assert _recovery_rows(store, "run-dead") == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# (b) 上限耗尽 → 停止并留 decline 审计（跨重启累计）


def test_redrive_declines_when_cap_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _redrive_env(
            monkeypatch,
            store,
            {
                chain.CHALLENGE_CUP_WORKFLOW_ID: [_blocked_formal_run("run-dead")],
            },
        )
        _seed_attempts(
            store,
            [
                _attempt(
                    "run-dead",
                    "source_finding",
                    4,
                    "blocked",
                    _INTERRUPTED_DEAD_TURN_PROBLEM,
                    updated_at_ms=2_000,
                )
            ],
        )
        monkeypatch.setenv(chain.AUTO_DEAD_TURN_REDRIVE_MAX_PER_NODE_ENV, "1")
        # 一次自动化 redrive 已花掉（recovery_records 跨重启累计）。
        assert chain._record_auto_dead_turn_redrive(
            store,
            run_id="run-dead",
            node_id="source_finding",
            attempt_no=4,
            action="auto_redrive",
            resolution={"terminalStatus": "interrupted"},
            now_ms=FIXED_NOW_MS,
        )
        submitted: list[dict[str, Any]] = []
        monkeypatch.setattr(
            chain,
            "_submit_formal_v2_command",
            lambda _team_id, **kwargs: submitted.append(kwargs) or {},
        )

        summary = chain.auto_redrive_dead_turn_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )

        assert summary == {
            "blockedRuns": 1,
            "redriven": 0,
            "declined": 1,
            "skipped": 0,
            "ineligible": 0,
            "failed": 0,
        }
        assert submitted == []
        records = _recovery_rows(store, "run-dead")
        declines = [r for r in records if r["evidence"].get("action") == "declined"]
        assert len(declines) == 1
        assert declines[0]["resolution"]["reason"] == "auto_redrive_cap_exhausted"
        assert declines[0]["resolution"]["autoRedrivesApplied"] == 1
        assert declines[0]["resolution"]["maxAutoRedrives"] == 1
        # 重跑不重复留 decline、不再提交。
        again = chain.auto_redrive_dead_turn_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )
        assert again["declined"] == 1
        assert submitted == []
        assert (
            [
                r
                for r in _recovery_rows(store, "run-dead")
                if r["evidence"].get("action") == "declined"
            ]
            == declines
        )
    finally:
        store.close()


# ---------------------------------------------------------------------------
# (c) stopped 死回合必须过运行时停止证据门


def _stopped_redrive_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ledger_name: str,
    reason: str | None,
    user_stops: bool = False,
) -> Any:
    """fresh ledger + stopped 死回合 attempt + 指定证据，返回 store。"""
    store = open_ledger_store(tmp_path / ledger_name)
    _redrive_env(
        monkeypatch,
        store,
        {
            chain.CHALLENGE_CUP_WORKFLOW_ID: [_blocked_formal_run("run-dead")],
        },
    )
    _seed_attempts(
        store,
        [
            _attempt(
                "run-dead",
                "source_finding",
                4,
                "blocked",
                _STOPPED_DEAD_TURN_PROBLEM,
                updated_at_ms=2_000,
            )
        ],
    )
    if reason is not None or user_stops:
        _seed_turn_stop_evidence(
            monkeypatch,
            tmp_path,
            reason=reason,
            user_stops=user_stops,
        )
    return store


@pytest.mark.parametrize(
    "reason,user_stops",
    [
        # 证据缺失：journal 里没有该回合的 interrupted 事件。
        (None, False),
        # 用户真停：interrupted 原因是操作者文案（不在运行时停止原因集合）。
        ("操作者请求停止当前轮。", False),
        # 运行时原因与 user_stops 信号并存 → 用户信号赢，fail-closed。
        ("runtime_shutdown", True),
    ],
)
def test_redrive_stopped_user_or_missing_evidence_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str | None,
    user_stops: bool,
) -> None:
    """用户真停的运行绝不能被自动复活（fail-closed）。"""
    store = _stopped_redrive_case(
        tmp_path,
        monkeypatch,
        ledger_name=f"ledger-{reason is not None}-{user_stops}.sqlite3",
        reason=reason,
        user_stops=user_stops,
    )
    try:
        submitted: list[dict[str, Any]] = []
        monkeypatch.setattr(
            chain,
            "_submit_formal_v2_command",
            lambda _team_id, **kwargs: submitted.append(kwargs) or {},
        )

        summary = chain.auto_redrive_dead_turn_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )

        assert summary == {
            "blockedRuns": 1,
            "redriven": 0,
            "declined": 0,
            "skipped": 0,
            "ineligible": 1,
            "failed": 0,
        }
        assert submitted == []
        assert _recovery_rows(store, "run-dead") == []
    finally:
        store.close()


def test_redrive_stopped_with_runtime_stop_evidence_redrives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stopped + journal runtime_shutdown 证据（重启杀）→ offer 通道 redrive。"""
    store = _stopped_redrive_case(
        tmp_path,
        monkeypatch,
        ledger_name="ledger-stopped-runtime.sqlite3",
        reason="runtime_shutdown",
    )
    try:
        submitted: list[dict[str, Any]] = []
        monkeypatch.setattr(
            chain,
            "_submit_formal_v2_command",
            lambda _team_id, **kwargs: submitted.append(kwargs)
            or {"status": "accepted"},
        )

        summary = chain.auto_redrive_dead_turn_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )

        assert summary == {
            "blockedRuns": 1,
            "redriven": 1,
            "declined": 0,
            "skipped": 0,
            "ineligible": 0,
            "failed": 0,
        }
        assert len(submitted) == 1
        assert submitted[0]["node_id"] == "source_finding"
        assert submitted[0]["command"] == "retry_node"
        records = _recovery_rows(store, "run-dead")
        assert len(records) == 1
        assert records[0]["evidence"]["action"] == "auto_redrive"
        assert records[0]["resolution"]["terminalStatus"] == "stopped"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# (d) 非 dead-turn blocked 原因 / 有 live invocation 的 knowledge 子运行不碰


def test_redrive_ignores_non_dead_turn_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _redrive_env(
            monkeypatch,
            store,
            {
                chain.CHALLENGE_CUP_WORKFLOW_ID: [_blocked_formal_run("run-budget")],
            },
        )
        _seed_attempts(
            store,
            [
                _attempt(
                    "run-budget",
                    "source_finding",
                    2,
                    "blocked",
                    _BUDGET_PROBLEM,
                    updated_at_ms=1_000,
                )
            ],
        )
        submitted: list[dict[str, Any]] = []
        monkeypatch.setattr(
            chain,
            "_submit_formal_v2_command",
            lambda _team_id, **kwargs: submitted.append(kwargs) or {},
        )

        summary = chain.auto_redrive_dead_turn_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )

        assert summary == {
            "blockedRuns": 1,
            "redriven": 0,
            "declined": 0,
            "skipped": 0,
            "ineligible": 1,
            "failed": 0,
        }
        assert submitted == []
        assert _recovery_rows(store, "run-budget") == []
    finally:
        store.close()


def test_redrive_leaves_owned_knowledge_children_to_reconcile_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """live invocation 的 knowledge 子运行归对账 pass 管：不重复 retry_node。"""
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _redrive_env(
            monkeypatch,
            store,
            {
                KNOWLEDGE_SIDEFLOW_WORKFLOW_ID: [_blocked_formal_run("run-child")],
            },
        )
        _seed_attempts(
            store,
            [
                _attempt(
                    "run-child",
                    "evidence_relations",
                    1,
                    "blocked",
                    _INTERRUPTED_DEAD_TURN_PROBLEM,
                    updated_at_ms=2_000,
                )
            ],
        )

        def seed_invocation(uow):
            # FK：parent_run_id 必须真实存在。
            uow.repository.insert_run(
                replace(
                    build_run_record(
                        run_id="run-parent",
                        workflow_version_id="wv-dead-turn-redrive",
                        status="blocked",
                        run_version=2,
                        last_event_sequence=2,
                        team_id=_TEAM_ID,
                    ),
                    structure_hash="structure-hash",
                )
            )
            uow.repository.insert_knowledge_invocation(
                KnowledgeInvocationRecord(
                    invocation_id="ki-owned",
                    parent_run_id="run-parent",
                    parent_node_id="hypothesis_design",
                    parent_node_run_id="nr-parent-hypothesis_design-a1",
                    parent_attempt=1,
                    question_id=_QUESTION_ID,
                    scope_hash="scope",
                    request_hash="req-owned",
                    search_envelope_hash="env",
                    requirements_hash="req-hash",
                    source_policy_version="2",
                    knowledge_child_run_id="run-child",
                    status="running",
                    knowledge_package_ref=None,
                    package_content_hash=None,
                    handoff_state="pending",
                    error_json=None,
                    created_at_ms=FIXED_NOW_MS - 1_000,
                    updated_at_ms=FIXED_NOW_MS,
                )
            )
            return True

        store.submit(seed_invocation, force_flush=True).result(timeout=10)
        submitted: list[dict[str, Any]] = []
        monkeypatch.setattr(
            chain,
            "_submit_formal_v2_command",
            lambda _team_id, **kwargs: submitted.append(kwargs) or {},
        )

        summary = chain.auto_redrive_dead_turn_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )

        assert summary == {
            "blockedRuns": 1,
            "redriven": 0,
            "declined": 0,
            "skipped": 0,
            "ineligible": 1,
            "failed": 0,
        }
        assert submitted == []
        assert _recovery_rows(store, "run-child") == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# (e) config gate：VIBELUTION_AUTO_DEAD_TURN_REDRIVE=0 停用整步


def test_env_gate_disables_auto_dead_turn_redrive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(chain.AUTO_DEAD_TURN_REDRIVE_ENV, "0")

    def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("disabled step must not enumerate runs")

    monkeypatch.setattr(formal_read_runtime, "get_query_service", _forbidden)

    summary = chain.auto_redrive_dead_turn_blocked_nodes(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary == {
        "blockedRuns": 0,
        "redriven": 0,
        "declined": 0,
        "skipped": 0,
        "ineligible": 0,
        "failed": 0,
    }
