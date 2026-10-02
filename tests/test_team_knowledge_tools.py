import json

import pytest

from core.web.services import (
    agent_directory_service,
    agent_role_tool_profile_service,
    chat_room_service,
    team_knowledge_service,
    team_service,
)
from tools import team_knowledge_tools
from tools.Key_Tools import create_llm_facing_tools


@pytest.fixture(autouse=True)
def _isolate_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))


def _seed_team_knowledge(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    lead = agent_directory_service.create_agent_instance(display_name="Knowledge Lead")
    member = agent_directory_service.create_agent_instance(display_name="Knowledge Member")
    team = team_service.create_team(
        name="Tool Knowledge Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    base = team_knowledge_service.create_knowledge_base(team["teamId"], name="Tool KB", actor_agent_id=lead["agentId"])
    base_ref = base.get("scopedKnowledgeBaseId") or base["knowledgeBaseId"]
    agent_directory_service.update_agent_instance(
        member["agentId"],
        tool_policy={
            "allowedTools": [
                "unified_memory_search_tool",
                "knowledge_proposal_tool",
                "knowledge_ingestion_tool",
                "knowledge_governance_tasks_tool",
                "knowledge_operations_health_tool",
                "knowledge_governance_plan_tool",
                "knowledge_steward_recommendations_tool",
                "knowledge_steward_workbench_tool",
            ]
        },
        memory_policy={
            "readKnowledgeBaseIds": [base_ref],
            "proposeKnowledgeBaseIds": [base_ref],
            "rateKnowledgeBaseIds": [base_ref],
        },
    )
    return {"lead": lead, "member": member, "team": team, "base": base}


def _promote_central_source(env: dict, *, source_type: str = "manual_user_entry", title: str = "Tool source", source_ref: dict | None = None) -> dict:
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        env["team"]["teamId"],
        source_type=source_type,
        source_ref=source_ref or {"note": title},
        original_content="Tool test source content.",
        original_filename="tool-source.txt",
        title=title,
        actor_agent_id=env["member"]["agentId"],
    )
    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        env["team"]["teamId"],
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )
    return reviewed["centralSource"]


def _source_artifact(env: dict, *, title: str = "Tool source", knowledge_base_id: str = "") -> dict:
    central_source = _promote_central_source(env, title=title)
    return team_knowledge_service.create_source_artifact_from_central_source(
        knowledge_base_id or _kb_ref(env),
        central_source["centralSourceId"],
        actor_agent_id=env["member"]["agentId"],
        title=title,
    )


def _source_ids(env: dict, *, title: str = "Tool source", knowledge_base_id: str = "") -> list[str]:
    source = _source_artifact(env, title=title, knowledge_base_id=knowledge_base_id)
    return [source["sourceArtifactId"]]


def _kb_ref(env: dict) -> str:
    return str(env["base"].get("scopedKnowledgeBaseId") or env["base"]["knowledgeBaseId"])


def _create_approved_owner_knowledge_item(
    *,
    owner_type: str,
    owner_id: str,
    knowledge_base_id: str,
    actor_agent_id: str,
    reviewer_agent_id: str,
    title: str,
    content: str,
) -> dict:
    source_type = "agent_authored" if owner_type == "agent" else "manual_user_entry"
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        owner_type,
        owner_id,
        source_type=source_type,
        source_ref={"note": title},
        original_content=content,
        original_filename=f"{title}.txt",
        title=title,
        actor_agent_id=actor_agent_id,
    )
    reviewed_source = team_knowledge_service.review_owner_inbox_source(
        owner_type,
        owner_id,
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=reviewer_agent_id,
    )
    artifact = team_knowledge_service.create_source_artifact_from_central_source(
        knowledge_base_id,
        reviewed_source["centralSource"]["centralSourceId"],
        actor_agent_id=actor_agent_id,
        title=title,
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_base_id,
        source_artifact_ids=[artifact["sourceArtifactId"]],
        proposed_by_agent_id=actor_agent_id,
        title=title,
        content=content,
    )
    return team_knowledge_service.review_refinement_proposal(
        knowledge_base_id,
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=reviewer_agent_id,
    )["item"]


_LLM_FACING_KNOWLEDGE_TOOL_NAMES = {
    "unified_memory_search_tool",
    "read_knowledge_item_tool",
    "knowledge_proposal_tool",
    "knowledge_proposal_review_tool",
    "knowledge_rating_suggestion_tool",
    "knowledge_operations_health_tool",
    "knowledge_governance_plan_tool",
    "knowledge_steward_recommendations_tool",
    "knowledge_steward_workbench_tool",
}
_LLM_FACING_PRIVATE_MEMORY_TOOL_NAMES = {"search_agent_private_memory_tool"}
_LLM_FACING_ATTACHMENT_STAGE_TOOL_NAMES = {"knowledge_stage_session_attachment_tool"}
_LLM_FACING_COMMUNICATION_TOOL_NAMES = {
    "agent_message_tool",
}
_LLM_FACING_TOOL_NAMES = _LLM_FACING_KNOWLEDGE_TOOL_NAMES | _LLM_FACING_COMMUNICATION_TOOL_NAMES
_LLM_FACING_TOOL_NAMES |= _LLM_FACING_PRIVATE_MEMORY_TOOL_NAMES
_LLM_FACING_TOOL_NAMES |= _LLM_FACING_ATTACHMENT_STAGE_TOOL_NAMES


def _llm_facing_knowledge_tools():
    return [
        tool
        for tool in create_llm_facing_tools()
        if tool.name in _LLM_FACING_TOOL_NAMES
    ]


def test_team_knowledge_tools_are_hidden_without_explicit_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Default Agent")
    tools = _llm_facing_knowledge_tools()

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-tools"):
        visible = agent_directory_service.filter_llm_tools_for_current_agent(tools)

    assert {tool.name for tool in tools} == _LLM_FACING_TOOL_NAMES
    assert {tool.name for tool in visible} == (
        _LLM_FACING_COMMUNICATION_TOOL_NAMES
        | _LLM_FACING_PRIVATE_MEMORY_TOOL_NAMES
        | _LLM_FACING_ATTACHMENT_STAGE_TOOL_NAMES
    )
    assert not ({tool.name for tool in visible} & _LLM_FACING_KNOWLEDGE_TOOL_NAMES)


