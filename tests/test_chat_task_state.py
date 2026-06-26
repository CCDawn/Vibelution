#!/usr/bin/env python3
"""chat result helper tests."""

from core.chat.chat_result_contract import build_chat_coding_result_contract
from core.chat.chat_result_formatter import format_chat_reply


def test_build_chat_coding_result_contract_extracts_structured_fields_from_tool_trace():
    contract = build_chat_coding_result_contract(
        {
            "status": "completed",
            "summary": "已完成修复并验证。",
            "tool_call_count": 3,
            "tool_trace": [
                {
                    "name": "read_file_tool",
                    "args": {"file_path": "core/ui/cli_ui.py"},
                    "result_preview": "read ok",
                },
                {
                    "name": "apply_diff_edit_tool",
                    "args": {"file_path": "core/ui/cli_ui.py"},
                    "result_preview": "patched",
                },
                {
                    "name": "run_test_for_tool",
                    "args": {"source_path": "core/ui/cli_ui.py"},
                    "result_preview": "3 passed in 0.40s",
                },
            ],
        }
    )

    assert contract["read_files"] == ["core/ui/cli_ui.py"]
    assert contract["changed_files"] == ["core/ui/cli_ui.py"]
    assert contract["verification_status"] == "passed"
    assert contract["outcome"] == "done"
    assert contract["no_change"] is False


def test_build_chat_coding_result_contract_treats_completed_file_artifact_as_done_without_verify():
    contract = build_chat_coding_result_contract(
        {
            "status": "completed",
            "summary": "文件已成功创建：workspace/agents/a/outputs/presentation_structure.html\n任务完成：10页HTML演示文稿已生成。",
            "raw_output": "文件已成功创建：workspace/agents/a/outputs/presentation_structure.html\n任务完成：10页HTML演示文稿已生成。",
            "tool_call_count": 1,
            "tool_trace": [
                {
                    "name": "write_file_tool",
                    "args": {"file_path": "workspace/agents/a/outputs/presentation_structure.html"},
                    "result_preview": "[创建文件] [OK] 成功",
                },
            ],
        }
    )

    assert contract["changed_files"] == ["workspace/agents/a/outputs/presentation_structure.html"]
    assert contract["verification_status"] == ""
    assert contract["outcome"] == "done"
    assert contract["no_change"] is False


def test_build_chat_coding_result_contract_keeps_explicit_progress_even_with_completion_words():
    contract = build_chat_coding_result_contract(
        {
            "status": "completed",
            "summary": "我已经完成第一项优化，下一步继续收口剩余日志路径。",
            "raw_output": "我已经完成第一项优化，下一步继续收口剩余日志路径。",
            "outcome": "progress",
            "recommended_next_action": "继续收口剩余日志路径。",
            "tool_trace": [
                {
                    "name": "write_file_tool",
                    "args": {"file_path": "docs/partial.md"},
                    "result_preview": "[创建文件] [OK] 成功",
                },
            ],
        }
    )

    assert contract["outcome"] == "progress"
    assert contract["next_action"] == "继续收口剩余日志路径。"


def test_build_chat_coding_result_contract_blocks_cross_platform_pytest_warning():
    contract = build_chat_coding_result_contract(
        {
            "status": "completed",
            "summary": "测试通过。再运行配置相关的测试验证：",
            "raw_output": "测试通过。再运行配置相关的测试验证：",
            "tool_call_count": 3,
            "tool_trace": [
                {
                    "name": "apply_diff_edit_tool",
                    "args": {"file_path": "config/settings.py"},
                    "result_preview": "[编辑] 成功修改 config/settings.py",
                },
                {
                    "name": "run_test_for_tool",
                    "args": {"source_path": "config/workbench.py"},
                    "result_preview": "37 passed in 10.10s",
                },
                {
                    "name": "cli_tool",
                    "args": {
                        "command": (
                            "python -m pytest tests/test_config.py -x -q "
                            "2>&1 | head -50"
                        )
                    },
                    "result_preview": (
                        "[跨平台警告] 在 Windows 上检测到 Unix shell 片段: "
                        "python -m pytest tests/test_config.py -x -q 2>&1 | head -50"
                    ),
                },
            ],
        }
    )

    assert contract["verification_status"] == "failed"
    assert "跨平台警告" in contract["verification_summary"]
    assert contract["blocked_reason"] == "pytest 命令被跨平台检查拦截，验证尚未执行。"
    assert contract["outcome"] == "blocked"


