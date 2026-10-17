# -*- coding: utf-8 -*-
"""失败审查规划师（stage failure planner）第二层回路回归。

生产实弹（session-20261017-203847-419417）：relations 代理被确定性拒绝后
blocked 举手提问，答案就在它读过的上下文里；L1 的确定性补救契约只覆盖系统
可本地 diff 的拒绝，没有人审查失败现场并给补救指令，闭环率低。

回归契约：
- blocked（最新 attempt，含 retry 后仍 blocked）+ 宽限窗外的任务触发一次
  LLM 规划；同一条 retry 链只一次：链上任一旧 attempt 的任务带指令/升级
  痕迹即整链跳过（链级防重入，上溯最多 5 步、防环、任务解析失败视为无痕迹）；
- actionable retry_task → ``plannerDirective`` 落正典任务记录、上下文注入
  ``context["plannerDirective"]``、一次幂等 RETRY_NODE（重复 sweep 不二次
  提交）；completed 合规回写清除指令；
- escalate_human → 冻结 taxonomy code ``stage_task_planner_escalation`` 的
  异常收件箱 item 落任务 ``anomalyEscalation``；
- LLM 无凭证 / 非法输出 → 不重试不升级只记有界事件（fail-open，含进程内
  冷却）；
- rerun_source_finding → 只落指令不提交重试。

Sweep 侧走真实 Ledger runtime + CommandService（仿 quote-anchor 恢复测试），
LLM 以注入的假规划师替代；上下文注入/清除走公开编排服务行为。
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.research.workflow.definition_registry import register_or_resolve
from core.research.workflow.knowledge_sideflow_definition import (
    KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
    build_knowledge_sideflow_workflow_definition,
)
from tests._support.workflow_ledger_helpers import (
    build_attempt_record,
    build_command_record,
    build_run_record,
)

TEAM_ID = "research-team"
NODE_ID = "evidence_relations"
NODE_RUN_ID = "nr-run-planner-evidence_relations-a1"
A2_NODE_RUN_ID = "nr-run-planner-evidence_relations-a2"
SOURCE_RUN_ID = "source-planner"
OLD_UPDATED_AT = "2026-01-01T00:00:00+00:00"

_RETRY_TASK_VERDICT = {
    "actionable": True,
    "recommendation": "retry_task",
    "directive": "把 candidateRelations[0].evidenceRefs 的 dprec-1 替换为 ce-good-alpha 后重新回写 completed。",
    "targetFix": {"field": "candidateRelations[0].evidenceRefs[0]", "expectation": "ce-good-alpha"},
    "justification": "答案在代理已读的 relationEvidence 绑定卡里，属引用映射错误。",
}
_ESCALATE_VERDICT = {
    "actionable": False,
    "recommendation": "escalate_human",
    "directive": "两次系统补救已耗尽且证据权威缺失，需要人工决定重试或放弃。",
    "targetFix": {},
    "justification": "allowedEvidenceRefs 为空，任何自动重试都会再次 blocked。",
}
_RERUN_FINDING_VERDICT = {
    "actionable": True,
    "recommendation": "rerun_source_finding",
    "directive": "现有候选缺少独立基线与反证来源，需补充检索后重跑资料搜集。",
    "targetFix": {"missingPerspectives": ["independent_baseline", "falsification"]},
    "justification": "证据面不足，不是回写格式问题。",
}


@pytest.fixture(autouse=True)
def _isolated_registry():
    from core.research.workflow.definition_registry import reset_registry_for_tests

    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


@pytest.fixture(autouse=True)
def _reset_planner_state():
    from core.web.services.team_workflow.research_runtime import (
        stage_failure_planner,
    )
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        reset_stage_planner_sweep_throttle_for_tests,
    )

    stage_failure_planner.reset_stage_failure_planner_fail_open_for_tests()
    reset_stage_planner_sweep_throttle_for_tests()
    yield
    stage_failure_planner.reset_stage_failure_planner_fail_open_for_tests()
    reset_stage_planner_sweep_throttle_for_tests()


def _base_task(**overrides) -> dict:
    task = {
        "taskId": "stage-task-planner-1",
        "stageId": "relations",
        "status": "blocked",
        "agentRole": "source_relation_mapper",
        "sessionId": "session-planner",
        "updatedAt": OLD_UPDATED_AT,
        "writeback": {
            "status": "blocked",
            "summary": "关系图因 evidence_relation_graph_invalid 被拒绝两次，任务 blocked。",
            "agentRequestedStatus": "blocked",
        },
        "writebackRemediationContract": {
            "schemaVersion": 1,
            "kind": "relation_refs",
            "findings": [
                {"finding": "non_canonical_ref", "path": "candidateRelations[0].evidenceRefs[0]", "value": "dprec-1"}
            ],
            "attempt": 2,
            "exhausted": True,
        },
    }
    task.update(overrides)
    return task


class _SweepHarness:
    """Real Ledger runtime + fake stage-task store + injected planner.

    ``chain_attempts`` seeds a retry chain instead of the default single
    attempt: a list of ``(node_run_id, retry_of_node_run_id)`` tuples whose
    ordinals are 1..N (latest = last entry).  ``cycle_back_edge`` re-points
    one seeded attempt's ``retry_of`` via raw SQL so a cyclic chain can be
    fixture-built despite the FK insert order.  ``chain_tasks`` overrides
    task resolution per node_run_id (dict → task record, BaseException →
    resolver raises), anything else falls back to the latest task record.
    """

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        task: dict,
        chain_attempts: list[tuple[str, str | None]] | None = None,
        chain_tasks: dict[str, dict | BaseException] | None = None,
        cycle_back_edge: tuple[str, str] | None = None,
    ) -> None:
        from core.web.services.team_workflow.research_runtime.runtime_factory import (
            build_workflow_runtime,
        )

        identity = register_or_resolve(build_knowledge_sideflow_workflow_definition())
        ledger_path = tmp_path / "ledger.sqlite3"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime = build_workflow_runtime(
            ledger_path,
            checkpoint_path=tmp_path / "checkpoints.sqlite3",
        )
        self.task_state: dict[str, dict] = {"task": dict(task)}
        self.upsert_calls: list[dict] = []
        self.planner_scenes: list[dict] = []
        self.task_lookups: list[str] = []
        self.chain_tasks: dict[str, dict | BaseException] = dict(chain_tasks or {})
        self.latest_node_run_id: str = ""
        self.child = replace(
            build_run_record(
                run_id="run-planner",
                workflow_id=KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
                workflow_version_id=identity.workflowVersionId,
                status="blocked",
                team_id=TEAM_ID,
            ),
            active_node_id=NODE_ID,
            blocked_problem_json=json.dumps(
                {"code": "evidence_relation_graph_invalid", "detail": "non-canonical refs"}
            ),
            input_snapshot_json=json.dumps(
                {"snapshotHash": "b" * 64, "sourceCollectionRunId": SOURCE_RUN_ID}
            ),
            structure_hash=identity.structureHash,
        )
        entries = list(chain_attempts or [(NODE_RUN_ID, None)])
        self.latest_node_run_id = entries[-1][0]
        self.attempt = None  # first seeded attempt record (single-attempt seam)

        def seed(uow) -> None:
            uow.repository.insert_run(self.child)
            for index, (node_run_id, retry_of) in enumerate(entries, start=1):
                attempt = replace(
                    build_attempt_record(
                        node_run_id=node_run_id,
                        run_id=self.child.run_id,
                        node_id=NODE_ID,
                        attempt=index,
                        status="blocked",
                        command_id=f"cmd-planner-a{index}",
                        problem_json=json.dumps(
                            {"code": "evidence_relation_graph_invalid"}
                        ),
                    ),
                    finished_at_ms=1_750_000_000_001,
                    retry_of_node_run_id=retry_of,
                )
                if index == 1:
                    self.attempt = attempt
                uow.repository.insert_command(
                    build_command_record(
                        command_id=attempt.command_id,
                        run_id=self.child.run_id,
                        node_id=NODE_ID,
                        idempotency_key=f"planner-a{index}",
                    )
                )
                uow.repository.insert_attempt(attempt)
            if cycle_back_edge is not None:
                uow.repository.execute(
                    "UPDATE node_attempts SET retry_of_node_run_id = ? "
                    "WHERE node_run_id = ?",
                    (cycle_back_edge[1], cycle_back_edge[0]),
                )

        self.runtime.store.submit(seed, force_flush=True).result(timeout=10)

        # Fake canonical stage-task store: per-node_run overrides (record or
        # raise), fallback returns the latest upserted record so the
        # once-only guard stays observable across sweeps.
        from core.web.services.team_workflow.research_runtime import (
            stage_task_remediation,
        )

        def task_for_node_run(*, team_id, source_run_id, node_run_id):
            assert (team_id, source_run_id) == (TEAM_ID, SOURCE_RUN_ID)
            self.task_lookups.append(str(node_run_id))
            override = self.chain_tasks.get(str(node_run_id))
            if isinstance(override, BaseException):
                raise override
            if isinstance(override, dict):
                return dict(override)
            return dict(self.task_state["task"])

        monkeypatch.setattr(
            stage_task_remediation,
            "source_stage_task_for_node_run",
            task_for_node_run,
        )

        from core.web.services import team_workflow_orchestration_service

        def fake_upsert(team_id: str, run_id: str, task: dict) -> dict:
            self.upsert_calls.append(dict(task))
            self.task_state["task"] = dict(task)
            return task

        monkeypatch.setattr(
            team_workflow_orchestration_service,
            "_upsert_source_collection_stage_session_task",
            fake_upsert,
        )

        # Bounded scene assembly degrades to deterministic stubs (no project
        # root on the sweep path).
        from core.web.services.team_workflow.research_runtime import (
            artifact_readback_registry as registry,
        )
        from core.web.services.team_workflow.source_collection import candidates

        monkeypatch.setattr(
            registry, "load_allowed_evidence_refs", lambda **_: ["ce-good-alpha"]
        )
        monkeypatch.setattr(
            registry,
            "load_relation_evidence_context",
            lambda **_: [
                {
                    "claimEvidenceId": "ce-good-alpha",
                    "candidateId": "cand-a",
                    "sourceId": "src-a",
                    "quote": "Independent replication under stricter control.",
                    "supportLevel": "supports",
                }
            ],
        )
        monkeypatch.setattr(
            candidates,
            "list_candidate_store",
            lambda *args, **kwargs: {"candidateCount": 2},
        )

        monkeypatch.setattr(
            self.runtime.readiness,
            "evaluate",
            lambda **_kwargs: SimpleNamespace(ready=True, blockers=()),
        )

    def plan(self, planner):
        from core.web.services.team_workflow.research_runtime.stage_failure_planner import (
            plan_stage_task_failure_remediation,
        )

        return plan_stage_task_failure_remediation(
            self.runtime.store,
            self.runtime.command_service,
            limit=1,
            planner=planner,
        )

    def close(self) -> None:
        self.runtime.close()


def _verdict_planner(verdict: dict, *, calls: list | None = None):
    def planner(scene: dict) -> dict:
        if calls is not None:
            calls.append(dict(scene))
        return dict(verdict)

    return planner


def _maintenance_plan(runtime, monkeypatch, *, planner) -> dict:
    """Drive the sweep through the runtime maintenance wrapper (throttled)."""
    from core.web.services.team_workflow.research_runtime import (
        stage_failure_planner as planner_module,
    )
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        reset_stage_planner_sweep_throttle_for_tests,
    )

    if planner is None:
        monkeypatch.setattr(
            "core.web.services.team_workflow.llm_review_runners.build_failure_review_planner",
            lambda llm=None: None,
        )
    else:
        monkeypatch.setattr(
            "core.web.services.team_workflow.llm_review_runners.build_failure_review_planner",
            lambda llm=None: planner,
        )
    reset_stage_planner_sweep_throttle_for_tests()
    runtime._plan_stage_task_failure_remediation_best_effort(limit=4)
    return {}


def test_first_blocked_task_planned_once_via_task_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(a) 首次 blocked+宽限窗外触发规划师且同任务只一次。

    Verdict 用 escalate_human（不提交重试），使「同任务只一次」直接落在任务
    层守卫（anomalyEscalation 持久化后不再规划）；retry 链级的防重入由下方
    chain 用例覆盖。
    """
    harness = _SweepHarness(tmp_path, monkeypatch, task=_base_task())
    try:
        calls: list[dict] = []
        first = harness.plan(_verdict_planner(_ESCALATE_VERDICT, calls=calls))
        assert first["escalated"] == 1
        assert len(calls) == 1
        scene = calls[0]
        assert scene["taskId"] == "stage-task-planner-1"
        assert scene["allowedEvidenceRefs"] == ["ce-good-alpha"]
        assert scene["relationEvidenceCardCount"] == 1
        assert scene["candidateCount"] == 2
        assert scene["summary"].startswith("关系图因")

        second = harness.plan(_verdict_planner(_ESCALATE_VERDICT, calls=calls))
        assert second["escalated"] == 0
        assert second["skipped"] == 1
        assert len(calls) == 1, "task carrying anomalyEscalation must not be re-planned"
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# Retry-chain candidate semantics: chain-level planner-trace exclusion
# ---------------------------------------------------------------------------


