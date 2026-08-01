from __future__ import annotations

from copy import deepcopy

import pytest

from core.web.services.self_evolution_autonomous_loop_runtime import (
    AutonomousLoopRuntimeDependencies,
    AutonomousLoopRuntimeError,
    build_autonomous_loop_hooks,
)


def _snapshot(**updates):
    payload = {
        "runId": "self-loop-001",
        "request": {"goal": "优化当前自进化流程", "maxIterations": 1},
        "observation": {
            "summary": "当前只有观察入口",
            "evidence": [],
            "conversationSessionId": "session-observer",
        },
        "plan": {
            "summary": "建立无评分闭环",
            "steps": [{"id": "implement", "title": "实现闭环"}],
            "targetFiles": ["core/example.py", "tests/test_example.py"],
            "conversationSessionId": "session-observer",
        },
        "candidate": {
            "branch": "codex/self-loop-candidate",
            "worktreePath": "C:/workspace/self-loop-candidate",
            "baseCommit": "a" * 40,
            "headCommit": "b" * 40,
            "changedFiles": ["core/example.py"],
            "variantId": "variant-001",
        },
        "approval": {
            "decision": "approve",
            "actorType": "user",
            "actorId": "local-user",
        },
        "integration": {
            "status": "merged",
            "mergedHead": "d" * 40,
        },
    }
    payload.update(updates)
    return payload


def test_runtime_hooks_use_one_observer_context_then_isolated_executor():
    calls: list[tuple[str, dict]] = []

    def load_bindings():
        return {
            "observer": {
                "agentId": "observer-agent",
                "directSessionId": "session-observer",
                "workspacePath": "C:/workspace/main",
            },
            "executor": {
                "agentId": "executor-agent",
                "directSessionId": "session-executor",
                "workspacePath": "C:/workspace/main",
            },
        }

    def run_role_turn(**kwargs):
        calls.append(("turn", deepcopy(kwargs)))
        if kwargs["role"] == "observer" and not kwargs.get("carryover"):
            return {
                "result": {
                    "status": "completed",
                    "summary": "发现自动闭环缺少用户批准后的 Git 收口。",
                    "tool_trace": [{"name": "runtime_snapshot", "status": "completed"}],
                },
                "carryover": {"previousResponseId": "response-observe"},
                "conversationSessionId": "session-observer",
            }
        if kwargs["role"] == "observer":
            return {
                "result": {
                    "status": "completed",
                    "summary": "新增状态机、真实执行适配和确定性 Git 接线。",
                    "targetFiles": ["core/example.py", "tests/test_example.py"],
                    "steps": [
                        {"id": "state", "title": "状态机"},
                        {"id": "git", "title": "Git 收口"},
                    ],
                },
                "carryover": {"previousResponseId": "response-plan"},
                "conversationSessionId": "session-observer",
            }
        return {
            "result": {
                "status": "completed",
                "summary": "候选实现完成，聚焦测试通过。",
                "tool_trace": [{"name": "pytest", "status": "completed"}],
            },
            "carryover": {},
            "conversationSessionId": "session-executor",
        }

    def create_candidate(context):
        calls.append(("create_candidate", deepcopy(context)))
        return {
            "branch": "codex/self-loop-candidate",
            "worktreePath": "C:/workspace/self-loop-candidate",
            "baseCommit": "a" * 40,
        }

    def inspect_candidate(context):
        calls.append(("inspect_candidate", deepcopy(context)))
        return {
            "headCommit": "b" * 40,
            "changedFiles": ["core/example.py", "tests/test_example.py"],
            "variantId": "variant-001",
        }

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=load_bindings,
            run_role_turn=run_role_turn,
            create_candidate=create_candidate,
            inspect_candidate=inspect_candidate,
            integrate_candidate=lambda context: {
                "status": "committed",
                "commitSha": "d" * 40,
                "candidateVariantId": context["candidate"]["variantId"],
            },
            cleanup_candidate=lambda _context: {
                "status": "cleaned",
                "worktreeRemoved": True,
                "localBranchDeleted": True,
            },
        )
    )

    observation = hooks.observe(_snapshot(observation=None, plan=None, candidate=None))
    plan = hooks.plan(_snapshot(observation=observation, plan=None, candidate=None))
    candidate = hooks.evolve(_snapshot(observation=observation, plan=plan, candidate=None))

    turn_calls = [payload for name, payload in calls if name == "turn"]
    assert [call["role"] for call in turn_calls] == [
        "observer",
        "observer",
        "executor",
    ]
    assert all(call["role"] != "reviewer" for call in turn_calls)
    assert turn_calls[0]["runtime_tool_grants"] == [
        "grep_search_tool",
        "code_symbol_tool",
    ]
    assert turn_calls[1]["runtime_tool_grants"] == [
        "grep_search_tool",
        "code_symbol_tool",
    ]
    assert turn_calls[0]["max_iterations"] == 4
    assert turn_calls[1]["max_iterations"] == 3
    assert turn_calls[0]["disable_tools"] is False
    assert turn_calls[1]["disable_tools"] is False
    assert "apply_patch_tool" not in turn_calls[0]["runtime_tool_grants"]
    assert "cli_tool" not in turn_calls[0]["runtime_tool_grants"]
    assert turn_calls[2]["runtime_tool_grants"] == [
        "open_evolution_transaction_tool",
        "close_evolution_transaction_tool",
        "grep_search_tool",
        "code_symbol_tool",
        "apply_patch_tool",
        "write_file_tool",
    ]
    assert turn_calls[2]["max_iterations"] == 12
    assert "12 次" in turn_calls[2]["prompt"]
    assert all(
        call["runtime_tool_source"] == "self_evolution_autonomous_loop"
        for call in turn_calls
    )
    assert turn_calls[1]["carryover"] == {
        "previousResponseId": "response-observe"
    }
    assert "读取 logs/runtime_scenes 使用 grep_search_tool" in turn_calls[0]["prompt"]
    assert "由自己触发的工具参数或目录不适配失败" in turn_calls[0]["prompt"]
    assert "当前运行仍未恢复" in turn_calls[0]["prompt"]
    assert "不得从最近 Git 记忆推断未验证需求" in turn_calls[0]["prompt"]
    assert "当前观察结果" in turn_calls[1]["prompt"]
    assert "本阶段的工具预算已经独立重置" in turn_calls[1]["prompt"]
    assert "必须与观察摘要中已验证的问题一致" in turn_calls[1]["prompt"]
    assert "不得改用仅来自 GIT_MEMORY" in turn_calls[1]["prompt"]
    assert "TARGET_FILES_JSON" in turn_calls[1]["prompt"]
    assert turn_calls[2]["binding"]["workspacePath"] == (
        "C:/workspace/self-loop-candidate"
    )
    assert turn_calls[2]["allowed_target_paths"] == [
        "C:\\workspace\\self-loop-candidate\\core\\example.py",
        "C:\\workspace\\self-loop-candidate\\tests\\test_example.py",
    ]
    assert "不得执行评分" in turn_calls[2]["prompt"]
    assert observation["conversationSessionId"] == "session-observer"
    assert plan["steps"][1]["id"] == "git"
    assert candidate["conversationSessionId"] == "session-executor"
    assert candidate["variantId"] == "variant-001"
    assert candidate["changedFiles"] == [
        "core/example.py",
        "tests/test_example.py",
    ]


