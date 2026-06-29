import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from core.infrastructure.agent_session import reset_session_state
from core.infrastructure.git_memory import GitMemoryService
from core.infrastructure.tool_executor import ToolExecutor
from core.web.services import agent_directory_service
from core.web.services import chat_room_service
from core.web.services import team_knowledge_service
from core.web.services import team_service
from core.web.services import tool_catalog
from tools.Key_Tools import create_key_tools, create_llm_facing_tools


TEAM_COLLABORATION_TOOLS = {
    "agent_message_tool",
    "source_collection_context_tool",
    "source_collection_stage_writeback_tool",
}

EVOLUTION_TOOLS = {
    "open_evolution_transaction_tool",
    "close_evolution_transaction_tool",
    "get_evolution_fitness_tool",
}

RUNTIME_MEMORY_TOOLS = {
    "read_memory_tool",
    "get_memory_summary_tool",
    "record_learning_tool",
    "search_memory_tool",
    "search_error_archive_tool",
}

TEAM_MEMORY_TOOLS = {
    "unified_memory_search_tool",
    "knowledge_proposal_tool",
    "knowledge_ingestion_tool",
    "knowledge_governance_tasks_tool",
    "knowledge_operations_health_tool",
    "knowledge_governance_plan_tool",
    "knowledge_steward_recommendations_tool",
    "knowledge_steward_workbench_tool",
    "knowledge_rating_suggestion_tool",
}

CURRENT_AGENT_TOOL_CONTRACT = (
    TEAM_COLLABORATION_TOOLS
    | EVOLUTION_TOOLS
    | RUNTIME_MEMORY_TOOLS
    | TEAM_MEMORY_TOOLS
)

RETIRED_TOOL_NAMES = {
    "knowledge_query_tool",
    "knowledge_rag_retrieve_tool",
    "unified_knowledge_search_tool",
    "memory_tools",
    "memory_tools.py",
}


@pytest.fixture(autouse=True)
def _isolate_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("VIBELUTION_AGENT_ID", raising=False)
    monkeypatch.delenv("VIBELUTION_AGENT_DIRECT_SESSION_ID", raising=False)
    reset_session_state()


def _executor_result(tool_name: str, args: dict) -> tuple[str, object]:
    result, action = ToolExecutor().execute(tool_name, args)
    return str(result or ""), action


def test_team_evolution_and_memory_tools_have_current_registry_contract():
    canonical_names = {tool.name for tool in create_key_tools()}
    llm_facing_names = {tool.name for tool in create_llm_facing_tools()}

    assert CURRENT_AGENT_TOOL_CONTRACT.issubset(canonical_names)
    assert CURRENT_AGENT_TOOL_CONTRACT.issubset(llm_facing_names)
    assert RETIRED_TOOL_NAMES.isdisjoint(canonical_names)

    expected_categories = {
        "agent_message_tool": "agent_collaboration",
        "source_collection_context_tool": "media_research",
        "source_collection_stage_writeback_tool": "media_research",
        "open_evolution_transaction_tool": "git_evolution",
        "close_evolution_transaction_tool": "git_evolution",
        "get_evolution_fitness_tool": "git_evolution",
        "record_learning_tool": "memory_context",
        "search_memory_tool": "memory_context",
        "unified_memory_search_tool": "memory_context",
        "knowledge_ingestion_tool": "memory_context",
    }
    for tool_name, category in expected_categories.items():
        metadata = tool_catalog.metadata_for_tool(tool_name)
        assert metadata["category"] == category
        assert metadata["permissionTier"] in {"low", "medium", "high"}
        assert metadata["capabilityTags"], tool_name

    bundles = {bundle["bundleId"]: bundle for bundle in tool_catalog.list_tool_bundles()}
    assert TEAM_COLLABORATION_TOOLS.issubset(set(bundles["source_collection_stage"]["toolNames"]))
    assert {"unified_memory_search_tool"}.issubset(set(bundles["memory_context"]["toolNames"]))
    assert {
        "knowledge_proposal_tool",
        "knowledge_ingestion_tool",
        "knowledge_steward_workbench_tool",
    }.issubset(set(bundles["knowledge_steward"]["toolNames"]))
    assert {
        "open_evolution_transaction_tool",
        "close_evolution_transaction_tool",
        "get_evolution_fitness_tool",
    }.issubset(set(bundles["operations"]["toolNames"]))


