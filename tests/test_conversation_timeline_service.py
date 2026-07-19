from core.web.services.conversation_timeline_service import build_conversation_timeline_items


def test_cli_tool_groups_keep_command_title():
    items = build_conversation_timeline_items(
        message_id="message-cli-group",
        feedback_events=[
            {
                "sequence": 1,
                "kind": "tool",
                "status": "done",
                "name": "cli_tool",
                "summary": "运行 pytest",
            },
            {
                "sequence": 2,
                "kind": "tool",
                "status": "done",
                "name": "cli_tool",
                "summary": "运行 npm build",
            },
        ],
        include_assistant_text=False,
        lang="zh",
    )

    assert items == [
        {
            "id": "message-cli-group-timeline-command-group-1-2",
            "kind": "command_group",
            "status": "completed",
            "title": "已运行 2 条命令",
            "summary": "运行 pytest；运行 npm build",
            "sourceOperationIds": [
                "message-cli-group-feedback-1",
                "message-cli-group-feedback-2",
            ],
            "operationIds": [
                "message-cli-group-feedback-1",
                "message-cli-group-feedback-2",
            ],
        }
    ]


def test_search_and_read_tool_groups_use_tool_title_not_command_title():
    items = build_conversation_timeline_items(
        message_id="message-tool-group",
        feedback_events=[
            {
                "sequence": 1,
                "kind": "tool",
                "status": "done",
                "name": "grep_search_tool",
                "summary": "搜索 timeline 标题",
            },
            {
                "sequence": 2,
                "kind": "tool",
                "status": "done",
                "name": "read_file_tool",
                "summary": "读取 timeline 实现",
            },
        ],
        include_assistant_text=False,
        lang="zh",
    )

    assert items[0]["kind"] == "command_group"
    assert items[0]["status"] == "completed"
    assert items[0]["title"] == "已执行 2 项工具"
    assert "命令" not in items[0]["title"]


def test_running_non_shell_tool_groups_use_running_tool_title():
    items = build_conversation_timeline_items(
        message_id="message-running-tool-group",
        feedback_events=[
            {
                "sequence": 1,
                "kind": "tool",
                "status": "done",
                "name": "grep_search_tool",
                "summary": "搜索入口",
            },
            {
                "sequence": 2,
                "kind": "tool",
                "status": "running",
                "name": "read_file_tool",
                "summary": "读取文件",
            },
        ],
        include_assistant_text=False,
        lang="zh",
    )

    assert items[0]["kind"] == "command_group"
    assert items[0]["status"] == "running"
    assert items[0]["title"] == "正在执行 2 项工具"


def test_transport_degraded_and_recovered_statuses_remain_in_timeline():
    degraded = build_conversation_timeline_items(
        message_id="message-transport",
        feedback_events=[
            {
                "sequence": 1,
                "kind": "status",
                "status": "degraded",
                "name": "model_transport",
                "summary": "WebSocket 暂时不可用，正在切换到 HTTP。",
                "error": "no available account",
            }
        ],
        include_assistant_text=False,
        lang="zh",
    )
    recovered = build_conversation_timeline_items(
        message_id="message-transport",
        feedback_events=[
            {
                "sequence": 1,
                "kind": "status",
                "status": "recovered",
                "name": "model_transport",
                "summary": "连接已恢复。",
            }
        ],
        include_assistant_text=False,
        lang="zh",
    )

    assert degraded[0]["status"] == "degraded"
    assert recovered[0]["status"] == "recovered"
