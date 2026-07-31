"""Structure pack guards for team_service pure extracts."""

from __future__ import annotations

from core.web.services import team_service as facade
from core.web.services.team import (
    ai_search_ranking,
    canvas_primitives,
    kind_helpers,
    system_bootstrap,
    system_teams,
)


def test_facade_reexports_canvas_primitives() -> None:
    assert facade._safe_token is canvas_primitives._safe_token
    assert facade._safe_float is canvas_primitives._safe_float
    assert facade._issue is canvas_primitives._issue
    assert facade.TeamCanvasValidationError is canvas_primitives.TeamCanvasValidationError
    assert facade.NODE_TYPES is canvas_primitives.NODE_TYPES
    assert facade.EDGE_TYPES is canvas_primitives.EDGE_TYPES


def test_facade_reexports_kind_helpers() -> None:
    assert facade._infer_team_kind is kind_helpers._infer_team_kind
    assert facade._infer_team_template_id is kind_helpers._infer_team_template_id
    assert facade._team_default_chat_room_purpose is kind_helpers._team_default_chat_room_purpose
    assert facade._team_kind_allows_member_agent_cascade is kind_helpers._team_kind_allows_member_agent_cascade
    assert facade.TEAM_KIND_DEFAULTS is kind_helpers.TEAM_KIND_DEFAULTS
    assert facade.TEAM_SOURCE_TO_KIND is kind_helpers.TEAM_SOURCE_TO_KIND
    assert facade.TEAM_ID_TO_KIND is kind_helpers.TEAM_ID_TO_KIND
    assert facade.DERIVED_TEAM_KINDS is kind_helpers.DERIVED_TEAM_KINDS


def test_facade_reexports_ai_search_ranking() -> None:
    assert facade._rank_ai_search_source_page_references is ai_search_ranking._rank_ai_search_source_page_references
    assert facade._ai_search_source_page_keywords is ai_search_ranking._ai_search_source_page_keywords
    assert facade._clean_ai_search_source_text is ai_search_ranking._clean_ai_search_source_text


def test_kind_helpers_infer_known_team_ids() -> None:
    assert kind_helpers.infer_team_kind({"teamId": "ai-search-team"}) == "ai_search"
    assert kind_helpers.infer_team_kind({"teamId": "research-team"}) == "research"
    assert kind_helpers.infer_team_kind({"teamSource": "knowledge_expansion"}) == "knowledge_expansion"
    assert kind_helpers.infer_team_kind({"teamKind": "custom"}) == "custom"
    assert kind_helpers.team_kind_allows_member_agent_cascade({"teamKind": "custom"}) is True
    assert kind_helpers.team_kind_allows_member_agent_cascade({"teamKind": "research"}) is False


def test_facade_reexports_system_bootstrap_control_plane() -> None:
    assert facade.request_system_team_bootstrap is system_bootstrap.request_system_team_bootstrap
    assert facade._run_system_team_bootstrap is system_bootstrap._run_system_team_bootstrap
    assert facade._run_system_team_bootstrap_discovery is system_bootstrap._run_system_team_bootstrap_discovery
    assert facade._system_team_bootstrap_required_steps is system_bootstrap._system_team_bootstrap_required_steps
    assert facade._system_team_bootstrap_state_snapshot_locked is system_bootstrap._system_team_bootstrap_state_snapshot_locked
    assert facade._record_system_team_bootstrap_event is system_bootstrap._record_system_team_bootstrap_event
    # Shared mutable control-plane state remains on the facade for route/test access.
    assert hasattr(facade, "_TEAM_SYSTEM_BOOTSTRAP_LOCK")
    assert hasattr(facade, "_TEAM_SYSTEM_BOOTSTRAP_THREAD")
    assert isinstance(facade._TEAM_SYSTEM_BOOTSTRAP_STATE, dict)
    assert facade.TEAM_SYSTEM_BOOTSTRAP_READY_CACHE_TTL_SECONDS == 30.0


def test_facade_reexports_system_teams_materialize() -> None:
    assert facade.ensure_ai_search_system_team is system_teams.ensure_ai_search_system_team
    assert facade.ensure_challenge_cup_research_team_agents is system_teams.ensure_challenge_cup_research_team_agents
    assert facade.ensure_knowledge_expansion_team_agents is system_teams.ensure_knowledge_expansion_team_agents
    assert facade.ensure_evolution_system_teams is system_teams.ensure_evolution_system_teams
    assert facade.evolution_system_teams_missing is system_teams.evolution_system_teams_missing
    assert facade.ai_search_system_team_missing is system_teams.ai_search_system_team_missing
    assert facade.challenge_cup_research_team_agents_need_repair is system_teams.challenge_cup_research_team_agents_need_repair
    assert facade.knowledge_expansion_team_agents_need_repair is system_teams.knowledge_expansion_team_agents_need_repair
    assert facade._ensure_evolution_system_team_in_state is system_teams._ensure_evolution_system_team_in_state
    assert facade._system_members_from_agents is system_teams._system_members_from_agents


def test_system_bootstrap_required_steps_orders_missing_checks(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(facade, "evolution_system_teams_missing", lambda: calls.append("evolution") or True)
    monkeypatch.setattr(facade, "ai_search_system_team_missing", lambda: calls.append("ai_search") or False)
    monkeypatch.setattr(facade, "challenge_cup_research_team_agents_need_repair", lambda: calls.append("challenge") or True)
    monkeypatch.setattr(facade, "knowledge_expansion_team_agents_need_repair", lambda: calls.append("knowledge") or False)

    steps = system_bootstrap._system_team_bootstrap_required_steps()
    assert steps == ["evolution_system_teams", "challenge_cup_research_team_agents"]
    assert calls == ["evolution", "ai_search", "challenge", "knowledge"]


def test_ai_search_ranking_filters_and_scores() -> None:
    refs = ai_search_ranking.rank_ai_search_source_page_references(
        [
            {"title": "Privacy policy", "url": "https://example.com/privacy"},
            {"title": "New AI model release", "url": "https://example.com/blog/model"},
            {"title": "Jobs", "url": "https://example.com/careers"},
        ],
        topic="AI model",
        source_name="Example",
        base_url="https://example.com/",
        max_results=5,
    )
    assert len(refs) == 1
    assert refs[0]["url"].endswith("/blog/model")