def test_runtime_plan_rejects_missing_structured_target_files():
    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {
                    "agentId": "observer-agent",
                    "directSessionId": "session-observer",
                },
                "executor": {"agentId": "executor-agent"},
            },
            run_role_turn=lambda **_kwargs: {
                "result": {
                    "status": "completed",
                    "summary": "修改 core/example.py 并补充测试。",
                },
                "carryover": {},
                "conversationSessionId": "session-observer",
            },
            create_candidate=lambda _context: {},
            inspect_candidate=lambda _context: {},
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    with pytest.raises(
        AutonomousLoopRuntimeError,
        match="structured target files",
    ):
        hooks.plan(
            _snapshot(
                observation={
                    "summary": "已确认问题",
                    "evidence": [],
                    "conversationSessionId": "session-observer",
                },
                plan=None,
                candidate=None,
            )
        )


def test_runtime_plan_parses_target_files_from_visible_marker():
    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {
                    "agentId": "observer-agent",
                    "directSessionId": "session-observer",
                },
                "executor": {"agentId": "executor-agent"},
            },
            run_role_turn=lambda **_kwargs: {
                "result": {
                    "status": "completed",
                    "summary": (
                        "修改候选运行契约并补充测试。\n"
                        'TARGET_FILES_JSON: ["core/example.py", '
                        '"tests/test_example.py"]'
                    ),
                },
                "carryover": {},
                "conversationSessionId": "session-observer",
            },
            create_candidate=lambda _context: {},
            inspect_candidate=lambda _context: {},
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    plan = hooks.plan(
        _snapshot(
            observation={
                "summary": "已确认问题",
                "evidence": [],
                "conversationSessionId": "session-observer",
            },
            plan=None,
            candidate=None,
        )
    )

    assert plan["targetFiles"] == [
        "core/example.py",
        "tests/test_example.py",
    ]