def _chain_marker(marker: str) -> dict:
    """Non-empty plannerDirective / anomalyEscalation stamp for chain nodes."""

    if marker == "plannerDirective":
        return {
            "schemaVersion": 1,
            "recommendation": "retry_task",
            "directive": "替换引用后重新回写 completed。",
            "targetFix": {},
            "justification": "上一次规划已给出修复指令。",
            "recordedAt": OLD_UPDATED_AT,
            "runId": "run-planner",
            "nodeId": NODE_ID,
            "nodeRunId": NODE_RUN_ID,
        }
    return {
        "status": "emitted",
        "taxonomyCode": "stage_task_planner_escalation",
        "taskId": "stage-task-planner-a1",
        "stageId": "relations",
        "runId": "run-planner",
        "nodeId": NODE_ID,
        "nodeRunId": NODE_RUN_ID,
        "sourceCollectionRunId": SOURCE_RUN_ID,
        "emittedAt": OLD_UPDATED_AT,
        "items": [],
    }


def test_blocked_retry_attempt_without_chain_trace_is_planned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归 run-cd671f3d5dc7：retry 后仍 blocked 的最新 attempt 是候选。

    旧的 attempt 级排除（最新 attempt retry_of 非空即跳过）把 a2 全部过滤，
    实弹里 evidence_relations 最新 attempt blocked 且 retry_of=a1，7 分钟无人
    裁决；链级语义下 a1 无介入痕迹 → a2 走完整规划并提交重试。
    """
    harness = _SweepHarness(
        tmp_path,
        monkeypatch,
        task=_base_task(),
        chain_attempts=[(NODE_RUN_ID, None), (A2_NODE_RUN_ID, NODE_RUN_ID)],
    )
    try:
        calls: list[dict] = []
        summary = harness.plan(_verdict_planner(_RETRY_TASK_VERDICT, calls=calls))
        assert (summary["planned"], summary["retried"]) == (1, 1)
        assert len(calls) == 1
        directive = harness.task_state["task"]["plannerDirective"]
        assert directive["nodeRunId"] == A2_NODE_RUN_ID
        # 链级防重入：痕迹已落在链上任务记录里，同一条链不再二次规划。
        second = harness.plan(_verdict_planner(_RETRY_TASK_VERDICT, calls=calls))
        assert second["planned"] == 0
        assert len(calls) == 1
    finally:
        harness.close()


@pytest.mark.parametrize("marker", ["plannerDirective", "anomalyEscalation"])
def test_retry_chain_with_planner_marker_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    """链上旧 attempt 的任务已带介入痕迹 → 整条链跳过（skipped 计数）。"""
    ancestor_task = _base_task(taskId="stage-task-planner-a1")
    ancestor_task[marker] = _chain_marker(marker)
    harness = _SweepHarness(
        tmp_path / marker,
        monkeypatch,
        task=_base_task(),
        chain_attempts=[(NODE_RUN_ID, None), (A2_NODE_RUN_ID, NODE_RUN_ID)],
        chain_tasks={NODE_RUN_ID: ancestor_task},
    )
    try:
        calls: list[dict] = []
        summary = harness.plan(_verdict_planner(_RETRY_TASK_VERDICT, calls=calls))
        assert summary == {
            "scanned": 1,
            "planned": 0,
            "retried": 0,
            "escalated": 0,
            "degraded": 0,
            "skipped": 1,
        }
        assert calls == []
        assert harness.upsert_calls == []
    finally:
        harness.close()


def test_cyclic_retry_chain_terminates_without_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """a2→a1→a2 环形 retry 链：防环截断，按无痕迹处理，有限时间出裁决。"""
    harness = _SweepHarness(
        tmp_path,
        monkeypatch,
        task=_base_task(),
        chain_attempts=[(NODE_RUN_ID, None), (A2_NODE_RUN_ID, NODE_RUN_ID)],
        cycle_back_edge=(NODE_RUN_ID, A2_NODE_RUN_ID),
    )
    try:
        calls: list[dict] = []
        summary = harness.plan(_verdict_planner(_ESCALATE_VERDICT, calls=calls))
        assert summary["escalated"] == 1
        assert len(calls) == 1
    finally:
        harness.close()


def test_retry_chain_walk_truncated_at_five_hops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """链长超过 5 步：截断安全——第 6 跳上的痕迹不可见，按无痕迹规划。"""
    entries: list[tuple[str, str | None]] = [(NODE_RUN_ID, None)]
    for index in range(2, 8):
        entries.append((f"nr-run-planner-evidence_relations-a{index}", entries[-1][0]))
    deepest_task = _base_task(taskId="stage-task-planner-a1")
    deepest_task["plannerDirective"] = _chain_marker("plannerDirective")
    harness = _SweepHarness(
        tmp_path,
        monkeypatch,
        task=_base_task(),
        chain_attempts=entries,
        chain_tasks={NODE_RUN_ID: deepest_task},
    )
    try:
        calls: list[dict] = []
        summary = harness.plan(_verdict_planner(_ESCALATE_VERDICT, calls=calls))
        assert summary["escalated"] == 1
        # 上溯只走最近 5 跳（a6..a2）：主循环解析最新 a7 一次 + 5 跳祖先，
        # 最深一跳 a1 的任务从未被查询。
        assert len(harness.task_lookups) == 6
        assert NODE_RUN_ID not in harness.task_lookups
    finally:
        harness.close()


def test_chain_task_lookup_error_swallowed_and_walk_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """链上任务解析抛异常：吞掉继续上溯，更深一跳的介入痕迹仍被发现。"""
    deepest_task = _base_task(taskId="stage-task-planner-a1")
    deepest_task["plannerDirective"] = _chain_marker("plannerDirective")
    a3_node_run_id = "nr-run-planner-evidence_relations-a3"
    harness = _SweepHarness(
        tmp_path,
        monkeypatch,
        task=_base_task(),
        chain_attempts=[
            (NODE_RUN_ID, None),
            (A2_NODE_RUN_ID, NODE_RUN_ID),
            (a3_node_run_id, A2_NODE_RUN_ID),
        ],
        chain_tasks={
            A2_NODE_RUN_ID: RuntimeError("stage session store unreadable"),
            NODE_RUN_ID: deepest_task,
        },
    )
    try:
        calls: list[dict] = []
        summary = harness.plan(_verdict_planner(_RETRY_TASK_VERDICT, calls=calls))
        assert summary["skipped"] == 1
        assert summary["planned"] == 0
        assert calls == []
    finally:
        harness.close()


def test_recent_update_and_active_turn_stay_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(a-2) 宽限窗内的活跃任务不触发规划师。"""
    from datetime import datetime, timezone

    fresh = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    for overrides in (
        {"updatedAt": fresh},
        {"turn": {"status": "running"}},
        {"status": "completed"},
    ):
        harness = _SweepHarness(
            tmp_path / _slug(overrides), monkeypatch, task=_base_task(**overrides)
        )
        try:
            calls: list[dict] = []
            summary = harness.plan(_verdict_planner(_RETRY_TASK_VERDICT, calls=calls))
            assert summary["planned"] == 0
            assert calls == []
            assert harness.upsert_calls == []
        finally:
            harness.close()


