# -*- coding: utf-8 -*-
"""Regression: continuation caps must follow the scenario class.

执行型场景（基线/自改/复跑）的 agent 常以 needs_continue 分段完成大量工作；
历史上全局 3 次上限在复跑产出真实补丁后仍把 case 判死
（swte-3458aa8712c6：初始 + 3 次续跑全部 needs_continue）。结构化单发场景
（Judge 评分、独立审批）保持紧上限 3，其余场景放宽到 8，总量仍受每 turn
超时预算约束。
"""

from __future__ import annotations

from core.web.services.supervised_conversation_harness_adapter import (
    _max_continuations_for_scenario,
)


def test_structured_single_shot_scenarios_keep_tight_cap() -> None:
    assert _max_continuations_for_scenario("supervised_judge_evaluation") == 3
    assert _max_continuations_for_scenario("supervised_independent_approval") == 3


def test_execution_scenarios_get_raised_cap() -> None:
    assert _max_continuations_for_scenario("transaction") == 8
    assert _max_continuations_for_scenario("candidate_self_improvement") == 8


def test_unknown_or_empty_scenario_defaults_to_raised_cap() -> None:
    assert _max_continuations_for_scenario("") == 8
    assert _max_continuations_for_scenario("anything_else") == 8
    assert _max_continuations_for_scenario("  supervised_judge_evaluation  ") == 3
