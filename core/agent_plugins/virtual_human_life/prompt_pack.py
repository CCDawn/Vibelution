"""Bounded loader for the trusted first-party virtual-human prompt pack."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

PROMPT_PACK_FILES = (
    "01_identity_invariants.md",
    "02_life_autonomy.md",
    "03_schedule_protocol.md",
    "04_mood_and_expression.md",
    "05_tool_boundaries.md",
    "06_diary_memory_rules.md",
    "07_relationship_rules.md",
    "08_proactive_message_rules.md",
    "09_reflection_and_environment.md",
    "10_full_life_continuity.md",
    "11_companion_dialogue_decision.md",
    "13_companion_dialogue_v2_draft.md",
)
LEGACY_FOLLOWUP_PROMPT_FILE = "12_companion_followup_delivery.md"
MAX_PROMPT_PACK_CHARS = 12_000


def proactive_turn_orientation(trigger: Mapping[str, object] | None) -> str:
    """Put native-attempt identity before optional, truncatable life-state data.

    The caller resolves the attempt by the current native Turn id. Never infer
    a proactive turn merely from an empty user message or from session history.
    """
    if not trigger:
        return ""
    if str(trigger.get("deliveryKind") or "") == "self_wake":
        return (
            "## Companion Turn Origin: internal_self_wake\n"
            "本轮没有新的用户消息，是你此前自主安排的行动时间到了。先读取当前生活状态、目标、"
            "真实经历和未完成事项，再决定是否继续、修改或取消计划；仅使用本轮可见且已授权的工具。"
            "计划和被唤醒都不代表完成；结果以真实工具 receipt 和原生 Session 记录为准。"
            "本轮结束前用 virtual_human_schedule_tool 的 view_wakeup 与 schedule_wakeup 安排下一步，"
            "或 cancel_wakeup 停止自主循环。当前 final 只作内部行动摘要，不发送给用户。若值得分享，"
            "另用 virtual_human_proactive_message_tool 申请联系，由权限、免打扰和额度检查决定。"
            "本轮不适用用户对话气泡和 dialogue_decision 规则。\n\n"
        )
    continuation = str(trigger.get("deliveryKind") or "") in {
        "followup",
        "burst_continuation",
    }
    purpose = (
        "本轮是你上一条回复的自然延续；接着尚未说完的内容，不重复上一条，也不假装用户刚回复。"
        if continuation
        else "本轮是你根据生活事件主动联系用户；从自己的近况或有依据的共同话题自然开口。"
    )
    return (
        "## Companion Turn Origin: internal_proactive\n"
        "本轮没有新的用户消息。空输入只是内部触发占位，不代表用户发了空消息或误触发送。"
        "不要把历史最后一句当作刚收到的新消息，不询问用户是否发空了，不解释内部触发机制。\n"
        + purpose
        + "\n\n"
    )


@lru_cache(maxsize=2)
def load_prompt_pack(*, self_wake: bool = False) -> str:
    root = Path(__file__).with_name("prompts")
    sections: list[str] = []
    for filename in PROMPT_PACK_FILES:
        if self_wake and filename in {
            "11_companion_dialogue_decision.md",
            "13_companion_dialogue_v2_draft.md",
        }:
            continue
        text = (root / filename).read_text(encoding="utf-8").strip()
        if text:
            sections.append(text)
    block = "\n\n".join(sections)
    if not block or len(block) > MAX_PROMPT_PACK_CHARS:
        raise RuntimeError(
            "virtual-human-life prompt pack is missing or exceeds its budget"
        )
    return block


@lru_cache(maxsize=1)
def load_legacy_followup_prompt() -> str:
    return (
        (Path(__file__).with_name("prompts") / LEGACY_FOLLOWUP_PROMPT_FILE)
        .read_text(encoding="utf-8")
        .strip()
    )


__all__ = [
    "LEGACY_FOLLOWUP_PROMPT_FILE",
    "PROMPT_PACK_FILES",
    "load_legacy_followup_prompt",
    "load_prompt_pack",
    "proactive_turn_orientation",
]
