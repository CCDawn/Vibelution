"""Budget-exhaustion auto-advance closure: recovery sweep tests.

The close hook advances a chain in place, but chains can be left stuck at the
adjudication gate by an older build or a process death between closure and
advance. The serial recovery tick therefore hosts a self-throttled sweep
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
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.research.workflow.ledger.records import RunRecord
from core.web.services import team_service
from core.web.services.team_workflow import (
    hypothesis_rounds as hrounds,
)
from core.web.services.team_workflow import meeting_rounds
from core.web.services.team_workflow.research_runtime import (
    formal_lineage_heal as heal,
)
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
    monkeypatch.setattr(chain, "auto_advance_stage_one_generation", lambda *args, **kwargs: {})
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    # The sweep's approve step enumerates meeting rounds; keep that store on
    # the tmp root so the sweep never reads a real workspace.
    monkeypatch.setattr(meeting_rounds, "PROJECT_ROOT", tmp_path)
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


def test_recovery_tick_auto_advances_stuck_exhausted_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """存量卡链（第 5/5 轮、无裁决）被一次 recovery tick 救活：自动裁决
    accepted + 自动创建并自动启动 formal run，全程无人工步骤。"""
    from core.web.services.team_workflow.research_runtime import hypothesis_first_state_v2

    ledger_path = _sweep_env(tmp_path, monkeypatch)
    offer = {"kind": "command", "command": "create_formal_run", "enabled": True,
             "actionId": "create-formal-run-v2:round", "idempotencyKey": "shared-create-key",
             "payload": {"questionId": _QUESTION_ID, "hypothesisRoundId": _ROUND_ID}}
    monkeypatch.setattr(hypothesis_first_state_v2, "project_hypothesis_first_state_v2",
                        lambda *_args: {"stateVersion": "current-state", "allowedActions": [offer]})
    create_calls = []
    def execute(team, request, **kwargs):
        create_calls.append((team, request, kwargs))
        return {"result": {"runId": "run-sweep-1"}}
    monkeypatch.setattr(chain, "execute_v2_command", execute)
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "ledger-checkpoints.sqlite",
    )
    try:
        runtime_factory.reset_auto_advance_sweep_throttle_for_tests()
        runtime.run_hypothesis_recovery_once(limit=2)
    finally:
        runtime.close()
        runtime_factory.reset_auto_advance_sweep_throttle_for_tests()

    assert len(create_calls) == 1
    team, request, kwargs = create_calls[0]
    assert team == _TEAM_ID
    assert kwargs["question_id"] == _QUESTION_ID
    assert request["idempotencyKey"] == "shared-create-key"
    assert request["payload"]["hypothesisRoundId"] == _ROUND_ID
    assert request["expectedStateVersion"] == "current-state"
    adjudications = _adjudications(ledger_path)
    assert len(adjudications) == 1
    assert adjudications[0]["decision"] == "accepted"
    assert adjudications[0]["decidedBy"] == "system:auto-advance:budget-exhausted"
    assert adjudications[0]["idempotencyKey"] == (
        f"hf2:auto-adjudication:{_ROUND_ID}"
    )


def test_recovery_tick_records_rejected_outcome_when_gate_blocks(
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
        runtime.run_hypothesis_recovery_once(limit=2)
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


def test_recovery_tick_sweep_is_self_throttled(
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
        runtime.run_hypothesis_recovery_once(limit=2)
        runtime.run_hypothesis_recovery_once(limit=2)
        assert len(sweep_calls) == 1
        runtime_factory.reset_auto_advance_sweep_throttle_for_tests()
        runtime.run_hypothesis_recovery_once(limit=2)
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
    # Sequencing seam: the canonical creation command owns create + start.
    monkeypatch.setattr(chain, "auto_create_formal_run_after_convergence",
                        lambda *_args, **_kwargs: (order.extend(["create", "start"])
                            or {"status": "created", "runId": "run-sweep", "roundId": _ROUND_ID}))

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


# ---------------------------------------------------------------------------
# step zero: auto-approval of stale awaiting_approval review digests
# (the last per-round human gate of the chain, resolved through the same
# approve_meeting_digest domain implementation the approve_summary command
# reaches)


_BASE_TS = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_REVIEW_MEETING_ID = "meeting-approve-r2"


def _offset_iso(offset_seconds: float) -> str:
    return (_BASE_TS + timedelta(seconds=offset_seconds)).isoformat().replace(
        "+00:00", "Z"
    )


def _offset_ms(offset_seconds: float) -> int:
    return int((_BASE_TS + timedelta(seconds=offset_seconds)).timestamp() * 1000)


def _approve_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Tmp-isolated meeting storage; returns the captured scene events."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(meeting_rounds, "PROJECT_ROOT", tmp_path)
    # The TTL default is an operator decision: a leaked env override must not
    # change what "default" means in these tests.
    monkeypatch.delenv("VIBELUTION_AUTO_APPROVE_DIGEST_TTL_MS", raising=False)
    events: list[dict[str, Any]] = []

    def _capture(
        event_code: str,
        *,
        outcome: str,
        fields: dict[str, Any] | None = None,
        level: str = "info",
    ) -> None:
        events.append(
            {
                "code": event_code,
                "outcome": outcome,
                "fields": dict(fields or {}),
                "level": level,
            }
        )

    monkeypatch.setattr(chain, "_record_scene_event", _capture)
    return events


def _seed_meeting(record: dict[str, Any]) -> None:
    path = meeting_rounds._rounds_path(_TEAM_ID)
    path.parent.mkdir(parents=True, exist_ok=True)
    meeting_rounds._append_jsonl(path, record)


def _awaiting_review_meeting(
    meeting_id: str,
    *,
    updated_at: str,
    status: str = "awaiting_approval",
    meeting_type: str = "hypothesis_review",
    with_draft: bool = True,
    summary_draft_error: str = "",
    draft_extra: dict[str, Any] | None = None,
    question: str = _QUESTION_ID,
) -> dict[str, Any]:
    record = {
        "meetingRoundId": meeting_id,
        "question": question,
        "meetingType": meeting_type,
        "status": status,
        "startedAt": _offset_iso(0),
        "updatedAt": updated_at,
        "participants": ["agent-a"],
    }
    if with_draft:
        draft: dict[str, Any] = {
            "digestDraftId": f"draft-{meeting_id}",
            "contentHash": f"hash-{meeting_id}",
            "evidenceRequests": [
                {
                    "rationale": f"补充 {meeting_id} 的关键证据",
                    "candidateRefs": ["hyp-a"],
                    "evidenceRefs": [],
                    "searchEnvelope": {
                        "keywords": ["predictive coding"],
                        "sourceTypes": ["paper"],
                        "evidenceLevels": ["peer_reviewed"],
                    },
                    "requirements": {
                        "minEvidenceLevel": "medium",
                        "completeness": "stage-one",
                    },
                    "writebackPolicy": {},
                }
            ],
        }
        if draft_extra:
            draft.update(draft_extra)
        record["digestDraft"] = draft
    if summary_draft_error:
        record["summaryDraftError"] = summary_draft_error
    return record


def _capture_close(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace close_review_meeting with a recorder (closure itself faked)."""
    closes: list[dict[str, Any]] = []

    def _close(team_id, meeting_round_id, payload=None, **_kwargs):
        closes.append(
            {
                "teamId": team_id,
                "meetingRoundId": meeting_round_id,
                "payload": dict(payload or {}),
            }
        )
        return {"status": "created", "meetingRound": {"status": "closed"}}

    monkeypatch.setattr(chain, "close_review_meeting", _close)
    return closes


def test_auto_approve_closes_stale_review_digest_with_request_new_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超 TTL 的 awaiting_approval 评审会：批准走 approve_meeting_digest 领域
    路径，关闭决策为 request_new_evidence、decidedBy 为系统标识，并发事件。"""
    events = _approve_env(tmp_path, monkeypatch)
    _seed_meeting(
        _awaiting_review_meeting(
            _REVIEW_MEETING_ID, updated_at=_offset_iso(0)
        )
    )
    closes = _capture_close(monkeypatch)

    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        # 11 minutes after the digest landed: beyond any positive window and,
        # under the zero default, approved on this very pass regardless.
        now_ms=_offset_ms(660),
    )

    assert summary["awaitingApproval"] == 1
    assert summary["approved"] == 1
    assert summary["reused"] == 0
    assert summary["failed"] == 0
    assert len(closes) == 1
    close = closes[0]
    assert close["teamId"] == _TEAM_ID
    assert close["meetingRoundId"] == _REVIEW_MEETING_ID
    assert close["payload"]["closedBy"] == "system:auto-approve:review-digest"
    decisions = list(close["payload"]["decisions"])
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["decision"] == chain.REQUEST_EVIDENCE_DECISION
    assert decision["decidedBy"] == "system:auto-approve:review-digest"
    # candidateRefs/evidenceRefs derive from the meeting digest draft.
    assert decision["candidateRefs"] == ["hyp-a"]
    assert decision["evidenceRefs"] == [f"meeting_round:{_REVIEW_MEETING_ID}"]
    approved_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_approve_review_digest"
        and item["outcome"] == "approved"
    ]
    assert len(approved_events) == 1
    fields = approved_events[0]["fields"]
    assert fields["meetingRoundId"] == _REVIEW_MEETING_ID
    assert fields["questionId"] == _QUESTION_ID
    assert fields["ttlMs"] == chain.DEFAULT_AUTO_APPROVE_DIGEST_TTL_MS
    # deterministic rationale: carries the meeting id + TTL semantics, no clock
    assert _REVIEW_MEETING_ID in str(fields["rationale"])
    assert "ttl" in str(fields["rationale"])


def test_auto_approve_leaves_fresh_digests_alone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正 TTL 窗口之内的 awaiting_approval 会议不碰（reason=within_ttl）：
    env 恢复的人工窗口语义保留。"""
    events = _approve_env(tmp_path, monkeypatch)
    monkeypatch.setenv("VIBELUTION_AUTO_APPROVE_DIGEST_TTL_MS", "60000")
    _seed_meeting(
        _awaiting_review_meeting(_REVIEW_MEETING_ID, updated_at=_offset_iso(0))
    )
    closes = _capture_close(monkeypatch)

    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        now_ms=_offset_ms(30),  # 30 seconds old: well within the 60s window
    )

    assert closes == []
    assert summary["approved"] == 0
    assert summary["skipped"] == 1
    skipped = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_approve_review_digest"
    ]
    assert len(skipped) == 1
    assert skipped[0]["outcome"] == "skipped"
    assert skipped[0]["fields"]["reason"] == "within_ttl"


def test_auto_approve_default_ttl_zero_approves_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认 TTL=0：刚落地的 awaiting_approval 会议在同一个 sweep pass 内
    立即批准，不再等待人工窗口（旧默认 180s 已移除）。"""
    events = _approve_env(tmp_path, monkeypatch)
    monkeypatch.delenv("VIBELUTION_AUTO_APPROVE_DIGEST_TTL_MS", raising=False)
    assert chain.DEFAULT_AUTO_APPROVE_DIGEST_TTL_MS == 0
    assert chain._auto_approve_digest_ttl_ms() == 0
    _seed_meeting(
        _awaiting_review_meeting(_REVIEW_MEETING_ID, updated_at=_offset_iso(0))
    )
    closes = _capture_close(monkeypatch)

    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        # Same instant the digest landed: age 0 is already beyond TTL=0.
        now_ms=_offset_ms(0),
    )

    assert summary["awaitingApproval"] == 1
    assert summary["approved"] == 1
    assert summary["failed"] == 0
    assert len(closes) == 1
    assert closes[0]["payload"]["closedBy"] == "system:auto-approve:review-digest"
    approved = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_approve_review_digest"
        and item["outcome"] == "approved"
    ]
    assert len(approved) == 1
    assert approved[0]["fields"]["ttlMs"] == 0


def test_auto_approve_skips_already_closed_meetings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已 closed 的会议不再进入待批集合，也绝不重复批准。"""
    _approve_env(tmp_path, monkeypatch)
    _seed_meeting(
        _awaiting_review_meeting(
            _REVIEW_MEETING_ID,
            updated_at=_offset_iso(0),
            status="closed",
        )
    )
    closes = _capture_close(monkeypatch)

    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        now_ms=_offset_ms(3_600),
    )

    assert closes == []
    assert summary["awaitingApproval"] == 0
    assert summary["approved"] == 0


def test_auto_approve_covers_candidate_generation_digests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """候选生成会纳入自动批准：走与手动 approve-generation-summary 完全
    同源的 approve_meeting_digest 领域分派（real domain dispatch），closedBy
    用 generation 专属系统标识，decidedBy 随 closedBy 可追溯。过质量门的
    candgen 草稿在默认 TTL=0 下同 pass 立即批准。"""
    events = _approve_env(tmp_path, monkeypatch)
    _seed_meeting(
        _awaiting_review_meeting(
            "meeting-generation",
            updated_at=_offset_iso(0),
            meeting_type="hypothesis_candidate_generation",
            # A gate-passing candgen draft: no validation errors, at least
            # one proposed candidate.
            draft_extra={
                "proposedCandidates": [
                    {
                        "candidateId": "hyp-new",
                        "statement": "预测编码 thesis 的新候选",
                        "rationale": "来自纪要的提案",
                        "proposedBy": "agent-a",
                    }
                ]
            },
        )
    )
    generation_closes: list[dict[str, Any]] = []

    def _close_generation(team_id, meeting_round, payload=None, **_kwargs):
        generation_closes.append(
            {
                "teamId": team_id,
                "meetingRoundId": str(meeting_round.get("meetingRoundId")),
                "payload": dict(payload or {}),
            }
        )
        return {"status": "created", "meetingRound": {"status": "closed"}}

    monkeypatch.setattr(chain, "_close_generation_meeting", _close_generation)

    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        # Same instant the digest landed: under the zero default the landed
        # digest is approved on this very pass — no human window.
        now_ms=_offset_ms(0),
    )

    assert summary["awaitingApproval"] == 1
    assert summary["approved"] == 1
    assert summary["failed"] == 0
    assert len(generation_closes) == 1
    close = generation_closes[0]
    assert close["teamId"] == _TEAM_ID
    assert close["meetingRoundId"] == "meeting-generation"
    # The real approve_meeting_digest dispatched the candgen meeting with the
    # generation-specific system identity (decidedBy derives from closedBy).
    assert close["payload"]["closedBy"] == (
        chain.AUTO_APPROVE_GENERATION_DIGEST_CLOSED_BY
    )
    assert close["payload"]["closedBy"] == "system:auto-approve:generation-digest"
    approved = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_approve_review_digest"
        and item["outcome"] == "approved"
    ]
    assert len(approved) == 1
    assert approved[0]["fields"]["closedBy"] == (
        "system:auto-approve:generation-digest"
    )
    assert approved[0]["fields"]["meetingType"] == "hypothesis_candidate_generation"
    assert approved[0]["fields"]["ttlMs"] == 0
    assert "hypothesis_candidate_generation" in str(approved[0]["fields"]["rationale"])


def test_auto_approve_candgen_quality_gate_keeps_human_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """candgen 自动批准的质量门：validationErrors 非空或缺提案的草稿不过门，
    保留人工门并记 warning 提醒事件（不静默跳过、绝不自动批准）；默认
    TTL=0 下门判定发生在同一 pass，与等待窗口无关。"""
    events = _approve_env(tmp_path, monkeypatch)
    _seed_meeting(
        _awaiting_review_meeting(
            "meeting-gen-validation-errors",
            updated_at=_offset_iso(0),
            meeting_type="hypothesis_candidate_generation",
            draft_extra={
                "proposedCandidates": [
                    {"candidateId": "hyp-new", "proposedBy": "agent-a"}
                ],
                "validationErrors": [
                    {
                        "code": "missing_falsifier",
                        "message": "candidate hyp-new lacks a falsifier",
                    }
                ],
            },
        )
    )
    _seed_meeting(
        _awaiting_review_meeting(
            "meeting-gen-no-proposals",
            updated_at=_offset_iso(0),
            meeting_type="hypothesis_candidate_generation",
        )
    )
    closes = _capture_close(monkeypatch)

    def _must_not_be_called(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError(
            "approve_meeting_digest must not run for a failing quality gate"
        )

    monkeypatch.setattr(chain, "approve_meeting_digest", _must_not_be_called)

    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        now_ms=_offset_ms(0),
    )

    assert closes == []
    assert summary["awaitingApproval"] == 2
    assert summary["approved"] == 0
    assert summary["skipped"] == 2
    reminders = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_approve_review_digest"
        and item["outcome"] == "skipped"
        and item["level"] == "warning"
    ]
    assert len(reminders) == 2
    reasons = {item["fields"]["meetingRoundId"]: item["fields"] for item in reminders}
    validation_failure = reasons["meeting-gen-validation-errors"]
    no_proposals_failure = reasons["meeting-gen-no-proposals"]
    assert validation_failure["reason"] == "candgen_digest_validation_errors"
    assert validation_failure["validationErrorCount"] == 1
    assert validation_failure["proposedCandidateCount"] == 1
    assert no_proposals_failure["reason"] == "candgen_digest_no_proposals"
    assert no_proposals_failure["validationErrorCount"] == 0
    assert no_proposals_failure["proposedCandidateCount"] == 0
    for fields in (validation_failure, no_proposals_failure):
        assert "manual approval" in str(fields["reminder"])