def _slug(overrides: dict) -> str:
    key = next(iter(overrides))
    return key.replace("[", "").replace("]", "")


def test_actionable_retry_task_lands_directive_and_one_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(b) actionable retry_task → 指令落任务 + RETRY_NODE 一次。"""
    from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
        canonical_sha256,
    )

    harness = _SweepHarness(tmp_path, monkeypatch, task=_base_task())
    try:
        calls: list[dict] = []
        summary = harness.plan(_verdict_planner(_RETRY_TASK_VERDICT, calls=calls))
        assert (summary["planned"], summary["retried"]) == (1, 1)
        stored = harness.task_state["task"]
        directive = stored["plannerDirective"]
        assert directive["schemaVersion"] == 1
        assert directive["recommendation"] == "retry_task"
        assert directive["directive"] == _RETRY_TASK_VERDICT["directive"]
        assert directive["targetFix"] == _RETRY_TASK_VERDICT["targetFix"]
        assert directive["runId"] == "run-planner"
        assert directive["nodeId"] == NODE_ID
        assert directive["nodeRunId"] == NODE_RUN_ID
        assert directive["recordedAt"]

        latest = harness.runtime.store.latest_attempt("run-planner", NODE_ID)
        assert latest is not None
        assert latest.attempt == 2
        assert latest.retry_of_node_run_id == NODE_RUN_ID

        # 重复 sweep：任务已带指令，不二次提交（幂等键 replay 收敛同一结果）。
        reset = harness.plan(_verdict_planner(_RETRY_TASK_VERDICT, calls=calls))
        assert reset["planned"] == 0
        latest_again = harness.runtime.store.latest_attempt("run-planner", NODE_ID)
        assert latest_again.attempt == 2

        identity_hash = canonical_sha256(
            {
                "runId": "run-planner",
                "nodeId": NODE_ID,
                "nodeRunId": NODE_RUN_ID,
                "reason": "stage_failure_planner",
            }
        )
        idempotency_key = f"stage-failure-planner:{identity_hash}"
        command = harness.runtime.store.read(
            lambda repo: repo.find_command_by_idempotency("run-planner", idempotency_key)
        )
        assert command is not None
        assert "stage-failure-planner" in str(command.requested_by_json or "")
        assert command.node_id == NODE_ID
    finally:
        harness.close()


@pytest.mark.parametrize("skip_reason", ["planned", "active", "recent", "cooldown", "completed", "retry_pending"])
def test_ineligible_first_run_does_not_starve_later_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skip_reason: str
) -> None:
    from datetime import datetime, timezone
    from core.web.services.team_workflow.research_runtime import (
        stage_failure_planner as planner_module,
        stage_task_remediation,
    )

    harness = _SweepHarness(tmp_path, monkeypatch, task=_base_task())
    try:
        first_run = replace(harness.child, run_id="run-z-skipped", thread_id="thread-skipped", created_at_ms=harness.child.created_at_ms + 1)
        first_attempt = replace(harness.attempt, run_id=first_run.run_id, node_run_id="nr-skipped", command_id="cmd-skipped")
        harness.runtime.store.submit(
            lambda uow: (
                uow.repository.insert_run(first_run),
                uow.repository.insert_command(build_command_record(command_id="cmd-skipped", run_id=first_run.run_id, node_id=NODE_ID, idempotency_key="skipped")),
                uow.repository.insert_attempt(first_attempt),
            ),
            force_flush=True,
        ).result(timeout=10)
        first_task = _base_task(taskId="task-skipped")
        if skip_reason == "planned":
            first_task["plannerDirective"] = {"recommendation": "rerun_source_finding"}
        elif skip_reason == "active":
            first_task["turn"] = {"status": "running"}
        elif skip_reason == "recent":
            first_task["updatedAt"] = datetime.now(timezone.utc).isoformat()
        elif skip_reason == "completed":
            first_task["status"] = "completed"
        elif skip_reason == "retry_pending":
            first_task["plannerDirective"] = {
                "recommendation": "retry_task", "runId": first_run.run_id,
                "nodeId": NODE_ID, "nodeRunId": first_attempt.node_run_id,
            }
            monkeypatch.setattr(harness.runtime.command_service, "submit", lambda _: (_ for _ in ()).throw(RuntimeError("still unavailable")))
        else:
            planner_module._mark_fail_open(first_run.run_id, first_attempt.node_run_id, now_ms=int(datetime.now(timezone.utc).timestamp() * 1000))
        monkeypatch.setattr(stage_task_remediation, "source_stage_task_for_node_run", lambda **kwargs: dict(first_task if kwargs["node_run_id"] == "nr-skipped" else harness.task_state["task"]))
        calls: list[dict] = []
        summary = harness.plan(_verdict_planner(_ESCALATE_VERDICT, calls=calls))
        assert summary["escalated"] == 1
        assert [scene["taskId"] for scene in calls] == ["stage-task-planner-1"]
        assert harness.plan(_verdict_planner(_ESCALATE_VERDICT, calls=calls))["escalated"] == 0
        assert len(calls) == 1
    finally:
        harness.close()


@pytest.mark.parametrize("interruption", ["submit_failure", "version_race", "restart", "receipt_lost"])
def test_persisted_retry_recovers_without_replanning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interruption: str
) -> None:
    from core.web.services.team_workflow.research_runtime.runtime_factory import build_workflow_runtime

    harness = _SweepHarness(tmp_path, monkeypatch, task=_base_task())
    calls: list[dict] = []
    requests = []
    original_submit = harness.runtime.command_service.submit

    def interrupted_submit(request):
        requests.append(request)
        if interruption == "restart":
            raise SystemExit("process stopped after directive persistence")
        if interruption == "version_race":
            harness.runtime.store.submit(
                lambda uow: uow.repository.bump_run_version("run-planner", TEAM_ID, request.expected_run_version, 0, request.requested_at_ms),
                force_flush=True,
            ).result(timeout=10)
            return original_submit(request)  # real optimistic version refusal
        if interruption == "receipt_lost":
            original_submit(request)
        raise RuntimeError("retry transport interrupted")

    monkeypatch.setattr(harness.runtime.command_service, "submit", interrupted_submit)
    try:
        planner = _verdict_planner(_RETRY_TASK_VERDICT, calls=calls)
        if interruption == "restart":
            with pytest.raises(SystemExit):
                harness.plan(planner)
            harness.runtime.close()
            harness.runtime = build_workflow_runtime(tmp_path / "ledger.sqlite3", checkpoint_path=tmp_path / "checkpoints.sqlite3")
            monkeypatch.setattr(harness.runtime.readiness, "evaluate", lambda **_: SimpleNamespace(ready=True, blockers=()))
        else:
            harness.plan(planner)
            monkeypatch.setattr(harness.runtime.command_service, "submit", original_submit)
        persisted = dict(harness.task_state["task"]["plannerDirective"])
        summary = harness.plan(planner)
        assert summary["retried"] == (0 if interruption == "receipt_lost" else 1)
        latest = harness.runtime.store.latest_attempt("run-planner", NODE_ID)
        assert latest.attempt == 2 and latest.retry_of_node_run_id == NODE_RUN_ID
        assert len(calls) == 1
        assert harness.task_state["task"]["plannerDirective"] == persisted
        assert harness.plan(planner)["retried"] == 0
        assert harness.runtime.store.latest_attempt("run-planner", NODE_ID).attempt == 2
        assert len(calls) == 1
        assert len(harness.upsert_calls) == 1
        command = harness.runtime.store.get_command_by_idempotency("run-planner", requests[0].idempotency_key)
        assert command is not None
    finally:
        harness.close()


@pytest.mark.parametrize("change", ["new_attempt", "active_node", "running"])
def test_retry_submission_rechecks_fresh_run_and_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from core.web.services.team_workflow.research_runtime.stage_failure_planner import _submit_planner_retry

    harness = _SweepHarness(tmp_path, monkeypatch, task=_base_task())
    try:
        def advance(uow):
            repo = uow.repository
            repo.bump_run_version("run-planner", TEAM_ID, harness.child.run_version, 0, 1_800_000_000_000)
            if change == "new_attempt":
                repo.insert_attempt(replace(harness.attempt, node_run_id="nr-newer", attempt=2))
            else:
                repo.update_run_status(
                    "run-planner", TEAM_ID, "running" if change == "running" else "blocked",
                    1_800_000_000_000, active_node_id="other-node" if change == "active_node" else NODE_ID,
                )

        harness.runtime.store.submit(advance, force_flush=True).result(timeout=10)
        before = harness.runtime.store.get_run("run-planner")
        submitted = []
        monkeypatch.setattr(harness.runtime.command_service, "submit", submitted.append)
        assert not _submit_planner_retry(
            store=harness.runtime.store, command_service=harness.runtime.command_service,
            run=harness.child, attempt=harness.attempt, node_id=NODE_ID, now_ms=1_800_000_000_001,
        )
        assert submitted == []
        assert harness.runtime.store.get_run("run-planner") == before
        assert harness.runtime.store.latest_attempt("run-planner", NODE_ID).attempt == (2 if change == "new_attempt" else 1)
    finally:
        harness.close()


@pytest.mark.parametrize("field,value", [("runId", "other-run"), ("nodeId", "other-node"), ("nodeRunId", "older-attempt")])
def test_mismatched_retry_directive_is_not_replanned_or_submitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    directive = {"recommendation": "retry_task", "runId": "run-planner", "nodeId": NODE_ID, "nodeRunId": NODE_RUN_ID, field: value}
    harness = _SweepHarness(tmp_path, monkeypatch, task=_base_task(plannerDirective=directive))
    try:
        calls: list[dict] = []
        summary = harness.plan(_verdict_planner(_RETRY_TASK_VERDICT, calls=calls))
        assert (summary["planned"], summary["retried"]) == (0, 0)
        assert calls == [] and harness.upsert_calls == []
        assert harness.runtime.store.latest_attempt("run-planner", NODE_ID).attempt == 1
    finally:
        harness.close()


def test_escalate_human_lands_anomaly_escalation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(c) escalate_human → 异常收件箱 item 落任务 anomalyEscalation。"""
    harness = _SweepHarness(tmp_path, monkeypatch, task=_base_task())
    try:
        summary = harness.plan(_verdict_planner(_ESCALATE_VERDICT))
        assert summary["escalated"] == 1
        assert summary["planned"] == 0
        escalation = harness.task_state["task"]["anomalyEscalation"]
        assert escalation["status"] == "emitted"
        assert escalation["taxonomyCode"] == "stage_task_planner_escalation"
        assert escalation["runId"] == "run-planner"
        assert escalation["nodeRunId"] == NODE_RUN_ID
        items = escalation["items"]
        assert items and items[0]["kind"] == "blocked_run"
        assert items[0]["recommendedAction"] == "retry_node"
        assert "stage_task_planner_escalation" in items[0]["evidence"][0]
        # 升级后同任务不再规划。
        calls: list[dict] = []
        again = harness.plan(_verdict_planner(_ESCALATE_VERDICT, calls=calls))
        assert again["skipped"] == 1
        assert calls == []
        assert harness.runtime.store.latest_attempt("run-planner", NODE_ID).attempt == 1
    finally:
        harness.close()


