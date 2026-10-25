import pytest

from core.web.services import cli_agent_protocols as protocols


@pytest.mark.parametrize("output", ["done", "completed", "failed", "error", "已完成", "失败", "Working"])
@pytest.mark.parametrize("marker", ["", "[VIBELUTION_CLI_DONE:task-own]"])
def test_codex_requires_own_marker_instead_of_natural_status_words(output, marker):
    assert protocols.detect_task_status("codex_code", output, completion_marker=marker) == ""


def test_codex_input_echo_cannot_contain_the_generated_completion_marker():
    marker = protocols.completion_marker_for_task("cli-task-random-123")
    payload = protocols.task_input_for_adapter("codex_code", "Inspect the source", completion_marker=marker)
    assert marker not in payload
    assert marker.strip("[]") in payload
    assert protocols.detect_task_status("codex_code", payload, completion_marker=marker) == ""
    assert protocols.detect_task_status("codex_code", "[VIBELUTION_CLI_DONE:other]", completion_marker=marker) == ""
    assert protocols.detect_task_status("codex_code", "completed\n" + marker, completion_marker=marker) == "completed"


def test_other_adapter_protocols_keep_their_existing_completion_contracts():
    mimo = protocols.protocol_for_adapter("mimo_code")
    assert mimo.marker_completion_required is True
    assert mimo.allow_idle_completion_with_marker is True
    assert protocols.detect_task_status("claude_code", "completed") == "completed"
    assert protocols.detect_task_status("claude_code", "permission denied") == "failed"


def test_codex_multiline_task_is_one_bracketed_paste_followed_by_one_submit():
    task = "Inspect the first section.\r\nThen the second section.\rFinally report."
    marker = protocols.completion_marker_for_task("cli-task-paste")
    payload = protocols.task_input_for_adapter("codex_code", task, completion_marker=marker)

    assert payload.startswith("\x1b[200~")
    assert payload.endswith("\x1b[201~\r")
    body = payload[len("\x1b[200~"):-len("\x1b[201~\r")]
    assert body.startswith("Inspect the first section.\nThen the second section.\nFinally report.\n\n")
    assert marker.strip("[]") in body
    assert marker not in body
    assert "\r" not in body
    assert payload.count("\r") == 1
    assert protocols.detect_task_status("codex_code", payload, completion_marker=marker) == ""


@pytest.mark.parametrize("adapter", ["mimo_code", "claude_code"])
def test_non_codex_task_payload_keeps_its_existing_multiline_bytes(adapter):
    task = "First line\r\nSecond line"
    assert protocols.task_input_for_adapter(adapter, task) == task + "\r\n"
    marker = protocols.completion_marker_for_task("cli-task-other")
    payload = protocols.task_input_for_adapter(adapter, task, completion_marker=marker)
    expected = task
    if adapter == "mimo_code":
        expected += (
            "\n\n完成本任务后，请在最终回复最后单独输出结束标记。标记格式是：左方括号 + "
            + marker.strip("[]") + " + 右方括号。"
        )
    assert payload == expected + "\r\n"