def test_auto_approve_skips_failed_drafts_for_both_types(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两类会议的 summaryDraftError/缺纪要都是失败态：留给 stuck-digest
    恢复，绝不自动批准（领域函数一次都不该被调）。"""
    events = _approve_env(tmp_path, monkeypatch)
    _seed_meeting(
        _awaiting_review_meeting(
            "meeting-draft-error",
            updated_at=_offset_iso(0),
            summary_draft_error="digest provider exploded",
        )
    )
    _seed_meeting(
        _awaiting_review_meeting(
            "meeting-no-draft",
            updated_at=_offset_iso(0),
            with_draft=False,
        )
    )
    _seed_meeting(
        _awaiting_review_meeting(
            "meeting-gen-draft-error",
            updated_at=_offset_iso(0),
            meeting_type="hypothesis_candidate_generation",
            summary_draft_error="digest provider exploded",
        )
    )
    _seed_meeting(
        _awaiting_review_meeting(
            "meeting-gen-no-draft",
            updated_at=_offset_iso(0),
            meeting_type="hypothesis_candidate_generation",
            with_draft=False,
        )
    )
    closes = _capture_close(monkeypatch)

    def _must_not_be_called(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("approve_meeting_digest must not run for failed drafts")

    monkeypatch.setattr(chain, "approve_meeting_digest", _must_not_be_called)

    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        now_ms=_offset_ms(3_600),
    )

    assert closes == []
    assert summary["approved"] == 0
    assert summary["failed"] == 0
    assert summary["awaitingApproval"] == 4  # both types, all four meetings
    reasons = {
        item["fields"]["meetingRoundId"]: item["fields"]["reason"]
        for item in events
        if item["code"] == "hypothesis_first.auto_approve_review_digest"
    }
    assert reasons["meeting-draft-error"] == "summary_draft_error"
    assert reasons["meeting-no-draft"] == "digest_missing"
    assert reasons["meeting-gen-draft-error"] == "summary_draft_error"
    assert reasons["meeting-gen-no-draft"] == "digest_missing"


def test_auto_approve_isolates_rejections_and_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """领域拒绝（状态已变/纪要再生）计 skipped，其他异常计 failed，均不外抛。"""
    events = _approve_env(tmp_path, monkeypatch)
    _seed_meeting(
        _awaiting_review_meeting("meeting-reject", updated_at=_offset_iso(0))
    )
    _seed_meeting(
        _awaiting_review_meeting("meeting-boom", updated_at=_offset_iso(0))
    )

    def _rejected(_team_id, _meeting_round_id, **_kwargs):
        raise chain.HypothesisFirstChainError(
            "approve-digest requires a meeting in awaiting_approval"
        )

    def _exploded(_team_id, _meeting_round_id, **_kwargs):
        raise RuntimeError("storage exploded")

    outcomes = {
        "meeting-reject": _rejected,
        "meeting-boom": _exploded,
    }
    monkeypatch.setattr(
        chain,
        "approve_meeting_digest",
        lambda team_id, meeting_round_id, **kwargs: outcomes[meeting_round_id](
            team_id, meeting_round_id, **kwargs
        ),
    )

    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        now_ms=_offset_ms(3_600),
    )

    assert summary["approved"] == 0
    assert summary["skipped"] == 1
    assert summary["failed"] == 1
    outcomes_by_id = {
        item["fields"]["meetingRoundId"]: item
        for item in events
        if item["code"] == "hypothesis_first.auto_approve_review_digest"
    }
    assert outcomes_by_id["meeting-reject"]["outcome"] == "skipped"
    assert outcomes_by_id["meeting-boom"]["outcome"] == "failed"
    assert outcomes_by_id["meeting-boom"]["level"] == "warning"


def test_auto_approve_reports_replayed_closure_as_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """closure 幂等重放（status=reused）单独计数并上报 reused 事件。"""
    events = _approve_env(tmp_path, monkeypatch)
    _seed_meeting(
        _awaiting_review_meeting(_REVIEW_MEETING_ID, updated_at=_offset_iso(0))
    )

    def _replayed(_team_id, _meeting_round_id, **_kwargs):
        return {"status": "reused", "meetingRound": {"status": "closed"}}

    monkeypatch.setattr(chain, "approve_meeting_digest", _replayed)

    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        now_ms=_offset_ms(3_600),
    )

    assert summary["reused"] == 1
    assert summary["approved"] == 0
    reused = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_approve_review_digest"
        and item["outcome"] == "reused"
    ]
    assert len(reused) == 1


def test_auto_approve_ttl_env_override_takes_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TTL 环境变量覆盖生效：正窗口低于 60s 钳到下限；显式 0 合法（无人工
    窗口）；负数/垃圾值兜底回默认值（也是 0）。"""
    _approve_env(tmp_path, monkeypatch)
    _seed_meeting(
        _awaiting_review_meeting(_REVIEW_MEETING_ID, updated_at=_offset_iso(0))
    )
    closes = _capture_close(monkeypatch)

    # 90 seconds old: beyond a 60s TTL, within the 10min default.
    monkeypatch.setenv("VIBELUTION_AUTO_APPROVE_DIGEST_TTL_MS", "60000")
    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        now_ms=_offset_ms(90),
    )
    assert len(closes) == 1
    assert summary["approved"] == 1

    # Below the 60s floor the override clamps: a 30s-old digest stays put.
    monkeypatch.setenv("VIBELUTION_AUTO_APPROVE_DIGEST_TTL_MS", "5000")
    assert chain._auto_approve_digest_ttl_ms() == 60_000
    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        now_ms=_offset_ms(30),
    )
    assert len(closes) == 1
    assert summary["approved"] == 0
    assert summary["skipped"] == 1

    # An explicit "0" is the legal no-human-window value.
    monkeypatch.setenv("VIBELUTION_AUTO_APPROVE_DIGEST_TTL_MS", "0")
    assert chain._auto_approve_digest_ttl_ms() == 0

    # A negative override is not a window: falls back to the default.
    monkeypatch.setenv("VIBELUTION_AUTO_APPROVE_DIGEST_TTL_MS", "-1")
    assert chain._auto_approve_digest_ttl_ms() == (
        chain.DEFAULT_AUTO_APPROVE_DIGEST_TTL_MS
    )
    assert chain.DEFAULT_AUTO_APPROVE_DIGEST_TTL_MS == 0

    # A garbage override falls back to the default TTL.
    monkeypatch.setenv("VIBELUTION_AUTO_APPROVE_DIGEST_TTL_MS", "not-a-number")
    assert chain._auto_approve_digest_ttl_ms() == (
        chain.DEFAULT_AUTO_APPROVE_DIGEST_TTL_MS
    )


def test_maintenance_sweep_approves_stale_digests_before_adjudicating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sweep 每题顺序：先 approve（消化 awaiting_approval）→ 缺 round 补生成 →
    adjudicate → create(+start) → retry，approved 计数汇入 sweep summary。"""
    from core.web.services.team_workflow.research_runtime import run_creation

    ledger_path = _sweep_env(tmp_path, monkeypatch)
    order: list[str] = []

    def _record_approve(team_id: str, *, question_id: str, now_ms=None):
        order.append("approve")
        return {
            "awaitingApproval": 1,
            "approved": 1,
            "reused": 0,
            "skipped": 0,
            "failed": 0,
        }

    def _record_regen(team_id: str, *, question_id: str, now_ms=None):
        order.append("regen")
        return {
            "status": "skipped",
            "reason": "round_exists",
            "created": 0,
            "skipped": 1,
            "failed": 0,
        }

    def _record_retry(team_id: str, *, question_id: str):
        order.append(f"retry:{question_id}")
        return {"blockedRuns": 1, "retried": 1, "skipped": 0, "failed": 0}

    monkeypatch.setattr(
        chain, "auto_approve_awaiting_review_digests", _record_approve
    )
    monkeypatch.setattr(
        chain, "auto_regenerate_missing_hypothesis_round", _record_regen
    )
    monkeypatch.setattr(chain, "auto_retry_blocked_formal_nodes", _record_retry)
    # Sequencing seam: the canonical creation command owns create + start.
    monkeypatch.setattr(chain, "auto_create_formal_run_after_convergence",
                        lambda *_args, **_kwargs: (order.extend(["create", "start"])
                            or {"status": "created", "runId": "run-sweep", "roundId": _ROUND_ID}))

    summary = chain.sweep_auto_advance_closure()

    assert order == [
        "approve",
        "regen",
        "create",
        "start",
        f"retry:{_QUESTION_ID}",
    ]
    assert summary["approved"] == 1
    assert summary["roundsRegenerated"] == 0
    assert summary["adjudicated"] == 1
    assert summary["formalRuns"] == 1
    assert summary["retried"] == 1
    adjudications = _adjudications(ledger_path)
    assert len(adjudications) == 1
    assert adjudications[0]["decision"] == "accepted"


# ---------------------------------------------------------------------------
# step zero-five: auto-regeneration of a missing HypothesisRound (the closure
# fan-in generation died mid-close: the meeting and its closure artifacts are
# already persisted closed, but no round ever lands, so every downstream
# auto-advance gate dead-waits forever)


_REGEN_SELECTION_ID = "hsel-regen-1"
_REGEN_R1_MEETING_ID = "hf-review-hsel-regen-1-round-1"
_REGEN_R2_MEETING_A = "hf-review-hsel-regen-1-round-2-hyp-a"
_REGEN_R2_MEETING_B = "hf-review-hsel-regen-1-round-2-hyp-b"
_REGEN_CANDIDATE_A = "hyp-regen-a"
_REGEN_CANDIDATE_B = "hyp-regen-b"


def _regen_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[dict[str, Any]]:
    """Tmp-isolated chain/meeting/round stores plus captured scene events."""
    events = _approve_env(tmp_path, monkeypatch)
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    # The inflight marker is process-global: a fresh env must not inherit one.
    chain._ROUND_REGEN_INFLIGHT.clear()
    monkeypatch.delenv("VIBELUTION_AUTO_REGEN_ROUND_GRACE_MS", raising=False)
    return events


def _seed_review_link(
    meeting_id: str,
    *,
    round_index: int,
    candidate_id: str = "",
    selection_id: str = _REGEN_SELECTION_ID,
    created_at: str = "",
) -> None:
    path = chain._storage_path(_TEAM_ID)
    path.parent.mkdir(parents=True, exist_ok=True)
    chain._append_jsonl(
        path,
        {
            "schemaVersion": 1,
            "recordKind": chain.REVIEW_ROUND_LINK_KIND,
            "linkId": f"hf-link-{meeting_id}",
            "meetingRoundId": meeting_id,
            "previousMeetingRoundId": "",
            "selectionId": selection_id,
            "collectionRequestId": "request-regen-1",
            "questionId": _QUESTION_ID,
            "roundIndex": round_index,
            "roundBudget": chain.HARD_ROUND_LIMIT,
            "candidateId": candidate_id,
            "candidateOrder": None,
            "createdAt": created_at or _offset_iso(0),
        },
    )


def _seed_closed_review_meeting(
    meeting_id: str,
    *,
    closed_at: str,
    status: str = "closed",
) -> None:
    _seed_meeting(
        {
            "meetingRoundId": meeting_id,
            "question": _QUESTION_ID,
            "meetingType": "hypothesis_review",
            "status": status,
            "startedAt": _offset_iso(0),
            "updatedAt": closed_at,
            "closedAt": closed_at,
            "participants": ["agent-a"],
        }
    )


def _seed_stored_round(round_id: str, *, meeting_ids: list[str]) -> dict[str, Any]:
    """Append a stored round record straight into the round ledger."""
    record = {
        "roundId": round_id,
        "question": _QUESTION_ID,
        "status": "closed",
        "meetingRefs": [
            {"kind": "meeting_round", "id": meeting_id} for meeting_id in meeting_ids
        ],
        "createdAt": _offset_iso(0),
    }
    hrounds._append_jsonl(hrounds._storage_path(_TEAM_ID), record)
    return record


def _seed_superseded_dispatch_attempt(candidate_id: str, attempt_number: int) -> None:
    """Append one superseded review-dispatch attempt state for one identity."""
    path = chain._storage_path(_TEAM_ID)
    path.parent.mkdir(parents=True, exist_ok=True)
    chain._append_jsonl(
        path,
        {
            "schemaVersion": 1,
            "recordKind": chain.REVIEW_DISPATCH_ATTEMPT_KIND,
            "attemptId": f"attempt-{candidate_id}-{attempt_number}",
            "attemptNumber": attempt_number,
            "selectionId": _REGEN_SELECTION_ID,
            "candidateId": candidate_id,
            "roundIndex": 2,
            "lifecycle": "failed",
            "outcome": "superseded",
            "meetingRoundId": f"hf-review-dead-{attempt_number}",
            "updatedAt": _offset_iso(attempt_number),
            "createdAt": _offset_iso(attempt_number),
        },
    )


def _seed_regen_chain(
    *, second_round_status: str = "closed", closed_at: str = ""
) -> None:
    """Round-1 selection review plus a fully closed round-2 candidate pair."""
    _seed_review_link(_REGEN_R1_MEETING_ID, round_index=1)
    _seed_review_link(
        _REGEN_R2_MEETING_A,
        round_index=2,
        candidate_id=_REGEN_CANDIDATE_A,
        created_at=_offset_iso(10),
    )
    _seed_review_link(
        _REGEN_R2_MEETING_B,
        round_index=2,
        candidate_id=_REGEN_CANDIDATE_B,
        created_at=_offset_iso(10),
    )
    _seed_closed_review_meeting(_REGEN_R1_MEETING_ID, closed_at=_offset_iso(0))
    _seed_closed_review_meeting(
        _REGEN_R2_MEETING_A,
        closed_at=closed_at or _offset_iso(100),
        status=second_round_status,
    )
    _seed_closed_review_meeting(
        _REGEN_R2_MEETING_B,
        closed_at=closed_at or _offset_iso(300),
        status=second_round_status,
    )


def test_auto_regenerate_creates_missing_round_after_grace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """最新轮会议全部 closed 且过宽限期、无 round → 走 regenerate 命令路径补
    生成；触发会议取该轮最后 closed 的一个，round 真实落盘并发事件。"""
    events = _regen_env(tmp_path, monkeypatch)
    _seed_regen_chain()
    calls: list[str] = []

    def _regenerate(team_id, meeting_round_id, **_kwargs):
        calls.append(meeting_round_id)
        record = _seed_stored_round(
            "hround-regen-r2", meeting_ids=[meeting_round_id]
        )
        return {"status": "created", "round": record}

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regenerate)

    summary = chain.auto_regenerate_missing_hypothesis_round(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        # Round-2 meetings closed 300s ago (beyond the 120s grace).
        now_ms=_offset_ms(600),
    )

    assert summary["status"] == "created"
    assert summary["reason"] == "round_generated"
    assert summary["roundId"] == "hround-regen-r2"
    # The last closed round-2 meeting triggers the regeneration.
    assert calls == [_REGEN_R2_MEETING_B]
    stored_rounds = hrounds.list_hypothesis_rounds(_TEAM_ID)["rounds"]
    assert any(item["roundId"] == "hround-regen-r2" for item in stored_rounds)
    created_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_regenerate_round"
    ]
    assert created_events and created_events[-1]["outcome"] == "created"
    assert created_events[-1]["fields"]["meetingRoundId"] == _REGEN_R2_MEETING_B


def test_auto_regenerate_waits_within_grace_period(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """closed 后未过宽限期（同步 fan-in 还在跑）→ skipped within_grace，
    不触碰 regenerate。"""
    events = _regen_env(tmp_path, monkeypatch)
    _seed_regen_chain(closed_at=_offset_iso(100))
    calls: list[str] = []

    def _regenerate(team_id, meeting_round_id, **_kwargs):
        calls.append(meeting_round_id)
        return {"status": "created", "round": {}}

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regenerate)

    summary = chain.auto_regenerate_missing_hypothesis_round(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        # Newest closure 100s ago: still inside the 120s grace.
        now_ms=_offset_ms(200),
    )

    assert summary["status"] == "skipped"
    assert summary["reason"] == "within_grace"
    assert calls == []
    skipped_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_regenerate_round"
    ]
    assert skipped_events and skipped_events[-1]["outcome"] == "skipped"
    assert skipped_events[-1]["fields"]["reason"] == "within_grace"


def test_auto_regenerate_skips_when_round_already_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """当前 attempt 的完整会议组已被同一 round 覆盖 → 不重复生成。"""
    _regen_env(tmp_path, monkeypatch)
    _seed_regen_chain()
    _seed_stored_round(
        "hround-existing-r2",
        meeting_ids=[_REGEN_R2_MEETING_A, _REGEN_R2_MEETING_B],
    )
    calls: list[str] = []

    def _regenerate(team_id, meeting_round_id, **_kwargs):
        calls.append(meeting_round_id)
        return {"status": "created", "round": {}}

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regenerate)

    summary = chain.auto_regenerate_missing_hypothesis_round(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )

    assert summary["status"] == "skipped"
    assert summary["reason"] == "round_exists"
    assert calls == []


def test_auto_regenerate_does_not_treat_partial_historical_overlap_as_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧 round 只引用当前 fan-in 的一部分时，当前完整 attempt 仍需生成。"""
    _regen_env(tmp_path, monkeypatch)
    _seed_regen_chain()
    _seed_stored_round("hround-legacy-partial", meeting_ids=[_REGEN_R2_MEETING_A])
    calls: list[str] = []

    def _regenerate(team_id, meeting_round_id, **_kwargs):
        calls.append(meeting_round_id)
        record = _seed_stored_round(
            "hround-current-complete",
            meeting_ids=[_REGEN_R2_MEETING_A, _REGEN_R2_MEETING_B],
        )
        return {"status": "created", "round": record}

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regenerate)

    summary = chain.auto_regenerate_missing_hypothesis_round(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )

    assert summary["status"] == "created"
    assert summary["reason"] == "round_generated"
    assert calls == [_REGEN_R2_MEETING_B]


