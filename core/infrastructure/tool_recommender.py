# -*- coding: utf-8 -*-
"""
工具推荐/决策器。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass(frozen=True)
class ToolDecision:
    next_intent: str
    recommended_tools: List[str]
    avoid_tools: List[str]
    reason: str
    fallback_if_failed: List[str]


def decide_next_tools(snapshot: Dict[str, Any]) -> ToolDecision:
    task = snapshot.get("reading_task") or "locate"
    sufficiency = snapshot.get("reading_sufficiency") or ""
    read_ranges = snapshot.get("read_ranges") or {}
    read_entities = snapshot.get("read_entities") or {}
    read_searches = snapshot.get("read_searches") or []
    blockers = snapshot.get("recent_blockers") or []
    validations = snapshot.get("recent_validation_results") or []
    pending_continuations = snapshot.get("pending_continuations") or []
    has_location = bool(read_searches)
    has_detail = any(read_ranges.values()) or any(read_entities.values())
    duplicate_read_seen = any(item.get("kind") == "duplicate_read_soft_redirect" for item in blockers)
    enough_for_conclusion = any(
        marker in sufficiency
        for marker in (
            "已初步够用",
            "已初步足够",
            "已基本够用",
            "已足够",
            "已具备",
            "可形成分析结论",
            "可形成结论",
            "没有新增证据",
        )
    )
    modify_enough = "已足够" in sufficiency or "可开始动手" in sufficiency

    if task == "modify" and modify_enough:
        return ToolDecision(
            next_intent="edit_target",
            recommended_tools=["apply_diff_edit_tool"],
            avoid_tools=["grep_search_tool", "read_file_tool", "cli_tool"],
            reason="修改上下文已足够，继续读取会稀释当前证据；直接进入编辑并保留验证闭环。",
            fallback_if_failed=["code_symbol_tool", "grep_search_tool"],
        )

    if duplicate_read_seen and has_detail:
        return ToolDecision(
            next_intent="synthesize_answer",
            recommended_tools=[],
            avoid_tools=["read_file_tool", "cli_tool"],
            reason="最新读取与已读范围重叠，没有新增证据；先综合现有证据、明确缺口或进入修改，不要继续顺序读取。",
            fallback_if_failed=["code_symbol_tool", "grep_search_tool"],
        )

    if pending_continuations:
        latest = pending_continuations[-1]
        path = latest.get("path") or ""
        if has_detail or enough_for_conclusion:
            return ToolDecision(
                next_intent="synthesize_answer",
                recommended_tools=[],
                avoid_tools=["read_file_tool", "cli_tool"],
                reason="上一段结果还有剩余内容，但当前已有局部证据；先综合现有证据或说明精确缺口，不要按剩余内容顺序翻页。",
                fallback_if_failed=["code_symbol_tool", "grep_search_tool"],
            )
        reason = (
            f"上一段结果还有剩余内容，但不要默认顺序补读 {path}；先按目标判断缺少文本命中、结构还是实体上下文。"
            if path
            else "上一段结果还有剩余内容，但不要默认顺序补读；先按目标判断缺少哪类证据。"
        )
        return ToolDecision(
            next_intent="choose_read_target",
            recommended_tools=["grep_search_tool", "code_symbol_tool"],
            avoid_tools=["read_file_tool", "cli_tool"],
            reason=reason,
            fallback_if_failed=["code_symbol_tool"],
        )

    if task == "verify":
        return ToolDecision(
            next_intent="inspect_range" if validations else "locate_text",
            recommended_tools=["run_test_for_tool", "read_file_tool"],
            avoid_tools=["cli_tool"] if validations else [],
            reason="验证任务优先读取失败输出与相关片段，再决定复测。",
            fallback_if_failed=["grep_search_tool", "python_lint_tool"],
        )

    if task == "modify":
        if any(read_entities.values()) and not any(read_ranges.values()):
            return ToolDecision(
                next_intent="inspect_range",
                recommended_tools=["read_file_tool"],
                avoid_tools=["cli_tool"],
                reason="已定位目标实体，但还缺一段局部上下文；只补目标片段。",
                fallback_if_failed=["code_symbol_tool", "grep_search_tool"],
            )
        return ToolDecision(
            next_intent="inspect_entity",
            recommended_tools=["code_symbol_tool", "read_file_tool"],
            avoid_tools=["cli_tool"],
            reason="修改任务先拿到目标实体和上下文；证据足够后直接进入编辑。",
            fallback_if_failed=["code_symbol_tool", "grep_search_tool"],
        )

    if task == "understand":
        if enough_for_conclusion and has_detail:
            return ToolDecision(
                next_intent="synthesize_answer",
                recommended_tools=[],
                avoid_tools=["read_file_tool", "cli_tool"],
                reason="理解上下文已够形成结论；先输出归纳或明确缺口，不再机械补读。",
                fallback_if_failed=["code_symbol_tool"],
            )
        return ToolDecision(
            next_intent="inspect_structure" if not read_entities else "inspect_entity",
            recommended_tools=["code_symbol_tool", "read_file_tool"],
            avoid_tools=["cli_tool"],
            reason="理解任务先看结构，再看实体。",
            fallback_if_failed=["read_file_tool"],
        )

    if task == "analyze":
        if has_detail and (has_location or enough_for_conclusion):
            return ToolDecision(
                next_intent="synthesize_answer",
                recommended_tools=[],
                avoid_tools=["read_file_tool", "cli_tool"],
                reason="归因已有搜索命中和局部证据；先形成分析结论或列出精确缺口。",
                fallback_if_failed=["code_symbol_tool", "grep_search_tool"],
            )
        return ToolDecision(
            next_intent="locate_text" if not read_searches else "inspect_range",
            recommended_tools=["grep_search_tool", "read_file_tool"],
            avoid_tools=["cli_tool"],
            reason="归因任务先定位症状，再补局部证据。",
            fallback_if_failed=["code_symbol_tool"],
        )

    avoid = []
    if any(item.get("kind") == "duplicate_search" for item in blockers):
        avoid.append("grep_search_tool")
    if has_location and has_detail:
        return ToolDecision(
            next_intent="synthesize_answer",
            recommended_tools=[],
            avoid_tools=avoid + ["read_file_tool", "cli_tool"],
            reason="定位任务已有命中和局部证据；下一步应综合判断或说明缺口，而不是继续读取片段。",
            fallback_if_failed=["code_symbol_tool", "grep_search_tool"],
        )
    return ToolDecision(
        next_intent="locate_text" if not has_location else "inspect_entity",
        recommended_tools=["grep_search_tool", "code_symbol_tool"] if not has_location else ["code_symbol_tool", "read_file_tool"],
        avoid_tools=avoid + ["cli_tool"],
        reason="定位任务先命中，再转实体或局部上下文。",
        fallback_if_failed=["code_symbol_tool", "read_file_tool"],
    )


def format_decision_summary(decision: ToolDecision) -> str:
    parts = [
        f"下一步意图：{decision.next_intent}",
        f"推荐工具：{' -> '.join(decision.recommended_tools)}",
    ]
    if decision.avoid_tools:
        parts.append(f"避免工具：{' / '.join(decision.avoid_tools)}")
    parts.append(f"原因：{decision.reason}")
    if decision.fallback_if_failed:
        parts.append(f"失败回退：{' -> '.join(decision.fallback_if_failed)}")
    return " | ".join(parts)


__all__ = ["ToolDecision", "decide_next_tools", "format_decision_summary"]