@pytest.mark.parametrize("mode", ["llm_unavailable", "invalid_verdict"])
def test_fail_open_no_retry_no_escalation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """(d) LLM 无凭证/非法输出 → 不重试不升级只记事件。"""
    from core.research.workflow.contracts import ContractValidationError

    harness = _SweepHarness(tmp_path, monkeypatch, task=_base_task())
    try:
        if mode == "llm_unavailable":
            planner = None
        else:
            def planner(scene: dict) -> dict:
                raise ContractValidationError("bad verdict")

        from core.web.services.team_workflow.research_runtime.stage_failure_planner import (
            plan_stage_task_failure_remediation,
        )

        summary = plan_stage_task_failure_remediation(
            harness.runtime.store,
            harness.runtime.command_service,
            limit=1,
            planner=planner,
        )
        assert summary["degraded"] == 1
        assert summary["planned"] == 0
        assert summary["escalated"] == 0
        task = harness.task_state["task"]
        assert "plannerDirective" not in task
        assert "anomalyEscalation" not in task
        assert harness.upsert_calls == []
        assert harness.runtime.store.latest_attempt("run-planner", NODE_ID).attempt == 1

        # 进程内冷却：紧接着的第二趟不再把同一任务送进规划师。
        probe_calls: list[dict] = []

        def probe(scene: dict) -> dict:
            probe_calls.append(dict(scene))
            return dict(_RETRY_TASK_VERDICT)

        summary2 = plan_stage_task_failure_remediation(
            harness.runtime.store,
            harness.runtime.command_service,
            limit=1,
            planner=probe,
        )
        assert summary2["skipped"] == 1
        assert probe_calls == []
    finally:
        harness.close()