def test_auto_regenerate_skips_when_review_meetings_still_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """最新轮还有会议未 closed → skipped review_not_closed（fan-in 兄弟
    未齐也是同一语义，交给 regenerate 的域断言兜底）。"""
    _regen_env(tmp_path, monkeypatch)
    _seed_regen_chain(second_round_status="awaiting_approval")
    calls: list[str] = []

    def _regenerate(team_id, meeting_round_id, **_kwargs):
        calls.append(meeting_round_id)
        return {"status": "created", "round": {}}

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regenerate)

    summary = chain.auto_regenerate_missing_hypothesis_round(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )

    assert summary["status"] == "skipped"
    assert summary["reason"] == "review_not_closed"
    assert calls == []


def test_auto_regenerate_reports_failed_generation_without_raising(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生成失败（如评审 LLM 300s 超时）→ failed 不外抛、无新 round；
    下一轮再试由幂等域保证成功。"""
    events = _regen_env(tmp_path, monkeypatch)
    _seed_regen_chain()
    state = {"attempt": 0}

    def _regenerate(team_id, meeting_round_id, **_kwargs):
        state["attempt"] += 1
        if state["attempt"] == 1:
            raise RuntimeError("review LLM did not return within 300s")
        record = _seed_stored_round(
            "hround-regen-r2", meeting_ids=[meeting_round_id]
        )
        return {"status": "created", "round": record}

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regenerate)

    failed = chain.auto_regenerate_missing_hypothesis_round(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )
    assert failed["status"] == "failed"
    assert failed["reason"] == "RuntimeError"
    assert "300s" in failed["error"]
    assert hrounds.list_hypothesis_rounds(_TEAM_ID)["roundCount"] == 0
    failed_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_regenerate_round"
    ]
    assert failed_events and failed_events[-1]["outcome"] == "failed"
    assert failed_events[-1]["level"] == "warning"

    # The next sweep pass simply retries; the domain stays the idempotency
    # authority (a stored round would replay as reuse instead).
    retry = chain.auto_regenerate_missing_hypothesis_round(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )
    assert retry["status"] == "created"
    assert hrounds.list_hypothesis_rounds(_TEAM_ID)["roundCount"] == 1


def test_auto_regenerate_maps_sibling_rejection_to_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """regenerate 域拒绝（waiting_for_sibling_reviews）→ skipped，不算失败。"""
    _regen_env(tmp_path, monkeypatch)
    _seed_regen_chain()

    def _regenerate(team_id, meeting_round_id, **_kwargs):
        return {
            "status": "waiting_for_sibling_reviews",
            "selectionId": _REGEN_SELECTION_ID,
            "roundIndex": 2,
        }

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regenerate)

    summary = chain.auto_regenerate_missing_hypothesis_round(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )

    assert summary["status"] == "skipped"
    assert summary["reason"] == "waiting_for_sibling_reviews"


def test_auto_regenerate_respects_the_failure_retry_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一次 auto-advance 失败已记账后，下一 sweep 不再自动重撞同一确定性失败
    （SCI-024 式的 255 次盲重试），只保留 operator 提示。"""
    events = _regen_env(tmp_path, monkeypatch)
    _seed_regen_chain()
    hrounds.record_hypothesis_round_failure(
        _TEAM_ID,
        {
            "status": "failed",
            "failureCode": "hypothesis_round_generation_error",
            "reason": "review step did not return within 800s",
            "meetingRoundIds": [_REGEN_R2_MEETING_B],
            "selectionId": _REGEN_SELECTION_ID,
            "roundIndex": 2,
            "trigger": "auto_advance",
        },
    )
    calls: list[str] = []

    def _regenerate(team_id, meeting_round_id, **_kwargs):
        calls.append(meeting_round_id)
        return {"status": "created", "round": {}}

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regenerate)

    summary = chain.auto_regenerate_missing_hypothesis_round(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )

    assert summary["status"] == "skipped"
    assert summary["reason"] == "auto_retry_budget_exhausted"
    assert calls == []
    budget_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_regenerate_round"
        and item["fields"].get("reason") == "auto_retry_budget_exhausted"
    ]
    assert budget_events and budget_events[-1]["outcome"] == "skipped"


def test_auto_regenerate_redispatches_superseded_reviews(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """superseded digest-less 候选没有可关闭的会议：sweep 自动重派发其评审，
    而不是继续等待不可能发生的 sibling close。"""
    events = _regen_env(tmp_path, monkeypatch)
    _seed_regen_chain()
    redispatch_calls: list[tuple[str, list[str]]] = []

    def _retry(team_id, selection_id, candidate_ids):
        redispatch_calls.append((selection_id, list(candidate_ids)))
        return {"status": "opened"}

    monkeypatch.setattr(chain, "retry_review_dispatch", _retry)

    def _regenerate(team_id, meeting_round_id, **_kwargs):
        return {
            "status": "waiting_for_sibling_reviews",
            "selectionId": _REGEN_SELECTION_ID,
            "roundIndex": 2,
            "missingCandidateIds": [],
            "pendingMeetingRoundIds": [],
            "supersededCandidateIds": [_REGEN_CANDIDATE_A],
            "supersededMeetingRoundIds": ["hf-review-dead"],
        }

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regenerate)

    summary = chain.auto_regenerate_missing_hypothesis_round(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )

    assert summary["reason"] == "waiting_for_sibling_reviews"
    assert redispatch_calls == [(_REGEN_SELECTION_ID, [_REGEN_CANDIDATE_A])]
    assert summary["autoRedispatch"]["redispatched"] == 1
    redispatch_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_redispatch_superseded"
    ]
    assert redispatch_events and redispatch_events[-1]["outcome"] == "redispatched"


def test_auto_redispatch_superseded_reviews_stops_at_the_attempt_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """每个 dispatch identity 的自动重派发有上限：达到上限后保留 operator 路径。"""
    _regen_env(tmp_path, monkeypatch)
    for attempt_number in (1, 2):
        _seed_superseded_dispatch_attempt(_REGEN_CANDIDATE_A, attempt_number)
    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(
        chain,
        "retry_review_dispatch",
        lambda team_id, selection_id, candidate_ids: calls.append(
            (selection_id, list(candidate_ids))
        ),
    )

    result = chain._auto_redispatch_superseded_reviews(
        _TEAM_ID,
        selection_id=_REGEN_SELECTION_ID,
        candidate_ids=[_REGEN_CANDIDATE_A],
    )

    assert result["exhausted"] == 1
    assert result["redispatched"] == 0
    assert calls == []


def test_auto_regenerate_is_inflight_guarded_per_question(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一 (team, question) 重入（上一轮补生成还在跑）→ 内层直接 skipped
    already_in_flight；外层结束后标记释放，下一轮可再次检测。"""
    _regen_env(tmp_path, monkeypatch)
    _seed_regen_chain()
    reentrant: dict[str, Any] = {}

    def _regenerate(team_id, meeting_round_id, **_kwargs):
        # Re-enter the helper while the outer generation is still "running":
        # the inflight marker must fence the nested call for the same question.
        reentrant.update(
            chain.auto_regenerate_missing_hypothesis_round(
                team_id, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
            )
        )
        return {
            "status": "waiting_for_sibling_reviews",
            "selectionId": _REGEN_SELECTION_ID,
        }

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regenerate)

    summary = chain.auto_regenerate_missing_hypothesis_round(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )

    assert reentrant["reason"] == "already_in_flight"
    assert summary["status"] == "skipped"
    assert summary["reason"] == "waiting_for_sibling_reviews"
    # The marker is released after the outer call: a fresh pass detects again.
    followup = chain.auto_regenerate_missing_hypothesis_round(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )
    assert followup["status"] == "skipped"
    assert followup["reason"] == "waiting_for_sibling_reviews"
    assert all(
        team_id != _TEAM_ID for team_id, _question in chain._ROUND_REGEN_INFLIGHT
    )


def test_maintenance_sweep_counts_regenerated_round_in_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sweep 在 approve 之后、adjudicate 之前补缺 round；created 计数汇入
    summary.roundsRegenerated，failed 计入 summary.failed。"""
    ledger_path = _sweep_env(tmp_path, monkeypatch)

    def _record_regen(team_id: str, *, question_id: str, now_ms=None):
        return {"status": "created", "reason": "round_generated", "created": 1}

    monkeypatch.setattr(
        chain, "auto_regenerate_missing_hypothesis_round", _record_regen
    )

    def _record_adjudicate(team_id: str, *, question_id: str):
        return {"status": "skipped", "reason": "round_not_exhausted"}

    monkeypatch.setattr(
        chain, "auto_adjudicate_exhausted_round", _record_adjudicate
    )

    summary = chain.sweep_auto_advance_closure()

    assert summary["roundsRegenerated"] == 1
    assert summary["failed"] == 0
    assert _adjudications(ledger_path) == []


# ---------------------------------------------------------------------------
# step zero-six: authority backfill for closed rounds whose canonical
# dimension_reviews artifact never landed (a first-write persistence failure
# or a round generated by an older build).  The stage-one result_package
# readiness gate then blocks on the generic result_package_incomplete while
# every retry is rejected node_not_ready: the round exists, the regen step's
# round_exists guard skips it, and nothing ever re-ran the writer.


_BACKFILL_SELECTION_ID = "hsel-backfill-1"
_BACKFILL_ROUND_ID = "hround-backfill-r1"
_BACKFILL_MEETING_ID = "hf-review-hsel-backfill-1-round-1"
_BACKFILL_RUN_ID = "workflow-backfill-1"
_BACKFILL_NODE_ID = "node-backfill-1"
_BACKFILL_CANDIDATE_A = "hyp-bf-a"
_BACKFILL_CANDIDATE_B = "hyp-bf-b"
_BACKFILL_EVIDENCE_REF = (
    "evidence_card_batch://team-sweep-closure/source-1/"
    "0123456789abcdef0123456789abcdef"
)


def _backfill_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[dict[str, Any]]:
    """Regen env plus a tmp-rooted workflow artifact store for the probe."""
    from core.web.services.team_workflow.research_runtime import (
        dimension_reviews_artifact_writer,
        workflow_artifact_store,
    )

    events = _regen_env(tmp_path, monkeypatch)
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    # Evidence readback is a storage concern out of scope here; the writer
    # tests use the same seam.
    monkeypatch.setattr(
        dimension_reviews_artifact_writer,
        "read_domain_artifact",
        lambda ref: object(),
    )
    return events


def _backfill_review_rows() -> list[dict[str, Any]]:
    from core.research.competition.question_result_package import (
        REQUIRED_REVIEW_DIMENSIONS,
    )

    return [
        {
            "hypothesis_id": candidate,
            "dimension": dimension,
            "rating": "adequate",
            "rationale": f"{candidate} {dimension} rationale",
            "reviewer": "reviewer-1",
            "evidence_refs": [_BACKFILL_EVIDENCE_REF],
        }
        for candidate in (_BACKFILL_CANDIDATE_A, _BACKFILL_CANDIDATE_B)
        for dimension in REQUIRED_REVIEW_DIMENSIONS
    ]


def _seed_backfill_chain(*, round_status: str = "closed") -> None:
    """One closed round-1 review meeting plus its stored round (no authority)."""
    _seed_review_link(_BACKFILL_MEETING_ID, round_index=1)
    _seed_meeting(
        {
            "meetingRoundId": _BACKFILL_MEETING_ID,
            "question": _QUESTION_ID,
            "meetingType": "hypothesis_review",
            "status": "closed",
            "startedAt": _offset_iso(0),
            "updatedAt": _offset_iso(100),
            "closedAt": _offset_iso(100),
            "participants": ["agent-a"],
            "inputArtifactRefs": [f"hypothesis_selection:{_BACKFILL_SELECTION_ID}"],
            "discussionScope": {"workflowRunId": _BACKFILL_RUN_ID},
        }
    )
    record = {
        "roundId": _BACKFILL_ROUND_ID,
        "question": _QUESTION_ID,
        "status": round_status,
        "candidates": [
            {"candidateId": _BACKFILL_CANDIDATE_A, "claim": "claim a"},
            {"candidateId": _BACKFILL_CANDIDATE_B, "claim": "claim b"},
        ],
        "dimensionReviews": _backfill_review_rows(),
        "pareto": {
            "paretoFrontCandidateIds": [_BACKFILL_CANDIDATE_A],
            "dominatedCandidateIds": [_BACKFILL_CANDIDATE_B],
            "notes": "explicit front",
        },
        "metaReview": {
            "metaReviewId": "meta-backfill-1",
            "reviewerAgentId": "agent-coordinator",
            "recommendationCandidateId": _BACKFILL_CANDIDATE_A,
            "rationale": "收敛结论已确认。",
            "riskNotes": "",
            "accepted": True,
        },
        "meetingRefs": [{"kind": "meeting_round", "id": _BACKFILL_MEETING_ID}],
        "createdAt": _offset_iso(0),
    }
    hrounds._append_jsonl(hrounds._storage_path(_TEAM_ID), record)


def _replay_reuse_via_real_writer(team_id: str, meeting_round_id: str, **_kwargs):
    """Production-shaped reuse replay: stored round through the real writer."""
    from core.web.services.team_workflow.research_runtime import (
        dimension_reviews_artifact_writer,
    )

    stored = hrounds._latest_by_id(
        hrounds._read_jsonl(hrounds._storage_path(team_id)),
        "roundId",
        _BACKFILL_ROUND_ID,
    )
    authority = dimension_reviews_artifact_writer.materialize_dimension_reviews_authority(
        team_id=team_id,
        workflow_run_id=_BACKFILL_RUN_ID,
        node_run_id=_BACKFILL_NODE_ID,
        question_id=_QUESTION_ID,
        selection_id=_BACKFILL_SELECTION_ID,
        review_round_id=_BACKFILL_ROUND_ID,
        input_refs=[f"hypothesis_selection:{_BACKFILL_SELECTION_ID}"],
        input_snapshot_hash="a" * 64,
        candidates=[
            {"candidateId": _BACKFILL_CANDIDATE_A, "claim": "claim a"},
            {"candidateId": _BACKFILL_CANDIDATE_B, "claim": "claim b"},
        ],
        review=stored,
        workflow_authority={
            "authorityKind": "workflow_run",
            "teamId": team_id,
            "questionId": _QUESTION_ID,
            "workflowRunId": _BACKFILL_RUN_ID,
            "nodeRunId": _BACKFILL_NODE_ID,
        },
    )
    return {
        "status": "reused",
        "round": stored,
        "dimensionReviewsAuthority": authority,
    }


def _dimension_reviews_store_rows() -> list[dict[str, Any]]:
    from core.web.services.team_workflow.research_runtime import (
        workflow_artifact_store,
    )

    return workflow_artifact_store.list_workflow_artifacts(
        _TEAM_ID, kind="dimension_reviews", workflow_run_id=_BACKFILL_RUN_ID
    )


def test_auto_backfill_writes_missing_dimension_reviews_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已闭合轮次 + 权威缺失 → backfill 触发 reuse 重放，store 出现该 run 的
    dimension_reviews 记录并计入 backfilled；重放零调用由 dedup 域保证。"""
    events = _backfill_env(tmp_path, monkeypatch)
    _seed_backfill_chain()
    regen_calls: list[str] = []

    def _regen(team_id, meeting_round_id, **_kwargs):
        regen_calls.append(meeting_round_id)
        return _replay_reuse_via_real_writer(team_id, meeting_round_id)

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regen)

    summary = chain.auto_backfill_missing_round_authorities(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert regen_calls == [_BACKFILL_MEETING_ID]
    assert summary["status"] == "backfilled"
    assert summary["backfilled"] == 1
    assert summary["failed"] == 0
    rows = _dimension_reviews_store_rows()
    assert len(rows) == 1
    assert rows[0]["payload"]["reviewRoundId"] == _BACKFILL_ROUND_ID
    assert rows[0]["workflowRunId"] == _BACKFILL_RUN_ID
    assert len(rows[0]["payload"]["dimensionReviews"]) == 14
    written_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_backfill_round_authorities"
    ]
    assert written_events and written_events[-1]["outcome"] == "backfilled"


def test_auto_backfill_is_idempotent_once_authority_is_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """权威已在 → 第二次 backfill 直接 skip，不重放、store 记录不翻倍。"""
    _backfill_env(tmp_path, monkeypatch)
    _seed_backfill_chain()
    _seed_backfill_selection()
    regen_calls: list[str] = []

    def _regen(team_id, meeting_round_id, **_kwargs):
        regen_calls.append(meeting_round_id)
        return _replay_reuse_via_real_writer(team_id, meeting_round_id)

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regen)

    first = chain.auto_backfill_missing_round_authorities(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert first["status"] == "backfilled"

    second = chain.auto_backfill_missing_round_authorities(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert second["status"] == "skipped"
    assert second["backfilled"] == 0
    assert regen_calls == [_BACKFILL_MEETING_ID]
    # The exact-replay dedup in the artifact store keeps one immutable row.
    assert len(_dimension_reviews_store_rows()) == 1


def test_auto_backfill_stays_fail_closed_when_materialize_still_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重放后物化仍 blocked → failed 不伪造；store 无记录，blocker 可见。"""
    events = _backfill_env(tmp_path, monkeypatch)
    _seed_backfill_chain()
    regen_calls: list[str] = []

    def _regen(team_id, meeting_round_id, **_kwargs):
        regen_calls.append(meeting_round_id)
        stored = hrounds._latest_by_id(
            hrounds._read_jsonl(hrounds._storage_path(team_id)),
            "roundId",
            _BACKFILL_ROUND_ID,
        )
        return {
            "status": "reused",
            "round": stored,
            "dimensionReviewsAuthority": {
                "status": "blocked",
                "reason": "NEEDS_CONTEXT",
                "blockerCodes": ["dimension_reviews_authority_persistence_failed"],
                "missingAuthorities": ["dimension_reviews"],
            },
        }

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regen)

    summary = chain.auto_backfill_missing_round_authorities(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["status"] == "failed"
    assert summary["reason"] == "authority_still_blocked"
    assert summary["backfilled"] == 0
    assert summary["failed"] == 1
    assert _dimension_reviews_store_rows() == []
    failed_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_backfill_round_authorities"
    ]
    assert failed_events and failed_events[-1]["outcome"] == "failed"
    assert failed_events[-1]["level"] == "warning"
    assert (
        failed_events[-1]["fields"]["blockerCodes"]
        == ["dimension_reviews_authority_persistence_failed"]
    )


