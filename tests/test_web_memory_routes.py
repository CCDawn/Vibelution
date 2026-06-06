import json
import sqlite3

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, memory_graph_service, memory_service, runtime_scene_service, team_knowledge_service, team_service


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_memory_overview_endpoint_groups_agent_memory_sources(tmp_path, monkeypatch):
    project_memory = tmp_path / ".docs" / "project-memory"
    lanes_dir = project_memory / "lanes"
    lanes_dir.mkdir(parents=True)
    memory_payload = {
        "project": {"name": "Vibelution"},
        "summary": {"currentPhase": "phase", "focus": "memory overview"},
        "lanes": [{"id": "web-workbench-surface"}],
        "recentUpdates": [{"title": "one"}],
    }
    (project_memory / "memory.json").write_text(json.dumps(memory_payload, ensure_ascii=False), encoding="utf-8")
    (project_memory / "INDEX.md").write_text("| 类目 | 数量 |\n|---|---:|\n| 最近更新 | 2 |\n", encoding="utf-8")
    (project_memory / "profile.json").write_text('{"density":"compact"}', encoding="utf-8")
    (project_memory / "inbox.json").write_text("[]", encoding="utf-8")
    (lanes_dir / "web-workbench-surface.json").write_text(
        json.dumps(
            {"title": "Web 工作台", "focus": "memory page", "recentUpdates": [{"title": "lane update"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_memory / "overview.html").write_text("<html>memory</html>", encoding="utf-8")
    (tmp_path / "PROJECT_MEMORY.html").write_text("<html>root</html>", encoding="utf-8")

    runtime_memory = tmp_path / "workspace" / "memory"
    runtime_memory.mkdir(parents=True)
    (runtime_memory / "memory.json").write_text('{"core_wisdom":["keep focus"]}', encoding="utf-8")
    (runtime_memory / "tasks.json").write_text('{"tasks":[]}', encoding="utf-8")

    prompt_dir = tmp_path / "workspace" / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "STATE_MEMORY.md").write_text("Current prompt memory.", encoding="utf-8")
    (prompt_dir / "DYNAMIC.md").write_text("Dynamic prompt note.", encoding="utf-8")

    db_path = tmp_path / "workspace" / "agent_brain.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE LongTermMemory (id INTEGER PRIMARY KEY, content TEXT, updated_at TEXT)")
        conn.execute(
            "INSERT INTO LongTermMemory (content, updated_at) VALUES (?, ?)",
            ("lesson", "2026-05-23T10:00:00Z"),
        )
        conn.execute("CREATE TABLE EvolutionTransaction (id INTEGER PRIMARY KEY, status TEXT, updated_at TEXT)")
        conn.execute(
            "INSERT INTO EvolutionTransaction (status, updated_at) VALUES (?, ?)",
            ("closed", "2026-05-23T11:00:00Z"),
        )

    (tmp_path / "workspace" / "chat").mkdir(parents=True)
    (tmp_path / "workspace" / "chat" / "chat_state.json").write_text('{"sessions":[]}', encoding="utf-8")
    session_memory = tmp_path / "workspace" / "sessions" / "session-1" / "memory"
    session_memory.mkdir(parents=True)
    (session_memory / "memory.json").write_text('{"session":"one"}', encoding="utf-8")
    research_root = tmp_path / "workspace" / "research"
    research_root.mkdir(parents=True)
    (research_root / "knowledge_base.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "updatedAt": "2026-05-26T12:00:00Z",
                "entries": [
                    {
                        "knowledgeId": "rk-one",
                        "kind": "paper",
                        "title": "AI Scientist source",
                        "lastSeenAt": "2026-05-26T12:00:00Z",
                        "hitCount": 2,
                    }
                ],
                "claims": [{"recordId": "rkc-one"}],
                "evidence": [{"recordId": "rke-one"}],
                "gaps": [{"recordId": "rkg-one"}],
                "agentEvolutionMemory": {
                    "experienceRefs": ["exp-one"],
                    "reflectionRefs": [],
                    "candidateRefs": [],
                    "strategyNotes": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "workspace" / "gym").mkdir(parents=True)
    (tmp_path / "workspace" / "gym" / "active_promotions.json").write_text("[]", encoding="utf-8")
    supervised_root = tmp_path / "workspace" / "supervised_evolution"
    (supervised_root / "decisions").mkdir(parents=True)
    (supervised_root / "workbench_state.json").write_text('{"dataset":"demo"}', encoding="utf-8")
    (supervised_root / "history.jsonl").write_text('{"run":"one"}\n', encoding="utf-8")
    (supervised_root / "decisions" / "decision.json").write_text('{"decision":"hold"}', encoding="utf-8")
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260523T100000Z__memory"
    scene_dir.mkdir(parents=True)
    (scene_dir / "manifest.json").write_text('{"title":"memory run","status":"stopped"}', encoding="utf-8")

    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Knowledge Agent", direct_session_id="session-knowledge")
    team = team_service.create_team(name="Knowledge Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Team Knowledge",
        actor_agent_id=agent["agentId"],
    )
    team_knowledge_service.create_refinement_proposal(
        knowledge_base["knowledgeBaseId"],
        source_artifact_ids=[],
        proposed_by_agent_id=agent["agentId"],
        title="Pending knowledge",
        content="This candidate should stay out of memory overview content.",
    )

    response = client.get("/api/memory/overview")

    assert response.status_code == 200, response.json()
    payload = response.json()
    sections = {section["id"]: section for section in payload["sections"]}
    assert payload["schemaVersion"] == 3
    assert payload["projectRoot"] == str(tmp_path.resolve())
    assert payload["summary"]["sectionCount"] == 12
    assert set(sections) == {
        "user-managed-memory",
        "project-memory",
        "runtime-memory",
        "prompt-memory",
        "workspace-database",
        "research-memory",
        "team-knowledge",
        "git-memory",
        "chat-session-memory",
        "self-evolution-memory",
        "supervised-evolution-memory",
        "runtime-scene-evidence",
    }
    assert not any("计数不一致" in item for item in payload["summary"]["warnings"])
    assert sections["user-managed-memory"]["sourcePath"] == "workspace/memory/user_memory_overrides.json"
    assert sections["user-managed-memory"]["sourceApi"] == "/api/memory/items"
    prompt_items = {item["title"]: item for item in sections["prompt-memory"]["items"]}
    assert prompt_items["STATE_MEMORY.md"]["agentVisible"] is True
    assert prompt_items["STATE_MEMORY.md"]["inPrompt"] is True
    assert prompt_items["STATE_MEMORY.md"]["visibilityClass"] == "prompt"
    assert prompt_items["STATE_MEMORY.md"]["channels"] == ["conversation"]
    assert prompt_items["STATE_MEMORY.md"]["managedState"]["editable"] is True
    assert prompt_items["STATE_MEMORY.md"]["managedState"]["overridden"] is False
    assert prompt_items["STATE_MEMORY.md"]["content"] == "Current prompt memory."
    assert prompt_items["DYNAMIC.md"]["inPrompt"] is False
    assert prompt_items["DYNAMIC.md"]["visibilityClass"] == "agent_visible"
    assert prompt_items["DYNAMIC.md"]["channels"] == ["explicit_read"]
    git_items = {item["id"]: item for item in sections["git-memory"]["items"]}
    assert git_items["git-working-tree"]["agentVisible"] is True
    assert git_items["git-working-tree"]["inPrompt"] is True
    assert git_items["git-working-tree"]["visibilityClass"] == "prompt"
    assert git_items["git-working-tree"]["channels"] == ["conversation", "self_evolution"]
    assert "GIT_MEMORY" in sections["git-memory"]["agentVisibility"]
    sqlite_items = {item["id"]: item for item in sections["workspace-database"]["items"]}
    assert '"count": 1' in sqlite_items["sqlite-longtermmemory"]["content"]
    assert sqlite_items["sqlite-longtermmemory"]["channels"] == ["explicit_read"]
    research_items = {item["id"]: item for item in sections["research-memory"]["items"]}
    assert sections["research-memory"]["sourceApi"] == "/api/research/knowledge-base"
    assert research_items["research-knowledge-base"]["channels"] == ["research", "self_evolution", "explicit_read"]
    assert research_items["research-knowledge-base"]["agentVisible"] is True
    assert research_items["research-knowledge-base"]["inPrompt"] is False
    assert '"claimCount": 1' in research_items["research-knowledge-base"]["content"]
    assert "1 条论断" in research_items["research-knowledge-base"]["summary"]
    team_knowledge_items = {item["id"]: item for item in sections["team-knowledge"]["items"]}
    assert sections["team-knowledge"]["sourceApi"] == "/api/knowledge/overview"
    assert team_knowledge_items["team-knowledge-platform"]["agentVisible"] is True
    assert team_knowledge_items["team-knowledge-platform"]["inPrompt"] is False
    assert team_knowledge_items["team-knowledge-platform"]["channels"] == ["research", "explicit_read"]
    assert "Pending knowledge" not in team_knowledge_items["team-knowledge-platform"]["content"]
    assert '"pendingProposalCount": 1' in team_knowledge_items["team-knowledge-platform"]["content"]
    self_items = {item["id"]: item for item in sections["self-evolution-memory"]["items"]}
    assert self_items["self-evolution-transactions"]["channels"] == ["self_evolution"]
    supervised_items = {item["id"]: item for item in sections["supervised-evolution-memory"]["items"]}
    assert supervised_items["supervised-bundles"]["channels"] == ["supervised_evolution"]
    runtime_scene_items = {item["id"]: item for item in sections["runtime-scene-evidence"]["items"]}
    assert runtime_scene_items["runtime-scenes-index"]["visibilityClass"] == "prompt"
    assert runtime_scene_items["runtime-scenes-index"]["inPrompt"] is True
    assert runtime_scene_items["runtime-scenes-index"]["channels"] == [
        "conversation",
        "self_evolution",
        "supervised_evolution",
        "explicit_read",
    ]
    assert "RUNTIME_LOG_INDEX" in sections["runtime-scene-evidence"]["agentVisibility"]
    assert any("tools.memory_tools" in item["usedBy"] for item in sections["runtime-memory"]["items"])
    project_items = {item["title"]: item for item in sections["project-memory"]["items"]}
    assert project_items["overview.html"]["contentType"] == "html"
    assert project_items["overview.html"]["summary"].startswith("HTML 页面：")
    assert "<html" not in project_items["overview.html"]["summary"].lower()


def test_memory_knowledge_graph_endpoint_returns_read_only_project_structure(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_graph_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Graph Agent", direct_session_id="session-graph")
    team = team_service.create_team(name="Graph Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Graph Knowledge",
        actor_agent_id=agent["agentId"],
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_base["knowledgeBaseId"],
        source_artifact_ids=[],
        proposed_by_agent_id=agent["agentId"],
        title="Graph API proposal",
        content="GRAPH API BODY MUST STAY OUT",
    )
    team_knowledge_service.review_refinement_proposal(
        knowledge_base["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=agent["agentId"],
    )

    response = client.get("/api/memory/knowledge-graph", params={"agentId": agent["agentId"]})
    payload = response.json()

    assert response.status_code == 200
    assert payload["operatingBoundary"]["readOnly"] is True
    assert payload["operatingBoundary"]["layoutWorker"] is True
    assert payload["operatingBoundary"]["fullContentIncluded"] is False
    assert payload["summary"]["nodeTypeCounts"]["agent"] >= 1
    assert payload["summary"]["nodeTypeCounts"].get("knowledge_base", 0) == 0
    assert payload["summary"]["nodeTypeCounts"].get("knowledge_item", 0) == 0
    team_node = next(node for node in payload["nodes"] if node["type"] == "team")
    agent_node = next(node for node in payload["nodes"] if node["type"] == "agent" and node["metadata"]["agentId"] == agent["agentId"])
    assert team_node["childNodeIds"] == [agent_node["id"]]
    assert team_node["responsibilityQuestion"]
    assert agent_node["visual"]["size"] == "leaf"
    assert team_node["contentItems"][0]["title"] == "Graph API proposal"
    assert agent_node["contentItems"] == []
    assert "GRAPH API BODY MUST STAY OUT" not in str(payload)


def test_memory_knowledge_graph_node_detail_endpoint_returns_selected_node_content(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_graph_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Graph Detail Agent", direct_session_id="session-graph-detail")
    outsider = agent_directory_service.create_agent_instance(display_name="Graph Detail Outsider")
    team = team_service.create_team(name="Graph Detail Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Graph Detail Knowledge",
        actor_agent_id=agent["agentId"],
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_base["knowledgeBaseId"],
        source_artifact_ids=[],
        proposed_by_agent_id=agent["agentId"],
        title="Graph detail proposal",
        content="GRAPH DETAIL API BODY SHOULD LOAD",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_base["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=agent["agentId"],
    )

    graph_response = client.get("/api/memory/knowledge-graph", params={"agentId": agent["agentId"]})
    detail_response = client.get(
        "/api/memory/knowledge-graph/node-detail",
        params={"nodeId": f"knowledge_item:{reviewed['item']['knowledgeItemId']}", "agentId": agent["agentId"]},
    )
    empty_actor_response = client.get(
        "/api/memory/knowledge-graph/node-detail",
        params={"nodeId": f"knowledge_item:{reviewed['item']['knowledgeItemId']}"},
    )
    outsider_response = client.get(
        "/api/memory/knowledge-graph/node-detail",
        params={"nodeId": f"team:{team['teamId']}", "agentId": outsider["agentId"]},
    )
    missing_response = client.get(
        "/api/memory/knowledge-graph/node-detail",
        params={"nodeId": "knowledge_base:not-found", "agentId": agent["agentId"]},
    )

    assert graph_response.status_code == 200
    assert "GRAPH DETAIL API BODY SHOULD LOAD" not in str(graph_response.json())
    assert detail_response.status_code == 200, detail_response.json()
    detail_payload = detail_response.json()
    assert detail_payload["mode"] == "read_only_project_memory_graph_node_detail"
    assert detail_payload["operatingBoundary"]["fullContentIncluded"] is True
    assert detail_payload["contentItems"][0]["content"] == "GRAPH DETAIL API BODY SHOULD LOAD"
    assert detail_payload["contentItems"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]
    assert empty_actor_response.status_code == 422
    assert outsider_response.status_code == 200, outsider_response.json()
    assert outsider_response.json()["contentItems"] == []
    assert missing_response.status_code == 404


def test_memory_knowledge_graph_uses_owner_scoped_knowledge_node_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_graph_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    original_new_event_id = team_knowledge_service._new_event_id

    def fake_new_event_id(prefix: str) -> str:
        if prefix == "kitem":
            return "kitem-shared-leaf"
        return original_new_event_id(prefix)

    monkeypatch.setattr(team_knowledge_service, "_new_event_id", fake_new_event_id)
    first_agent = agent_directory_service.create_agent_instance(display_name="Graph Owner One")
    second_agent = agent_directory_service.create_agent_instance(display_name="Graph Owner Two")
    graph_viewer = agent_directory_service.create_agent_instance(display_name="Graph Cross-Team Viewer")
    first_team = team_service.create_team(name="Graph Owner Team One", members=[{"agentId": first_agent["agentId"], "role": "lead"}])
    second_team = team_service.create_team(name="Graph Owner Team Two", members=[{"agentId": second_agent["agentId"], "role": "lead"}])
    first_base = team_knowledge_service.create_knowledge_base(
        first_team["teamId"],
        name="Shared Graph KB",
        actor_agent_id=first_agent["agentId"],
        acl={"grants": {"read": [graph_viewer["agentId"]], "propose": [first_agent["agentId"]], "review": [first_agent["agentId"]]}},
    )
    second_base = team_knowledge_service.create_knowledge_base(
        second_team["teamId"],
        name="Shared Graph KB",
        actor_agent_id=second_agent["agentId"],
        acl={"grants": {"read": [graph_viewer["agentId"]], "propose": [second_agent["agentId"]], "review": [second_agent["agentId"]]}},
    )
    assert first_base["knowledgeBaseId"] == second_base["knowledgeBaseId"]
    first_scoped_base_id = first_base["scopedKnowledgeBaseId"]
    second_scoped_base_id = second_base["scopedKnowledgeBaseId"]
    assert first_scoped_base_id != second_scoped_base_id
    assert first_scoped_base_id.startswith(f"team:{first_team['teamId']}:")
    assert second_scoped_base_id.startswith(f"team:{second_team['teamId']}:")

    first_proposal = team_knowledge_service.create_refinement_proposal(
        first_scoped_base_id,
        source_artifact_ids=[],
        proposed_by_agent_id=first_agent["agentId"],
        title="First owner graph item",
        content="FIRST OWNER GRAPH BODY",
    )
    second_proposal = team_knowledge_service.create_refinement_proposal(
        second_scoped_base_id,
        source_artifact_ids=[],
        proposed_by_agent_id=second_agent["agentId"],
        title="Second owner graph item",
        content="SECOND OWNER GRAPH BODY",
    )
    first_reviewed = team_knowledge_service.review_refinement_proposal(
        first_scoped_base_id,
        first_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=first_agent["agentId"],
    )["item"]
    second_reviewed = team_knowledge_service.review_refinement_proposal(
        second_scoped_base_id,
        second_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=second_agent["agentId"],
    )["item"]
    first_reviewed.setdefault("metadata", {})["officialResearchGraph"] = {
        "status": "synced",
        "summary": {"edgeCount": 0},
        "edges": [],
    }
    second_reviewed.setdefault("metadata", {})["officialResearchGraph"] = {
        "status": "synced",
        "summary": {"edgeCount": 0},
        "edges": [],
    }
    team_knowledge_service.update_knowledge_item_metadata(
        first_scoped_base_id,
        first_reviewed["knowledgeItemId"],
        metadata_patch=first_reviewed["metadata"],
        actor_agent_id=first_agent["agentId"],
    )
    team_knowledge_service.update_knowledge_item_metadata(
        second_scoped_base_id,
        second_reviewed["knowledgeItemId"],
        metadata_patch=second_reviewed["metadata"],
        actor_agent_id=second_agent["agentId"],
    )

    response = client.get(
        "/api/memory/knowledge-graph",
        params={"include": "officialResearchGraph", "agentId": graph_viewer["agentId"]},
    )
    payload = response.json()

    assert response.status_code == 200
    base_nodes = [
        node
        for node in payload["nodes"]
        if node["type"] == "knowledge_base" and node["metadata"]["knowledgeBaseId"] == first_base["knowledgeBaseId"]
    ]
    assert len(base_nodes) == 2
    assert {node["metadata"]["ownerId"] for node in base_nodes} == {first_team["teamId"], second_team["teamId"]}
    assert len({node["id"] for node in base_nodes}) == 2
    assert all(node["id"].startswith("knowledge_base:team:") for node in base_nodes)
    item_nodes = [
        node
        for node in payload["nodes"]
        if node["type"] == "knowledge_item" and node["metadata"]["knowledgeItemId"] == first_reviewed["knowledgeItemId"]
    ]
    assert len(item_nodes) == 2
    assert len({node["id"] for node in item_nodes}) == 2

    scoped_response = client.get(
        "/api/memory/knowledge-graph",
        params={
            "include": "officialResearchGraph",
            "agentId": graph_viewer["agentId"],
            "knowledgeBaseId": first_scoped_base_id,
        },
    )
    scoped_payload = scoped_response.json()
    scoped_base_nodes = [
        node
        for node in scoped_payload["nodes"]
        if node["type"] == "knowledge_base" and node["metadata"]["knowledgeBaseId"] == first_base["knowledgeBaseId"]
    ]
    scoped_item_nodes = [
        node
        for node in scoped_payload["nodes"]
        if node["type"] == "knowledge_item" and node["metadata"]["knowledgeItemId"] == first_reviewed["knowledgeItemId"]
    ]
    bare_base_detail = client.get(
        "/api/memory/knowledge-graph/node-detail",
        params={"nodeId": f"knowledge_base:{first_base['knowledgeBaseId']}", "agentId": graph_viewer["agentId"]},
    )
    bare_item_detail = client.get(
        "/api/memory/knowledge-graph/node-detail",
        params={"nodeId": f"knowledge_item:{first_reviewed['knowledgeItemId']}", "agentId": graph_viewer["agentId"]},
    )

    assert scoped_response.status_code == 200
    assert len(scoped_base_nodes) == 1
    assert scoped_base_nodes[0]["metadata"]["ownerId"] == first_team["teamId"]
    assert len(scoped_item_nodes) == 1
    assert scoped_item_nodes[0]["metadata"]["ownerId"] == first_team["teamId"]
    assert bare_base_detail.status_code == 422
    assert bare_item_detail.status_code == 422

    first_detail = client.get(
        "/api/memory/knowledge-graph/node-detail",
        params={
            "nodeId": next(node["id"] for node in item_nodes if node["metadata"]["ownerId"] == first_team["teamId"]),
            "agentId": first_agent["agentId"],
        },
    )
    second_detail = client.get(
        "/api/memory/knowledge-graph/node-detail",
        params={
            "nodeId": next(node["id"] for node in item_nodes if node["metadata"]["ownerId"] == second_team["teamId"]),
            "agentId": second_agent["agentId"],
        },
    )

    assert first_detail.status_code == 200
    assert second_detail.status_code == 200
    assert first_detail.json()["contentItems"][0]["content"] == "FIRST OWNER GRAPH BODY"
    assert second_detail.json()["contentItems"][0]["content"] == "SECOND OWNER GRAPH BODY"


def test_memory_overview_marks_research_knowledge_base_missing_before_first_search(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/memory/overview")

    assert response.status_code == 200, response.json()
    sections = {section["id"]: section for section in response.json()["sections"]}
    research_item = {item["id"]: item for item in sections["research-memory"]["items"]}["research-knowledge-base"]
    assert research_item["exists"] is False
    assert research_item["agentVisible"] is False
    assert research_item["visibilityClass"] == "missing"
    assert research_item["channels"] == ["research", "self_evolution", "explicit_read"]
    assert "科研知识库尚未生成" in research_item["summary"]
    assert '"status": "missing"' in research_item["content"]


def test_memory_usage_contract_aligns_team_agent_and_evolution_boundaries(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Contract Agent")
    team = team_service.create_team(name="Contract Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    base = team_knowledge_service.create_knowledge_base(team["teamId"], name="Contract KB", actor_agent_id=agent["agentId"])
    source = team_knowledge_service.create_source_artifact(
        base["knowledgeBaseId"],
        source_type="runtime_evidence_refinement",
        source_ref={"runId": "self-run-1"},
        title="Runtime evidence",
        actor_agent_id=agent["agentId"],
    )
    team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=agent["agentId"],
        title="Runtime lesson proposal",
        content="Evolution evidence should wait for review.",
    )

    response = client.get("/api/memory/usage-contract")

    assert response.status_code == 200, response.json()
    payload = response.json()
    domains = {item["domainId"]: item for item in payload["domains"]}
    assert payload["schemaVersion"] == 1
    assert domains["agent_private_memory"]["canCreateFormalKnowledge"] is False
    assert domains["team_knowledge"]["canCreateFormalKnowledge"] is True
    assert domains["self_evolution"]["canRegisterSource"] is True
    assert domains["self_evolution"]["canCreateFormalKnowledge"] is False
    assert domains["supervised_evolution"]["canCreateFormalKnowledge"] is False
    assert payload["runtimeAccess"]["knowledgeBodiesInPromptByDefault"] is False
    assert "Evolution runtime directly creates KnowledgeItem." in payload["forbiddenActions"]
    assert payload["currentState"]["knowledge"]["knowledgeBaseCount"] == 1
    assert payload["currentState"]["knowledge"]["pendingProposalCount"] == 1
    assert payload["currentState"]["operatingBoundary"]["formalKnowledgeRequiresReviewer"] is True
    items = team_knowledge_service.list_knowledge_items(base["knowledgeBaseId"], agent_id=agent["agentId"])
    assert items["summary"]["itemCount"] == 0


def test_git_entity_change_snapshot_uses_insert_order_for_append_only_table(tmp_path):
    db_path = tmp_path / "agent_brain.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE GitEntityChange (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commit_sha TEXT NOT NULL,
                path TEXT NOT NULL,
                entity_ref TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                change_type TEXT NOT NULL,
                is_worktree INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO GitEntityChange
                (commit_sha, path, entity_ref, entity_type, change_type, created_at)
            VALUES
                ('old-sha', 'old.py', 'old.ref', 'function', 'modified', '2099-01-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO GitEntityChange
                (commit_sha, path, entity_ref, entity_type, change_type, created_at)
            VALUES
                ('new-sha', 'new.py', 'new.ref', 'function', 'modified', '2026-01-01T00:00:00Z')
            """
        )

    snapshot = memory_service._sqlite_table_snapshot(db_path, "GitEntityChange", limit=1)

    assert snapshot["count"] == 2
    assert snapshot["countExact"] is False
    assert snapshot["rows"][0]["commit_sha"] == "new-sha"


def test_memory_management_api_persists_user_items_and_system_overrides(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "workspace" / "prompts"
    prompt_dir.mkdir(parents=True)
    state_memory_path = prompt_dir / "STATE_MEMORY.md"
    state_memory_path.write_text("Original state memory.", encoding="utf-8")
    monkeypatch.setattr(memory_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[dict] = []

    def fake_record_runtime_scene_event(component, phase, event_code, **kwargs):
        recorded_events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **kwargs,
            }
        )
        return {"accepted": True, "runtimeSceneId": "scene-memory"}

    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", fake_record_runtime_scene_event)

    create_response = client.post(
        "/api/memory/items",
        json={
            "title": "人工规则",
            "summary": "用户确认的长期偏好",
            "content": "始终先解释记忆来源。",
        },
    )

    assert create_response.status_code == 201, create_response.json()
    created = create_response.json()
    assert created["sectionId"] == "user-managed-memory"
    assert created["item"]["managedState"]["userManaged"] is True
    managed_path = tmp_path / "workspace" / "memory" / "user_memory_overrides.json"
    assert managed_path.exists()
    managed_payload = json.loads(managed_path.read_text(encoding="utf-8"))
    assert managed_payload["items"][0]["title"] == "人工规则"

    overview = client.get("/api/memory/overview").json()
    user_section = next(section for section in overview["sections"] if section["id"] == "user-managed-memory")
    assert user_section["items"][0]["title"] == "人工规则"
    assert user_section["items"][0]["channels"] == ["explicit_read"]

    overview = client.get("/api/memory/overview").json()
    prompt_section = next(section for section in overview["sections"] if section["id"] == "prompt-memory")
    state_item_id = next(item["id"] for item in prompt_section["items"] if item["title"] == "STATE_MEMORY.md")

    patch_response = client.patch(
        f"/api/memory/items/prompt-memory/{state_item_id}",
        json={
            "title": "短期状态记忆（用户标注）",
            "summary": "这条摘要来自用户覆盖层",
            "content": "覆盖展示内容，不改原文件。",
        },
    )

    assert patch_response.status_code == 200, patch_response.json()
    assert state_memory_path.read_text(encoding="utf-8") == "Original state memory."
    overview = client.get("/api/memory/overview").json()
    prompt_section = next(section for section in overview["sections"] if section["id"] == "prompt-memory")
    state_item = next(item for item in prompt_section["items"] if item["id"] == state_item_id)
    assert state_item["title"] == "短期状态记忆（用户标注）"
    assert state_item["summary"] == "这条摘要来自用户覆盖层"
    assert state_item["content"] == "覆盖展示内容，不改原文件。"
    assert state_item["managedState"]["overridden"] is True
    assert state_item["managedState"]["restorable"] is True

    delete_response = client.delete(f"/api/memory/items/prompt-memory/{state_item_id}")

    assert delete_response.status_code == 200, delete_response.json()
    overview = client.get("/api/memory/overview").json()
    prompt_section = next(section for section in overview["sections"] if section["id"] == "prompt-memory")
    disabled_item = next(item for item in prompt_section["items"] if item["id"] == state_item_id)
    assert disabled_item["managedState"]["disabled"] is True
    assert disabled_item["agentVisible"] is False
    assert disabled_item["inPrompt"] is False
    assert disabled_item["channels"] == []
    assert state_memory_path.read_text(encoding="utf-8") == "Original state memory."

    restore_response = client.post(f"/api/memory/items/prompt-memory/{state_item_id}/restore")

    assert restore_response.status_code == 200, restore_response.json()
    overview = client.get("/api/memory/overview").json()
    prompt_section = next(section for section in overview["sections"] if section["id"] == "prompt-memory")
    restored_item = next(item for item in prompt_section["items"] if item["id"] == state_item_id)
    assert restored_item["title"] == "STATE_MEMORY.md"
    assert restored_item["content"] == "Original state memory."
    assert restored_item["managedState"]["overridden"] is False
    assert restored_item["managedState"]["restorable"] is False

    delete_user_response = client.delete(f"/api/memory/items/user-managed-memory/{created['itemId']}")

    assert delete_user_response.status_code == 200, delete_user_response.json()
    overview = client.get("/api/memory/overview").json()
    user_section = next(section for section in overview["sections"] if section["id"] == "user-managed-memory")
    assert user_section["items"] == []
    management_events = [event for event in recorded_events if event["phase"] == "memory_management"]
    event_codes = [event["eventCode"] for event in management_events]
    assert event_codes == [
        "memory.create",
        "memory.update",
        "memory.disable",
        "memory.restore",
        "memory.delete",
    ]
    assert all(event["component"] == "memory_service" for event in management_events)
    assert all(event["phase"] == "memory_management" for event in management_events)
    assert all(event["lifecycle"] is True for event in management_events)
    assert all("content" not in event.get("fields", {}) for event in management_events)


def test_memory_overview_slow_event_includes_section_timings(tmp_path, monkeypatch):
    recorded_events: list[dict] = []

    def fake_record_runtime_scene_event(component, phase, event_code, **kwargs):
        recorded_events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **kwargs,
            }
        )
        return {"accepted": True, "runtimeSceneId": "scene-memory"}

    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", fake_record_runtime_scene_event)

    memory_service._record_memory_overview_perf_event(
        tmp_path,
        {
            "summary": {"itemCount": 2},
            "sections": [
                {"id": "project-memory", "items": [{"id": "one"}]},
                {"id": "runtime-memory", "items": [{"id": "two"}]},
            ],
        },
        duration_ms=900,
        section_timings=[
            {"sectionId": "project-memory", "durationMs": 12.3, "itemCount": 1},
            {"sectionId": "runtime-memory", "durationMs": 45.6, "itemCount": 1},
        ],
    )

    assert recorded_events
    event = recorded_events[-1]
    assert event["eventCode"] == "memory.overview.slow"
    assert event["fields"]["durationMs"] == 900
    assert event["fields"]["sectionTimingsMs"] == [
        {"sectionId": "project-memory", "durationMs": 12.3, "itemCount": 1},
        {"sectionId": "runtime-memory", "durationMs": 45.6, "itemCount": 1},
    ]
