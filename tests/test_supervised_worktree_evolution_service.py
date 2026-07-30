import json
import re
import subprocess
from pathlib import Path

import pytest

from core.infrastructure import developer_sandbox
from core.web.services import supervised_worktree_evolution_service as service
from scripts.evolution_harness import HarnessResult

pytestmark = pytest.mark.slow


def _run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "test@example.local")
    _run_git(repo, "config", "user.name", "Test User")


def _write_bundle(project_root: Path, name: str = "closed_loop_v1") -> None:
    payload = json.dumps(
        {
            "bundle_name": name,
            "benchmark": "unit",
            "cases": [
                {"case_id": "one", "prompt": "case one"},
                {"case_id": "two", "prompt": "case two"},
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    bundle_paths = {
        project_root / "workspace" / "evaluation" / "bundles" / f"{name}.json",
        developer_sandbox.seeded_sandbox_workspace_path(project_root, "evaluation", "bundles", f"{name}.json"),
    }
    for bundle_path in bundle_paths:
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(payload, encoding="utf-8")


def _fake_evaluator(_: Path, bundle_name: str, role: str, __: dict) -> dict:
    successes = 1 if role == "baseline" else 2
    return {
        "role": role,
        "status": "success",
        "score": successes * 50.0,
        "successes": successes,
        "total": 2,
        "failures": 2 - successes,
        "bundleName": bundle_name,
        "summary": f"{role} fake score",
    }


def _fake_harness_result(
    *,
    role: str,
    repo_root: Path,
    prompt: str,
    status: str = "success",
    session_id: str = "",
    agent_judgment: dict | None = None,
) -> HarnessResult:
    return HarnessResult(
        harness_id=f"h_{role}",
        status=status,
        reason=f"{role} ok" if status == "success" else f"{role} failed",
        started_at="2026-05-14T00:00:00Z",
        ended_at="2026-05-14T00:00:10Z",
        repo_root=str(repo_root),
        worktree_path=str(repo_root),
        base_head="abc123",
        checkpoint_commit="abc123",
        checkpoint_ref=None,
        tracked_dirty=False,
        untracked_files=[],
        command=["session_service.submit_session_message", "--prompt", prompt],
        returncode=0 if status == "success" else 1,
        timeout_seconds=60,
        restarts_observed=0,
        normalized_restarts_observed=0,
        restart_expected=False,
        restart_reentered=False,
        process_history=[],
        process_summary={"session_id": session_id} if session_id else {},
        new_conversation_files=[],
        new_debug_files=[],
        stdout_tail=[],
        stderr_tail=[],
        agent_realtime_tail=[],
        last_observation={},
        post_restart_observation={},
        evolution_summary={
            "validation": {"passed": 1 if status == "success" else 0, "failed": 0 if status == "success" else 1, "last": None},
            "transaction": {"opened": False, "closed": False, "status": None, "txn_id": None},
            "git": {"commit_detected": False, "commit_refs": []},
            "restart": {"expected": False, "triggered": False, "reentered": False},
            "guarded_tools": {"total": 0, "restart_guarded": 0},
            **({"agent_judgment": agent_judgment} if agent_judgment else {}),
        },
        agent_binding={"role": role},
    )


def test_harness_result_payload_includes_bounded_trace_evidence_for_judge(tmp_path):
    result = _fake_harness_result(
        role="baseline",
        repo_root=tmp_path,
        prompt="run baseline",
        session_id="session-baseline",
    )
    result.stdout_tail = ["analysis complete", "final answer"]
    result.evolution_summary.update(
        {
            "tool_sequence_tail": ["read_file_tool", "run_test_for_tool"],
            "tool_phase_sequence_tail": [
                "tool:read_file_tool:success",
                "tool:run_test_for_tool:success",
            ],
            "evidence": {"conversation_tool_events": 2},
        }
    )

    payload = service._harness_result_payload(result, case_id="one", role="baseline")

    assert payload["assistantOutput"] == "analysis complete final answer"
    assert payload["traceSummary"]["toolSequence"] == ["read_file_tool", "run_test_for_tool"]
    assert payload["traceSummary"]["validation"]["passed"] == 1
    assert payload["traceSummary"]["evidence"]["conversation_tool_events"] == 2


def test_real_judge_runner_retries_wrong_phase_in_same_session(tmp_path, monkeypatch):
    calls: list[dict] = []
    rubric_hash = "a" * 64
    rubric = {
        "rubricHash": rubric_hash,
        "taskCriteria": [
            {
                "id": "task_completion",
                "label": "Task completion",
                "description": "Complete the requested task.",
                "weight": 1.0,
            }
        ],
        "systemCriteria": [
            {
                "id": "evidence_verifiability",
                "label": "Evidence",
                "description": "Provide verifiable evidence.",
                "weight": 1.0,
            }
        ],
        "compositionWeights": {"taskSpecific": 0.7, "systemFixed": 0.3},
    }

    def fake_conversation_harness(**kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            judgment = {
                "phase": "rubric",
                "task_summary": "stale rubric response",
                "criteria": [
                    {
                        "id": "task_completion",
                        "label": "Task completion",
                        "description": "Complete the requested task.",
                        "weight": 1.0,
                    }
                ],
            }
        else:
            judgment = {
                "phase": "baseline",
                "recommendation": "REVISE",
                "rubric_hash": rubric_hash,
                "problems": ["missing evidence"],
                "improvement_instructions": ["add evidence"],
                "task_scores": {"task_completion": 0.6},
                "system_scores": {"evidence_verifiability": 0.5},
                "evidence_refs": ["case:one"],
            }
        return _fake_harness_result(
            role="judge",
            repo_root=tmp_path,
            prompt=str(kwargs.get("prompt") or ""),
            session_id="session-judge",
            agent_judgment=judgment,
        )

    monkeypatch.setattr(service, "run_supervised_conversation_harness", fake_conversation_harness)

    result = service._real_judge_runner(
        tmp_path,
        "closed_loop_v1",
        "baseline",
        {
            "runId": "swte-phase-retry",
            "options": {
                "agentBindings": {
                    "judge": {
                        "agentId": "agent-judge",
                        "role": "judge",
                    }
                }
            },
            "conversationSessionId": "session-judge",
            "taskContract": {"benchmark": "unit", "cases": [{"caseId": "one"}]},
            "rubric": rubric,
            "baselineEvaluation": {"status": "success", "cases": []},
        },
    )

    assert result["status"] == "success"
    assert result["phase"] == "baseline"
    assert result["conversationSessionId"] == "session-judge"
    assert len(calls) == 2
    assert calls[0]["conversation_session_id"] == "session-judge"
    assert calls[1]["conversation_session_id"] == "session-judge"
    assert "PHASE_CORRECTION_REQUIRED" in calls[1]["prompt"]
    assert "expected phase=baseline" in calls[1]["prompt"]


def test_real_candidate_modifier_retries_judgment_protocol_drift_in_same_session(tmp_path, monkeypatch):
    calls: list[dict] = []

    def fake_conversation_harness(**kwargs):
        calls.append(dict(kwargs))
        result = _fake_harness_result(
            role="baseline",
            repo_root=tmp_path,
            prompt=str(kwargs.get("prompt") or ""),
            session_id="session-baseline",
        )
        if len(calls) == 1:
            result.stdout_tail = [
                'SUPERVISED_AGENT_JUDGMENT: {"phase":"rubric","criteria":[]}'
            ]
            result.evolution_summary["agent_judgment"] = {
                "phase": "rubric",
                "criteria": [],
            }
        else:
            result.stdout_tail = ["Applied the supported candidate change and ran focused validation."]
        return result

    monkeypatch.setattr(service, "run_supervised_conversation_harness", fake_conversation_harness)

    result = service._real_candidate_modifier(
        tmp_path,
        "Implement the evidence-backed improvement in this candidate worktree.",
        {
            "runId": "swte-self-edit-phase-retry",
            "options": {
                "agentBindings": {
                    "baseline": {
                        "agentId": "agent-baseline",
                        "role": "baseline",
                    }
                }
            },
            "conversationSessionId": "session-baseline",
        },
    )

    assert result["status"] == "success"
    assert result["conversationSessionId"] == "session-baseline"
    assert result["phaseRetryCount"] == 1
    assert len(calls) == 2
    assert calls[0]["conversation_session_id"] == "session-baseline"
    assert calls[1]["conversation_session_id"] == "session-baseline"
    assert "SELF_EDIT_PHASE_CORRECTION_REQUIRED" in calls[1]["prompt"]
    assert "Do not output SUPERVISED_AGENT_JUDGMENT" in calls[1]["prompt"]


def _retryable_provider_failure_evaluator(_: Path, bundle_name: str, role: str, __: dict) -> dict:
    assert role == "baseline"
    return {
        "role": role,
        "status": "failed",
        "score": 0.0,
        "successes": 0,
        "total": 1,
        "failures": 1,
        "bundleName": bundle_name,
        "summary": "baseline score 0.0",
        "cases": [
            {
                "caseId": "provider-down",
                "status": "failed",
                "reason": "LLM provider 传输异常，未生成可评估输出；请稍后重试",
                "llmFailure": {
                    "detected": True,
                    "category": "provider_transport_error",
                    "retryable": True,
                    "message": "server_error: upstream request failed",
                },
            }
        ],
    }


def _retryable_provider_reason_evaluator(_: Path, bundle_name: str, role: str, __: dict) -> dict:
    assert role == "baseline"
    return {
        "role": role,
        "status": "failed",
        "score": 0.0,
        "successes": 0,
        "total": 1,
        "failures": 1,
        "bundleName": bundle_name,
        "summary": "baseline score 0.0",
        "cases": [
            {
                "caseId": "provider-down",
                "status": "failed",
                "reason": (
                    "server_error: litellm.ServiceUnavailableError: "
                    'OpenAIException - {"error":{"message":"Service temporarily unavailable","type":"api_error"}}'
                ),
                "llmFailure": {"detected": False},
            }
        ],
    }


def _retryable_provider_html_reason_evaluator(_: Path, bundle_name: str, role: str, __: dict) -> dict:
    result = _retryable_provider_reason_evaluator(_, bundle_name, role, __)
    result["cases"][0]["reason"] = (
        "provider_protocol_error: litellm.BadGatewayError: BadGatewayError: "
        "OpenAIException - <html><head><title>网站请求超时</title>"
        "<style>body{background-size:400% 400%}</style></head>"
        "<body><p>502</p><h1>回源请求被中断</h1></body></html>"
    )
    return result


def _make_candidate_repo(tmp_path: Path, project_root: Path, *, changed_path: str = "agent.py") -> Path:
    candidate = tmp_path / f"candidate-{changed_path.replace('/', '-')}"
    _init_repo(candidate)
    for source in project_root.rglob("*"):
        if not source.is_file():
            continue
        try:
            rel = source.relative_to(project_root)
        except ValueError:
            continue
        if ".git" in rel.parts:
            continue
        target = candidate / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    _run_git(candidate, "add", ".")
    _run_git(candidate, "commit", "-m", "base")
    target = candidate / changed_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(target.read_text(encoding="utf-8") + "\n# candidate edit\n", encoding="utf-8")
    return candidate


def _bound_candidate_worktree(
    candidate: Path,
    *,
    baseline_untracked: list[str] | None = None,
) -> dict:
    baseline_noise = list(baseline_untracked or [])
    checkpoint_commit = _run_git(candidate, "rev-parse", "HEAD")
    changed_files = service._candidate_changed_files(
        candidate,
        baseline_untracked=baseline_noise,
    )
    return {
        "path": str(candidate),
        "preserved": True,
        "checkpointCommit": checkpoint_commit,
        "untrackedFiles": baseline_noise,
        "variant": service._build_candidate_variant(
            candidate,
            checkpoint_commit=checkpoint_commit,
            changed_files=changed_files,
            baseline_untracked=baseline_noise,
        ),
    }


def test_active_baseline_keeps_future_approval_pending():
    snapshot = {
        "runId": "swte-live-baseline",
        "status": "running",
        "phase": "baseline",
        "latestMessage": "hidden conversation",
        "baseline": {},
        "candidate": {},
        "candidateModification": {},
        "decision": {},
    }

    workflow_steps = service._build_workflow_steps(snapshot)

    assert workflow_steps[0]["status"] == "running"
    assert workflow_steps[0]["current"] is True
    assert workflow_steps[3]["status"] == "pending"
    assert workflow_steps[3]["current"] is False


def test_task_contract_uses_the_same_baseline_prompt_that_the_agent_executes():
    contract = service._build_task_contract(
        {
            "benchmark": "unit",
            "cases": [
                {
                    "case_id": "baseline-only",
                    "baseline_prompt": "执行真实基线任务",
                    "prompt": "不得替代真实基线任务的旧字段",
                }
            ],
        },
        bundle_name="baseline_contract_v1",
        self_origin={},
    )

    assert contract["cases"] == [
        {
            "caseId": "baseline-only",
            "prompt": "执行真实基线任务",
        }
    ]


def test_full_score_reflection_does_not_invent_a_failure_target():
    reflection = service._build_reflection(
        {},
        {
            "successes": 1,
            "total": 1,
            "failures": 0,
            "summary": "baseline score 100.0",
        },
    )

    assert reflection["summary"] == "基线 1/1 通过；候选只在有可信边界改进时修改。"
    assert "同一题集复测时比基线分数更高" not in reflection["selfModificationPrompt"]
    assert "如果没有可信改进，保守地不做无依据改动" in reflection["selfModificationPrompt"]


def test_supervised_worktree_flow_preserves_improved_candidate_and_records_merge_analysis(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")

    def worktree_factory(root: Path, run_id: str) -> dict:
        candidate = _make_candidate_repo(tmp_path, root)
        return {
            "path": str(candidate),
            "baseHead": "base",
            "checkpointCommit": "base",
            "checkpointRef": "",
            "trackedDirty": False,
            "untrackedFiles": [],
        }

    def modifier(worktree_path: Path, _: str, __: dict) -> dict:
        _run_git(worktree_path, "status", "--porcelain")
        return {"status": "success", "summary": "candidate edited agent.py"}

    snapshot = service.run_supervised_worktree_flow(
        {"sourceKind": "bundle", "bundleName": "closed_loop_v1", "mode": "auto"},
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=_fake_evaluator,
            candidate_modifier=modifier,
            worktree_factory=worktree_factory,
        ),
    )

    assert snapshot["status"] == "done"
    assert snapshot["outcome"] == "awaiting_user_approval"
    assert snapshot["decision"]["scoreDelta"] == 40.0
    assert snapshot["decision"]["recommendedAction"] == "user_decision"
    assert set(snapshot["baselineJudgment"]["taskScores"]) == {
        item["id"] for item in snapshot["judgeRubric"]["taskCriteria"]
    }
    assert set(snapshot["candidateJudgment"]["systemScores"]) == {
        item["id"] for item in snapshot["judgeRubric"]["systemCriteria"]
    }
    assert snapshot["mergeAnalysis"]["status"] == "blocked"
    assert snapshot["mergeAnalysis"]["mergeAllowed"] is False
    assert "supervised_review_pending" in snapshot["mergeAnalysis"]["blockers"]
    assert snapshot["mergeAnalysis"]["changedFiles"][0]["path"] == "agent.py"


def test_supervised_worktree_flow_projects_six_steps_with_independent_rerun_session(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    evaluator_calls: list[dict[str, object]] = []

    def worktree_factory(root: Path, run_id: str) -> dict:
        candidate = _make_candidate_repo(tmp_path, root)
        return {
            "path": str(candidate),
            "baseHead": "base",
            "checkpointCommit": "base",
            "checkpointRef": "",
            "trackedDirty": False,
            "untrackedFiles": [],
        }

    def evaluator(_: Path, bundle_name: str, role: str, context: dict) -> dict:
        evaluator_calls.append({"role": role, "session": context.get("conversationSessionId")})
        assert context.get("conversationSessionId") == ""
        successes = 1 if role == "baseline" else 2
        return {
            "role": role,
            "status": "success",
            "executionScore": successes * 50.0,
            "successes": successes,
            "total": 2,
            "failures": 2 - successes,
            "bundleName": bundle_name,
            "summary": f"{role} fake score",
            "conversationSessionId": "session-improver" if role == "baseline" else "session-rerun",
        }

    def modifier(worktree_path: Path, _: str, __: dict) -> dict:
        marker = worktree_path / "agent.py"
        marker.write_text(marker.read_text(encoding="utf-8") + "\n# candidate edit\n", encoding="utf-8")
        return {
            "status": "success",
            "summary": "candidate improved the worktree",
            "conversationSummary": {
                "conversation_backend": {
                    "enabled": True,
                    "session_id": "session-improver",
                    "observed_active_turn_id": "turn-improve",
                }
            },
        }

    snapshot = service.run_supervised_worktree_flow(
        {"sourceKind": "bundle", "bundleName": "closed_loop_v1", "mode": "auto"},
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=evaluator,
            candidate_modifier=modifier,
            worktree_factory=worktree_factory,
        ),
    )

    assert [item["id"] for item in snapshot["workflowSteps"]] == [
        "baseline_eval",
        "baseline_judge",
        "improve",
        "rerun_eval",
        "rerun_judge",
        "approval",
    ]
    improve_step = snapshot["workflowSteps"][2]
    rerun_score_step = snapshot["workflowSteps"][3]
    approval_step = snapshot["workflowSteps"][5]
    assert improve_step["label"] == "基线自改"
    assert rerun_score_step["label"] == "独立复跑"
    assert improve_step["conversationSessionId"] == "session-improver"
    assert rerun_score_step["conversationSessionId"] == "session-rerun"
    assert improve_step["chatRoute"].endswith("session=session-improver")
    assert rerun_score_step["chatRoute"].endswith("session=session-rerun")
    assert approval_step["label"] == "用户审批与合入"
    assert approval_step["ownerKind"] == "human"
    assert approval_step["conversationSessionId"] == ""
    assert approval_step["metrics"]["scoreDelta"] == 40.0
    assert evaluator_calls[1]["session"] == ""


def test_supervised_worktree_flow_uses_three_sessions_and_same_judge_session(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    calls: list[tuple[str, str, str]] = []
    scene_events: list[tuple[str, str, str, dict]] = []

    def record_scene_event(component, phase, event_code, **kwargs):
        scene_events.append((component, phase, event_code, kwargs))

    monkeypatch.setattr(service, "record_runtime_scene_event", record_scene_event)

    def worktree_factory(root: Path, run_id: str) -> dict:
        candidate = _make_candidate_repo(tmp_path, root)
        return {
            "path": str(candidate),
            "baseHead": "base",
            "checkpointCommit": "base",
            "checkpointRef": "",
            "trackedDirty": False,
            "untrackedFiles": [],
        }

    def evaluator(_: Path, bundle_name: str, role: str, context: dict) -> dict:
        session_id = str(context.get("conversationSessionId") or "")
        calls.append(("evaluate", role, session_id))
        if role == "baseline":
            assert session_id == ""
            resolved_session = "session-baseline"
            successes = 1
        else:
            assert role == "baseline_rerun"
            assert session_id == ""
            resolved_session = "session-rerun"
            successes = 2
        return {
            "role": role,
            "status": "success",
            "executionScore": successes * 50.0,
            "successes": successes,
            "total": 2,
            "failures": 2 - successes,
            "bundleName": bundle_name,
            "summary": f"{role} execution result",
            "conversationSessionId": resolved_session,
            "cases": [{"caseId": "one", "status": "success"}],
        }

    def judge(_: Path, __: str, phase: str, context: dict) -> dict:
        session_id = str(context.get("conversationSessionId") or "")
        calls.append(("judge", phase, session_id))
        if phase == "rubric":
            assert session_id == ""
            assert context["taskContract"]["cases"][0]["prompt"] == "case one"
            assert "baselineEvaluation" not in context
            rubric = service.normalize_judge_rubric(
                {
                    "phase": "rubric",
                    "task_summary": "完成题集并提供可信运行证据",
                    "criteria": [
                        {
                            "id": "task_completion",
                            "label": "任务完成度",
                            "description": "完成题集要求。",
                            "weight": 0.7,
                            "evidence_requirements": ["case trace"],
                        },
                        {
                            "id": "task_quality",
                            "label": "任务质量",
                            "description": "任务结果满足题目约束。",
                            "weight": 0.3,
                            "evidence_requirements": ["case result"],
                        },
                    ],
                },
                task_contract=context["taskContract"],
            )
            return {
                **rubric,
                "conversationSessionId": "session-judge",
            }
        if phase == "baseline":
            assert session_id == "session-judge"
            assert context["rubric"]["rubricHash"]
            return {
                "status": "success",
                "phase": "baseline",
                "recommendation": "REVISE",
                "decision": "REVISE",
                "score": 40.0,
                "rubricHash": context["rubric"]["rubricHash"],
                "problems": ["缺少失败恢复"],
                "improvementInstructions": ["补充失败恢复"],
                "evidenceRefs": ["case:one"],
                "conversationSessionId": "session-judge",
            }
        assert session_id == "session-judge"
        assert context["rubric"]["rubricHash"]
        return {
            "status": "success",
            "phase": "rerun",
            "recommendation": "REJECT",
            "decision": "REJECT",
            "baselineScore": 40.0,
            "score": 85.0,
            "rubricHash": context["rubric"]["rubricHash"],
            "problems": [],
            "improvementInstructions": [],
            "evidenceRefs": ["case:one"],
            "conversationSessionId": "session-judge",
        }

    def modifier(worktree_path: Path, prompt: str, context: dict) -> dict:
        session_id = str(context.get("conversationSessionId") or "")
        calls.append(("modify", "baseline", session_id))
        assert session_id == "session-baseline"
        assert "缺少失败恢复" in prompt
        marker = worktree_path / "agent.py"
        marker.write_text(marker.read_text(encoding="utf-8") + "\n# improved by baseline\n", encoding="utf-8")
        return {
            "status": "success",
            "summary": "baseline Agent improved the worktree",
            "conversationSessionId": session_id,
        }

    snapshot = service.run_supervised_worktree_flow(
        {"sourceKind": "bundle", "bundleName": "closed_loop_v1", "mode": "manual"},
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=evaluator,
            judge_runner=judge,
            candidate_modifier=modifier,
            worktree_factory=worktree_factory,
        ),
    )

    assert calls == [
        ("evaluate", "baseline", ""),
        ("judge", "rubric", ""),
        ("judge", "baseline", "session-judge"),
        ("modify", "baseline", "session-baseline"),
        ("evaluate", "baseline_rerun", ""),
        ("judge", "rerun", "session-judge"),
    ]
    assert snapshot["baselineConversationSessionId"] == "session-baseline"
    assert snapshot["rerunConversationSessionId"] == "session-rerun"
    assert snapshot["judgeConversationSessionId"] == "session-judge"
    assert snapshot["baselineConversationSessionId"] != snapshot["rerunConversationSessionId"]
    assert snapshot["baselineJudgment"]["score"] == 40.0
    assert snapshot["candidateJudgment"]["score"] == 85.0
    assert snapshot["judgeRubric"]["rubricHash"]
    assert snapshot["baselineJudgment"]["rubricHash"] == snapshot["judgeRubric"]["rubricHash"]
    assert snapshot["candidateJudgment"]["rubricHash"] == snapshot["judgeRubric"]["rubricHash"]
    assert snapshot["decision"]["judgeRecommendation"] == "REJECT"
    assert snapshot["decision"]["recommendedAction"] == "user_decision"
    assert [item["id"] for item in snapshot["workflowSteps"]] == [
        "baseline_eval",
        "baseline_judge",
        "improve",
        "rerun_eval",
        "rerun_judge",
        "approval",
    ]
    assert snapshot["workflowSteps"][0]["conversationSessionId"] == "session-baseline"
    assert snapshot["workflowSteps"][1]["conversationSessionId"] == "session-judge"
    assert snapshot["workflowSteps"][2]["conversationSessionId"] == "session-baseline"
    assert snapshot["workflowSteps"][3]["conversationSessionId"] == "session-rerun"
    assert snapshot["workflowSteps"][4]["conversationSessionId"] == "session-judge"
    rubric_event = next(
        item for item in scene_events if item[2] == "supervised_worktree_run.judge_rubric_frozen"
    )
    assert rubric_event[1] == "judge_rubric"
    assert rubric_event[3]["outcome"] == "frozen"
    assert rubric_event[3]["fields"] == {
        "runId": snapshot["runId"],
        "rubricHash": snapshot["judgeRubric"]["rubricHash"],
        "taskCriterionCount": 2,
        "systemRubricVersion": snapshot["judgeRubric"]["systemRubricVersion"],
        "judgeConversationSessionId": "session-judge",
    }


def test_self_origin_worktree_flow_carries_goal_and_requires_review(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    captured_prompt: dict[str, str] = {}

    def worktree_factory(root: Path, run_id: str) -> dict:
        candidate = _make_candidate_repo(tmp_path, root)
        return {
            "path": str(candidate),
            "baseHead": "base",
            "checkpointCommit": "base",
            "checkpointRef": "",
            "trackedDirty": False,
            "untrackedFiles": [],
        }

    def modifier(_: Path, prompt: str, __: dict) -> dict:
        captured_prompt["value"] = prompt
        return {"status": "success", "summary": "candidate edited from self goal"}

    snapshot = service.run_supervised_worktree_flow(
        {
            "sourceKind": "bundle",
            "bundleName": "closed_loop_v1",
            "mode": "manual",
            "selfEvolutionGoal": "修复自进化候选回流并补测试",
            "selfEvolutionRiskReason": "goal_write_marker",
            "requiresSupervisedReview": True,
        },
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=_fake_evaluator,
            candidate_modifier=modifier,
            worktree_factory=worktree_factory,
        ),
    )

    assert "修复自进化候选回流并补测试" in captured_prompt["value"]
    assert snapshot["selfEvolutionOrigin"]["sourceTrack"] == "self_evolution"
    assert snapshot["reviewGate"]["required"] is True
    assert snapshot["reviewGate"]["status"] == "pending"
    assert snapshot["mergeAnalysis"]["mergeAllowed"] is False
    assert "supervised_review_pending" in snapshot["mergeAnalysis"]["blockers"]
    assert snapshot["actionStates"]["approveReview"]["enabled"] is True
    assert snapshot["actionStates"]["merge"]["enabled"] is False
    assert [item["id"] for item in snapshot["workflowSteps"]] == [
        "baseline_eval",
        "baseline_judge",
        "improve",
        "rerun_eval",
        "rerun_judge",
        "approval",
    ]
    self_step = snapshot["workflowSteps"][2]
    approval_step = snapshot["workflowSteps"][5]
    assert self_step["label"] == "基线自改"
    assert self_step["ownerKind"] == "agent"
    assert self_step["role"] == "baseline"
    assert approval_step["label"] == "用户审批与合入"
    assert approval_step["ownerKind"] == "human"
    assert approval_step["conversationSessionId"] == ""


def test_real_worktree_flow_uses_supervised_conversation_chain_for_candidate_branch(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    calls: list[dict] = []

    def worktree_factory(root: Path, run_id: str) -> dict:
        candidate = _make_candidate_repo(tmp_path, root)
        return {
            "path": str(candidate),
            "baseHead": "base",
            "checkpointCommit": "base",
            "checkpointRef": "",
            "trackedDirty": False,
            "untrackedFiles": [],
        }

    def fake_bindings() -> dict:
        return {
            "baseline": {"agentId": "agent-baseline", "role": "baseline", "workspacePath": "workspace/agents/baseline"},
            "candidate": {"agentId": "agent-candidate", "role": "candidate", "workspacePath": "workspace/agents/candidate"},
            "judge": {"agentId": "agent-judge", "role": "judge", "workspacePath": "workspace/agents/judge"},
        }

    def fake_conversation_harness(**kwargs):
        call = dict(kwargs)
        calls.append(call)
        role = str((kwargs.get("agent_binding") or {}).get("role") or "")
        repo_root = Path(kwargs["repo_root"])
        prompt = str(kwargs.get("prompt") or "")
        requested_session = str(kwargs.get("conversation_session_id") or "")
        agent_judgment = None
        if kwargs.get("scenario") == "candidate_self_improvement":
            (repo_root / "agent.py").write_text(
                (repo_root / "agent.py").read_text(encoding="utf-8") + "\n# improved by candidate\n",
                encoding="utf-8",
            )
            session_id = requested_session
        elif kwargs.get("scenario") == "supervised_judge_evaluation":
            session_id = requested_session or "session-judge"
            if '"phase":"rubric"' in prompt:
                agent_judgment = {
                    "phase": "rubric",
                    "task_summary": "complete the supervised bundle",
                    "criteria": [
                        {
                            "id": "task_completion",
                            "label": "Task completion",
                            "description": "Complete the requested task.",
                            "weight": 0.7,
                            "evidence_requirements": ["case result"],
                        },
                        {
                            "id": "task_quality",
                            "label": "Task quality",
                            "description": "Preserve task-specific correctness.",
                            "weight": 0.3,
                            "evidence_requirements": ["trace"],
                        },
                    ],
                }
            else:
                phase = "rerun" if '"phase":"rerun"' in prompt else "baseline"
                rubric_hash_match = re.search(r'"rubric_hash":"([a-f0-9]{64})"', prompt)
                assert rubric_hash_match is not None
                agent_judgment = {
                    "phase": phase,
                    "recommendation": "APPROVE" if phase == "rerun" else "REVISE",
                    "rubric_hash": rubric_hash_match.group(1),
                    "problems": [] if phase == "rerun" else ["improve validation"],
                    "improvement_instructions": [] if phase == "rerun" else ["run focused validation"],
                    "task_scores": {
                        "task_completion": 0.85 if phase == "rerun" else 0.4,
                        "task_quality": 0.85 if phase == "rerun" else 0.4,
                    },
                    "system_scores": {
                        "evidence_verifiability": 0.8,
                        "tool_transaction_discipline": 0.8,
                        "scope_and_safety": 0.8,
                        "recovery_and_state_consistency": 0.8,
                        "efficiency_and_minimality": 0.8,
                    },
                    "evidence_refs": ["case:one"],
                }
        else:
            session_id = requested_session or (
                "session-rerun" if repo_root != project_root else "session-baseline"
            )
        return _fake_harness_result(
            role=role or "baseline",
            repo_root=repo_root,
            prompt=prompt,
            session_id=session_id,
            agent_judgment=agent_judgment,
        )

    monkeypatch.setattr(service, "supervised_agent_bindings", fake_bindings)
    monkeypatch.setattr(service, "run_supervised_conversation_harness", fake_conversation_harness)

    snapshot = service.run_supervised_worktree_flow(
        {
            "sourceKind": "bundle",
            "bundleName": "closed_loop_v1",
            "mode": "manual",
            "executionMode": "real",
            "confirmRealLlmCost": True,
            "mentalModelMode": "enabled",
        },
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(worktree_factory=worktree_factory),
    )

    assert snapshot["status"] == "done"
    assert snapshot["candidateWorktree"]["path"]
    candidate_path = Path(snapshot["candidateWorktree"]["path"]).resolve()
    assert "# improved by candidate" in (candidate_path / "agent.py").read_text(encoding="utf-8")
    variant = snapshot["candidateWorktree"]["variant"]
    assert variant["bindingStatus"] == "verified"
    assert variant["checkpointCommit"] == "base"
    assert variant["variantId"].startswith("swte-variant-")
    assert len(variant["patchSha256"]) == 64
    assert variant["changedPaths"] == ["agent.py"]
    assert [str(call["agent_binding"]["role"]) for call in calls] == [
        "baseline",
        "baseline",
        "judge",
        "judge",
        "baseline",
        "baseline",
        "baseline",
        "judge",
    ]
    improvement_call = calls[4]
    assert improvement_call["scenario"] == "candidate_self_improvement"
    assert Path(improvement_call["repo_root"]).resolve() == candidate_path
    assert Path(improvement_call["workspace_override"]).resolve() == candidate_path
    candidate_eval_calls = calls[5:7]
    assert all(Path(call["repo_root"]).resolve() == candidate_path for call in candidate_eval_calls)
    assert all(Path(call["workspace_override"]).resolve() == candidate_path for call in candidate_eval_calls)
    assert snapshot["candidate"]["candidateVariant"] == variant
    assert snapshot["agentBindings"]["baseline"]["agentId"] == "agent-baseline"
    assert snapshot["baselineConversationSessionId"] == "session-baseline"
    assert snapshot["rerunConversationSessionId"] == "session-rerun"
    assert snapshot["judgeConversationSessionId"] == "session-judge"
    assert snapshot["mentalModelMode"] == "enabled"


def test_candidate_variant_changes_when_untracked_content_changes(tmp_path):
    candidate = tmp_path / "candidate"
    _init_repo(candidate)
    (candidate / "tracked.txt").write_text("base\n", encoding="utf-8")
    _run_git(candidate, "add", ".")
    _run_git(candidate, "commit", "-m", "base")
    (candidate / "candidate.txt").write_text("first\n", encoding="utf-8")
    changed_files = service._candidate_changed_files(candidate)

    first = service._build_candidate_variant(
        candidate,
        checkpoint_commit="checkpoint-a",
        changed_files=changed_files,
    )
    (candidate / "candidate.txt").write_text("second\n", encoding="utf-8")
    second = service._build_candidate_variant(
        candidate,
        checkpoint_commit="checkpoint-a",
        changed_files=changed_files,
    )

    assert first["patchSha256"] != second["patchSha256"]
    assert first["variantId"] != second["variantId"]


def test_candidate_variant_handles_unicode_untracked_path(tmp_path):
    candidate = tmp_path / "candidate"
    _init_repo(candidate)
    (candidate / "tracked.txt").write_text("base\n", encoding="utf-8")
    _run_git(candidate, "add", "tracked.txt")
    _run_git(candidate, "commit", "-m", "base")
    unicode_file = candidate / "挑战杯" / "README.md"
    unicode_file.parent.mkdir(parents=True)
    unicode_file.write_text("candidate evidence\n", encoding="utf-8")

    changed_files = service._candidate_changed_files(candidate)
    variant = service._build_candidate_variant(
        candidate,
        checkpoint_commit="checkpoint-unicode",
        changed_files=changed_files,
    )

    assert changed_files == [
        {
            "path": "挑战杯/README.md",
            "status": "??",
            "changeType": "added",
            "highRisk": False,
        }
    ]
    assert variant["bindingStatus"] == "verified"
    assert variant["changedPaths"] == ["挑战杯/README.md"]


def test_candidate_changed_files_handles_unicode_rename(tmp_path):
    candidate = tmp_path / "candidate"
    _init_repo(candidate)
    original = candidate / "旧名称.txt"
    original.write_text("base\n", encoding="utf-8")
    _run_git(candidate, "add", "旧名称.txt")
    _run_git(candidate, "commit", "-m", "base")
    _run_git(candidate, "mv", "旧名称.txt", "新名称.txt")

    assert service._candidate_changed_files(candidate) == [
        {
            "path": "新名称.txt",
            "status": "R",
            "changeType": "renamed",
            "highRisk": False,
        }
    ]


def test_decision_fails_closed_without_candidate_variant_binding():
    snapshot = {
        "baseline": {"score": 50},
        "candidate": {"score": 100},
        "candidateModification": {"status": "success", "summary": "done"},
        "candidateWorktree": {
            "changedFiles": [{"path": "agent.py", "status": "M", "highRisk": False}],
        },
    }

    decision = service._build_decision(snapshot, {"mode": "auto"})

    variant_gate = next(gate for gate in decision["gates"] if gate["name"] == "candidate_variant_bound")
    assert variant_gate["status"] == "fail"
    assert decision["recommendedAction"] == "user_decision"


def test_candidate_variant_gate_rejects_mismatched_variant_id():
    candidate_variant = {
        "bindingStatus": "verified",
        "variantId": "swte-variant-" + ("0" * 64),
        "checkpointCommit": "checkpoint-a",
        "patchSha256": "1" * 64,
        "changedFileCount": 1,
    }

    assert service._candidate_variant_is_bound(candidate_variant) is False


def test_supervised_worktree_flow_stops_when_baseline_provider_transport_fails(tmp_path):
    project_root = tmp_path / "project"
    _write_bundle(project_root)
    calls = {"modifier": 0, "worktree": 0}

    def modifier(*_: object) -> dict:
        calls["modifier"] += 1
        return {"status": "success"}

    def worktree_factory(*_: object) -> dict:
        calls["worktree"] += 1
        return {"path": str(tmp_path / "candidate")}

    snapshot = service.run_supervised_worktree_flow(
        {"sourceKind": "bundle", "bundleName": "closed_loop_v1", "mode": "manual"},
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=_retryable_provider_failure_evaluator,
            candidate_modifier=modifier,
            worktree_factory=worktree_factory,
        ),
    )

    assert snapshot["status"] == "failed"
    assert snapshot["phase"] == "baseline_unavailable"
    assert snapshot["outcome"] == "baseline_unavailable"
    assert snapshot["errorType"] == "ProviderTransportError"
    assert "upstream request failed" in snapshot["error"]
    assert snapshot["candidateWorktree"] == {}
    assert snapshot["candidateModification"] == {}
    assert snapshot["candidate"] == {}
    assert calls == {"modifier": 0, "worktree": 0}


def test_supervised_worktree_flow_stops_when_retryable_provider_failure_is_only_in_case_reason(tmp_path):
    project_root = tmp_path / "project"
    _write_bundle(project_root)
    calls = {"modifier": 0, "worktree": 0}

    def modifier(*_: object) -> dict:
        calls["modifier"] += 1
        return {"status": "success"}

    def worktree_factory(*_: object) -> dict:
        calls["worktree"] += 1
        return {"path": str(tmp_path / "candidate")}

    snapshot = service.run_supervised_worktree_flow(
        {"sourceKind": "bundle", "bundleName": "closed_loop_v1", "mode": "manual"},
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=_retryable_provider_reason_evaluator,
            candidate_modifier=modifier,
            worktree_factory=worktree_factory,
        ),
    )

    assert snapshot["status"] == "failed"
    assert snapshot["phase"] == "baseline_unavailable"
    assert snapshot["outcome"] == "baseline_unavailable"
    assert snapshot["errorType"] == "ProviderTransportError"
    assert "Service temporarily unavailable" in snapshot["error"]
    assert calls == {"modifier": 0, "worktree": 0}


def test_supervised_worktree_flow_stops_on_bad_gateway_html_with_css_400_percent(tmp_path):
    project_root = tmp_path / "project"
    _write_bundle(project_root)
    calls = {"modifier": 0, "worktree": 0}

    def modifier(*_: object) -> dict:
        calls["modifier"] += 1
        return {"status": "success"}

    def worktree_factory(*_: object) -> dict:
        calls["worktree"] += 1
        return {"path": str(tmp_path / "candidate")}

    snapshot = service.run_supervised_worktree_flow(
        {"sourceKind": "bundle", "bundleName": "closed_loop_v1", "mode": "manual"},
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=_retryable_provider_html_reason_evaluator,
            candidate_modifier=modifier,
            worktree_factory=worktree_factory,
        ),
    )

    assert snapshot["status"] == "failed"
    assert snapshot["phase"] == "baseline_unavailable"
    assert snapshot["outcome"] == "baseline_unavailable"
    assert snapshot["errorType"] == "ProviderTransportError"
    assert "回源请求被中断" in snapshot["error"]
    assert calls == {"modifier": 0, "worktree": 0}


@pytest.mark.parametrize("modifier_status", ["cancelled", "failed"])
def test_supervised_worktree_flow_stops_when_candidate_modifier_does_not_finish(tmp_path, modifier_status):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    calls = {"candidate_eval": 0}

    def worktree_factory(root: Path, run_id: str) -> dict:
        candidate = _make_candidate_repo(tmp_path, root)
        return {
            "path": str(candidate),
            "baseHead": "base",
            "checkpointCommit": "base",
            "checkpointRef": "",
            "trackedDirty": False,
            "untrackedFiles": [],
        }

    def evaluator(_: Path, bundle_name: str, role: str, __: dict) -> dict:
        if role == "candidate":
            calls["candidate_eval"] += 1
        return _fake_evaluator(_, bundle_name, role, __)

    def modifier(_: Path, __: str, ___: dict) -> dict:
        return {
            "status": modifier_status,
            "summary": f"candidate modifier {modifier_status}",
            "conversationSummary": {
                "conversation_backend": {
                    "enabled": True,
                    "session_id": "session-improver",
                    "observed_active_turn_id": "turn-improve",
                }
            },
        }

    snapshot = service.run_supervised_worktree_flow(
        {"sourceKind": "bundle", "bundleName": "closed_loop_v1", "mode": "manual"},
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=evaluator,
            candidate_modifier=modifier,
            worktree_factory=worktree_factory,
        ),
    )

    assert snapshot["status"] == modifier_status
    assert snapshot["phase"] == "candidate_modify"
    assert snapshot["runtimeStatus"] == modifier_status
    assert snapshot["outcome"] == f"candidate_modify_{modifier_status}"
    assert snapshot["candidate"] == {}
    assert snapshot["decision"] == {}
    assert calls["candidate_eval"] == 0
    assert snapshot["candidateConversationSessionId"] == "session-improver"
    improve_step = next(item for item in snapshot["workflowSteps"] if item["id"] == "improve")
    assert improve_step["status"] == modifier_status
    assert improve_step["conversationSessionId"] == "session-improver"


def test_supervised_worktree_flow_stops_when_candidate_modifier_makes_no_changes(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    calls = {"candidate_eval": 0}

    def worktree_factory(root: Path, run_id: str) -> dict:
        candidate = tmp_path / "candidate-no-change"
        _init_repo(candidate)
        for source in root.rglob("*"):
            if not source.is_file():
                continue
            rel = source.relative_to(root)
            if ".git" in rel.parts:
                continue
            target = candidate / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        _run_git(candidate, "add", ".")
        _run_git(candidate, "commit", "-m", "base")
        return {
            "path": str(candidate),
            "baseHead": "base",
            "checkpointCommit": "base",
            "checkpointRef": "",
            "trackedDirty": False,
            "untrackedFiles": [],
        }

    def evaluator(_: Path, bundle_name: str, role: str, __: dict) -> dict:
        if role == "candidate":
            calls["candidate_eval"] += 1
        return _fake_evaluator(_, bundle_name, role, __)

    def modifier(_: Path, __: str, ___: dict) -> dict:
        return {
            "status": "success",
            "summary": "candidate only inspected files",
            "conversationSummary": {
                "conversation_backend": {
                    "enabled": True,
                    "session_id": "session-improver",
                    "observed_active_turn_id": "turn-improve",
                }
            },
        }

    snapshot = service.run_supervised_worktree_flow(
        {"sourceKind": "bundle", "bundleName": "closed_loop_v1", "mode": "manual"},
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=evaluator,
            candidate_modifier=modifier,
            worktree_factory=worktree_factory,
        ),
    )

    assert snapshot["status"] == "failed"
    assert snapshot["phase"] == "candidate_modify"
    assert snapshot["runtimeStatus"] == "failed"
    assert snapshot["outcome"] == "candidate_modify_no_changes"
    assert snapshot["candidateModification"]["status"] == "no_changes"
    assert snapshot["candidate"] == {}
    assert snapshot["decision"] == {}
    assert calls["candidate_eval"] == 0
    assert snapshot["workflowSteps"][2]["status"] == "failed"


def test_merge_analysis_blocks_when_main_workspace_touched_same_file(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    (project_root / "agent.py").write_text("print('user edit')\n", encoding="utf-8")
    candidate = _make_candidate_repo(tmp_path, project_root)
    snapshot = {
        "runId": "swte-conflict",
        "runKind": service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": {"path": str(candidate), "preserved": True},
    }
    service._persist_snapshot(snapshot, active_run_id="")

    updated = service.execute_supervised_worktree_action("swte-conflict", "analyze_merge")

    assert updated["mergeAnalysis"]["status"] == "blocked"
    assert updated["mergeAnalysis"]["mergeAllowed"] is False
    assert "main_workspace_overlap" in updated["mergeAnalysis"]["blockers"]
    assert updated["mergeAnalysis"]["overlapFiles"] == ["agent.py"]


def test_merge_analysis_ignores_untracked_noise_from_worktree_baseline(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    tests_keep = project_root / "tests" / ".keep"
    tests_keep.parent.mkdir(parents=True, exist_ok=True)
    tests_keep.write_text("", encoding="utf-8")
    noise_path = project_root / ".codex" / "visual-checks" / "noise.png"
    noise_path.parent.mkdir(parents=True, exist_ok=True)
    noise_path.write_bytes(b"preexisting visual check")
    _write_bundle(project_root)
    _run_git(project_root, "add", "agent.py", "tests/.keep", "workspace/evaluation/bundles/closed_loop_v1.json")
    _run_git(project_root, "commit", "-m", "init")

    candidate = tmp_path / "candidate-noise"
    _init_repo(candidate)
    (candidate / "agent.py").write_text("print('base')\n", encoding="utf-8")
    candidate_tests_keep = candidate / "tests" / ".keep"
    candidate_tests_keep.parent.mkdir(parents=True, exist_ok=True)
    candidate_tests_keep.write_text("", encoding="utf-8")
    candidate_bundle = candidate / "workspace" / "evaluation" / "bundles" / "closed_loop_v1.json"
    candidate_bundle.parent.mkdir(parents=True, exist_ok=True)
    candidate_bundle.write_bytes((project_root / "workspace" / "evaluation" / "bundles" / "closed_loop_v1.json").read_bytes())
    _run_git(candidate, "add", "agent.py", "tests/.keep", "workspace/evaluation/bundles/closed_loop_v1.json")
    _run_git(candidate, "commit", "-m", "base")
    candidate_noise = candidate / ".codex" / "visual-checks" / "noise.png"
    candidate_noise.parent.mkdir(parents=True, exist_ok=True)
    candidate_noise.write_bytes(b"preexisting visual check")
    marker = candidate / "tests" / "supervised_worktree_candidate_marker.py"
    marker.write_text("CANDIDATE_SELF_EDITED = True\n", encoding="utf-8")
    snapshot = {
        "runId": "swte-noise",
        "runKind": service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": _bound_candidate_worktree(
            candidate,
            baseline_untracked=[".codex/visual-checks/noise.png"],
        ),
    }
    service._persist_snapshot(snapshot, active_run_id="")

    updated = service.execute_supervised_worktree_action("swte-noise", "analyze_merge")

    assert updated["mergeAnalysis"]["status"] == "ready"
    assert updated["mergeAnalysis"]["mergeAllowed"] is True
    assert updated["mergeAnalysis"]["changedFiles"] == [
        {
            "path": "tests/supervised_worktree_candidate_marker.py",
            "status": "??",
            "changeType": "added",
            "highRisk": False,
        }
    ]
    assert updated["mergeAnalysis"]["overlapFiles"] == []
    assert "main_workspace_overlap" not in updated["mergeAnalysis"]["blockers"]


def test_force_merge_never_overwrites_main_workspace_overlap(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    (project_root / "agent.py").write_text("print('user edit')\n", encoding="utf-8")
    candidate = _make_candidate_repo(tmp_path, project_root)
    snapshot = {
        "runId": "swte-merge",
        "runKind": service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": _bound_candidate_worktree(candidate),
        "candidateJudgment": {"status": "success", "phase": "rerun", "decision": "REJECT"},
        "judgeConversationSessionId": "session-judge",
    }
    service._persist_snapshot(snapshot, active_run_id="")

    with pytest.raises(service.SupervisedWorktreeRunActionError, match="主工作区冲突"):
        service.execute_supervised_worktree_action("swte-merge", "merge", force=True)

    assert (project_root / "agent.py").read_text(encoding="utf-8") == "print('user edit')\n"


def test_force_merge_creates_rollback_manifest_and_rollback_restores_file(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    candidate = _make_candidate_repo(tmp_path, project_root)
    snapshot = {
        "runId": "swte-merge-rollback",
        "runKind": service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": _bound_candidate_worktree(candidate),
        "candidateJudgment": {"status": "success", "phase": "rerun", "decision": "REJECT"},
        "judgeConversationSessionId": "session-judge",
    }
    service._persist_snapshot(snapshot, active_run_id="")

    merged = service.execute_supervised_worktree_action("swte-merge-rollback", "merge", force=True)

    assert merged["merge"]["status"] == "merged"
    assert merged["merge"]["triggeredBy"]["role"] == "judge"
    assert merged["merge"]["triggeredBy"]["conversationSessionId"] == "session-judge"
    assert "# candidate edit" in (project_root / "agent.py").read_text(encoding="utf-8")
    manifest_path = Path(merged["rollback"]["manifestPath"])
    assert manifest_path.exists()

    rolled_back = service.execute_supervised_worktree_action("swte-merge-rollback", "rollback")

    assert rolled_back["rollback"]["status"] == "rolled_back"
    assert (project_root / "agent.py").read_text(encoding="utf-8") == "print('base')\n"


def test_merge_rejects_candidate_mutated_after_judge_variant_binding(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    candidate = _make_candidate_repo(tmp_path, project_root)
    worktree = _bound_candidate_worktree(candidate)
    snapshot = {
        "runId": "swte-variant-drift",
        "runKind": service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": worktree,
        "candidateJudgment": {"status": "success", "phase": "rerun", "decision": "APPROVE"},
        "judgeConversationSessionId": "session-judge",
    }
    service._persist_snapshot(snapshot, active_run_id="")
    (candidate / "agent.py").write_text(
        (candidate / "agent.py").read_text(encoding="utf-8") + "# post-judge mutation\n",
        encoding="utf-8",
    )

    with pytest.raises(service.SupervisedWorktreeRunActionError, match="候选版本绑定"):
        service.execute_supervised_worktree_action("swte-variant-drift", "merge", force=True)

    assert (project_root / "agent.py").read_text(encoding="utf-8") == "print('base')\n"


def test_self_origin_merge_requires_review_even_when_forced(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    candidate = _make_candidate_repo(tmp_path, project_root)
    snapshot = {
        "runId": "swte-self-review",
        "runKind": service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": _bound_candidate_worktree(candidate),
        "selfEvolutionOrigin": {
            "sourceTrack": "self_evolution",
            "goal": "修复核心代码",
            "riskReason": "goal_write_marker",
            "requiresSupervisedReview": True,
        },
        "reviewGate": {
            "required": True,
            "status": "pending",
            "reason": "must review",
            "approvedAt": "",
            "reviewerNote": "",
        },
        "candidateJudgment": {"status": "success", "phase": "rerun", "decision": "PROMOTE"},
        "judgeConversationSessionId": "session-judge",
    }
    service._persist_snapshot(snapshot, active_run_id="")

    blocked = service.execute_supervised_worktree_action("swte-self-review", "analyze_merge")

    assert blocked["mergeAnalysis"]["mergeAllowed"] is False
    assert "supervised_review_pending" in blocked["mergeAnalysis"]["blockers"]
    with pytest.raises(service.SupervisedWorktreeRunActionError, match="用户审批 pending"):
        service.execute_supervised_worktree_action("swte-self-review", "merge", force=True)

    approved = service.execute_supervised_worktree_action(
        "swte-self-review",
        "approve_review",
        reviewer_note="reviewed by supervised line",
    )
    assert approved["reviewGate"]["status"] == "approved"
    assert approved["reviewGate"]["reviewerNote"] == "reviewed by supervised line"
    assert approved["merge"]["status"] == "merged"
    assert approved["merge"]["triggeredBy"]["role"] == "judge"
    assert "# candidate edit" in (project_root / "agent.py").read_text(encoding="utf-8")


def test_rejected_judgment_remains_advisory_and_user_can_approve_without_force(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    candidate = _make_candidate_repo(tmp_path, project_root)
    snapshot = {
        "runId": "swte-rejected-approval",
        "runKind": service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": _bound_candidate_worktree(candidate),
        "candidateJudgment": {
            "status": "success",
            "phase": "rerun",
            "recommendation": "REJECT",
            "decision": "REJECT",
        },
        "judgeConversationSessionId": "session-judge",
        "reviewGate": {
            "required": True,
            "status": "pending",
            "reason": "user approval required",
            "approvedAt": "",
            "reviewerNote": "",
        },
    }
    service._persist_snapshot(snapshot, active_run_id="")

    projected = service.get_supervised_worktree_run("swte-rejected-approval")
    assert projected["actionStates"]["approveReview"]["enabled"] is True
    assert projected["actionStates"]["approveReview"]["reason"] == ""

    merged = service.execute_supervised_worktree_action(
        "swte-rejected-approval",
        "approve_review",
        reviewer_note="user reviewed the Judge recommendation and approved",
    )
    assert merged["merge"]["status"] == "merged"
    assert merged["merge"]["force"] is False
    assert merged["merge"]["triggeredBy"]["decision"] == "REJECT"
    assert merged["reviewGate"]["overrodeJudgeRecommendation"] is True


def test_real_judge_merge_trigger_honors_user_approval_even_when_recommendation_is_reject(tmp_path, monkeypatch):
    calls: list[dict] = []

    def fake_harness(**kwargs):
        calls.append(dict(kwargs))
        return _fake_harness_result(
            role="judge",
            repo_root=Path(kwargs["repo_root"]),
            prompt=str(kwargs.get("prompt") or ""),
            session_id="session-judge",
            agent_judgment={
                "phase": "merge_authorization",
                "decision": "REJECT",
                "merge_requested": True,
                "reason": "user approved despite advisory rejection",
                "evidence_refs": ["variant:one"],
            },
        )

    monkeypatch.setattr(service, "run_supervised_conversation_harness", fake_harness)
    snapshot = {
        "runId": "swte-real-trigger",
        "executionMode": "real",
        "projectRoot": str(tmp_path),
        "mentalModelMode": "follow",
        "mentalModelEnabled": False,
        "agentBindings": {
            "judge": {"agentId": "agent-judge", "role": "judge"},
        },
        "judgeConversationSessionId": "session-judge",
        "candidateJudgment": {
            "status": "success",
            "phase": "rerun",
            "recommendation": "REJECT",
            "decision": "REJECT",
        },
        "candidateWorktree": {
            "variant": {"variantId": "variant-one", "patchSha256": "abc"},
        },
    }

    triggered = service._request_judge_controlled_merge(
        snapshot,
        force=False,
        reviewer_note="approved by user",
    )

    assert triggered["judgeMergeTrigger"]["status"] == "requested"
    assert triggered["judgeMergeTrigger"]["decision"] == "REJECT"
    assert triggered["judgeMergeTrigger"]["conversationSessionId"] == "session-judge"
    assert triggered["judgeMergeTrigger"]["mechanism"] == "judge_conversation_request"
    assert len(calls) == 1
    assert calls[0]["conversation_session_id"] == "session-judge"
    assert calls[0]["scenario"] == "supervised_judge_merge_trigger"
    assert "不要执行 shell、git merge" in calls[0]["prompt"]


def test_discard_removes_owned_candidate_worktree(tmp_path, monkeypatch):
    scene_events: list[dict] = []
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    candidate = tmp_path / "vibelution-harness-swte-rem-owned"
    candidate.mkdir()

    def fake_remove_worktree(root: Path, path: Path) -> None:
        assert root == project_root.resolve()
        assert path == candidate
        candidate.rmdir()

    def record_scene_event(*args, **kwargs):
        scene_events.append({"args": args, "kwargs": kwargs})
        return {"accepted": True}

    monkeypatch.setattr(service, "remove_worktree", fake_remove_worktree)
    monkeypatch.setattr(service, "record_runtime_scene_event", record_scene_event)
    snapshot = {
        "runId": "swte-rem-owned",
        "runKind": service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": {
            "path": str(candidate),
            "preserved": True,
            "cleanupOwner": service.RUN_KIND,
            "cleanupRunId": "swte-rem-owned",
        },
    }
    service._persist_snapshot(snapshot, active_run_id="")

    updated = service.execute_supervised_worktree_action("swte-rem-owned", "discard")

    assert updated["outcome"] == "discarded"
    assert updated["candidateWorktree"]["preserved"] is False
    assert updated["candidateWorktree"]["cleanup"]["status"] == "removed"
    assert not candidate.exists()
    assert scene_events == []


def test_discard_skips_unowned_candidate_path_without_rmtree(tmp_path, monkeypatch):
    scene_events: list[dict] = []
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    external_worktree = tmp_path / "ordinary-dev-worktree"
    external_worktree.mkdir()
    sentinel = external_worktree / "sentinel.txt"
    sentinel.write_text("keep me", encoding="utf-8")

    def forbidden_remove_worktree(*_: object) -> None:
        raise AssertionError("unowned worktree must not reach git worktree remove")

    def forbidden_rmtree(*_: object, **__: object) -> None:
        raise AssertionError("unowned worktree must not be recursively deleted")

    def record_scene_event(*args, **kwargs):
        scene_events.append({"args": args, "kwargs": kwargs})
        return {"accepted": True}

    monkeypatch.setattr(service, "remove_worktree", forbidden_remove_worktree)
    monkeypatch.setattr(service.shutil, "rmtree", forbidden_rmtree)
    monkeypatch.setattr(service, "record_runtime_scene_event", record_scene_event)
    snapshot = {
        "runId": "swte-skip-unowned",
        "runKind": service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": {"path": str(external_worktree), "preserved": True},
    }
    service._persist_snapshot(snapshot, active_run_id="")

    updated = service.execute_supervised_worktree_action("swte-skip-unowned", "discard")

    assert updated["outcome"] == "discard_skipped"
    assert updated["candidateWorktree"]["preserved"] is True
    assert updated["candidateWorktree"]["cleanup"]["status"] == "skipped"
    assert updated["candidateWorktree"]["cleanup"]["reason"] == "unowned_candidate_path"
    assert updated["actionStates"]["discard"]["enabled"] is False
    assert sentinel.read_text(encoding="utf-8") == "keep me"
    assert scene_events
    assert scene_events[0]["args"][2] == "supervised_worktree_run.candidate_cleanup_skipped"
    assert scene_events[0]["kwargs"]["fields"]["cleanupReason"] == "unowned_candidate_path"


def test_legacy_harness_name_must_live_under_temp_dir(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    candidate = tmp_path / "vibelution-harness-swte-legacy-owned"
    candidate.mkdir()
    plan = service._candidate_worktree_cleanup_plan(
        {"runId": "swte-legacy-owned"},
        project_root=project_root,
        worktree={"path": str(candidate)},
    )

    assert plan["status"] == "skipped"
    assert plan["reason"] == "unowned_candidate_path"


def test_candidate_path_file_path_is_rejected_by_flow(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    _write_bundle(project_root)
    bad_path = tmp_path / "candidate-agent.py"
    bad_path.write_text("def candidate_agent():\n    pass\n", encoding="utf-8")

    snapshot = service.run_supervised_worktree_flow(
        {"sourceKind": "bundle", "bundleName": "closed_loop_v1", "mode": "manual"},
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=_fake_evaluator,
            candidate_modifier=lambda *_: {"status": "success"},
            worktree_factory=lambda *_: {"path": str(bad_path)},
        ),
    )

    assert snapshot["status"] == "failed"
    assert snapshot["errorType"] == "SupervisedWorktreeRunValidationError"
    assert "候选工作树路径不是目录" in snapshot["error"]
    assert snapshot["candidateWorktree"] == {}


def test_candidate_worktree_cleanup_plan_rejects_file_path(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    bad_path = tmp_path / "candidate-agent.py"
    bad_path.write_text("def candidate_agent():\n    pass\n", encoding="utf-8")

    plan = service._candidate_worktree_cleanup_plan(
        {"runId": "swte-candidate-file"},
        project_root=project_root,
        worktree={"path": str(bad_path)},
    )

    assert plan["status"] == "skipped"
    assert plan["reason"] == "not_directory"


def test_get_supervised_worktree_run_cleanses_invalid_candidate_worktree_path(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    bad_path = tmp_path / "candidate-file.py"
    bad_path.write_text("print('legacy')\n", encoding="utf-8")
    run_id = "swte-get-invalid-candidate-worktree"
    service._persist_snapshot(
        {
            "runId": run_id,
            "runKind": service.RUN_KIND,
            "status": "done",
            "projectRoot": str(project_root),
            "candidateWorktree": {"path": str(bad_path), "preserved": True},
            "updatedAt": "2026-06-01T00:00:00+00:00",
        }
    )

    snapshot = service.get_supervised_worktree_run(run_id)
    assert snapshot is not None
    assert "path" not in snapshot["candidateWorktree"]
    assert "pathValidationError" in snapshot["candidateWorktree"]
    assert snapshot["actionStates"]["preserve"]["enabled"] is False


def test_get_supervised_worktree_run_cleanses_nested_candidate_worktree_path(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    nested_path = project_root / ".temp-candidate"
    nested_path.mkdir()
    run_id = "swte-get-nested-candidate-worktree"
    service._persist_snapshot(
        {
            "runId": run_id,
            "runKind": service.RUN_KIND,
            "status": "done",
            "projectRoot": str(project_root),
            "candidateWorktree": {"path": str(nested_path), "preserved": True},
            "updatedAt": "2026-06-01T00:00:03+00:00",
        }
    )

    snapshot = service.get_supervised_worktree_run(run_id)
    assert snapshot is not None
    assert "path" not in snapshot["candidateWorktree"]
    assert "pathValidationError" in snapshot["candidateWorktree"]
    assert "主项目目录内" in snapshot["candidateWorktree"]["pathValidationError"]
    assert snapshot["actionStates"]["discard"]["enabled"] is False


def test_list_supervised_worktree_runs_cleanses_invalid_candidate_worktree_path(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    invalid_path = tmp_path / "candidate-file.py"
    invalid_path.write_text("print('legacy')\n", encoding="utf-8")
    valid_path = tmp_path / "candidate-dir"
    valid_path.mkdir()
    invalid_run_id = "swte-list-invalid-candidate-worktree"
    valid_run_id = "swte-list-valid-candidate-worktree"

    service._persist_snapshot(
        {
            "runId": invalid_run_id,
            "runKind": service.RUN_KIND,
            "status": "done",
            "projectRoot": str(project_root),
            "candidateWorktree": {"path": str(invalid_path), "preserved": True},
            "updatedAt": "2026-06-01T00:00:01+00:00",
        }
    )
    service._persist_snapshot(
        {
            "runId": valid_run_id,
            "runKind": service.RUN_KIND,
            "status": "done",
            "projectRoot": str(project_root),
            "candidateWorktree": {"path": str(valid_path), "preserved": True},
            "updatedAt": "2026-06-01T00:00:02+00:00",
        }
    )

    snapshots = service.list_supervised_worktree_runs(limit=10)
    snapshots_by_id = {snapshot.get("runId"): snapshot for snapshot in snapshots}
    invalid_snapshot = snapshots_by_id[invalid_run_id]
    assert "path" not in invalid_snapshot["candidateWorktree"]
    assert "pathValidationError" in invalid_snapshot["candidateWorktree"]
    assert invalid_snapshot["candidateWorktree"]["pathValidationError"]
    valid_snapshot = snapshots_by_id[valid_run_id]
    assert "path" in valid_snapshot["candidateWorktree"]


def test_real_llm_mode_requires_explicit_cost_confirmation(tmp_path):
    project_root = tmp_path / "project"
    _write_bundle(project_root)

    with pytest.raises(service.SupervisedWorktreeRunValidationError) as exc_info:
        service.run_supervised_worktree_flow(
            {
                "sourceKind": "bundle",
                "bundleName": "closed_loop_v1",
                "executionMode": "real",
                "confirmRealLlmCost": False,
            },
            project_root=project_root,
            dependencies=service.WorktreeRunDependencies(
                evaluation_runner=_fake_evaluator,
                candidate_modifier=lambda *_: {"status": "success"},
                worktree_factory=lambda *_: {"path": str(tmp_path / "candidate")},
            ),
        )

    assert "预计会发起" in str(exc_info.value)
    assert "tokens" in str(exc_info.value)


def test_real_mode_requires_baseline_and_judge_bindings_before_execution(tmp_path):
    project_root = tmp_path / "project"
    _write_bundle(project_root)

    with pytest.raises(service.SupervisedWorktreeRunValidationError, match="Judge Agent"):
        service._normalize_start_payload(
            {
                "sourceKind": "bundle",
                "bundleName": "closed_loop_v1",
                "executionMode": "real",
                "confirmRealLlmCost": True,
                "agentBindings": {
                    "baseline": {"agentId": "agent-baseline", "role": "baseline"},
                },
            },
            lang="zh",
            project_root=project_root,
        )


def test_candidate_worktree_receives_ignored_runtime_bundle(tmp_path):
    project_root = tmp_path / "project"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _write_bundle(project_root, "ignored_bundle_v1")

    service._ensure_bundle_available_in_candidate(
        project_root,
        candidate_path=candidate,
        bundle_name="ignored_bundle_v1",
    )

    copied = candidate / "workspace" / "evaluation" / "bundles" / "ignored_bundle_v1.json"
    assert copied.exists()
    assert json.loads(copied.read_text(encoding="utf-8"))["bundle_name"] == "ignored_bundle_v1"


def test_force_cancel_active_supervised_worktree_run_for_shutdown_releases_snapshot(monkeypatch):
    scene_events: list[tuple[str, str, str, dict]] = []

    def record_scene_event(component, phase, event_code, **kwargs):
        scene_events.append((component, phase, event_code, kwargs))
        return {"accepted": True}

    monkeypatch.setattr(service, "record_runtime_scene_event", record_scene_event)
    snapshot = {
        "runId": "swte-shutdown-active",
        "runKind": service.RUN_KIND,
        "leases": service.RUN_LEASES,
        "status": "running",
        "phase": "candidate_modify",
        "runtimeStatus": "running",
        "outcome": "",
        "startedAt": "2026-05-22T10:00:00+00:00",
        "updatedAt": "2026-05-22T10:01:00+00:00",
        "finishedAt": "",
        "latestMessage": "候选 agent 正在反思并修改自身。",
        "decision": {},
        "mergeAnalysis": {},
    }
    service._persist_snapshot(snapshot, active_run_id="swte-shutdown-active")

    closed = service.force_cancel_active_supervised_worktree_runs_for_shutdown("closing")

    assert len(closed) == 1
    assert closed[0]["runId"] == "swte-shutdown-active"
    assert closed[0]["runKind"] == service.RUN_KIND
    assert closed[0]["status"] == "cancelled"
    assert closed[0]["phase"] == "shutdown"
    assert closed[0]["runtimeStatus"] == "cancelled"
    assert closed[0]["outcome"] == "shutdown_cancelled"
    assert closed[0]["latestMessage"] == "工作台关闭前已终止监督工作树进化运行。"
    assert closed[0]["runtimeManagerControl"] == {"reason": "shutdown", "message": "closing"}
    assert closed[0]["finishedAt"]
    assert closed[0]["stages"][-1]["phase"] == "shutdown"
    assert service.get_active_supervised_worktree_run() is None
    persisted = service.get_supervised_worktree_run("swte-shutdown-active")
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["phase"] == "shutdown"
    assert persisted["runtimeManagerControl"]["reason"] == "shutdown"
    cancelled_event = next(item for item in scene_events if item[2] == "supervised_worktree_run.shutdown_cancelled")
    assert cancelled_event[1] == "shutdown"
    assert cancelled_event[3]["lifecycle"] is True


def test_operator_terminate_action_cancels_active_supervised_worktree_run_and_unlocks(monkeypatch):
    scene_events: list[tuple[str, str, str, dict]] = []

    def record_scene_event(component, phase, event_code, **kwargs):
        scene_events.append((component, phase, event_code, kwargs))
        return {"accepted": True}

    monkeypatch.setattr(service, "record_runtime_scene_event", record_scene_event)
    run_id = "swte-operator-terminate"
    snapshot = {
        "runId": run_id,
        "runKind": service.RUN_KIND,
        "leases": service.RUN_LEASES,
        "status": "running",
        "phase": "candidate_modify",
        "runtimeStatus": "running",
        "outcome": "",
        "startedAt": "2026-05-22T10:00:00+00:00",
        "updatedAt": "2026-05-22T10:01:00+00:00",
        "finishedAt": "",
        "latestMessage": "候选 agent 正在改良。",
        "decision": {},
        "mergeAnalysis": {},
    }
    service._persist_snapshot(snapshot, active_run_id=run_id)

    updated = service.execute_supervised_worktree_action(
        run_id,
        "terminate",
        reviewer_note="用户从监督进化页面终止。",
    )

    assert updated["status"] == "cancelled"
    assert updated["phase"] == "operator_terminated"
    assert updated["runtimeStatus"] == "cancelled"
    assert updated["outcome"] == "operator_cancelled"
    assert updated["runtimeManagerControl"] == {
        "reason": "operator_terminate",
        "message": "用户从监督进化页面终止。",
    }
    assert updated["finishedAt"]
    assert updated["actionStates"]["terminate"]["enabled"] is False
    assert service.get_active_supervised_worktree_run() is None
    persisted = service.get_supervised_worktree_run(run_id)
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["runtimeManagerControl"]["reason"] == "operator_terminate"
    cancelled_event = next(item for item in scene_events if item[2] == "supervised_worktree_run.operator_cancelled")
    assert cancelled_event[1] == "operator_terminated"
    assert cancelled_event[3]["lifecycle"] is True


def test_terminal_snapshot_cannot_regress_to_active_progress():
    run_id = "swte-terminal-snapshot"
    cancelled = {
        "runId": run_id,
        "runKind": service.RUN_KIND,
        "status": "cancelled",
        "phase": "operator_terminated",
        "runtimeStatus": "cancelled",
        "outcome": "operator_cancelled",
        "latestMessage": "用户已终止。",
    }
    service._persist_snapshot(cancelled, active_run_id="")

    stale_progress = {
        **cancelled,
        "status": "running",
        "phase": "candidate_modify",
        "runtimeStatus": "running",
        "outcome": "",
        "latestMessage": "stale worker progress",
    }
    persisted = service._persist_snapshot(stale_progress, active_run_id=run_id)

    assert persisted["status"] == "cancelled"
    assert persisted["phase"] == "operator_terminated"
    assert persisted["latestMessage"] == "用户已终止。"
    assert service.get_active_supervised_worktree_run() is None


def test_get_active_run_reconciles_stopped_candidate_conversation(monkeypatch, tmp_path):
    monkeypatch.setattr(service.work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    monkeypatch.setattr(service, "record_runtime_scene_event", lambda *args, **kwargs: {"accepted": True})
    monkeypatch.setattr(service, "_ACTIVE_RUN_ID", None)
    service._RUN_CANCEL_EVENTS.clear()
    run_id = "swte-orphaned-candidate"
    turn_id = "session-candidate-turn-1"
    service._persist_snapshot(
        {
            "runId": run_id,
            "runKind": service.RUN_KIND,
            "leases": service.RUN_LEASES,
            "status": "running",
            "phase": "candidate_modify",
            "runtimeStatus": "running",
            "outcome": "",
            "startedAt": "2026-05-22T10:00:00+00:00",
            "updatedAt": "2026-05-22T10:01:00+00:00",
            "finishedAt": "",
            "latestMessage": "候选 agent 正在反思并修改自身。",
            "candidateWorktree": {"path": str(tmp_path / "candidate"), "preserved": True},
            "candidateModification": {},
            "candidate": {},
            "decision": {},
            "mergeAnalysis": {},
            "workflowProgress": {
                "improve": {
                    "stepId": "improve",
                    "status": "running",
                    "phase": "conversation_turn_running",
                    "conversationSessionId": "session-candidate",
                    "conversationTurnId": turn_id,
                    "livePreview": "正在改良",
                }
            },
        },
        active_run_id=run_id,
    )
    service._work_run_store().persist_snapshot(
        "chat_turn",
        {
            "runId": turn_id,
            "status": "stopped_by_user",
            "runtimeStatus": "force_stopped",
            "updatedAt": "2026-05-22T10:02:00+00:00",
            "finishedAt": "2026-05-22T10:02:00+00:00",
        },
        active_run_id="",
    )

    active = service.get_active_supervised_worktree_run()

    assert active is None
    persisted = service.get_supervised_worktree_run(run_id)
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["phase"] == "candidate_modify"
    assert persisted["runtimeStatus"] == "cancelled"
    assert persisted["outcome"] == "candidate_modify_cancelled"
    assert persisted["candidateModification"]["status"] == "cancelled"
    assert persisted["candidate"] == {}
    assert persisted["workflowSteps"][2]["status"] == "cancelled"


def test_shutdown_cancel_stops_flow_before_candidate_work(tmp_path, monkeypatch):
    monkeypatch.setattr(service.work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    monkeypatch.setattr(service, "record_runtime_scene_event", lambda *args, **kwargs: {"accepted": True})
    project_root = tmp_path / "project"
    _write_bundle(project_root, "cancel_bundle_v1")
    options = service._normalize_start_payload(
        {"sourceKind": "bundle", "bundleName": "cancel_bundle_v1", "executionMode": "simulation"},
        lang="zh",
        project_root=project_root,
    )
    run_id = "swte-cancel-flow"
    snapshot = {
        "runId": run_id,
        "runKind": service.RUN_KIND,
        "leases": service.RUN_LEASES,
        "status": "queued",
        "phase": "queued",
        "runtimeStatus": "queued",
        "outcome": "",
        "mode": options["mode"],
        "executionMode": options["executionMode"],
        "sourceKind": options["sourceKind"],
        "datasetName": options["datasetName"],
        "datasetLimit": options["datasetLimit"],
        "bundleName": options["bundleName"],
        "keepWorktree": bool(options["keepWorktree"]),
        "startRequest": options["startRequest"],
        "selfEvolutionOrigin": options["selfEvolutionOrigin"],
        "reviewGate": options["reviewGate"],
        "startedAt": "2026-05-22T10:00:00+00:00",
        "updatedAt": "2026-05-22T10:00:00+00:00",
        "finishedAt": "",
        "projectRoot": str(project_root),
        "latestMessage": "",
        "costEstimate": options["costEstimate"],
        "stages": [],
        "events": [],
        "baseline": {},
        "reflection": {},
        "candidateWorktree": {},
        "candidateModification": {},
        "candidate": {},
        "decision": {},
        "mergeAnalysis": {},
        "merge": {},
        "rollback": {},
        "error": "",
        "errorType": "",
    }
    calls = {"baseline": 0, "worktree": 0, "modifier": 0, "candidate": 0}

    def evaluator(root: Path, bundle_name: str, role: str, context: dict) -> dict:
        assert callable(context.get("cancelChecker"))
        calls[role] += 1
        if role == "baseline":
            service.force_cancel_active_supervised_worktree_runs_for_shutdown("closing")
        return _fake_evaluator(root, bundle_name, role, context)

    def worktree_factory(*_: object) -> dict:
        calls["worktree"] += 1
        return {"path": str(tmp_path / "candidate")}

    def modifier(*_: object) -> dict:
        calls["modifier"] += 1
        return {"status": "success"}

    service._persist_snapshot(snapshot, active_run_id=run_id)
    try:
        result = service._execute_flow(
            snapshot,
            options,
            root=project_root,
            dependencies=service.WorktreeRunDependencies(
                evaluation_runner=evaluator,
                candidate_modifier=modifier,
                worktree_factory=worktree_factory,
            ),
        )
    finally:
        service._clear_run_cancel_event(run_id)

    assert result["status"] == "cancelled"
    assert result["phase"] == "shutdown"
    assert result["outcome"] == "shutdown_cancelled"
    assert calls == {"baseline": 1, "worktree": 0, "modifier": 0, "candidate": 0}
    persisted = service.get_supervised_worktree_run(run_id)
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["phase"] == "shutdown"
