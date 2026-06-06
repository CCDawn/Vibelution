import json

from core.web.services import agent_directory_service
from core.research import knowledge_base
from tools import research_knowledge_tools
from tools.Key_Tools import create_llm_facing_tools


def _seed_knowledge_base(root):
    path = root / "workspace" / "research" / "knowledge_base.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "updatedAt": "2026-05-28T00:00:00+00:00",
                "entries": [
                    {
                        "entryId": "entry-paper-1",
                        "kind": "paper",
                        "title": "Agentic literature review benchmark",
                        "url": "https://example.invalid/paper",
                        "summary": "A benchmark for agentic literature review.",
                        "tags": ["agentic", "literature"],
                        "categories": ["literature"],
                        "sourceIds": ["source-paper-1"],
                        "lastSeenAt": "2026-05-28T00:00:00+00:00",
                    },
                    {
                        "entryId": "entry-dataset-1",
                        "kind": "dataset",
                        "title": "Scientific discovery dataset",
                        "url": "https://example.invalid/dataset",
                        "summary": "A dataset for scientific discovery agents.",
                        "tags": ["dataset"],
                        "categories": ["dataset"],
                        "sourceIds": ["source-dataset-1"],
                        "lastSeenAt": "2026-05-27T00:00:00+00:00",
                    },
                ],
                "claims": [
                    {
                        "recordId": "claim-1",
                        "type": "claim",
                        "content": "Agentic review needs traceable evidence.",
                        "tags": ["agentic"],
                        "sourceIds": ["source-paper-1"],
                        "createdAt": "2026-05-28T00:00:00+00:00",
                    }
                ],
                "evidence": [],
                "gaps": [
                    {
                        "recordId": "gap-1",
                        "type": "gap",
                        "content": "Dataset coverage is still thin.",
                        "tags": ["dataset"],
                        "sourceIds": ["source-dataset-1"],
                        "createdAt": "2026-05-28T00:00:00+00:00",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_research_knowledge_tool_requires_explicit_agent_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(knowledge_base, "get_workspace", lambda: type("Workspace", (), {"project_root": tmp_path})())
    _seed_knowledge_base(tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="普通科研 Agent")

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-research"):
        result = json.loads(research_knowledge_tools.research_knowledge_query_tool(query="agentic"))

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["error"] == "tool_not_explicitly_allowed"


def test_research_knowledge_tool_queries_allowed_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(knowledge_base, "get_workspace", lambda: type("Workspace", (), {"project_root": tmp_path})())
    path = _seed_knowledge_base(tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="知识库 Agent")
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"allowedTools": ["research_knowledge_query_tool"]},
    )

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-research"):
        result = json.loads(
            research_knowledge_tools.research_knowledge_query_tool(
                query="agentic",
                collection="all",
                kind="paper",
                limit=5,
            )
        )

    assert result["ok"] is True
    assert result["path"] == str(path)
    assert result["results"]["entries"][0]["entryId"]
    assert result["results"]["entries"][0]["kind"] == "paper"
    assert result["results"]["entries"][0]["title"] == "Agentic literature review benchmark"
    assert result["results"]["entries"][0]["url"] == "https://example.invalid/paper"
    assert result["results"]["claims"][0]["recordId"]
    assert result["limit"] == 5


def test_research_knowledge_tool_is_llm_facing_but_hidden_without_explicit_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="默认工具 Agent")
    tools = [tool for tool in create_llm_facing_tools() if tool.name in {"research_knowledge_query_tool", "agent_message_tool"}]

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-tools"):
        visible = agent_directory_service.filter_llm_tools_for_current_agent(tools)

    assert {tool.name for tool in tools} == {"research_knowledge_query_tool", "agent_message_tool"}
    assert [tool.name for tool in visible] == ["agent_message_tool"]

    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"allowedTools": ["research_knowledge_query_tool"]},
    )
    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-tools"):
        visible = agent_directory_service.filter_llm_tools_for_current_agent(tools)

    assert [tool.name for tool in visible] == ["agent_message_tool", "research_knowledge_query_tool"]


def test_tool_policy_filtering_stays_structural_not_prompt_text(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="受限工具 Agent", primary_mode="general")
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"allowedTools": ["agent_message_tool"]},
    )
    tools = [tool for tool in create_llm_facing_tools() if tool.name in {"agent_message_tool", "web_search_tool"}]

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-tools"):
        visible = agent_directory_service.filter_llm_tools_for_current_agent(tools)

    assert [tool.name for tool in visible] == ["agent_message_tool"]
