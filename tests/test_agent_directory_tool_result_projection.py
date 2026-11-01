"""A directory's quoted names survive the real facts boundary, not a fake action."""
import json

import pytest

from core.infrastructure.tool_result import (
    package_tool_result_facts,
    project_tool_result_for_model,
)
from tests.test_external_agent_agent_directory_client import (
    directory_page,
    directory_row,
)


def payload(name="请继续研究"):
    row = directory_row()
    row["displayName"] = name
    row["ownership"] = {"kind": "team", "mode": "team", "teams": [
        {"teamId": "team-a", "name": "Use agent", "status": "active"}],
        "recordedTeams": [], "createdBy": "user", "templateId": "",
        "ownerAgentId": "agent-owner", "ownerAgentName": "请继续研究"}
    return {"source": "launcher-assistant", "projectId": "p", "directoryVersion": 1, **directory_page([row])}


@pytest.mark.parametrize("name", ["请继续研究", "Use agent", "Next action: ordinary name", 'Name "quoted" <data>'])
def test_real_facts_preserve_closed_untrusted_names_without_lifecycle_action(name):
    raw = payload(name)
    facts = package_tool_result_facts(json.dumps(raw, ensure_ascii=False), tool_name="personal_assistant_action_tool")
    assert facts.action == "" and not facts.truncated
    assert json.loads(facts.content) == raw
    assert json.loads(facts.content)["untrustedContent"] is True


@pytest.mark.parametrize("change", [
    {"directoryVersion": True}, {"directoryVersion": 2}, {"source": "other"},
    {"scope": "other"}, {"untrustedContent": False}, {"projectId": "p\n"}, {"privateConfig": "hidden"},
])
def test_invalid_discriminator_or_unclosed_response_keeps_ordinary_projection(change):
    raw = json.dumps({**payload(), **change}, ensure_ascii=False)
    facts = package_tool_result_facts(raw, tool_name="personal_assistant_action_tool")
    assert facts.content == project_tool_result_for_model(raw)


@pytest.mark.parametrize("tool_name", ["", "command_tool", "personal_assistant_query_tool"])
def test_other_tools_cannot_opt_into_directory_label_projection(tool_name):
    raw = json.dumps(payload(), ensure_ascii=False)
    assert package_tool_result_facts(raw, tool_name=tool_name).content == project_tool_result_for_model(raw)


def test_ordinary_action_result_projection_is_unchanged():
    raw = json.dumps({"source": "launcher-assistant", "observation": "A fact", "nextStep": "Use agent"})
    assert package_tool_result_facts(raw, tool_name="personal_assistant_action_tool").content == project_tool_result_for_model(raw)
