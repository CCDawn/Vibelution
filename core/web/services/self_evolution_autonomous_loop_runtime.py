"""Agent execution adapter for the no-score self-evolution lifecycle."""

from __future__ import annotations

import threading
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from .self_evolution_autonomous_loop_service import AutonomousLoopHooks


RuntimeCallable = Callable[[dict[str, Any]], dict[str, Any]]
RoleTurnCallable = Callable[..., dict[str, Any]]
BindingsCallable = Callable[[], dict[str, dict[str, Any]]]
AUTONOMOUS_RUNTIME_TOOL_SOURCE = "self_evolution_autonomous_loop"
OBSERVER_RUNTIME_TOOLS = (
    "grep_search_tool",
    "code_symbol_tool",
)
EXECUTOR_RUNTIME_TOOLS = (
    "open_evolution_transaction_tool",
    "close_evolution_transaction_tool",
    "grep_search_tool",
    "code_symbol_tool",
    "apply_patch_tool",
    "write_file_tool",
    "cli_tool",
    "python_lint_tool",
)


class AutonomousLoopRuntimeError(RuntimeError):
    """Raised when an Agent or candidate runtime cannot satisfy its contract."""


@dataclass(frozen=True)
class AutonomousLoopRuntimeDependencies:
    load_bindings: BindingsCallable
    run_role_turn: RoleTurnCallable
    create_candidate: RuntimeCallable
    inspect_candidate: RuntimeCallable
    integrate_candidate: RuntimeCallable
    cleanup_candidate: RuntimeCallable


