"""Lifecycle goal detectors for evolution restart / close-and-restart.

These classifiers decide whether an evolution turn may trigger self-restart.
False positives can restart the runtime; false negatives stall a closeout.
"""

from core.orchestration.delegation_governor import DelegationGovernor
from core.orchestration.evolution_lifecycle import (
    is_full_evolution_goal,
    is_restart_focused_goal,
)


def test_restart_focus_empty_and_unrelated_goals_are_false():
    assert is_restart_focused_goal("") is False
    assert is_restart_focused_goal("   ") is False
    assert is_restart_focused_goal("只做事务探针和验证") is False


def test_restart_focus_positive_markers_and_casefold():
    assert is_restart_focused_goal("请重启你自己") is True
    assert is_restart_focused_goal("调用 trigger_self_restart_tool") is True
    assert is_restart_focused_goal("Restart Yourself after closeout") is True
    assert is_restart_focused_goal("完成重启") is True


def test_restart_focus_negative_markers_win():
    assert is_restart_focused_goal("执行非重启事务探针，不要调用 trigger_self_restart_tool。") is False
    assert is_restart_focused_goal("只做事务和验证探针，不要触发重启。") is False
    assert is_restart_focused_goal("do not restart, just report") is False


def test_incomplete_restart_status_is_not_restart_focused():
    assert is_restart_focused_goal("检查未完成重启状态") is False
    assert is_restart_focused_goal("未完成重启，然后重启你自己") is True


def test_full_evolution_requires_close_and_restart():
    assert is_full_evolution_goal(
        "调用 close_evolution_transaction_tool 关账，关账成功后立即调用 trigger_self_restart_tool 完成重启。"
    ) is True
    assert is_full_evolution_goal("制定重启任务，然后调用 trigger_self_restart_tool 重启你自己。") is False
    assert is_full_evolution_goal("调用 close_evolution_transaction_tool 关账，不要触发重启。") is False
    assert is_full_evolution_goal("关账") is False


def test_delegation_governor_shares_lifecycle_detectors():
    goal = "关账成功后立即调用 trigger_self_restart_tool 完成重启。"
    assert DelegationGovernor.is_restart_focused_goal(goal) is is_restart_focused_goal(goal)
    assert DelegationGovernor.is_full_evolution_goal(goal) is is_full_evolution_goal(goal)
    assert DelegationGovernor.is_restart_focused_goal("检查未完成重启状态") is False