def test_search_agent_private_memory_tool_reads_only_current_agents_private_knowledge(tmp_path, monkeypatch):
    from core.web.services import user_content_markdown_service

    env = _seed_team_knowledge(tmp_path, monkeypatch)
    owner_id = env["member"]["agentId"]
    other = agent_directory_service.create_agent_instance(display_name="Private Memory Other Agent")
    own_base = team_knowledge_service.create_agent_knowledge_base(
        owner_id,
        name="Current Agent Private Knowledge",
        actor_agent_id=owner_id,
    )
    other_base = team_knowledge_service.create_agent_knowledge_base(
        other["agentId"],
        name="Other Agent Private Knowledge",
        actor_agent_id=other["agentId"],
    )
    query_text = "cobalt archive private retrieval"
    own_item = _create_approved_owner_knowledge_item(
        owner_type="agent",
        owner_id=owner_id,
        knowledge_base_id=own_base["knowledgeBaseId"],
        actor_agent_id=owner_id,
        reviewer_agent_id=owner_id,
        title="Current Agent Private Note",
        content=f"{query_text}: this belongs to the current Agent.",
    )
    other_item = _create_approved_owner_knowledge_item(
        owner_type="agent",
        owner_id=other["agentId"],
        knowledge_base_id=other_base["knowledgeBaseId"],
        actor_agent_id=other["agentId"],
        reviewer_agent_id=other["agentId"],
        title="Other Agent Private Note",
        content=f"{query_text}: this belongs to another Agent.",
    )
    team_item = _create_approved_owner_knowledge_item(
        owner_type="team",
        owner_id=env["team"]["teamId"],
        knowledge_base_id=_kb_ref(env),
        actor_agent_id=owner_id,
        reviewer_agent_id=env["lead"]["agentId"],
        title="Team Shared Note",
        content=f"{query_text}: this belongs to the Team.",
    )

    monkeypatch.setattr(user_content_markdown_service, "PROJECT_ROOT", tmp_path / "project")
    user_source = tmp_path / "user-source"
    user_source.mkdir()
    (user_source / "user-note.md").write_text(f"# User note\n{query_text}: user content.", encoding="utf-8")
    user_space = user_content_markdown_service.import_markdown_space(str(user_source), space_name="Private Search User Notes")
    agent_directory_service.update_agent_instance(
        owner_id,
        memory_policy={
            "readKnowledgeBaseIds": [_kb_ref(env)],
            "readUserContentSpaceIds": [user_space["space"]["spaceId"]],
        },
    )

    with agent_directory_service.active_agent_runtime(owner_id, session_id="session-private-search"):
        payload = json.loads(
            team_knowledge_tools.search_agent_private_memory_tool(
                query=query_text,
                query_mode="hybrid",
                limit=10,
            )
        )

    result_ids = {item.get("knowledgeItemId") for item in payload["results"]}
    assert payload["ok"] is True
    assert payload["summary"]["userContentResultCount"] == 0
    assert result_ids == {own_item["knowledgeItemId"]}
    assert other_item["knowledgeItemId"] not in result_ids
    assert team_item["knowledgeItemId"] not in result_ids
    assert all(item.get("ownerType") == "agent" and item.get("ownerId") == owner_id for item in payload["results"])


def test_search_agent_private_memory_tool_hides_internal_errors(monkeypatch):
    monkeypatch.setattr(team_knowledge_tools, "_current_runtime", lambda: {"agentId": "agent-private"})
    monkeypatch.setattr(team_knowledge_tools, "_record_event", lambda *args, **kwargs: None)

    def fail_list(*args, **kwargs):
        raise FileNotFoundError("C:/private/runtime/knowledge.json")

    monkeypatch.setattr(team_knowledge_service, "list_agent_knowledge_bases", fail_list)
    payload = json.loads(team_knowledge_tools.search_agent_private_memory_tool(query="fact"))

    assert payload["ok"] is False
    assert payload["error"] == "private_memory_search_failed"
    assert "C:/private/runtime" not in json.dumps(payload)


def test_session_attachment_stage_tool_binds_agent_and_session_from_runtime(monkeypatch):
    from core.web.services import runtime_scene_service

    calls = []
    events = []
    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", lambda *args, **kwargs: events.append(kwargs))

    def collect(owner_type, owner_id, **kwargs):
        calls.append({"ownerType": owner_type, "ownerId": owner_id, **kwargs})
        return {
            "inboxSourceId": "inbox-staged",
            "sourceType": "manual_user_entry",
            "status": "pending",
            "originalPath": "private/hidden-document.txt",
            "localCopies": ["private/hidden-document.txt"],
            "sourceRef": {"localCopies": ["private/hidden-document.txt"]},
        }

    monkeypatch.setattr(
        team_knowledge_tools,
        "_current_runtime",
        lambda: {"agentId": "agent-current", "sessionId": "session-current"},
    )
    monkeypatch.setattr(team_knowledge_service, "collect_session_attachment_to_inbox", collect)

    private_result = json.loads(
        team_knowledge_tools.knowledge_stage_session_attachment_tool(attachment_id="attachment-1")
    )
    team_result = json.loads(
        team_knowledge_tools.knowledge_stage_session_attachment_tool(
            attachment_id="attachment-2",
            team_id="team-authorized-by-service",
            title="Team source",
            summary="A staged team source.",
        )
    )
    titled_result = json.loads(
        team_knowledge_tools.knowledge_stage_session_attachment_tool(
            attachment_id="attachment-1", title="Updated source title"
        )
    )

    assert private_result["ok"] is True
    assert private_result["ownerType"] == "agent"
    assert private_result["ownerId"] == "agent-current"
    assert private_result["reviewStatus"] == "pending"
    assert "source" not in private_result
    assert "private/hidden-document.txt" not in json.dumps(private_result)
    assert "sessionId" not in private_result
    assert events and all("sessionId" not in event["fields"] for event in events)
    assert team_result["ok"] is True
    assert team_result["ownerType"] == "team"
    assert team_result["ownerId"] == "team-authorized-by-service"
    stage_keys = [call.pop("idempotency_key") for call in calls]
    assert all(key.startswith("agent-stage-") and len(key) == 76 for key in stage_keys)
    assert stage_keys[0] != stage_keys[1]
    assert stage_keys[0] != stage_keys[2]
    assert all("idempotency_key" not in json.dumps(result) for result in (private_result, team_result))
    assert calls == [
        {
            "ownerType": "agent",
            "ownerId": "agent-current",
            "session_id": "session-current",
            "attachment_id": "attachment-1",
            "actor_agent_id": "agent-current",
            "title": "",
            "summary": "",
        },
        {
            "ownerType": "team",
            "ownerId": "team-authorized-by-service",
            "session_id": "session-current",
            "attachment_id": "attachment-2",
            "actor_agent_id": "agent-current",
            "title": "Team source",
            "summary": "A staged team source.",
        },
        {
            "ownerType": "agent",
            "ownerId": "agent-current",
            "session_id": "session-current",
            "attachment_id": "attachment-1",
            "actor_agent_id": "agent-current",
            "title": "Updated source title",
            "summary": "",
        },
    ]
    assert titled_result["reviewStatus"] == "pending"

    import inspect

    parameters = inspect.signature(team_knowledge_tools.knowledge_stage_session_attachment_tool).parameters
    assert not {"owner_type", "owner_id", "agent_id", "session_id", "actor_agent_id", "path"} & set(parameters)