def test_runtime_plan_retries_once_without_tools_for_invalid_target_contract():
    turn_calls: list[dict] = []

    def run_role_turn(**kwargs):
        turn_calls.append(deepcopy(kwargs))
        if len(turn_calls) == 1:
            return {
                "result": {
                    "status": "completed",
                    "summary": "读取运行证据并修改实现。",
                    "targetFiles": [
                        "logs/runtime_scenes/latest/summary.json",
                        "core/example.py",
                    ],
                },
                "carryover": {"previousResponseId": "response-invalid-plan"},
                "conversationSessionId": "session-observer",
            }
        return {
            "result": {
                "status": "completed",
                "summary": "纠正目标清单，只修改源码与测试。",
                "targetFiles": ["core/example.py", "tests/test_example.py"],
            },
            "carryover": {"previousResponseId": "response-corrected-plan"},
            "conversationSessionId": "session-observer",
        }

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {
                    "agentId": "observer-agent",
                    "directSessionId": "session-observer",
                },
                "executor": {"agentId": "executor-agent"},
            },
            run_role_turn=run_role_turn,
            create_candidate=lambda _context: {},
            inspect_candidate=lambda _context: {},
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    plan = hooks.plan(
        _snapshot(
            observation={
                "summary": "已确认一个源码可观测性缺口。",
                "evidence": [],
                "conversationSessionId": "session-observer",
            },
            plan=None,
            candidate=None,
        )
    )

    assert plan["targetFiles"] == [
        "core/example.py",
        "tests/test_example.py",
    ]
    assert len(turn_calls) == 2
    assert turn_calls[1]["carryover"] == {
        "previousResponseId": "response-invalid-plan"
    }
    assert turn_calls[1]["runtime_tool_grants"] == []
    assert turn_calls[1]["disable_tools"] is True
    assert turn_calls[1]["max_iterations"] == 1
    assert "结构化目标文件清单违反了宿主安全契约" in turn_calls[1]["prompt"]
    assert "不要读取或修改被拒绝的路径" in turn_calls[1]["prompt"]
    assert "logs/runtime_scenes/latest/summary.json" not in (
        turn_calls[1]["prompt"]
    )


def test_runtime_plan_corrects_targets_outside_explicit_user_file_scope(
    monkeypatch,
):
    turn_calls: list[dict] = []
    scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.services.self_evolution_autonomous_loop_runtime."
        "record_runtime_scene_event",
        lambda *args, **kwargs: scene_events.append((args, kwargs)),
    )

    def run_role_turn(**kwargs):
        turn_calls.append(deepcopy(kwargs))
        if len(turn_calls) == 1:
            return {
                "result": {
                    "status": "completed",
                    "summary": "改做无关浏览器恢复。",
                    "targetFiles": [
                        "web/src/lib/browser/api.ts",
                        "web/src/lib/browser/api.test.ts",
                    ],
                },
                "carryover": {"previousResponseId": "response-drifted-plan"},
                "conversationSessionId": "session-observer",
            }
        return {
            "result": {
                "status": "completed",
                "summary": "纠正为用户明确限定的两个文件。",
                "targetFiles": [
                    "core/web/services/self_evolution_control_service.py",
                    "tests/test_self_evolution_control_service.py",
                ],
            },
            "carryover": {"previousResponseId": "response-corrected-plan"},
            "conversationSessionId": "session-observer",
        }

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {
                    "agentId": "observer-agent",
                    "directSessionId": "session-observer",
                },
                "executor": {"agentId": "executor-agent"},
            },
            run_role_turn=run_role_turn,
            create_candidate=lambda _context: {},
            inspect_candidate=lambda _context: {},
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    plan = hooks.plan(
        _snapshot(
            request={
                "goal": (
                    "计划和修改范围必须且只能是 "
                    "core/web/services/self_evolution_control_service.py "
                    "与 tests/test_self_evolution_control_service.py。"
                ),
                "maxIterations": 1,
            },
            observation={
                "summary": "已确认候选 Git 绑定缺少有界事件。",
                "evidence": [],
                "conversationSessionId": "session-observer",
            },
            plan=None,
            candidate=None,
        )
    )

    assert len(turn_calls) == 2
    assert plan["targetFiles"] == [
        "core/web/services/self_evolution_control_service.py",
        "tests/test_self_evolution_control_service.py",
    ]
    assert turn_calls[1]["runtime_tool_grants"] == []
    assert turn_calls[1]["disable_tools"] is True
    assert "用户明确限定的可修改文件" in turn_calls[1]["prompt"]
    assert "core/web/services/self_evolution_control_service.py" in (
        turn_calls[1]["prompt"]
    )
    assert "web/src/lib/browser/api.ts" not in turn_calls[1]["prompt"]
    assert scene_events[0][1]["fields"]["reason"] == (
        "request_target_mismatch"
    )


@pytest.mark.parametrize(
    "target_file",
    [
        "../outside.py",
        "C:/outside.py",
        ".git/config",
        "workspace/prompts/DYNAMIC.md",
        "docs/standards/development-standard.md",
    ],
)
def test_runtime_plan_rejects_forbidden_target_files(target_file):
    turn_count = 0

    def run_role_turn(**_kwargs):
        nonlocal turn_count
        turn_count += 1
        return {
            "result": {
                "status": "completed",
                "summary": "有界计划",
                "targetFiles": [target_file],
            },
            "carryover": {},
            "conversationSessionId": "session-observer",
        }

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {
                    "agentId": "observer-agent",
                    "directSessionId": "session-observer",
                },
                "executor": {"agentId": "executor-agent"},
            },
            run_role_turn=run_role_turn,
            create_candidate=lambda _context: {},
            inspect_candidate=lambda _context: {},
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    with pytest.raises(AutonomousLoopRuntimeError, match="target file"):
        hooks.plan(
            _snapshot(
                observation={
                    "summary": "已确认问题",
                    "evidence": [],
                    "conversationSessionId": "session-observer",
                },
                plan=None,
                candidate=None,
            )
        )
    assert turn_count == 2


