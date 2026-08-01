"""Agent execution adapter for the no-score self-evolution lifecycle."""

from __future__ import annotations

import re
import threading
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from .runtime_scene_service import record_runtime_scene_event
from .self_evolution_candidate_target_contract import (
    CandidateTargetContractError,
    candidate_target_paths,
    extract_plan_target_files,
    normalize_target_files,
    record_plan_target_contract,
    validate_candidate_changes,
)
from .self_evolution_autonomous_loop_service import AutonomousLoopHooks


RuntimeCallable = Callable[[dict[str, Any]], dict[str, Any]]
RoleTurnCallable = Callable[..., dict[str, Any]]
BindingsCallable = Callable[[], dict[str, dict[str, Any]]]
AUTONOMOUS_RUNTIME_TOOL_SOURCE = "self_evolution_autonomous_loop"
OBSERVER_MAX_ITERATIONS = 4
PLANNER_MAX_ITERATIONS = 3
ANALYSIS_FINALIZATION_MAX_ITERATIONS = 2
EXECUTOR_MAX_ITERATIONS = 24
EXECUTOR_MUTATION_MAX_ITERATIONS = 4
EXECUTOR_VALIDATION_MAX_ITERATIONS = 8
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
EXECUTOR_MUTATION_TOOLS = (
    "apply_patch_tool",
    "write_file_tool",
)
EXECUTOR_VALIDATION_TOOLS = (
    "close_evolution_transaction_tool",
    "cli_tool",
    "python_lint_tool",
)
EXPLICIT_TARGET_SCOPE_CUES = (
    "必须且只能",
    "修改范围只能",
    "计划范围只能",
    "仅修改",
    "only modify",
    "must be limited to",
)
REPOSITORY_FILE_REFERENCE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.\-/])"
    r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9]+"
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
        turn = _run_bounded_analysis_turn(
            dependencies.run_role_turn,
            phase="observation",
            role="observer",
            binding=binding,
            run_id=run_id,
            prompt=_observation_prompt(context),
            carryover=None,
            runtime_tool_grants=list(OBSERVER_RUNTIME_TOOLS),
            runtime_tool_source=AUTONOMOUS_RUNTIME_TOOL_SOURCE,
            max_iterations=OBSERVER_MAX_ITERATIONS,
            disable_tools=False,
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
        turn = _run_bounded_analysis_turn(
            dependencies.run_role_turn,
            phase="planning",
            role="observer",
            binding=binding,
            run_id=run_id,
            prompt=_planning_prompt(context),
            carryover=carryover,
            runtime_tool_grants=list(OBSERVER_RUNTIME_TOOLS),
            runtime_tool_source=AUTONOMOUS_RUNTIME_TOOL_SOURCE,
            max_iterations=PLANNER_MAX_ITERATIONS,
            disable_tools=False,
        )
        result = turn["result"]
        with state_lock:
            carryovers.pop(run_id, None)
        try:
            target_files = _plan_target_files(result)
            _validate_plan_targets_against_request(context, target_files)
        except AutonomousLoopRuntimeError as exc:
            requested_target_files = _explicit_request_target_files(context)
            _record_plan_target_correction(
                run_id=run_id,
                reason=_target_contract_error_code(str(exc)),
            )
            turn = _run_successful_turn(
                dependencies.run_role_turn,
                role="observer",
                binding=binding,
                run_id=run_id,
                prompt=_planning_target_correction_prompt(
                    requested_target_files=requested_target_files,
                ),
                carryover=deepcopy(turn.get("carryover") or {}),
                runtime_tool_grants=[],
                runtime_tool_source=AUTONOMOUS_RUNTIME_TOOL_SOURCE,
                max_iterations=1,
                disable_tools=True,
            )
            result = turn["result"]
            target_files = _plan_target_files(result)
            _validate_plan_targets_against_request(context, target_files)
        record_plan_target_contract(
            run_id=run_id,
            target_files=target_files,
        )
        return {
            "summary": _result_summary(result, label="Plan"),
            "steps": _plan_steps(result),
            "targetFiles": target_files,
            "conversationSessionId": _conversation_session_id(turn, binding),
        }

    def evolve(context: dict[str, Any]) -> dict[str, Any]:
        run_id = _run_id(context)
        bindings = bindings_for(context)
        target_files = _target_files_from_context(context)
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
        allowed_target_paths = _candidate_target_paths(
            worktree_path,
            target_files,
        )
        executor_binding = deepcopy(bindings["executor"])
        executor_binding["workspacePath"] = worktree_path
        turn = dependencies.run_role_turn(
            role="executor",
            binding=executor_binding,
            run_id=run_id,
            prompt=_evolution_prompt(context),
            carryover=None,
            runtime_tool_grants=list(EXECUTOR_RUNTIME_TOOLS),
            runtime_tool_source=AUTONOMOUS_RUNTIME_TOOL_SOURCE,
            max_iterations=EXECUTOR_MAX_ITERATIONS,
            allowed_target_paths=allowed_target_paths,
        )
        executor_exhausted = _turn_max_iteration_exhausted(turn)
        if not executor_exhausted:
            turn = _require_successful_turn(turn)
        inspection = _inspect_candidate(
            dependencies,
            run_id=run_id,
            context=context,
            workspace=workspace,
            turn=turn,
        )
        changed_files = _validated_candidate_changes(
            inspection,
            run_id=run_id,
            target_files=target_files,
        )
        mutation_required = not changed_files
        transaction_opened = _result_used_tool(
            turn["result"],
            "open_evolution_transaction_tool",
        )
        validation_carryover = deepcopy(turn.get("carryover") or {})
        if mutation_required:
            tool_call_count = _result_tool_call_count(turn["result"])
            _record_executor_retry(
                run_id=run_id,
                reason=(
                    "max_iterations_exhausted_no_changed_files"
                    if executor_exhausted
                    else (
                        "no_tool_calls_and_no_changed_files"
                        if tool_call_count == 0
                        else "tool_calls_but_no_changed_files"
                    )
                ),
            )
            mutation_turn = _run_successful_turn(
                dependencies.run_role_turn,
                role="executor",
                binding=executor_binding,
                run_id=run_id,
                prompt=_evolution_mutation_prompt(context),
                carryover=deepcopy(turn.get("carryover") or {}),
                runtime_tool_grants=list(EXECUTOR_MUTATION_TOOLS),
                runtime_tool_source=AUTONOMOUS_RUNTIME_TOOL_SOURCE,
                max_iterations=EXECUTOR_MUTATION_MAX_ITERATIONS,
                allowed_target_paths=allowed_target_paths,
            )
            inspection = _inspect_candidate(
                dependencies,
                run_id=run_id,
                context=context,
                workspace=workspace,
                turn=mutation_turn,
            )
            changed_files = _validated_candidate_changes(
                inspection,
                run_id=run_id,
                target_files=target_files,
            )
            if not changed_files:
                raise AutonomousLoopRuntimeError(
                    "Candidate has no changed files after evolution."
                )
            validation_carryover = deepcopy(
                mutation_turn.get("carryover") or {}
            )
        if mutation_required or executor_exhausted:
            validation_tools = list(EXECUTOR_VALIDATION_TOOLS)
            if not transaction_opened:
                validation_tools.insert(0, "open_evolution_transaction_tool")
            turn = _run_successful_turn(
                dependencies.run_role_turn,
                role="executor",
                binding=executor_binding,
                run_id=run_id,
                prompt=_evolution_validation_prompt(
                    context,
                    changed_files=changed_files,
                    transaction_opened=transaction_opened,
                ),
                carryover=validation_carryover,
                runtime_tool_grants=validation_tools,
                runtime_tool_source=AUTONOMOUS_RUNTIME_TOOL_SOURCE,
                max_iterations=EXECUTOR_VALIDATION_MAX_ITERATIONS,
                allowed_target_paths=allowed_target_paths,
            )
            inspection = _inspect_candidate(
                dependencies,
                run_id=run_id,
                context=context,
                workspace=workspace,
                turn=turn,
            )
        changed_files = _validated_candidate_changes(
            inspection,
            run_id=run_id,
            target_files=target_files,
        )
        if not changed_files:
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


def _inspect_candidate(
    dependencies: AutonomousLoopRuntimeDependencies,
    *,
    run_id: str,
    context: dict[str, Any],
    workspace: dict[str, Any],
    turn: dict[str, Any],
) -> dict[str, Any]:
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
    return inspection


def _run_successful_turn(
    runner: RoleTurnCallable,
    **kwargs: Any,
) -> dict[str, Any]:
    return _require_successful_turn(runner(**kwargs))


def _require_turn_result(turn: Any) -> dict[str, Any]:
    if not isinstance(turn, dict):
        raise AutonomousLoopRuntimeError("Agent turn returned an invalid result.")
    result = turn.get("result")
    if not isinstance(result, dict):
        raise AutonomousLoopRuntimeError("Agent turn result is missing.")
    return turn


def _turn_max_iteration_exhausted(turn: Any) -> bool:
    validated_turn = _require_turn_result(turn)
    return bool(validated_turn["result"].get("max_iteration_exhausted"))


def _require_successful_turn(turn: Any) -> dict[str, Any]:
    validated_turn = _require_turn_result(turn)
    result = validated_turn["result"]
    status = str(result.get("status") or "").strip().lower()
    if status in {"failed", "stopped", "cancelled", "error"}:
        detail = str(
            result.get("error")
            or result.get("summary")
            or f"Agent turn ended with status={status}"
        ).strip()
        raise AutonomousLoopRuntimeError(detail)
    return validated_turn


def _run_bounded_analysis_turn(
    runner: RoleTurnCallable,
    *,
    phase: str,
    **kwargs: Any,
) -> dict[str, Any]:
    turn = runner(**kwargs)
    result = turn.get("result") if isinstance(turn, dict) else None
    exhausted = bool(
        isinstance(result, dict)
        and result.get("max_iteration_exhausted")
    )
    if not exhausted:
        return _require_successful_turn(turn)
    run_id = str(kwargs.get("run_id") or "").strip()
    _record_analysis_finalization(run_id=run_id, phase=phase)
    finalization_turn = runner(
        role=kwargs["role"],
        binding=kwargs["binding"],
        run_id=run_id,
        prompt=_analysis_finalization_prompt(phase),
        carryover=deepcopy(turn.get("carryover") or {}),
        runtime_tool_grants=[],
        runtime_tool_source=AUTONOMOUS_RUNTIME_TOOL_SOURCE,
        max_iterations=ANALYSIS_FINALIZATION_MAX_ITERATIONS,
        disable_tools=True,
    )
    return _require_successful_turn(finalization_turn)


def _result_tool_call_count(result: dict[str, Any]) -> int:
    for key in ("tool_call_count", "toolCallCount"):
        try:
            count = int(result.get(key) or 0)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            return count
    return len(_result_evidence(result))


def _result_used_tool(result: dict[str, Any], tool_name: str) -> bool:
    expected = str(tool_name or "").strip()
    if not expected:
        return False
    for item in _result_evidence(result):
        observed = str(item.get("name") or item.get("toolName") or "").strip()
        if observed == expected:
            return True
    return False


def _result_summary(result: dict[str, Any], *, label: str) -> str:
    for key in ("summary", "content", "message", "output"):
        value = str(result.get(key) or "").strip()
        if value:
            return value
    raise AutonomousLoopRuntimeError(f"{label} Agent returned no visible summary.")


def _plan_target_files(result: dict[str, Any]) -> list[str]:
    try:
        return extract_plan_target_files(
            result,
            summary=_result_summary(result, label="Plan"),
        )
    except CandidateTargetContractError as exc:
        raise AutonomousLoopRuntimeError(str(exc)) from exc


def _explicit_request_target_files(context: dict[str, Any]) -> list[str]:
    request = context.get("request")
    goal = str(
        request.get("goal")
        if isinstance(request, dict)
        else ""
    ).strip()
    goal_casefolded = goal.casefold()
    if not any(
        cue.casefold() in goal_casefolded
        for cue in EXPLICIT_TARGET_SCOPE_CUES
    ):
        return []
    matches = REPOSITORY_FILE_REFERENCE_PATTERN.findall(goal)
    if not matches:
        return []
    try:
        return normalize_target_files(matches)
    except CandidateTargetContractError as exc:
        raise AutonomousLoopRuntimeError(str(exc)) from exc


def _validate_plan_targets_against_request(
    context: dict[str, Any],
    target_files: list[str],
) -> None:
    requested_target_files = _explicit_request_target_files(context)
    if not requested_target_files:
        return
    requested = set(requested_target_files)
    if any(target not in requested for target in target_files):
        raise AutonomousLoopRuntimeError(
            "Plan target files are outside explicit request target files."
        )


def _target_files_from_context(context: dict[str, Any]) -> list[str]:
    plan = context.get("plan") if isinstance(context.get("plan"), dict) else {}
    raw_targets = plan.get("targetFiles")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise AutonomousLoopRuntimeError(
            "Plan did not declare structured target files."
        )
    try:
        return normalize_target_files(raw_targets)
    except CandidateTargetContractError as exc:
        raise AutonomousLoopRuntimeError(str(exc)) from exc


def _candidate_target_paths(
    worktree_path: str,
    target_files: list[str],
) -> list[str]:
    try:
        return candidate_target_paths(worktree_path, target_files)
    except CandidateTargetContractError as exc:
        raise AutonomousLoopRuntimeError(str(exc)) from exc


def _validated_candidate_changes(
    inspection: dict[str, Any],
    *,
    run_id: str,
    target_files: list[str],
) -> list[str]:
    try:
        return validate_candidate_changes(
            inspection,
            run_id=run_id,
            target_files=target_files,
        )
    except CandidateTargetContractError as exc:
        raise AutonomousLoopRuntimeError(str(exc)) from exc


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
        "3. RUNTIME_LOG_INDEX 只是定位线索；必须读取对应事件并确认问题在"
        "当前运行仍未恢复，才能列为进化目标。读取 logs/runtime_scenes 使用 "
        "grep_search_tool；code_symbol_tool 只用于已索引源码。\n"
        "4. 不得把本轮诊断过程中由自己触发的工具参数或目录不适配失败当成"
        "项目缺陷。\n"
        "5. 如果目标只是“开始自主进化”，选取一个被当前源码或日志直接证实、"
        "可在一轮内修复的问题；不得从最近 Git 记忆推断未验证需求。\n"
        "6. 最多补充 2 轮只读检索；证据足够时立即停止继续搜索。\n"
        "7. 必须在第 4 轮前保留一次最终回答，给出可供下一轮制定计划的简洁事实摘要。"
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
        "1. 本阶段的工具预算已经独立重置；上一阶段回答中的“预算耗尽”"
        "不再约束本阶段。\n"
        "2. 计划对象必须与观察摘要中已验证的问题一致；不得改用仅来自 "
        "GIT_MEMORY、最近提交或通用猜测的其他模块，也不得凭空引入依赖。\n"
        "3. 计划必须能在隔离 worktree 内完成并留下测试证据。\n"
        "4. 不执行计划，不评分，不调用 Judge。\n"
        "5. 最多补充 1 轮只读检索；已有观察证据足够时不得重复搜索。\n"
        "6. 必须在第 3 轮前输出计划，明确修改范围、验证方法和停止条件。\n"
        "7. 最终回答最后一行必须逐字使用 `TARGET_FILES_JSON: "
        "[\"相对仓库路径\"]` 声明本轮最多 8 个精确目标文件；不得使用目录、"
        "绝对路径、通配符、..、workspace、logs、config、.git、"
        "docs/standards 或项目记忆路径。"
    )