def test_session_attachment_stage_tool_requires_bound_runtime_session(monkeypatch):
    calls = []
    monkeypatch.setattr(team_knowledge_tools, "_current_runtime", lambda: {"agentId": "agent-current"})
    monkeypatch.setattr(
        team_knowledge_service,
        "collect_session_attachment_to_inbox",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    payload = json.loads(team_knowledge_tools.knowledge_stage_session_attachment_tool(attachment_id="attachment-1"))

    assert payload["ok"] is False
    assert payload["error"] == "agent_session_identity_required"
    assert calls == []


def test_session_attachment_stage_tool_redacts_sensitive_error_details(monkeypatch):
    from core.web.services import runtime_scene_service

    events = []
    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", lambda *args, **kwargs: events.append(kwargs))
    monkeypatch.setattr(
        team_knowledge_tools,
        "_current_runtime",
        lambda: {"agentId": "agent-current", "sessionId": "session-secret"},
    )

    def fail(*args, **kwargs):
        raise ValueError("private/path/session-secret")

    monkeypatch.setattr(team_knowledge_service, "collect_session_attachment_to_inbox", fail)
    payload = json.loads(team_knowledge_tools.knowledge_stage_session_attachment_tool(attachment_id="attachment-1"))
    assert payload["ok"] is False
    assert "private/path" not in json.dumps(payload)
    assert "session-secret" not in json.dumps(payload)
    assert events and all("sessionId" not in event["fields"] for event in events)


def test_disabled_private_memory_blocks_default_search_and_private_attachment_stage(monkeypatch):
    monkeypatch.setattr(
        team_knowledge_tools,
        "_current_runtime",
        lambda: {
            "agentId": "agent-current",
            "sessionId": "session-current",
            "memoryPolicy": {"enabled": False},
        },
    )
    search = json.loads(team_knowledge_tools.search_agent_private_memory_tool(query="private fact"))
    stage = json.loads(
        team_knowledge_tools.knowledge_stage_session_attachment_tool(attachment_id="attachment-1")
    )
    assert search["ok"] is False and search["error"] == "personal_memory_disabled"
    assert stage["ok"] is False and stage["error"] == "personal_memory_disabled"


def test_proposal_review_tool_uses_runtime_reviewer_and_returns_bounded_result(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    base_ref = _kb_ref(env)
    proposal = team_knowledge_service.create_refinement_proposal(
        base_ref,
        source_artifact_ids=_source_ids(env),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Reviewed fact",
        content="A reviewed fact.",
    )
    reviewer_id = env["lead"]["agentId"]
    monkeypatch.setattr(
        team_knowledge_tools,
        "_current_runtime",
        lambda: {
            "agentId": reviewer_id,
            "memoryPolicy": {"reviewKnowledgeBaseIds": [base_ref]},
        },
    )

    payload = json.loads(
        team_knowledge_tools.knowledge_proposal_review_tool(
            base_ref, proposal["proposalId"], "applied"
        )
    )

    assert payload["ok"] is True
    assert payload["status"] == "applied"
    assert payload["knowledgeItemId"]
    assert "proposal" not in payload and "item" not in payload
    reviewed = team_knowledge_service.list_knowledge_items(base_ref, agent_id=reviewer_id)
    assert any(item["knowledgeItemId"] == payload["knowledgeItemId"] for item in reviewed["items"])

    import inspect

    parameters = inspect.signature(team_knowledge_tools.knowledge_proposal_review_tool).parameters
    assert not {"actor_agent_id", "reviewed_by_agent_id", "owner_id"} & set(parameters)


def test_session_attachment_stage_tool_signature_cannot_select_actor_or_local_path():
    import inspect

    parameters = inspect.signature(team_knowledge_tools.knowledge_stage_session_attachment_tool).parameters

    assert not {"owner_type", "owner_id", "agent_id", "session_id", "actor_agent_id", "path", "local_file_paths"} & set(parameters)


def test_team_knowledge_tools_are_llm_facing_with_explicit_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Knowledge Tools Agent")
    tools = _llm_facing_knowledge_tools()
    allowed_names = [tool.name for tool in tools]
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"allowedTools": allowed_names},
    )

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-tools"):
        visible = agent_directory_service.filter_llm_tools_for_current_agent(tools)

    assert {tool.name for tool in tools} == _LLM_FACING_TOOL_NAMES
    assert [tool.name for tool in visible] == [tool.name for tool in tools]


