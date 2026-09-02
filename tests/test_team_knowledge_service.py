import pytest

from core.infrastructure import developer_sandbox
from core.web.services import (
    agent_directory_service,
    agent_role_tool_profile_service,
    chat_room_service,
    memory_graph_service,
    team_knowledge_service,
    team_service,
)


def _enable_developer_sandbox(project_root, monkeypatch):
    config_path = project_root / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    return developer_sandbox.update_developer_mode_status(
        True,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=project_root,
    )


@pytest.fixture(autouse=True)
def isolate_developer_sandbox_config(tmp_path, monkeypatch):
    config_path = tmp_path / "developer-mode-off.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "developer-mode-project"
    project_root.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)


@pytest.fixture()
def knowledge_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_graph_service, "PROJECT_ROOT", tmp_path)
    lead = agent_directory_service.create_agent_instance(display_name="Lead Agent", direct_session_id="session-lead")
    member = agent_directory_service.create_agent_instance(display_name="Member Agent", direct_session_id="session-member")
    outsider = agent_directory_service.create_agent_instance(display_name="Outsider Agent", direct_session_id="session-outsider")
    team = team_service.create_team(
        name="Knowledge Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Shared Decisions",
        actor_agent_id=lead["agentId"],
    )
    return {"team": team, "base": base, "lead": lead, "member": member, "outsider": outsider}


def _promote_central_source(
    *,
    owner_type: str,
    owner_id: str,
    actor_agent_id: str,
    reviewer_agent_id: str,
    source_type: str = "manual_user_entry",
    source_ref: dict | None = None,
    title: str = "Test source",
    summary: str = "Governed test source.",
    original_content: str = "Governed test source content.",
) -> dict:
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        owner_type,
        owner_id,
        source_type=source_type,
        source_ref=source_ref or {"note": title},
        original_content=original_content,
        original_filename="test-source.txt",
        title=title,
        summary=summary,
        actor_agent_id=actor_agent_id,
    )
    reviewed = team_knowledge_service.review_owner_inbox_source(
        owner_type,
        owner_id,
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=reviewer_agent_id,
    )
    return reviewed["centralSource"]


def _create_central_source_artifact(
    knowledge_base_id: str,
    *,
    owner_type: str,
    owner_id: str,
    actor_agent_id: str,
    reviewer_agent_id: str,
    source_type: str = "manual_user_entry",
    source_ref: dict | None = None,
    title: str = "Test source",
    summary: str = "Governed test source.",
) -> dict:
    central_source = _promote_central_source(
        owner_type=owner_type,
        owner_id=owner_id,
        actor_agent_id=actor_agent_id,
        reviewer_agent_id=reviewer_agent_id,
        source_type=source_type,
        source_ref=source_ref,
        title=title,
        summary=summary,
    )
    return team_knowledge_service.create_source_artifact_from_central_source(
        knowledge_base_id,
        central_source["centralSourceId"],
        actor_agent_id=actor_agent_id,
        title=title,
        summary=summary,
    )


def _source_ids_for_env(knowledge_env: dict, *, title: str = "Test source") -> list[str]:
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title=title,
    )
    return [source["sourceArtifactId"]]


def test_team_member_can_register_source_and_submit_proposal(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Standup source",
        summary="Decision source",
    )

    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Keep source links",
        content="Every knowledge item keeps source artifacts and timestamps.",
        tags=["memory-platform"],
    )

    assert proposal["status"] == "pending"
    assert proposal["sourceArtifactIds"] == [source["sourceArtifactId"]]


def test_owner_inbox_promotes_source_to_central_registry_and_formal_artifact(knowledge_env, tmp_path):
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="external_search_refinement",
        source_ref={"url": "https://example.test/source", "query": "source governance"},
        original_content="Original external search capture for governed source storage.",
        original_filename="search-capture.txt",
        title="Governed source capture",
        summary="Captured source waits in the owner inbox before central promotion.",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    inbox_path = tmp_path / inbox_source["originalPath"]
    assert inbox_source["status"] == "pending"
    assert inbox_path.exists()
    assert "Original external search capture" in inbox_path.read_text(encoding="utf-8")
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.list_owner_source_inbox(
            "team",
            knowledge_env["team"]["teamId"],
            agent_id=knowledge_env["outsider"]["agentId"],
        )
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.review_owner_inbox_source(
            "team",
            knowledge_env["team"]["teamId"],
            inbox_source["inboxSourceId"],
            decision="accepted",
            reviewed_by_agent_id=knowledge_env["member"]["agentId"],
        )

    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        knowledge_env["team"]["teamId"],
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
        resolution_note="Source is relevant and has preserved capture.",
    )
    central_source = reviewed["centralSource"]
    central_path = tmp_path / central_source["centralPath"]
    registry = team_knowledge_service.list_central_sources(agent_id=knowledge_env["member"]["agentId"])

    assert reviewed["source"]["status"] == "accepted"
    assert reviewed["promotion"]["dedupeStatus"] == "created"
    assert central_source["centralSourceId"]
    assert central_path.exists()
    assert registry["summary"]["centralSourceCount"] == 1
    assert team_knowledge_service.list_central_sources(agent_id=knowledge_env["outsider"]["agentId"])["summary"]["centralSourceCount"] == 0

    source_artifact = team_knowledge_service.create_source_artifact_from_central_source(
        knowledge_env["base"]["knowledgeBaseId"],
        central_source["centralSourceId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source_artifact["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Central source references survive review",
        content="Formal knowledge items should retain central source references for RAG citation provenance.",
    )
    applied = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    assert source_artifact["centralSourceId"] == central_source["centralSourceId"]
    assert proposal["centralSourceIds"] == [central_source["centralSourceId"]]
    assert applied["item"]["centralSourceIds"] == [central_source["centralSourceId"]]


def test_inbox_local_file_copies_promote_to_central_source_and_trace(knowledge_env, tmp_path):
    paper = tmp_path / "papers" / "challenge-note.pdf"
    paper.parent.mkdir()
    paper.write_bytes(b"%PDF-1.4\nchallenge local paper body\n")
    missing = tmp_path / "papers" / "missing.pdf"

    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="pdf_refinement",
        source_ref={"filePath": str(paper), "agentId": knowledge_env["member"]["agentId"]},
        original_content="Steward pack snapshot for a local PDF.",
        original_filename="steward-pack-cand.json",
        title="Local PDF steward pack",
        summary="Pack plus a copyable local paper.",
        actor_agent_id=knowledge_env["member"]["agentId"],
        local_file_paths=[
            {"candidateId": "cand-paper-1", "path": str(paper), "title": "Challenge paper"},
            {"candidateId": "cand-missing", "path": str(missing), "title": "Missing paper"},
            {"candidateId": "cand-url", "path": "https://doi.org/10.0000/remote-only", "title": "Remote DOI"},
        ],
    )

    assert len(inbox_source["localCopies"]) == 1
    inbox_copy = tmp_path / inbox_source["localCopies"][0]["inboxPath"]
    assert inbox_copy.exists()
    assert inbox_copy.read_bytes().startswith(b"%PDF-1.4")
    assert inbox_source["localCopies"][0]["candidateId"] == "cand-paper-1"

    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        knowledge_env["team"]["teamId"],
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
        resolution_note="Keep the local paper copy in the central source store.",
    )
    central_source = reviewed["centralSource"]
    central_copies = list(central_source.get("localCopies") or [])
    assert len(central_copies) == 1
    central_copy = tmp_path / central_copies[0]["centralPath"]
    assert central_copy.exists()
    assert central_copy.read_bytes() == paper.read_bytes()
    assert str(central_copies[0]["centralPath"]).startswith("workspace/")

    source_artifact = team_knowledge_service.create_source_artifact_from_central_source(
        knowledge_env["base"]["knowledgeBaseId"],
        central_source["centralSourceId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        title="Local PDF steward pack",
    )
    artifact_copies = list((source_artifact.get("sourceRef") or {}).get("localCopies") or [])
    assert artifact_copies
    assert artifact_copies[0]["sha256"] == central_copies[0]["sha256"]

    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source_artifact["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Traceable local paper knowledge",
        content="Agents should follow localCopies.centralPath to the copied PDF.",
    )
    applied = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    trace = team_knowledge_service.get_knowledge_trace(
        knowledge_env["base"]["knowledgeBaseId"],
        applied["item"]["knowledgeItemId"],
        agent_id=knowledge_env["member"]["agentId"],
    )
    file_copies = [item for item in trace["localCopies"] if item.get("kind") == "local_file"]
    pack_copies = [item for item in trace["localCopies"] if item.get("kind") == "source_pack"]
    assert trace["summary"]["localCopyCount"] >= 2
    assert file_copies and (tmp_path / file_copies[0]["centralPath"]).exists()
    assert pack_copies and (tmp_path / pack_copies[0]["centralPath"]).exists()

    search = team_knowledge_service.search_knowledge_items(
        agent_id=knowledge_env["member"]["agentId"],
        knowledge_base_id=knowledge_env["base"]["knowledgeBaseId"],
        query="Traceable local paper",
        search_mode="exact",
    )
    assert search["summary"]["resultCount"] == 1
    assert any(item.get("kind") == "local_file" for item in search["results"][0]["localCopies"])


def test_steward_pack_collects_existing_candidate_source_paths(tmp_path, monkeypatch):
    from core.web.services.team_workflow import knowledge as knowledge_mod

    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF-1.4\n")

    class _FakeService:
        team_knowledge_service = type("T", (), {"MAX_LOCAL_SOURCE_COPIES": 16})()

        def _normalize_text_list(self, value, max_items=32, max_length=160):
            return [str(item)[:max_length] for item in list(value or [])[:max_items] if str(item or "").strip()]

        def _load_candidate_store(self, team_id):
            return {
                "candidates": [
                    {"candidateId": "cand-1", "title": "Paper", "sourcePath": str(paper)},
                    {"candidateId": "cand-2", "title": "Missing", "sourcePath": str(tmp_path / "gone.pdf")},
                ]
            }

        def _source_manifest_path(self, item):
            return str(item.get("sourcePath") or "")

        def _source_manifest_label(self, item):
            return str(item.get("title") or "source")

    monkeypatch.setattr(knowledge_mod, "_service", lambda: _FakeService())
    paths = knowledge_mod._steward_pack_local_file_paths("team-1", {"candidateIds": ["cand-1", "cand-2"]})
    assert paths == [
        {"candidateId": "cand-1", "path": str(paper), "title": "Paper"},
        {"candidateId": "cand-2", "path": str(tmp_path / "gone.pdf"), "title": "Missing"},
    ]


def test_owner_source_review_directly_ingests_accepted_source_into_formal_knowledge(knowledge_env):
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="external_search_refinement",
        source_ref={"url": "https://example.test/direct", "query": "direct memory ingestion"},
        original_content="Direct ingestion source content with evidence for governed team memory.",
        original_filename="direct-ingestion.txt",
        title="Direct ingestion source",
        summary="Knowledge steward accepted source should become formal knowledge without a proposal wait.",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        knowledge_env["team"]["teamId"],
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
        resolution_note="筛选通过，直接入库。",
        ingest_on_accept=True,
        knowledge_base_id=knowledge_env["base"]["knowledgeBaseId"],
        knowledge_title="Direct ingestion becomes governed memory",
        knowledge_summary="Accepted source review can create a formal KnowledgeItem directly.",
        knowledge_content="Accepted owner inbox sources can be screened once and then become searchable formal team knowledge.",
        tags=["direct-ingestion", "memory-platform"],
    )

    direct = reviewed["directIngestion"]
    items = team_knowledge_service.list_knowledge_items(
        knowledge_env["base"]["knowledgeBaseId"],
        agent_id=knowledge_env["member"]["agentId"],
    )
    governance = team_knowledge_service.list_knowledge_governance_tasks(agent_id=knowledge_env["lead"]["agentId"])

    assert reviewed["source"]["status"] == "accepted"
    assert direct["status"] == "ingested"
    assert direct["sourceArtifact"]["centralSourceId"] == reviewed["centralSource"]["centralSourceId"]
    assert direct["item"]["centralSourceIds"] == [reviewed["centralSource"]["centralSourceId"]]
    assert direct["item"]["sourceArtifactIds"] == [direct["sourceArtifact"]["sourceArtifactId"]]
    assert direct["item"]["title"] == "Direct ingestion becomes governed memory"
    assert items["summary"]["itemCount"] == 1
    assert items["items"][0]["knowledgeItemId"] == direct["item"]["knowledgeItemId"]
    assert governance["summary"]["proposalReviewCount"] == 0


