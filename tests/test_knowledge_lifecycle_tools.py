"""Agent tool contracts for reading knowledge history and governing sources."""

from __future__ import annotations

import json

import pytest

from core.web.services import (
    agent_directory_service,
    agent_role_tool_profile_service,
    chat_room_service,
    team_knowledge_service,
    team_service,
)
from core.web.services.team_knowledge import governance, lifecycle
from tools import team_knowledge_tools
from tools.Key_Tools import create_llm_facing_tools


@pytest.fixture(autouse=True)
def _isolate_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))


def _environment(tmp_path, monkeypatch):
    for service in (agent_directory_service, chat_room_service, team_service, team_knowledge_service):
        monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    lead = agent_directory_service.create_agent_instance(display_name="Lifecycle Tool Lead")
    member = agent_directory_service.create_agent_instance(display_name="Lifecycle Tool Member")
    outsider = agent_directory_service.create_agent_instance(display_name="Lifecycle Tool Outsider")
    team = team_service.create_team(
        name="Lifecycle Tool Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    base = team_knowledge_service.create_knowledge_base(
        team["teamId"], name="Lifecycle Tool KB", actor_agent_id=lead["agentId"],
    )
    base_ref = str(base.get("scopedKnowledgeBaseId") or base["knowledgeBaseId"])
    agent_directory_service.update_agent_instance(
        lead["agentId"],
        tool_policy={"allowedTools": ["knowledge_source_lifecycle_tool", "read_knowledge_item_tool"]},
        memory_policy={"readKnowledgeBaseIds": [base_ref], "reviewKnowledgeBaseIds": [base_ref]},
    )
    agent_directory_service.update_agent_instance(
        member["agentId"],
        tool_policy={"allowedTools": ["read_knowledge_item_tool", "knowledge_proposal_tool"]},
        memory_policy={"readKnowledgeBaseIds": [base_ref], "proposeKnowledgeBaseIds": [base_ref]},
    )
    return {"lead": lead, "member": member, "outsider": outsider, "team": team, "base": base, "baseRef": base_ref}


def _source_artifact(env, *, title="Lifecycle tool source"):
    inbox = team_knowledge_service.collect_source_to_inbox(
        "team", env["team"]["teamId"], source_type="manual_user_entry", source_ref={"note": title},
        original_content="Immutable tool source body.", original_filename="tool-source.txt",
        title=title, actor_agent_id=env["member"]["agentId"],
    )
    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team", env["team"]["teamId"], inbox["inboxSourceId"], decision="accepted",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )
    return team_knowledge_service.create_source_artifact_from_central_source(
        env["baseRef"], reviewed["centralSource"]["centralSourceId"],
        actor_agent_id=env["member"]["agentId"], title=title,
    )


def _approved_item(env, source, content):
    proposal = team_knowledge_service.create_refinement_proposal(
        env["baseRef"], source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=env["member"]["agentId"], title="Tool history item", content=content,
    )
    return team_knowledge_service.review_refinement_proposal(
        env["baseRef"], proposal["proposalId"], status="applied",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]


def test_knowledge_source_lifecycle_tool_binds_runtime_actor_and_enforces_review_policy(tmp_path, monkeypatch):
    env = _environment(tmp_path, monkeypatch)
    source = _source_artifact(env)
    with agent_directory_service.active_agent_runtime(env["lead"]["agentId"], session_id="session-lifecycle-lead"):
        updated = json.loads(team_knowledge_tools.knowledge_source_lifecycle_tool(
            knowledge_base_id=env["baseRef"], source_artifact_id=source["sourceArtifactId"],
            status="withdrawn", reason="Source evidence is outdated",
        ))

    assert updated["ok"] is True
    assert updated["agentId"] == env["lead"]["agentId"]
    assert updated["sourceArtifact"]["status"] == "withdrawn"
    assert updated["sourceArtifact"]["lifecycleUpdatedByAgentId"] == env["lead"]["agentId"]

    member_source = _source_artifact(env, title="Member cannot withdraw")
    # Prove the explicit review-policy gate independently of the database's default policy.
    current_runtime = team_knowledge_tools._current_runtime
    monkeypatch.setattr(team_knowledge_tools, "_current_runtime", lambda: {
        "agentId": env["member"]["agentId"],
        "memoryPolicy": {
            "readKnowledgeBaseIds": [env["baseRef"]], "proposeKnowledgeBaseIds": [env["baseRef"]],
            "reviewKnowledgeBaseIds": ["team:other-team:other-kb"],
        },
    })
    denied = json.loads(team_knowledge_tools.knowledge_source_lifecycle_tool(
        knowledge_base_id=env["baseRef"], source_artifact_id=member_source["sourceArtifactId"],
        status="withdrawn", reason="Attempt without review policy",
    ))
    untouched = team_knowledge_service._find_by_id(
        team_knowledge_service._read_jsonl(
            team_knowledge_service._source_artifacts_path_for_owner(
                team_knowledge_service._require_base_with_owner(env["baseRef"])[0]
            )
        ),
        "sourceArtifactId", member_source["sourceArtifactId"],
    )
    assert denied["ok"] is False
    assert denied["status"] == "blocked"
    assert denied["error"] == "knowledge_base_not_in_memory_policy"
    assert untouched.get("status", "active") == "active"

    monkeypatch.setattr(team_knowledge_tools, "_current_runtime", current_runtime)
    agent_directory_service.update_agent_instance(
        env["member"]["agentId"], memory_policy={"reviewKnowledgeBaseIds": [env["baseRef"]]},
    )
    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-lifecycle-member-acl"):
        acl_denied = json.loads(team_knowledge_tools.knowledge_source_lifecycle_tool(
            knowledge_base_id=env["baseRef"], source_artifact_id=member_source["sourceArtifactId"],
            status="withdrawn", reason="Policy allowed but ACL does not",
        ))
    assert acl_denied["ok"] is False
    assert acl_denied["status"] == "blocked"
    assert acl_denied["error"] == "knowledge_access_denied"


