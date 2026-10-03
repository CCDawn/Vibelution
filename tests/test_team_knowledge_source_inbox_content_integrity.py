from __future__ import annotations

import hashlib

import pytest

from core.infrastructure import developer_sandbox
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    team_knowledge_service,
    team_service,
)
from core.web.services.knowledge_read_service import read_knowledge_item


@pytest.fixture(autouse=True)
def isolate_developer_sandbox_config(tmp_path, monkeypatch):
    config_path = tmp_path / "developer-mode-off.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "developer-mode-project"
    project_root.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)


@pytest.fixture
def knowledge_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    lead = agent_directory_service.create_agent_instance(
        display_name="Knowledge Lead",
        direct_session_id="session-knowledge-lead",
    )
    member = agent_directory_service.create_agent_instance(
        display_name="Knowledge Member",
        direct_session_id="session-knowledge-member",
    )
    team = team_service.create_team(
        name="Knowledge Integrity Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Content Integrity",
        actor_agent_id=lead["agentId"],
    )
    return {"team": team, "base": base, "lead": lead, "member": member}


def _long_body(label: str) -> tuple[str, str]:
    tail_marker = f"MEMORY-PERSIST-{label}-TAIL-8E613A"
    lines = [
        f"{label} verified knowledge line {index:03d}: preserve this reviewed detail."
        for index in range(1, 242)
    ]
    lines.append(f"Full body tail evidence marker: {tail_marker}.")
    content = "\n".join(lines)
    assert len(lines) > 120
    assert len(content) > 4_000
    assert len(content) <= 40_000
    return content, tail_marker


def _accept_source(knowledge_env, *, label: str) -> dict:
    team_id = knowledge_env["team"]["teamId"]
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        team_id,
        source_type="manual_user_entry",
        source_ref={"note": f"Complete source for {label}"},
        original_content=f"Captured source material for {label}.",
        original_filename=f"{label}.txt",
        title=f"Source for {label}",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )
    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        team_id,
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    return reviewed["centralSource"]


def _assert_body_survives_search_and_paged_read(
    knowledge_env,
    *,
    item: dict,
    content: str,
    tail_marker: str,
) -> None:
    assert item["content"] == content
    expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert hashlib.sha256(item["content"].encode("utf-8")).hexdigest() == expected_hash

    base_id = knowledge_env["base"]["knowledgeBaseId"]
    member_id = knowledge_env["member"]["agentId"]
    stored_items = team_knowledge_service.list_knowledge_items(base_id, agent_id=member_id)
    stored_item = next(
        row for row in stored_items["items"] if row["knowledgeItemId"] == item["knowledgeItemId"]
    )
    assert stored_item["content"] == content
    assert hashlib.sha256(stored_item["content"].encode("utf-8")).hexdigest() == expected_hash

    search = team_knowledge_service.search_knowledge_items(
        agent_id=member_id,
        knowledge_base_id=base_id,
        query=tail_marker,
        search_mode="exact",
    )
    assert search["summary"]["resultCount"] == 1
    assert search["results"][0]["knowledgeItemId"] == item["knowledgeItemId"]
    assert tail_marker in search["results"][0]["matchedExcerpt"]

    pages = []
    page = read_knowledge_item(
        knowledge_base_id=base_id,
        knowledge_item_id=item["knowledgeItemId"],
        agent_id=member_id,
        offset=0,
        max_chars=4_000,
    )
    while True:
        pages.append(page["content"])
        assert page["contentLength"] == len(content)
        if not page["hasMore"]:
            break
        page = read_knowledge_item(
            knowledge_base_id=base_id,
            knowledge_item_id=item["knowledgeItemId"],
            agent_id=member_id,
            offset=page["nextOffset"],
            max_chars=4_000,
        )

    paged_content = "".join(pages)
    assert len(pages) > 1
    assert paged_content == content
    assert tail_marker in pages[-1]
    assert hashlib.sha256(paged_content.encode("utf-8")).hexdigest() == expected_hash


def test_direct_source_ingestion_preserves_full_body_for_search_and_paged_read(knowledge_env):
    content, tail_marker = _long_body("DIRECT")
    team_id = knowledge_env["team"]["teamId"]
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        team_id,
        source_type="manual_user_entry",
        source_ref={"note": "direct full-body ingestion"},
        original_content=content,
        original_filename="direct-full-body.txt",
        title="Direct full-body source",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        team_id,
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
        ingest_on_accept=True,
        knowledge_base_id=knowledge_env["base"]["knowledgeBaseId"],
        knowledge_title="Direct full-body knowledge",
        knowledge_content=content,
    )

    item = reviewed["directIngestion"]["item"]
    _assert_body_survives_search_and_paged_read(
        knowledge_env,
        item=item,
        content=content,
        tail_marker=tail_marker,
    )