def test_global_knowledge_steward_can_direct_ingest_screened_team_source(knowledge_env):
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "steward direct source"},
        original_content="Knowledge steward direct ingestion source.",
        title="Steward direct source",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        knowledge_env["team"]["teamId"],
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=steward_id,
        ingest_on_accept=True,
        knowledge_base_id=knowledge_env["base"]["knowledgeBaseId"],
        knowledge_title="Knowledge steward direct memory",
        knowledge_content="The global knowledge steward can screen a Team source and direct-ingest it into the Team knowledge base.",
        tags=["steward", "direct-ingestion"],
    )
    items = team_knowledge_service.list_knowledge_items(
        knowledge_env["base"]["knowledgeBaseId"],
        agent_id=knowledge_env["member"]["agentId"],
    )

    assert reviewed["directIngestion"]["status"] == "ingested"
    assert reviewed["directIngestion"]["item"]["reviewedByAgentId"] == steward_id
    assert items["summary"]["itemCount"] == 1


def test_direct_ingestion_rejects_cross_owner_target_knowledge_base(knowledge_env):
    other_lead = agent_directory_service.create_agent_instance(display_name="Other Lead")
    other_team = team_service.create_team(name="Other Knowledge Team", members=[{"agentId": other_lead["agentId"], "role": "lead"}])
    other_base = team_knowledge_service.create_knowledge_base(
        other_team["teamId"],
        name="Other Team KB",
        actor_agent_id=other_lead["agentId"],
    )
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "cross owner source"},
        original_content="Cross owner source should stay scoped to its owner.",
        title="Cross owner source",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.review_owner_inbox_source(
            "team",
            knowledge_env["team"]["teamId"],
            inbox_source["inboxSourceId"],
            decision="accepted",
            reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
            ingest_on_accept=True,
            knowledge_base_id=other_base["knowledgeBaseId"],
            knowledge_title="Should not cross owner",
            knowledge_content="A source owned by one team cannot direct-ingest into another team's knowledge base.",
        )


def test_developer_mode_routes_owner_knowledge_state_to_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_graph_service, "PROJECT_ROOT", tmp_path)
    enabled = _enable_developer_sandbox(tmp_path, monkeypatch)

    lead = agent_directory_service.create_agent_instance(display_name="Sandbox Lead")
    team = team_service.create_team(name="Sandbox Team", members=[{"agentId": lead["agentId"], "role": "lead"}])
    team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Debug Knowledge",
        actor_agent_id=lead["agentId"],
    )

    sandbox_workspace = tmp_path / ".runtime" / "developer-mode" / "sandboxes" / enabled["sandbox"]["sandboxId"] / "workspace"
    sandbox_bases = sandbox_workspace / "teams" / team["teamId"] / "knowledge" / "knowledge_bases.json"
    formal_bases = tmp_path / "workspace" / "teams" / team["teamId"] / "knowledge" / "knowledge_bases.json"

    assert sandbox_bases.exists()
    assert not formal_bases.exists()


def test_developer_mode_blocks_owner_source_central_promotion(knowledge_env, tmp_path, monkeypatch):
    enabled = _enable_developer_sandbox(tmp_path, monkeypatch)
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "debug-only source"},
        original_content="Debug-only source should not be promoted to central storage.",
        original_filename="debug-source.txt",
        title="Debug-only source",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    with pytest.raises(developer_sandbox.DeveloperSandboxWriteBlocked):
        team_knowledge_service.review_owner_inbox_source(
            "team",
            knowledge_env["team"]["teamId"],
            inbox_source["inboxSourceId"],
            decision="accepted",
            reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
        )

    sandbox_workspace = tmp_path / ".runtime" / "developer-mode" / "sandboxes" / enabled["sandbox"]["sandboxId"] / "workspace"
    assert (sandbox_workspace / "teams" / knowledge_env["team"]["teamId"] / "knowledge" / "inbox").exists()
    assert not (tmp_path / "workspace" / "knowledge" / "sources" / "registry" / "source_registry.jsonl").exists()


def test_developer_mode_blocks_duplicate_source_owner_ref_write(knowledge_env, tmp_path, monkeypatch):
    central_source = _promote_central_source(
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Formal source",
        original_content="Formal source created before developer mode.",
    )
    owner_refs_path = tmp_path / "workspace" / "knowledge" / "sources" / "registry" / "owner_refs.jsonl"
    before_owner_refs = owner_refs_path.read_text(encoding="utf-8")
    _enable_developer_sandbox(tmp_path, monkeypatch)
    duplicate_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "debug duplicate"},
        original_content="Debug duplicate source should not append a formal owner ref.",
        title="Debug duplicate",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    with pytest.raises(developer_sandbox.DeveloperSandboxWriteBlocked):
        team_knowledge_service.review_owner_inbox_source(
            "team",
            knowledge_env["team"]["teamId"],
            duplicate_source["inboxSourceId"],
            decision="duplicate",
            duplicate_of=central_source["centralSourceId"],
            reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
        )

    assert owner_refs_path.read_text(encoding="utf-8") == before_owner_refs


def test_agent_inbox_is_private_and_global_steward_can_promote(knowledge_env):
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "agent",
        knowledge_env["member"]["agentId"],
        source_type="agent_authored",
        source_ref={"agentId": knowledge_env["member"]["agentId"], "note": "private source"},
        original_content="Private Agent source should remain owner-scoped before central review.",
        title="Private Agent source",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.list_owner_source_inbox(
            "agent",
            knowledge_env["member"]["agentId"],
            agent_id=knowledge_env["outsider"]["agentId"],
        )
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.review_owner_inbox_source(
            "agent",
            knowledge_env["member"]["agentId"],
            inbox_source["inboxSourceId"],
            decision="accepted",
            reviewed_by_agent_id=knowledge_env["outsider"]["agentId"],
        )

    reviewed = team_knowledge_service.review_owner_inbox_source(
        "agent",
        knowledge_env["member"]["agentId"],
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID,
    )

    assert reviewed["centralSource"]["centralSourceId"]
    assert team_knowledge_service.list_central_sources(agent_id=knowledge_env["member"]["agentId"])["summary"]["centralSourceCount"] == 1
    assert team_knowledge_service.list_central_sources(agent_id=knowledge_env["outsider"]["agentId"])["summary"]["centralSourceCount"] == 0


