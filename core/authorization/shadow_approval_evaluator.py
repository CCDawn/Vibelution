"""Shadow-approval hypothesis evaluator (批四 Lane S, observe-only).

对每个进入审批判定点的工具调用，在不改变任何真实行为的前提下重放
「免批链」（tool_approvals.authorize_or_wait 的自动批准前奏，
core/web/services/session/tool_approvals.py:401-480）并评估四个假设终态：

- ``baseline``：现状（权威值直接派生自真实 outcome code，不经复刻链）；
- ``no_pa_message_override``：关闭个人助理派发策略的
  ``approvalOverrides: {"agent_message_tool": "never"}``
  （core/web/services/personal_assistant_service.py current_policy）；
- ``no_external_write_override``：关闭外部代理 capability 预设的
  ``approvalOverrides: {"apply_diff_edit_tool": "always", "write_file_tool": "always"}``
  （core/web/services/external_management/contracts.py project_files_v1）；
- ``no_action_window``：关闭助理低风险 manage action 的窗口直批
  （core/web/services/session/assistant_manage_policy.py）。

纯化边界（本模块自述）：除 workspace 路径包含性判定这一处只读 resolve
（与真实 ``_workspace_path_call_is_contained`` 同源、never-raise）外，本模块
无任何 I/O。会话授予（session grant）、持久授予（durable grant）、协作模式
等真实链已算出的命中结果一律由挂载点作为 ``ShadowChainFacts`` 注入；影子侧
绝不重读任何存储。counterfactual 假设下的 grant 命中保守取 False：基线
approval 为 always/never 的工具在真实链中从未产生过授予（always 的审批请求
禁止接受 session/durable 授予，never 不产生请求），一期按现状授予集外推，
并在台账注释中声明该保守界。

默认 shadow（纯观察）。``VIBELUTION_SHADOW_APPROVALS`` 仅提供 off 关闭档；
不存在 enforce 档——一期只观察，任何非 off 值（包括 "enforce"）都停留在
观察档，注释即契约：二期如需硬门必须显式新增档位并重走评审。

遥测照 turn_journal 的 hook 形制（core/chat/turn_journal.py:286-347）：有界
固定键计数器 + 可注册 sink，sink 每次收到一个有界 dict（无 payload、无用户
内容），且永不抛错。
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from threading import Lock
from typing import Any, Callable, Mapping

from .tool_policy_models import MAX_RULE_ID_LENGTH


SHADOW_APPROVALS_ENV = "VIBELUTION_SHADOW_APPROVALS"

# 显式关闭值；其余一切值（含未设置）都停留在 shadow 观察档。一期无 enforce。
_SHADOW_OFF_VALUES = frozenset({"off", "0", "false", "no", "disabled"})

# 假设终态三分类（台账 CHECK 与聚合端点同口径）。
SHADOW_OUTCOME_APPROVED_AUTO = "approved_auto"
SHADOW_OUTCOME_APPROVED_FOR_SESSION = "approved_for_session"
SHADOW_OUTCOME_NEEDS_HUMAN = "needs_human"
SHADOW_OUTCOMES = frozenset(
    {SHADOW_OUTCOME_APPROVED_AUTO, SHADOW_OUTCOME_APPROVED_FOR_SESSION, SHADOW_OUTCOME_NEEDS_HUMAN}
)

# 假设键（台账列名与聚合端点 hypothesis key 同源）。
HYPOTHESIS_BASELINE = "baseline"
HYPOTHESIS_NO_PA_MESSAGE_OVERRIDE = "no_pa_message_override"
HYPOTHESIS_NO_EXTERNAL_WRITE_OVERRIDE = "no_external_write_override"
HYPOTHESIS_NO_ACTION_WINDOW = "no_action_window"
HYPOTHESIS_KEYS = (
    HYPOTHESIS_BASELINE,
    HYPOTHESIS_NO_PA_MESSAGE_OVERRIDE,
    HYPOTHESIS_NO_EXTERNAL_WRITE_OVERRIDE,
    HYPOTHESIS_NO_ACTION_WINDOW,
)

# 假设对象一：PA 派发策略豁免的唯一工具（personal_assistant_service.current_policy）。
PA_MESSAGE_OVERRIDE_TOOL = "agent_message_tool"
# 假设对象二：外部代理 project_files_v1 预设强制 always 的写工具
# （external_management/contracts.py capability_preset）。测试侧与该常量做漂移对账。
EXTERNAL_WRITE_OVERRIDE_TOOLS = frozenset({"apply_diff_edit_tool", "write_file_tool"})

# ---------------------------------------------------------------------------
# 免批链复刻所需的准纯谓词常量（与 tool_approvals.py:1144-1262 逐字对齐，
# 由 tests/test_shadow_approval_evaluator.py 的 parity 用例对账漂移）。
# ---------------------------------------------------------------------------
_SANDBOX_CONTAINED_TOOLS = frozenset({"cli_tool", "exec_command", "write_stdin"})
_WORKSPACE_PATH_TOOLS = frozenset({"apply_diff_edit_tool", "apply_patch_tool", "write_file_tool"})
_CLI_SHELL_TOOLS = frozenset({"cli_tool", "exec_command"})
_SAFE_READONLY_GIT_SUBCOMMANDS = frozenset(
    {
        "status", "branch", "log", "show", "diff", "rev-parse", "rev-list",
        "ls-files", "ls-tree", "describe", "tag", "remote", "stash", "blame",
        "shortlog", "whatchanged", "name-rev", "cat-file", "config", "version", "help",
    }
)
_SAFE_READONLY_GIT_STASH_ACTIONS = frozenset({"list", "show"})
_SAFE_READONLY_GIT_REMOTE_ACTIONS = frozenset({"", "-v", "--verbose", "show", "get-url"})
_SAFE_READONLY_GIT_CONFIG_ACTIONS = frozenset({"--get", "--get-all", "--list", "-l", "--get-regexp"})
_UNSAFE_GIT_FLAG_TOKENS = frozenset({"--exec", "--upload-pack", "--receive-pack", "-c"})
_SHELL_METACHARS = re.compile(r"[|;&><`$]|&&|\|\|")
_PATCH_TARGET_PATTERN = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File: (?P<path>.+?)\s*$",
    re.MULTILINE,
)


def shadow_approvals_enabled() -> bool:
    """Shadow 观察是否开启（默认开；仅显式 off 值关闭；无 enforce 档）。"""

    raw = os.environ.get(SHADOW_APPROVALS_ENV, "").strip().lower()
    return raw not in _SHADOW_OFF_VALUES


def compose_shadow_rule_id(policy_id: str, gate_id: str, outcome: str) -> str:
    """Compose the stable audit ruleId for one shadow chain rule.

    形制与 ``compose_deny_rule_id``（tool_policy_models.py:74-84）一致：
    ``policyId:gate:outcome``，超长按同一上限截断，确定性可审计。gate 以
    ``shadow.`` 前缀命名，绝不与真实 deny 审计 id 混淆。
    """

    normalized_policy = str(policy_id or "").strip() or "policy-unresolved"
    normalized_gate = str(gate_id or "").strip() or "shadow.rule.unspecified"
    return f"{normalized_policy}:{normalized_gate}:{outcome}"[:MAX_RULE_ID_LENGTH]


@dataclass(frozen=True, slots=True)
class ShadowApprovalSnapshot:
    """One approval decision point's injected inputs (no storage reads).

    ``decision_arguments`` 是免批链谓词所需的只读参数投影（action / cmd /
    command / cwd / file_path / patch_text），由挂载点从真实 tool_args 投影；
    snapshot 仅在本次记录调用栈内存活，不落盘、不长期持有。
    """

    tool_name: str
    risk: str
    decision_arguments: Mapping[str, Any]
    permission_preset: str
    reminder_recovery: bool
    policy_id: str
    # 真实链将使用的 required approval（policy override 折叠后，即
    # approval_requirements 里的值）。
    approval_baseline: str
    # descriptor 的原生 approval（去 override 口径）；缺失/未知为空串，
    # 对应假设退化为基线克隆（保守 no-op）。
    approval_descriptor: str


@dataclass(frozen=True, slots=True)
class ShadowChainFacts:
    """The real chain's already-computed hit results, injected (never re-read).

    由挂载点从真实 ``ToolApprovalOutcome.code`` 揭示：链路按 never →
    full_access → action window → session grant → durable grant →
    auto-approve 顺序短路，outcome code 一一揭示首个命中；其前的步骤必为
    miss，其后的步骤未被评估（对复刻基线不可达，见 _walk 的短路顺序）。
    """

    approval_not_required: bool = False
    full_access_hit: bool = False
    action_window_hit: bool = False
    session_grant_hit: bool = False
    durable_grant_hit: bool = False
    auto_approve_hit: bool = False
    # 人工终态（请求被真人决议或超时/取消）："" 或 approved/declined/timeout/cancelled
    human_resolution: str = ""


@dataclass(frozen=True, slots=True)
class ShadowHypothesisOutcome:
    outcome: str
    rule_id: str
    rule_gate: str


@dataclass(frozen=True, slots=True)
class ShadowApprovalEvaluation:
    """Four hypothesis end states for one approval decision point."""

    baseline: ShadowHypothesisOutcome
    no_pa_message_override: ShadowHypothesisOutcome
    no_external_write_override: ShadowHypothesisOutcome
    no_action_window: ShadowHypothesisOutcome
    # 复刻链用揭示事实重放基线是否与权威基线一致（漂移报警遥测，不影响行为）。
    replica_baseline: ShadowHypothesisOutcome

    @property
    def replica_baseline_agrees(self) -> bool:
        return (
            self.replica_baseline.outcome == self.baseline.outcome
            and self.replica_baseline.rule_gate == self.baseline.rule_gate
        )

    def by_key(self, key: str) -> ShadowHypothesisOutcome:
        return {
            HYPOTHESIS_BASELINE: self.baseline,
            HYPOTHESIS_NO_PA_MESSAGE_OVERRIDE: self.no_pa_message_override,
            HYPOTHESIS_NO_EXTERNAL_WRITE_OVERRIDE: self.no_external_write_override,
            HYPOTHESIS_NO_ACTION_WINDOW: self.no_action_window,
        }[key]


# ---------------------------------------------------------------------------
# Real-outcome revelation (ground truth mapping)
# ---------------------------------------------------------------------------

# 真实 outcome code → (基线终态, 命中规则 gate)。这些 code 是
# tool_approvals.authorize_or_wait 的全部合法返回（含人工终态）。
_BASELINE_BY_OUTCOME_CODE: dict[str, tuple[str, str]] = {
    "approval_not_required": (SHADOW_OUTCOME_APPROVED_AUTO, "shadow.approval.never"),
    "full_access_auto_approved": (SHADOW_OUTCOME_APPROVED_AUTO, "shadow.approval.full_access"),
    "approved_for_action_window": (SHADOW_OUTCOME_APPROVED_AUTO, "shadow.approval.action_window"),
    "approved_for_session": (SHADOW_OUTCOME_APPROVED_FOR_SESSION, "shadow.approval.session_grant"),
    "approved_for_agent": (SHADOW_OUTCOME_APPROVED_AUTO, "shadow.approval.durable_grant"),
    "auto_approved": (SHADOW_OUTCOME_APPROVED_AUTO, "shadow.approval.auto_review"),
    "approved": (SHADOW_OUTCOME_NEEDS_HUMAN, "shadow.approval.pending"),
    "approval_declined": (SHADOW_OUTCOME_NEEDS_HUMAN, "shadow.approval.pending"),
    "approval_timeout": (SHADOW_OUTCOME_NEEDS_HUMAN, "shadow.approval.pending"),
    "approval_cancelled": (SHADOW_OUTCOME_NEEDS_HUMAN, "shadow.approval.pending"),
}
_HUMAN_RESOLUTION_BY_OUTCOME_CODE = {
    "approved": "approved",
    "approval_declined": "declined",
    "approval_timeout": "timeout",
    "approval_cancelled": "cancelled",
}


def reveal_chain_facts(outcome_code: str) -> ShadowChainFacts:
    """Reveal which chain rule the real outcome code pinned (injected input)."""

    normalized = str(outcome_code or "").strip()
    facts = ShadowChainFacts(
        approval_not_required=normalized == "approval_not_required",
        full_access_hit=normalized == "full_access_auto_approved",
        action_window_hit=normalized == "approved_for_action_window",
        session_grant_hit=normalized == "approved_for_session",
        durable_grant_hit=normalized == "approved_for_agent",
        auto_approve_hit=normalized == "auto_approved",
        human_resolution=_HUMAN_RESOLUTION_BY_OUTCOME_CODE.get(normalized, ""),
    )
    return facts


def baseline_from_real_outcome(outcome_code: str, policy_id: str) -> ShadowHypothesisOutcome:
    """Derive the authoritative baseline end state from the real outcome code.

    基线不经过复刻链：真实链本身就是基线评估器，其 outcome code 权威且零
    复刻风险；复刻基线仅作漂移报警（replica_baseline_agrees）。
    """

    normalized = str(outcome_code or "").strip()
    outcome, gate = _BASELINE_BY_OUTCOME_CODE.get(
        normalized, (SHADOW_OUTCOME_NEEDS_HUMAN, "shadow.approval.pending")
    )
    return ShadowHypothesisOutcome(
        outcome=outcome,
        rule_id=compose_shadow_rule_id(policy_id, gate, outcome),
        rule_gate=gate,
    )


def evaluate_shadow_approvals(
    snapshot: ShadowApprovalSnapshot,
    *,
    real_outcome_code: str,
) -> ShadowApprovalEvaluation:
    """Evaluate the four hypothesis end states for one approval decision point.

    纯函数：除 workspace 路径只读 resolve 外无 I/O；grant/协作命中一律来自
    ``real_outcome_code`` 揭示的事实（注入），counterfactual 下保守取 miss。
    任何输入异常都不应打断真实链：调用方（挂载点）整体 never-raise 包裹。
    """

    facts = reveal_chain_facts(real_outcome_code)
    baseline = baseline_from_real_outcome(real_outcome_code, snapshot.policy_id)
    replica_baseline = _walk_chain(
        snapshot,
        approval=snapshot.approval_baseline,
        action_window=facts.action_window_hit,
        session_grant=facts.session_grant_hit,
        durable_grant=facts.durable_grant_hit,
    )
    return ShadowApprovalEvaluation(
        baseline=baseline,
        replica_baseline=replica_baseline,
        no_pa_message_override=_counterfactual_override_off(
            snapshot,
            baseline=baseline,
            tools=frozenset({PA_MESSAGE_OVERRIDE_TOOL}),
        ),
        no_external_write_override=_counterfactual_override_off(
            snapshot,
            baseline=baseline,
            tools=EXTERNAL_WRITE_OVERRIDE_TOOLS,
        ),
        no_action_window=_counterfactual_window_off(snapshot, baseline=baseline, facts=facts),
    )


def _counterfactual_override_off(
    snapshot: ShadowApprovalSnapshot,
    *,
    baseline: ShadowHypothesisOutcome,
    tools: frozenset[str],
) -> ShadowHypothesisOutcome:
    """Hypothesis: the named tools' policy approvalOverrides never existed.

    仅当基线 required approval 确实来自 override（与 descriptor 原生值不同）
    时假设才有区分度；reminder_recovery 强制 always、descriptor 未知或一致
    时退化为基线克隆。counterfactual 的 grant 命中保守取 miss（见模块注释）。
    """

    if snapshot.reminder_recovery:
        return baseline
    if snapshot.tool_name not in tools:
        return baseline
    descriptor = str(snapshot.approval_descriptor or "").strip()
    if not descriptor or descriptor == snapshot.approval_baseline:
        return baseline
    outcome = _walk_chain(
        snapshot,
        approval=descriptor,
        action_window=False,
        session_grant=False,
        durable_grant=False,
    )
    return outcome


def _counterfactual_window_off(
    snapshot: ShadowApprovalSnapshot,
    *,
    baseline: ShadowHypothesisOutcome,
    facts: ShadowChainFacts,
) -> ShadowHypothesisOutcome:
    """Hypothesis: the assistant manage action window never auto-approves.

    仅当真实链确实由 action window 自动批准时假设才有区分度；否则关闭窗口
    不改变该调用的任何路径，退化为基线克隆。窗口命中后的 grant 状态真实链
    因短路从未评估，counterfactual 保守取 miss（见模块注释）。
    """

    if not facts.action_window_hit:
        return baseline
    return _walk_chain(
        snapshot,
        approval=snapshot.approval_baseline,
        action_window=False,
        session_grant=False,
        durable_grant=False,
    )


def _walk_chain(
    snapshot: ShadowApprovalSnapshot,
    *,
    approval: str,
    action_window: bool,
    session_grant: bool,
    durable_grant: bool,
) -> ShadowHypothesisOutcome:
    """Replica of the auto-approval chain prelude (authorize_or_wait:401-480).

    顺序与真实链逐条对齐：never → full_access → action window → session
    grant → durable grant → auto-approve → 人工 pending。approval 为 always
    时授予块被跳过（与真实链一致）。
    """

    normalized_approval = str(approval or "never").strip()
    reminder_recovery = bool(snapshot.reminder_recovery)
    if reminder_recovery:
        # 真实链把 reminder_recovery 的 required approval 强制为 always。
        normalized_approval = "always"
    policy_id = snapshot.policy_id
    if normalized_approval == "never":
        return _shadow_outcome(policy_id, "shadow.approval.never", SHADOW_OUTCOME_APPROVED_AUTO)
    preset = str(snapshot.permission_preset or "").strip()
    if preset == "full_access" and not reminder_recovery:
        return _shadow_outcome(policy_id, "shadow.approval.full_access", SHADOW_OUTCOME_APPROVED_AUTO)
    if action_window:
        return _shadow_outcome(policy_id, "shadow.approval.action_window", SHADOW_OUTCOME_APPROVED_AUTO)
    if normalized_approval != "always":
        if session_grant:
            return _shadow_outcome(policy_id, "shadow.approval.session_grant", SHADOW_OUTCOME_APPROVED_FOR_SESSION)
        if durable_grant:
            return _shadow_outcome(policy_id, "shadow.approval.durable_grant", SHADOW_OUTCOME_APPROVED_AUTO)
    if _can_auto_approve(
        permission_preset=preset,
        tool_name=snapshot.tool_name,
        tool_args=snapshot.decision_arguments,
        approval=normalized_approval,
        risk=str(snapshot.risk or "read").strip(),
    ):
        return _shadow_outcome(policy_id, "shadow.approval.auto_review", SHADOW_OUTCOME_APPROVED_AUTO)
    return _shadow_outcome(policy_id, "shadow.approval.pending", SHADOW_OUTCOME_NEEDS_HUMAN)


def _shadow_outcome(policy_id: str, gate: str, outcome: str) -> ShadowHypothesisOutcome:
    return ShadowHypothesisOutcome(
        outcome=outcome,
        rule_id=compose_shadow_rule_id(policy_id, gate, outcome),
        rule_gate=gate,
    )


def _can_auto_approve(
    *,
    permission_preset: str,
    tool_name: str,
    tool_args: Mapping[str, Any],
    approval: str,
    risk: str,
) -> bool:
    """Replica of tool_approvals._can_auto_approve (准纯，路径 resolve 只读)."""

    if permission_preset == "full_access":
        return True
    if approval == "always" or risk in {"network", "destructive"}:
        return False
    if permission_preset == "request_approval":
        return tool_name in _CLI_SHELL_TOOLS and _is_safe_readonly_git_cli(tool_args)
    if tool_name in _SANDBOX_CONTAINED_TOOLS:
        return True
    if tool_name in _WORKSPACE_PATH_TOOLS:
        return _workspace_path_call_is_contained(tool_name, tool_args)
    return False


def _cli_command_text(tool_args: Mapping[str, Any]) -> str:
    return str(tool_args.get("cmd") or tool_args.get("command") or "").strip()


def _is_safe_readonly_git_cli(tool_args: Mapping[str, Any]) -> bool:
    """Replica of tool_approvals._is_safe_readonly_git_cli."""

    command = _cli_command_text(tool_args)
    if not command:
        return False
    if _SHELL_METACHARS.search(command):
        return False
    try:
        parts = [part for part in re.split(r"\s+", command) if part]
    except Exception:
        return False
    if len(parts) < 2:
        return False
    head = parts[0].strip().lower().replace("\\", "/")
    executable = head.rsplit("/", 1)[-1]
    if executable not in {"git", "git.exe"}:
        return False
    index = 1
    while index < len(parts):
        lowered = parts[index].lower()
        if lowered in _UNSAFE_GIT_FLAG_TOKENS:
            return False
        if lowered in {"-c", "-C"}:
            index += 2
            continue
        if lowered.startswith("-"):
            index += 1
            continue
        break
    if index >= len(parts):
        return False
    subcommand = parts[index].strip().lower()
    if subcommand not in _SAFE_READONLY_GIT_SUBCOMMANDS:
        return False
    rest = [part.lower() for part in parts[index + 1 :]]
    if subcommand == "stash":
        action = rest[0] if rest else "list"
        return action in _SAFE_READONLY_GIT_STASH_ACTIONS
    if subcommand == "remote":
        action = rest[0] if rest else ""
        return action in _SAFE_READONLY_GIT_REMOTE_ACTIONS
    if subcommand == "config":
        if not rest:
            return False
        return rest[0] in _SAFE_READONLY_GIT_CONFIG_ACTIONS
    if subcommand == "tag" and any(
        token in {"-d", "--delete", "-a", "-m", "-f", "--force"} for token in rest
    ):
        return False
    return True


def _workspace_path_call_is_contained(tool_name: str, tool_args: Mapping[str, Any]) -> bool:
    """Replica of tool_approvals._workspace_path_call_is_contained.

    唯一的准纯点：只读 resolve 当前 workspace 根（与真实链同一来源、同一
    失败语义——resolve 失败按不包含处理，绝不升级为自动批准）。
    """

    from pathlib import Path

    try:
        from tools.shell_tools import _get_workspace_root

        workspace_root = _get_workspace_root().resolve()
        if tool_name == "apply_patch_tool":
            cwd = Path(str(tool_args.get("cwd") or ".").strip() or ".")
            base = cwd.resolve() if cwd.is_absolute() else (workspace_root / cwd).resolve()
            targets = [
                (base / str(match.group("path") or "").strip()).resolve()
                for match in _PATCH_TARGET_PATTERN.finditer(str(tool_args.get("patch_text") or ""))
                if str(match.group("path") or "").strip()
            ]
            return bool(targets) and base.is_relative_to(workspace_root) and all(
                target.is_relative_to(workspace_root) for target in targets
            )
        raw_path = str(tool_args.get("file_path") or "").strip()
        if not raw_path:
            return False
        candidate = Path(raw_path)
        if candidate.is_absolute():
            return False
        parts = candidate.parts
        if parts and parts[0].lower() == "workspace":
            candidate = Path(*parts[1:])
        return (workspace_root / candidate).resolve().is_relative_to(workspace_root)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Bounded telemetry (turn_journal hook form): fixed-key counters + settable
# sink; the sink receives one bounded dict per event and must never raise.
# ---------------------------------------------------------------------------

_TELEMETRY_LOCK = Lock()
_TELEMETRY_KEYS = (
    "engaged",
    "recorded",
    "ledger_write_failures",
    "baseline_replica_mismatches",
    "evaluation_failures",
)
_TELEMETRY: dict[str, int] = {key: 0 for key in _TELEMETRY_KEYS}
_TELEMETRY_SINK: Callable[[dict[str, Any]], None] | None = None
_TELEMETRY_SINK_LOCK = Lock()


def set_shadow_approval_telemetry_sink(hook: Callable[[dict[str, Any]], None] | None) -> None:
    """Register the telemetry sink invoked once per shadow record event.

    与 turn_journal 的 set_turn_transition_guard_hook 同形制：sink 只收到
    有界 dict（计数与无内容标识，无 payload、无用户内容），且必须永不抛错
    （本模块侧亦兜底吞异常）。传 None 注销。
    """

    global _TELEMETRY_SINK
    with _TELEMETRY_SINK_LOCK:
        _TELEMETRY_SINK = hook


def bump_shadow_telemetry(**deltas: int) -> None:
    """Bump bounded counters; emit through the sink; never raises."""

    record: dict[str, Any] = {}
    with _TELEMETRY_LOCK:
        for key, delta in deltas.items():
            if key in _TELEMETRY and isinstance(delta, int) and not isinstance(delta, bool):
                _TELEMETRY[key] += delta
                record[key] = _TELEMETRY[key]
    if not record:
        return
    with _TELEMETRY_SINK_LOCK:
        sink = _TELEMETRY_SINK
    if sink is None:
        return
    try:
        sink(record)
    except Exception:  # noqa: BLE001 - telemetry must never fail the caller
        pass


def shadow_approval_telemetry() -> dict[str, int]:
    """Snapshot copy of the bounded counters (summary endpoint surface)."""

    with _TELEMETRY_LOCK:
        return {key: int(_TELEMETRY[key]) for key in _TELEMETRY_KEYS}


def reset_shadow_telemetry() -> None:
    """Zero the counters (tests and explicit invalidation)."""

    with _TELEMETRY_LOCK:
        for key in _TELEMETRY_KEYS:
            _TELEMETRY[key] = 0