def test_knowledge_proposal_tool_submits_source_and_pending_candidate(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    central_source = _promote_central_source(env, title="Tool submitted source")

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_proposal_tool(
                knowledge_base_id=_kb_ref(env),
                central_source_id=central_source["centralSourceId"],
                source_type="manual_user_entry",
                source_ref_json='{"note":"tool source"}',
                proposal_title="Tool submitted knowledge",
                proposal_content="Knowledge proposal tool submits candidates for review.",
                tags="tool,knowledge",
            )
        )

    assert result["ok"] is True
    assert result["proposal"]["status"] == "pending"
    items = team_knowledge_service.list_knowledge_items(_kb_ref(env), agent_id=env["member"]["agentId"])
    assert items["summary"]["itemCount"] == 0


def test_knowledge_ingestion_tool_submits_standard_package(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    central_source = _promote_central_source(
        env,
        source_type="external_search_refinement",
        source_ref={"url": "https://example.test", "query": "memory"},
        title="Tool ingestion source",
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_ingestion_tool(
                knowledge_base_id=_kb_ref(env),
                central_source_id=central_source["centralSourceId"],
                source_type="external_search_refinement",
                source_ref_json='{"url":"https://example.test","query":"memory"}',
                proposal_title="Tool ingestion package",
                excerpt="Search adapter output can be submitted as pending knowledge.",
                tags="ingestion,tool",
            )
        )

    assert result["ok"] is True
    assert result["package"]["proposal"]["status"] == "pending"
    assert result["package"]["sourceArtifact"]["sourceType"] == "external_search_refinement"


def test_knowledge_ingestion_tool_directly_ingests_reviewed_inbox_source(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "tool direct source"},
        original_content="Tool direct source content.",
        original_filename="tool-direct-source.txt",
        title="Tool direct source",
        actor_agent_id=env["member"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["lead"]["agentId"], session_id="session-knowledge-lead"):
        result = json.loads(
            team_knowledge_tools.knowledge_ingestion_tool(
                knowledge_base_id=_kb_ref(env),
                source_type="manual_user_entry",
                source_ref_json='{"note":"tool direct source"}',
                proposal_title="Tool direct source becomes memory",
                proposal_content="The ingestion tool can screen an inbox source and create a formal KnowledgeItem directly.",
                inbox_source_id=inbox_source["inboxSourceId"],
                owner_type="team",
                owner_id=env["team"]["teamId"],
                resolution_note="筛选通过，直接入库。",
                tags="direct-ingestion,tool",
            )
        )

    items = team_knowledge_service.list_knowledge_items(_kb_ref(env), agent_id=env["member"]["agentId"])

    assert result["ok"] is True
    assert result["status"] == "ingested"
    assert result["directIngestion"]["item"]["title"] == "Tool direct source becomes memory"
    assert result["workflowReconciliation"]["status"] == "not_applicable"
    assert result["workflowReconciliation"]["updated"] is False
    assert items["summary"]["itemCount"] == 1


def test_knowledge_ingestion_tool_uses_review_policy_for_inbox_direct_ingest(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "policy-gated-direct-ingest"},
        original_content="The source should remain pending when the runtime review policy excludes its base.",
        title="Policy-gated source",
        actor_agent_id=env["member"]["agentId"],
    )
    monkeypatch.setattr(
        team_knowledge_tools,
        "_current_runtime",
        lambda: {
            "agentId": env["lead"]["agentId"],
            "memoryPolicy": {
                "proposeKnowledgeBaseIds": [_kb_ref(env)],
                "reviewKnowledgeBaseIds": ["kb-other"],
            },
        },
    )

    result = json.loads(
        team_knowledge_tools.knowledge_ingestion_tool(
            knowledge_base_id=_kb_ref(env),
            source_type="manual_user_entry",
            source_ref_json='{"note":"policy-gated-direct-ingest"}',
            proposal_title="Policy-gated source",
            inbox_source_id=inbox_source["inboxSourceId"],
            owner_type="team",
            owner_id=env["team"]["teamId"],
            proposal_content="This must not become formal knowledge.",
        )
    )

    inbox = team_knowledge_service.list_owner_source_inbox(
        "team", env["team"]["teamId"], agent_id=env["lead"]["agentId"]
    )
    assert result["ok"] is False
    assert result["error"] == "knowledge_base_not_in_memory_policy"
    assert inbox["sources"][0]["status"] == "pending"


def test_knowledge_ingestion_tool_reports_partial_when_experiment_reconciliation_fails(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        env["team"]["teamId"],
        source_type="runtime_evidence_refinement",
        source_ref={
            "planId": "exp-plan-partial",
            "experimentResultPackId": "experiment-pack-partial",
        },
        original_content="Bounded experiment evidence.",
        original_filename="experiment-pack-partial.json",
        title="Experiment result source",
        actor_agent_id=env["member"]["agentId"],
    )
    from core.web.services import team_workflow_orchestration_service

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "reconcile_experiment_knowledge_ingestion",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("ledger unavailable")),
    )

    with agent_directory_service.active_agent_runtime(env["lead"]["agentId"], session_id="session-knowledge-lead"):
        result = json.loads(
            team_knowledge_tools.knowledge_ingestion_tool(
                knowledge_base_id=_kb_ref(env),
                source_type="runtime_evidence_refinement",
                source_ref_json='{"planId":"exp-plan-partial"}',
                proposal_title="Experiment result becomes memory",
                proposal_content="The reviewed experiment conclusion is still formal knowledge.",
                inbox_source_id=inbox_source["inboxSourceId"],
                owner_type="team",
                owner_id=env["team"]["teamId"],
                resolution_note="Knowledge accepted; ledger reconciliation is tested as unavailable.",
            )
        )

    items = team_knowledge_service.list_knowledge_items(_kb_ref(env), agent_id=env["member"]["agentId"])
    assert result["ok"] is True
    assert result["status"] == "ingested"
    assert result["workflowReconciliation"] == {
        "status": "failed",
        "updated": False,
        "reason": "experiment_workflow_reconciliation_failed",
        "errorType": "OSError",
    }
    assert items["summary"]["itemCount"] == 1


