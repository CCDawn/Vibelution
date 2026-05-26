"""Research theme discovery MVP tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.research.models import CandidateTheme, EvidenceRecord, ResearchDiscoverySession, new_id
from core.research import providers
from core.research.providers import DeterministicResearchSearchProvider, PublicResearchSearchProvider
from core.research.repository import ResearchRepository
from core.research.scoring import calculate_recommendation_score, deduplicate_themes
from core.research.theme_discovery import ResearchThemeDiscoveryService
from core.research.agent_templates import ensure_research_prompt_defaults
from core.research.agent_runner import AgentEvidenceResult, DeterministicResearchAgentRunner, LLMResearchAgentRunner
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import research_service


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
    assert {node["id"] for node in default_canvas["nodes"]} >= {"broad_search", "evidence_review", "theme_card"}
    assert any(edge["condition"] == "needs_evidence" for edge in default_canvas["edges"])

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
                "condition": "completed",
            }
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    saved = research_service.save_research_flow_canvas(payload)

    assert saved["nodes"][0]["label"] == "主题探针"
    assert saved["edges"][0]["source"] == "topic_probe"
    assert events[-1][0][0] == "research.flow_canvas.updated"
    assert research_service.get_research_flow_canvas()["nodes"][1]["type"] == "decision"


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
    assert agent_execution["trace"][0]["kind"] == "agent"
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
            assert live_trace[0]["title"] == "live trace probe"
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
    assert trace[0]["title"] == "live trace probe"
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


def test_theme_discovery_surfaces_search_configuration_errors(tmp_path):
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

    with pytest.raises(ValueError, match="network.proxy_url is required"):
        service.run_broad_search(created["session"]["sessionId"])


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