def test_rerun_source_finding_directive_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(e) rerun_source_finding → 只落指令不提交重试。"""
    from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
        canonical_sha256,
    )

    harness = _SweepHarness(tmp_path, monkeypatch, task=_base_task())
    try:
        summary = harness.plan(_verdict_planner(_RERUN_FINDING_VERDICT))
        assert (summary["planned"], summary["retried"]) == (1, 0)
        directive = harness.task_state["task"]["plannerDirective"]
        assert directive["recommendation"] == "rerun_source_finding"
        assert harness.runtime.store.latest_attempt("run-planner", NODE_ID).attempt == 1
        command = harness.runtime.store.read(
            lambda repo: repo.find_command_by_idempotency(
                "run-planner",
                "stage-failure-planner:"
                + canonical_sha256(
                    {
                        "runId": "run-planner",
                        "nodeId": NODE_ID,
                        "nodeRunId": NODE_RUN_ID,
                        "reason": "stage_failure_planner",
                    }
                ),
            )
        )
        assert command is None
    finally:
        harness.close()


def test_maintenance_wrapper_throttles_to_one_pass_per_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_maintenance_once 挂载 + 节流：同一间隔内第二趟不进规划师。"""
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        reset_stage_planner_sweep_throttle_for_tests,
    )

    harness = _SweepHarness(tmp_path, monkeypatch, task=_base_task())
    try:
        calls: list[dict] = []
        _maintenance_plan(harness.runtime, monkeypatch, planner=_verdict_planner(_RETRY_TASK_VERDICT, calls=calls))
        assert len(calls) == 1
        # 不重置节流：第二趟维护循环不再调用规划师。
        harness.runtime._plan_stage_task_failure_remediation_best_effort(limit=4)
        assert len(calls) == 1
        reset_stage_planner_sweep_throttle_for_tests()
        harness.runtime._plan_stage_task_failure_remediation_best_effort(limit=4)
        # 任务已带指令，重置节流后也只是跳过。
        assert len(calls) == 1
    finally:
        harness.close()


