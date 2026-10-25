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
