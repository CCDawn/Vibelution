# -*- coding: utf-8 -*-
"""统一 Vibelution agent 的运行目标包。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from core.orchestration.agent_modes import AgentMode, ModePolicy


@dataclass(frozen=True)
class RuntimeGoalPacket:
    """单个 agent 回合的当前目标与能力边界。"""

    goal: str
    source: str
    objective_type: str
    allow_auto_continue: bool
    allow_file_writes: bool
    allow_git_commit: bool
    allow_evolution_transaction: bool
    allow_subagents: bool
    completion_standard: str
    forbidden_actions: tuple[str, ...] = field(default_factory=tuple)

    def allowed_components(self, registered_components: Iterable[str]) -> set[str]:
        """返回当前目标包允许激活的提示词组件。"""

        allowed = {str(item).strip().upper() for item in registered_components if str(item).strip()}
        if not self.allow_file_writes:
            allowed.discard("CODEBASE_MAP")
        if not self.allow_git_commit and not self.allow_evolution_transaction:
            allowed.discard("GIT_RULES")
        return allowed

    def render(self) -> str:
        forbidden = list(self.forbidden_actions) or ["无额外禁止项；仍遵守工具、日志、Git 和安全边界。"]
        lines = [
            "## 当前运行目标包",
            "- 统一主体: 当前运行者始终是同一个 Vibelution agent；入口只改变目标、能力边界和完成标准。",
            f"- 目标来源: {self.source}",
            f"- 目标类型: {self.objective_type}",
            f"- 当前目标: {self.goal or '未提供显式目标'}",
            "- 能力边界:",
            f"  - 自动持续推进: {_yes_no(self.allow_auto_continue)}",
            f"  - 写文件: {_yes_no(self.allow_file_writes)}",
            f"  - Git 提交: {_yes_no(self.allow_git_commit)}",
            f"  - 进化事务: {_yes_no(self.allow_evolution_transaction)}",
            f"  - 子 agent: {_yes_no(self.allow_subagents)}",
            f"- 完成标准: {self.completion_standard}",
            "- 禁止项:",
            *[f"  - {item}" for item in forbidden],
            "- 提示词组件选择: 可以用 `<active_components>` 请求切换组件，但必须服务当前目标包，不能突破能力边界或移除受保护基座。",
        ]
        return "\n".join(lines)


def build_runtime_goal_packet(policy: ModePolicy, goal: str) -> RuntimeGoalPacket:
    """根据当前策略构建目标包，但不改变 agent 身份。"""

    mode = policy.mode
    goal_text = str(goal or "").strip()
    if mode == AgentMode.CHAT:
        return RuntimeGoalPacket(
            goal=goal_text,
            source="对话入口",
            objective_type="user_request",
            allow_auto_continue=policy.allow_auto_loop,
            allow_file_writes=True,
            allow_git_commit=True,
            allow_evolution_transaction=False,
            allow_subagents=True,
            completion_standard="完成当前外部请求；可按明确请求读写项目文件或提交，但不默认自动提交或开启长期进化事务。",
            forbidden_actions=(
                "不要仅因文本提到自进化或监督进化就切换成另一个 agent。",
                "不要在没有明确任务边界时默认开启进化事务或 Git 提交。",
            ),
        )
    if mode == AgentMode.SUPERVISED_EVOLUTION:
        return RuntimeGoalPacket(
            goal=goal_text,
            source="监督进化入口",
            objective_type="evaluation_case",
            allow_auto_continue=policy.allow_auto_loop,
            allow_file_writes=True,
            allow_git_commit=False,
            allow_evolution_transaction=True,
            allow_subagents=False,
            completion_standard="按给定 case 或评测请求产生可比较证据，并在边界内停止。",
            forbidden_actions=(
                "不要把监督 case 当成新的长期人格或长期目标。",
                "不要污染其他 case 的上下文。",
            ),
        )
    return RuntimeGoalPacket(
        goal=goal_text,
        source="自进化入口",
        objective_type="self_improvement",
        allow_auto_continue=policy.allow_auto_loop,
        allow_file_writes=True,
        allow_git_commit=True,
        allow_evolution_transaction=True,
        allow_subagents=True,
        completion_standard="围绕 Vibelution 稳定性、进化效率或 UI/agent 一致性完成可验证改进。",
        forbidden_actions=("不要把当前入口解释成另一个 agent；仍然是同一个 Vibelution agent 面对自进化目标。",),
    )


def _yes_no(value: bool) -> str:
    return "允许" if value else "不允许"
