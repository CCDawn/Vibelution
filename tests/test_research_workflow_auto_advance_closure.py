"""Budget-exhaustion auto-advance closure: maintenance sweep tests.

The close hook advances a chain in place, but chains can be left stuck at the
adjudication gate by an older build or a process death between closure and
advance. The serial maintenance tick therefore hosts a self-throttled sweep
(same peek + throttle discipline as the stuck-digest watchdog) that reuses the
chain's own idempotent helpers:

- an exhausted unadjudicated round gets its accepted adjudication and then the
  formal run (create + auto-start) in the same pass;
- a blocked claim gate records the rejected outcome as the formal failure
  result and creates nothing;
- the throttle guarantees at most one sweep per interval across ticks.

No real model, network, or research activity is involved.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.web.services.team_workflow import hypothesis_rounds as hrounds
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import (
    runtime_factory,
)
from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
    reset_formal_write_runtime_for_tests,
)
from core.web.services.team_workflow.research_runtime.runtime_factory import (
    build_workflow_runtime,
)

from tests._support.team_workflow.helpers import (
    _use_fake_local_research_config,
    _use_tmp_project_root,
)

_TEAM_ID = "team-sweep-closure"
_QUESTION_ID = "SCI-096"
_ROUND_ID = "hround-sweep-5"
_MEETING_ID = "meeting-sweep-5"
_CANDIDATE_ID = "hyp-sweep-a"


def _sweep_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tmp project root plus the exhausted-round read seams for the sweep."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    reset_formal_write_runtime_for_tests()
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    from core.web.services import team_service

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    round_record = {
        "roundId": _ROUND_ID,
        "question": _QUESTION_ID,
        "status": "closed",
        "roundIndex": 5,
        "metaReview": {
            "metaReviewId": "mr-sweep-5",
            "recommendationCandidateId": _CANDIDATE_ID,
            "accepted": False,
        },
        "meetingRefs": [{"kind": "meeting_round", "id": _MEETING_ID}],
        "createdAt": "2026-09-01T00:00:00Z",
    }
    monkeypatch.setattr(
        hrounds,
        "get_hypothesis_round",
        lambda _team_id, _round_id: {"round": round_record},
    )
    monkeypatch.setattr(
        chain,
        "_question_hypothesis_rounds",
        lambda _team_id, _question: [round_record]
        if str(_question).upper() == _QUESTION_ID
        else [],
    )

    def _allow(_team_id, _question_id, candidate_ids):
        return {
            candidate_id: {
                "status": "allowed",
                "reason": "",
                "claims": [],
                "blockedClaims": [],
            }
            for candidate_id in candidate_ids
        }

    monkeypatch.setattr(chain, "evaluate_claim_belief_gate", _allow)
    monkeypatch.setattr(
        chain, "_question_non_archived_formal_run_exists", lambda _t, _q: False
    )
    # The ledger lives at the production-resolved path so the sweep's
    # read-only team/question enumeration finds it.
    ledger_path = chain._storage_path(_TEAM_ID)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    chain._append_jsonl(
        ledger_path,
        {
            "recordKind": "collection_request",
            "requestId": "request-sweep-1",
            "questionId": _QUESTION_ID,
            "meetingRoundId": _MEETING_ID,
            "status": "handed_off",
            "createdAt": "2026-09-01T00:01:00Z",
        },
    )
    return ledger_path


def _adjudications(ledger_path: Path) -> list[dict[str, Any]]:
    return [
        item
        for item in chain._read_jsonl(ledger_path)
        if str(item.get("recordKind") or "") == chain.HUMAN_ADJUDICATION_KIND
    ]


def test_maintenance_tick_auto_advances_stuck_exhausted_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """存量卡链（第 5/5 轮、无裁决）被一次 maintenance tick 救活：自动裁决
    accepted + 自动创建并自动启动 formal run，全程无人工步骤。"""
    from core.web.services.team_workflow.research_runtime import run_creation

    ledger_path = _sweep_env(tmp_path, monkeypatch)
    create_calls: list[dict] = []
    monkeypatch.setattr(
        run_creation,
        "create_question_run",
        lambda *_args, **kwargs: (
            create_calls.append(kwargs) or {"runId": "run-sweep-1"}
        ),
    )
    start_calls: list[dict] = []
    monkeypatch.setattr(
        chain,
        "_auto_start_created_formal_run",
        lambda _team_id, *, run, idempotency_key: (
            start_calls.append(
                {
                    "runId": str(run.get("runId") or ""),
                    "idempotencyKey": idempotency_key,
                }
            )
            or {"status": "accepted"}
        ),
    )
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "ledger-checkpoints.sqlite",
    )
    try:
        runtime_factory.reset_auto_advance_sweep_throttle_for_tests()
        runtime.run_maintenance_once(limit=2)
    finally:
        runtime.close()
        runtime_factory.reset_auto_advance_sweep_throttle_for_tests()

    assert len(create_calls) == 1
    call = create_calls[0]
    assert call["team_id"] == _TEAM_ID
    assert call["question_id"] == _QUESTION_ID
    assert call["idempotency_key"] == f"hf2:auto-formal-run:{_QUESTION_ID}:{_ROUND_ID}"
    assert call["formal_hypothesis_round_id"] == _ROUND_ID
    assert start_calls == [
        {
            "runId": "run-sweep-1",
            "idempotencyKey": f"hf2:auto-formal-run:{_QUESTION_ID}:{_ROUND_ID}",
        }
    ]
    adjudications = _adjudications(ledger_path)
    assert len(adjudications) == 1
    assert adjudications[0]["decision"] == "accepted"
    assert adjudications[0]["decidedBy"] == "system:auto-advance:budget-exhausted"
    assert adjudications[0]["idempotencyKey"] == (
        f"hf2:auto-adjudication:{_ROUND_ID}"
    )


def test_maintenance_tick_records_rejected_outcome_when_gate_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gate-blocked stuck chain gets its rejected outcome recorded (the
    formal failure result) and no formal run is created."""
    from core.web.services.team_workflow.research_runtime import run_creation

    ledger_path = _sweep_env(tmp_path, monkeypatch)

    def _blocked(_team_id, _question_id, candidate_ids):
        return {
            candidate_id: {
                "status": "blocked",
                "reason": "claim_data_missing",
                "claims": [],
                "blockedClaims": [],
            }
            for candidate_id in candidate_ids
        }

    monkeypatch.setattr(chain, "evaluate_claim_belief_gate", _blocked)
    create_calls: list[dict] = []
    monkeypatch.setattr(
        run_creation,
        "create_question_run",
        lambda *_args, **kwargs: (
            create_calls.append(kwargs) or {"runId": "run-sweep-x"}
        ),
    )
    monkeypatch.setattr(
        chain, "_auto_start_created_formal_run", lambda *_args, **_kwargs: None
    )
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "ledger-checkpoints.sqlite",
    )
    try:
        runtime_factory.reset_auto_advance_sweep_throttle_for_tests()
        runtime.run_maintenance_once(limit=2)
    finally:
        runtime.close()
        runtime_factory.reset_auto_advance_sweep_throttle_for_tests()

    adjudications = _adjudications(ledger_path)
    assert len(adjudications) == 1
    assert adjudications[0]["decision"] == "rejected"
    assert adjudications[0]["decidedBy"] == "system:auto-advance:gate-blocked"
    assert adjudications[0]["idempotencyKey"] == (
        f"hf2:auto-adjudication-rejected:{_ROUND_ID}"
    )
    assert create_calls == []