def test_auto_backfill_skips_replay_when_fan_in_group_moved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """触发会议的 fan-in 组已不等于轮次绑定会议集 → skip，不触发重放
    （不同 round id 会绕过 reuse 去重、产生真实评审预算消耗）。"""
    _backfill_env(tmp_path, monkeypatch)
    _seed_backfill_chain()
    _seed_backfill_selection()
    regen_calls: list[str] = []

    def _regen(team_id, meeting_round_id, **_kwargs):
        regen_calls.append(meeting_round_id)
        return _replay_reuse_via_real_writer(team_id, meeting_round_id)

    monkeypatch.setattr(chain, "regenerate_hypothesis_round", _regen)
    monkeypatch.setattr(
        chain,
        "_review_meeting_fan_in_group",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "selectionId": _BACKFILL_SELECTION_ID,
            "roundIndex": 2,
            "meetings": [
                {"meetingRoundId": "hf-review-other-round-2-meeting"},
            ],
        },
    )

    summary = chain.auto_backfill_missing_round_authorities(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert regen_calls == []
    assert summary["status"] == "skipped"
    assert summary["reason"] == "fan_in_group_moved"
    assert _dimension_reviews_store_rows() == []


def test_maintenance_sweep_counts_backfilled_authorities_in_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sweep 在 regen 之后调用 backfill 步骤；backfilled 计数汇入
    summary.authoritiesBackfilled，failed 计入 summary.failed。"""
    ledger_path = _sweep_env(tmp_path, monkeypatch)

    def _record_regen(team_id: str, *, question_id: str, now_ms=None):
        return {"status": "skipped", "reason": "round_exists", "created": 0}

    monkeypatch.setattr(
        chain, "auto_regenerate_missing_hypothesis_round", _record_regen
    )

    def _record_backfill(team_id: str, *, question_id: str):
        return {
            "status": "backfilled",
            "reason": "authority_backfilled",
            "backfilled": 1,
            "skipped": 0,
            "failed": 0,
        }

    monkeypatch.setattr(
        chain, "auto_backfill_missing_round_authorities", _record_backfill
    )

    def _record_adjudicate(team_id: str, *, question_id: str):
        return {"status": "skipped", "reason": "round_not_exhausted"}

    monkeypatch.setattr(
        chain, "auto_adjudicate_exhausted_round", _record_adjudicate
    )

    summary = chain.sweep_auto_advance_closure()

    assert summary["authoritiesBackfilled"] == 1
    assert summary["failed"] == 0
    assert _adjudications(ledger_path) == []


# ---------------------------------------------------------------------------
# livefix: the production replay entry.  The closed formal rounds of real runs
# carry server-owned receipt authority, so the old replay entry
# (regenerate_hypothesis_round) resolved real review runners first and the
# formal fence rejected the pure re-materialization whenever the evaluator
# configuration did not resolve — the backfill silently skipped forever (the
# scene sink is best-effort in production, so nothing was visible).  The
# backfill now replays through replay_only=True: runners are never resolved,
# the content-addressed dedup must hit, and a miss raises a structured
# ResearchHypothesisRoundReplayMissError instead of ever reaching the
# executor.


def test_auto_backfill_replays_without_resolving_review_runners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正式轮次的权威补写不再解析评审 runners：fence 即使配置缺失也无法拒绝
    replay，replay_only=True 一路传到生成入口且补写成功。"""
    _backfill_env(tmp_path, monkeypatch)
    _seed_backfill_chain()
    _seed_backfill_selection()
    # Make the meeting writer-satisfiable: the binding needs node identity and
    # the input snapshot hash from the meeting.  The ledger is append-only, so
    # the updated meeting record supersedes the seeded one for latest-reads.
    _seed_meeting(
        {
            "meetingRoundId": _BACKFILL_MEETING_ID,
            "question": _QUESTION_ID,
            "meetingType": "hypothesis_review",
            "status": "closed",
            "startedAt": _offset_iso(0),
            "updatedAt": _offset_iso(100),
            "closedAt": _offset_iso(100),
            "participants": ["agent-a"],
            "inputArtifactRefs": [f"hypothesis_selection:{_BACKFILL_SELECTION_ID}"],
            "workflowRunId": _BACKFILL_RUN_ID,
            "modelInvocationReceiptAuthority": {
                "authorityKind": "workflow_run",
                "teamId": _TEAM_ID,
                "questionId": _QUESTION_ID,
                "workflowRunId": _BACKFILL_RUN_ID,
            },
            "discussionScope": {"workflowRunId": _BACKFILL_RUN_ID},
            "nodeRunId": "node-backfill-1",
            "inputSnapshotHash": "a" * 64,
        }
    )

    def _forbidden_fence(*_args, **_kwargs):
        raise AssertionError(
            "replay backfill must never resolve review runners"
        )

    monkeypatch.setattr(chain, "_resolve_review_runners", _forbidden_fence)
    generation_calls: list[dict[str, Any]] = []

    def _fake_generation(team_id, meeting_round_id, payload=None, **kwargs):
        generation_calls.append({"replayOnly": kwargs.get("replay_only")})
        stored = hrounds._latest_by_id(
            hrounds._read_jsonl(hrounds._storage_path(team_id)),
            "roundId",
            _BACKFILL_ROUND_ID,
        )
        assert kwargs.get("replay_only") is True
        # Mirrors the real dedup hit: the stored round comes back untouched.
        return {"status": "reused", "round": stored}

    monkeypatch.setattr(
        hrounds, "generate_hypothesis_round_from_meeting", _fake_generation
    )

    summary = chain.auto_backfill_missing_round_authorities(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert generation_calls == [{"replayOnly": True}]
    assert summary["status"] == "backfilled"
    assert summary["backfilled"] == 1
    rows = _dimension_reviews_store_rows()
    assert len(rows) == 1
    assert rows[0]["payload"]["nodeRunId"] == "node-backfill-1"


def test_auto_backfill_replay_miss_skips_without_generation_or_failure_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """replay_only 未命中已存轮次 → 结构化 replay_miss skip：不写失败 trace
    （轮次账本保持只读事实）、不触发评审执行器、store 不变。"""
    _backfill_env(tmp_path, monkeypatch)
    _seed_backfill_chain()
    _seed_backfill_selection()
    events = _backfill_env_events(monkeypatch)

    def _forbidden_executor(*_args, **_kwargs):
        raise AssertionError("replay miss must never reach the review executor")

    from core.web.services.team_workflow import hypothesis_review_executor

    monkeypatch.setattr(
        hypothesis_review_executor, "execute_hypothesis_review", _forbidden_executor
    )

    def _fake_generation(team_id, meeting_round_id, payload=None, **kwargs):
        assert kwargs.get("replay_only") is True
        raise hrounds.ResearchHypothesisRoundReplayMissError(
            team_id, "hround-derived-miss"
        )

    monkeypatch.setattr(
        hrounds, "generate_hypothesis_round_from_meeting", _fake_generation
    )

    summary = chain.auto_backfill_missing_round_authorities(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["status"] == "skipped"
    assert summary["reason"] == "replay_miss"
    assert summary["backfilled"] == 0
    assert summary["failed"] == 0
    # No ghost failure trace: the stored round ledger stays untouched.
    assert hrounds.list_hypothesis_round_failures(_TEAM_ID)["failureCount"] == 0
    assert _dimension_reviews_store_rows() == []
    miss_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_backfill_round_authorities"
    ]
    assert miss_events and miss_events[-1]["outcome"] == "skipped"


def test_generate_replay_only_fails_closed_before_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """generate_hypothesis_round_from_meeting(replay_only=True) 在推导 round id
    未命中已存轮次时、于评审执行器之前抛结构化 ReplayMiss。"""
    from core.research.workflow.contracts import scope_hash_for
    from core.web.services.team_workflow import hypothesis_review_executor

    _backfill_env(tmp_path, monkeypatch)
    scope = {
        "program": "challenge",
        "theme": "theme-x",
        "campaign": "campaign-x",
        "question": _QUESTION_ID,
        "branch": "main",
        "workflow": "challenge-cup-research",
        "agentId": "agent-a",
        "mode": "dev",
    }
    scope_hash = scope_hash_for(
        **{
            key: scope[key]
            for key in ("program", "theme", "campaign", "question", "branch", "workflow")
        },
        agent_id=scope["agentId"],
        mode=scope["mode"],
    )
    _seed_meeting(
        {
            "meetingRoundId": _BACKFILL_MEETING_ID,
            "question": _QUESTION_ID,
            "meetingType": "hypothesis_review",
            "status": "closed",
            "startedAt": _offset_iso(0),
            "updatedAt": _offset_iso(100),
            "closedAt": _offset_iso(100),
            "participants": ["agent-a"],
            "closedBy": "agent-a",
            "digestId": "digest-backfill-1",
            "decisionRefs": ["decision-backfill-1"],
            **scope,
            "scopeHash": scope_hash,
        }
    )
    meeting_rounds._append_jsonl(
        meeting_rounds._digests_path(_TEAM_ID),
        {
            "digestId": "digest-backfill-1",
            "meetingRoundId": _BACKFILL_MEETING_ID,
            "sourceMessageRefs": ["chat_message:room-1:1"],
        },
    )
    meeting_rounds._append_jsonl(
        meeting_rounds._decisions_path(_TEAM_ID),
        {"decisionId": "decision-backfill-1"},
    )

    def _forbidden_executor(*_args, **_kwargs):
        raise AssertionError("replay miss must never reach the review executor")

    monkeypatch.setattr(
        hypothesis_review_executor, "execute_hypothesis_review", _forbidden_executor
    )

    with pytest.raises(
        hrounds.ResearchHypothesisRoundReplayMissError
    ) as excinfo:
        hrounds.generate_hypothesis_round_from_meeting(
            _TEAM_ID, _BACKFILL_MEETING_ID, replay_only=True
        )

    assert excinfo.value.round_id.startswith("hround-")
    # The non-replay path still owns generation; replay-only never appended a
    # round or touched the failure ledger.
    assert hrounds.list_hypothesis_rounds(_TEAM_ID)["roundCount"] == 0
    assert hrounds.list_hypothesis_round_failures(_TEAM_ID)["failureCount"] == 0


def test_auto_backfill_surfaces_blockers_for_legacy_review_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实数据形态回归（脱敏）：轮次候选行携带非 canonical 证据引用且会议/轮
    /receipt authority 均无 inputSnapshotHash 时，backfill 穿透到物化器；
    快照哈希可从真实会议/轮记录确定性复算（不再是 blocker），但行级证据
    引用无法合法 canonical 化的部分仍 fail-closed 暴露精确 blocker，store
    零写入、不伪造。"""
    events = _backfill_env(tmp_path, monkeypatch)
    _seed_review_link(_BACKFILL_MEETING_ID, round_index=1)
    _seed_backfill_selection()
    # Production shape: no nodeRunId/inputSnapshotHash anywhere on the meeting,
    # dev-mode scope with server-owned run authority, discussionScope carries
    # the run identity.
    _seed_meeting(
        {
            "meetingRoundId": _BACKFILL_MEETING_ID,
            "question": _QUESTION_ID,
            "meetingType": "hypothesis_review",
            "status": "closed",
            "startedAt": _offset_iso(0),
            "updatedAt": _offset_iso(100),
            "closedAt": _offset_iso(100),
            "participants": ["agent-a"],
            "mode": "dev",
            "inputArtifactRefs": [f"hypothesis_selection:{_BACKFILL_SELECTION_ID}"],
            "modelInvocationReceiptAuthority": {
                "authorityKind": "workflow_run",
                "teamId": _TEAM_ID,
                "questionId": _QUESTION_ID,
                "workflowRunId": _BACKFILL_RUN_ID,
            },
            "discussionScope": {"workflowRunId": _BACKFILL_RUN_ID},
        }
    )
    # Production shape: the explicit rows ride on the candidates, with raw
    # chat-candidate citation ids (non-canonical) and empty refs; no
    # dimensionReviews at the round top level, no snapshot hash anywhere.
    dimensions = ("evidence_support", "novelty", "methodology", "factual_accuracy")
    legacy_rows_a = [
        {
            "hypothesis_id": _BACKFILL_CANDIDATE_A,
            "dimension": dimension,
            "rating": "mixed",
            "reviewer": "llm:reviewer-1",
            "evidence_refs": (
                ["candidate-20260908171714-7c13f5b4"]
                if index == 0
                else []
            ),
        }
        for index, dimension in enumerate(dimensions)
    ]
    legacy_rows_b = [
        {
            "hypothesis_id": _BACKFILL_CANDIDATE_B,
            "dimension": dimension,
            "rating": "adequate",
            "reviewer": "llm:reviewer-1",
            "evidence_refs": [],
        }
        for dimension in dimensions
    ]
    hrounds._append_jsonl(
        hrounds._storage_path(_TEAM_ID),
        {
            "roundId": _BACKFILL_ROUND_ID,
            "question": _QUESTION_ID,
            "status": "closed",
            "candidates": [
                {
                    "candidateId": _BACKFILL_CANDIDATE_A,
                    "claim": "claim a",
                    "dimensionReviews": legacy_rows_a,
                },
                {
                    "candidateId": _BACKFILL_CANDIDATE_B,
                    "claim": "claim b",
                    "dimensionReviews": legacy_rows_b,
                },
            ],
            "pareto": {
                "paretoFrontCandidateIds": [_BACKFILL_CANDIDATE_A],
                "dominatedCandidateIds": [_BACKFILL_CANDIDATE_B],
            },
            "metaReview": {
                "recommendationCandidateId": _BACKFILL_CANDIDATE_A,
                "rationale": "收敛结论已确认。",
                "accepted": True,
            },
            "meetingRefs": [{"kind": "meeting_round", "id": _BACKFILL_MEETING_ID}],
        },
    )
    generation_calls: list[dict[str, Any]] = []

    def _fake_generation(team_id, meeting_round_id, payload=None, **kwargs):
        generation_calls.append({"replayOnly": kwargs.get("replay_only")})
        stored = hrounds._latest_by_id(
            hrounds._read_jsonl(hrounds._storage_path(team_id)),
            "roundId",
            _BACKFILL_ROUND_ID,
        )
        return {"status": "reused", "round": stored}

    monkeypatch.setattr(
        hrounds, "generate_hypothesis_round_from_meeting", _fake_generation
    )

    summary = chain.auto_backfill_missing_round_authorities(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert generation_calls == [{"replayOnly": True}]
    assert summary["status"] == "failed"
    assert summary["reason"] == "authority_still_blocked"
    assert summary["backfilled"] == 0
    blockers = set(summary["blockerCodes"])
    # 快照绑定已由真实记录确定性复算（可复算 = 可审计），不再是 blocker。
    assert "inputSnapshotHash_missing" not in blockers
    assert "input_snapshot_hash_invalid" not in blockers
    # 行级证据引用无法合法派生的部分保持精确 blocker。
    assert "dimension_review_evidence_ref_invalid" in blockers
    assert "dimension_review_evidence_refs_missing" in blockers
    assert _dimension_reviews_store_rows() == []
    failed_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_backfill_round_authorities"
    ]
    assert failed_events and failed_events[-1]["outcome"] == "failed"
    assert failed_events[-1]["level"] == "warning"


def _backfill_env_events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture scene events on an already-built backfill env."""
    events: list[dict[str, Any]] = []

    def _capture(code, *, outcome, fields=None, level="info"):
        events.append({"code": code, "outcome": outcome, "level": level, "fields": fields or {}})

    monkeypatch.setattr(chain, "_record_scene_event", _capture)
    return events


def _seed_backfill_selection() -> None:
    """Seed the hypothesis selection the replay's fan-in binding resolves.

    ``_generate_hypothesis_round`` looks the selection up before the round
    generation and requires its scope/question to match the trigger meeting.
    """
    from core.web.services.team_workflow import hypothesis_selection

    hypothesis_selection._append_jsonl(
        hypothesis_selection._storage_path(_TEAM_ID),
        {
            "selectionId": _BACKFILL_SELECTION_ID,
            "questionId": _QUESTION_ID,
            "scopeHash": "",
            "selectedCandidateIds": [_BACKFILL_CANDIDATE_A, _BACKFILL_CANDIDATE_B],
        },
    )


# ---------------------------------------------------------------------------
# review round link: sibling fan-out tolerance — the two sibling collection
# requests of one logical round both hand off into the same next-round
# meeting fan-out, so both race to bind the identical link; the late sibling
# must reuse the existing link instead of wedging its writeback


def _chain_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Tmp-isolated chain ledger plus captured scene events."""
    events = _approve_env(tmp_path, monkeypatch)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    return events


def _seed_review_round_link(
    meeting_round_id: str,
    *,
    collection_request_id: str,
    selection_id: str = "hsel-sibling-1",
    round_index: int = 5,
    candidate_id: str = "hyp-sib-a",
) -> dict[str, Any]:
    return chain._record_review_round_link(
        _TEAM_ID,
        meeting_round_id=meeting_round_id,
        previous_meeting_round_id="meeting-prev-1",
        selection_id=selection_id,
        collection_request_id=collection_request_id,
        question_id=_QUESTION_ID,
        round_index=round_index,
        candidate_id=candidate_id,
        candidate_order=1,
        selection_version="v7",
    )


def _links(ledger_path: Path) -> list[dict[str, Any]]:
    return [
        item
        for item in chain._read_jsonl(ledger_path)
        if str(item.get("recordKind") or "") == chain.REVIEW_ROUND_LINK_KIND
    ]


def test_review_round_link_reuses_existing_when_only_request_id_differs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一逻辑轮的两个兄弟请求交接双写同一 link：仅 collectionRequestId
    和 previousMeetingRoundId 不同 → reuse 返回首写 link，不 raise，账本
    不追加重复 link。"""
    _chain_env(tmp_path, monkeypatch)
    ledger_path = chain._storage_path(_TEAM_ID)
    first = _seed_review_round_link(
        "meeting-next-5", collection_request_id="request-sib-1"
    )

    second = chain._record_review_round_link(
        _TEAM_ID,
        meeting_round_id="meeting-next-5",
        previous_meeting_round_id="meeting-prev-2",
        selection_id="hsel-sibling-1",
        collection_request_id="request-sib-2",
        question_id=_QUESTION_ID,
        round_index=5,
        candidate_id="hyp-sib-a",
        candidate_order=1,
        selection_version="v7",
    )

    assert second == first
    assert second["collectionRequestId"] == "request-sib-1"
    assert len(_links(ledger_path)) == 1


def test_review_round_link_still_rejects_other_content_differences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """除 collectionRequestId 外任一字段不同（如 selectionId 漂移）→ 仍按
    现状 raise already bound to different content。"""
    _chain_env(tmp_path, monkeypatch)
    _seed_review_round_link("meeting-next-5", collection_request_id="request-sib-1")

    with pytest.raises(chain.HypothesisFirstChainError) as excinfo:
        chain._record_review_round_link(
            _TEAM_ID,
            meeting_round_id="meeting-next-5",
            previous_meeting_round_id="meeting-prev-1",
            selection_id="hsel-sibling-OTHER",
            collection_request_id="request-sib-2",
            question_id=_QUESTION_ID,
            round_index=5,
            candidate_id="hyp-sib-a",
            candidate_order=1,
            selection_version="v7",
        )
    assert "already bound to different content" in str(excinfo.value)


# ---------------------------------------------------------------------------
# zombie handoff retry: a collection request parked in handoff_pending by a
# once-failed writeback (its run already completed) is retried by the sweep
# past the grace — unblocking the pending count that permanently blocked
# budget-exhaustion adjudication


_ZOMBIE_REQUEST_ID = "request-zombie-1"
_ZOMBIE_RUN_ID = "crun-zombie-1"


def _seed_zombie_handoff_request(
    *,
    request_id: str = _ZOMBIE_REQUEST_ID,
    run_id: str = _ZOMBIE_RUN_ID,
    status: str = "handoff_pending",
    collection_run_status: str = "completed",
    handed_off_at: str = "",
    last_auto_retry_at: str = "",
) -> dict[str, Any]:
    record = {
        "schemaVersion": 1,
        "recordKind": chain.COLLECTION_REQUEST_KIND,
        "requestId": request_id,
        "questionId": _QUESTION_ID,
        "meetingRoundId": _MEETING_ID,
        "collectionRunId": run_id,
        "status": status,
        "collectionRunStatus": collection_run_status,
        "handoffRef": f"source_collection_run:{run_id}",
        "handoffError": {
            "code": "handoff_failed",
            "message": "review round link ... is already bound to different content",
        },
        "handedOffAt": handed_off_at or _offset_iso(0),
        "createdAt": _offset_iso(0),
    }
    if last_auto_retry_at:
        record["lastAutoRetryAt"] = last_auto_retry_at
    chain._append_jsonl(chain._storage_path(_TEAM_ID), record)
    return record


def _fake_handoff_success(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]
) -> None:
    """Replace record_collection_handoff with the domain success shape."""

    def _handoff(team_id, request_id, *, handoff_ref="", **_kwargs):
        calls.append({"requestId": request_id, "handoffRef": handoff_ref})
        updated = chain._update_collection_request(
            team_id,
            request_id,
            status="handed_off",
            handedOffAt=_offset_iso(900),
            handoffRef=handoff_ref,
            handoffError={},
        )
        return {"status": "handed_off", "request": updated}

    monkeypatch.setattr(chain, "record_collection_handoff", _handoff)


def _latest_request(request_id: str = _ZOMBIE_REQUEST_ID) -> dict[str, Any]:
    return chain._latest_by_id(
        [
            item
            for item in chain._read_jsonl(chain._storage_path(_TEAM_ID))
            if item.get("recordKind") == chain.COLLECTION_REQUEST_KIND
        ],
        "requestId",
        request_id,
    )


def test_auto_retry_recovers_zombie_handoff_pending_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """僵尸请求（handoff_pending + completed run + 过宽限）→ 幂等交接重试，
    请求转 handed_off，pending 计数归零（adjudicate 守卫解除）。"""
    events = _chain_env(tmp_path, monkeypatch)
    _seed_zombie_handoff_request()
    assert chain._pending_handoff_count(_TEAM_ID, _QUESTION_ID) == 1
    calls: list[dict[str, Any]] = []
    _fake_handoff_success(monkeypatch, calls)

    summary = chain.auto_retry_pending_collection_handoffs(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )

    assert summary["status"] == "retried"
    assert summary["retried"] == 1
    assert summary["failed"] == 0
    assert calls == [
        {
            "requestId": _ZOMBIE_REQUEST_ID,
            "handoffRef": f"source_collection_run:{_ZOMBIE_RUN_ID}",
        }
    ]
    recovered = _latest_request()
    assert recovered["status"] == "handed_off"
    assert recovered["lastAutoRetryAt"]
    # The pending-collection guard that blocked adjudication is gone.
    assert chain._pending_handoff_count(_TEAM_ID, _QUESTION_ID) == 0
    retried_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_retry_handoff"
    ]
    assert retried_events and retried_events[-1]["outcome"] == "retried"


