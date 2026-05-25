"""Research theme discovery MVP tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.research.models import CandidateTheme, ResearchDiscoverySession, new_id
from core.research import providers
from core.research.providers import DeterministicResearchSearchProvider, PublicResearchSearchProvider
from core.research.repository import ResearchRepository
from core.research.scoring import calculate_recommendation_score, deduplicate_themes
from core.research.theme_discovery import ResearchThemeDiscoveryService
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
    report = result["agentReport"]
    assert run["modelProfile"]["runtimeDataPolicy"] == "live-public-network-only-by-default"
    assert len(execution["attempts"]) == 12
    assert execution["sourceCounts"]["paper"] > 0
    assert report["queries"] == run["queries"]
    assert report["sourceKindCounts"]["paper"] > 0
    assert report["mode"] == "mixed_or_legacy"
    assert "legacy placeholder" in " ".join(report["warnings"])


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

    service = ResearchThemeDiscoveryService(
        repository=ResearchRepository(root=tmp_path / "research"),
        search_provider=BrokenProvider(),
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
    return ResearchThemeDiscoveryService(
        repository=ResearchRepository(root=tmp_path / "research"),
        search_provider=DeterministicResearchSearchProvider(),
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