def test_proposal_application_preserves_full_body_for_search_and_paged_read(knowledge_env):
    content, tail_marker = _long_body("PROPOSAL")
    central_source = _accept_source(knowledge_env, label="proposal")
    source_artifact = team_knowledge_service.create_source_artifact_from_central_source(
        knowledge_env["base"]["knowledgeBaseId"],
        central_source["centralSourceId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source_artifact["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Full-body proposal",
        content=content,
    )
    assert proposal["content"] == content
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    _assert_body_survives_search_and_paged_read(
        knowledge_env,
        item=reviewed["item"],
        content=content,
        tail_marker=tail_marker,
    )


def test_ingestion_adapter_preserves_full_body_through_proposal_application(knowledge_env):
    content, tail_marker = _long_body("ADAPTER")
    central_source = _accept_source(knowledge_env, label="adapter")
    package = team_knowledge_service.create_ingestion_package(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="manual_user_entry",
        source_ref={"note": "adapter full-body ingestion"},
        source_title="Adapter source",
        source_summary="A concise source summary remains bounded.",
        excerpt="A concise excerpt remains bounded.",
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        central_source_id=central_source["centralSourceId"],
        proposal_title="Adapter full-body proposal",
        proposal_content=content,
    )
    assert package["proposal"]["content"] == content
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        package["proposal"]["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    _assert_body_survives_search_and_paged_read(
        knowledge_env,
        item=reviewed["item"],
        content=content,
        tail_marker=tail_marker,
    )


@pytest.mark.parametrize("entrypoint", ["source_review", "proposal", "adapter"])
def test_formal_knowledge_ingestion_rejects_bodies_over_api_limit(knowledge_env, entrypoint):
    oversized_content = "x" * 40_001
    base_id = knowledge_env["base"]["knowledgeBaseId"]
    member_id = knowledge_env["member"]["agentId"]
    lead_id = knowledge_env["lead"]["agentId"]

    if entrypoint == "source_review":
        inbox_source = team_knowledge_service.collect_source_to_inbox(
            "team",
            knowledge_env["team"]["teamId"],
            source_type="manual_user_entry",
            source_ref={"note": "oversized direct ingestion"},
            original_content="Captured source body.",
            title="Oversized direct source",
            actor_agent_id=member_id,
        )
        with pytest.raises(team_knowledge_service.TeamKnowledgeError, match="40000"):
            team_knowledge_service.review_owner_inbox_source(
                "team",
                knowledge_env["team"]["teamId"],
                inbox_source["inboxSourceId"],
                decision="accepted",
                reviewed_by_agent_id=lead_id,
                ingest_on_accept=True,
                knowledge_base_id=base_id,
                knowledge_title="Oversized direct item",
                knowledge_content=oversized_content,
            )
        inbox = team_knowledge_service.list_owner_source_inbox(
            "team", knowledge_env["team"]["teamId"], agent_id=lead_id
        )
        assert inbox["sources"][0]["status"] == "pending"
        assert team_knowledge_service.list_central_sources(agent_id=member_id)["summary"]["centralSourceCount"] == 0
        return

    central_source = _accept_source(knowledge_env, label=f"oversized-{entrypoint}")
    source_artifact = team_knowledge_service.create_source_artifact_from_central_source(
        base_id,
        central_source["centralSourceId"],
        actor_agent_id=member_id,
    )
    if entrypoint == "proposal":
        with pytest.raises(team_knowledge_service.TeamKnowledgeError, match="40000"):
            team_knowledge_service.create_refinement_proposal(
                base_id,
                source_artifact_ids=[source_artifact["sourceArtifactId"]],
                proposed_by_agent_id=member_id,
                title="Oversized proposal",
                content=oversized_content,
            )
        return

    with pytest.raises(team_knowledge_service.TeamKnowledgeError, match="40000"):
        team_knowledge_service.create_ingestion_package(
            base_id,
            source_type="manual_user_entry",
            source_ref={"note": "oversized adapter body"},
            source_title="Oversized adapter source",
            proposed_by_agent_id=member_id,
            central_source_id=central_source["centralSourceId"],
            proposal_title="Oversized adapter proposal",
            proposal_content=oversized_content,
        )
