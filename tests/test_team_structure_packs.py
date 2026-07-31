"""Structure pack guards for team_service pure extracts."""

from __future__ import annotations

from core.web.services import team_service as facade
from core.web.services.team import (
    ai_search,
    ai_search_ranking,
    canvas_normalize,
    canvas_primitives,
    chat_room_links,
    kind_helpers,
    research_organization,
    system_bootstrap,
    system_teams,
    team_crud,
    team_logging,
    team_membership,
    team_projection,
    team_repair,
    team_constants,
    team_store,
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


def test_facade_reexports_team_projection() -> None:
    assert facade._team_to_api is team_projection._team_to_api
    assert facade._team_to_compact_reference is team_projection._team_to_compact_reference
    assert facade._team_detail_to_api is team_projection._team_detail_to_api
    assert facade._members_to_api is team_projection._members_to_api
    assert facade._get_team_record is team_projection._get_team_record
    assert facade._agent_reference_maps is team_projection._agent_reference_maps
    assert facade._merged_agent_reference_maps is team_projection._merged_agent_reference_maps


def test_facade_reexports_team_membership() -> None:
    assert facade._find_active_team_for_agent is team_membership._find_active_team_for_agent
    assert facade._find_active_team_for_agent_in_state is team_membership._find_active_team_for_agent_in_state
    assert facade._unique_active_member_agent_ids is team_membership._unique_active_member_agent_ids
    assert facade._active_member_agent_ids is team_membership._active_member_agent_ids
    assert facade._active_member_session_ids is team_membership._active_member_session_ids
    assert facade._apply_team_contract is team_membership._apply_team_contract


def test_facade_reexports_team_logging() -> None:
    assert facade._record_team_event is team_logging._record_team_event
    assert facade._team_detail_log_fields is team_logging._team_detail_log_fields
    assert facade._team_detail_log_signature is team_logging._team_detail_log_signature
    assert facade._emit_team_detail_loaded is team_logging._emit_team_detail_loaded
    assert facade._emit_team_detail_rollup is team_logging._emit_team_detail_rollup
    assert facade._record_team_detail_loaded is team_logging._record_team_detail_loaded
    assert facade._record_team_membership_conflict is team_logging._record_team_membership_conflict
    assert facade._record_team_archive_rejected is team_logging._record_team_archive_rejected
    assert facade._record_archived_team_member_cascade_repaired is team_logging._record_archived_team_member_cascade_repaired
    assert facade._record_system_team_membership_conflict is team_logging._record_system_team_membership_conflict
    assert facade._record_system_team_sync_failed is team_logging._record_system_team_sync_failed
    # Shared mutable telemetry state remains on the facade for pack late-bind.
    assert hasattr(facade, "_TEAM_DETAIL_LOG_LOCK")
    assert isinstance(facade._TEAM_DETAIL_LOG_STATE, dict)
    assert facade.TEAM_DETAIL_LOG_SLOW_THRESHOLD_MS == 250
    assert facade.TEAM_DETAIL_LOG_ROLLUP_REPEAT_THRESHOLD == 5


def test_facade_reexports_team_store() -> None:
    assert facade.utc_now_iso is team_store.utc_now_iso
    assert facade._perf_counter is team_store._perf_counter
    assert facade._elapsed_ms is team_store._elapsed_ms
    assert facade._try_acquire_team_lock is team_store._try_acquire_team_lock
    assert facade._release_team_lock_if_acquired is team_store._release_team_lock_if_acquired
    assert facade._load_index is team_store._load_index
    assert facade._save_index is team_store._save_index
    assert facade._read_json is team_store._read_json
    assert facade._write_json is team_store._write_json
    assert facade._teams_root is team_store._teams_root
    assert facade._teams_index_path is team_store._teams_index_path
    assert facade._team_canvas_path is team_store._team_canvas_path
    assert facade._project_root is team_store._project_root
    assert facade._sync_project_bus_root is team_store._sync_project_bus_root
    assert facade._relative_path is team_store._relative_path
    assert facade._find_team is team_store._find_team
    assert facade._normalize_required_id is team_store._normalize_required_id
    assert facade._format_validation_error is team_store._format_validation_error
    # Shared mutable registry lock remains on the facade for pack late-bind.
    assert hasattr(facade, "_TEAM_LOCK")
    assert facade.SCHEMA_VERSION == 1
    assert facade.PROJECT_ROOT is not None


def test_facade_reexports_team_constants() -> None:
    assert facade.SCHEMA_VERSION is team_constants.SCHEMA_VERSION
    assert facade.CANVAS_KIND is team_constants.CANVAS_KIND
    assert facade.DEFAULT_TEAM_STATUS is team_constants.DEFAULT_TEAM_STATUS
    assert facade.TEAM_STATUSES is team_constants.TEAM_STATUSES
    assert facade.AI_SEARCH_SYSTEM_ROLES is team_constants.AI_SEARCH_SYSTEM_ROLES
    assert facade.AI_SEARCH_SOURCE_SCOPE_GROUPS is team_constants.AI_SEARCH_SOURCE_SCOPE_GROUPS
    assert facade.CHALLENGE_CUP_RESEARCH_TEAM_ROLES is team_constants.CHALLENGE_CUP_RESEARCH_TEAM_ROLES
    assert facade.KNOWLEDGE_EXPANSION_TEAM_ROLES is team_constants.KNOWLEDGE_EXPANSION_TEAM_ROLES
    assert facade.EVOLUTION_SYSTEM_TEAM_SPECS is team_constants.EVOLUTION_SYSTEM_TEAM_SPECS
    assert facade.AI_SEARCH_TEAM_ID is kind_helpers.AI_SEARCH_TEAM_ID
    assert facade.KNOWLEDGE_EXPANSION_TEAM_ID is kind_helpers.KNOWLEDGE_EXPANSION_TEAM_ID
    # Mutable locks/state remain on the facade.
    assert hasattr(facade, "_TEAM_LOCK")
    assert hasattr(facade, "_TEAM_SYSTEM_BOOTSTRAP_STATE")
    assert isinstance(facade._TEAM_DETAIL_LOG_STATE, dict)


def test_facade_reexports_team_repair() -> None:
    assert facade._repair_team is team_repair._repair_team
    assert facade._repair_index_state is team_repair._repair_index_state
    assert facade._repair_members is team_repair._repair_members
    assert facade._repair_archived_team_member_agents is team_repair._repair_archived_team_member_agents
    assert facade._prune_unavailable_derived_team_members is team_repair._prune_unavailable_derived_team_members


def test_facade_reexports_team_crud() -> None:
    assert facade.list_teams is team_crud.list_teams
    assert facade.list_teams_compact is team_crud.list_teams_compact
    assert facade.create_team is team_crud.create_team
    assert facade.get_team is team_crud.get_team
    assert facade.update_team is team_crud.update_team
    assert facade.archive_team is team_crud.archive_team
    assert facade.remove_agents_from_teams is team_crud.remove_agents_from_teams
    assert facade.restore_removed_agents_to_teams is team_crud.restore_removed_agents_to_teams
    assert facade.send_team_message is team_crud.send_team_message


def test_facade_reexports_research_organization() -> None:
    assert facade.ensure_research_team_from_organization is research_organization.ensure_research_team_from_organization
    assert facade._members_from_research_organization is research_organization._members_from_research_organization
    assert facade._canvas_from_research_organization is research_organization._canvas_from_research_organization
    assert facade._organization_reporting_edges is research_organization._organization_reporting_edges
    assert facade._sync_research_team_member_agent_roles is research_organization._sync_research_team_member_agent_roles


def test_facade_reexports_ai_search_runs() -> None:
    assert facade.list_ai_search_source_scope_runs is ai_search.list_ai_search_source_scope_runs
    assert facade.start_ai_search_source_scope_run is ai_search.start_ai_search_source_scope_run
    assert facade._default_ai_search_source_scope is ai_search._default_ai_search_source_scope
    assert facade._load_ai_search_source_scope is ai_search._load_ai_search_source_scope
    assert facade._execute_ai_search_query_card is ai_search._execute_ai_search_query_card
    assert facade._AiSearchSourcePageParser is ai_search._AiSearchSourcePageParser
    assert facade._ai_search_source_scope_path is ai_search._ai_search_source_scope_path


def test_facade_reexports_canvas_normalize() -> None:
    assert facade.get_team_canvas is canvas_normalize.get_team_canvas
    assert facade.save_team_canvas is canvas_normalize.save_team_canvas
    assert facade._normalize_canvas is canvas_normalize._normalize_canvas
    assert facade._normalize_node is canvas_normalize._normalize_node
    assert facade._validate_canvas is canvas_normalize._validate_canvas
    assert facade._normalize_members is canvas_normalize._normalize_members
    assert facade._default_canvas_for_team is canvas_normalize._default_canvas_for_team
    assert facade._ai_search_canvas_for_team is canvas_normalize._ai_search_canvas_for_team
    assert facade._default_nodes_for_members is canvas_normalize._default_nodes_for_members
    assert facade._default_edges_for_team is canvas_normalize._default_edges_for_team


def test_facade_reexports_chat_room_links() -> None:
    assert facade.sync_team_chat_room is chat_room_links.sync_team_chat_room
    assert facade.list_archived_team_linked_chat_room_ids is chat_room_links.list_archived_team_linked_chat_room_ids
    assert facade.repair_archived_team_chat_rooms is chat_room_links.repair_archived_team_chat_rooms
    assert facade._ensure_team_chat_room_link is chat_room_links._ensure_team_chat_room_link
    assert facade._team_chat_room_needs_sync is chat_room_links._team_chat_room_needs_sync
    assert facade._compact_chat_room is chat_room_links._compact_chat_room
    assert facade._sync_compact_team_chat_room_metadata is chat_room_links._sync_compact_team_chat_room_metadata


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