def _planning_target_correction_prompt(
    *,
    requested_target_files: list[str] | None = None,
) -> str:
    requested_targets = list(requested_target_files or [])
    explicit_scope = ""
    if requested_targets:
        rendered_targets = ", ".join(
            f'"{target}"' for target in requested_targets
        )
        explicit_scope = (
            "用户明确限定的可修改文件只有："
            f"[{rendered_targets}]。纠正后的 TARGET_FILES_JSON 只能从该清单"
            "中选择，不得引入其他文件。"
        )
    return (
        "上一次实施计划的结构化目标文件清单违反了宿主安全契约。"
        "现在只纠正计划正文中的修改范围和最后一行 TARGET_FILES_JSON，"
        "不要调用任何工具，也不要增加新的实施目标。"
        f"{explicit_scope}"
        "不要读取或修改被拒绝的路径；不得使用目录、绝对路径、通配符、..、"
        "workspace、logs、config、.git、docs/standards 或项目记忆路径。"
        "请保留已经证实的目标和验证方法，并在最后一行输出最多 8 个"
        '可修改的仓库相对文件，例如 TARGET_FILES_JSON: ["core/example.py", '
        '"tests/test_example.py"]。'
    )


def _analysis_finalization_prompt(phase: str) -> str:
    label = "观察摘要" if phase == "observation" else "实施计划"
    target_contract = (
        "\n实施计划的最后一行仍必须逐字输出 "
        '`TARGET_FILES_JSON: ["相对仓库路径"]`，否则计划按失效关闭处理。'
        if phase == "planning"
        else ""
    )
    return (
        f"当前{label}的只读工具预算已经用完。现在停止调用工具，"
        "仅使用同一会话中已经获得的证据输出最终可见回答。\n"
        "不要继续搜索，不要修改文件，不要请求用户确认，不要评分或调用 Judge。\n"
        f"直接输出简洁、可执行的{label}；证据不足的部分明确标为未验证。"
        f"{target_contract}"
    )


