# -*- coding: utf-8 -*-
"""演化事务的生命周期目标识别，不参与对话 Agent 的任务路由或委派。"""

from __future__ import annotations


def is_restart_focused_goal(goal: str) -> bool:
    """识别显式要求自我重启、且未被否定的目标。"""
    text = (goal or "").strip().lower()
    if not text:
        return False
    negative_markers = (
        "不要调用 trigger_self_restart_tool",
        "不调用 trigger_self_restart_tool",
        "禁止调用 trigger_self_restart_tool",
        "不要触发重启",
        "不触发重启",
        "禁止重启",
        "不要重启",
        "不重启",
        "do not call trigger_self_restart_tool",
        "don't call trigger_self_restart_tool",
        "do not restart",
        "don't restart",
        "without restart",
        "non-restart",
    )
    if any(marker in text for marker in negative_markers):
        return False
    restart_markers = (
        "trigger_self_restart_tool",
        "重启你自己",
        "重启自己",
        "完成重启",
        "触发重启",
        "执行重启",
        "restart yourself",
        "self restart",
        "self-restart",
    )
    return any(marker in text for marker in restart_markers)


def is_full_evolution_goal(goal: str) -> bool:
    """识别需要关账成功后继续触发自我重启的完整进化闭环目标。"""
    text = (goal or "").strip().lower()
    if not text or not is_restart_focused_goal(text):
        return False
    close_markers = (
        "close_evolution_transaction_tool",
        "关账",
        "关闭演化事务",
        "close transaction",
        "close evolution transaction",
    )
    return any(marker in text for marker in close_markers)