def test_auto_retry_skips_within_grace_period(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上次尝试在宽限内 → skipped within_grace_period，不触碰交接。"""
    _chain_env(tmp_path, monkeypatch)
    _seed_zombie_handoff_request(last_auto_retry_at=_offset_iso(0))
    calls: list[dict[str, Any]] = []
    _fake_handoff_success(monkeypatch, calls)

    summary = chain.auto_retry_pending_collection_handoffs(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(30)
    )

    assert summary["status"] == "skipped"
    assert summary["retried"] == 0
    assert summary["skipped"] == 1
    assert calls == []
    assert _latest_request()["status"] == "handoff_pending"

    # The env override clamps to the 10s floor (a 5s override stays 10s).
    monkeypatch.setenv("VIBELUTION_AUTO_RETRY_HANDOFF_GRACE_MS", "5000")
    assert chain._auto_retry_handoff_grace_ms() == 10_000


def test_auto_retry_skips_when_collection_run_not_completed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run 还在跑（collectionRunStatus=running）→ skipped run_not_completed，
    writeback 归 writeback，重试不抢跑。"""
    events = _chain_env(tmp_path, monkeypatch)
    _seed_zombie_handoff_request(collection_run_status="running")
    calls: list[dict[str, Any]] = []
    _fake_handoff_success(monkeypatch, calls)

    summary = chain.auto_retry_pending_collection_handoffs(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )

    assert summary["status"] == "skipped"
    assert summary["retried"] == 0
    assert summary["skipped"] == 1
    assert calls == []
    assert _latest_request()["status"] == "handoff_pending"
    skipped_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_retry_handoff"
    ]
    assert skipped_events and skipped_events[-1]["fields"]["reason"] == (
        "run_not_completed"
    )


def test_auto_retry_isolates_domain_failure_and_restores_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """交接域拒绝 → failed 不外抛，请求打回 handoff_pending 下轮再试。"""
    events = _chain_env(tmp_path, monkeypatch)
    _seed_zombie_handoff_request()

    def _handoff_rejects(team_id, request_id, *, handoff_ref="", **_kwargs):
        raise chain.HypothesisFirstChainError("domain guard disagreed")

    monkeypatch.setattr(chain, "record_collection_handoff", _handoff_rejects)

    summary = chain.auto_retry_pending_collection_handoffs(
        _TEAM_ID, question_id=_QUESTION_ID, now_ms=_offset_ms(600)
    )

    assert summary["status"] == "failed"
    assert summary["failed"] == 1
    assert summary["retried"] == 0
    restored = _latest_request()
    assert restored["status"] == "handoff_pending"
    assert restored["handoffError"]["code"] == "handoff_failed"
    # The throttling timestamp advanced even on failure: the next pass waits
    # out the grace instead of hammering the same rejection every sweep.
    assert restored["lastAutoRetryAt"]
    failed_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_retry_handoff"
    ]
    assert failed_events and failed_events[-1]["outcome"] == "failed"


