from __future__ import annotations

from core.orchestration.output_boundary import (
    sanitize_assistant_thought_delta_text,
    sanitize_assistant_thought_text,
    sanitize_assistant_visible_delta_text,
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


def test_strip_llm_protocol_artifacts_removes_litellm_empty_content_placeholder():
    raw = "[System: Empty message content sanitised to satisfy protocol]"

    cleaned = strip_llm_protocol_artifacts(raw)

    assert cleaned == ""


def test_strip_llm_protocol_artifacts_removes_litellm_placeholder_line_only():
    raw = "已读取文件。\n[System: Empty message content sanitized to satisfy protocol]\n请发送“继续”汇总。"

    cleaned = strip_llm_protocol_artifacts(raw)

    assert cleaned == "已读取文件。\n请发送“继续”汇总。"


def test_sanitize_assistant_visible_text_removes_think_and_protocol_markers_together():
    raw = "<think>内部推理</think>\n用户可见回答。\n[outcome=done]\n<state>{}</state>"

    cleaned = sanitize_assistant_visible_text(raw)

    assert cleaned == "用户可见回答。"


def test_sanitize_assistant_thought_delta_preserves_token_boundary_spaces():
    assert sanitize_assistant_thought_delta_text(" me") == " me"
    assert sanitize_assistant_thought_delta_text(" check ") == " check "
    assert sanitize_assistant_thought_text(" me ") == "me"


def test_sanitize_assistant_visible_delta_preserves_token_boundary_spaces():
    assert sanitize_assistant_visible_delta_text(" 下一步") == " 下一步"
    assert sanitize_assistant_visible_text(" 下一步 ") == "下一步"


def test_strip_llm_protocol_artifacts_removes_invoke_tool_call_and_dsml_blocks():
    raw = (
        "先读取文件。\n"
        '<invoke name="read_file_tool"><parameter name="path">secret.py</parameter></invoke>\n'
        '<tool_call>{"name":"hidden_tool"}</tool_call>\n'
        "<｜DSML｜parameter>leak</｜DSML｜parameter>\n"
        "然后继续。"
    )
    cleaned = strip_llm_protocol_artifacts(raw)
    assert cleaned == "先读取文件。\n\n然后继续。"
    assert "secret.py" not in cleaned
    assert "hidden_tool" not in cleaned


def test_strip_llm_protocol_artifacts_removes_trailing_partial_protocol_tags():
    assert strip_llm_protocol_artifacts("可见文本\n<sta") == "可见文本"
    assert strip_llm_protocol_artifacts('可见文本\n<invoke name="read_file_tool"') == "可见文本"


def test_strip_llm_protocol_artifacts_keeps_non_protocol_trailing_angle_brackets():
    assert strip_llm_protocol_artifacts("see the <stack") == "see the <stack"
    assert strip_llm_protocol_artifacts("open the <parser") == "open the <parser"
    assert strip_llm_protocol_artifacts("click the <toolbar") == "click the <toolbar"


def test_sanitize_assistant_visible_text_hides_unclosed_think_blocks():
    assert sanitize_assistant_visible_text("<think>内部推理") == ""
    assert sanitize_assistant_visible_text("<think>内部推理</think>可见") == "可见"