def test_runtime_rejects_candidate_diff_outside_planned_target_files(monkeypatch):
    scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.services.self_evolution_candidate_target_contract."
        "record_runtime_scene_event",
        lambda *args, **kwargs: scene_events.append((args, kwargs)),
    )
    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {"agentId": "observer-agent"},
                "executor": {"agentId": "executor-agent"},
            },
            run_role_turn=lambda **_kwargs: {
                "result": {
                    "status": "completed",
                    "summary": "候选实现完成。",
                    "tool_trace": [
                        {"name": "apply_patch_tool", "status": "success"},
                    ],
                },
                "carryover": {},
                "conversationSessionId": "session-executor",
            },
            create_candidate=lambda _context: {
                "branch": "codex/self-loop-candidate",
                "worktreePath": "C:/workspace/self-loop-candidate",
                "baseCommit": "a" * 40,
            },
            inspect_candidate=lambda _context: {
                "headCommit": "b" * 40,
                "changedFiles": ["core/unplanned.py"],
                "variantId": "variant-outside-plan",
            },
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    with pytest.raises(
        AutonomousLoopRuntimeError,
        match="outside planned target files",
    ):
        hooks.evolve(
            _snapshot(
                plan={
                    "summary": "只修改计划文件",
                    "steps": [],
                    "targetFiles": ["core/example.py"],
                },
                candidate=None,
            )
        )
    assert scene_events[-1][0][2] == (
        "self_evolution.autonomous_loop.candidate_boundary_blocked"
    )
    assert scene_events[-1][1]["fields"]["changedFileCount"] == 1
    assert scene_events[-1][1]["fields"]["outsideTargetCount"] == 1


def test_observer_exhaustion_gets_one_tool_disabled_summary_turn(monkeypatch):
    turn_calls: list[dict] = []
    scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.services.self_evolution_autonomous_loop_runtime."
        "record_runtime_scene_event",
        lambda *args, **kwargs: scene_events.append((args, kwargs)),
    )

    def run_role_turn(**kwargs):
        turn_calls.append(deepcopy(kwargs))
        if len(turn_calls) == 1:
            return {
                "result": {
                    "status": "stopped",
                    "summary": "已达到本轮最大迭代次数 4。",
                    "max_iteration_exhausted": True,
                    "tool_call_count": 8,
                    "tool_trace": [
                        {"name": "grep_search_tool", "status": "success"}
                    ],
                },
                "carryover": {"previousResponseId": "response-observe-tools"},
                "conversationSessionId": "session-observer",
            }
        return {
            "result": {
                "status": "completed",
                "summary": "已完成有界观察摘要。",
                "tool_call_count": 0,
            },
            "carryover": {"previousResponseId": "response-observe-summary"},
            "conversationSessionId": "session-observer",
        }

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {
                    "agentId": "observer-agent",
                    "directSessionId": "session-observer",
                },
                "executor": {"agentId": "executor-agent"},
            },
            run_role_turn=run_role_turn,
            create_candidate=lambda _context: {},
            inspect_candidate=lambda _context: {},
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    observation = hooks.observe(_snapshot(observation=None, plan=None, candidate=None))

    assert observation["summary"] == "已完成有界观察摘要。"
    assert len(turn_calls) == 2
    assert turn_calls[0]["max_iterations"] == 4
    assert turn_calls[0]["disable_tools"] is False
    assert turn_calls[1]["max_iterations"] == 2
    assert turn_calls[1]["disable_tools"] is True
    assert turn_calls[1]["runtime_tool_grants"] == []
    assert turn_calls[1]["carryover"] == {
        "previousResponseId": "response-observe-tools"
    }
    assert "停止调用工具" in turn_calls[1]["prompt"]
    assert scene_events[0][0][2] == (
        "self_evolution.autonomous_loop.analysis_finalization_requested"
    )


def test_runtime_integration_and_cleanup_hooks_are_deterministic_passthroughs():
    captured: list[tuple[str, dict]] = []
    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {},
            run_role_turn=lambda **_kwargs: {},
            create_candidate=lambda _context: {},
            inspect_candidate=lambda _context: {},
            integrate_candidate=lambda context: captured.append(
                ("integrate", deepcopy(context))
            )
            or {
                "status": "committed",
                "commitSha": "d" * 40,
                "candidateVariantId": context["candidate"]["variantId"],
            },
            cleanup_candidate=lambda context: captured.append(
                ("cleanup", deepcopy(context))
            )
            or {
                "status": "cleaned",
                "worktreeRemoved": True,
                "localBranchDeleted": True,
            },
        )
    )

    integration = hooks.integrate(_snapshot())
    cleanup = hooks.cleanup(_snapshot())

    assert [name for name, _ in captured] == ["integrate", "cleanup"]
    assert integration["commitSha"] == "d" * 40
    assert cleanup["localBranchDeleted"] is True