def test_maintenance_sweep_retries_zombie_handoff_before_adjudicating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sweep 同一 pass 内先重试僵尸交接再裁决：handoffsRetried 汇入 summary，
    adjudicate 不再被 pending 计数挡住，accepted 裁决真实落账。"""
    ledger_path = _sweep_env(tmp_path, monkeypatch)
    # The sweep env seeds a handed_off request; add the zombie that used to
    # wedge the chain (the live SCI-001 shape).
    _seed_zombie_handoff_request()
    assert chain._pending_handoff_count(_TEAM_ID, _QUESTION_ID) == 1
    calls: list[dict[str, Any]] = []
    _fake_handoff_success(monkeypatch, calls)

    summary = chain.sweep_auto_advance_closure()

    assert summary["handoffsRetried"] == 1
    assert summary["adjudicated"] == 1
    assert calls and calls[0]["requestId"] == _ZOMBIE_REQUEST_ID
    assert _latest_request()["status"] == "handed_off"
    adjudications = _adjudications(ledger_path)
    assert len(adjudications) == 1
    assert adjudications[0]["decision"] == "accepted"


# ---------------------------------------------------------------------------
# the auto-approval wait is an operator decision pinned to 0 (immediate)


def test_auto_approve_digest_default_ttl_is_immediate() -> None:
    """自动批准等待默认值钉在 0：无人工窗口，落地即批（2026-09 operator
    决定，取代此前的 3 分钟窗口）；正窗口下限常量保留供 env 覆盖钳制。"""
    assert chain.DEFAULT_AUTO_APPROVE_DIGEST_TTL_MS == 0
    assert chain.AUTO_APPROVE_DIGEST_TTL_MIN_MS == 60_000


# ---------------------------------------------------------------------------
# appended fix: generated HypothesisRound records carry no roundIndex of
# their own — the exhausted-round guard falls back to the review-round
# lineage links instead of collapsing to round 0 (which silently disabled
# budget-exhaustion adjudication on every live chain, e.g. SCI-001)


def _sweep_env_with_linkless_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    meeting_ids: list[str],
    seed_links: bool = True,
) -> Path:
    """The sweep read seams, but the latest round record has no roundIndex —
    the exact shape a generated round persists on live data."""
    ledger_path = _sweep_env(tmp_path, monkeypatch)
    round_record = {
        "roundId": _ROUND_ID,
        "question": _QUESTION_ID,
        "status": "closed",
        "metaReview": {
            "metaReviewId": "mr-sweep-5",
            "recommendationCandidateId": _CANDIDATE_ID,
            "accepted": False,
        },
        "meetingRefs": [
            {"kind": "meeting_round", "id": meeting_id}
            for meeting_id in meeting_ids
        ],
        "createdAt": "2026-09-01T00:00:00Z",
    }
    monkeypatch.setattr(
        chain,
        "_question_hypothesis_rounds",
        lambda _team_id, _question: [round_record]
        if str(_question).upper() == _QUESTION_ID
        else [],
    )
    monkeypatch.setattr(
        hrounds,
        "get_hypothesis_round",
        lambda _team_id, _round_id: {"round": round_record},
    )
    if seed_links:
        for meeting_id in meeting_ids:
            _seed_review_link(
                meeting_id,
                round_index=5,
                selection_id=_REGEN_SELECTION_ID,
            )
    return ledger_path


def test_exhausted_round_guard_resolves_index_from_review_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """round 记录无 roundIndex（活数据真实形状）→ 从 review round links 反查
    roundIndex=5，auto_adjudicate 正常开火（SCI-001 复现形状）。"""
    ledger_path = _sweep_env_with_linkless_round(
        tmp_path, monkeypatch, meeting_ids=[_MEETING_ID]
    )

    latest = chain._latest_closed_exhausted_round(_TEAM_ID, _QUESTION_ID)
    assert latest is not None
    assert latest["roundId"] == _ROUND_ID

    result = chain.auto_adjudicate_exhausted_round(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert result["status"] == "created"
    adjudications = _adjudications(ledger_path)
    assert len(adjudications) == 1
    assert adjudications[0]["decision"] == "accepted"


def test_exhausted_round_guard_stays_fail_closed_without_link_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """round 无 roundIndex 且 links 反查不到任何会议 → fail-closed 返回 None，
    adjudicate 保持 skipped round_not_exhausted（绝不猜测）。"""
    _sweep_env_with_linkless_round(
        tmp_path,
        monkeypatch,
        meeting_ids=["meeting-never-linked"],
        seed_links=False,
    )

    assert chain._latest_closed_exhausted_round(_TEAM_ID, _QUESTION_ID) is None
    result = chain.auto_adjudicate_exhausted_round(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert result == {"status": "skipped", "reason": "round_not_exhausted"}


def test_exhausted_round_budget_counts_superseded_newest_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """预算轮被取代的活形状（SCI-001 2026-09-02 复现）：

    最权威 round 覆盖 r4 会议（自身 link roundIndex=4），但该 selection 的
    r5 会议被 blocked-run 恢复无摘要关闭、永远不产 round——fan-in 正确落回
    r4 组。耗尽判定必须看 selection 的会议轮预算（最新 link=5），而不是
    round 自身组的轮号（4），否则这条链永远到不了裁决。
    """
    ledger_path = _sweep_env_with_linkless_round(
        tmp_path, monkeypatch, meeting_ids=[_MEETING_ID], seed_links=False
    )
    # The round's own meetings sit at round 4 of the selection...
    for link_meeting_id in (_MEETING_ID,):
        _seed_review_link(
            link_meeting_id,
            round_index=4,
            selection_id=_REGEN_SELECTION_ID,
            created_at="2026-09-02T04:38:00Z",
        )
    # ...while the selection's round-5 budget meetings were force-closed
    # without a digest (superseded; they never generate a round of their own).
    for index, superseded_meeting_id in enumerate(
        ("superseded-r5-alpha", "superseded-r5-beta")
    ):
        _seed_review_link(
            superseded_meeting_id,
            round_index=5,
            candidate_id=f"cand-r5-{index}",
            selection_id=_REGEN_SELECTION_ID,
            created_at="2026-09-02T06:11:00Z",
        )
    # A different selection's rounds must not leak into this budget.
    _seed_review_link(
        "other-selection-r7",
        round_index=7,
        selection_id="hsel-other-selection",
        created_at="2026-09-02T06:12:00Z",
    )

    latest = chain._latest_closed_exhausted_round(_TEAM_ID, _QUESTION_ID)
    assert latest is not None
    assert latest["roundId"] == _ROUND_ID

    result = chain.auto_adjudicate_exhausted_round(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert result["status"] == "created"
    adjudications = _adjudications(ledger_path)
    assert len(adjudications) == 1
    assert adjudications[0]["hypothesisRoundId"] == _ROUND_ID


# ---------------------------------------------------------------------------
# knowledge-handoff auto-accept: the ingestion governance chain (source review
# accepted -> knowledge review approved -> official sync) is itself the human
# decision, so the residual knowledge_handoff click on formal runs is accepted
# automatically through the resolve_human_task command SSOT — never for other
# human gates and never without the knowledge_package_draft artifact proof.


from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
)

_KH_RUN_ID = "run-knowledge-handoff"
_KH_TASK_ID = "ht-knowledge-auto"
_KH_NODE_RUN_ID = "nr-run-knowledge-handoff-knowledge_handoff-a1"
_KH_TEAM_ID = "research-team"


def _accepted_knowledge_package() -> dict[str, object]:
    return {
        "teamId": _KH_TEAM_ID,
        "sourceCollectionRunId": "sc-run-1",
        "accepted": True,
        "knowledgeItems": [
            {"knowledgeItemId": "ki-1", "contentHash": "b" * 64}
        ],
    }


class _FakeAttemptRecord:
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id


class _FakeEvent:
    def __init__(
        self,
        *,
        sequence: int,
        event_id: str,
        event_type: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> None:
        self.sequence = sequence
        self.event_id = event_id
        self.event_type = event_type
        self.correlation_id = correlation_id
        self.payload_json = json.dumps(payload, ensure_ascii=False)


class _FakeHandoffRepo:
    """In-memory stand-in for the ledger repository reads the scan needs."""

    def __init__(
        self,
        *,
        pending_tasks: list[tuple] | None = None,
        attempts: dict[str, _FakeAttemptRecord] | None = None,
        handoffs_by_node: dict[str, list[tuple]] | None = None,
        artifact_refs: list[tuple] | None = None,
        events: list[_FakeEvent] | None = None,
    ) -> None:
        self._pending_tasks = pending_tasks or []
        self._attempts = attempts or {}
        self._handoffs_by_node = handoffs_by_node or {}
        self._artifact_refs = artifact_refs or []
        self._events = events or []

    def list_pending_human_tasks(self, run_id: str) -> list[tuple]:
        return list(self._pending_tasks)

    def get_attempt(self, node_run_id: str) -> _FakeAttemptRecord | None:
        return self._attempts.get(node_run_id)

    def list_handoffs_for_node(self, run_id: str, to_node_id: str) -> list[tuple]:
        return list(self._handoffs_by_node.get(to_node_id) or [])

    def list_handoff_artifact_refs_for_run(self, run_id: str) -> list[tuple]:
        return list(self._artifact_refs)

    def latest_event_sequence(self, run_id: str) -> int:
        return max((item.sequence for item in self._events), default=0)

    def list_events(
        self, run_id: str, after_sequence: int = 0, limit: int = 500
    ) -> list[_FakeEvent]:
        return [
            item
            for item in self._events
            if item.sequence > after_sequence
        ][:limit]


class _FakeHandoffStore:
    def __init__(self, repo: _FakeHandoffRepo, run_version: int = 7) -> None:
        self.repo = repo
        self.run_version = run_version

    def read(self, fn):
        return fn(self.repo)

    def get_run(self, run_id: str):
        return SimpleNamespace(team_id=_TEAM_ID, run_version=self.run_version)


class _FakeHandoffCommandService:
    def __init__(
        self,
        *,
        receipt: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.requests: list[Any] = []
        self.operator_ids: list[str] = []
        self._receipt = receipt or {"status": "accepted"}
        self._error = error

    def submit(self, request: Any):
        from core.web.services.team_workflow.research_runtime.operator_authorization import (
            current_server_operator,
        )

        self.requests.append(request)
        operator = current_server_operator()
        self.operator_ids.append(
            str(operator.operator_id) if operator is not None else ""
        )
        if self._error is not None:
            raise self._error
        payload = dict(self._receipt)

        class _Receipt:
            def to_dict(self) -> dict[str, Any]:
                return dict(payload)

        return _Receipt()


def _pending_knowledge_task_tuple(
    task_id: str = _KH_TASK_ID,
    *,
    node_run_id: str = _KH_NODE_RUN_ID,
    task_kind: str = chain.KNOWLEDGE_HANDOFF_TASK_KIND,
) -> tuple:
    return (
        task_id,
        "run-1",
        node_run_id,
        "ho-outbound-1",
        task_kind,
        json.dumps({"nodeId": "knowledge_handoff"}),
        "pending",
        None,
        FIXED_NOW_MS,
        None,
    )


def _inbound_handoff_rows() -> list[tuple]:
    return [
        (
            "ho-inbound-1",
            "run-1",
            "knowledge_ingestion->knowledge_handoff",
            "nr-run-1-knowledge_ingestion-a1",
            "knowledge_handoff",
            None,
            "human",
            "a" * 64,
            "ready",
            None,
            None,
            None,
            FIXED_NOW_MS,
            None,
        )
    ]


def _draft_artifact_refs() -> list[tuple]:
    return [
        (
            "ho-inbound-1",
            "ar-draft-1",
            "knowledge_package_draft",
            json.dumps({"canonicalRef": "knowledge_package_draft://x"}),
            "1.0.0",
            "c" * 64,
        )
    ]


def _auto_accepted_event(
    task_id: str = _KH_TASK_ID,
    *,
    sequence: int = 2,
    correlation_id: str = "",
) -> _FakeEvent:
    return _FakeEvent(
        sequence=sequence,
        event_id=f"evt-{sequence}",
        event_type="handoff_accepted",
        correlation_id=(
            correlation_id
            or f"hf2:auto-knowledge-handoff:run-1:{task_id}"
        ),
        payload={"taskId": task_id, "decision": "accept"},
    )


def _unit_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    repo: _FakeHandoffRepo,
    *,
    command: _FakeHandoffCommandService | None = None,
    runs: list[dict[str, Any]] | None = None,
    run_version: int = 7,
) -> tuple[list[dict[str, Any]], _FakeHandoffCommandService]:
    """Tmp isolation + fake formal runtime; returns (captured events, command)."""
    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
    )

    events = _approve_env(tmp_path, monkeypatch)
    command = command or _FakeHandoffCommandService()
    monkeypatch.setattr(
        formal_read_runtime,
        "get_query_service",
        lambda: _FakeQueryService(
            runs
            if runs is not None
            else [
                {
                    "runId": "run-1",
                    "questionId": _QUESTION_ID,
                    "status": "waiting_human",
                }
            ]
        ),
    )
    store = _FakeHandoffStore(repo, run_version=run_version)
    monkeypatch.setattr(
        runtime_factory,
        "production_workflow_runtime",
        lambda: _FakeUnitRuntime(store, command),
    )
    return events, command


class _FakeUnitRuntime:
    def __init__(self, store: _FakeHandoffStore, command: Any) -> None:
        self.store = store
        self.command_service = command


class _CapturingCommandService:
    """Wraps the real command SSOT, capturing requests + operator context."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.requests: list[Any] = []
        self.operator_ids: list[str] = []

    def submit(self, request: Any):
        from core.web.services.team_workflow.research_runtime.operator_authorization import (
            current_server_operator,
        )

        operator = current_server_operator()
        self.operator_ids.append(
            str(operator.operator_id) if operator is not None else ""
        )
        self.requests.append(request)
        return self._inner.submit(request)