def test_read_knowledge_item_tool_returns_version_paged_history_without_bodies(tmp_path, monkeypatch):
    env = _environment(tmp_path, monkeypatch)
    source = _source_artifact(env)
    original = _approved_item(env, source, "Original tool-visible policy.")
    revision = governance.create_refinement_proposal(
        env["baseRef"], source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=env["member"]["agentId"], title=original["title"],
        content="Revised tool-visible policy.", supersedes_knowledge_item_id=original["knowledgeItemId"],
        expected_content_sha256=lifecycle.content_sha256(original), revision_reason="Verified update",
    )
    revised = governance.review_refinement_proposal(
        env["baseRef"], revision["proposalId"], status="applied",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-history-read"):
        history = json.loads(team_knowledge_tools.read_knowledge_item_tool(
            knowledge_base_id=env["baseRef"], knowledge_item_id=revised["knowledgeItemId"],
            offset=1, max_chars=1, read_mode="history",
        ))

    assert history["ok"] is True
    assert history["agentId"] == env["member"]["agentId"]
    assert history["readMode"] == "history"
    assert history["offsetUnit"] == "versions"
    assert history["versionCount"] == 2
    assert [row["revision"] for row in history["versions"]] == [1]
    assert history["versions"][0]["knowledgeItemId"] == original["knowledgeItemId"]
    assert "content" not in history["versions"][0]


def test_proposal_tool_forwards_revision_guard_fields_to_service_facade(monkeypatch):
    captured = {}

    class FakeKnowledgeService:
        @staticmethod
        def create_source_artifact(*args, **kwargs):
            return {"sourceArtifactId": "source-1", "sourceType": "manual_user_entry"}

        @staticmethod
        def create_refinement_proposal(*args, **kwargs):
            captured.update(kwargs)
            return {"proposalId": "proposal-1", "status": "pending"}

    monkeypatch.setattr(team_knowledge_tools, "_current_runtime", lambda: {
        "agentId": "agent-author", "memoryPolicy": {"proposeKnowledgeBaseIds": ["team:team-1:kb-1"]},
    })
    monkeypatch.setattr("core.web.services.team_knowledge_service.create_source_artifact", FakeKnowledgeService.create_source_artifact)
    monkeypatch.setattr("core.web.services.team_knowledge_service.create_refinement_proposal", FakeKnowledgeService.create_refinement_proposal)

    result = json.loads(team_knowledge_tools.knowledge_proposal_tool(
        knowledge_base_id="team:team-1:kb-1", source_type="manual_user_entry", source_ref_json="{}",
        proposal_title="Revision", proposal_content="Corrected text", central_source_id="central-1",
        supersedes_knowledge_item_id="item-1", expected_content_sha256="a" * 64,
        revision_reason="The source was corrected",
    ))

    assert result["ok"] is True
    assert captured["supersedes_knowledge_item_id"] == "item-1"
    assert captured["expected_content_sha256"] == "a" * 64
    assert captured["revision_reason"] == "The source was corrected"


def test_native_knowledge_proposal_tool_accepts_and_forwards_revision_fields(monkeypatch):
    captured = {}

    def fake_proposal_impl(**kwargs):
        captured.update(kwargs)
        return json.dumps({"ok": True})

    monkeypatch.setattr("tools.Key_Tools._knowledge_proposal_impl", fake_proposal_impl)
    tool = next(tool for tool in create_llm_facing_tools() if tool.name == "knowledge_proposal_tool")
    result = tool.invoke({
        "knowledge_base_id": "team:team-1:kb-1", "source_type": "manual_user_entry",
        "source_ref_json": "{}", "proposal_title": "Revision", "proposal_content": "Corrected text",
        "supersedes_knowledge_item_id": "item-1", "expected_content_sha256": "b" * 64,
        "revision_reason": "Source updated",
    })

    assert json.loads(result)["ok"] is True
    assert captured["supersedes_knowledge_item_id"] == "item-1"
    assert captured["expected_content_sha256"] == "b" * 64
    assert captured["revision_reason"] == "Source updated"


def test_knowledge_index_build_tool_binds_runtime_reviewer_and_forwards_prepare_flag(tmp_path, monkeypatch):
    env = _environment(tmp_path, monkeypatch)
    observed = []
    monkeypatch.setattr(team_knowledge_tools, "_current_runtime", lambda: {
        "agentId": env["lead"]["agentId"],
        "memoryPolicy": {"reviewKnowledgeBaseIds": [env["baseRef"]]},
    })
    monkeypatch.setattr(
        team_knowledge_service, "_require_base_with_owner",
        lambda _knowledge_base_id: ({"ownerType": "team", "ownerId": env["team"]["teamId"]}, env["base"]),
    )

    def build(knowledge_base_id, *, agent_id, prepare_model=False):
        observed.append((knowledge_base_id, agent_id, prepare_model))
        return {"status": "ready", "knowledgeBaseId": knowledge_base_id}

    monkeypatch.setattr("core.web.services.team_knowledge.semantic.build_knowledge_index", build)
    result = json.loads(team_knowledge_tools.knowledge_index_build_tool(env["baseRef"], prepare_model=True))

    assert result["ok"] is True
    assert result["agentId"] == env["lead"]["agentId"]
    assert observed == [(env["baseRef"], env["lead"]["agentId"], True)]


def test_knowledge_index_build_tool_blocks_policy_mismatch_and_disabled_private_memory(monkeypatch):
    build_calls = []

    def unexpected_build(*args, **kwargs):
        build_calls.append((args, kwargs))
        return {"status": "ready"}

    monkeypatch.setattr("core.web.services.team_knowledge.semantic.build_knowledge_index", unexpected_build)
    monkeypatch.setattr(team_knowledge_tools, "_current_runtime", lambda: {
        "agentId": "agent-reviewer", "memoryPolicy": {"reviewKnowledgeBaseIds": ["team:other:kb"]},
    })
    policy_denied = json.loads(team_knowledge_tools.knowledge_index_build_tool("team:team-1:kb-1"))
    assert policy_denied["status"] == "blocked"
    assert policy_denied["error"] == "knowledge_base_not_in_memory_policy"

    monkeypatch.setattr(team_knowledge_tools, "_current_runtime", lambda: {
        "agentId": "agent-private-owner",
        "memoryPolicy": {"enabled": False, "reviewKnowledgeBaseIds": ["agent:agent-private-owner:kb-private"]},
    })
    monkeypatch.setattr(
        team_knowledge_service, "_require_base_with_owner",
        lambda _knowledge_base_id: ({"ownerType": "agent", "ownerId": "agent-private-owner"}, {}),
    )
    private_denied = json.loads(
        team_knowledge_tools.knowledge_index_build_tool("agent:agent-private-owner:kb-private")
    )

    assert private_denied["status"] == "blocked"
    assert private_denied["error"] == "private_memory_disabled"
    assert build_calls == []


def test_native_knowledge_index_build_tool_defaults_and_forwards_prepare_model(monkeypatch):
    observed = []

    def fake_index_impl(*, knowledge_base_id, prepare_model=False):
        observed.append((knowledge_base_id, prepare_model))
        return json.dumps({"ok": True, "status": "ready"})

    monkeypatch.setattr("tools.Key_Tools._knowledge_index_build_impl", fake_index_impl)
    tool = next(tool for tool in create_llm_facing_tools() if tool.name == "knowledge_index_build_tool")
    default_result = tool.invoke({"knowledge_base_id": "team:team-1:kb-1"})
    explicit_result = tool.invoke({"knowledge_base_id": "team:team-1:kb-1", "prepare_model": True})

    assert json.loads(default_result)["ok"] is True
    assert json.loads(explicit_result)["ok"] is True
    assert observed == [("team:team-1:kb-1", False), ("team:team-1:kb-1", True)]