def test_maintenance_tick_sweep_is_self_throttled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two consecutive ticks run the sweep exactly once; a throttle reset
    (the 30s cadence passing) lets the next tick sweep again."""
    _sweep_env(tmp_path, monkeypatch)
    sweep_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        chain,
        "sweep_auto_advance_closure",
        lambda: sweep_calls.append({}) or {"adjudicated": 0, "formalRuns": 0},
    )
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "ledger-checkpoints.sqlite",
    )
    try:
        runtime_factory.reset_auto_advance_sweep_throttle_for_tests()
        runtime.run_maintenance_once(limit=2)
        runtime.run_maintenance_once(limit=2)
        assert len(sweep_calls) == 1
        runtime_factory.reset_auto_advance_sweep_throttle_for_tests()
        runtime.run_maintenance_once(limit=2)
        assert len(sweep_calls) == 2
    finally:
        runtime.close()
        runtime_factory.reset_auto_advance_sweep_throttle_for_tests()


# ---------------------------------------------------------------------------
# step three: offer-gated auto-retry of formal nodes blocked on the transient
# auto_advance_not_ready readiness verdict


def _retry_attempt(
    run_id: str,
    node_id: str,
    attempt: int,
    status: str,
    problem: dict[str, Any] | None,
    updated_at_ms: int = 1_000,
) -> Any:
    from core.research.workflow.ledger.records import NodeAttemptRecord

    return NodeAttemptRecord(
        node_run_id=f"nrun-{run_id}-{node_id}-{attempt}",
        run_id=run_id,
        node_id=node_id,
        attempt=attempt,
        actor_kind="agent",
        status=status,
        command_id="cmd-seed",
        binding_snapshot_id=None,
        input_snapshot_hash="hash-seed",
        pending_action_id=None,
        execution_anchor_id=None,
        retry_of_node_run_id=None,
        problem_json=(
            json.dumps(problem, ensure_ascii=False) if problem is not None else None
        ),
        started_at_ms=updated_at_ms - 10,
        updated_at_ms=updated_at_ms,
        finished_at_ms=None,
    )


class _FakeQueryService:
    def __init__(self, runs: list[dict[str, Any]]) -> None:
        self._runs = runs

    def list_runs(self, *, team_id: str, workflow_id: str) -> dict[str, Any]:
        return {"workflowId": workflow_id, "runs": list(self._runs)}


class _FakeStore:
    def __init__(self, attempts_by_run: dict[str, list[Any]]) -> None:
        self._attempts_by_run = attempts_by_run
        self.listed_run_ids: list[str] = []

    def list_attempts(self, run_id: str) -> list[Any]:
        self.listed_run_ids.append(run_id)
        return list(self._attempts_by_run.get(run_id, []))


class _FakeRuntime:
    def __init__(self, store: _FakeStore) -> None:
        self.store = store


def _retry_env(
    monkeypatch: pytest.MonkeyPatch,
    runs: list[dict[str, Any]],
    attempts_by_run: dict[str, list[Any]],
) -> _FakeStore:
    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
    )

    monkeypatch.setattr(
        formal_read_runtime,
        "get_query_service",
        lambda: _FakeQueryService(runs),
    )
    store = _FakeStore(attempts_by_run)
    monkeypatch.setattr(
        runtime_factory,
        "production_workflow_runtime",
        lambda: _FakeRuntime(store),
    )
    return store


_TRANSIENT_PROBLEM = {
    "code": "auto_advance_not_ready",
    "detail": "hypothesis_first_meeting_open",
}


def test_auto_retry_submits_offer_gated_retry_for_transient_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """blocked on auto_advance_not_ready → retry 走人工同款 offer 通道提交。

    只命中本题的 blocked run；节点取「最新 attempt 恰为该暂态码」的最新者，
    非 blocked run（running）与其他题的 blocked run 一律不碰。
    """
    _use_tmp_project_root(tmp_path, monkeypatch)
    runs = [
        {
            "runId": "run-blocked",
            "questionId": _QUESTION_ID,
            "status": "blocked",
            "runVersion": 7,
        },
        {"runId": "run-running", "questionId": _QUESTION_ID, "status": "running"},
        {"runId": "run-other-q", "questionId": "SCI-100", "status": "blocked"},
    ]
    attempts_by_run = {
        "run-blocked": [
            _retry_attempt(
                "run-blocked",
                "source_extraction",
                3,
                "blocked",
                _TRANSIENT_PROBLEM,
                updated_at_ms=1_000,
            ),
            _retry_attempt(
                "run-blocked",
                "source_finding",
                2,
                "blocked",
                _TRANSIENT_PROBLEM,
                updated_at_ms=2_000,
            ),
        ],
    }
    _retry_env(monkeypatch, runs, attempts_by_run)
    submitted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        chain,
        "_submit_formal_v2_command",
        lambda _team_id, **kwargs: submitted.append(kwargs) or {"status": "accepted"},
    )

    summary = chain.auto_retry_blocked_formal_nodes(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert len(submitted) == 1
    call = submitted[0]
    assert call["run_id"] == "run-blocked"
    assert call["node_id"] == "source_finding"
    assert call["command"] == "retry_node"
    assert call["idempotency_key"] == "hf2:auto-retry:run-blocked:source_finding"
    assert summary == {
        "blockedRuns": 1,
        "retried": 1,
        "skipped": 0,
        "ineligible": 0,
        "failed": 0,
    }


def test_auto_retry_waits_when_offer_gate_still_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """readiness 仍挡（offer 不可用）→ 结构化 skipped，不提交任何命令。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    runs = [
        {
            "runId": "run-blocked",
            "questionId": _QUESTION_ID,
            "status": "blocked",
        }
    ]
    attempts_by_run = {
        "run-blocked": [
            _retry_attempt(
                "run-blocked",
                "source_finding",
                4,
                "blocked",
                _TRANSIENT_PROBLEM,
                updated_at_ms=3_000,
            )
        ]
    }
    _retry_env(monkeypatch, runs, attempts_by_run)
    submitted: list[dict[str, Any]] = []

    def _offer_unavailable(_team_id: str, **kwargs: Any) -> dict[str, Any]:
        submitted.append(kwargs)
        raise chain.HypothesisFirstChainError(
            "formal node retry offer is unavailable or no longer matches the node"
        )

    monkeypatch.setattr(chain, "_submit_formal_v2_command", _offer_unavailable)

    summary = chain.auto_retry_blocked_formal_nodes(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert len(submitted) == 1
    assert summary["retried"] == 0
    assert summary["skipped"] == 1
    assert summary["failed"] == 0


def test_auto_retry_never_touches_other_blocked_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """blocked 在其他 problem code（真实 readiness 缺口/人工问题）→ 不碰。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    runs = [
        {
            "runId": "run-real-gap",
            "questionId": _QUESTION_ID,
            "status": "blocked",
        }
    ]
    attempts_by_run = {
        "run-real-gap": [
            # an older transient block moved on: the latest verdict is a
            # different problem, so the run is no longer auto-retryable
            _retry_attempt(
                "run-real-gap",
                "source_finding",
                3,
                "blocked",
                _TRANSIENT_PROBLEM,
                updated_at_ms=1_000,
            ),
            _retry_attempt(
                "run-real-gap",
                "source_finding",
                4,
                "blocked",
                {"code": "required_artifact_missing", "detail": "plan.md"},
                updated_at_ms=2_000,
            ),
        ]
    }
    _retry_env(monkeypatch, runs, attempts_by_run)
    submitted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        chain,
        "_submit_formal_v2_command",
        lambda _team_id, **kwargs: submitted.append(kwargs) or {},
    )

    summary = chain.auto_retry_blocked_formal_nodes(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert submitted == []
    assert summary["blockedRuns"] == 1
    assert summary["ineligible"] == 1
    assert summary["retried"] == 0


def test_auto_retry_ignores_non_blocked_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """running/completed run 不进入处理，也不读 ledger attempts。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    runs = [
        {"runId": "run-running", "questionId": _QUESTION_ID, "status": "running"},
        {"runId": "run-done", "questionId": _QUESTION_ID, "status": "succeeded"},
    ]
    _retry_env(monkeypatch, runs, {})
    submitted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        chain,
        "_submit_formal_v2_command",
        lambda _team_id, **kwargs: submitted.append(kwargs) or {},
    )

    summary = chain.auto_retry_blocked_formal_nodes(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert submitted == []
    assert summary["blockedRuns"] == 0
    assert summary["retried"] == 0


def test_auto_retry_survives_ledger_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单 run ledger 读失败 → failed 计数 + 不外抛，best-effort 语义。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    runs = [
        {
            "runId": "run-broken",
            "questionId": _QUESTION_ID,
            "status": "blocked",
        }
    ]
    store = _retry_env(monkeypatch, runs, {})
    submitted: list[dict[str, Any]] = []

    def _boom(_run_id: str) -> list[Any]:
        raise RuntimeError("ledger read exploded")

    store.list_attempts = _boom  # type: ignore[method-assign]
    monkeypatch.setattr(
        chain,
        "_submit_formal_v2_command",
        lambda _team_id, **kwargs: submitted.append(kwargs) or {},
    )

    summary = chain.auto_retry_blocked_formal_nodes(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert submitted == []
    assert summary["failed"] == 1
    assert summary["retried"] == 0


def test_submit_formal_v2_retry_submits_with_offer_idempotency_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """对齐钉子：真实 offer 通道里 retry_node 以投影 offer 的幂等键与载荷
    提交（auto-retry 与人工 retry_formal_node 完全同一条命令路径）。"""
    from core.research.workflow.contracts import WorkflowCommandKind
    from core.research.workflow.ledger.records import RunRecord
    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    run_record = RunRecord(
        run_id="run-offer",
        team_id=_TEAM_ID,
        workflow_id="challenge-cup",
        workflow_version_id="wf-v1",
        thread_id="thread-1",
        project_id="proj-1",
        question_id=_QUESTION_ID,
        status="blocked",
        run_version=7,
        last_event_sequence=12,
        input_snapshot_json="{}",
        input_snapshot_hash="hash",
        safety_limits_json="{}",
        binding_snapshot_set_id="bs-1",
        active_node_id="source_finding",
        parent_run_id=None,
        forked_from_checkpoint_id=None,
        completion_kind=None,
        terminal_reason=None,
        blocked_problem_json=json.dumps(_TRANSIENT_PROBLEM),
        created_at_ms=1_000,
        updated_at_ms=2_000,
        completed_at_ms=None,
    )

    class _Snapshot:
        def to_dict(self) -> dict[str, Any]:
            return {
                "commandOffers": [
                    {
                        "command": "retry_node",
                        "nodeId": "source_finding",
                        "available": True,
                        "label": "重试 source_finding",
                        "reasonCode": "retry_available",
                        "idempotencyKey": (
                            "offer:run-offer:source_finding:retry_node:a5:v7"
                        ),
                        "expectedRunVersion": 7,
                        "payload": {"retryKind": "same_node"},
                    }
                ]
            }

    class _QueryService:
        def get_snapshot(self, *, team_id: str, run_id: str) -> _Snapshot:
            return _Snapshot()

    class _CommandService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        def submit(self, request: Any) -> Any:
            self.requests.append(request)

            class _Receipt:
                def to_dict(self) -> dict[str, Any]:
                    return {"status": "accepted", "commandId": "cmd-1"}

            return _Receipt()

    class _Runtime:
        def __init__(self) -> None:
            self.command_service = _CommandService()

            class _Store:
                def get_run(self, run_id: str) -> RunRecord:
                    return run_record

            self.store = _Store()

    runtime = _Runtime()
    monkeypatch.setattr(
        runtime_factory, "production_workflow_runtime", lambda: runtime
    )
    monkeypatch.setattr(
        formal_read_runtime, "get_query_service", lambda: _QueryService()
    )

    receipt = chain._submit_formal_v2_command(
        _TEAM_ID,
        run_id="run-offer",
        node_id="source_finding",
        command="retry_node",
        idempotency_key="hf2:auto-retry:run-offer:source_finding",
    )

    assert receipt == {"status": "accepted", "commandId": "cmd-1"}
    assert len(runtime.command_service.requests) == 1
    request = runtime.command_service.requests[0]
    assert request.command is WorkflowCommandKind.RETRY_NODE
    assert request.run_id == "run-offer"
    assert request.node_id == "source_finding"
    # the offer's own idempotency key wins — never a self-invented key
    assert request.idempotency_key == (
        "offer:run-offer:source_finding:retry_node:a5:v7"
    )
    assert request.payload == {"retryKind": "same_node"}
    assert request.expected_run_version == 7


def test_maintenance_sweep_retries_transient_blocked_formal_node_after_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一轮 sweep 的每题串联顺序：adjudicate → create(+start) → retry，
    且 retried 计数汇入 sweep summary（tick → sweep 的触发已由上文测试钉住）。"""
    from core.web.services.team_workflow.research_runtime import run_creation

    ledger_path = _sweep_env(tmp_path, monkeypatch)
    order: list[str] = []
    monkeypatch.setattr(
        run_creation,
        "create_question_run",
        lambda *_args, **kwargs: (
            order.append("create")
            or {"runId": "run-sweep-retry", "questionId": _QUESTION_ID}
        ),
    )
    monkeypatch.setattr(
        chain,
        "_auto_start_created_formal_run",
        lambda _team_id, *, run, idempotency_key: order.append("start") or None,
    )

    def _record_retry(team_id: str, *, question_id: str) -> dict[str, Any]:
        order.append(f"retry:{question_id}")
        return {"blockedRuns": 1, "retried": 1, "skipped": 0, "failed": 0}

    monkeypatch.setattr(chain, "auto_retry_blocked_formal_nodes", _record_retry)

    summary = chain.sweep_auto_advance_closure()

    assert order == [
        "create",
        "start",
        f"retry:{_QUESTION_ID}",
    ]
    assert summary["adjudicated"] == 1
    assert summary["formalRuns"] == 1
    assert summary["retried"] == 1
    adjudications = _adjudications(ledger_path)
    assert len(adjudications) == 1
    assert adjudications[0]["decision"] == "accepted"
