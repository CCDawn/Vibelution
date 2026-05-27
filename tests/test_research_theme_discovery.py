"""Research theme discovery MVP tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.research.knowledge_base import ResearchKnowledgeBase
from core.research.models import CandidateTheme, EvidenceRecord, ResearchDiscoverySession, new_id
from core.research import providers
from core.research.providers import DeterministicResearchSearchProvider, PublicResearchSearchProvider
from core.research.repository import ResearchRepository
from core.research.scoring import calculate_recommendation_score, deduplicate_themes
from core.research.theme_discovery import ResearchThemeDiscoveryService
from core.research.agent_templates import ensure_research_prompt_defaults, normalize_research_agent_config
from core.research.agent_runner import AgentEvidenceResult, DeterministicResearchAgentRunner, LLMResearchAgentRunner
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import research_service, runtime_scene_service


def test_research_recommendation_score_uses_novelty_first_weights():
    score = calculate_recommendation_score(
        {
            "noveltyGap": 100,
            "scientificValue": 80,
            "technicalDepth": 70,
            "interdisciplinaryAuthenticity": 60,
            "verifiability": 50,
            "competitionFit": 40,
            "implementationFeasibility": 20,
        }
    )

    assert score == 70.5


def test_theme_deduplication_keeps_stronger_different_candidates():
    session_id = new_id("session")
    strong = _theme(
        session_id,
        title="Mechanism-gap discovery for AI Scientist",
        question="Can AI Scientist discover under-specified mechanisms?",
        score=92,
        novelty_path="problem_perspective",
    )
    near_duplicate = _theme(
        session_id,
        title="AI Scientist mechanism gap discovery",
        question="Can AI Scientist discover under-specified mechanisms in papers?",
        score=89,
        novelty_path="problem_perspective",
    )
    different = _theme(
        session_id,
        title="Causal falsifiability filters for hypothesis generation",
        question="Can counterfactual filters make hypotheses more falsifiable?",
        score=87,
        novelty_path="method_transfer",
    )

    selected = deduplicate_themes([near_duplicate, different, strong], limit=2)

    assert [item.theme_id for item in selected] == [strong.theme_id, different.theme_id]


def test_research_repository_roundtrip(tmp_path):
    repository = ResearchRepository(root=tmp_path / "research")
    session = ResearchDiscoverySession(
        session_id=new_id("research-session"),
        open_goal="Find a novel AI Scientist theme",
        constraints="Student team and public sources",
        preferences="Novel first",
    )

    repository.save_session(session)
    loaded = repository.load_session(session.session_id)

    assert loaded.session_id == session.session_id
    assert loaded.open_goal == "Find a novel AI Scientist theme"
    assert repository.list_sessions()[0].session_id == session.session_id


def test_research_knowledge_base_ingests_search_sources_and_dedupes(tmp_path):
    service = _service(tmp_path)
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )
    session_id = created["session"]["sessionId"]

    first = service.run_broad_search(session_id)
    second = service.run_broad_search(session_id)
    knowledge = service.get_knowledge_base(query="scientist")

    assert first["events"][-1]["fields"]["knowledgeBase"]["added"] > 0
    assert second["events"][-1]["fields"]["knowledgeBase"]["updated"] > 0
    assert knowledge["path"].endswith("knowledge_base.json")
    assert knowledge["schemaVersion"] == 2
    assert knowledge["summary"]["entryCount"] > 0
    assert knowledge["summary"]["claimCount"] > 0
    assert knowledge["summary"]["evidenceCount"] > 0
    assert knowledge["summary"]["gapCount"] > 0
    assert knowledge["agentContext"]["entryCount"] == knowledge["summary"]["entryCount"]
    assert knowledge["agentContext"]["claimCount"] == knowledge["summary"]["claimCount"]
    assert "claim" in knowledge["agentContext"]["cognitiveLayers"]
    assert knowledge["agentContext"]["recentQueries"]
    assert "avoid repeating known sources" in knowledge["agentContext"]["purpose"]
    assert knowledge["summary"]["kindCounts"]["paper"] > 0
    assert any("literature" in item["categories"] for item in knowledge["entries"])
    assert any(item["hitCount"] > 1 for item in knowledge["entries"])
    first_entry = knowledge["entries"][0]
    assert first_entry["dedupeKey"]
    assert first_entry["firstSeenAt"]
    assert first_entry["lastSeenAt"]
    assert first_entry["firstRetrievedAt"]
    assert first_entry["lastRetrievedAt"]
    assert first_entry["sourceIds"]
    assert first_entry["sessionIds"] == [session_id]
    assert first_entry["searchRunIds"]
    assert first_entry["queries"]
    assert first_entry["providers"]
    assert first_entry["provenance"][0]["sourceId"] in first_entry["sourceIds"]
    assert first_entry["provenance"][0]["retrievedAt"]
    assert first_entry["provenance"][0]["seenAt"]
    first_claim = knowledge["claims"][0]
    assert first_claim["recordId"].startswith("rkc-")
    assert first_claim["type"] == "claim"
    assert first_claim["sourceIds"]
    assert first_claim["knowledgeIds"]
    assert first_claim["provenance"]
    first_evidence = knowledge["evidence"][0]
    assert first_evidence["recordId"].startswith("rke-")
    assert first_evidence["type"] == "evidence"
    first_gap = knowledge["gaps"][0]
    assert first_gap["recordId"].startswith("rkg-")
    assert first_gap["status"] == "needs_review"
    assert knowledge["agentEvolutionMemory"]["purpose"].startswith("Reserved bridge")


def test_theme_discovery_checks_knowledge_base_before_search_and_reuses_context(tmp_path):
    service = _service(tmp_path)
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )
    session_id = created["session"]["sessionId"]

    first = service.run_broad_search(session_id)
    first_run = first["searchRuns"][0]
    first_preflight = first_run["modelProfile"]["knowledgePreflight"]

    assert first_preflight["decision"] == "kb_empty_search_required"
    assert first_preflight["matchedEntryCount"] == 0
    assert first_run["modelProfile"]["agentExecution"]["knowledgeContextDecision"] == "kb_empty_search_required"
    assert first_run["modelProfile"]["agentExecution"]["trace"][0]["kind"] == "memory"
    assert first["events"][-1]["fields"]["knowledgePreflight"]["decision"] == "kb_empty_search_required"

    second = service.run_broad_search(session_id)
    second_run = second["searchRuns"][-1]
    second_preflight = second_run["modelProfile"]["knowledgePreflight"]

    assert second_preflight["decision"] == "reuse_and_search"
    assert second_preflight["matchedEntryCount"] > 0
    assert second_preflight["matchedClaimCount"] > 0
    assert second_preflight["matchedEvidenceCount"] > 0
    assert second_preflight["matchedGapCount"] > 0
    assert second_preflight["recentSources"]
    assert second_run["modelProfile"]["agentExecution"]["knowledgeContextDecision"] == "reuse_and_search"
    assert second_run["modelProfile"]["agentExecution"]["trace"][0]["title"] == "科研知识库预检"
    assert second["events"][-1]["fields"]["knowledgePreflight"]["decision"] == "reuse_and_search"


def test_theme_discovery_passes_knowledge_context_to_compatible_search_runner(tmp_path):
    captured: dict[str, object] = {}

    class InspectingRunner(DeterministicResearchAgentRunner):
        def run_search(
            self,
            *,
            phase,
            session,
            suggested_queries,
            existing_sources,
            knowledge_context=None,
            trace_sink=None,
        ):
            captured["knowledge_context"] = knowledge_context
            return super().run_search(
                phase=phase,
                session=session,
                suggested_queries=suggested_queries,
                existing_sources=existing_sources,
                knowledge_context=knowledge_context,
                trace_sink=trace_sink,
            )

    search_provider = DeterministicResearchSearchProvider()
    service = ResearchThemeDiscoveryService(
        repository=ResearchRepository(root=tmp_path / "research"),
        search_provider=search_provider,
        agent_runner=InspectingRunner(search_provider=search_provider),
    )
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )

    service.run_broad_search(created["session"]["sessionId"])

    assert isinstance(captured["knowledge_context"], dict)
    assert captured["knowledge_context"]["decision"] == "kb_empty_search_required"


def test_research_runtime_scene_events_are_compact_stage_summaries(tmp_path, monkeypatch):
    recorded: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        runtime_scene_service,
        "record_research_scene_event",
        lambda event_code, **kwargs: recorded.append((event_code, kwargs)),
    )
    service = _service(tmp_path)
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )

    service.run_broad_search(created["session"]["sessionId"])

    codes = [event_code for event_code, _kwargs in recorded]
    assert "search.broad.started" in codes
    assert "search.broad.completed" in codes
    started = next(kwargs for event_code, kwargs in recorded if event_code == "search.broad.started")
    completed = next(kwargs for event_code, kwargs in recorded if event_code == "search.broad.completed")
    assert started["outcome"] == "started"
    assert completed["outcome"] == "succeeded"
    assert completed["fields"]["agentExecution"]["traceCount"] > 0
    assert "trace" not in completed["fields"]["agentExecution"]
    assert completed["fields"]["trace"]["count"] > 0
    assert "recentSources" not in completed["fields"]["knowledgePreflight"]
    assert completed["fields"]["knowledgeBase"]["total"] > 0


def test_research_knowledge_base_filters_by_kind_and_category(tmp_path):
    service = _service(tmp_path)
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )

    service.run_broad_search(created["session"]["sessionId"])
    papers = service.get_knowledge_base(kind="paper", category="literature")

    assert papers["entries"]
    assert {item["kind"] for item in papers["entries"]} == {"paper"}
    assert all("literature" in item["categories"] for item in papers["entries"])


def test_research_knowledge_base_reads_legacy_source_only_payload(tmp_path):
    path = tmp_path / "knowledge_base.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "updatedAt": "2026-05-26T00:00:00Z",
                "entries": [
                    {
                        "kind": "paper",
                        "title": "Legacy AI Scientist Source",
                        "url": "https://example.com/legacy",
                        "summary": "Legacy source summary",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = ResearchKnowledgeBase(path=path).payload()

    assert payload["schemaVersion"] == 2
    assert payload["entries"][0]["title"] == "Legacy AI Scientist Source"
    assert payload["claims"] == []
    assert payload["evidence"] == []
    assert payload["gaps"] == []
    assert payload["agentEvolutionMemory"]["experienceRefs"] == []


def test_research_prompt_defaults_are_agent_specific(tmp_path):
    class FakeWorkspace:
        def __init__(self, root):
            self.root = root

        def get_research_prompt_path(self, filename):
            return self.root / filename

        def write_research_prompt(self, filename, content):
            path = self.get_research_prompt_path(filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return True

    workspace = FakeWorkspace(tmp_path / "prompts" / "research")

    ensure_research_prompt_defaults(workspace)

    broad = (workspace.root / "broad.md").read_text(encoding="utf-8")
    deep = (workspace.root / "deep.md").read_text(encoding="utf-8")
    review = (workspace.root / "review.md").read_text(encoding="utf-8")
    themes = (workspace.root / "themes.md").read_text(encoding="utf-8")
    card = (workspace.root / "card.md").read_text(encoding="utf-8")
    assert "广撒网探索 agent" in broad
    assert "定向深搜 agent" in deep
    assert "证据审查 agent" in review
    assert "主题生成 agent" in themes
    assert "主题卡规划 agent" in card
    assert "不要提前给出最终选题" in broad
    assert "Evidence Chain" in deep
    assert "Claim Traceability" in review
    assert "noveltyGap" in themes
    assert "dataset_plan" in card


def test_research_agent_config_can_hide_deleted_default_agent():
    config = normalize_research_agent_config({"schemaVersion": 1, "deletedDefaultAgents": ["review"], "agents": []})

    assert "review" not in {agent["key"] for agent in config["agents"]}
    assert "review" in config["deletedDefaultAgents"]


def test_research_prompt_update_failure_emits_runtime_scene_log(monkeypatch):
    events = []
    monkeypatch.setattr(research_service, "_record_research_config_event", lambda *args, **kwargs: events.append((args, kwargs)))

    with pytest.raises(ValueError, match="Unknown research prompt key"):
        research_service.save_research_prompt("unknown-agent", "prompt")

    assert events[0][0][0] == "research.prompt.update_failed"
    assert events[0][1]["outcome"] == "failed"
    assert events[0][1]["fields"]["reason"] == "unknown_prompt_key"


def test_research_agent_pool_allows_custom_agent_and_blocks_referenced_delete(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, root):
            self.root = root

        def research_prompts_dir(self):
            return self.root / "prompts" / "research"

        def get_research_prompt_path(self, filename):
            return self.research_prompts_dir() / filename

        def get_research_agent_config_path(self):
            return self.research_prompts_dir() / "agents.json"

        def get_research_flow_canvas_path(self):
            return self.research_prompts_dir() / "flow_canvas.json"

        def read_research_agent_config(self):
            path = self.get_research_agent_config_path()
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

        def write_research_agent_config(self, data):
            path = self.get_research_agent_config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return True

        def read_research_flow_canvas(self):
            return {
                "schemaVersion": 1,
                "viewport": {},
                "nodes": [
                    {
                        "id": "reader",
                        "label": "论文阅读",
                        "type": "agent",
                        "status": "ready",
                        "agentKey": "paper_reader",
                        "promptKey": "paper_reader",
                    }
                ],
                "edges": [],
            }

        def write_research_prompt(self, filename, content):
            path = self.get_research_prompt_path(filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return True

        def read_research_prompt(self, filename):
            path = self.get_research_prompt_path(filename)
            return path.read_text(encoding="utf-8") if path.exists() else ""

    workspace = FakeWorkspace(tmp_path)
    monkeypatch.setattr(research_service, "get_workspace", lambda: workspace)
    monkeypatch.setattr(research_service, "_list_llm_config_options", lambda: [{"configId": "research_broad"}])

    payload = research_service.save_research_agent_binding(
        "paper_reader",
        "research_broad_explorer",
        "research_broad",
        label="论文阅读 Agent",
        prompt_filename="paper_reader.md",
    )

    created = next(agent for agent in payload["agents"] if agent["key"] == "paper_reader")
    assert created["label"] == "论文阅读 Agent"
    assert created["llmConfigId"] == "research_broad"
    assert (workspace.research_prompts_dir() / "paper_reader.md").exists()

    with pytest.raises(ValueError, match="still used by flow nodes"):
        research_service.delete_research_agent_binding("paper_reader")


def test_research_flow_canvas_roundtrip_uses_workspace_source_of_truth(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, root):
            self.root = root

        def get_research_flow_canvas_path(self):
            return self.root / "prompts" / "research" / "flow_canvas.json"

        def read_research_flow_canvas(self):
            path = self.get_research_flow_canvas_path()
            if path.exists():
                import json

                return json.loads(path.read_text(encoding="utf-8"))
            return {}

        def write_research_flow_canvas(self, data):
            path = self.get_research_flow_canvas_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            import json

            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return True

    events = []
    monkeypatch.setattr(research_service, "get_workspace", lambda: FakeWorkspace(tmp_path))
    monkeypatch.setattr(research_service, "_record_research_config_event", lambda *args, **kwargs: events.append((args, kwargs)))

    default_canvas = research_service.get_research_flow_canvas()
    assert default_canvas["path"].endswith("flow_canvas.json")
    assert default_canvas["validation"]["valid"] is True
    assert default_canvas["validation"]["summary"]["errorCount"] == 0
    assert {node["id"] for node in default_canvas["nodes"]} >= {
        "broad_search",
        "knowledge_store",
        "knowledge_lookup",
        "literature_project_parse",
        "semantic_cluster",
        "novelty_reverse_check",
        "evidence_review",
        "theme_card",
    }
    assert any(edge["condition"] == "needs_evidence" for edge in default_canvas["edges"])
    assert next(edge for edge in default_canvas["edges"] if edge["id"] == "edge_broad_store")["target"] == "knowledge_store"
    assert next(edge for edge in default_canvas["edges"] if edge["id"] == "edge_store_lookup")["target"] == "knowledge_lookup"
    assert next(edge for edge in default_canvas["edges"] if edge["id"] == "edge_lookup_deep")["target"] == "deep_search"
    assert next(edge for edge in default_canvas["edges"] if edge["id"] == "edge_novelty_review")["source"] == "novelty_reverse_check"
    assert next(edge for edge in default_canvas["edges"] if edge["id"] == "edge_review_deep")["type"] == "evidence_loop"

    payload = {
        "nodes": [
            {
                "id": "topic_probe",
                "label": "主题探针",
                "type": "agent",
                "status": "ready",
                "x": 100,
                "y": 120,
                "agentKey": "broad",
                "promptKey": "broad",
                "llmConfigId": "research_broad",
                "description": "search",
                "routeCondition": "start",
            },
            {
                "id": "review_gate",
                "label": "审查门",
                "type": "decision",
                "status": "needs_review",
                "x": 360,
                "y": 120,
                "agentKey": "review",
                "promptKey": "review",
                "llmConfigId": "research_review",
                "description": "review",
                "routeCondition": "after search",
            },
        ],
        "edges": [
            {
                "id": "edge_topic_review",
                "source": "topic_probe",
                "target": "review_gate",
                "label": "证据审查",
                "condition": "人工手填条件",
            }
        ],
        "viewport": {"x": 42, "y": -16, "zoom": 1.42},
    }
    saved = research_service.save_research_flow_canvas(payload)

    assert saved["nodes"][0]["label"] == "主题探针"
    assert saved["validation"]["valid"] is True
    assert saved["edges"][0]["source"] == "topic_probe"
    assert saved["edges"][0]["condition"] == "completed"
    assert saved["edges"][0]["type"] == "success"
    assert saved["viewport"] == {"x": 42, "y": -16, "zoom": 1.42}
    assert events[-1][0][0] == "research.flow_canvas.updated"
    assert research_service.get_research_flow_canvas()["nodes"][1]["type"] == "decision"

    saved_loop = research_service.save_research_flow_canvas(
        {
            **payload,
            "edges": [
                {
                    "id": "edge_review_topic",
                    "source": "review_gate",
                    "target": "topic_probe",
                    "label": "缺证据补搜",
                    "condition": "needs_evidence",
                }
            ],
        }
    )
    assert saved_loop["edges"][0]["type"] == "evidence_loop"


def test_research_flow_canvas_rejects_mojibake_payload(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, root):
            self.root = root

        def get_research_flow_canvas_path(self):
            return self.root / "prompts" / "research" / "flow_canvas.json"

        def read_research_flow_canvas(self):
            return {}

        def write_research_flow_canvas(self, data):
            raise AssertionError("mojibake payload must not be persisted")

    events = []
    monkeypatch.setattr(research_service, "get_workspace", lambda: FakeWorkspace(tmp_path))
    monkeypatch.setattr(research_service, "_record_research_config_event", lambda *args, **kwargs: events.append((args, kwargs)))

    payload = research_service._default_research_flow_canvas()
    payload["nodes"][0]["label"] = "å¹¿æç½æ¢ç´¢"
    payload["nodes"][0]["description"] = "ä»å¼æ¾ç®æ åºå"

    with pytest.raises(ValueError, match="mojibake"):
        research_service.save_research_flow_canvas(payload)

    assert events[-1][0][0] == "research.flow_canvas.update_failed"
    assert events[-1][1]["fields"]["mojibakeMarkerCount"] >= 2
    assert events[-1][1]["fields"]["mojibakeMarkers"][0]["id"] == "broad_search"


def test_research_flow_canvas_rejects_question_mark_encoding_loss(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, root):
            self.root = root

        def get_research_flow_canvas_path(self):
            return self.root / "prompts" / "research" / "flow_canvas.json"

        def read_research_flow_canvas(self):
            return {}

        def write_research_flow_canvas(self, data):
            raise AssertionError("question-mark-corrupted payload must not be persisted")

    monkeypatch.setattr(research_service, "get_workspace", lambda: FakeWorkspace(tmp_path))
    monkeypatch.setattr(research_service, "_record_research_config_event", lambda *args, **kwargs: None)

    payload = research_service._default_research_flow_canvas()
    payload["nodes"][1]["label"] = "??????"
    payload["nodes"][1]["description"] = "???/?????????????????? ResearchKnowledgeBase"

    with pytest.raises(ValueError, match="mojibake"):
        research_service.save_research_flow_canvas(payload)


def test_research_flow_canvas_preserves_saved_default_node_positions(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, root):
            self.root = root

        def get_research_flow_canvas_path(self):
            return self.root / "prompts" / "research" / "flow_canvas.json"

        def read_research_flow_canvas(self):
            path = self.get_research_flow_canvas_path()
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            return {}

        def write_research_flow_canvas(self, data):
            path = self.get_research_flow_canvas_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return True

    monkeypatch.setattr(research_service, "get_workspace", lambda: FakeWorkspace(tmp_path))
    monkeypatch.setattr(research_service, "_record_research_config_event", lambda *args, **kwargs: None)

    payload = research_service._default_research_flow_canvas()
    expected_positions = {
        "broad_search": {"x": 24.5, "y": 221.25},
        "knowledge_store": {"x": 444.75, "y": 310.5},
        "deep_search": {"x": 1199.125, "y": -36.75},
    }
    for node in payload["nodes"]:
        position = expected_positions.get(node["id"])
        if position:
            node.update(position)

    saved = research_service.save_research_flow_canvas(payload)
    reloaded = research_service.get_research_flow_canvas()
    saved_positions = {
        node["id"]: {"x": node["x"], "y": node["y"]}
        for node in saved["nodes"]
        if node["id"] in expected_positions
    }
    reloaded_positions = {
        node["id"]: {"x": node["x"], "y": node["y"]}
        for node in reloaded["nodes"]
        if node["id"] in expected_positions
    }

    assert saved_positions == expected_positions
    assert reloaded_positions == expected_positions


def test_research_flow_canvas_rejects_misaligned_graph_contract(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, root):
            self.root = root

        def get_research_flow_canvas_path(self):
            return self.root / "prompts" / "research" / "flow_canvas.json"

        def read_research_flow_canvas(self):
            return {}

        def write_research_flow_canvas(self, data):
            return True

    monkeypatch.setattr(research_service, "get_workspace", lambda: FakeWorkspace(tmp_path))
    monkeypatch.setattr(research_service, "_record_research_config_event", lambda *args, **kwargs: None)
    base_nodes = [
        {
            "id": "broad_search",
            "label": "广搜",
            "type": "agent",
            "status": "ready",
            "x": 0,
            "y": 0,
            "agentKey": "broad",
            "promptKey": "broad",
            "llmConfigId": "research_broad",
            "description": "",
            "routeCondition": "",
        },
        {
            "id": "semantic_cluster",
            "label": "语义去重与聚类",
            "type": "tool",
            "status": "idle",
            "x": 260,
            "y": 0,
            "agentKey": "semantic_cluster",
            "promptKey": "",
            "llmConfigId": "",
            "description": "",
            "routeCondition": "",
        },
    ]

    with pytest.raises(ValueError, match="无法满足"):
        research_service.save_research_flow_canvas(
            {
                "nodes": base_nodes,
                "edges": [
                    {
                        "id": "edge_broad_cluster",
                        "source": "broad_search",
                        "target": "semantic_cluster",
                        "label": "错误直连",
                        "condition": "completed",
                        "type": "success",
                    }
                ],
            }
        )


def test_research_flow_canvas_rejects_structural_contract_errors(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, root):
            self.root = root

        def get_research_flow_canvas_path(self):
            return self.root / "prompts" / "research" / "flow_canvas.json"

        def read_research_flow_canvas(self):
            return {}

        def write_research_flow_canvas(self, data):
            return True

    monkeypatch.setattr(research_service, "get_workspace", lambda: FakeWorkspace(tmp_path))
    monkeypatch.setattr(research_service, "_record_research_config_event", lambda *args, **kwargs: None)
    nodes = [
        {
            "id": "broad_search",
            "label": "广搜",
            "type": "agent",
            "status": "ready",
            "x": 0,
            "y": 0,
            "agentKey": "broad",
            "promptKey": "broad",
            "llmConfigId": "research_broad",
            "description": "",
            "routeCondition": "",
        },
        {
            "id": "deep_search",
            "label": "深搜",
            "type": "agent",
            "status": "idle",
            "x": 260,
            "y": 0,
            "agentKey": "deep",
            "promptKey": "deep",
            "llmConfigId": "research_deep",
            "description": "",
            "routeCondition": "",
        },
    ]

    with pytest.raises(ValueError, match="不能连接到自身"):
        research_service.save_research_flow_canvas(
            {
                "nodes": nodes,
                "edges": [
                    {"id": "edge_self", "source": "broad_search", "target": "broad_search", "condition": "completed", "type": "success"}
                ],
            }
        )

    with pytest.raises(ValueError, match="路由 ID 重复"):
        research_service.save_research_flow_canvas(
            {
                "nodes": nodes,
                "edges": [
                    {"id": "edge_dup", "source": "broad_search", "target": "deep_search", "condition": "completed", "type": "success"},
                    {"id": "edge_dup", "source": "broad_search", "target": "deep_search", "condition": "completed", "type": "success"},
                ],
            }
        )

    with pytest.raises(ValueError, match="触发条件 needs_evidence 与箭头类型 success 不一致"):
        research_service.save_research_flow_canvas(
            {
                "nodes": nodes,
                "edges": [
                    {"id": "edge_drift", "source": "broad_search", "target": "deep_search", "condition": "needs_evidence", "type": "success"}
                ],
            }
        )


def test_research_flow_canvas_executes_next_ready_node_and_routes_successors(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, root):
            self.root = root

        def get_research_flow_canvas_path(self):
            return self.root / "prompts" / "research" / "flow_canvas.json"

        def read_research_flow_canvas(self):
            path = self.get_research_flow_canvas_path()
            if path.exists():
                import json

                return json.loads(path.read_text(encoding="utf-8"))
            return {}

        def write_research_flow_canvas(self, data):
            path = self.get_research_flow_canvas_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            import json

            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return True

    service = _service(tmp_path)
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )
    events = []
    monkeypatch.setattr(research_service, "_SERVICE", service)
    monkeypatch.setattr(research_service, "get_workspace", lambda: FakeWorkspace(tmp_path))
    monkeypatch.setattr(
        research_service,
        "record_research_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    result = research_service.execute_research_flow_canvas_node(created["session"]["sessionId"])

    canvas = result["canvas"]
    assert result["execution"]["nodeId"] == "broad_search"
    assert result["execution"]["routeOutcome"] == "completed"
    assert result["session"]["summary"]["sourceCount"] > 0
    assert next(node for node in canvas["nodes"] if node["id"] == "broad_search")["status"] == "done"
    assert next(node for node in canvas["nodes"] if node["id"] == "knowledge_store")["status"] == "ready"
    assert next(node for node in canvas["nodes"] if node["id"] == "deep_search")["status"] == "idle"
    event_codes = [event[0][0] for event in events]
    assert "research.flow_canvas.updated" not in event_codes
    assert "research.flow_canvas.node_started" in event_codes
    assert events[-1][0][0] == "research.flow_canvas.node_executed"
    assert events[-1][1]["fields"]["activatedNodeIds"] == ["knowledge_store"]

    store_result = research_service.execute_research_flow_canvas_node(created["session"]["sessionId"])
    store_canvas = store_result["canvas"]
    assert store_result["execution"]["nodeId"] == "knowledge_store"
    assert next(node for node in store_canvas["nodes"] if node["id"] == "knowledge_lookup")["status"] == "ready"
    assert store_result["execution"]["activatedNodeIds"] == ["knowledge_lookup"]

    lookup_result = research_service.execute_research_flow_canvas_node(created["session"]["sessionId"])
    lookup_canvas = lookup_result["canvas"]
    assert lookup_result["execution"]["nodeId"] == "knowledge_lookup"
    assert next(node for node in lookup_canvas["nodes"] if node["id"] == "deep_search")["status"] == "ready"
    assert lookup_result["execution"]["activatedNodeIds"] == ["deep_search"]
    assert any(
        event.get("eventCode") == "research.capability.knowledge_lookup.completed"
        for event in lookup_result["session"]["events"]
    )

    deep_result = research_service.execute_research_flow_canvas_node(created["session"]["sessionId"])
    deep_canvas = deep_result["canvas"]
    assert deep_result["execution"]["nodeId"] == "deep_search"
    assert next(node for node in deep_canvas["nodes"] if node["id"] == "literature_project_parse")["status"] == "ready"
    assert next(node for node in deep_canvas["nodes"] if node["id"] == "semantic_cluster")["status"] == "idle"

    parse_result = research_service.execute_research_flow_canvas_node(created["session"]["sessionId"])
    parse_canvas = parse_result["canvas"]
    assert parse_result["execution"]["nodeId"] == "literature_project_parse"
    assert parse_result["execution"]["activatedNodeIds"] == ["semantic_cluster"]
    assert next(node for node in parse_canvas["nodes"] if node["id"] == "semantic_cluster")["status"] == "ready"
    parse_event = next(
        event for event in parse_result["session"]["events"]
        if event.get("eventCode") == "research.capability.literature_project_parse.completed"
    )
    parse_fields = parse_event["fields"]
    assert parse_fields["capabilityMode"] == "metadata_signal_parser"
    assert parse_fields["parsedSourceCount"] > 0
    assert parse_fields["parseTypeCounts"]["paper_or_pdf"] > 0
    assert parse_fields["parseTypeCounts"]["github_repository"] > 0
    assert parse_fields["signalCounts"]["method"] > 0
    assert parse_fields["parsedRecords"][0]["sourceId"]

    rerun_result = research_service.execute_research_flow_canvas_node(created["session"]["sessionId"], node_id="broad_search")
    rerun_canvas = rerun_result["canvas"]
    assert rerun_result["execution"]["nodeId"] == "broad_search"
    assert next(node for node in rerun_canvas["nodes"] if node["id"] == "broad_search")["status"] == "done"
    assert next(node for node in rerun_canvas["nodes"] if node["id"] == "knowledge_store")["status"] == "ready"
    assert next(node for node in rerun_canvas["nodes"] if node["id"] == "knowledge_lookup")["status"] == "stale"
    assert rerun_result["execution"]["activatedNodeIds"] == ["knowledge_store"]
    rerun_started = [
        event
        for event in events
        if event[0][0] == "research.flow_canvas.node_started" and event[1]["fields"].get("rerun")
    ]
    assert rerun_started


def test_theme_discovery_actions_sync_flow_canvas_statuses(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, root):
            self.root = root

        def get_research_flow_canvas_path(self):
            return self.root / "prompts" / "research" / "flow_canvas.json"

        def read_research_flow_canvas(self):
            path = self.get_research_flow_canvas_path()
            if path.exists():
                import json

                return json.loads(path.read_text(encoding="utf-8"))
            return {}

        def write_research_flow_canvas(self, data):
            path = self.get_research_flow_canvas_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            import json

            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return True

    service = _service(tmp_path)
    events = []
    monkeypatch.setattr(research_service, "_SERVICE", service)
    monkeypatch.setattr(research_service, "get_workspace", lambda: FakeWorkspace(tmp_path))
    monkeypatch.setattr(
        research_service,
        "record_research_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    created = research_service.create_theme_discovery_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )
    session_id = created["session"]["sessionId"]
    canvas_after_create = research_service.get_research_flow_canvas()

    assert next(node for node in canvas_after_create["nodes"] if node["id"] == "broad_search")["status"] == "ready"
    assert next(node for node in canvas_after_create["nodes"] if node["id"] == "evidence_review")["status"] == "idle"
    assert next(node for node in canvas_after_create["nodes"] if node["id"] == "human_choice")["status"] == "idle"

    research_service.run_broad_theme_search(session_id)
    canvas_after_broad = research_service.get_research_flow_canvas()

    assert next(node for node in canvas_after_broad["nodes"] if node["id"] == "broad_search")["status"] == "done"
    assert next(node for node in canvas_after_broad["nodes"] if node["id"] == "knowledge_store")["status"] == "ready"
    assert next(node for node in canvas_after_broad["nodes"] if node["id"] == "deep_search")["status"] == "idle"
    assert any(event[0][0] == "research.flow_canvas.synced" for event in events)


def test_research_flow_canvas_blocks_theme_card_without_selected_theme(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, root):
            self.root = root

        def get_research_flow_canvas_path(self):
            return self.root / "prompts" / "research" / "flow_canvas.json"

        def read_research_flow_canvas(self):
            return {
                "nodes": [
                    {
                        "id": "theme_card",
                        "label": "正式主题卡",
                        "type": "artifact",
                        "status": "ready",
                        "x": 0,
                        "y": 0,
                        "agentKey": "card",
                        "promptKey": "card",
                        "llmConfigId": "research_card",
                        "description": "",
                        "routeCondition": "",
                    }
                ],
                "edges": [],
                "viewport": {"x": 0, "y": 0, "zoom": 1},
            }

        def write_research_flow_canvas(self, data):
            self.saved = data
            return True

    service = _service(tmp_path)
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )
    workspace = FakeWorkspace(tmp_path)
    monkeypatch.setattr(research_service, "_SERVICE", service)
    monkeypatch.setattr(research_service, "get_workspace", lambda: workspace)
    monkeypatch.setattr(research_service, "record_research_scene_event", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="Select a candidate theme"):
        research_service.execute_research_flow_canvas_node(created["session"]["sessionId"], node_id="theme_card")

    assert workspace.saved["nodes"][0]["status"] == "failed"


def test_research_flow_canvas_reopens_done_search_on_missing_evidence(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self):
            self.saved = None

        def get_research_flow_canvas_path(self):
            return tmp_path / "prompts" / "research" / "flow_canvas.json"

        def read_research_flow_canvas(self):
            return {
                "nodes": [
                    {
                        "id": "deep_search",
                        "label": "定向深搜",
                        "type": "agent",
                        "status": "done",
                        "x": 0,
                        "y": 0,
                        "agentKey": "deep",
                        "promptKey": "deep",
                        "llmConfigId": "research_deep",
                        "description": "",
                        "routeCondition": "",
                    },
                    {
                        "id": "evidence_review",
                        "label": "证据审查",
                        "type": "agent",
                        "status": "ready",
                        "x": 260,
                        "y": 0,
                        "agentKey": "review",
                        "promptKey": "review",
                        "llmConfigId": "research_review",
                        "description": "",
                        "routeCondition": "",
                    },
                ],
                "edges": [
                    {
                        "id": "edge_review_deep",
                        "source": "evidence_review",
                        "target": "deep_search",
                        "label": "缺证据补搜",
                        "condition": "needs_evidence",
                    }
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 1},
            }

        def write_research_flow_canvas(self, data):
            self.saved = data
            return True

    workspace = FakeWorkspace()
    monkeypatch.setattr(research_service, "get_workspace", lambda: workspace)
    monkeypatch.setattr(research_service, "record_research_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        research_service,
        "extract_theme_discovery_evidence",
        lambda session_id: {
            "session": {"sessionId": session_id},
            "summary": {"evidenceCount": 1},
            "events": [{"fields": {"missingEvidenceRequests": ["补充 GitHub 项目证据"]}}],
        },
    )

    result = research_service.execute_research_flow_canvas_node("session-1", node_id="evidence_review")

    deep_node = next(node for node in result["canvas"]["nodes"] if node["id"] == "deep_search")
    review_node = next(node for node in result["canvas"]["nodes"] if node["id"] == "evidence_review")
    assert result["execution"]["routeOutcome"] == "needs_evidence"
    assert result["execution"]["activatedNodeIds"] == ["deep_search"]
    assert deep_node["status"] == "needs_evidence"
    assert review_node["status"] == "done"


def test_research_flow_canvas_blocks_new_node_while_another_is_running(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self):
            self.saved = None

        def get_research_flow_canvas_path(self):
            return tmp_path / "prompts" / "research" / "flow_canvas.json"

        def read_research_flow_canvas(self):
            canvas = research_service._default_research_flow_canvas()
            for node in canvas["nodes"]:
                if node["id"] == "broad_search":
                    node["status"] = "done"
                if node["id"] == "theme_generation":
                    node["status"] = "running"
            return canvas

        def write_research_flow_canvas(self, data):
            self.saved = data
            return True

    service = _service(tmp_path)
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )
    monkeypatch.setattr(research_service, "_SERVICE", service)
    monkeypatch.setattr(research_service, "get_workspace", lambda: FakeWorkspace())
    monkeypatch.setattr(research_service, "record_research_scene_event", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="Research flow node is already running: theme_generation"):
        research_service.execute_research_flow_canvas_node(created["session"]["sessionId"], node_id="broad_search")


def test_llm_research_agent_runner_requires_search_tool_calls(tmp_path, monkeypatch):
    class FakeWorkspace:
        def read_research_agent_config(self):
            return {
                "agents": [
                    {
                        "key": "broad",
                        "promptFilename": "broad.md",
                        "templateId": "research_broad_explorer",
                        "llmConfigId": "research_broad",
                        "enabled": True,
                    }
                ]
            }

        def read_research_prompt(self, filename):
            return "Use search tools."

    class FakeClient:
        def invoke(self, messages, tools=None, metadata=None):
            class Response:
                content = '{"summary":"done"}'
                tool_calls = []

            return Response()

    monkeypatch.setattr("core.research.agent_runner.get_workspace", lambda: FakeWorkspace())
    monkeypatch.setattr("core.research.agent_runner.get_llm_client", lambda profile_id=None: FakeClient())
    runner = LLMResearchAgentRunner(search_provider=DeterministicResearchSearchProvider())
    session = ResearchDiscoverySession(
        session_id=new_id("research-session"),
        open_goal="Find a theme",
        constraints="public sources",
        preferences="novel",
    )

    with pytest.raises(ValueError, match="did not call any search tools"):
        runner.run_search(phase="broad", session=session, suggested_queries=["ai scientist"], existing_sources=[])


def test_theme_discovery_draft_generates_five_persisted_candidates(tmp_path):
    service = _service(tmp_path)
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel problem perspective first",
        }
    )
    session_id = created["session"]["sessionId"]

    result = service.run_draft(session_id)

    assert result["summary"]["sourceCount"] > 0
    assert result["summary"]["evidenceCount"] > 0
    assert result["summary"]["candidateThemeCount"] == 5
    assert len([item for item in result["candidateThemes"] if item["status"] == "shortlisted"]) == 5
    assert result["candidateThemes"][0]["scores"]["noveltyGap"] >= 75

    reopened = service.get_session(session_id)
    assert reopened["summary"]["candidateThemeCount"] == 5


def test_theme_discovery_records_agent_search_report_and_provider_attempts(tmp_path):
    service = _service(tmp_path)
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel problem perspective first",
        }
    )
    session_id = created["session"]["sessionId"]

    result = service.run_broad_search(session_id)

    run = result["searchRuns"][0]
    execution = run["modelProfile"]["searchExecution"]
    agent_execution = run["modelProfile"]["agentExecution"]
    report = result["agentReport"]
    assert agent_execution["executionMode"] == "deterministic_test_double"
    assert agent_execution["trace"][0]["kind"] == "memory"
    assert agent_execution["trace"][1]["kind"] == "agent"
    assert run["modelProfile"]["runtimeDataPolicy"] == "live-public-network-only-by-default"
    assert len(execution["attempts"]) == 12
    assert execution["sourceCounts"]["paper"] > 0
    assert report["queries"] == run["queries"]
    assert report["sourceKindCounts"]["paper"] > 0
    assert report["mode"] == "mixed_or_legacy"
    assert "legacy placeholder" in " ".join(report["warnings"])


def test_theme_discovery_persists_live_agent_trace_while_step_runs(tmp_path):
    class InspectingRunner(DeterministicResearchAgentRunner):
        def run_search(self, *, phase, session, suggested_queries, existing_sources, trace_sink=None):
            if trace_sink:
                trace_sink({"kind": "agent", "title": "live trace probe", "detail": "visible before completion"})
            running = service.get_session(session.session_id)
            run = running["searchRuns"][0]
            live_trace = run["modelProfile"]["agentExecution"]["trace"]
            assert run["status"] == "running"
            assert live_trace[0]["title"] == "科研知识库预检"
            assert live_trace[1]["title"] == "live trace probe"
            return super().run_search(
                phase=phase,
                session=session,
                suggested_queries=suggested_queries,
                existing_sources=existing_sources,
                trace_sink=trace_sink,
            )

    search_provider = DeterministicResearchSearchProvider()
    service = ResearchThemeDiscoveryService(
        repository=ResearchRepository(root=tmp_path / "research"),
        search_provider=search_provider,
        agent_runner=InspectingRunner(search_provider=search_provider),
    )
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )

    result = service.run_broad_search(created["session"]["sessionId"])

    trace = result["searchRuns"][0]["modelProfile"]["agentExecution"]["trace"]
    assert trace[0]["title"] == "科研知识库预检"
    assert trace[1]["title"] == "live trace probe"
    assert any(item["kind"] == "tool" for item in trace)


def test_select_theme_and_generate_theme_card(tmp_path):
    service = _service(tmp_path)
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )
    session_id = created["session"]["sessionId"]
    draft = service.run_draft(session_id)
    theme_id = draft["candidateThemes"][0]["themeId"]

    selected = service.select_theme(session_id, theme_id)
    card_result = service.generate_theme_card(session_id, theme_id)

    assert selected["session"]["selectedThemeId"] == theme_id
    assert any(item["themeId"] == theme_id and item["status"] == "selected" for item in selected["candidateThemes"])
    assert len(card_result["themeCards"]) == 1
    assert card_result["themeCards"][0]["themeId"] == theme_id
    assert "AI Scientist" in card_result["themeCards"][0]["whyCompetitionFit"]
    assert card_result["events"][-1]["fields"]["trace"][0]["kind"] == "agent"


def test_rerun_search_marks_downstream_artifacts_stale(tmp_path):
    service = _service(tmp_path)
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )
    session_id = created["session"]["sessionId"]
    draft = service.run_draft(session_id)
    theme_id = draft["candidateThemes"][0]["themeId"]
    service.select_theme(session_id, theme_id)
    service.generate_theme_card(session_id, theme_id)

    rerun = service.run_deep_search(session_id)

    assert rerun["summary"]["staleThemeCount"] >= 1
    assert any(item["status"] == "stale" for item in rerun["themeCards"])


def test_evidence_extraction_persists_missing_evidence_requests(tmp_path):
    search_provider = DeterministicResearchSearchProvider()

    class MissingEvidenceRunner(DeterministicResearchAgentRunner):
        def extract_evidence(self, *, session, sources, existing_evidence, trace_sink=None):
            source = sources[0]
            evidence = [
                EvidenceRecord(
                    evidence_id="evidence-missing-probe",
                    session_id=session.session_id,
                    source_id=source.source_id,
                    claim="Current sources need a stronger dataset benchmark check.",
                    evidence_type="gap",
                    confidence="medium",
                    note="Missing benchmark evidence.",
                )
            ]
            trace = [{"kind": "agent", "title": "missing evidence probe", "detail": "request follow-up"}]
            return AgentEvidenceResult(
                evidence=evidence,
                missing_evidence_requests=["public benchmark evidence for falsifiable AI Scientist hypothesis"],
                trace=trace,
                profile={
                    "agentKey": "review",
                    "missingEvidenceRequests": ["public benchmark evidence for falsifiable AI Scientist hypothesis"],
                    "trace": trace,
                },
            )

    service = ResearchThemeDiscoveryService(
        repository=ResearchRepository(root=tmp_path / "research"),
        search_provider=search_provider,
        agent_runner=MissingEvidenceRunner(search_provider=search_provider),
    )
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )
    session_id = created["session"]["sessionId"]
    service.run_broad_search(session_id)
    service.run_deep_search(session_id)

    payload = service.extract_evidence(session_id)

    event = payload["events"][-1]
    assert event["eventCode"] == "evidence.extracted"
    assert event["fields"]["missingEvidenceRequests"] == [
        "public benchmark evidence for falsifiable AI Scientist hypothesis"
    ]


def test_deep_search_accepts_missing_evidence_requests_as_follow_up_queries(tmp_path):
    service = _service(tmp_path)
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )
    session_id = created["session"]["sessionId"]
    service.run_broad_search(session_id)

    payload = service.run_deep_search(
        session_id,
        evidence_requests=["public benchmark evidence for falsifiable AI Scientist hypothesis"],
    )
    deep_run = [item for item in payload["searchRuns"] if item["phase"] == "deep"][-1]

    assert any("public benchmark evidence" in query for query in deep_run["queries"])
    assert payload["events"][-1]["fields"]["evidenceRequests"] == [
        "public benchmark evidence for falsifiable AI Scientist hypothesis"
    ]


def test_research_theme_discovery_routes_are_mounted(tmp_path, monkeypatch):
    monkeypatch.setattr(research_service, "_SERVICE", _service(tmp_path))
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    create_response = client.post(
        "/api/research/theme-discovery/sessions",
        json={
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        },
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["session"]["sessionId"]

    draft_response = client.post(f"/api/research/theme-discovery/sessions/{session_id}/run-draft")
    assert draft_response.status_code == 200
    payload = draft_response.json()
    assert payload["summary"]["candidateThemeCount"] == 5
    theme_id = payload["candidateThemes"][0]["themeId"]

    select_response = client.post(
        f"/api/research/theme-discovery/sessions/{session_id}/themes/{theme_id}/select"
    )
    assert select_response.status_code == 200
    assert select_response.json()["session"]["selectedThemeId"] == theme_id

    deep_run_count = len([item for item in payload["searchRuns"] if item["phase"] == "deep"])

    rerun_response = client.post(f"/api/research/theme-discovery/sessions/{session_id}/run-deep-search")
    assert rerun_response.status_code == 200
    rerun_payload = rerun_response.json()
    deep_runs = [item for item in rerun_payload["searchRuns"] if item["phase"] == "deep"]
    assert len(deep_runs) == deep_run_count + 1
    assert deep_runs[-1]["status"] == "completed"
    assert rerun_payload["summary"]["sourceCount"] >= payload["summary"]["sourceCount"]
    assert rerun_payload["summary"]["staleThemeCount"] >= 1

    delete_response = client.delete(f"/api/research/theme-discovery/sessions/{session_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    assert delete_response.json()["sessionId"] == session_id
    assert all(item["sessionId"] != session_id for item in delete_response.json()["sessions"])
    assert client.get(f"/api/research/theme-discovery/sessions/{session_id}").status_code == 404


def test_research_flow_canvas_api_declares_utf8_json(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, root):
            self.root = root

        def get_research_flow_canvas_path(self):
            return self.root / "prompts" / "research" / "flow_canvas.json"

        def read_research_flow_canvas(self):
            return {}

    monkeypatch.setattr(research_service, "get_workspace", lambda: FakeWorkspace(tmp_path))
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    response = client.get("/api/research/flow-canvas")

    assert response.status_code == 200
    assert response.headers["content-type"].lower().startswith("application/json")
    assert "charset=utf-8" in response.headers["content-type"].lower()
    assert response.json()["nodes"][0]["label"] == "广撒网探索"


def test_public_search_provider_uses_configured_proxy(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, limit):
            return b"<feed xmlns=\"http://www.w3.org/2005/Atom\"></feed>"

    class FakeOpener:
        def open(self, request, *, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["user_agent"] = request.headers.get("User-agent")
            return FakeResponse()

    def fake_proxy_handler(mapping):
        captured["proxy_mapping"] = mapping
        return "proxy-handler"

    def fake_https_handler(*, context):
        captured["ssl_context"] = context
        return "https-handler"

    def fake_build_opener(*handlers):
        captured["handlers"] = handlers
        return FakeOpener()

    monkeypatch.setattr(
        providers,
        "get_network_config",
        lambda: SimpleNamespace(
            timeout=7,
            user_agent="Vibelution Test Agent",
            verify_ssl=False,
            proxy_enabled=True,
            proxy_url="http://127.0.0.1:7890",
        ),
    )
    monkeypatch.setattr(providers.urllib.request, "ProxyHandler", fake_proxy_handler)
    monkeypatch.setattr(providers.urllib.request, "HTTPSHandler", fake_https_handler)
    monkeypatch.setattr(providers.urllib.request, "build_opener", fake_build_opener)
    monkeypatch.setattr(providers.ssl, "_create_unverified_context", lambda: "ssl-context")

    result = PublicResearchSearchProvider(per_kind_limit=1).search_papers("ai scientist")

    assert result == []
    assert captured["timeout"] == 7
    assert captured["user_agent"] == "Vibelution Test Agent"
    assert captured["proxy_mapping"] == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
    assert captured["handlers"] == ("proxy-handler", "https-handler")
    assert captured["ssl_context"] == "ssl-context"


def test_public_search_provider_requires_proxy_url_when_enabled(monkeypatch):
    monkeypatch.setattr(
        providers,
        "get_network_config",
        lambda: SimpleNamespace(
            timeout=7,
            user_agent="Vibelution Test Agent",
            verify_ssl=True,
            proxy_enabled=True,
            proxy_url="",
        ),
    )

    with pytest.raises(ValueError, match="network.proxy_url is required"):
        PublicResearchSearchProvider(per_kind_limit=1).search_papers("ai scientist")


def test_theme_discovery_surfaces_search_configuration_errors(tmp_path, monkeypatch):
    class BrokenProvider(DeterministicResearchSearchProvider):
        provider_name = "broken-provider"

        def search_papers(self, query: str):
            raise ValueError("network.proxy_url is required when network.proxy_enabled is true")

    search_provider = BrokenProvider()
    service = ResearchThemeDiscoveryService(
        repository=ResearchRepository(root=tmp_path / "research"),
        search_provider=search_provider,
        agent_runner=DeterministicResearchAgentRunner(search_provider=search_provider),
    )
    created = service.create_session(
        {
            "openGoal": "Find a novel interdisciplinary AI Scientist research theme",
            "constraints": "Student team, public sources, competition MVP",
            "preferences": "Novel first",
        }
    )
    recorded: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        runtime_scene_service,
        "record_research_scene_event",
        lambda event_code, **kwargs: recorded.append((event_code, kwargs)),
    )

    with pytest.raises(ValueError, match="network.proxy_url is required"):
        service.run_broad_search(created["session"]["sessionId"])
    codes = [event_code for event_code, _kwargs in recorded]
    assert "search.broad.started" in codes
    assert "search.broad.failed" in codes
    failed = next(kwargs for event_code, kwargs in recorded if event_code == "search.broad.failed")
    assert failed["outcome"] == "failed"
    assert failed["fields"]["errorType"] == "ValueError"


def _service(tmp_path) -> ResearchThemeDiscoveryService:
    search_provider = DeterministicResearchSearchProvider()
    return ResearchThemeDiscoveryService(
        repository=ResearchRepository(root=tmp_path / "research"),
        search_provider=search_provider,
        agent_runner=DeterministicResearchAgentRunner(search_provider=search_provider),
    )


def _theme(session_id: str, *, title: str, question: str, score: float, novelty_path: str) -> CandidateTheme:
    return CandidateTheme(
        theme_id=new_id("theme"),
        session_id=session_id,
        title=title,
        one_line=title,
        interdisciplinary_combination=["computer science", "science of science"],
        core_question=question,
        novelty_path=novelty_path,  # type: ignore[arg-type]
        scores={
            "noveltyGap": score,
            "scientificValue": score,
            "technicalDepth": score,
            "interdisciplinaryAuthenticity": score,
            "verifiability": score,
            "competitionFit": score,
            "implementationFeasibility": score,
        },
        recommendation_score=score,
    )