def test_planner_verdict_contract_rejects_contradictions() -> None:
    """规划师输出契约：矛盾判定按非法输出处理。"""
    from core.research.workflow.contracts import ContractValidationError
    from core.web.services.team_workflow.llm_review_runners import (
        _validate_stage_failure_planning_payload,
    )

    assert _validate_stage_failure_planning_payload(_RETRY_TASK_VERDICT)[
        "recommendation"
    ] == "retry_task"
    with pytest.raises(ContractValidationError):
        _validate_stage_failure_planning_payload(
            {**_RETRY_TASK_VERDICT, "actionable": False}
        )
    with pytest.raises(ContractValidationError):
        _validate_stage_failure_planning_payload(
            {**_ESCALATE_VERDICT, "actionable": True}
        )
    with pytest.raises(ContractValidationError):
        _validate_stage_failure_planning_payload(
            {**_RETRY_TASK_VERDICT, "recommendation": "do_nothing"}
        )
    with pytest.raises(ContractValidationError):
        _validate_stage_failure_planning_payload(
            {**_RETRY_TASK_VERDICT, "targetFix": ["not-an-object"]}
        )


# ---------------------------------------------------------------------------
# Context injection / consumption through the public orchestration service
# ---------------------------------------------------------------------------


def _start_relations_stage_task(tmp_path, monkeypatch):
    from core.web.services import (
        agent_directory_service,
        session_service,
        team_service,
        team_workflow_orchestration_service,
    )
    from tests._support.team_workflow.helpers import (
        _seed_source_collection_raw_records,
        _start_source_collection_run_with_problem_understanding,
        _use_fake_local_research_config,
        _use_tmp_project_root,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="规划师回归")
    session_service.ensure_agent_direct_session(
        agent_id=agent["agentId"], title="失败审查规划师回归"
    )
    team = team_service.create_team(
        name="失败审查规划师回归团队",
        members=[
            {
                "agentId": agent["agentId"],
                "role": "source_relation_mapper",
                "agentName": "规划师回归",
            }
        ],
    )
    run_response = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "失败审查规划师回归",
            "agentRoles": ["source_relation_mapper"],
            "agentIds": {"source_relation_mapper": agent["agentId"]},
            "querySeeds": ["stage failure planner"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    for index in (1, 2):
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Planner regression candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/planner-{index}",
                "sourceKind": "paper",
                "summary": f"Planner regression candidate {index} summary.",
                "allowedForAnalysis": True,
                "metadata": {
                    "sourceCollectionRunId": run_id,
                    "doi": f"10.0000/planner-{index}",
                },
                "createdByAgent": "planner-fixture",
            },
        )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-failure-planner",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {
            "stageId": "relations",
            "agentId": agent["agentId"],
            "agentRole": "source_relation_mapper",
        },
    )
    return {"teamId": team["teamId"], "runId": run_id, "task": task}


