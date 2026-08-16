# -*- coding: utf-8 -*-

from core.orchestration.subagent_roles import (
    ALLOWED_SUBAGENT_TASK_TYPES,
    SubagentRoleNeed,
    extract_subagent_primary_goal,
    get_subagent_role_spec,
)


def test_subagent_role_specs_cover_allowed_task_types():
    assert ALLOWED_SUBAGENT_TASK_TYPES == {"diagnose", "inspect", "summarize"}
    for task_type in ALLOWED_SUBAGENT_TASK_TYPES:
        spec = get_subagent_role_spec(task_type)
        assert spec.task_type == task_type
        assert spec.role_name
        assert spec.system_purpose
        assert len(spec.owned_work) == 2
        assert len(spec.forbidden_work) == 2
        assert spec.return_shape


def test_unknown_subagent_role_defaults_to_inspect():
    spec = get_subagent_role_spec("unknown")
    assert spec.task_type == "inspect"
    assert spec.role_name == "局部状态探针"


def test_subagent_role_need_shape_is_explicit():
    need = SubagentRoleNeed(
        task_type="diagnose",
        trigger_reason="failure_attribution_needed",
        why_now="当前更缺的是局部故障归因证据。",
    )
    assert need.task_type == "diagnose"
    assert need.trigger_reason == "failure_attribution_needed"
    assert "故障归因" in need.why_now


def test_role_spec_accepts_bytes_and_hyphen_aliases():
    assert get_subagent_role_spec(b"diagnose").task_type == "diagnose"
    assert get_subagent_role_spec("Summarize").task_type == "summarize"
    assert get_subagent_role_spec("  ").task_type == "inspect"
    assert get_subagent_role_spec(memoryview(b"diagnose")).task_type == "diagnose"
    assert get_subagent_role_spec({"taskType": "diagnose"}).task_type == "diagnose"
    assert get_subagent_role_spec('{"task_type":"summarize"}').task_type == "summarize"
    assert get_subagent_role_spec(["inspect"]).task_type == "inspect"


def test_extract_primary_goal_accepts_bytes_and_survives_non_text():
    prompt = (
        "## 主 Agent 任务指令\n"
        "- 当前唯一目标: 分析最近验证失败的根因\n"
        "- 当前任务类型: diagnose\n"
    )
    assert extract_subagent_primary_goal(prompt.encode("utf-8")) == "分析最近验证失败的根因"
    assert extract_subagent_primary_goal(None) == ""
    assert isinstance(extract_subagent_primary_goal(["not", "a", "prompt"]), str)
    assert extract_subagent_primary_goal({"prompt": prompt}) == "分析最近验证失败的根因"
    assert extract_subagent_primary_goal(["- 当前唯一目标: 分析最近验证失败的根因"]) == "分析最近验证失败的根因"