def test_knowledge_governance_tasks_tool_reads_open_queue(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Open governance task source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Open governance task",
        content="Governance task tool should see pending proposal.",
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(team_knowledge_tools.knowledge_governance_tasks_tool(status="open"))

    assert result["ok"] is True
    assert result["summary"]["proposalReviewCount"] == 1
    assert result["tasks"][0]["taskType"] == "proposal_review"


def test_knowledge_steward_recommendations_tool_reads_read_only_actions(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Steward tool source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Steward tool proposal",
        content="Steward recommendations should suggest review without applying.",
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(team_knowledge_tools.knowledge_steward_recommendations_tool(limit=4))

    assert result["ok"] is True
    assert result["operatingBoundary"]["recommendationsOnly"] is True
    assert result["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert any(item["targetId"] == proposal["proposalId"] for item in result["recommendations"])
    assert result["recommendations"][0]["recommendedAction"] == "review_proposal"


def test_knowledge_steward_workbench_tool_reads_grouped_workflow(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    source = _source_artifact(env, title="Tool workbench source")

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(team_knowledge_tools.knowledge_steward_workbench_tool(limit=4))

    assert result["ok"] is True
    assert result["operatingBoundary"]["recommendationsOnly"] is True
    assert result["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert any(stage["stageId"] == "source_to_proposal" for stage in result["stages"])
    assert any(action["targetId"] == source["sourceArtifactId"] for action in result["nextActions"])


def test_knowledge_operations_health_and_plan_tools_are_read_only(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    source = _source_artifact(env, title="Health tool source")

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        health = json.loads(team_knowledge_tools.knowledge_operations_health_tool())
        plan = json.loads(team_knowledge_tools.knowledge_governance_plan_tool(limit=3))

    assert health["ok"] is True
    assert health["summary"]["orphanSourceCount"] == 1
    assert source["sourceArtifactId"] in health["knowledgeBases"][0]["nextReviewTargetIds"]
    assert plan["ok"] is True
    assert plan["mode"] == "recommendations_only"
    assert plan["operatingBoundary"]["planOnly"] is True
    assert all(action["mutatesFormalKnowledge"] is False for action in plan["actions"])
    assert team_knowledge_service.list_knowledge_items(_kb_ref(env), agent_id=env["member"]["agentId"])["summary"]["itemCount"] == 0


def test_unified_memory_search_tool_reads_applied_items_only(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Applied tool source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Applied tool knowledge",
        content="Formal team knowledge should be readable by the query tool.",
        tags=["query-tool"],
    )
    team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="formal team",
                query_mode="hybrid",
                knowledge_base_id=_kb_ref(env),
                limit=5,
            )
        )

    assert result["ok"] is True
    assert result["summary"]["resultCount"] == 1
    assert result["results"][0]["title"] == "Applied tool knowledge"
    assert result["results"][0]["knowledgeBaseId"] == env["base"]["knowledgeBaseId"]


def test_unified_memory_search_tool_returns_standard_results(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Unified search source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Unified search knowledge",
        content="Unified search lets agents query formal knowledge with one stable tool.",
        tags=["unified-search"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="stable tool",
                query_mode="hybrid",
                knowledge_base_id=_kb_ref(env),
                tags="unified-search",
                limit=5,
            )
        )

    assert result["ok"] is True
    assert result["request"]["effectiveQueryMode"] == "hybrid"
    assert result["request"]["backend"] == "local_hybrid"
    assert result["summary"]["resultCount"] == 1
    assert result["results"][0]["resultType"] == "knowledge_item"
    assert result["results"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]
    assert result["results"][0]["searchBackend"] == "local_hybrid"
    assert result["retrievalPolicy"]["mutatesFormalKnowledge"] is False


def test_unified_memory_search_tool_supports_bm25_mode(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    sparse_proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Sparse BM25 tool source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Sparse benchmark note",
        content="Benchmark memory retrieval appears once before unrelated operational text.",
        tags=["bm25-tool"],
    )
    dense_proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Dense BM25 tool source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Dense benchmark memory retrieval",
        content="Benchmark memory retrieval repeats benchmark memory retrieval evidence for BM25 ranking.",
        tags=["bm25-tool"],
    )
    sparse_item = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        sparse_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]
    dense_item = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        dense_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="benchmark memory retrieval",
                query_mode="bm25",
                knowledge_base_id=_kb_ref(env),
                limit=2,
            )
        )

    assert result["ok"] is True
    assert result["request"]["effectiveQueryMode"] == "bm25"
    assert result["request"]["backend"] == "local_bm25"
    assert [item["knowledgeItemId"] for item in result["results"]] == [
        dense_item["knowledgeItemId"],
        sparse_item["knowledgeItemId"],
    ]
    assert result["results"][0]["score"] > result["results"][1]["score"] > 0
    assert result["results"][0]["matchReason"] == "bm25"


def test_unified_memory_search_tool_supports_regex_and_rag_modes(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Unified regex source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Unified regex knowledge",
        content="Regex mode and RAG mode both return the unified result protocol.",
        tags=["unified-regex"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        regex_result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="Regex mode",
                query_mode="regex",
                knowledge_base_id=_kb_ref(env),
            )
        )
        rag_result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="rag mode unified protocol",
                query_mode="rag",
                knowledge_base_id=_kb_ref(env),
                limit=3,
            )
        )

    assert regex_result["ok"] is True
    assert regex_result["request"]["backend"] == "local_regex"
    assert regex_result["results"][0]["matchReason"] == "regex_match"
    assert rag_result["ok"] is True
    assert rag_result["request"]["backend"] == "local_rag"
    assert rag_result["summary"]["citationCount"] == 1
    assert rag_result["results"][0]["resultType"] == "rag_context"
    assert rag_result["results"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]


def test_unified_memory_search_tool_honors_memory_policy_base_ids(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    other_base = team_knowledge_service.create_knowledge_base(env["team"]["teamId"], name="Other Unified KB", actor_agent_id=env["lead"]["agentId"])

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="",
                query_mode="metadata",
                knowledge_base_id=other_base["scopedKnowledgeBaseId"],
            )
        )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["error"] == "knowledge_base_not_in_memory_policy"