def test_agent_message_tool_blocks_without_bound_agent_runtime(monkeypatch):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {})

    result, action = _executor_result(
        "agent_message_tool",
        {"target_agent": "target-agent", "content": "hello"},
    )

    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["error"] == "agent_runtime_missing"


def test_team_memory_write_tools_block_before_service_mutation_when_policy_disallows_base(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Policy blocked memory agent")
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"allowedTools": sorted(TEAM_MEMORY_TOOLS)},
        memory_policy={
            "readKnowledgeBaseIds": ["kb-allowed"],
            "proposeKnowledgeBaseIds": ["kb-allowed"],
            "rateKnowledgeBaseIds": ["kb-allowed"],
        },
    )

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-policy"):
        proposal_result, proposal_action = _executor_result(
            "knowledge_proposal_tool",
            {
                "knowledge_base_id": "kb-blocked",
                "source_type": "manual_user_entry",
                "source_ref_json": '{"note":"blocked"}',
                "proposal_title": "blocked",
                "proposal_content": "should not be submitted",
            },
        )
        rating_result, rating_action = _executor_result(
            "knowledge_rating_suggestion_tool",
            {
                "knowledge_base_id": "kb-blocked",
                "target_type": "knowledge_item",
                "knowledge_item_id": "item-1",
                "importance_level": "high",
                "stability": "stable",
                "review_priority": "elevated",
                "marking_reason": "blocked policy",
                "confidence": 0.9,
            },
        )

    proposal_payload = json.loads(proposal_result)
    rating_payload = json.loads(rating_result)
    assert proposal_action is None
    assert rating_action is None
    assert proposal_payload["status"] == "blocked"
    assert proposal_payload["error"] == "knowledge_base_not_in_memory_policy"
    assert rating_payload["status"] == "blocked"
    assert rating_payload["error"] == "knowledge_base_not_in_memory_policy"


class _MemoryWorkspace:
    def __init__(self):
        self.memories: list[dict] = []

    def add_long_term_memory(self, generation, category, content, title=None, importance=1):
        self.memories.append(
            {
                "generation": generation,
                "category": category,
                "content": content,
                "title": title,
                "importance": importance,
            }
        )
        return True

    def search_long_term_memory(self, query, category=None, limit=20):
        query_text = str(query or "").casefold()
        results = [
            item
            for item in self.memories
            if (not category or item["category"] == category)
            and (
                query_text in str(item.get("title") or "").casefold()
                or query_text in str(item.get("content") or "").casefold()
            )
        ]
        return results[:limit]

    def search_error_archive(self, error_type=None, limit=20):
        return []

    def get_recent_errors(self, limit=20):
        return []


def test_runtime_memory_learning_tools_persist_and_search_through_executor(monkeypatch):
    import tools.memory_tools as memory_tools

    workspace = _MemoryWorkspace()
    monkeypatch.setattr(memory_tools, "get_workspace", lambda: workspace)

    write_result, write_action = _executor_result(
        "record_learning_tool",
        {
            "category": "SYSTEM_INSIGHT",
            "title": "contract memory",
            "content": "Agent memory tools must round trip through ToolExecutor.",
            "importance": 4,
        },
    )
    search_result, search_action = _executor_result(
        "search_memory_tool",
        {"query": "round trip", "category": "SYSTEM_INSIGHT"},
    )

    write_payload = json.loads(write_result)
    search_payload = json.loads(search_result)
    assert write_action is None
    assert search_action is None
    assert write_payload["status"] == "ok"
    assert search_payload["status"] == "ok"
    assert search_payload["count"] == 1
    assert search_payload["results"][0]["title"] == "contract memory"