@pytest.mark.parametrize("status", ["failed", "stopped"])
def test_runtime_rejects_non_successful_agent_turn(status):
    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {"agentId": "observer-agent"},
                "executor": {"agentId": "executor-agent"},
            },
            run_role_turn=lambda **_kwargs: {
                "result": {"status": status, "error": "model unavailable"},
                "carryover": {},
            },
            create_candidate=lambda _context: {},
            inspect_candidate=lambda _context: {},
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    with pytest.raises(AutonomousLoopRuntimeError, match="model unavailable"):
        hooks.observe(_snapshot(observation=None, plan=None, candidate=None))


def test_runtime_rejects_candidate_without_changed_files():
    turn_calls = 0

    def run_role_turn(**_kwargs):
        nonlocal turn_calls
        turn_calls += 1
        return {
            "result": {"status": "completed", "summary": "完成"},
            "carryover": {},
            "conversationSessionId": "session-executor",
        }

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {"agentId": "observer-agent"},
                "executor": {
                    "agentId": "executor-agent",
                    "workspacePath": "C:/workspace/main",
                },
            },
            run_role_turn=run_role_turn,
            create_candidate=lambda _context: {
                "branch": "codex/self-loop-candidate",
                "worktreePath": "C:/workspace/self-loop-candidate",
                "baseCommit": "a" * 40,
            },
            inspect_candidate=lambda _context: {
                "headCommit": "a" * 40,
                "changedFiles": [],
                "variantId": "",
            },
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    with pytest.raises(AutonomousLoopRuntimeError, match="no changed files"):
        hooks.evolve(_snapshot(candidate=None))
    assert turn_calls == 2


def test_runtime_retries_executor_once_when_first_turn_only_repeats_the_plan(
    monkeypatch,
):
    turn_calls: list[dict] = []
    inspection_calls = 0
    scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.services.self_evolution_autonomous_loop_runtime."
        "record_runtime_scene_event",
        lambda *args, **kwargs: scene_events.append((args, kwargs)),
    )

    def run_role_turn(**kwargs):
        turn_calls.append(deepcopy(kwargs))
        if len(turn_calls) == 1:
            return {
                "result": {
                    "status": "completed",
                    "summary": "我已经制定计划，请确认后再执行。",
                    "tool_call_count": 0,
                },
                "carryover": {"previousResponseId": "response-plan-only"},
                "conversationSessionId": "session-executor",
            }
        return {
            "result": {
                "status": "completed",
                "summary": "已实施候选并完成聚焦验证。",
                "tool_call_count": 3,
                "tool_trace": [
                    {"name": "open_evolution_transaction_tool", "status": "success"},
                    {"name": "apply_patch_tool", "status": "success"},
                    {"name": "close_evolution_transaction_tool", "status": "success"},
                ],
            },
            "carryover": {"previousResponseId": "response-implemented"},
            "conversationSessionId": "session-executor",
        }

    def inspect_candidate(_context):
        nonlocal inspection_calls
        inspection_calls += 1
        if inspection_calls == 1:
            return {
                "headCommit": "a" * 40,
                "changedFiles": [],
                "variantId": "",
            }
        return {
            "headCommit": "b" * 40,
            "changedFiles": ["core/example.py"],
            "variantId": "variant-retry",
        }

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {"agentId": "observer-agent"},
                "executor": {
                    "agentId": "executor-agent",
                    "workspacePath": "C:/workspace/main",
                },
            },
            run_role_turn=run_role_turn,
            create_candidate=lambda _context: {
                "branch": "codex/self-loop-candidate",
                "worktreePath": "C:/workspace/self-loop-candidate",
                "baseCommit": "a" * 40,
            },
            inspect_candidate=inspect_candidate,
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    candidate = hooks.evolve(_snapshot(candidate=None))

    assert len(turn_calls) == 3
    assert inspection_calls == 3
    assert turn_calls[1]["carryover"] == {
        "previousResponseId": "response-plan-only"
    }
    assert "不要复述计划" in turn_calls[1]["prompt"]
    assert "无需再次请求用户确认" in turn_calls[1]["prompt"]
    assert turn_calls[1]["runtime_tool_grants"] == [
        "apply_patch_tool",
        "write_file_tool",
    ]
    assert turn_calls[1]["max_iterations"] == 1
    assert "第一项工具调用必须产生文件修改" in turn_calls[1]["prompt"]
    assert turn_calls[2]["runtime_tool_grants"] == [
        "open_evolution_transaction_tool",
        "close_evolution_transaction_tool",
        "cli_tool",
        "python_lint_tool",
    ]
    assert turn_calls[2]["max_iterations"] == 8
    assert "候选已经产生文件变更" in turn_calls[2]["prompt"]
    assert candidate["changedFiles"] == ["core/example.py"]
    assert candidate["variantId"] == "variant-retry"
    assert scene_events[0][0][2] == (
        "self_evolution.autonomous_loop.executor_retry_requested"
    )
    assert scene_events[0][1]["fields"]["reason"] == (
        "no_tool_calls_and_no_changed_files"
    )