def test_knowledge_steward_policy_includes_skill_library_search_tool():
    policy = agent_directory_service._knowledge_steward_tool_policy()
    expected_policy = agent_role_tool_profile_service.resolve_role_tool_policy(
        role_key="knowledge_steward",
        primary_mode="general",
        metadata={"systemRole": "knowledge_steward"},
        policy_id=agent_directory_service.KNOWLEDGE_STEWARD_TOOL_POLICY_ID,
    )
    assert expected_policy is not None

    assert "skill_library_search_tool" in policy["allowedTools"]
    assert "skill_library_search_tool" in policy["preferredTools"]
    assert "github_project_library_search_tool" in policy["allowedTools"]
    assert "github_project_library_search_tool" in policy["preferredTools"]
    assert "github_project_library_clone_tool" not in policy["allowedTools"]
    assert "source_collection_context_tool" in policy["allowedTools"]
    assert "source_collection_stage_writeback_tool" in policy["allowedTools"]
    assert policy["preferredTools"] == expected_policy["preferredTools"]


def test_research_agent_creation_and_readiness_report_expose_unified_memory_search(knowledge_env):
    research_agent = agent_directory_service.create_agent_instance(
        display_name="Research Memory Agent",
        primary_mode="research",
        role_key="research_paper_reader",
    )
    research_team = team_service.create_team(
        name="Research Memory Team",
        members=[{"agentId": research_agent["agentId"], "role": "member"}],
    )
    team_knowledge_service.create_knowledge_base(
        research_team["teamId"],
        name="Research Memory KB",
        actor_agent_id=research_agent["agentId"],
    )
    expected_policy = agent_role_tool_profile_service.resolve_role_tool_policy(
        role_key="research_paper_reader",
        primary_mode="research",
        policy_id=f"tool-{research_agent['agentId']}",
    )
    assert expected_policy is not None

    assert research_agent["toolPolicy"]["allowedTools"] == expected_policy["allowedTools"]
    assert research_agent["toolPolicy"]["preferredTools"] == expected_policy["preferredTools"]

    report = team_knowledge_service.get_agent_memory_readiness_report(agent_id=knowledge_env["lead"]["agentId"])
    row = next(item for item in report["agents"] if item["agentId"] == research_agent["agentId"])

    assert report["schemaVersion"] == team_knowledge_service.SCHEMA_VERSION
    assert report["operatingBoundary"]["readOnly"] is True
    assert report["operatingBoundary"]["mutatesFormalKnowledge"] is False
    assert report["summary"]["agentCount"] >= 4
    assert report["summary"]["unifiedMemorySearchToolAgentCount"] >= 1
    assert report["summary"]["visibleKnowledgeBaseCount"] >= 1
    assert row["memorySearch"]["hasUnifiedMemorySearchTool"] is True
    assert row["memorySearch"]["primarySearchTool"] == "unified_memory_search_tool"
    assert row["formalKnowledge"]["visibleKnowledgeBaseCount"] == 1
    assert row["formalKnowledge"]["effectiveReadScope"] == "team_membership_and_owner_acl"


def test_global_knowledge_steward_can_prepare_formal_kb_governance_without_applying(knowledge_env):
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Steward governance source",
    )

    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=steward_id,
        title="Steward prepares proposal",
        content="Knowledge Steward can prepare formal knowledge proposals without applying them.",
        tags=["steward"],
    )
    suggestion = team_knowledge_service.create_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggested_by_agent_id=steward_id,
        target_type="proposal",
        proposal_id=proposal["proposalId"],
        importance_level="medium",
        confidence=0.7,
        stability="evolving",
        review_priority="normal",
        marking_reason="Steward proposes metadata; reviewers still apply it.",
    )

    tasks = team_knowledge_service.list_knowledge_governance_tasks(agent_id=steward_id)
    recommendations = team_knowledge_service.list_knowledge_steward_recommendations(agent_id=steward_id)

    assert proposal["status"] == "pending"
    assert suggestion["status"] == "pending"
    assert tasks["summary"]["openTaskCount"] >= 2
    assert recommendations["summary"]["recommendationCount"] >= 2

    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.review_refinement_proposal(
            knowledge_env["base"]["knowledgeBaseId"],
            proposal["proposalId"],
            status="applied",
            reviewed_by_agent_id=steward_id,
        )
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.review_rating_suggestion(
            knowledge_env["base"]["knowledgeBaseId"],
            suggestion["suggestionId"],
            status="applied",
            reviewed_by_agent_id=steward_id,
        )