def test_source_collection_stage_tools_execute_current_service_contract(monkeypatch):
    from core.web.services import team_workflow_orchestration_service as workflow_service

    seen: dict[str, dict] = {}

    def fake_context(team_id, **kwargs):
        seen["context"] = {"team_id": team_id, **kwargs}
        return {
            "contextKind": "source_collection_stage_task_context",
            "teamId": team_id,
            "runId": kwargs["run_id"],
            "stageId": kwargs["stage_id"],
            "taskId": kwargs["task_id"],
            "counts": {"recordCount": 0, "candidateCount": 0},
        }

    def fake_writeback(team_id, task_id, payload):
        seen["writeback"] = {"team_id": team_id, "task_id": task_id, "payload": payload}
        return {
            "status": "completed",
            "teamId": team_id,
            "taskId": task_id,
            "runId": "run-1",
            "stageId": "stage-1",
        }

    monkeypatch.setattr(workflow_service, "get_source_collection_stage_task_context", fake_context)
    monkeypatch.setattr(workflow_service, "writeback_source_collection_stage_session_task", fake_writeback)

    context_result, context_action = _executor_result(
        "source_collection_context_tool",
        {
            "team_id": "team-1",
            "run_id": "run-1",
            "stage_id": "stage-1",
            "task_id": "task-1",
            "record_limit": 3,
            "candidate_limit": 2,
            "context_mode": "compact",
        },
    )
    writeback_result, writeback_action = _executor_result(
        "source_collection_stage_writeback_tool",
        {
            "team_id": "team-1",
            "task_id": "task-1",
            "status": "completed",
            "summary": "done",
            "result_json": '{"candidateCount": 2}',
            "evidence_refs_json": '[{"type":"source","id":"s1"}]',
            "next_actions_json": '["review"]',
            "recorded_by_agent": "agent-1",
        },
    )

    context_payload = json.loads(context_result)
    writeback_payload = json.loads(writeback_result)
    assert context_action is None
    assert writeback_action is None
    assert context_payload["contextKind"] == "source_collection_stage_task_context"
    assert seen["context"]["team_id"] == "team-1"
    assert seen["context"]["record_limit"] == 3
    assert seen["context"]["candidate_limit"] == 2
    assert writeback_payload["status"] == "completed"
    assert seen["writeback"]["payload"]["result"] == {"candidateCount": 2}
    assert seen["writeback"]["payload"]["evidenceRefs"] == [{"type": "source", "id": "s1"}]
    assert seen["writeback"]["payload"]["nextActions"] == ["review"]


class _FakeGitWorkspace:
    def __init__(self, project_root: Path, db_path: Path):
        self.project_root = project_root
        self._db_path = db_path

    @contextmanager
    def get_db_connection(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


class _FakeBus:
    def __init__(self):
        self.events: list[tuple] = []

    def publish(self, name, data=None, source=None):
        self.events.append((name, data, source))

    def subscribe(self, name, handler):
        return None


def test_evolution_transaction_tools_open_and_close_through_executor(tmp_path, monkeypatch):
    import core.infrastructure.git_memory as git_memory_module
    import tools.git_tools as git_tools

    workspace = _FakeGitWorkspace(tmp_path, tmp_path / "brain.db")
    bus = _FakeBus()
    monkeypatch.setattr(git_memory_module, "get_workspace", lambda: workspace)
    monkeypatch.setattr(git_memory_module, "get_event_bus", lambda: bus)
    service = GitMemoryService()
    monkeypatch.setattr(service, "_git_head_rev", lambda: "HEAD-test")
    monkeypatch.setattr(git_tools, "get_git_memory_service", lambda: service)
    session = reset_session_state()

    opened, open_action = _executor_result(
        "open_evolution_transaction_tool",
        {"summary": "contract test transaction"},
    )
    opened_payload = json.loads(opened)
    txn_id = opened_payload["txn_id"]
    assert session.get_active_evolution_txn() == txn_id
    closed, close_action = _executor_result(
        "close_evolution_transaction_tool",
        {"txn_id": txn_id, "status": "failed", "summary": "closed by contract test"},
    )
    closed_payload = json.loads(closed)

    assert open_action is None
    assert close_action is None
    assert opened_payload["status"] == "success"
    assert session.get_active_evolution_txn() is None
    assert closed_payload["status"] == "success"
    assert closed_payload["transaction_status"] == "failed"
    with workspace.get_db_connection() as conn:
        row = conn.execute(
            "SELECT status, summary FROM EvolutionTransaction WHERE txn_id = ?",
            (txn_id,),
        ).fetchone()
    assert dict(row) == {"status": "failed", "summary": "closed by contract test"}
