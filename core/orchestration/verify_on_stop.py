"""收工证据门。

默认关闭。环境变量 ``VIBELUTION_VERIFY_ON_STOP`` 设为 ``1``、``true``、
``yes``、``on``、``enforce`` 或 ``hard`` 时，编码回合如果改了可验证文件，
又没有一次落在最后一次改动之后的通过记录，就先不收工，最多再追问两次。

这层只记账、只决定要不要追问。它不自己跑检查，一次通过也不等于整仓通过。
只改文档、许可证和表格不会触发。没走文件工具的 shell 改动不在这道门里。
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

VERIFY_ON_STOP_ENV = "VIBELUTION_VERIFY_ON_STOP"
_ENABLED_VALUES = {"1", "true", "yes", "on", "enforce", "hard"}
_MAX_NUDGES = 2
_MAX_PATHS_IN_NUDGE = 8

_NON_CODE_EXTENSIONS = frozenset(
    {
        ".md",
        ".markdown",
        ".mdx",
        ".rst",
        ".txt",
        ".text",
        ".adoc",
        ".asciidoc",
        ".org",
        ".log",
        ".csv",
        ".tsv",
    }
)
_NON_CODE_NAMES = frozenset(
    {
        "license",
        "licence",
        "notice",
        "authors",
        "contributors",
        "changelog",
        "codeowners",
    }
)
_WRITE_TOOLS = frozenset(
    {
        "write_file_tool",
        "apply_diff_edit_tool",
        "apply_patch_tool",
        "create_file",
        "edit_file",
    }
)
_COMMAND_TOOLS = frozenset({"cli_tool", "exec_command"})
_LINT_TOOLS = frozenset({"python_lint_tool"})
_VERIFY_COMMAND = re.compile(
    r"(?:^|[\s;&|`(])(?:"
    r"pytest\b|py\.test\b|vitest\b|tsc\b|mypy\b|pyright\b"
    r"|ruff\s+check\b"
    r"|go\s+test\b"
    r"|cargo\s+test\b"
    r"|python(?:\d+(?:\.\d+)?)?\s+-m\s+(?:pytest|unittest|mypy)\b"
    r"|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b"
    r")",
    re.IGNORECASE,
)
_PATCH_PREFIXES = (
    "*** Update File:",
    "*** Add File:",
    "*** Delete File:",
)


@dataclass
class _TurnState:
    generation: int = 0
    paths: list[str] = field(default_factory=list)
    passes: list[int] = field(default_factory=list)
    nudges: int = 0


_STATE: ContextVar[_TurnState | None] = ContextVar("verify_on_stop_state", default=None)


@dataclass(frozen=True)
class VerifyFinish:
    """收工决定。``nudge`` 要继续本轮；``allow_unverified`` 是追问用尽后仍放行。"""

    action: str
    text: str = ""
    reason: str = ""


def verify_on_stop_enabled() -> bool:
    return str(os.environ.get(VERIFY_ON_STOP_ENV) or "").strip().lower() in _ENABLED_VALUES


def reset_verify_on_stop_turn() -> None:
    """每个用户回合开始时清掉上一回合的改动和通过记录。"""

    _STATE.set(_TurnState())


def note_tool_outcome(
    *,
    tool_name: str,
    args: Mapping[str, Any] | None,
    result: Any,
    skipped: bool = False,
) -> None:
    """从一次已结束的工具调用里记改动或通过记录。失败和被跳过的调用不计。"""

    if skipped or not _business_passed(result):
        return
    name = str(tool_name or "").strip()
    payload = dict(args or {})
    state = _state()
    if name in _WRITE_TOOLS:
        _note_paths(state, _write_paths(name, payload))
        return
    if name in _LINT_TOOLS or (name in _COMMAND_TOOLS and _is_verify_command(_command_text(payload))):
        state.passes.append(state.generation)


def decide_verify_finish() -> VerifyFinish:
    """看当前回合该不该收工。不消耗追问次数。"""

    if not verify_on_stop_enabled():
        return VerifyFinish("allow")
    state = _state()
    if state.generation <= 0 or state.generation in state.passes:
        return VerifyFinish("allow")
    if state.nudges >= _MAX_NUDGES:
        return VerifyFinish("allow_unverified", reason="nudge_cap")
    return VerifyFinish("nudge", text=_nudge_text(state.paths))


def commit_verify_nudge() -> None:
    """模型确实又拿到一次追问时才计一次。"""

    _state().nudges += 1


def take_verify_finish(*, can_continue: bool) -> VerifyFinish:
    """本轮还有下一次模型调用时才把追问交出去。"""

    decision = decide_verify_finish()
    if decision.action != "nudge":
        return decision
    if not can_continue:
        return VerifyFinish("allow_unverified", reason="iteration_budget")
    commit_verify_nudge()
    return decision


def _state() -> _TurnState:
    current = _STATE.get()
    if current is None:
        current = _TurnState()
        _STATE.set(current)
    return current


def _business_passed(result: Any) -> bool:
    from core.infrastructure.tool_result import infer_tool_business_success

    return infer_tool_business_success(result)


def _command_text(args: Mapping[str, Any]) -> str:
    for key in ("command", "cmd"):
        text = args.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def _is_verify_command(command: str) -> bool:
    return bool(command and _VERIFY_COMMAND.search(command))


def _write_paths(tool_name: str, args: Mapping[str, Any]) -> list[str]:
    if tool_name == "apply_patch_tool":
        parsed = _paths_from_patch(_patch_text(args))
        return parsed or ["apply_patch"]
    for key in ("file_path", "filePath", "path"):
        text = args.get(key)
        if isinstance(text, str) and text.strip():
            return [text.strip()]
    return []


def _patch_text(args: Mapping[str, Any]) -> str:
    for key in ("patch_text", "patch", "diff", "diff_text"):
        text = args.get(key)
        if isinstance(text, str) and text.strip():
            return text
    return ""


def _paths_from_patch(patch: str) -> list[str]:
    paths: list[str] = []
    for raw in patch.splitlines():
        line = raw.strip()
        for prefix in _PATCH_PREFIXES:
            if line.startswith(prefix):
                path = line[len(prefix) :].strip()
                if path:
                    paths.append(path)
                break
        else:
            if line.startswith("+++ b/") and not line.startswith("+++ /dev/null"):
                paths.append(line[len("+++ b/") :].strip())
    return paths


def _note_paths(state: _TurnState, paths: list[str]) -> None:
    fresh: list[str] = []
    for path in paths:
        normalized = str(path or "").replace("\\", "/").strip()
        if normalized and not _is_non_code(normalized):
            fresh.append(normalized)
    if not fresh:
        return
    state.generation += 1
    for path in fresh:
        if path not in state.paths:
            state.paths.append(path)


def _is_non_code(path: str) -> bool:
    name = PurePosixPath(path).name
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in _NON_CODE_EXTENSIONS:
        return True
    return name.lower() in _NON_CODE_NAMES


def _nudge_text(paths: list[str]) -> str:
    shown = paths[:_MAX_PATHS_IN_NUDGE]
    lines = "\n".join(f"- {path}" for path in shown)
    extra = len(paths) - len(shown)
    if extra > 0:
        lines = f"{lines}\n- 还有 {extra} 个文件"
    return (
        "这一轮改过可验证的代码，但最后一次改动之后还没有通过的检查。\n"
        f"改动：\n{lines}\n"
        "请现在跑和这些改动相关的测试、类型检查或 lint，看完结果再收尾。"
        "通过只说明你刚跑的那条命令过了，不要写成整仓已经通过。"
        "如果跑不了，直接写出卡住的原因。"
    )