def _stub_relations_acceptance(monkeypatch) -> None:
    from core.web.services.team_workflow.research_runtime import (
        artifact_readback_registry as registry,
    )
    from core.web.services.team_workflow.source_collection import stage_writeback

    graph = {
        "nodes": [{"candidateId": "cand-a"}, {"candidateId": "cand-b"}],
        "edges": [
            {
                "sourceCandidateId": "cand-a",
                "targetCandidateId": "cand-b",
                "relation": "supports",
                "evidenceRefs": ["ce-good-alpha"],
            }
        ],
        "evidenceGaps": [{"description": "Independent replication missing"}],
        "counterEvidenceRefs": [
            {"evidenceRef": "ce-good-beta", "claim": "Null result under stricter control"}
        ],
    }
    monkeypatch.setattr(registry, "_load_scoped_relation_graph", lambda **_: graph)
    monkeypatch.setattr(
        registry, "load_allowed_evidence_refs", lambda **_: ["ce-good-alpha", "ce-good-beta"]
    )
    monkeypatch.setattr(registry, "load_relation_evidence_context", lambda **_: [])
    s = stage_writeback._service()
    monkeypatch.setattr(
        s,
        "_source_collection_stage_writeback_candidate_coverage",
        lambda *_a, **_kw: {},
    )
    for name in (
        "sources",
        "content_extraction",
        "quality",
        "candidate_graph",
        "knowledge_ingestion",
    ):
        monkeypatch.setattr(
            s, "_materialize_source_collection_stage_writeback_" + name, lambda *_a, **_kw: {}
        )
    monkeypatch.setattr(
        s,
        "_source_collection_stage_writeback_closure_summary",
        lambda *_a, **_kw: {"artifactComplete": True, "taskChecklistComplete": True},
    )
    monkeypatch.setattr(
        s, "_source_collection_stage_completion_gate", lambda **_: {"passed": True}
    )