def test_runtime_retries_executor_once_when_first_turn_only_inspects_candidate(
    monkeypatch,
):
    turn_calls: list[dict] = []
    inspection_calls = 0
    scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.services.self_evolution_autonomous_loop_runtime."
        "record_runtime_scene_event",
        lambda *args, **kwargs: scene_events.append((args, kwargs)),
    )

    def run_role_turn(**kwargs):
        turn_calls.append(deepcopy(kwargs))
        if len(turn_calls) == 1:
            return {
                "result": {
                    "status": "completed",
                    "summary": "已读取目标源码并确认现有测试。",
                    "tool_call_count": 5,
                    "tool_trace": [
                        {
                            "name": "open_evolution_transaction_tool",
                            "status": "success",
                        },
                        {"name": "glob_tool", "status": "success"},
                        {"name": "cli_tool", "status": "success"},
                    ],
                },
                "carryover": {"previousResponseId": "response-inspection-only"},
                "conversationSessionId": "session-executor",
            }
        return {
            "result": {
                "status": "completed",
                "summary": "已实施候选并完成聚焦验证。",
                "tool_call_count": 3,
                "tool_trace": [
                    {"name": "apply_patch_tool", "status": "success"},
                    {"name": "cli_tool", "status": "success"},
                    {
                        "name": "close_evolution_transaction_tool",
                        "status": "success",
                    },
                ],
            },
            "carryover": {"previousResponseId": "response-implemented"},
            "conversationSessionId": "session-executor",
        }

    def inspect_candidate(_context):
        nonlocal inspection_calls
        inspection_calls += 1
        if inspection_calls == 1:
            return {
                "headCommit": "a" * 40,
                "changedFiles": [],
                "variantId": "",
            }
        return {
            "headCommit": "b" * 40,
            "changedFiles": ["tests/test_example.py"],
            "variantId": "variant-inspection-retry",
        }

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {"agentId": "observer-agent"},
                "executor": {
                    "agentId": "executor-agent",
                    "workspacePath": "C:/workspace/main",
                },
            },
            run_role_turn=run_role_turn,
            create_candidate=lambda _context: {
                "branch": "codex/self-loop-candidate",
                "worktreePath": "C:/workspace/self-loop-candidate",
                "baseCommit": "a" * 40,
            },
            inspect_candidate=inspect_candidate,
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    candidate = hooks.evolve(_snapshot(candidate=None))

    assert len(turn_calls) == 3
    assert inspection_calls == 3
    assert turn_calls[1]["carryover"] == {
        "previousResponseId": "response-inspection-only"
    }
    assert turn_calls[1]["runtime_tool_grants"] == [
        "apply_patch_tool",
        "write_file_tool",
    ]
    assert turn_calls[2]["runtime_tool_grants"] == [
        "close_evolution_transaction_tool",
        "cli_tool",
        "python_lint_tool",
    ]
    assert "已有事务已经开账" in turn_calls[2]["prompt"]
    assert candidate["changedFiles"] == ["tests/test_example.py"]
    assert scene_events[0][1]["fields"]["reason"] == (
        "tool_calls_but_no_changed_files"
    )