def _target_contract_error_code(message: str) -> str:
    lowered = str(message or "").casefold()
    if "outside explicit request target files" in lowered:
        return "request_target_mismatch"
    if "forbidden" in lowered:
        return "forbidden_target"
    if "repository-relative" in lowered:
        return "non_relative_target"
    if "unsafe" in lowered or "empty" in lowered:
        return "unsafe_target"
    if "count exceeds" in lowered:
        return "target_count"
    if "structured target files" in lowered or "invalid json" in lowered:
        return "missing_or_invalid_structure"
    return "invalid_contract"


def _record_plan_target_correction(*, run_id: str, reason: str) -> None:
    record_runtime_scene_event(
        "work_run",
        "planning",
        "self_evolution.autonomous_loop.plan_target_correction_requested",
        message=(
            "Self-evolution requested one bounded correction for an invalid "
            "plan target contract."
        ),
        outcome="retrying",
        fields={
            "runKind": "self_evolution_autonomous_loop",
            "runId": run_id,
            "reason": reason,
            "attempt": 1,
            "toolsEnabled": False,
        },
        lifecycle=True,
    )


def _evolution_prompt(context: dict[str, Any]) -> str:
    request = context.get("request") if isinstance(context.get("request"), dict) else {}
    observation = (
        context.get("observation")
        if isinstance(context.get("observation"), dict)
        else {}
    )
    plan = context.get("plan") if isinstance(context.get("plan"), dict) else {}
    target_files = _target_files_from_context(context)
    return (
        "请在当前隔离 worktree 内实施这一轮自进化候选。\n"
        f"目标：{str(request.get('goal') or '').strip()}\n"
        f"观察：{str(observation.get('summary') or '').strip()}\n"
        f"计划：{str(plan.get('summary') or '').strip()}\n"
        f"宿主批准的精确目标文件：{', '.join(target_files)}\n\n"
        "要求：\n"
        "1. 当前阶段已经获得自动闭环的执行授权，无需再次请求用户确认。\n"
        "2. 必须实际调用工具实施计划；先调用 open_evolution_transaction_tool，"
        "再读取、修改并验证候选，最后调用 close_evolution_transaction_tool 收口。\n"
        "3. 只允许修改上面列出的精确目标文件，运行与改动相称的测试；"
        "纯文本复述计划不算完成。\n"
        "4. 本阶段最多 24 次模型/工具迭代；优先完成定位、修改与聚焦测试，"
        "不要反复读取同一文件。\n"
        "5. 不写主工作区，不刷新 Launcher，不执行远端操作。\n"
        "6. 不得执行评分、Judge 或自行批准合入。\n"
        "7. 完成后报告改动、测试、未覆盖边界和剩余风险。"
    )