def test_context_injects_unconsumed_directive_and_completed_writeback_clears_it(
    tmp_path, monkeypatch
) -> None:
    """(b-上下文) 未消费指令注入 context；completed 合规回写清除。"""
    from core.web.services import team_workflow_orchestration_service

    setup = _start_relations_stage_task(tmp_path, monkeypatch)
    _stub_relations_acceptance(monkeypatch)
    task_id = setup["task"]["taskId"]

    stored, run_id = (
        team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
            setup["teamId"], task_id
        )
    )
    assert stored is not None and run_id == setup["runId"]
    stored["plannerDirective"] = {
        "schemaVersion": 1,
        "recommendation": "retry_task",
        "directive": "把 evidenceRefs 替换为 ce-good-alpha 后重新回写 completed。",
        "targetFix": {"field": "candidateRelations[0].evidenceRefs[0]"},
        "justification": "引用映射错误。",
        "recordedAt": "2026-10-17T00:00:00+00:00",
        "runId": "run-planner",
        "nodeId": NODE_ID,
        "nodeRunId": NODE_RUN_ID,
    }
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        setup["teamId"], run_id, stored
    )

    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        setup["teamId"],
        run_id=run_id,
        task_id=task_id,
    )
    injected = context.get("plannerDirective")
    assert isinstance(injected, dict) and injected["recommendation"] == "retry_task"

    # completed 合规回写消费指令：同点清除，下一次上下文不再注入。
    team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task_id,
        {
            "status": "completed",
            "result": {
                "themeNodes": [{"themeId": "theme-x", "label": "主题 X"}],
                "candidateRelations": [
                    {
                        "sourceCandidateId": "cand-a",
                        "targetCandidateId": "cand-b",
                        "relation": "supports",
                        "evidenceRefs": ["ce-good-alpha"],
                    }
                ],
                "sourceThemeEdges": [],
                "topicRelations": [],
                "missingLinks": [],
                "evidenceGaps": [
                    {
                        "id": "gap-x",
                        "description": "缺少跨设备验证",
                        "neededEvidence": "多设备基准",
                        "blocksConclusion": True,
                    }
                ],
                "counterEvidenceRefs": [
                    {
                        "evidenceRef": "ce-good-beta",
                        "claim": "该结论受设备与负载边界限制",
                        "disposition": "limit_scope",
                    }
                ],
            },
        },
    )
    cleared, _ = (
        team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
            setup["teamId"], task_id
        )
    )
    assert "plannerDirective" not in cleared
    context_after = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        setup["teamId"],
        run_id=run_id,
        task_id=task_id,
    )
    assert "plannerDirective" not in context_after


def test_prompt_contract_carries_planner_directive_line() -> None:
    """规划师指令行进入全部既有阶段契约（未知阶段不追加）。"""
    from core.web.services.team_workflow.source_collection.stage_writeback_prompt_contracts import (
        stage_writeback_prompt_lines,
    )

    for stage_id in ("finding", "extraction", "relations", "ingestion"):
        prompt = "\n".join(stage_writeback_prompt_lines(stage_id))
        assert "plannerDirective" in prompt
        assert "rerun_source_finding" in prompt
        assert "重新回写 completed" in prompt
    assert stage_writeback_prompt_lines("unknown") == []