def test_runtime_recovers_once_when_executor_exhausts_before_mutation(
    monkeypatch,
):
    turn_calls: list[dict] = []
    inspection_calls = 0
    scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.services.self_evolution_autonomous_loop_runtime."
        "record_runtime_scene_event",
        lambda *args, **kwargs: scene_events.append((args, kwargs)),
    )

    def run_role_turn(**kwargs):
        turn_calls.append(deepcopy(kwargs))
        if len(turn_calls) == 1:
            return {
                "result": {
                    "status": "failed",
                    "summary": "已达到本轮最大迭代次数 24。",
                    "max_iteration_exhausted": True,
                    "tool_call_count": 24,
                    "tool_trace": [
                        {"name": "code_symbol_tool", "status": "success"}
                    ],
                },
                "carryover": {"previousResponseId": "response-exhausted"},
                "conversationSessionId": "session-executor",
            }
        if len(turn_calls) == 2:
            return {
                "result": {
                    "status": "completed",
                    "summary": "已完成聚焦修改。",
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "apply_patch_tool", "status": "success"}
                    ],
                },
                "carryover": {"previousResponseId": "response-mutated"},
                "conversationSessionId": "session-executor",
            }
        return {
            "result": {
                "status": "completed",
                "summary": "已完成聚焦验证。",
                "tool_call_count": 3,
                "tool_trace": [
                    {
                        "name": "open_evolution_transaction_tool",
                        "status": "success",
                    },
                    {"name": "cli_tool", "status": "success"},
                    {
                        "name": "close_evolution_transaction_tool",
                        "status": "success",
                    },
                ],
            },
            "carryover": {"previousResponseId": "response-validated"},
            "conversationSessionId": "session-executor",
        }

    def inspect_candidate(_context):
        nonlocal inspection_calls
        inspection_calls += 1
        if inspection_calls == 1:
            return {
                "headCommit": "a" * 40,
                "changedFiles": [],
                "variantId": "",
            }
        return {
            "headCommit": "b" * 40,
            "changedFiles": ["core/example.py"],
            "variantId": "variant-exhaustion-recovery",
        }

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {"agentId": "observer-agent"},
                "executor": {
                    "agentId": "executor-agent",
                    "workspacePath": "C:/workspace/main",
                },
            },
            run_role_turn=run_role_turn,
            create_candidate=lambda _context: {
                "branch": "codex/self-loop-candidate",
                "worktreePath": "C:/workspace/self-loop-candidate",
                "baseCommit": "a" * 40,
            },
            inspect_candidate=inspect_candidate,
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    candidate = hooks.evolve(_snapshot(candidate=None))

    assert len(turn_calls) == 3
    assert inspection_calls == 3
    assert turn_calls[1]["carryover"] == {
        "previousResponseId": "response-exhausted"
    }
    assert turn_calls[1]["runtime_tool_grants"] == [
        "apply_patch_tool",
        "write_file_tool",
    ]
    assert turn_calls[1]["max_iterations"] == 1
    assert turn_calls[2]["carryover"] == {
        "previousResponseId": "response-mutated"
    }
    assert turn_calls[2]["runtime_tool_grants"] == [
        "open_evolution_transaction_tool",
        "close_evolution_transaction_tool",
        "cli_tool",
        "python_lint_tool",
    ]
    assert turn_calls[2]["max_iterations"] == 8
    assert candidate["changedFiles"] == ["core/example.py"]
    assert candidate["variantId"] == "variant-exhaustion-recovery"
    assert scene_events[0][0][2] == (
        "self_evolution.autonomous_loop.executor_retry_requested"
    )
    assert scene_events[0][1]["fields"]["reason"] == (
        "max_iterations_exhausted_no_changed_files"
    )


def test_runtime_accepts_single_mutation_tool_step_before_validation():
    turn_calls: list[dict] = []
    inspection_calls = 0

    def run_role_turn(**kwargs):
        turn_calls.append(deepcopy(kwargs))
        if len(turn_calls) == 1:
            return {
                "result": {
                    "status": "completed",
                    "summary": "已定位需要补充的测试。",
                    "tool_call_count": 2,
                    "tool_trace": [
                        {"name": "code_symbol_tool", "status": "success"}
                    ],
                },
                "carryover": {"previousResponseId": "response-inspected"},
                "conversationSessionId": "session-executor",
            }
        if len(turn_calls) == 2:
            return {
                "result": {
                    "status": "failed",
                    "summary": "单步 mutation 已产生文件修改。",
                    "max_iteration_exhausted": True,
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "apply_patch_tool", "status": "success"}
                    ],
                },
                "carryover": {"previousResponseId": "response-mutated"},
                "conversationSessionId": "session-executor",
            }
        return {
            "result": {
                "status": "completed",
                "summary": "已完成聚焦验证。",
                "tool_call_count": 3,
                "tool_trace": [
                    {
                        "name": "open_evolution_transaction_tool",
                        "status": "success",
                    },
                    {"name": "cli_tool", "status": "success"},
                    {
                        "name": "close_evolution_transaction_tool",
                        "status": "success",
                    },
                ],
            },
            "carryover": {"previousResponseId": "response-validated"},
            "conversationSessionId": "session-executor",
        }

    def inspect_candidate(_context):
        nonlocal inspection_calls
        inspection_calls += 1
        if inspection_calls == 1:
            return {
                "headCommit": "a" * 40,
                "changedFiles": [],
                "variantId": "",
            }
        return {
            "headCommit": "b" * 40,
            "changedFiles": ["tests/test_example.py"],
            "variantId": "variant-single-mutation",
        }

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {"agentId": "observer-agent"},
                "executor": {
                    "agentId": "executor-agent",
                    "workspacePath": "C:/workspace/main",
                },
            },
            run_role_turn=run_role_turn,
            create_candidate=lambda _context: {
                "branch": "codex/self-loop-candidate",
                "worktreePath": "C:/workspace/self-loop-candidate",
                "baseCommit": "a" * 40,
            },
            inspect_candidate=inspect_candidate,
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    candidate = hooks.evolve(_snapshot(candidate=None))

    assert len(turn_calls) == 3
    assert turn_calls[1]["max_iterations"] == 1
    assert turn_calls[2]["carryover"] == {
        "previousResponseId": "response-mutated"
    }
    assert candidate["changedFiles"] == ["tests/test_example.py"]
    assert candidate["variantId"] == "variant-single-mutation"