def _seed_auto_accept_gate(harness: CommandHarness) -> None:
    """Real ledger shape: pending knowledge_handoff gate with draft refs."""
    from core.research.workflow.definition import (
        build_challenge_cup_workflow_definition,
    )
    from core.research.workflow.definition_registry import register_or_resolve

    identity = register_or_resolve(build_challenge_cup_workflow_definition())
    run = replace(
        build_run_record(
            run_id=_KH_RUN_ID,
            workflow_version_id=identity.workflowVersionId,
            last_event_sequence=1,
        ),
        structure_hash=identity.structureHash,
        input_snapshot_json=json.dumps(
            {
                "snapshotHash": "a" * 64,
                "sourceCollectionRunId": "sc-run-1",
            }
        ),
    )
    attempt = replace(
        build_attempt_record(
            node_run_id=_KH_NODE_RUN_ID,
            node_id="knowledge_handoff",
            actor_kind="human",
            status="waiting_human",
            command_id="cmd-seed-kh",
        ),
        run_id=_KH_RUN_ID,
        pending_action_id="act-knowledge-human",
    )

    def mutate(uow):
        uow.repository.insert_run(run)
        uow.repository.insert_event(
            build_event_record(
                sequence=1,
                run_id=_KH_RUN_ID,
                event_id="evt-created-run-kh",
            )
        )
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-seed-kh",
                run_id=_KH_RUN_ID,
                command_kind="start_node",
                node_id="knowledge_handoff",
            )
        )
        uow.repository.insert_attempt(attempt)
        # Outbound handoff: the selector the accept binds its
        # knowledge_package receipt to (task.handoffId points here).
        uow.repository.insert_handoff(
            handoff_id="ho-knowledge-hypothesis",
            run_id=_KH_RUN_ID,
            edge_id="knowledge_handoff->hypothesis_design",
            from_node_run_id=attempt.node_run_id,
            to_node_id="hypothesis_design",
            to_node_run_id=None,
            gate_kind="knowledge_package",
            input_snapshot_hash="a" * 64,
            offered_at_ms=FIXED_NOW_MS,
        )
        uow.repository.update_handoff_status(
            "ho-knowledge-hypothesis", "waiting_human", FIXED_NOW_MS
        )
        # Inbound handoff: knowledge_ingestion -> knowledge_handoff, carrying
        # the knowledge_package_draft artifact refs bound at agent-commit.
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id="nr-run-knowledge-handoff-knowledge_ingestion-a1",
                run_id=_KH_RUN_ID,
                node_id="knowledge_ingestion",
                actor_kind="agent",
                status="succeeded",
                command_id="cmd-seed-kh",
            )
        )
        uow.repository.insert_handoff(
            handoff_id="ho-ingest-knowledge",
            run_id=_KH_RUN_ID,
            edge_id="knowledge_ingestion->knowledge_handoff",
            from_node_run_id="nr-run-knowledge-handoff-knowledge_ingestion-a1",
            to_node_id="knowledge_handoff",
            to_node_run_id=None,
            gate_kind="human",
            input_snapshot_hash="a" * 64,
            offered_at_ms=FIXED_NOW_MS,
        )
        uow.repository.update_handoff_status(
            "ho-ingest-knowledge", "ready", FIXED_NOW_MS
        )
        uow.repository.insert_artifact_receipt(
            receipt_id="ar-draft-1",
            run_id=_KH_RUN_ID,
            node_run_id="nr-run-knowledge-handoff-knowledge_ingestion-a1",
            team_id=_KH_TEAM_ID,
            artifact_kind="knowledge_package_draft",
            canonical_ref_json=json.dumps(
                {"canonicalRef": "knowledge_package_draft://sc-run-1"}
            ),
            artifact_version="1.0.0",
            sha256="c" * 64,
            domain_revision="d" * 32,
            materialized=1,
            verified_at_ms=FIXED_NOW_MS,
        )
        uow.repository.insert_handoff_receipt("ho-ingest-knowledge", "ar-draft-1", 0)
        uow.repository.insert_human_task(
            task_id=_KH_TASK_ID,
            run_id=_KH_RUN_ID,
            node_run_id=attempt.node_run_id,
            handoff_id="ho-knowledge-hypothesis",
            task_kind="gate:knowledge_handoff",
            prompt_json='{"nodeId":"knowledge_handoff"}',
            created_at_ms=FIXED_NOW_MS,
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _kh_integration_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    harness: CommandHarness,
    capturing: _CapturingCommandService,
) -> None:
    """Point the auto-accept helper at the real ledger + command SSOT."""
    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        formal_read_runtime,
        "get_query_service",
        lambda: _FakeQueryService(
            [
                {
                    "runId": _KH_RUN_ID,
                    "questionId": "SCI-096",
                    "status": "waiting_human",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        runtime_factory,
        "production_workflow_runtime",
        lambda: SimpleNamespace(
            store=harness.store, command_service=capturing
        ),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime."
        "human_acceptance_artifact.load_scoped_artifact_payload",
        lambda *args, **kwargs: _accepted_knowledge_package(),
    )


def test_auto_accept_submits_command_then_replays_as_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pending + 入边 draft 引用 → 走正式命令 SSOT accept（system 身份、
    幂等键、任务翻 accepted 落盘）；再跑一次 → reused 不重复提交。"""
    from core.research.workflow.contracts import (
        ActorRef,
        WorkflowCommandKind,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_auto_accept_gate(harness)
        capturing = _CapturingCommandService(harness.command_service)
        _kh_integration_env(tmp_path, monkeypatch, harness, capturing)
        events = _capture_scene_events(monkeypatch)

        summary = chain.auto_accept_knowledge_handoffs(
            _KH_TEAM_ID, question_id="SCI-096"
        )

        assert summary == {
            "runsScanned": 1,
            "pendingTasks": 1,
            "accepted": 1,
            "reused": 0,
            "skipped": 0,
            "failed": 0,
        }
        assert len(capturing.requests) == 1
        request = capturing.requests[0]
        assert request.command is WorkflowCommandKind.RESOLVE_HUMAN_TASK
        assert request.node_id == "knowledge_handoff"
        assert request.idempotency_key == (
            f"hf2:auto-knowledge-handoff:{_KH_RUN_ID}:{_KH_TASK_ID}"
        )
        assert request.expected_run_version == 1
        assert request.payload["taskId"] == _KH_TASK_ID
        assert request.payload["decision"] == "accept"
        assert (
            "auto-advance: knowledge ingestion review chain passed"
            in request.payload["reason"]
        )
        assert request.requested_by == ActorRef(
            "system", "system:auto-advance:knowledge-handoff"
        )
        # The server-bound operator scope the helper carries (authorization
        # reached the raw command service, so the accept is not forbidden).
        assert capturing.operator_ids == [
            "system:auto-advance:knowledge-handoff"
        ]

        # System identity and accept decision are durable on the task row.
        row = harness.store.read(
            lambda repo: repo.get_human_task(_KH_TASK_ID)
        )
        assert row is not None and row[6] == "accepted"
        assert "system:auto-advance:knowledge-handoff" in str(row[7])
        command_row = harness.store.get_command_by_idempotency(
            _KH_RUN_ID,
            f"hf2:auto-knowledge-handoff:{_KH_RUN_ID}:{_KH_TASK_ID}",
        )
        assert command_row is not None
        accepted_events = [
            item
            for item in events
            if item["code"] == "hypothesis_first.auto_accept_knowledge_handoff"
            and item["outcome"] == "accepted"
        ]
        assert len(accepted_events) == 1
        assert accepted_events[0]["fields"]["runId"] == _KH_RUN_ID
        assert accepted_events[0]["fields"]["taskId"] == _KH_TASK_ID

        # Second pass: the task is resolved, the sweep's own accept replays
        # from the ledger as reused — no second command.
        replay = chain.auto_accept_knowledge_handoffs(
            _KH_TEAM_ID, question_id="SCI-096"
        )
        assert replay["accepted"] == 0
        assert replay["reused"] == 1
        assert replay["failed"] == 0
        assert len(capturing.requests) == 1
    finally:
        harness.close()


@pytest.mark.parametrize("workflow_id", [
    "challenge-cup-research", "challenge-cup-knowledge-sideflow",
])
def test_auto_accept_scans_governed_gate_in_each_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workflow_id: str,
) -> None:
    from core.web.services.team_workflow.research_runtime import formal_read_runtime

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_auto_accept_gate(harness)
        capturing = _CapturingCommandService(harness.command_service)
        _kh_integration_env(tmp_path, monkeypatch, harness, capturing)
        queried = []

        class ScopedQuery:
            def list_runs(self, *, team_id: str, workflow_id: str):
                queried.append(workflow_id)
                return {"runs": [
                    {"runId": _KH_RUN_ID, "questionId": "SCI-096", "status": "waiting_human"},
                    {"runId": "other-question", "questionId": "SCI-097", "status": "waiting_human"},
                    {"runId": "archived-run", "questionId": "SCI-096", "status": "archived"},
                ] if workflow_id == target_workflow else []}

        target_workflow = workflow_id
        monkeypatch.setattr(formal_read_runtime, "get_query_service", ScopedQuery)
        summary = chain.auto_accept_knowledge_handoffs(_KH_TEAM_ID, question_id="SCI-096")
        assert summary["accepted"] == 1
        assert summary["runsScanned"] == 1
        assert summary["failed"] == 0
        assert len(capturing.requests) == 1
        assert set(queried) == {"challenge-cup-research", "challenge-cup-knowledge-sideflow"}
        replay = chain.auto_accept_knowledge_handoffs(_KH_TEAM_ID, question_id="SCI-096")
        assert replay["reused"] == 1
        assert replay["accepted"] == 0
        assert len(capturing.requests) == 1
    finally:
        harness.close()


def test_auto_accept_skips_when_no_pending_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 pending task → runsScanned 计数但零动作、零提交。"""
    repo = _FakeHandoffRepo()
    _events, command = _unit_env(monkeypatch, tmp_path, repo)

    summary = chain.auto_accept_knowledge_handoffs(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["runsScanned"] == 1
    assert summary["pendingTasks"] == 0
    assert summary["accepted"] == 0
    assert summary["reused"] == 0
    assert summary["skipped"] == 0
    assert summary["failed"] == 0
    assert command.requests == []


def test_auto_accept_fails_closed_without_draft_artifact_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """入边缺 knowledge_package_draft 引用（或无入边）→ skipped
    artifact_refs_missing，任务保持 pending，绝不猜。"""
    # Inbound handoff exists but only carries a non-draft ref.
    repo = _FakeHandoffRepo(
        pending_tasks=[_pending_knowledge_task_tuple()],
        attempts={_KH_NODE_RUN_ID: _FakeAttemptRecord("knowledge_handoff")},
        handoffs_by_node={"knowledge_handoff": _inbound_handoff_rows()},
        artifact_refs=[
            (
                "ho-inbound-1",
                "ar-graph-1",
                "evidence_relation_graph",
                "{}",
                "1.0.0",
                "c" * 64,
            )
        ],
    )
    _events, command = _unit_env(monkeypatch, tmp_path, repo)

    summary = chain.auto_accept_knowledge_handoffs(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["pendingTasks"] == 1
    assert summary["skipped"] == 1
    assert summary["accepted"] == 0
    assert command.requests == []
    skipped = [
        item
        for item in _events
        if item["code"] == "hypothesis_first.auto_accept_knowledge_handoff"
    ]
    assert len(skipped) == 1
    assert skipped[0]["outcome"] == "skipped"
    assert skipped[0]["fields"]["reason"] == "artifact_refs_missing"

    # No inbound handoff at all: the same fail-closed skip.
    repo_no_handoff = _FakeHandoffRepo(
        pending_tasks=[_pending_knowledge_task_tuple()],
        attempts={_KH_NODE_RUN_ID: _FakeAttemptRecord("knowledge_handoff")},
    )
    _events_2, command_2 = _unit_env(monkeypatch, tmp_path, repo_no_handoff)
    summary_2 = chain.auto_accept_knowledge_handoffs(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert summary_2["skipped"] == 1
    assert command_2.requests == []
    reasons = {
        item["fields"].get("reason")
        for item in _events_2
        if item["code"] == "hypothesis_first.auto_accept_knowledge_handoff"
    }
    assert reasons == {"artifact_refs_missing"}


def test_auto_accept_ignores_human_decided_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """人工已决策（事件 correlation 是人工键）→ 既不重放为 reused，
    也绝不改写；零提交。"""
    repo = _FakeHandoffRepo(
        # The task was resolved by a human operator: not pending anymore.
        pending_tasks=[],
        events=[
            _FakeEvent(
                sequence=2,
                event_id="evt-human-accept",
                event_type="handoff_accepted",
                correlation_id="ui:human-accept-1",
                payload={"taskId": _KH_TASK_ID, "decision": "accept"},
            )
        ],
    )
    _events, command = _unit_env(monkeypatch, tmp_path, repo)

    summary = chain.auto_accept_knowledge_handoffs(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary == {
        "runsScanned": 1,
        "pendingTasks": 0,
        "accepted": 0,
        "reused": 0,
        "skipped": 0,
        "failed": 0,
    }
    assert command.requests == []


def test_auto_accept_never_touches_other_human_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """smoke_gate 等其它人工门（真人工决策语义）→ 完全不动；task_kind 与
    node attempt 不一致的 gate 也不碰（fail-closed）。"""
    repo = _FakeHandoffRepo(
        pending_tasks=[
            _pending_knowledge_task_tuple(
                "ht-smoke",
                node_run_id="nr-run-1-smoke_gate-a1",
                task_kind="gate:smoke_gate",
            ),
            _pending_knowledge_task_tuple(
                "ht-mismatch",
                node_run_id="nr-run-1-protocol_freeze-a1",
            ),
        ],
        attempts={
            "nr-run-1-smoke_gate-a1": _FakeAttemptRecord("smoke_gate"),
            "nr-run-1-protocol_freeze-a1": _FakeAttemptRecord(
                "protocol_freeze"
            ),
        },
        handoffs_by_node={"knowledge_handoff": _inbound_handoff_rows()},
        artifact_refs=_draft_artifact_refs(),
    )
    _events, command = _unit_env(monkeypatch, tmp_path, repo)

    summary = chain.auto_accept_knowledge_handoffs(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    # smoke_gate stays invisible to the helper; the knowledge-handoff-kind
    # task whose node attempt disagrees is fail-closed skipped, not accepted.
    assert summary["pendingTasks"] == 1
    assert summary["accepted"] == 0
    assert summary["skipped"] == 1
    assert summary["failed"] == 0
    assert command.requests == []
    skipped = [
        item
        for item in _events
        if item["code"] == "hypothesis_first.auto_accept_knowledge_handoff"
    ]
    assert len(skipped) == 1
    assert skipped[0]["fields"]["taskId"] == "ht-mismatch"
    assert skipped[0]["fields"]["reason"] == "task_node_unverifiable"


def test_auto_accept_isolates_rejections_and_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命令域拒绝（已决策/版本冲突等）→ skipped；意外异常 → failed；
    均不外抛。"""
    # Typed domain rejection.
    repo = _FakeHandoffRepo(
        pending_tasks=[_pending_knowledge_task_tuple()],
        attempts={_KH_NODE_RUN_ID: _FakeAttemptRecord("knowledge_handoff")},
        handoffs_by_node={"knowledge_handoff": _inbound_handoff_rows()},
        artifact_refs=_draft_artifact_refs(),
    )
    rejected = _FakeHandoffCommandService(
        error=chain.HypothesisFirstChainError("human task 已被并发决策")
    )
    events, _command = _unit_env(monkeypatch, tmp_path, repo, command=rejected)

    summary = chain.auto_accept_knowledge_handoffs(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert summary["accepted"] == 0
    assert summary["skipped"] == 1
    assert summary["failed"] == 0
    outcomes = {
        item["outcome"]: item
        for item in events
        if item["code"] == "hypothesis_first.auto_accept_knowledge_handoff"
    }
    assert "skipped" in outcomes
    assert "并发决策" in str(outcomes["skipped"]["fields"]["reason"])

    # Unexpected storage explosion.
    repo_boom = _FakeHandoffRepo(
        pending_tasks=[_pending_knowledge_task_tuple()],
        attempts={_KH_NODE_RUN_ID: _FakeAttemptRecord("knowledge_handoff")},
        handoffs_by_node={"knowledge_handoff": _inbound_handoff_rows()},
        artifact_refs=_draft_artifact_refs(),
    )
    exploded = _FakeHandoffCommandService(error=RuntimeError("disk on fire"))
    events_boom, _command_boom = _unit_env(
        monkeypatch, tmp_path, repo_boom, command=exploded
    )
    summary_boom = chain.auto_accept_knowledge_handoffs(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert summary_boom["failed"] == 1
    assert summary_boom["skipped"] == 0
    failed = [
        item
        for item in events_boom
        if item["code"] == "hypothesis_first.auto_accept_knowledge_handoff"
        and item["outcome"] == "failed"
    ]
    assert len(failed) == 1
    assert failed[0]["level"] == "warning"
    assert "disk on fire" in str(failed[0]["fields"]["reason"])


def _capture_scene_events(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    """Swap the chain's scene event recorder for a capturing list."""
    events: list[dict[str, Any]] = []

    def _capture(
        event_code: str,
        *,
        outcome: str,
        fields: dict[str, Any] | None = None,
        level: str = "info",
    ) -> None:
        events.append(
            {
                "code": event_code,
                "outcome": outcome,
                "fields": dict(fields or {}),
                "level": level,
            }
        )

    monkeypatch.setattr(chain, "_record_scene_event", _capture)
    return events


def test_maintenance_sweep_accepts_knowledge_handoffs_after_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sweep 每题顺序：adjudicate → create(+start) → knowledge-handoff-accept
    → retry；knowledgeHandoffsAccepted 计数汇入 summary 与 sweep scene event。"""
    from core.web.services.team_workflow.research_runtime import run_creation

    ledger_path = _sweep_env(tmp_path, monkeypatch)
    order: list[str] = []
    # Sequencing seam: the canonical creation command owns create + start.
    monkeypatch.setattr(chain, "auto_create_formal_run_after_convergence",
                        lambda *_args, **_kwargs: (order.extend(["create", "start"])
                            or {"status": "created", "runId": "run-sweep", "roundId": _ROUND_ID}))

    def _record_accept(team_id: str, *, question_id: str) -> dict[str, Any]:
        order.append(f"knowledge-handoff:{question_id}")
        return {
            "runsScanned": 1,
            "pendingTasks": 1,
            "accepted": 1,
            "reused": 0,
            "skipped": 0,
            "failed": 0,
        }

    monkeypatch.setattr(chain, "auto_accept_knowledge_handoffs", _record_accept)

    def _record_retry(team_id: str, *, question_id: str) -> dict[str, Any]:
        order.append(f"retry:{question_id}")
        return {"blockedRuns": 1, "retried": 1, "skipped": 0, "failed": 0}

    monkeypatch.setattr(chain, "auto_retry_blocked_formal_nodes", _record_retry)
    events = _capture_scene_events(monkeypatch)

    summary = chain.sweep_auto_advance_closure()

    assert order == [
        "create",
        "start",
        f"knowledge-handoff:{_QUESTION_ID}",
        f"retry:{_QUESTION_ID}",
    ]
    assert summary["knowledgeHandoffsAccepted"] == 1
    assert summary["adjudicated"] == 1
    assert summary["formalRuns"] == 1
    sweep_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_advance_sweep"
    ]
    assert sweep_events and sweep_events[-1]["outcome"] == "completed"
    assert sweep_events[-1]["fields"]["knowledgeHandoffsAccepted"] == 1
    adjudications = _adjudications(ledger_path)
    assert len(adjudications) == 1
    assert adjudications[0]["decision"] == "accepted"


@pytest.mark.parametrize("eligible", [False, True])
def test_grounded_generation_auto_consumes_only_normal_r1_offer(
    monkeypatch: pytest.MonkeyPatch, eligible: bool,
) -> None:
    from core.web.services.team_workflow.research_runtime import hypothesis_first_state_v2
    from core.web.services.team_workflow.research_runtime import formal_read_runtime
    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: SimpleNamespace(
        list_runs=lambda **kwargs: {"runs": [
            {"runId": "old-broken-run", "questionId": _QUESTION_ID,
             "status": "blocked", "createdAt": "2026-09-01"},
            {"runId": "run-r1", "questionId": _QUESTION_ID,
             "status": "blocked", "createdAt": "2026-09-05"},
            {"runId": "other-question", "questionId": "SCI-999",
             "status": "running", "createdAt": "2026-09-06"},
        ]},
    ))
    action = {
        "actionId": "open-stage-one-generation", "command": "open_generation",
        "enabled": eligible, "payload": {"questionId": _QUESTION_ID, "runId": "run-r1"},
        "idempotencyKey": "r1-offer", "expectedStateVersion": "action-version",
    }
    def project(team_id, question_id, *, workflow_run_id=""):
        assert workflow_run_id == "run-r1", "old broken snapshots must not be read"
        return {"stateVersion": "fresh-version", "allowedActions": [action]}

    monkeypatch.setattr(hypothesis_first_state_v2, "project_hypothesis_first_state_v2", project)
    requests = []
    monkeypatch.setattr(chain, "execute_v2_command",
                        lambda *args, **kwargs: requests.append((args, kwargs)) or {})
    _capture_scene_events(monkeypatch)
    assert chain.auto_advance_stage_one_generation(_TEAM_ID, question_id=_QUESTION_ID) == {
        "opened": int(eligible), "failed": 0,
    }
    assert len(requests) == int(eligible)
    if eligible:
        assert requests[0][0] == (_TEAM_ID, {**action, "expectedStateVersion": "fresh-version"})
        assert requests[0][1] == {"question_id": _QUESTION_ID, "workflow_run_id": "run-r1"}


def test_sweep_automatically_launches_r1_after_knowledge_accept_and_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sweep_env(tmp_path, monkeypatch)
    order = []
    for name, label in [("auto_accept_knowledge_handoffs", "accept"),
                        ("auto_retry_blocked_formal_nodes", "retry"),
                        ("auto_advance_stage_one_generation", "r1")]:
        monkeypatch.setattr(chain, name,
                            lambda *args, _label=label, **kwargs: order.append(_label) or {})
    chain.sweep_auto_advance_closure()
    assert order == ["accept", "retry", "r1"]


def test_grounded_generation_skips_full_projection_without_an_active_run(monkeypatch):
    from core.web.services.team_workflow.research_runtime import formal_read_runtime, hypothesis_first_state_v2

    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: SimpleNamespace(
        list_runs=lambda **kwargs: {"runs": [
            {"runId": "done", "questionId": _QUESTION_ID, "status": "succeeded"},
        ]},
    ))
    def unexpected_projection(*args, **kwargs):
        pytest.fail("historical terminal questions must not build full UI state")
    monkeypatch.setattr(hypothesis_first_state_v2, "project_hypothesis_first_state_v2", unexpected_projection)
    assert chain.auto_advance_stage_one_generation(_TEAM_ID, question_id=_QUESTION_ID) == {
        "opened": 0, "failed": 0,
    }


@pytest.mark.parametrize("attempts,expected", [(0, 0), (1, 1), (3, 0)])
@pytest.mark.parametrize("failure_code", ["discussion_round_failed", "diversity_collapse"])
def test_failed_grounded_generation_retries_only_within_r1_budget(monkeypatch, attempts, expected, failure_code):
    from core.web.services.team_workflow.research_runtime import formal_read_runtime, hypothesis_first_state_v2

    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: SimpleNamespace(
        list_runs=lambda **kwargs: {"runs": [
            {"runId": "run-r1", "questionId": _QUESTION_ID, "status": "blocked"},
        ]},
    ))
    action = {"actionId": "retry-generation", "command": "retry_generation", "enabled": True,
              "payload": {"runId": "run-r1"}, "idempotencyKey": "retry-r1"}
    monkeypatch.setattr(hypothesis_first_state_v2, "project_hypothesis_first_state_v2",
                        lambda *args, **kwargs: {"stateVersion": "fresh", "allowedActions": [action],
                            "generation": {"lifecycle": "failed", "generationMeetingId": "r1-current",
                                "problems": [{"code": failure_code}]}})
    meetings = [{"meetingRoundId": "r0", "modelInvocationReceiptAuthority": {"workflowRunId": "run-r1"},
                 "candidateAuthority": "exploratory_draft"}]
    meetings.extend({"meetingRoundId": "r1-current" if i == 0 else f"r1-{i}",
                     "modelInvocationReceiptAuthority": {"workflowRunId": "run-r1"}, "candidateAuthority": "formal_grounded_candidate"}
                    for i in range(attempts))
    monkeypatch.setattr(chain, "_question_generation_meetings", lambda *args: meetings)
    calls = []
    monkeypatch.setattr(chain, "execute_v2_command", lambda *args, **kwargs: calls.append((args, kwargs)))
    _capture_scene_events(monkeypatch)
    result = chain.auto_advance_stage_one_generation(_TEAM_ID, question_id=_QUESTION_ID)
    assert result == {"opened": expected, "failed": 0}
    assert len(calls) == expected


@pytest.mark.parametrize("authority,meeting_run,enabled,expected", [
    ("formal_grounded_candidate", "run-r1", True, 1),
    ("exploratory_draft", "run-r1", True, 0),
    ("formal_grounded_candidate", "another-run", True, 0),
    ("formal_grounded_candidate", "run-r1", False, 0),
])
def test_single_question_automatically_screens_all_grounded_candidates(
    monkeypatch, authority, meeting_run, enabled, expected,
):
    from core.web.services.team_workflow.research_runtime import formal_read_runtime, hypothesis_first_state_v2
    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: SimpleNamespace(
        list_runs=lambda **kwargs: {"runs": [
            {"runId": "run-r1", "questionId": _QUESTION_ID, "status": "blocked"},
        ]},
    ))
    action = {"actionId": "record-selection", "command": "record_selection", "enabled": enabled,
              "payload": {"questionId": _QUESTION_ID}, "idempotencyKey": "select-r1"}
    ids = ["candidate-a", "candidate-b", "candidate-c", "candidate-d"]
    monkeypatch.setattr(hypothesis_first_state_v2, "project_hypothesis_first_state_v2",
        lambda *args, **kwargs: {"stateVersion": "fresh", "allowedActions": [action],
            "generation": {"lifecycle": "completed", "generationMeetingId": "r1-current", "candidateIds": ids},
            "selection": {"lifecycle": "waiting_human", "selectionId": None}})
    monkeypatch.setattr(chain, "_question_generation_meetings", lambda *args: [
        {"meetingRoundId": "r1-current", "status": "closed", "candidateAuthority": authority,
         "modelInvocationReceiptAuthority": {"workflowRunId": meeting_run}},
    ])
    calls = []
    monkeypatch.setattr(chain, "execute_v2_command", lambda *args, **kwargs: calls.append((args, kwargs)))
    _capture_scene_events(monkeypatch)
    chain.auto_advance_stage_one_generation(_TEAM_ID, question_id=_QUESTION_ID)
    assert len(calls) == expected
    if expected:
        assert calls[0][0][1]["input"] == {"candidateIds": ids}
        assert calls[0][1]["workflow_run_id"] == "run-r1"
        assert calls[0][1]["_actor"] == "system:stage-one-auto-selection"


def test_sweep_budget_stops_new_questions_and_resumes_from_stop_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺陷 19 兜底：一轮超出墙钟预算后停止开新题，summary 记录
    budgetExhausted/questionsDeferred；下一轮从停点 round-robin 续扫。"""
    import time

    _sweep_env(tmp_path, monkeypatch)
    monkeypatch.setattr(chain, "_SWEEP_ROUND_ROBIN_CURSOR", None)
    monkeypatch.setenv(chain._AUTO_ADVANCE_SWEEP_BUDGET_ENV, "1")
    questions = ["SCI-A", "SCI-B", "SCI-C"]
    visited: list[str] = []
    monkeypatch.setattr(
        chain, "_team_ids_with_chain_storage", lambda: ["team-budget-1"]
    )
    monkeypatch.setattr(
        chain,
        "question_ids_with_chain_records",
        lambda _team_id, records=None: list(questions),
    )

    def _slow_adjudicate(_team_id, *, question_id):
        visited.append(question_id)
        # 50ms per question: after the first one the 1ms budget is always
        # exhausted, deterministically, without relying on wall-clock flake.
        time.sleep(0.05)
        return {"status": "skipped"}

    monkeypatch.setattr(chain, "auto_adjudicate_exhausted_round", _slow_adjudicate)

    first = chain.sweep_auto_advance_closure()

    assert first["questions"] == 1
    assert first["budgetExhausted"] is True
    assert first["questionsDeferred"] == 2
    assert visited == ["SCI-A"]

    second = chain.sweep_auto_advance_closure()

    # The stop cursor resumed at SCI-B instead of restarting from SCI-A.
    assert second["questions"] == 1
    assert second["budgetExhausted"] is True
    assert second["questionsDeferred"] == 1
    assert visited == ["SCI-A", "SCI-B"]


# ---------------------------------------------------------------------------
# handed-off claim-ref repair: a handed_off request whose served candidates
# still miss the collected candidate-dimension evidence (SCI-085: the core
# claim row was proposed ref-less at selection, the handoff-time Phase 2
# proposal collided with the ledger's content binding) gets the idempotent
# chain claim bridge re-run once by the sweep


_REPAIR_CANDIDATE_ID = "sci-096-cRepair"


def _seed_repair_request() -> None:
    _seed_zombie_handoff_request(status="handed_off")
    chain._update_collection_request(
        _TEAM_ID,
        _ZOMBIE_REQUEST_ID,
        hypothesisCandidateIds=[_REPAIR_CANDIDATE_ID],
    )


def _fake_claim_bridge(
    monkeypatch: pytest.MonkeyPatch, calls: list[str], *, result: dict[str, Any]
) -> None:
    def _bridge(_team_id, request):
        calls.append(str(request.get("requestId") or ""))
        return dict(result)

    monkeypatch.setattr(
        chain, "_materialize_request_collection_claims", _bridge
    )


def test_auto_repair_heals_handed_off_claim_refs_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SCI-085 恢复：handed_off 请求的候选维度证据缺失 → 幂等重跑桥一次，
    写 claimRefsRepairAt 标记；第二遍跳过，不重复触发。"""
    events = _chain_env(tmp_path, monkeypatch)
    _seed_repair_request()
    calls: list[str] = []
    _fake_claim_bridge(
        monkeypatch,
        calls,
        result={"status": "materialized", "evidenceRefsAttached": 2},
    )

    summary = chain.auto_repair_handed_off_claim_refs(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["status"] == "repaired"
    assert summary["repaired"] == 1
    assert summary["failed"] == 0
    assert calls == [_ZOMBIE_REQUEST_ID]
    repaired = _latest_request()
    assert repaired["claimRefsRepairAt"]

    # One-shot per request: the marker keeps later sweep passes write-free.
    second = chain.auto_repair_handed_off_claim_refs(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert second["repaired"] == 0
    assert second["skipped"] == 1
    assert calls == [_ZOMBIE_REQUEST_ID]

    repaired_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_repair_claim_refs"
    ]
    assert repaired_events and repaired_events[-1]["outcome"] == "repaired"


def test_auto_repair_skips_requests_already_covered_by_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ served 候选已有该 collection run 的候选维度证据行 → 检测为已覆盖，
    不再触发桥。"""
    from core.research.evidence import ClaimEvidenceStore

    _chain_env(tmp_path, monkeypatch)
    _seed_repair_request()
    store = ClaimEvidenceStore(tmp_path)
    store.register(
        _TEAM_ID,
        {
            "claimId": "claim-covered-1",
            "candidateId": _REPAIR_CANDIDATE_ID,
            "sourceId": "https://example.org/covered",
            "sourceRevision": "sha256:" + "b" * 64,
            "locator": {"kind": "url", "url": "https://example.org/covered"},
            "quote": "Covered collected excerpt.",
            "evidenceKind": "primary_result",
            "reasoningRole": "fact",
            "supportLevel": "supports",
            "extractionMethod": "manual",
            "extractorAgentId": "collector",
            "modelRef": "",
            "sourceCollectionRunId": _ZOMBIE_RUN_ID,
        },
    )
    calls: list[str] = []
    _fake_claim_bridge(monkeypatch, calls, result={"status": "materialized"})

    summary = chain.auto_repair_handed_off_claim_refs(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["status"] == "skipped"
    assert summary["repaired"] == 0
    assert calls == []


def test_auto_repair_retries_failed_materialization_without_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """桥重跑失败（status=failed）→ 不写标记、计 failed，下一遍仍会重试。"""
    events = _chain_env(tmp_path, monkeypatch)
    _seed_repair_request()
    calls: list[str] = []
    _fake_claim_bridge(
        monkeypatch,
        calls,
        result={"status": "failed", "error": "ledger unavailable"},
    )

    summary = chain.auto_repair_handed_off_claim_refs(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["status"] == "failed"
    assert summary["failed"] == 1
    assert calls == [_ZOMBIE_REQUEST_ID]
    assert not _latest_request().get("claimRefsRepairAt")

    # A later pass retries the unmarked request.
    chain.auto_repair_handed_off_claim_refs(_TEAM_ID, question_id=_QUESTION_ID)
    assert calls == [_ZOMBIE_REQUEST_ID, _ZOMBIE_REQUEST_ID]
    failed_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_repair_claim_refs"
    ]
    assert failed_events and failed_events[-1]["outcome"] == "failed"


# ---------------------------------------------------------------------------
# formal lineage auto-heal: the maintenance sweep archives the stale CANCELLED
# leaf behind a ``formal_run_lineage_conflict`` (the manual 「归档分支」 escape
# hatch the frontend often never surfaces)


def _leaf_run(
    run_id: str,
    status: str,
    *,
    updated_at_ms: int,
    parent_run_id: str | None = None,
    run_version: int = 5,
    question_id: str = _QUESTION_ID,
) -> RunRecord:
    from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
    from core.research.workflow.ledger.records import RunRecord

    return RunRecord(
        run_id=run_id,
        team_id=_TEAM_ID,
        workflow_id=CHALLENGE_CUP_WORKFLOW_ID,
        workflow_version_id="wf-v1",
        thread_id=f"thread-{run_id}",
        project_id="proj-1",
        question_id=question_id,
        status=status,
        run_version=run_version,
        last_event_sequence=1,
        input_snapshot_json="{}",
        input_snapshot_hash="hash",
        safety_limits_json="{}",
        binding_snapshot_set_id="bs-1",
        active_node_id=None,
        parent_run_id=parent_run_id,
        forked_from_checkpoint_id=None,
        completion_kind=None,
        terminal_reason=None,
        blocked_problem_json=None,
        created_at_ms=updated_at_ms - 1_000,
        updated_at_ms=updated_at_ms,
        completed_at_ms=None,
    )


class _HealStore:
    def __init__(self, runs: list[RunRecord]) -> None:
        self._runs = runs

    def list_runs_for_team(
        self, team_id: str, workflow_id: str
    ) -> list[RunRecord]:
        return [run for run in self._runs if run.team_id == team_id]

    def get_run(self, run_id: str) -> RunRecord | None:
        return next(
            (run for run in self._runs if run.run_id == run_id), None
        )


class _HealCommandService:
    def __init__(self, fail_run_ids: set[str] | None = None) -> None:
        self.requests: list[Any] = []
        self._fail_run_ids = fail_run_ids or set()

    def submit(self, request: Any) -> Any:
        self.requests.append(request)
        if request.run_id in self._fail_run_ids:
            raise RuntimeError("ledger exploded")
        return SimpleNamespace(status="accepted", run_id=request.run_id)


class _HealRuntime:
    def __init__(
        self,
        store: _HealStore,
        command_service: _HealCommandService,
    ) -> None:
        self.store = store
        self.command_service = command_service


def _heal_env(
    monkeypatch: pytest.MonkeyPatch,
    runs: list[RunRecord],
    *,
    fail_run_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], _HealRuntime]:
    """Fake runtime + captured scene events; teams enumerated without disk."""
    runtime = _HealRuntime(_HealStore(runs), _HealCommandService(fail_run_ids))
    monkeypatch.setattr(chain, "_team_ids_with_chain_storage", lambda: [_TEAM_ID])
    monkeypatch.setattr(
        runtime_factory, "production_workflow_runtime", lambda: runtime
    )
    events: list[dict[str, Any]] = []

    def _capture(
        event_code: str,
        *,
        outcome: str,
        fields: dict[str, Any] | None = None,
        level: str = "info",
    ) -> None:
        events.append(
            {
                "code": event_code,
                "outcome": outcome,
                "fields": dict(fields or {}),
                "level": level,
            }
        )

    monkeypatch.setattr(chain, "_record_scene_event", _capture)
    monkeypatch.setattr(heal, "_record_scene_event", _capture)
    return events, runtime


def _archive_run_ids(submitted: list[Any]) -> list[str]:
    return [request.run_id for request in submitted]


def test_sweep_archives_only_older_cancelled_leaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两条 leaf：旧 CANCELLED + 新 SUCCEEDED → 只归档旧 cancelled leaf；
    有 child 的 parent 不是 leaf，非 cancelled 的 stale leaf 不碰。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    events, runtime = _heal_env(
        monkeypatch,
        [
            # The cancelled stale leaf is the older one (updatedAt first).
            _leaf_run("run-stale-cancelled", "cancelled", updated_at_ms=1_000),
            _leaf_run("run-current", "succeeded", updated_at_ms=9_000),
            # A branched parent is never a leaf candidate; its child leaf is
            # stale but SUCCEEDED — operator-review territory, not touched.
            _leaf_run("run-parent", "failed", updated_at_ms=500),
            _leaf_run(
                "run-child",
                "succeeded",
                updated_at_ms=600,
                parent_run_id="run-parent",
            ),
        ],
    )

    summary = heal.sweep_archive_stale_formal_leaves()

    assert _archive_run_ids(runtime.command_service.requests) == [
        "run-stale-cancelled"
    ]
    request = runtime.command_service.requests[0]
    assert request.command.value == "archive_run"
    assert request.team_id == _TEAM_ID
    assert request.idempotency_key == (
        "hf2:sweep-archive-stale-leaf:run-stale-cancelled"
    )
    assert request.payload == {"reason": "auto-heal formal run lineage conflict"}
    assert request.expected_run_version == 5
    assert summary["conflicts"] == 1
    assert summary["archived"] == 1
    assert summary["failed"] == 0
    submitted_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.stale_leaf_auto_archive"
    ]
    assert len(submitted_events) == 1
    assert submitted_events[0]["outcome"] == "accepted"
    assert submitted_events[0]["fields"]["runId"] == "run-stale-cancelled"
    assert submitted_events[0]["fields"]["currentRunId"] == "run-current"


def test_sweep_never_archives_newest_cancelled_or_non_cancelled_leaves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两条 leaf 都非 cancelled（blocked/running）→ 冲突照记但零命令；
    cancelled 若是最新 leaf（current revision）同样不碰。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _events, runtime = _heal_env(
        monkeypatch,
        [
            # Conflict A: both leaves non-cancelled.
            _leaf_run("run-blocked", "blocked", updated_at_ms=1_000),
            _leaf_run("run-running", "running", updated_at_ms=2_000),
            # Conflict B (another question): the NEWEST leaf is CANCELLED —
            # the current revision is never auto-archived, and the stale one
            # is blocked, not cancelled, so nothing is submitted at all.
            _leaf_run(
                "run-old-blocked",
                "blocked",
                updated_at_ms=3_000,
                question_id="SCI-097",
            ),
            _leaf_run(
                "run-new-cancelled",
                "cancelled",
                updated_at_ms=9_000,
                question_id="SCI-097",
            ),
        ],
    )

    summary = heal.sweep_archive_stale_formal_leaves()

    assert runtime.command_service.requests == []
    assert summary["conflicts"] == 2
    assert summary["archived"] == 0
    assert summary["skipped"] == 2  # run-blocked + run-old-blocked


def test_sweep_ignores_already_archived_old_leaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧 leaf 已 archived → 投影口径下不构成 leaf，无冲突、零命令。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _events, runtime = _heal_env(
        monkeypatch,
        [
            _leaf_run("run-archived-old", "archived", updated_at_ms=1_000),
            _leaf_run("run-current", "succeeded", updated_at_ms=9_000),
        ],
    )

    summary = heal.sweep_archive_stale_formal_leaves()

    assert runtime.command_service.requests == []
    assert summary["conflicts"] == 0
    assert summary["archived"] == 0


def test_sweep_caps_archives_per_pass_and_survives_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认 ≤3 次/pass：4 条 cancelled 旧 leaf 只归档最旧 3 条；submit 抛错
    计 failed 不外抛，剩余预算照常处理后续 leaf。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    runs = [
        _leaf_run("run-stale-1", "cancelled", updated_at_ms=1_000),
        _leaf_run("run-stale-2", "cancelled", updated_at_ms=2_000),
        _leaf_run("run-stale-3", "cancelled", updated_at_ms=3_000),
        _leaf_run("run-stale-4", "cancelled", updated_at_ms=4_000),
        _leaf_run("run-current", "running", updated_at_ms=9_000),
    ]
    commands = _HealCommandService(fail_run_ids={"run-stale-2"})
    monkeypatch.setattr(chain, "_team_ids_with_chain_storage", lambda: [_TEAM_ID])
    monkeypatch.setattr(
        runtime_factory,
        "production_workflow_runtime",
        lambda: _HealRuntime(_HealStore(runs), commands),
    )
    monkeypatch.setattr(chain, "_record_scene_event", lambda *a, **kw: None)

    summary = heal.sweep_archive_stale_formal_leaves()

    # Oldest first: 1 accepted, 2 failed, 3 accepted → budget spent; 4 skipped.
    assert _archive_run_ids(commands.requests) == [
        "run-stale-1",
        "run-stale-2",
        "run-stale-3",
    ]
    assert summary["archived"] == 2
    assert summary["failed"] == 1
    assert summary["skipped"] == 1

    # An explicit smaller bound is honoured too.
    commands2 = _HealCommandService()
    monkeypatch.setattr(
        runtime_factory,
        "production_workflow_runtime",
        lambda: _HealRuntime(_HealStore(runs), commands2),
    )
    summary = heal.sweep_archive_stale_formal_leaves(limit=1)
    assert _archive_run_ids(commands2.requests) == ["run-stale-1"]
    assert summary["archived"] == 1
    assert summary["skipped"] == 3


def test_maintenance_tick_hosts_stale_leaf_archive_sweep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_maintenance_once 承载 sweep；sweep 抛错被吞掉，不破坏维护循环。"""
    _sweep_env(tmp_path, monkeypatch)
    calls: list[dict[str, Any]] = []
    state = {"boom": True}

    def _sweep() -> dict[str, Any]:
        calls.append({})
        if state["boom"]:
            raise RuntimeError("sweep exploded")
        return {"archived": 1, "failed": 0}

    monkeypatch.setattr(heal, "sweep_archive_stale_formal_leaves", _sweep)
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "ledger-checkpoints.sqlite",
    )
    try:
        runtime.run_maintenance_once(limit=2)
        assert len(calls) == 1  # raised but the loop survived
        state["boom"] = False
        runtime.run_maintenance_once(limit=2)
        assert len(calls) == 2
    finally:
        runtime.close()