def test_unified_memory_search_tool_limits_unscoped_search_to_memory_policy(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    other_base = team_knowledge_service.create_knowledge_base(
        env["team"]["teamId"],
        name="Blocked Unified KB",
        actor_agent_id=env["lead"]["agentId"],
    )
    allowed_proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Allowed unified source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Allowed unified knowledge",
        content="Unified global search may read this memory-policy-allowed knowledge.",
        tags=["unified-policy"],
    )
    blocked_proposal = team_knowledge_service.create_refinement_proposal(
        other_base["scopedKnowledgeBaseId"],
        source_artifact_ids=_source_ids(
            env,
            title="Blocked unified source",
            knowledge_base_id=other_base["scopedKnowledgeBaseId"],
        ),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Blocked unified knowledge",
        content="Unified global search must not return this memory-policy-blocked knowledge.",
        tags=["unified-policy"],
    )
    allowed_item = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        allowed_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]
    blocked_item = team_knowledge_service.review_refinement_proposal(
        other_base["scopedKnowledgeBaseId"],
        blocked_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="Unified global search",
                query_mode="hybrid",
                limit=10,
            )
        )

    result_item_ids = {item["knowledgeItemId"] for item in result["results"]}
    assert result["ok"] is True
    assert allowed_item["knowledgeItemId"] in result_item_ids
    assert blocked_item["knowledgeItemId"] not in result_item_ids
    assert {item["knowledgeBaseId"] for item in result["results"]} == {env["base"]["knowledgeBaseId"]}


def test_unified_memory_search_tool_honors_requested_base_memory_policy_ids(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    other_base = team_knowledge_service.create_knowledge_base(env["team"]["teamId"], name="Other KB", actor_agent_id=env["lead"]["agentId"])

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="",
                query_mode="metadata",
                knowledge_base_id=other_base["scopedKnowledgeBaseId"],
            )
        )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["error"] == "knowledge_base_not_in_memory_policy"


def test_unified_memory_search_tool_honors_owner_scoped_memory_policy_ids(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    second_lead = agent_directory_service.create_agent_instance(display_name="Second Knowledge Lead")
    second_team = team_service.create_team(
        name="Second Tool Knowledge Team",
        members=[{"agentId": second_lead["agentId"], "role": "lead"}],
    )
    second_base = team_knowledge_service.create_knowledge_base(
        second_team["teamId"],
        name="Tool KB",
        actor_agent_id=second_lead["agentId"],
        acl={"grants": {"read": [env["member"]["agentId"]]}},
    )
    agent_directory_service.update_agent_instance(
        env["member"]["agentId"],
        tool_policy={"allowedTools": ["unified_memory_search_tool"]},
        memory_policy={"readKnowledgeBaseIds": [env["base"]["scopedKnowledgeBaseId"]]},
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        allowed = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="",
                query_mode="metadata",
                knowledge_base_id=env["base"]["scopedKnowledgeBaseId"],
            )
        )
        blocked_scoped = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="",
                query_mode="metadata",
                knowledge_base_id=second_base["scopedKnowledgeBaseId"],
            )
        )
        blocked_raw = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="",
                query_mode="metadata",
                knowledge_base_id=env["base"]["knowledgeBaseId"],
            )
        )

    assert env["base"]["knowledgeBaseId"] == second_base["knowledgeBaseId"]
    assert allowed["ok"] is True
    assert blocked_scoped["ok"] is False
    assert blocked_scoped["error"] == "knowledge_base_not_in_memory_policy"
    assert blocked_raw["ok"] is False
    assert blocked_raw["error"] == "knowledge_base_not_in_memory_policy"