def test_central_source_registry_dedupes_by_source_hash(knowledge_env):
    first = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "duplicate source"},
        original_content="Same source body.",
        title="Duplicate source",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )
    second = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "duplicate source"},
        original_content="Same source body.",
        title="Duplicate source",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    first_review = team_knowledge_service.review_owner_inbox_source(
        "team",
        knowledge_env["team"]["teamId"],
        first["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    second_review = team_knowledge_service.review_owner_inbox_source(
        "team",
        knowledge_env["team"]["teamId"],
        second["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    registry = team_knowledge_service.list_central_sources(agent_id=knowledge_env["lead"]["agentId"])

    assert first_review["centralSource"]["centralSourceId"] == second_review["centralSource"]["centralSourceId"]
    assert second_review["promotion"]["dedupeStatus"] == "reused"
    assert registry["summary"]["centralSourceCount"] == 1
    assert registry["summary"]["ownerRefCount"] == 2


def test_agent_formal_knowledge_is_private_and_governed(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    owner = agent_directory_service.create_agent_instance(display_name="Owner Agent")
    other = agent_directory_service.create_agent_instance(display_name="Other Agent")

    base = team_knowledge_service.create_agent_knowledge_base(
        owner["agentId"],
        name="Owner Private Formal Knowledge",
        actor_agent_id=owner["agentId"],
    )
    source = _create_central_source_artifact(
        base["knowledgeBaseId"],
        owner_type="agent",
        owner_id=owner["agentId"],
        actor_agent_id=owner["agentId"],
        reviewer_agent_id=owner["agentId"],
        source_type="agent_authored",
        source_ref={"agentId": owner["agentId"], "note": "private formal memory"},
        title="Private source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=owner["agentId"],
        title="Private RAG boundary",
        content="Agent private formal knowledge can be governed and retrieved only by its owning Agent.",
        tags=["agent-private"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        base["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=owner["agentId"],
    )

    owner_results = team_knowledge_service.search_knowledge_items(
        agent_id=owner["agentId"],
        owner_type="agent",
        owner_id=owner["agentId"],
        query="private formal knowledge",
        search_mode="semantic",
    )
    other_results = team_knowledge_service.search_knowledge_items(
        agent_id=other["agentId"],
        owner_type="agent",
        owner_id=owner["agentId"],
        query="private formal knowledge",
        search_mode="semantic",
    )

    assert base["ownerType"] == "agent"
    assert base["ownerId"] == owner["agentId"]
    assert reviewed["item"]["ownerType"] == "agent"
    assert reviewed["item"]["agentId"] == owner["agentId"]
    assert owner_results["summary"]["resultCount"] == 1
    assert owner_results["results"][0]["ownerType"] == "agent"
    assert owner_results["results"][0]["agentId"] == owner["agentId"]
    assert other_results["summary"]["resultCount"] == 0
    assert (tmp_path / "workspace" / "agents" / owner["agentId"] / "knowledge" / "knowledge_bases.json").exists()


def test_duplicate_knowledge_base_ids_require_owner_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    first_agent = agent_directory_service.create_agent_instance(display_name="First KB Owner")
    second_agent = agent_directory_service.create_agent_instance(display_name="Second KB Owner")
    viewer = agent_directory_service.create_agent_instance(display_name="Duplicate KB Viewer")
    first_team = team_service.create_team(name="First KB Team", members=[{"agentId": first_agent["agentId"], "role": "lead"}])
    second_team = team_service.create_team(name="Second KB Team", members=[{"agentId": second_agent["agentId"], "role": "lead"}])
    first_base = team_knowledge_service.create_knowledge_base(
        first_team["teamId"],
        name="Duplicate KB",
        actor_agent_id=first_agent["agentId"],
        acl={"grants": {"read": [viewer["agentId"]]}},
    )
    second_base = team_knowledge_service.create_knowledge_base(
        second_team["teamId"],
        name="Duplicate KB",
        actor_agent_id=second_agent["agentId"],
        acl={"grants": {"read": [viewer["agentId"]]}},
    )

    assert first_base["knowledgeBaseId"] == second_base["knowledgeBaseId"]
    assert first_base["scopedKnowledgeBaseId"] != second_base["scopedKnowledgeBaseId"]
    with pytest.raises(team_knowledge_service.TeamKnowledgeAmbiguousKnowledgeBaseError):
        team_knowledge_service.list_knowledge_items(first_base["knowledgeBaseId"], agent_id=first_agent["agentId"])
    with pytest.raises(team_knowledge_service.TeamKnowledgeAmbiguousKnowledgeBaseError):
        team_knowledge_service.search_knowledge_items(
            agent_id=viewer["agentId"],
            knowledge_base_id=first_base["knowledgeBaseId"],
        )

    scoped_source = _create_central_source_artifact(
        first_base["scopedKnowledgeBaseId"],
        owner_type="team",
        owner_id=first_team["teamId"],
        actor_agent_id=first_agent["agentId"],
        reviewer_agent_id=first_agent["agentId"],
        title="First scoped source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        first_base["scopedKnowledgeBaseId"],
        source_artifact_ids=[scoped_source["sourceArtifactId"]],
        proposed_by_agent_id=first_agent["agentId"],
        title="First scoped item",
        content="Only the scoped first knowledge base should receive this item.",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        first_base["scopedKnowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=first_agent["agentId"],
    )
    scoped_items = team_knowledge_service.list_knowledge_items(
        first_base["scopedKnowledgeBaseId"],
        agent_id=first_agent["agentId"],
    )
    second_items = team_knowledge_service.list_knowledge_items(
        second_base["scopedKnowledgeBaseId"],
        agent_id=second_agent["agentId"],
    )

    assert scoped_items["summary"]["itemCount"] == 1
    assert scoped_items["items"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]
    assert second_items["summary"]["itemCount"] == 0

    direct_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        first_team["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "first direct scoped source"},
        original_content="Direct scoped source content.",
        title="First direct scoped source",
        actor_agent_id=first_agent["agentId"],
    )
    direct_review = team_knowledge_service.review_owner_inbox_source(
        "team",
        first_team["teamId"],
        direct_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=first_agent["agentId"],
        ingest_on_accept=True,
        knowledge_base_id=first_base["scopedKnowledgeBaseId"],
        knowledge_title="First scoped direct item",
        knowledge_content="Direct ingestion must use the scoped knowledge base id after resolving the owner.",
    )
    scoped_items_after_direct = team_knowledge_service.list_knowledge_items(
        first_base["scopedKnowledgeBaseId"],
        agent_id=first_agent["agentId"],
    )
    second_items_after_direct = team_knowledge_service.list_knowledge_items(
        second_base["scopedKnowledgeBaseId"],
        agent_id=second_agent["agentId"],
    )

    assert direct_review["directIngestion"]["scopedKnowledgeBaseId"] == first_base["scopedKnowledgeBaseId"]
    assert scoped_items_after_direct["summary"]["itemCount"] == 2
    assert second_items_after_direct["summary"]["itemCount"] == 0


def test_empty_actor_cannot_create_or_read_governed_knowledge_service(knowledge_env):
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.create_knowledge_base(
            knowledge_env["team"]["teamId"],
            name="Anonymous Team KB",
        )

    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.create_agent_knowledge_base(
            knowledge_env["member"]["agentId"],
            name="Anonymous Agent KB",
        )

    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Empty actor source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Empty actor service guard",
        content="Empty actor service calls must not read governed knowledge.",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    assert team_knowledge_service.list_knowledge_overview()["summary"]["knowledgeBaseCount"] == 0
    assert team_knowledge_service.list_knowledge_governance_tasks(status="all")["summary"]["taskCount"] == 0
    assert team_knowledge_service.get_knowledge_operations_health()["summary"]["knowledgeBaseCount"] == 0
    assert team_knowledge_service.get_knowledge_governance_plan()["summary"]["actionCount"] == 0
    assert team_knowledge_service.list_knowledge_steward_recommendations()["summary"]["recommendationCount"] == 0
    assert team_knowledge_service.get_knowledge_steward_workbench()["summary"]["openTaskCount"] == 0
    assert team_knowledge_service.get_knowledge_dashboard_snapshot()["overview"]["summary"]["knowledgeBaseCount"] == 0
    assert team_knowledge_service.get_knowledge_steward_overview()["governance"]["summary"]["openTaskCount"] == 0
    assert team_knowledge_service.search_knowledge_items(query="empty actor")["summary"]["resultCount"] == 0

    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.list_knowledge_items(knowledge_env["base"]["knowledgeBaseId"])
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.get_knowledge_trace(
            knowledge_env["base"]["knowledgeBaseId"],
            reviewed["item"]["knowledgeItemId"],
        )
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.list_rating_suggestions(knowledge_env["base"]["knowledgeBaseId"])

    internal_overview = team_knowledge_service.list_knowledge_overview(internal=True)
    internal_health = team_knowledge_service.get_knowledge_operations_health(internal=True)

    assert internal_overview["summary"]["knowledgeBaseCount"] == 1
    assert internal_health["summary"]["knowledgeBaseCount"] == 1


def test_internal_team_knowledge_base_list_uses_lightweight_team_identity(knowledge_env, monkeypatch):
    team = knowledge_env["team"]

    def fail_full_team_read(team_id):
        raise AssertionError("internal knowledge-base listing must not hydrate full team detail")

    monkeypatch.setattr(team_knowledge_service.team_service, "get_team", fail_full_team_read)

    payload = team_knowledge_service.list_team_knowledge_bases(team["teamId"], internal=True)

    assert payload["teamId"] == team["teamId"]
    assert payload["summary"]["knowledgeBaseCount"] == 1


def test_team_knowledge_memory_section_summary_uses_lightweight_disk_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    lead = agent_directory_service.create_agent_instance(display_name="Lead Agent")
    team = team_service.create_team(name="Knowledge Team", members=[{"agentId": lead["agentId"], "role": "lead"}])
    base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Shared Decisions",
        actor_agent_id=lead["agentId"],
    )
    source = _create_central_source_artifact(
        base["knowledgeBaseId"],
        owner_type="team",
        owner_id=team["teamId"],
        actor_agent_id=lead["agentId"],
        reviewer_agent_id=lead["agentId"],
        title="Summary source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=lead["agentId"],
        title="Pending summary proposal",
        content="Pending proposal should be counted by the lightweight summary.",
    )
    team_knowledge_service.review_refinement_proposal(
        base["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=lead["agentId"],
    )
    pending_source = _create_central_source_artifact(
        base["knowledgeBaseId"],
        owner_type="team",
        owner_id=team["teamId"],
        actor_agent_id=lead["agentId"],
        reviewer_agent_id=lead["agentId"],
        title="Still pending source",
    )
    team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"],
        source_artifact_ids=[pending_source["sourceArtifactId"]],
        proposed_by_agent_id=lead["agentId"],
        title="Still pending",
        content="This proposal remains pending.",
    )

    def fail_full_overview(**_kwargs):
        raise AssertionError("memory summary must not call full list_knowledge_overview")

    monkeypatch.setattr(team_knowledge_service, "list_knowledge_overview", fail_full_overview)

    summary = team_knowledge_service.team_knowledge_memory_section_summary()

    assert summary["knowledgeBaseCount"] == 1
    assert summary["pendingProposalCount"] == 1
    assert summary["itemCount"] == 1
    assert summary["sourceArtifactCount"] == 2
    assert summary["updatedAt"]


def test_non_member_cannot_submit_proposal(knowledge_env):
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.create_refinement_proposal(
            knowledge_env["base"]["knowledgeBaseId"],
            source_artifact_ids=[],
            proposed_by_agent_id=knowledge_env["outsider"]["agentId"],
            title="No access",
            content="This should be blocked.",
        )


def test_review_role_applies_proposal_into_batch_and_item(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="agent_authored",
        source_ref={"agentId": knowledge_env["member"]["agentId"]},
        title="Agent note",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Use proposal gate",
        summary="Formal knowledge is applied from proposals.",
        content="Agents submit candidates; leads apply them into batches.",
    )

    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    assert reviewed["proposal"]["status"] == "applied"
    assert reviewed["batch"]["sourceArtifactIds"] == [source["sourceArtifactId"]]
    assert reviewed["item"]["batchId"] == reviewed["batch"]["batchId"]
    assert reviewed["item"]["sourceArtifactIds"] == [source["sourceArtifactId"]]


def test_team_chat_refinement_source_collection_requires_team_linked_room(knowledge_env):
    with pytest.raises(team_knowledge_service.TeamKnowledgeError, match="linked chat room"):
        team_knowledge_service.collect_source_to_inbox(
            "team",
            knowledge_env["team"]["teamId"],
            source_type="team_chat_refinement",
            source_ref={"roomId": "room-not-linked", "messageRange": {"from": 0, "to": 1}},
            actor_agent_id=knowledge_env["member"]["agentId"],
        )

    linked_room_id = knowledge_env["team"]["linkedChatRoomId"]
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="team_chat_refinement",
        source_ref={"roomId": linked_room_id, "messageRange": {"from": 0, "to": 1}},
    )
    assert source["sourceType"] == "team_chat_refinement"


def test_rating_update_records_marker_and_audit(knowledge_env, tmp_path):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Rate knowledge source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Rate knowledge",
        content="Important knowledge can be marked later.",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="applied",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    rated = team_knowledge_service.update_knowledge_item_rating(
        knowledge_env["base"]["knowledgeBaseId"],
        reviewed["item"]["knowledgeItemId"],
        actor_agent_id=knowledge_env["lead"]["agentId"],
        importance_level="critical",
        confidence=0.95,
        stability="stable",
        scope="team",
        review_priority="urgent",
        marking_reason="Operationally required.",
    )

    assert rated["importanceLevel"] == "critical"
    assert rated["confidence"] == 0.95
    assert rated["markedBy"] == knowledge_env["lead"]["agentId"]
    audit_path = tmp_path / "workspace" / "teams" / knowledge_env["team"]["teamId"] / "knowledge" / "audit.jsonl"
    assert "knowledge.item.rating.updated" in audit_path.read_text(encoding="utf-8")


def test_rating_suggestion_is_reviewable_before_item_update(knowledge_env):
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Suggested rating source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Suggested rating",
        content="A reviewer should apply rating suggestions before item metadata changes.",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="applied",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    suggestion = team_knowledge_service.create_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggested_by_agent_id=knowledge_env["lead"]["agentId"],
        target_type="knowledge_item",
        knowledge_item_id=reviewed["item"]["knowledgeItemId"],
        importance_level="critical",
        confidence=0.96,
        stability="stable",
        review_priority="urgent",
        marking_reason="Management agent suggests promotion.",
    )
    before = team_knowledge_service.list_knowledge_items(
        knowledge_env["base"]["knowledgeBaseId"],
        agent_id=knowledge_env["member"]["agentId"],
    )["items"][0]

    assert suggestion["status"] == "pending"
    assert before["importanceLevel"] == "medium"

    applied = team_knowledge_service.review_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggestion["suggestionId"],
        status="applied",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    assert applied["suggestion"]["status"] == "applied"
    assert applied["item"]["importanceLevel"] == "critical"
    assert applied["item"]["markedBy"] == knowledge_env["lead"]["agentId"]


def test_rating_suggestion_bulk_review_applies_pending_and_skips_closed(knowledge_env, tmp_path):
    proposal_one = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Bulk rating one source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Bulk rating one",
        content="First item should receive bulk rating.",
    )
    proposal_two = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Bulk rating two source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Bulk rating two",
        content="Second item should receive bulk rating.",
    )
    item_one = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal_one["proposalId"],
        status="applied",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )["item"]
    item_two = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal_two["proposalId"],
        status="applied",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )["item"]
    suggestion_one = team_knowledge_service.create_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggested_by_agent_id=knowledge_env["lead"]["agentId"],
        target_type="knowledge_item",
        knowledge_item_id=item_one["knowledgeItemId"],
        importance_level="critical",
        confidence=0.91,
        stability="stable",
        review_priority="urgent",
        marking_reason="Bulk promotion one.",
    )
    suggestion_two = team_knowledge_service.create_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggested_by_agent_id=knowledge_env["lead"]["agentId"],
        target_type="knowledge_item",
        knowledge_item_id=item_two["knowledgeItemId"],
        importance_level="high",
        confidence=0.81,
        stability="evolving",
        review_priority="elevated",
        marking_reason="Bulk promotion two.",
    )
    team_knowledge_service.review_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggestion_two["suggestionId"],
        status="rejected",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    result = team_knowledge_service.review_rating_suggestions_bulk(
        knowledge_env["base"]["knowledgeBaseId"],
        suggestion_ids=[suggestion_one["suggestionId"], suggestion_two["suggestionId"], "missing-suggestion"],
        status="applied",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
        resolution_note="Batch queue reviewed.",
    )

    assert result["summary"] == {
        "requestedCount": 3,
        "reviewedCount": 1,
        "skippedCount": 2,
        "appliedItemCount": 1,
    }
    assert {item["reason"] for item in result["skipped"]} == {"not_pending", "not_found"}
    items = team_knowledge_service.list_knowledge_items(
        knowledge_env["base"]["knowledgeBaseId"],
        agent_id=knowledge_env["member"]["agentId"],
    )["items"]
    rated_item = next(item for item in items if item["knowledgeItemId"] == item_one["knowledgeItemId"])
    untouched_item = next(item for item in items if item["knowledgeItemId"] == item_two["knowledgeItemId"])
    assert rated_item["importanceLevel"] == "critical"
    assert untouched_item["importanceLevel"] == "medium"
    audit_path = tmp_path / "workspace" / "teams" / knowledge_env["team"]["teamId"] / "knowledge" / "audit.jsonl"
    assert "knowledge.rating_suggestion.bulk_reviewed" in audit_path.read_text(encoding="utf-8")