def test_build_chat_coding_result_contract_does_not_pass_missing_mapped_test():
    contract = build_chat_coding_result_contract(
        {
            "status": "completed",
            "summary": "已修改文件，准备验证。",
            "changed_files": ["core/ui/cli_ui.py"],
            "tool_trace": [
                {
                    "name": "run_test_for_tool",
                    "args": {"source_path": "core/ui/cli_ui.py"},
                    "result_preview": (
                        "[运行测试] 未找到对应测试文件\n"
                        "提示: 请先创建测试文件，或手动运行 pytest"
                    ),
                }
            ],
        }
    )

    assert contract["verification_status"] == "failed"
    assert "未找到对应测试文件" in contract["verification_summary"]
    assert contract["blocked_reason"] == "run_test_for_tool 未找到映射测试，验证尚未执行。"
    assert contract["outcome"] == "blocked"


def test_build_chat_coding_result_contract_lint_issues_are_failed_verification():
    contract = build_chat_coding_result_contract(
        {
            "status": "completed",
            "summary": "已修改文件并运行 lint。",
            "changed_files": ["agent.py"],
            "tool_trace": [
                {
                    "name": "python_lint_tool",
                    "args": {"target": "agent.py"},
                    "result_preview": '{"status": "ok", "issue_count": 2, "issues": []}',
                }
            ],
        }
    )

    assert contract["verification_status"] == "failed"
    assert "issue_count" in contract["verification_summary"]
    assert contract["blocked_reason"] == "python_lint_tool 发现 lint 问题，验证未通过。"
    assert contract["outcome"] == "blocked"


def test_build_chat_coding_result_contract_py_compile_warning_is_failed_verification():
    contract = build_chat_coding_result_contract(
        {
            "status": "completed",
            "summary": "已修改文件并运行编译检查。",
            "changed_files": ["agent.py"],
            "tool_trace": [
                {
                    "name": "cli_tool",
                    "args": {"command": "python -m py_compile agent.py"},
                    "result_preview": "[WARNING | Exit Code: 1]\nSyntaxError: invalid syntax",
                }
            ],
        }
    )

    assert contract["verification_status"] == "failed"
    assert "SyntaxError" in contract["verification_summary"]
    assert contract["blocked_reason"] == "python -m py_compile 执行失败，验证未通过。"
    assert contract["outcome"] == "blocked"


def test_format_chat_reply_adds_structured_coding_summary():
    reply = format_chat_reply(
        {
            "status": "completed",
            "summary": "已修复问题。",
        },
        {
            "kind": "coding",
            "status": "done",
            "changed_files": ["core/ui/cli_ui.py"],
            "verification_status": "passed",
            "verification_summary": "2 passed",
        },
    )

    assert "已修复问题。" in reply
    assert "修改文件：core/ui/cli_ui.py" in reply
    assert "验证：通过。2 passed" in reply


def test_format_chat_reply_can_summarize_structured_result_without_task_snapshot():
    reply = format_chat_reply(
        {
            "status": "completed",
            "summary": "",
            "raw_output": "",
            "outcome": "done",
            "changed_files": ["core/ui/cli_ui.py"],
            "verification_status": "passed",
            "verification_summary": "3 passed in 0.40s",
        }
    )

    assert "修改文件：core/ui/cli_ui.py" in reply
    assert "验证：通过。3 passed in 0.40s" in reply