def build_autonomous_loop_hooks(
    dependencies: AutonomousLoopRuntimeDependencies,
) -> AutonomousLoopHooks:
    """Bind Agent observation/planning/evolution to deterministic side effects."""

    state_lock = threading.RLock()
    carryovers: dict[str, dict[str, Any]] = {}
    bindings_by_run: dict[str, dict[str, dict[str, Any]]] = {}

    def bindings_for(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
        run_id = _run_id(context)
        with state_lock:
            cached = bindings_by_run.get(run_id)
            if cached is not None:
                return deepcopy(cached)
            bindings = dependencies.load_bindings()
            if not isinstance(bindings, dict):
                raise AutonomousLoopRuntimeError(
                    "Self-evolution Agent bindings are unavailable."
                )
            normalized = {
                str(role): deepcopy(binding)
                for role, binding in bindings.items()
                if isinstance(binding, dict)
            }
            for required_role in ("observer", "executor"):
                if not str(
                    (normalized.get(required_role) or {}).get("agentId") or ""
                ).strip():
                    raise AutonomousLoopRuntimeError(
                        f"Self-evolution {required_role} Agent is not configured."
                    )
            bindings_by_run[run_id] = normalized
            return deepcopy(normalized)

    def observe(context: dict[str, Any]) -> dict[str, Any]:
        run_id = _run_id(context)
        binding = bindings_for(context)["observer"]
        turn = _run_successful_turn(
            dependencies.run_role_turn,
            role="observer",
            binding=binding,
            run_id=run_id,
            prompt=_observation_prompt(context),
            carryover=None,
            runtime_tool_grants=list(OBSERVER_RUNTIME_TOOLS),
            runtime_tool_source=AUTONOMOUS_RUNTIME_TOOL_SOURCE,
        )
        with state_lock:
            carryovers[run_id] = deepcopy(turn.get("carryover") or {})
        result = turn["result"]
        return {
            "summary": _result_summary(result, label="Observation"),
            "evidence": _result_evidence(result),
            "conversationSessionId": _conversation_session_id(turn, binding),
        }

    def plan(context: dict[str, Any]) -> dict[str, Any]:
        run_id = _run_id(context)
        binding = bindings_for(context)["observer"]
        with state_lock:
            carryover = deepcopy(carryovers.get(run_id) or {})
        turn = _run_successful_turn(
            dependencies.run_role_turn,
            role="observer",
            binding=binding,
            run_id=run_id,
            prompt=_planning_prompt(context),
            carryover=carryover,
            runtime_tool_grants=list(OBSERVER_RUNTIME_TOOLS),
            runtime_tool_source=AUTONOMOUS_RUNTIME_TOOL_SOURCE,
        )
        result = turn["result"]
        with state_lock:
            carryovers.pop(run_id, None)
        return {
            "summary": _result_summary(result, label="Plan"),
            "steps": _plan_steps(result),
            "conversationSessionId": _conversation_session_id(turn, binding),
        }

    def evolve(context: dict[str, Any]) -> dict[str, Any]:
        run_id = _run_id(context)
        bindings = bindings_for(context)
        workspace = dependencies.create_candidate(deepcopy(context))
        if not isinstance(workspace, dict):
            raise AutonomousLoopRuntimeError(
                "Candidate workspace creation returned an invalid result."
            )
        worktree_path = str(workspace.get("worktreePath") or "").strip()
        branch = str(workspace.get("branch") or "").strip()
        base_commit = str(workspace.get("baseCommit") or "").strip()
        if not worktree_path or not branch or not base_commit:
            raise AutonomousLoopRuntimeError(
                "Candidate workspace is missing branch, worktreePath, or baseCommit."
            )
        executor_binding = deepcopy(bindings["executor"])
        executor_binding["workspacePath"] = worktree_path
        turn = _run_successful_turn(
            dependencies.run_role_turn,
            role="executor",
            binding=executor_binding,
            run_id=run_id,
            prompt=_evolution_prompt(context),
            carryover=None,
            runtime_tool_grants=list(EXECUTOR_RUNTIME_TOOLS),
            runtime_tool_source=AUTONOMOUS_RUNTIME_TOOL_SOURCE,
        )
        inspection = dependencies.inspect_candidate(
            {
                "runId": run_id,
                "snapshot": deepcopy(context),
                "candidateWorkspace": deepcopy(workspace),
                "agentResult": deepcopy(turn["result"]),
            }
        )
        if not isinstance(inspection, dict):
            raise AutonomousLoopRuntimeError(
                "Candidate inspection returned an invalid result."
            )
        changed_files = inspection.get("changedFiles")
        if not isinstance(changed_files, list) or not changed_files:
            raise AutonomousLoopRuntimeError(
                "Candidate has no changed files after evolution."
            )
        result = turn["result"]
        return {
            "summary": _result_summary(result, label="Evolution"),
            "branch": branch,
            "worktreePath": worktree_path,
            "baseCommit": base_commit,
            "headCommit": str(
                inspection.get("headCommit") or base_commit
            ).strip(),
            "changedFiles": deepcopy(changed_files),
            "verification": _result_evidence(result)
            or [{"name": "agent_turn", "outcome": "completed"}],
            "conversationSessionId": _conversation_session_id(
                turn,
                executor_binding,
            ),
            "variantId": str(inspection.get("variantId") or "").strip(),
        }

    def integrate(context: dict[str, Any]) -> dict[str, Any]:
        result = dependencies.integrate_candidate(deepcopy(context))
        if not isinstance(result, dict):
            raise AutonomousLoopRuntimeError(
                "Candidate integration returned an invalid result."
            )
        return result

    def cleanup(context: dict[str, Any]) -> dict[str, Any]:
        result = dependencies.cleanup_candidate(deepcopy(context))
        if not isinstance(result, dict):
            raise AutonomousLoopRuntimeError(
                "Candidate cleanup returned an invalid result."
            )
        return result

    return AutonomousLoopHooks(
        observe=observe,
        plan=plan,
        evolve=evolve,
        integrate=integrate,
        cleanup=cleanup,
    )


def _run_successful_turn(
    runner: RoleTurnCallable,
    **kwargs: Any,
) -> dict[str, Any]:
    turn = runner(**kwargs)
    if not isinstance(turn, dict):
        raise AutonomousLoopRuntimeError("Agent turn returned an invalid result.")
    result = turn.get("result")
    if not isinstance(result, dict):
        raise AutonomousLoopRuntimeError("Agent turn result is missing.")
    status = str(result.get("status") or "").strip().lower()
    if status in {"failed", "stopped", "cancelled", "error"}:
        detail = str(
            result.get("error")
            or result.get("summary")
            or f"Agent turn ended with status={status}"
        ).strip()
        raise AutonomousLoopRuntimeError(detail)
    return turn


def _result_summary(result: dict[str, Any], *, label: str) -> str:
    for key in ("summary", "content", "message", "output"):
        value = str(result.get(key) or "").strip()
        if value:
            return value
    raise AutonomousLoopRuntimeError(f"{label} Agent returned no visible summary.")


def _result_evidence(result: dict[str, Any]) -> list[dict[str, Any]]:
    trace = result.get("tool_trace")
    if not isinstance(trace, list):
        trace = result.get("toolTrace")
    if not isinstance(trace, list):
        return []
    return [deepcopy(item) for item in trace if isinstance(item, dict)]


def _plan_steps(result: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = result.get("steps")
    if not isinstance(raw_steps, list):
        raw_steps = result.get("planSteps")
    steps = [deepcopy(item) for item in raw_steps or [] if isinstance(item, dict)]
    if steps:
        return steps
    return [
        {
            "id": "agent-plan",
            "title": _result_summary(result, label="Plan"),
        }
    ]


def _conversation_session_id(
    turn: dict[str, Any],
    binding: dict[str, Any],
) -> str:
    return str(
        turn.get("conversationSessionId")
        or binding.get("directSessionId")
        or ""
    ).strip()


def _run_id(context: dict[str, Any]) -> str:
    run_id = str(context.get("runId") or "").strip()
    if not run_id:
        raise AutonomousLoopRuntimeError("Autonomous-loop runId is missing.")
    return run_id


def _observation_prompt(context: dict[str, Any]) -> str:
    goal = str((context.get("request") or {}).get("goal") or "").strip()
    return (
        "请以自进化观察 Agent 身份，只读分析当前项目与运行状态。\n"
        f"目标：{goal}\n\n"
        "要求：\n"
        "1. 只报告与目标直接相关的现状、证据、约束和风险。\n"
        "2. 不修改文件，不执行 Git 合入，不做评分或 Judge 判断。\n"
        "3. 给出可供下一轮制定计划的简洁事实摘要。"
    )


def _planning_prompt(context: dict[str, Any]) -> str:
    observation = context.get("observation")
    summary = str(
        (observation or {}).get("summary")
        if isinstance(observation, dict)
        else ""
    ).strip()
    goal = str((context.get("request") or {}).get("goal") or "").strip()
    return (
        "请基于同一会话里的观察结果制定一份有界实施计划。\n"
        f"目标：{goal}\n"
        f"当前观察结果：{summary}\n\n"
        "要求：\n"
        "1. 计划必须能在隔离 worktree 内完成并留下测试证据。\n"
        "2. 不执行计划，不评分，不调用 Judge。\n"
        "3. 明确修改范围、验证方法和停止条件。"
    )


def _evolution_prompt(context: dict[str, Any]) -> str:
    request = context.get("request") if isinstance(context.get("request"), dict) else {}
    observation = (
        context.get("observation")
        if isinstance(context.get("observation"), dict)
        else {}
    )
    plan = context.get("plan") if isinstance(context.get("plan"), dict) else {}
    return (
        "请在当前隔离 worktree 内实施这一轮自进化候选。\n"
        f"目标：{str(request.get('goal') or '').strip()}\n"
        f"观察：{str(observation.get('summary') or '').strip()}\n"
        f"计划：{str(plan.get('summary') or '').strip()}\n\n"
        "要求：\n"
        "1. 只修改计划范围内文件，运行与改动相称的测试。\n"
        "2. 不写主工作区，不刷新 Launcher，不执行远端操作。\n"
        "3. 不得执行评分、Judge 或自行批准合入。\n"
        "4. 完成后报告改动、测试、未覆盖边界和剩余风险。"
    )