def test_search_filters_only_visible_formal_items(knowledge_env):
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Searchable source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Searchable governance knowledge",
        content="Formal knowledge search should include reviewed items only.",
        tags=["governance", "search"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    team_knowledge_service.update_knowledge_item_rating(
        knowledge_env["base"]["knowledgeBaseId"],
        reviewed["item"]["knowledgeItemId"],
        actor_agent_id=knowledge_env["lead"]["agentId"],
        importance_level="high",
    )

    member_results = team_knowledge_service.search_knowledge_items(
        agent_id=knowledge_env["member"]["agentId"],
        query="governance",
        tags=["search"],
        importance_level="high",
    )
    outsider_results = team_knowledge_service.search_knowledge_items(
        agent_id=knowledge_env["outsider"]["agentId"],
        query="governance",
    )

    assert member_results["summary"]["resultCount"] == 1
    assert member_results["results"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]
    assert outsider_results["summary"]["resultCount"] == 0


def test_permission_audit_explains_tool_memory_and_team_boundaries(knowledge_env):
    agent_directory_service.update_agent_instance(
        knowledge_env["member"]["agentId"],
        tool_policy={"allowedTools": ["unified_memory_search_tool"]},
        memory_policy={"readKnowledgeBaseIds": [knowledge_env["base"]["knowledgeBaseId"]]},
    )

    audit = team_knowledge_service.knowledge_permission_audit(agent_id=knowledge_env["member"]["agentId"])

    assert audit["tools"]["unified_memory_search_tool"]["visible"] is True
    assert audit["tools"]["knowledge_proposal_tool"]["reason"] == "available"
    row = audit["knowledgeBases"][0]
    assert row["permissions"]["read"]["allowed"] is True
    assert row["permissions"]["review"]["allowed"] is False
    assert row["permissions"]["review"]["reason"] == "team_acl_blocked"


def test_ingestion_package_creates_source_and_pending_proposal_only(knowledge_env):
    central_source = _promote_central_source(
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="pdf_refinement",
        source_ref={"filePath": "workspace/research/report.pdf", "pageRange": "3-5"},
        title="Report pages 3-5",
        summary="PDF evidence about memory governance.",
    )
    package = team_knowledge_service.create_ingestion_package(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="pdf_refinement",
        source_ref={"filePath": "workspace/research/report.pdf", "pageRange": "3-5"},
        source_title="Report pages 3-5",
        source_summary="PDF evidence about memory governance.",
        excerpt="The PDF says governance knowledge must keep source pages.",
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        proposal_title="Keep PDF page provenance",
        tags=["pdf", "governance"],
        central_source_id=central_source["centralSourceId"],
    )
    items = team_knowledge_service.list_knowledge_items(
        knowledge_env["base"]["knowledgeBaseId"],
        agent_id=knowledge_env["member"]["agentId"],
    )

    assert package["status"] == "submitted"
    assert package["sourceArtifact"]["sourceType"] == "pdf_refinement"
    assert package["proposal"]["status"] == "pending"
    assert package["proposal"]["sourceArtifactIds"] == [package["sourceArtifact"]["sourceArtifactId"]]
    assert items["summary"]["itemCount"] == 0


def test_governance_tasks_adapters_and_trace_are_readable(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Orphan source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Traceable proposal",
        content="Traceable knowledge proposal.",
    )

    tasks = team_knowledge_service.list_knowledge_governance_tasks(agent_id=knowledge_env["lead"]["agentId"])
    adapters = team_knowledge_service.list_ingestion_adapters()
    trace = team_knowledge_service.get_knowledge_trace(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        agent_id=knowledge_env["member"]["agentId"],
    )

    assert tasks["summary"]["proposalReviewCount"] == 1
    assert any(task["taskType"] == "proposal_review" for task in tasks["tasks"])
    assert adapters["summary"]["adapterCount"] == len(team_knowledge_service.SOURCE_TYPES)
    assert trace["targetType"] == "proposal"
    assert trace["summary"]["sourceArtifacts"] == 1
    assert trace["summary"]["proposals"] == 1


def test_memory_knowledge_graph_links_project_agents_team_and_knowledge_without_bodies(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="agent_authored",
        source_ref={"agentId": knowledge_env["member"]["agentId"], "excerpt": "do not expose source body"},
        title="Graph source",
        summary="Graph source summary.",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Graph proposal",
        summary="Graph proposal summary.",
        content="SECRET FORMAL KNOWLEDGE BODY SHOULD NOT LEAK",
        tags=["graph"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    graph = memory_graph_service.get_memory_knowledge_graph(agent_id=knowledge_env["member"]["agentId"])
    node_types = {node["type"] for node in graph["nodes"]}
    edge_types = {edge["type"] for edge in graph["edges"]}
    payload_text = str(graph)

    assert graph["mode"] == "read_only_project_memory_graph"
    assert graph["operatingBoundary"]["readOnly"] is True
    assert graph["operatingBoundary"]["gpuPreferred"] is True
    assert {"project", "team", "agent"}.issubset(node_types)
    assert not {"agent_private_memory", "knowledge_base", "knowledge_item", "source_artifact"}.intersection(node_types)
    assert {"project_has_team", "team_has_agent"}.issubset(edge_types)
    member_node = next(
        node for node in graph["nodes"]
        if node["type"] == "agent" and node["metadata"]["agentId"] == knowledge_env["member"]["agentId"]
    )
    team_node = next(node for node in graph["nodes"] if node["type"] == "team")
    assert member_node["visual"]["agentCategory"] == "team_member_agent"
    assert member_node["responsibilityQuestion"]
    assert {member_node["id"], f"agent:{knowledge_env['lead']['agentId']}"}.issubset(set(team_node["childNodeIds"]))
    assert member_node["contentItems"] == []
    assert team_node["contentItems"][0]["title"] == "Graph proposal"
    assert reviewed["item"]["knowledgeItemId"] in payload_text
    assert "SECRET FORMAL KNOWLEDGE BODY SHOULD NOT LEAK" not in payload_text
    assert "do not expose source body" not in payload_text


def test_memory_knowledge_graph_node_detail_returns_acl_scoped_full_content(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="agent_authored",
        source_ref={"agentId": knowledge_env["member"]["agentId"]},
        title="Node detail source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Node detail knowledge",
        summary="Node detail summary.",
        content="NODE DETAIL FORMAL KNOWLEDGE BODY",
        tags=["node-detail"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    graph = memory_graph_service.get_memory_knowledge_graph(agent_id=knowledge_env["member"]["agentId"])
    member_detail = memory_graph_service.get_memory_knowledge_graph_node_detail(
        f"team:{knowledge_env['team']['teamId']}",
        agent_id=knowledge_env["member"]["agentId"],
    )
    item_detail = memory_graph_service.get_memory_knowledge_graph_node_detail(
        f"knowledge_item:{reviewed['item']['knowledgeItemId']}",
        agent_id=knowledge_env["member"]["agentId"],
    )
    outsider_detail = memory_graph_service.get_memory_knowledge_graph_node_detail(
        f"team:{knowledge_env['team']['teamId']}",
        agent_id=knowledge_env["outsider"]["agentId"],
    )

    assert "NODE DETAIL FORMAL KNOWLEDGE BODY" not in str(graph)
    assert member_detail is not None
    assert member_detail["operatingBoundary"]["fullContentIncluded"] is True
    assert member_detail["summaryCounts"]["contentItemCount"] == 1
    assert member_detail["contentItems"][0]["content"] == "NODE DETAIL FORMAL KNOWLEDGE BODY"
    assert member_detail["contentItems"][0]["fullContentIncluded"] is True
    assert item_detail is not None
    assert item_detail["contentItems"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]
    assert item_detail["contentItems"][0]["content"] == "NODE DETAIL FORMAL KNOWLEDGE BODY"
    assert outsider_detail is None


def test_memory_knowledge_graph_expands_official_research_trace_on_include(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="agent_authored",
        source_ref={"agentId": knowledge_env["member"]["agentId"]},
        title="Official graph source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Official graph item",
        summary="Trace summary.",
        content="OFFICIAL GRAPH BODY SHOULD NOT LEAK",
        tags=["challenge-cup"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    team_knowledge_service.update_knowledge_item_metadata(
        knowledge_env["base"]["knowledgeBaseId"],
        reviewed["item"]["knowledgeItemId"],
        actor_agent_id=knowledge_env["lead"]["agentId"],
        metadata_patch={
            "officialResearchGraph": {
                "status": "synced",
                "graphKind": "formal_research_trace",
                "summary": {"edgeCount": 2},
                "edges": [
                    {
                        "sourceId": "paper-note-1",
                        "sourceType": "paper_note",
                        "targetId": reviewed["item"]["knowledgeItemId"],
                        "targetType": "knowledge_item",
                        "relation": "supports",
                        "edgeState": "official_synced",
                    },
                    {
                        "sourceId": "hypothesis-1",
                        "sourceType": "algorithm_hypothesis",
                        "targetId": reviewed["item"]["knowledgeItemId"],
                        "targetType": "knowledge_item",
                        "relation": "inspires",
                        "edgeState": "official_synced",
                    },
                ],
            }
        },
    )

    default_graph = memory_graph_service.get_memory_knowledge_graph(agent_id=knowledge_env["member"]["agentId"])
    expanded_graph = memory_graph_service.get_memory_knowledge_graph(
        agent_id=knowledge_env["member"]["agentId"],
        include="officialResearchGraph",
    )
    expanded_text = str(expanded_graph)
    node_types = {node["type"] for node in expanded_graph["nodes"]}
    edge_types = {edge["type"] for edge in expanded_graph["edges"]}

    assert default_graph["summary"]["nodeTypeCounts"].get("knowledge_item", 0) == 0
    assert {"knowledge_base", "knowledge_item", "official_research_ref"}.issubset(node_types)
    assert {"team_has_knowledge_base", "knowledge_base_has_item", "official_supports", "official_inspires"}.issubset(edge_types)
    assert any(node["metadata"].get("sourceId") == "paper-note-1" for node in expanded_graph["nodes"])
    assert reviewed["item"]["knowledgeItemId"] in expanded_text
    assert "OFFICIAL GRAPH BODY SHOULD NOT LEAK" not in expanded_text


def test_memory_knowledge_graph_honors_team_knowledge_acl(knowledge_env):
    team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="ACL source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Visible only to members",
        content="hidden body",
    )

    member_graph = memory_graph_service.get_memory_knowledge_graph(agent_id=knowledge_env["member"]["agentId"])
    outsider_graph = memory_graph_service.get_memory_knowledge_graph(agent_id=knowledge_env["outsider"]["agentId"])

    assert any(
        node["type"] == "team" and node["metadata"]["teamId"] == knowledge_env["team"]["teamId"]
        for node in member_graph["nodes"]
    )
    assert not any(
        node["type"] == "team" and node["metadata"].get("teamId") == knowledge_env["team"]["teamId"]
        for node in outsider_graph["nodes"]
    )


def test_memory_knowledge_graph_uses_lightweight_team_graph_references(knowledge_env, monkeypatch):
    def fail_compact(*, include_archived: bool = False):
        raise AssertionError("memory graph must not hydrate compact team chat rooms")

    monkeypatch.setattr(team_service, "list_teams_compact", fail_compact)

    graph = memory_graph_service.get_memory_knowledge_graph(agent_id=knowledge_env["member"]["agentId"])

    assert any(
        node["type"] == "team" and node["metadata"]["teamId"] == knowledge_env["team"]["teamId"]
        for node in graph["nodes"]
    )


def test_steward_recommendations_are_read_only_actions(knowledge_env):
    orphan_source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Source without proposal",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Recommendation proposal source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Proposal needing review",
        content="Reviewer should inspect this candidate.",
    )
    applied = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    team_knowledge_service.create_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggested_by_agent_id=knowledge_env["lead"]["agentId"],
        target_type="knowledge_item",
        knowledge_item_id=applied["item"]["knowledgeItemId"],
        importance_level="critical",
        confidence=0.9,
        stability="stable",
        review_priority="urgent",
        marking_reason="Core knowledge should be marked critical.",
    )

    payload = team_knowledge_service.list_knowledge_steward_recommendations(agent_id=knowledge_env["lead"]["agentId"])

    actions = {item["recommendedAction"] for item in payload["recommendations"]}
    assert "draft_refinement_proposal" in actions
    assert "review_rating_suggestion" in actions
    assert any(item["targetId"] == orphan_source["sourceArtifactId"] for item in payload["recommendations"])
    assert payload["operatingBoundary"]["recommendationsOnly"] is True
    assert payload["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert payload["summary"]["proposalDraftCount"] == 1
    assert payload["summary"]["ratingReviewCount"] == 1


def test_steward_workbench_groups_actions_without_applying_knowledge(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Workbench source without proposal",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Workbench proposal source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Workbench proposal",
        content="Workbench should show this proposal without applying it.",
    )

    payload = team_knowledge_service.get_knowledge_steward_workbench(agent_id=knowledge_env["lead"]["agentId"], limit=5)

    assert payload["operatingBoundary"]["recommendationsOnly"] is True
    assert payload["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert payload["summary"]["openTaskCount"] >= 2
    assert {stage["stageId"] for stage in payload["stages"]} == {"source_to_proposal", "proposal_review", "rating_review"}
    source_stage = next(stage for stage in payload["stages"] if stage["stageId"] == "source_to_proposal")
    proposal_stage = next(stage for stage in payload["stages"] if stage["stageId"] == "proposal_review")
    assert any(item["targetId"] == source["sourceArtifactId"] for item in source_stage["items"])
    assert any(item["targetId"] == proposal["proposalId"] for item in proposal_stage["items"])
    assert payload["acceptanceChecklist"][0]["required"] is True
    assert not team_knowledge_service.list_knowledge_items(knowledge_env["base"]["knowledgeBaseId"], agent_id=knowledge_env["lead"]["agentId"])["items"]


def test_ingestion_package_preserves_team_chat_room_guard(knowledge_env):
    with pytest.raises(team_knowledge_service.TeamKnowledgeError, match="linked chat room"):
        central_source = _promote_central_source(
            owner_type="team",
            owner_id=knowledge_env["team"]["teamId"],
            actor_agent_id=knowledge_env["member"]["agentId"],
            reviewer_agent_id=knowledge_env["lead"]["agentId"],
            source_type="team_chat_refinement",
            source_ref={"roomId": "room-not-linked", "messageRange": {"from": 1, "to": 4}},
            title="Unlinked chat source",
        )
        team_knowledge_service.create_ingestion_package(
            knowledge_env["base"]["knowledgeBaseId"],
            source_type="team_chat_refinement",
            source_ref={"roomId": "room-not-linked", "messageRange": {"from": 1, "to": 4}},
            excerpt="Unlinked chat room must be rejected.",
            proposed_by_agent_id=knowledge_env["member"]["agentId"],
            central_source_id=central_source["centralSourceId"],
        )

    linked_central_source = _promote_central_source(
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="team_chat_refinement",
        source_ref={"roomId": knowledge_env["team"]["linkedChatRoomId"], "messageRange": {"from": 1, "to": 4}},
        title="Linked chat source",
    )
    package = team_knowledge_service.create_ingestion_package(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="team_chat_refinement",
        source_ref={"roomId": knowledge_env["team"]["linkedChatRoomId"], "messageRange": {"from": 1, "to": 4}},
        excerpt="Linked room decisions can become pending proposals.",
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        central_source_id=linked_central_source["centralSourceId"],
    )

    assert package["sourceArtifact"]["sourceRef"]["roomId"] == knowledge_env["team"]["linkedChatRoomId"]
    assert package["proposal"]["status"] == "pending"


def test_semantic_search_matches_token_overlap_without_exact_substring(knowledge_env):
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Planner cadence source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Planner cadence",
        content="Governance planner health signals should be visible before reviewer action.",
        tags=["ops"],
    )
    team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    exact = team_knowledge_service.search_knowledge_items(
        agent_id=knowledge_env["member"]["agentId"],
        knowledge_base_id=knowledge_env["base"]["knowledgeBaseId"],
        query="health governance missing",
        search_mode="exact",
    )
    semantic = team_knowledge_service.search_knowledge_items(
        agent_id=knowledge_env["member"]["agentId"],
        knowledge_base_id=knowledge_env["base"]["knowledgeBaseId"],
        query="health governance missing",
        search_mode="semantic",
    )

    assert exact["summary"]["resultCount"] == 0
    assert semantic["summary"]["resultCount"] == 1
    assert semantic["results"][0]["semanticScore"] > 0
    assert semantic["results"][0]["matchReason"] == "token_overlap"


def test_operations_health_reports_orphan_pending_and_unrated_items(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Orphan source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Pending health source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Pending health proposal",
        content="Pending proposal should be reported.",
    )
    applied = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    pending_rating = team_knowledge_service.create_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggested_by_agent_id=knowledge_env["lead"]["agentId"],
        target_type="knowledge_item",
        knowledge_item_id=applied["item"]["knowledgeItemId"],
        importance_level="high",
        stability="stable",
        review_priority="elevated",
    )

    health = team_knowledge_service.get_knowledge_operations_health(agent_id=knowledge_env["member"]["agentId"])

    assert health["summary"]["knowledgeBaseCount"] == 1
    assert health["summary"]["orphanSourceCount"] == 1
    assert health["summary"]["pendingRatingSuggestionCount"] == 1
    assert health["summary"]["unratedItemCount"] == 1
    finding_types = {finding["findingType"] for finding in health["findings"]}
    assert {"orphan_sources", "pending_rating_suggestions", "unrated_items"}.issubset(finding_types)
    assert source["sourceArtifactId"] in health["knowledgeBases"][0]["nextReviewTargetIds"]
    assert pending_rating["suggestionId"] in health["knowledgeBases"][0]["nextReviewTargetIds"]


def test_governance_plan_is_read_only_and_links_tools(knowledge_env):
    team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Plan source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Plan proposal",
        content="Governance plan should recommend review without applying.",
    )

    plan = team_knowledge_service.get_knowledge_governance_plan(agent_id=knowledge_env["lead"]["agentId"], limit=4)

    assert plan["mode"] == "recommendations_only"
    assert plan["operatingBoundary"]["planOnly"] is True
    assert plan["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert plan["operatingBoundary"]["canDeleteKnowledge"] is False
    assert plan["actions"]
    assert plan["actions"][0]["mutatesFormalKnowledge"] is False
    assert plan["actions"][0]["recommendedTool"] == "knowledge_governance_tasks_tool"


# ---------------------------------------------------------------------------
# Public structure curation catalog (workspace/knowledge/public) — plan A.8
# ---------------------------------------------------------------------------


def _public_project_root(team_knowledge_service):
    import pathlib

    return pathlib.Path(str(team_knowledge_service.PROJECT_ROOT))


def _write_project_file(project_root, relative, text):
    path = project_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_pin_card(card_id, *, locator, summary, title="Pin card", when_to_use="Use when needed", partition="standards", source_type="git_path", steward_weight=0, freshness_policy="steward_review", kind="pin"):
    return {
        "cardId": card_id,
        "kind": kind,
        "partition": partition,
        "title": title,
        "whenToUse": when_to_use,
        "summary": summary,
        "stewardWeight": steward_weight,
        "visibility": "agent_visible",
        "source": {"type": source_type, "locator": locator},
        "freshnessPolicy": freshness_policy,
    }


def test_public_catalog_steward_pin_becomes_stale_hidden_after_source_change(knowledge_env):
    project_root = _public_project_root(team_knowledge_service)
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    _write_project_file(project_root, "docs/pin-source.md", "original bytes v1")
    card = team_knowledge_service.upsert_public_card(
        _make_pin_card("pin-docs-1", locator="docs/pin-source.md", summary="Stable pin summary."),
        actor_agent_id=steward_id,
    )
    assert card["visibility"] == "agent_visible"
    assert card["freshness"]["status"] == "current"

    _write_project_file(project_root, "docs/pin-source.md", "changed bytes v2")
    refreshed = team_knowledge_service.refresh_public_catalog_freshness(actor_agent_id=steward_id)
    assert "pin-docs-1" in refreshed["staleCardIds"]

    catalog = team_knowledge_service.get_public_catalog(agent_id=knowledge_env["member"]["agentId"], internal=True)
    stored = next(item for item in catalog["cards"] if item["cardId"] == "pin-docs-1")
    assert stored["visibility"] == "hidden"
    assert stored["freshness"]["status"] == "stale"

    hits = team_knowledge_service.search_public_catalog(query="Stable pin summary", agent_id=knowledge_env["member"]["agentId"])
    assert all(result["cardId"] != "pin-docs-1" for result in hits["results"])


def test_public_proposal_acceptance_does_not_append_item_bodies(knowledge_env):
    project_root = _public_project_root(team_knowledge_service)
    items_path = project_root / "workspace" / "teams" / knowledge_env["team"]["teamId"] / "knowledge" / "items.jsonl"
    items_path.parent.mkdir(parents=True, exist_ok=True)
    items_path.write_text("", encoding="utf-8")
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID

    proposal = team_knowledge_service.submit_public_proposal(
        {
            "partition": "experience",
            "title": "Experience proposal",
            "summary": "Proposed experience summary.",
            "originRef": {"layer": "team", "ownerId": knowledge_env["team"]["teamId"], "itemId": "team-item-1"},
        },
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
    )
    resolved = team_knowledge_service.resolve_public_proposal(
        proposal["proposalId"],
        status="accepted",
        actor_agent_id=steward_id,
    )
    proposals = team_knowledge_service.list_public_proposals(internal=True)

    assert resolved["status"] == "accepted"
    assert proposals["summary"]["pendingProposalCount"] == 0
    assert items_path.read_text(encoding="utf-8") == ""
    team_items = team_knowledge_service.list_knowledge_items(
        knowledge_env["base"]["knowledgeBaseId"],
        agent_id=knowledge_env["member"]["agentId"],
    )
    assert team_items["summary"]["itemCount"] == 0


def test_startup_structure_block_respects_card_and_char_budget(knowledge_env):
    project_root = _public_project_root(team_knowledge_service)
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    for index in range(30):
        _write_project_file(project_root, f"docs/card-{index}.md", f"card body {index}")
        team_knowledge_service.upsert_public_card(
            _make_pin_card(
                f"pin-budget-{index}",
                locator=f"docs/card-{index}.md",
                summary=f"Budget card {index} summary.",
                title=f"Budget Card {index}",
                steward_weight=index,
            ),
            actor_agent_id=steward_id,
        )

    result = team_knowledge_service.build_startup_structure_block(agent_id=knowledge_env["member"]["agentId"])

    assert len(result["cards"]) <= team_knowledge_service.STARTUP_STRUCTURE_MAX_CARDS
    assert len(result["block"]) <= team_knowledge_service.STARTUP_STRUCTURE_MAX_CHARS
    assert result["budget"]["included"] == len(result["cards"])
    assert result["budget"]["omitted"] >= 0
    assert "excludedStartup" in result["budget"]
    assert f"included={result['budget']['included']}" in result["block"]


def test_public_catalog_hit_dto_has_no_content_and_open_fails_without_summary_fallback(knowledge_env):
    project_root = _public_project_root(team_knowledge_service)
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    _write_project_file(project_root, "docs/hit-source.md", "Hit source body")
    team_knowledge_service.upsert_public_card(
        _make_pin_card("pin-hit-1", locator="docs/hit-source.md", summary="Hit summary text", title="Hit Card"),
        actor_agent_id=steward_id,
    )

    hits = team_knowledge_service.search_public_catalog(query="Hit summary text", agent_id=knowledge_env["member"]["agentId"])
    assert hits["results"]
    hit = hits["results"][0]
    assert hit["resultType"] == "public_catalog_card"
    assert "content" not in hit
    assert "excerpt" not in hit
    assert hit["openRequired"] is True

    opened = team_knowledge_service.open_public_card("pin-hit-1", agent_id=knowledge_env["member"]["agentId"])
    assert opened["ok"] is True
    assert opened["content"] == "Hit source body"

    team_knowledge_service.upsert_public_card(
        _make_pin_card("pin-escape-1", locator="../outside.md", summary="Escape summary", title="Escape Card"),
        actor_agent_id=steward_id,
    )
    with pytest.raises(team_knowledge_service.PublicCatalogSourceUnavailableError) as exc_info:
        team_knowledge_service.open_public_card("pin-escape-1", agent_id=knowledge_env["member"]["agentId"])
    assert exc_info.value.reason == "forbidden"
    assert "Escape summary" not in str(exc_info.value)


def test_archived_public_card_stays_in_structure_and_has_no_delete_api(knowledge_env):
    project_root = _public_project_root(team_knowledge_service)
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    _write_project_file(project_root, "docs/archive-me.md", "archive body")
    team_knowledge_service.upsert_public_card(
        _make_pin_card("pin-archive-1", locator="docs/archive-me.md", summary="To archive", title="Archive Me"),
        actor_agent_id=steward_id,
    )

    archived = team_knowledge_service.archive_public_card("pin-archive-1", reason="superseded", actor_agent_id=steward_id)

    assert archived["visibility"] == "archived"
    assert archived["archivedAt"]
    assert archived["archivedReason"] == "superseded"
    catalog = team_knowledge_service.get_public_catalog(agent_id=knowledge_env["member"]["agentId"], internal=True)
    assert any(item["cardId"] == "pin-archive-1" for item in catalog["cards"])
    assert not hasattr(team_knowledge_service, "delete_public_card")
    assert not hasattr(team_knowledge_service, "remove_public_card")
    agent_view = team_knowledge_service.get_public_catalog(agent_id=knowledge_env["member"]["agentId"])
    assert all(item["cardId"] != "pin-archive-1" for item in agent_view["cards"])


def test_duplicate_locator_conflict_hides_both_pins_until_resolved(knowledge_env):
    project_root = _public_project_root(team_knowledge_service)
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    _write_project_file(project_root, "docs/conflict-source.md", "conflict body")
    team_knowledge_service.upsert_public_card(
        _make_pin_card("pin-conflict-a", locator="docs/conflict-source.md", summary="Summary A", title="Conflict A"),
        actor_agent_id=steward_id,
    )
    team_knowledge_service.upsert_public_card(
        _make_pin_card("pin-conflict-b", locator="docs/conflict-source.md", summary="Summary B differs", title="Conflict B"),
        actor_agent_id=steward_id,
    )

    refreshed = team_knowledge_service.refresh_public_catalog_freshness(actor_agent_id=steward_id)
    assert refreshed["conflictEventCount"] >= 1

    events = team_knowledge_service.list_catalog_queue_events(status="open")
    conflicts = [event for event in events["events"] if event["queueKind"] == "conflict"]
    assert conflicts
    assert "pin-conflict-a" in conflicts[0]["cardIds"]
    assert "pin-conflict-b" in conflicts[0]["cardIds"]

    hits = team_knowledge_service.search_public_catalog(query="Summary A", agent_id=knowledge_env["member"]["agentId"])
    assert all(result["cardId"] not in {"pin-conflict-a", "pin-conflict-b"} for result in hits["results"])
    block = team_knowledge_service.build_startup_structure_block(agent_id=knowledge_env["member"]["agentId"])
    assert all(card["cardId"] not in {"pin-conflict-a", "pin-conflict-b"} for card in block["cards"])

    resolved = team_knowledge_service.resolve_catalog_queue_event(
        conflicts[0]["queueEventId"],
        resolution="keep_a",
        actor_agent_id=steward_id,
    )
    assert resolved["status"] == "resolved"
    catalog = team_knowledge_service.get_public_catalog(agent_id=knowledge_env["member"]["agentId"], internal=True)
    keeper = next(item for item in catalog["cards"] if item["cardId"] == "pin-conflict-a")
    other = next(item for item in catalog["cards"] if item["cardId"] == "pin-conflict-b")
    assert keeper["visibility"] == "agent_visible"
    assert other["visibility"] == "hidden"


def test_startup_block_excludes_prompt_manager_and_agent_directory_sources(knowledge_env):
    project_root = _public_project_root(team_knowledge_service)
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    _write_project_file(project_root, "AGENTS.md", "Project rules body")
    _write_project_file(project_root, "core/core_prompt/COMMON.md", "Common discipline body")
    _write_project_file(project_root, "docs/keep-source.md", "keep body")
    team_knowledge_service.upsert_public_card(
        _make_pin_card("pin-agents-1", locator="AGENTS.md", summary="AGENTS card", title="AGENTS Rules Card"),
        actor_agent_id=steward_id,
    )
    team_knowledge_service.upsert_public_card(
        _make_pin_card("pin-common-1", locator="core/core_prompt/COMMON.md", summary="COMMON card", title="COMMON Card"),
        actor_agent_id=steward_id,
    )
    team_knowledge_service.upsert_public_card(
        _make_pin_card(
            "pin-directory-1",
            locator=knowledge_env["member"]["agentId"],
            summary="Directory card",
            title="Directory Card",
            source_type="agent_directory",
            partition="agents",
        ),
        actor_agent_id=steward_id,
    )
    team_knowledge_service.upsert_public_card(
        _make_pin_card("pin-keep-1", locator="docs/keep-source.md", summary="Keep card", title="Keep Card"),
        actor_agent_id=steward_id,
    )

    block = team_knowledge_service.build_startup_structure_block(agent_id=knowledge_env["member"]["agentId"])
    card_locs = [card["locator"] for card in block["cards"]]
    locator_text = " ".join(card_locs)

    assert "AGENTS.md" not in locator_text
    assert "core/core_prompt" not in locator_text
    assert knowledge_env["member"]["agentId"] not in locator_text
    assert block["budget"]["excludedStartup"] >= 3
    assert "docs/keep-source.md" in locator_text

    hits = team_knowledge_service.search_public_catalog(query="AGENTS Rules Card", agent_id=knowledge_env["member"]["agentId"])
    assert any(result["cardId"] == "pin-agents-1" for result in hits["results"])


def test_catalog_haystack_is_card_fields_only_not_source_bodies(knowledge_env):
    project_root = _public_project_root(team_knowledge_service)
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    _write_project_file(project_root, "AGENTS.md", "PROJECT-ONLY-MARKER_XYZZY phrase inside AGENTS body")
    team_knowledge_service.upsert_public_card(
        _make_pin_card("pin-agents-body-1", locator="AGENTS.md", summary="Rules pointer", title="Project Rules"),
        actor_agent_id=steward_id,
    )

    hits = team_knowledge_service.search_public_catalog(query="PROJECT-ONLY-MARKER_XYZZY", agent_id=knowledge_env["member"]["agentId"])
    assert hits["summary"]["resultCount"] == 0
    hits_by_title = team_knowledge_service.search_public_catalog(query="Project Rules", agent_id=knowledge_env["member"]["agentId"])
    assert any(result["cardId"] == "pin-agents-body-1" for result in hits_by_title["results"])


def test_escaping_locator_is_forbidden_and_freshness_task_appears_in_governance(knowledge_env):
    project_root = _public_project_root(team_knowledge_service)
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    team_knowledge_service.upsert_public_card(
        _make_pin_card("pin-escape-2", locator="../secret.md", summary="Escape summary", title="Escape Card"),
        actor_agent_id=steward_id,
    )
    team_knowledge_service.upsert_public_card(
        _make_pin_card("pin-abs-1", locator="/etc/passwd", summary="Absolute summary", title="Absolute Card"),
        actor_agent_id=steward_id,
    )

    with pytest.raises(team_knowledge_service.PublicCatalogSourceUnavailableError) as exc_info:
        team_knowledge_service.open_public_card("pin-escape-2", agent_id=knowledge_env["member"]["agentId"])
    assert exc_info.value.reason == "forbidden"

    refreshed = team_knowledge_service.refresh_public_catalog_freshness(actor_agent_id=steward_id)
    assert "pin-escape-2" in refreshed["missingCardIds"]
    assert "pin-abs-1" in refreshed["missingCardIds"]

    tasks = team_knowledge_service.list_knowledge_governance_tasks(agent_id=steward_id)
    freshness_tasks = [task for task in tasks["tasks"] if task["taskType"] == "catalog_freshness" and task["status"] == "open"]
    assert freshness_tasks
    assert tasks["summary"]["catalogFreshnessCount"] >= 2


def test_ensure_owner_source_review_grant_is_idempotent_and_preserves_existing_stewards(knowledge_env):
    team_id = knowledge_env["team"]["teamId"]
    lead_id = knowledge_env["lead"]["agentId"]
    member_id = knowledge_env["member"]["agentId"]
    outsider_id = knowledge_env["outsider"]["agentId"]

    seeded = team_knowledge_service.update_owner_source_governance(
        "team",
        team_id,
        local_steward_agent_ids=[member_id],
        actor_agent_id=lead_id,
    )
    assert seeded["localStewardAgentIds"] == [member_id]

    first = team_knowledge_service.ensure_owner_source_review_grant("team", team_id, outsider_id)
    assert first["localStewardAgentIds"] == [member_id, outsider_id]
    assert first["teamId"] == team_id

    second = team_knowledge_service.ensure_owner_source_review_grant("team", team_id, outsider_id)
    assert second["localStewardAgentIds"] == [member_id, outsider_id]
    assert second["updatedAt"] == first["updatedAt"]


def test_owner_source_review_blocked_until_ensure_grant_allows_non_member_steward(knowledge_env):
    team_id = knowledge_env["team"]["teamId"]
    member_id = knowledge_env["member"]["agentId"]
    steward_id = knowledge_env["outsider"]["agentId"]

    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        team_id,
        source_type="manual_user_entry",
        source_ref={"note": "auto ingestion source"},
        original_content="Auto ingestion source content captured for knowledge expansion.",
        original_filename="auto-source.txt",
        title="Auto ingestion source",
        summary="Captured by the automated knowledge-ingestion chain.",
        actor_agent_id=member_id,
    )

    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.review_owner_inbox_source(
            "team",
            team_id,
            inbox_source["inboxSourceId"],
            decision="accepted",
            reviewed_by_agent_id=steward_id,
        )

    granted = team_knowledge_service.ensure_owner_source_review_grant("team", team_id, steward_id)
    assert granted["localStewardAgentIds"] == [steward_id]

    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        team_id,
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=steward_id,
    )
    assert reviewed["source"]["status"] == "accepted"
    assert reviewed["centralSource"]["centralSourceId"]