def test_runtime_mutation_retry_receives_bounded_exact_target_context(tmp_path):
    target = tmp_path / "core" / "example.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "def target_function():\n"
        "    api_key = \"sk-live-secret\"\n"
        "    current_value = 'before'\n"
        "    return current_value\n",
        encoding="utf-8",
    )
    turn_calls: list[dict] = []
    inspection_calls = 0

    def run_role_turn(**kwargs):
        turn_calls.append(deepcopy(kwargs))
        if len(turn_calls) == 1:
            return {
                "result": {
                    "status": "completed",
                    "summary": "已定位 target_function。",
                    "tool_call_count": 2,
                    "tool_trace": [
                        {
                            "name": "open_evolution_transaction_tool",
                            "status": "success",
                        },
                        {"name": "code_symbol_tool", "status": "success"},
                    ],
                },
                "carryover": {"previousResponseId": "response-inspected"},
            }
        return {
            "result": {
                "status": "failed",
                "error": "stop after prompt capture",
            },
            "carryover": {},
        }

    def inspect_candidate(_context):
        nonlocal inspection_calls
        inspection_calls += 1
        return {
            "headCommit": "a" * 40,
            "changedFiles": [],
            "variantId": "",
        }

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {"agentId": "observer-agent"},
                "executor": {"agentId": "executor-agent"},
            },
            run_role_turn=run_role_turn,
            create_candidate=lambda _context: {
                "branch": "codex/self-loop-candidate",
                "worktreePath": str(tmp_path),
                "baseCommit": "a" * 40,
            },
            inspect_candidate=inspect_candidate,
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    context = _snapshot(candidate=None)
    context["plan"]["targetFiles"] = ["core/example.py"]
    context["plan"]["summary"] = "修改 target_function 的 current_value。"

    with pytest.raises(
        AutonomousLoopRuntimeError,
        match="stop after prompt capture",
    ):
        hooks.evolve(context)

    assert turn_calls[0]["max_iterations"] <= 12
    assert "cli_tool" not in turn_calls[0]["runtime_tool_grants"]
    mutation_prompt = turn_calls[1]["prompt"]
    assert "精确源码上下文" in mutation_prompt
    assert "def target_function():" in mutation_prompt
    assert "    current_value = 'before'" in mutation_prompt
    assert "sk-live-secret" not in mutation_prompt
    assert "api_key = \"[REDACTED]\"" in mutation_prompt


def test_runtime_failure_closes_only_transaction_opened_by_this_evolution(
    monkeypatch,
):
    closed: list[tuple[str, str, str]] = []

    class FakeSession:
        active = ""

        def get_active_evolution_txn(self):
            return self.active

        def set_active_evolution_txn(self, value):
            self.active = str(value or "")

    class FakeGitMemory:
        def close_evolution_transaction(self, txn_id, status, summary=""):
            closed.append((txn_id, status, summary))

    session = FakeSession()
    monkeypatch.setattr(
        "core.web.services.self_evolution_autonomous_loop_runtime."
        "get_session_state",
        lambda: session,
    )
    monkeypatch.setattr(
        "core.web.services.self_evolution_autonomous_loop_runtime."
        "get_git_memory_service",
        lambda: FakeGitMemory(),
    )

    def run_role_turn(**_kwargs):
        session.active = "txn-self-loop"
        return {
            "result": {
                "status": "failed",
                "error": "executor transport failed",
            },
            "carryover": {},
        }

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {"agentId": "observer-agent"},
                "executor": {"agentId": "executor-agent"},
            },
            run_role_turn=run_role_turn,
            create_candidate=lambda _context: {
                "branch": "codex/self-loop-candidate",
                "worktreePath": "C:/workspace/self-loop-candidate",
                "baseCommit": "a" * 40,
            },
            inspect_candidate=lambda _context: {},
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    with pytest.raises(
        AutonomousLoopRuntimeError,
        match="executor transport failed",
    ):
        hooks.evolve(_snapshot(candidate=None))

    assert closed == [
        (
            "txn-self-loop",
            "failed",
            "self-evolution candidate failed before transaction close",
        )
    ]
    assert session.active == ""


def test_runtime_does_not_recover_executor_failure_without_exhaustion():
    turn_calls = 0
    inspection_calls = 0

    def run_role_turn(**_kwargs):
        nonlocal turn_calls
        turn_calls += 1
        return {
            "result": {
                "status": "failed",
                "error": "executor transport failed",
            },
            "carryover": {},
        }

    def inspect_candidate(_context):
        nonlocal inspection_calls
        inspection_calls += 1
        return {}

    hooks = build_autonomous_loop_hooks(
        AutonomousLoopRuntimeDependencies(
            load_bindings=lambda: {
                "observer": {"agentId": "observer-agent"},
                "executor": {"agentId": "executor-agent"},
            },
            run_role_turn=run_role_turn,
            create_candidate=lambda _context: {
                "branch": "codex/self-loop-candidate",
                "worktreePath": "C:/workspace/self-loop-candidate",
                "baseCommit": "a" * 40,
            },
            inspect_candidate=inspect_candidate,
            integrate_candidate=lambda _context: {},
            cleanup_candidate=lambda _context: {},
        )
    )

    with pytest.raises(
        AutonomousLoopRuntimeError,
        match="executor transport failed",
    ):
        hooks.evolve(_snapshot(candidate=None))

    assert turn_calls == 1
    assert inspection_calls == 0
