from __future__ import annotations

from core.orchestration.output_boundary import (
    sanitize_assistant_visible_text,
    strip_llm_protocol_artifacts,
)


def test_strip_llm_protocol_artifacts_removes_standalone_bracket_control_markers():
    raw = "已经完成项目审查。\n[outcome=done]\n[task_outcome=success]\n[status=ready]\n下一步可以提交。"

    cleaned = strip_llm_protocol_artifacts(raw)

    assert cleaned == "已经完成项目审查。\n下一步可以提交。"


def test_strip_llm_protocol_artifacts_removes_standalone_bare_control_markers():
    raw = "已经完成项目审查。\noutcome=done\ntask_outcome=success\nstatus=ready\n下一步可以提交。"

    cleaned = strip_llm_protocol_artifacts(raw)

    assert cleaned == "已经完成项目审查。\n下一步可以提交。"


def test_strip_llm_protocol_artifacts_removes_lone_bare_done_marker():
    assert strip_llm_protocol_artifacts("outcome=done") == ""


def test_strip_llm_protocol_artifacts_keeps_bracket_markers_inside_normal_text():
    raw = "请在文档中说明 [status=ready] 是一个历史日志样例。"

    cleaned = strip_llm_protocol_artifacts(raw)

    assert cleaned == raw


def test_sanitize_assistant_visible_text_removes_think_and_protocol_markers_together():
    raw = "<think>内部推理</think>\n用户可见回答。\n[outcome=done]\n<state>{}</state>"

    cleaned = sanitize_assistant_visible_text(raw)

    assert cleaned == "用户可见回答。"