def _evolution_mutation_prompt(context: dict[str, Any]) -> str:
    plan = context.get("plan") if isinstance(context.get("plan"), dict) else {}
    target_files = _target_files_from_context(context)
    return (
        "上一轮执行后候选工作树仍没有产生任何文件变更；只读检查、复述计划"
        "或仅开事务都不算完成。\n"
        f"既定计划：{str(plan.get('summary') or '').strip()}\n"
        f"宿主批准的精确目标文件：{', '.join(target_files)}\n\n"
        "现在进入有界写入阶段：\n"
        "1. 不要复述计划，不要再次制定计划，也无需再次请求用户确认。\n"
        "2. 第一项工具调用必须产生文件修改；当前只提供 apply_patch_tool 和 "
        "write_file_tool，不再读取源码、目录或测试说明。\n"
        "3. 使用上一轮已经读取的证据，在 4 轮内完成最小安全候选修改；"
        "不得再次开账或关账。\n"
        "4. 仍须遵守原定范围；不要写主工作区、刷新 Launcher、执行远端操作、"
        "评分、Judge 或自行批准合入。\n"
        "5. 如果现有证据不足以安全修改，直接报告阻塞，不得伪造候选变更。"
    )


def _evolution_validation_prompt(
    context: dict[str, Any],
    *,
    changed_files: list[Any],
    transaction_opened: bool,
) -> str:
    plan = context.get("plan") if isinstance(context.get("plan"), dict) else {}
    normalized_files = [
        str(item).strip() for item in changed_files if str(item).strip()
    ]
    transaction_line = (
        "已有事务已经开账；不得重复调用 open_evolution_transaction_tool。"
        if transaction_opened
        else "尚未观察到已开事务；先开账一次，再执行验证。"
    )
    return (
        "候选已经产生文件变更，现在只做验证与事务收口。\n"
        f"既定计划：{str(plan.get('summary') or '').strip()}\n"
        f"候选文件：{', '.join(normalized_files)}\n"
        f"{transaction_line}\n\n"
        "要求：\n"
        "1. 不再修改文件，不重新制定计划，不请求用户确认。\n"
        "2. 使用 cli_tool 或 python_lint_tool 运行与改动相称的聚焦验证。\n"
        "3. 验证成功后调用 close_evolution_transaction_tool 以 success 收口；"
        "验证失败则以 failed 收口并报告真实失败。\n"
        "4. 最多 8 轮，不执行 Git 合入、Launcher 刷新、远端操作、评分、"
        "Judge 或用户审批。"
    )


def _record_executor_retry(*, run_id: str, reason: str) -> None:
    try:
        record_runtime_scene_event(
            "work_run",
            "evolving",
            "self_evolution.autonomous_loop.executor_retry_requested",
            message="Self-evolution executor received one bounded execution correction.",
            level="warning",
            outcome="retrying",
            fields={
                "runKind": "self_evolution_autonomous_loop",
                "runId": run_id,
                "reason": reason,
                "attempt": 1,
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_analysis_finalization(*, run_id: str, phase: str) -> None:
    try:
        record_runtime_scene_event(
            "work_run",
            phase,
            "self_evolution.autonomous_loop.analysis_finalization_requested",
            message="Self-evolution analysis reached its bounded tool budget.",
            level="warning",
            outcome="finalizing",
            fields={
                "runKind": "self_evolution_autonomous_loop",
                "runId": run_id,
                "phase": phase,
                "toolsDisabled": True,
                "maxIterations": ANALYSIS_FINALIZATION_MAX_ITERATIONS,
            },
            lifecycle=True,
        )
    except Exception:
        return
