# -*- coding: utf-8 -*-
"""统一 Vibelution agent 的运行目标包。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from core.orchestration.agent_modes import AgentMode, ModePolicy


@dataclass(frozen=True)
class TurnCapabilityProfile:
    """One authoritative capability profile for a turn."""

    profile_id: str
    objective_type: str
    allow_auto_continue: bool
    allow_file_writes: bool
    allow_git_commit: bool
    allow_evolution_transaction: bool
    allow_subagents: bool
    completion_standard: str
    forbidden_actions: tuple[str, ...] = field(default_factory=tuple)


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
    capability_profile: str = "default"

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
            f"- 能力 Profile: {self.capability_profile}",
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
        profile = _chat_capability_profile(policy, goal_text)
        return RuntimeGoalPacket(
            goal=goal_text,
            source="对话入口",
            objective_type=profile.objective_type,
            capability_profile=profile.profile_id,
            allow_auto_continue=profile.allow_auto_continue,
            allow_file_writes=profile.allow_file_writes,
            allow_git_commit=profile.allow_git_commit,
            allow_evolution_transaction=profile.allow_evolution_transaction,
            allow_subagents=profile.allow_subagents,
            completion_standard=profile.completion_standard,
            forbidden_actions=profile.forbidden_actions,
        )
    if mode == AgentMode.SUPERVISED_EVOLUTION:
        return RuntimeGoalPacket(
            goal=goal_text,
            source="监督进化入口",
            objective_type="evaluation_case",
            capability_profile="supervised_evaluation",
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
        capability_profile="self_improvement",
        allow_auto_continue=policy.allow_auto_loop,
        allow_file_writes=True,
        allow_git_commit=True,
        allow_evolution_transaction=True,
        allow_subagents=True,
        completion_standard="围绕 Vibelution 稳定性、进化效率或 UI/agent 一致性完成可验证改进。",
        forbidden_actions=("不要把当前入口解释成另一个 agent；仍然是同一个 Vibelution agent 面对自进化目标。",),
    )


def _chat_capability_profile(policy: ModePolicy, goal_text: str) -> TurnCapabilityProfile:
    if _is_readonly_discussion_goal(goal_text):
        return TurnCapabilityProfile(
            profile_id="readonly_discussion",
            objective_type="readonly_discussion",
            allow_auto_continue=False,
            allow_file_writes=False,
            allow_git_commit=False,
            allow_evolution_transaction=False,
            allow_subagents=False,
            completion_standard="给出一段紧凑、可读的只读回复；不修改文件、不提交、不派发子 agent、不启动进化或部署。",
            forbidden_actions=(
                "不要修改文件、执行写入型工具或通过命令间接写入工作区。",
                "不要提交 Git、创建分支、合并、推送或启动部署。",
                "不要派发子 agent 或开启长期进化事务。",
            ),
        )
    return TurnCapabilityProfile(
        profile_id="write_capable_chat",
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


def _is_readonly_discussion_goal(goal_text: str) -> bool:
    normalized = " ".join(str(goal_text or "").lower().split())
    if not normalized:
        return False
    explicit_readonly_markers = (
        "只读 agent 群聊",
        "只读agent群聊",
        "read-only agent",
        "readonly agent",
        "不要修改文件",
        "不要提交",
        "不要启动进化",
        "不要启动部署",
        "do not modify files",
        "do not commit",
        "do not start evolution",
        "do not deploy",
    )
    if any(marker in normalized for marker in explicit_readonly_markers):
        return True
    discussion_markers = (
        "对话目的: discussion",
        "对话目的：discussion",
        "本轮推进模式: discussion",
        "本轮推进模式：discussion",
        "purpose: discussion",
        "mode: discussion",
        "团队群聊",
        "群聊:",
        "群聊：",
    )
    if not any(marker in normalized for marker in discussion_markers):
        return False
    mutation_markers = (
        "开始修复",
        "开始实现",
        "修改",
        "改代码",
        "写入",
        "提交",
        "部署",
        "start fixing",
        "implement",
        "modify",
        "commit",
        "deploy",
    )
    return not any(marker in normalized for marker in mutation_markers)


def _yes_no(value: bool) -> str:
    return "允许" if value else "不允许"