def test_unified_memory_search_tool_returns_rag_results_with_citations(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    agent_directory_service.update_agent_instance(
        env["member"]["agentId"],
        tool_policy={"allowedTools": ["unified_memory_search_tool"]},
        memory_policy={"readKnowledgeBaseIds": [_kb_ref(env)]},
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="RAG tool source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="RAG tool knowledge",
        content="RAG tool retrieval should return cited context candidates.",
        tags=["rag-tool"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="rag tool context",
                query_mode="rag",
                knowledge_base_id=_kb_ref(env),
                limit=3,
                max_context_chars=240,
            )
        )

    assert result["ok"] is True
    assert result["request"]["backend"] == "local_rag"
    assert result["summary"]["contextCount"] == 1
    assert result["summary"]["citationCount"] == 1
    assert result["results"][0]["resultType"] == "rag_context"
    assert result["results"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]
    assert result["citations"][0]["contextId"] == result["results"][0]["resultId"]
    assert result["retrievalPolicy"]["injectsPromptByDefault"] is False


def test_read_knowledge_item_tool_reads_bounded_pages_and_only_linked_sources(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    agent_id = env["member"]["agentId"]
    base_id = _kb_ref(env)
    content = "0123456789" * 530
    item = _create_approved_owner_knowledge_item(
        owner_type="team",
        owner_id=env["team"]["teamId"],
        knowledge_base_id=base_id,
        actor_agent_id=agent_id,
        reviewer_agent_id=env["lead"]["agentId"],
        title="Paged knowledge item",
        content=content,
    )
    unrelated_source = _source_artifact(env, title="Unrelated source")
    agent_directory_service.update_agent_instance(
        agent_id,
        tool_policy={"allowedTools": ["read_knowledge_item_tool"]},
        memory_policy={"readKnowledgeBaseIds": [base_id]},
    )

    with agent_directory_service.active_agent_runtime(agent_id, session_id="session-knowledge-read"):
        first = json.loads(
            team_knowledge_tools.read_knowledge_item_tool(
                knowledge_base_id=base_id,
                knowledge_item_id=item["knowledgeItemId"],
                offset=0,
                max_chars=1300,
            )
        )
        second = json.loads(
            team_knowledge_tools.read_knowledge_item_tool(
                knowledge_base_id=base_id,
                knowledge_item_id=item["knowledgeItemId"],
                offset=first["nextOffset"],
                max_chars=1300,
            )
        )
        unrelated = json.loads(
            team_knowledge_tools.read_knowledge_item_tool(
                knowledge_base_id=base_id,
                knowledge_item_id=item["knowledgeItemId"],
                source_artifact_id=unrelated_source["sourceArtifactId"],
            )
        )

    assert first["ok"] is True
    assert first["content"] == content[:1300]
    assert first["contentLength"] == len(content)
    assert first["hasMore"] is True
    assert first["nextOffset"] == 1300
    assert first["untrusted"] is True
    assert first["embeddedInstructionsAreData"] is True
    assert [citation["sourceArtifactId"] for citation in first["citations"]] == item["sourceArtifactIds"]
    assert all("centralPath" not in citation for citation in first["citations"])
    assert second["content"] == content[1300:2600]
    assert second["offset"] == 1300
    assert unrelated["ok"] is False
    assert unrelated["error"] == "source_not_related_to_item"


def test_read_knowledge_item_tool_honors_current_agent_acl_and_memory_policy(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    base_id = _kb_ref(env)
    item = _create_approved_owner_knowledge_item(
        owner_type="team",
        owner_id=env["team"]["teamId"],
        knowledge_base_id=base_id,
        actor_agent_id=env["member"]["agentId"],
        reviewer_agent_id=env["lead"]["agentId"],
        title="Restricted knowledge item",
        content="This item is readable only through the current Agent's ACL and MemoryPolicy.",
    )
    outsider = agent_directory_service.create_agent_instance(display_name="Knowledge Reader Outsider")
    agent_directory_service.update_agent_instance(
        outsider["agentId"],
        tool_policy={"allowedTools": ["read_knowledge_item_tool"]},
        memory_policy={"readKnowledgeBaseIds": [base_id]},
    )
    agent_directory_service.update_agent_instance(
        env["member"]["agentId"],
        tool_policy={"allowedTools": ["read_knowledge_item_tool"]},
        memory_policy={"readKnowledgeBaseIds": ["team:another-team:another-kb"]},
    )

    with agent_directory_service.active_agent_runtime(outsider["agentId"], session_id="session-outsider-read"):
        acl_denied = json.loads(
            team_knowledge_tools.read_knowledge_item_tool(
                knowledge_base_id=base_id,
                knowledge_item_id=item["knowledgeItemId"],
            )
        )
    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-policy-read"):
        policy_denied = json.loads(
            team_knowledge_tools.read_knowledge_item_tool(
                knowledge_base_id=base_id,
                knowledge_item_id=item["knowledgeItemId"],
            )
        )

    assert acl_denied["ok"] is False
    assert acl_denied["status"] == "blocked"
    assert acl_denied["error"] == "knowledge_access_denied"
    assert policy_denied["ok"] is False
    assert policy_denied["error"] == "knowledge_base_not_in_memory_policy"


def test_read_knowledge_item_tool_is_exposed_only_by_knowledge_steward_profile():
    steward = agent_role_tool_profile_service.get_role_tool_profile("knowledge_steward")
    ordinary = agent_role_tool_profile_service.get_role_tool_profile("ai_search_scope_lead")

    assert "read_knowledge_item_tool" in steward["allowedTools"]
    assert "read_knowledge_item_tool" in steward["preferredTools"]
    assert "read_knowledge_item_tool" not in ordinary["allowedTools"]


def test_unified_memory_search_tool_rag_mode_honors_memory_policy_base_ids(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    agent_directory_service.update_agent_instance(
        env["member"]["agentId"],
        tool_policy={"allowedTools": ["unified_memory_search_tool"]},
        memory_policy={"readKnowledgeBaseIds": [_kb_ref(env)]},
    )
    other_base = team_knowledge_service.create_knowledge_base(env["team"]["teamId"], name="Other RAG KB", actor_agent_id=env["lead"]["agentId"])

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="",
                query_mode="rag",
                knowledge_base_id=other_base["scopedKnowledgeBaseId"],
            )
        )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["error"] == "knowledge_base_not_in_memory_policy"


def test_unified_memory_search_tool_can_include_user_content(tmp_path, monkeypatch):
    from core.web.services import user_content_markdown_service

    monkeypatch.setattr(user_content_markdown_service, "PROJECT_ROOT", tmp_path / "project")
    monkeypatch.setattr(team_knowledge_tools, "_current_runtime", lambda: {"agentId": "agent-1", "memoryPolicy": {}})
    source = tmp_path / "source"
    source.mkdir()
    (source / "Guide.md").write_text("# Guide\nagent-readable user note", encoding="utf-8")
    imported = user_content_markdown_service.import_markdown_space(str(source), space_name="User Notes")

    result = team_knowledge_tools.unified_memory_search_tool(
        query="agent-readable",
        include_user_content=True,
        user_content_space_ids=imported["space"]["spaceId"],
    )

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["summary"]["userContentResultCount"] == 1


def test_unified_memory_search_tool_blocks_user_content_space_outside_memory_policy(tmp_path, monkeypatch):
    from core.web.services import user_content_markdown_service

    monkeypatch.setattr(user_content_markdown_service, "PROJECT_ROOT", tmp_path / "project")
    source = tmp_path / "source"
    source.mkdir()
    (source / "Guide.md").write_text("# Guide\npolicy blocked note", encoding="utf-8")
    imported = user_content_markdown_service.import_markdown_space(str(source), space_name="User Notes")
    monkeypatch.setattr(
        team_knowledge_tools,
        "_current_runtime",
        lambda: {
            "agentId": "agent-1",
            "memoryPolicy": {"readUserContentSpaceIds": ["another-space"]},
        },
    )

    result = team_knowledge_tools.unified_memory_search_tool(
        query="policy blocked",
        include_user_content=True,
        user_content_space_ids=imported["space"]["spaceId"],
    )

    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["error"] == "user_content_space_not_in_memory_policy"


def test_knowledge_rating_suggestion_tool_submits_pending_suggestion_only(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    agent_directory_service.update_agent_instance(
        env["lead"]["agentId"],
        tool_policy={"allowedTools": ["unified_memory_search_tool", "knowledge_proposal_tool", "knowledge_rating_suggestion_tool"]},
        memory_policy={"rateKnowledgeBaseIds": [_kb_ref(env)]},
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Tool rating source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Tool rating target",
        content="Rating suggestion tools must not directly update formal knowledge.",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["lead"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_rating_suggestion_tool(
                knowledge_base_id=_kb_ref(env),
                target_type="knowledge_item",
                knowledge_item_id=reviewed["item"]["knowledgeItemId"],
                importance_level="high",
                confidence=0.88,
                stability="stable",
                review_priority="elevated",
                marking_reason="Useful operational knowledge.",
            )
        )

    item = team_knowledge_service.list_knowledge_items(_kb_ref(env), agent_id=env["member"]["agentId"])["items"][0]
    assert result["ok"] is True
    assert result["suggestion"]["status"] == "pending"
    assert item["importanceLevel"] == "medium"


def test_scoped_memory_policy_search_result_can_be_read_back(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    agent_id = env["member"]["agentId"]
    scoped_base_id = _kb_ref(env)
    query = "scoped-memory-readback-amber"
    item = _create_approved_owner_knowledge_item(
        owner_type="team",
        owner_id=env["team"]["teamId"],
        knowledge_base_id=scoped_base_id,
        actor_agent_id=agent_id,
        reviewer_agent_id=env["lead"]["agentId"],
        title="Scoped readback proof",
        content=f"{query}: this exact approved text must be readable after search.",
    )
    agent_directory_service.update_agent_instance(
        agent_id,
        tool_policy={"allowedTools": ["unified_memory_search_tool", "read_knowledge_item_tool"]},
        memory_policy={"readKnowledgeBaseIds": [scoped_base_id]},
    )

    with agent_directory_service.active_agent_runtime(agent_id, session_id="session-scoped-search-read"):
        search = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query=query,
                query_mode="bm25",
                knowledge_base_id=scoped_base_id,
                limit=3,
            )
        )
        result = next(row for row in search["results"] if row["knowledgeItemId"] == item["knowledgeItemId"])
        readback = json.loads(
            team_knowledge_tools.read_knowledge_item_tool(
                knowledge_base_id=result["scopedKnowledgeBaseId"],
                knowledge_item_id=result["knowledgeItemId"],
                max_chars=4000,
            )
        )

    assert search["ok"] is True
    assert result["scopedKnowledgeBaseId"] == scoped_base_id
    assert search["citations"][0]["scopedKnowledgeBaseId"] == scoped_base_id
    assert readback["ok"] is True
    assert readback["scopedKnowledgeBaseId"] == result["scopedKnowledgeBaseId"]
    assert readback["knowledgeItemId"] == item["knowledgeItemId"]
    assert readback["content"] == item["content"]


def test_global_knowledge_steward_cannot_read_another_agents_private_item(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    other = agent_directory_service.create_agent_instance(display_name="Private Knowledge Owner")
    private_base = team_knowledge_service.create_agent_knowledge_base(
        other["agentId"],
        name="Private Read Isolation",
        actor_agent_id=other["agentId"],
    )
    item = _create_approved_owner_knowledge_item(
        owner_type="agent",
        owner_id=other["agentId"],
        knowledge_base_id=private_base["knowledgeBaseId"],
        actor_agent_id=other["agentId"],
        reviewer_agent_id=other["agentId"],
        title="Another Agent private item",
        content="This private body must never be returned to a global steward through item readback.",
    )
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    monkeypatch.setattr(
        team_knowledge_tools,
        "_current_runtime",
        lambda: {
            "agentId": steward_id,
            "memoryPolicy": {
                "enabled": True,
                "readKnowledgeBaseIds": [private_base["scopedKnowledgeBaseId"]],
            },
        },
    )
    monkeypatch.setattr(team_knowledge_tools, "_record_event", lambda *args, **kwargs: None)

    payload = json.loads(
        team_knowledge_tools.read_knowledge_item_tool(
            knowledge_base_id=private_base["scopedKnowledgeBaseId"],
            knowledge_item_id=item["knowledgeItemId"],
        )
    )

    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["error"] == "knowledge_access_denied"
    assert item["content"] not in json.dumps(payload)


def test_agent_can_read_own_private_search_result_but_disabled_memory_blocks_readback(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    agent_id = env["member"]["agentId"]
    private_base = team_knowledge_service.create_agent_knowledge_base(
        agent_id,
        name="Current Agent Readback",
        actor_agent_id=agent_id,
    )
    query = "own-private-roundtrip-celadon"
    item = _create_approved_owner_knowledge_item(
        owner_type="agent",
        owner_id=agent_id,
        knowledge_base_id=private_base["knowledgeBaseId"],
        actor_agent_id=agent_id,
        reviewer_agent_id=agent_id,
        title="Own private readback",
        content=f"{query}: this private item belongs to the current Agent.",
    )
    scoped_base_id = private_base["scopedKnowledgeBaseId"]
    agent_directory_service.update_agent_instance(
        agent_id,
        tool_policy={"allowedTools": ["search_agent_private_memory_tool", "read_knowledge_item_tool"]},
        memory_policy={"enabled": True, "readKnowledgeBaseIds": [scoped_base_id]},
    )

    with agent_directory_service.active_agent_runtime(agent_id, session_id="session-own-private-read"):
        search = json.loads(
            team_knowledge_tools.search_agent_private_memory_tool(
                query=query,
                query_mode="bm25",
                limit=3,
            )
        )
        result = next(row for row in search["results"] if row["knowledgeItemId"] == item["knowledgeItemId"])
        readback = json.loads(
            team_knowledge_tools.read_knowledge_item_tool(
                knowledge_base_id=result["scopedKnowledgeBaseId"],
                knowledge_item_id=result["knowledgeItemId"],
            )
        )

    assert search["ok"] is True
    assert result["scopedKnowledgeBaseId"] == scoped_base_id
    assert readback["ok"] is True
    assert readback["ownerType"] == "agent"
    assert readback["ownerId"] == agent_id
    assert readback["content"] == item["content"]

    agent_directory_service.update_agent_instance(
        agent_id,
        memory_policy={"enabled": False, "readKnowledgeBaseIds": [scoped_base_id]},
    )
    with agent_directory_service.active_agent_runtime(agent_id, session_id="session-disabled-private-read"):
        disabled_read = json.loads(
            team_knowledge_tools.read_knowledge_item_tool(
                knowledge_base_id=scoped_base_id,
                knowledge_item_id=item["knowledgeItemId"],
            )
        )

    assert disabled_read["ok"] is False
    assert disabled_read["status"] == "blocked"
    assert disabled_read["error"] == "personal_memory_disabled"
    assert item["content"] not in json.dumps(disabled_read)
