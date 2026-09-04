"""Team workflow orchestration and candidate-store service."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from config.paths import resolve_workspace_home
from config.public_config import build_effective_config, load_public_config
from core.chat.conversation_ledger import load_conversation_events
from core.infrastructure import developer_sandbox
from core.llm import LLMClient, LLMInvocationContext, invoke_llm
from core.research import experiment_contract, formal_runner, smoke_runner
from core.runtime_manager import work_run_store
from core.web.services import agent_directory_service, candidate_schema_registry, chat_room_service, data_processing_service, session_service, team_knowledge_service, team_service
from core.web.services.runtime_scene_service import record_runtime_scene_event
from core.web.services.team_workflow.source_collection_context import (
    compact_source_collection_stage_task_context as _compact_source_collection_stage_task_context,
    normalize_source_collection_context_mode as _normalize_source_collection_context_mode,
    source_collection_context_continuation_hint as _source_collection_context_continuation_hint,
    source_collection_context_record_continuation_hint as _source_collection_context_record_continuation_hint,
)
from core.web.services.team_workflow.source_collection_projection import (
    latest_source_collection_stage_task as _latest_source_collection_stage_task,
    source_collection_stage_card_blocking_reasons as _source_collection_stage_card_blocking_reasons,
    source_collection_stage_card_projection as _source_collection_stage_card_projection,
    source_collection_stage_task_card_summary as _source_collection_stage_task_card_summary,
    source_collection_stage_task_coverage_summary as _source_collection_stage_task_coverage_summary,
    source_collection_stage_user_status_label as _source_collection_stage_user_status_label,
    source_collection_stage_user_summary as _source_collection_stage_user_summary,
    source_collection_summary_payload_status as _source_collection_summary_payload_status,
)
from core.web.services.team_workflow.research_memory_context import (
    build_research_memory_context as _build_research_memory_context,
)
from core.web.services.team_workflow.source_collection_stage_tasks import (
    source_collection_evidence_fetch_progress as _source_collection_evidence_fetch_progress,
    source_collection_relations_allowed_endpoint_ids as _source_collection_relations_allowed_endpoint_ids,
    source_collection_stage_can_materialize_formal_knowledge as _source_collection_stage_can_materialize_formal_knowledge,
    source_collection_stage_completion_gate as _source_collection_stage_completion_gate,
    source_collection_stage_round_status_from_task_refs as _source_collection_stage_round_status_from_task_refs,
    source_collection_stage_task_checklist as _source_collection_stage_task_checklist,
    source_collection_stage_task_title as _source_collection_stage_task_title,
    source_collection_stage_task_tool_progress as _source_collection_stage_task_tool_progress,
    source_collection_stage_task_writeback_contract as _source_collection_stage_task_writeback_contract_payload,
)
from core.web.services.team_workflow.orchestration_core import (
    ensure_team_workflow_orchestration,
    get_team_workflow_orchestration,
)
from core.web.services.team_workflow.research_projects import (
    LEGACY_PROJECT_ID,
    ResearchProjectError,
    ResearchProjectNameLockedError,
    ResearchProjectNotFoundError,
    activate_research_project,
    create_research_project,
    get_active_research_project,
    get_research_project,
    get_research_project_progress,
    list_research_projects,
    lock_research_project_name,
    resolve_research_project_workspace_root,
    resolve_team_program_root,
    update_research_project,
)
from core.web.services.team_workflow.research_project_agent_sessions import (
    ResearchProjectAgentSessionError,
    research_project_agent_role_label,
    resolve_research_project_identity,
    resolve_research_project_identity_from_record,
    resolve_research_project_agent_session,
)
from core.web.services.team_workflow.research_project_agent_tasks import (
    ResearchProjectAgentTaskError,
    get_research_project_agent_task_context,
    get_research_project_agent_task_status,
    reconcile_research_project_agent_task_statuses,
    require_research_project_agent_task,
    require_research_project_experiment_plan,
    start_research_project_agent_task,
    update_research_project_agent_task_status,
)
from core.web.services.team_workflow.source_collection.candidates import (
    extract_source_collection_candidates,
    import_data_record_as_source_candidate,
    list_candidate_store,
    register_candidate_source,
    validate_candidate_store,
)
from core.web.services.team_workflow.source_collection.runs import (
    execute_source_collection_search,
    get_source_collection_summary,
    load_source_collection_work_run_summary,
    reset_research_project_progress,
    reset_research_project_source_collection,
    start_source_collection_run,
    start_source_collection_search_background,
)
from core.web.services.team_workflow.source_collection.search_execution import (
    _source_collection_search_background_response,
    _run_source_collection_search_background,
    _execute_source_collection_search_impl,
    _sync_source_collection_stage_round_after_search,
    _source_collection_stage_round_status_after_search,
    _execute_source_collection_query,
    _execute_qwen_deep_search_for_run,
    _execute_arxiv_source_collection_query,
    _execute_openalex_source_collection_query,
    _source_collection_search_quality_terms,
    _source_collection_search_result_quality_gate,
    _source_collection_record_from_search_result,
    _source_collection_record_search_trace,
    _source_collection_assigned_queries,
    _source_collection_next_runnable_query_ids,
    _source_collection_attempted_query_ids,
    _source_collection_existing_identity_records,
    _source_collection_exclusion_match,
    _record_source_collection_exclusion_hit,
    _source_collection_execution_event,
    _append_source_collection_execution_artifacts,
    _source_collection_query_event_summaries,
    _source_collection_record_identity_key,
)
from core.web.services.team_workflow.source_collection.writeback_materialize import (
    _source_collection_stage_writeback_candidate_id,
    _source_collection_stage_writeback_record_id,
    _source_collection_stage_writeback_record_extractions,
    _source_collection_stage_writeback_candidate_extractions,
    _source_collection_stage_writeback_candidate_coverage,
    _source_collection_stage_writeback_content_extraction_summary,
    _source_collection_stage_writeback_record_extraction_decision,
    _source_collection_stage_writeback_record_exclusion_reason,
    _source_collection_stage_writeback_record_extraction_evidence,
    _materialize_source_collection_stage_writeback_content_extraction,
    _materialize_source_collection_stage_writeback_record_extractions,
    _materialize_source_collection_stage_writeback_sources,
    _materialize_source_collection_stage_writeback_quality,
    _source_collection_stage_writeback_closure_summary,
    _materialize_source_collection_stage_writeback_candidate_graph,
    _materialize_source_collection_stage_writeback_knowledge_ingestion,
    _source_collection_stage_writeback_candidate_decisions,
    _source_collection_stage_writeback_quality_decision,
    _source_collection_stage_writeback_quality_notes,
    _source_collection_stage_writeback_quality_summary,
    _source_collection_stage_writeback_candidate_graph_summary,
    _source_collection_stage_writeback_agent_graph_payload,
    _merge_source_collection_stage_writeback_agent_graph,
    _source_collection_stage_writeback_steward_pack_output,
    _source_collection_stage_writeback_standardize_steward_pack_output,
    _source_collection_stage_writeback_approved_candidate_ids,
    _source_collection_stage_writeback_target_domain,
    _source_collection_stage_writeback_approved_confidence,
    _source_collection_stage_writeback_knowledge_confidence,
    _source_collection_stage_writeback_knowledge_ingestion_summary,
    _source_collection_stage_writeback_child_log_payload,
    _source_collection_stage_writeback_materialization_child_summary,
    _source_collection_stage_writeback_source_leads,
    _source_collection_stage_writeback_invalid_sources,
    _materialize_source_collection_stage_invalid_sources,
    _source_collection_stage_writeback_lead_fingerprint,
    _source_collection_stage_writeback_record_payload,
    _source_collection_stage_writeback_authors,
    _source_collection_stage_writeback_materialization_summary,
    _merge_source_collection_stage_writeback_evidence_fetch_attempts,
    _merge_source_collection_stage_writeback_result_payload,
    _merge_source_collection_stage_writeback_result_pair,
    _merge_source_collection_stage_writeback_array_group,
    _source_collection_stage_writeback_array_items,
    _merge_source_collection_stage_writeback_array_items,
    _normalize_source_collection_stage_writeback_result_payload,
    _normalize_source_collection_stage_writeback_result_metadata,
    _normalize_source_collection_stage_writeback_result_metadata_dict,
    _normalize_source_collection_stage_writeback_result_metadata_value,
    _source_collection_stage_writeback_result_metadata_max_items,
    _parse_source_collection_stage_writeback_result_text,
)
from core.web.services.team_workflow.source_collection.residual import (
    _append_source_collection_seed,
    _build_source_collection_search_plan,
    _clean_source_collection_stage_agent_sessions_for_new_round,
    _coerce_source_collection_storage_path_soft,
    _crossref_authors,
    _crossref_date,
    _data_record_evidence_refs,
    _data_record_ref,
    _decorate_source_collection_work_run_snapshot,
    _find_source_candidate_by_identity_key,
    _first_crossref_text,
    _import_source_collection_local_workspace_sources,
    _import_source_collection_managed_root_sources,
    _load_candidate_store,
    _load_source_collection_exclusion_store,
    _merge_candidate_store_payloads,
    _load_stage_round_store,
    _managed_category_policy_enabled,
    _managed_root_title_from_parse,
    _mark_source_collection_work_run_stale,
    _new_record_id,
    _normalize_managed_root_request,
    _normalize_source_collection_exclusion_reason,
    _normalize_source_collection_prompt_cache_requirement,
    _normalize_source_collection_roles,
    _persist_source_collection_work_run,
    _bridge_managed_root_records_to_candidates,
    _create_managed_root_records,
    _record_source_collection_exclusion,
    _record_source_collection_summary_timing,
    _record_workflow_event,
    _resolve_candidate_store_write_run,
    _resolve_source_collection_record_id,
    _scan_managed_root_for_import,
    _source_candidate_payload_from_data_record,
    _source_collection_agent_context_next_actions,
    _source_collection_agent_graph_edges,
    _source_collection_agent_graph_nodes,
    _source_collection_agent_graph_theme_id,
    _source_collection_agent_graph_theme_node_id,
    _source_collection_agent_id,
    _source_collection_agent_role_for_id,
    _source_collection_assignment_scope,
    _source_collection_assignment_stage_summary,
    _source_collection_background_snapshot_is_active,
    _source_collection_candidate_count_for_run,
    _source_collection_candidates_for_run,
    _source_collection_collection_mode,
    _source_collection_completion_superseded_stage_cutoffs,
    _source_collection_count,
    _source_collection_current_stage_agent_ids,
    _source_collection_current_stage_agent_ids_by_stage,
    _source_collection_data_processing_source_type,
    _source_collection_data_run_exists,
    _source_collection_default_stage_agent,
    _source_collection_dynamic_delta_contract,
    _source_collection_exclusion_scope,
    _source_collection_exclusion_store_default,
    _source_collection_exclusion_store_path,
    _source_collection_existing_query_ids,
    _source_collection_expected_action,
    _source_collection_extract_doi,
    _source_collection_extraction_citation_items,
    _source_collection_extraction_claim_items,
    _source_collection_extraction_evidence_ledger,
    _source_collection_extraction_has_evidence_anchor,
    _source_collection_extraction_key_finding_items,
    _source_collection_extraction_key_finding_texts,
    _source_collection_filter_active_records,
    _source_collection_identity_key,
    _source_collection_is_text_model,
    _source_collection_local_file_summary,
    _source_collection_local_file_title,
    _source_collection_local_scan_summary,
    _source_collection_managed_root_record_payload,
    _source_collection_managed_scan_summary,
    _source_collection_matching_assignments,
    _source_collection_model_library,
    _source_collection_normalized_doi,
    _source_collection_normalized_url,
    _source_collection_open_assignments,
    _source_collection_output_query_ids,
    _source_collection_owner_agent_id,
    _source_collection_phase_close_gate,
    _source_collection_prompt_cache_mode,
    _source_collection_prompt_cache_model_score,
    _source_collection_prompt_cache_policy,
    _source_collection_prompt_cache_policy_ref,
    _source_collection_queries_for_role,
    _source_collection_query_seeds,
    _source_collection_query_text,
    _source_collection_record_extraction_effective_texts,
    _source_collection_record_extraction_has_effective_content,
    _source_collection_record_extraction_kept_status,
    _source_collection_record_extraction_metadata,
    _source_collection_record_id_suffix_lookup,
    _source_collection_record_identity_or_record_key,
    _source_collection_record_is_excluded,
    _source_collection_record_source_snapshot,
    _source_collection_resolve_prompt_cache_model,
    _source_collection_arxiv_atom_entries,
    _source_collection_result_from_arxiv_entry,
    _source_collection_openalex_abstract,
    _source_collection_result_from_openalex_work,
    _source_collection_result_from_crossref_item,
    _source_collection_qwen_url_doi,
    _source_collection_qwen_url_arxiv_id,
    _source_collection_qwen_url_display_title,
    _source_collection_qwen_answer_context,
    _source_collection_result_from_qwen_source_url,
    _source_collection_result_identity_key,
    _source_collection_role_assignment_inputs,
    _source_collection_run_belongs_to_research_project,
    _source_collection_run_belongs_to_team,
    _source_collection_run_context_bundle,
    _source_collection_run_has_usable_outputs,
    _source_collection_run_owner_research_project_id,
    _source_collection_run_workflow_root,
    _source_collection_task_store_search_roots,
    _source_collection_search_languages,
    _source_collection_search_plan_ref,
    _source_collection_seed_from_input_ref,
    _source_collection_snapshot_is_age_stale,  # noqa: F401 - facade re-export
    _source_collection_snapshot_stale_ms,  # noqa: F401 - facade re-export
    _source_collection_source_category,
    _source_collection_source_types,
    _source_collection_stable_prefix_contract,
    _source_collection_stage_id_for_agent_role,
    _source_collection_stage_invalid_source_record,
    _source_collection_stage_quality_materialization_child_summary,
    _source_collection_stage_records_for_run,
    _source_collection_stage_retry_ancestor_results,
    _source_collection_stage_round_ref_for_run,
    _source_collection_stage_task_has_evidence_gaps,
    _source_collection_storage_artifact_paths,
    _source_collection_storage_artifacts,
    _source_collection_storage_refs,
    _source_collection_storage_target_path,
    _source_collection_team_identity_snapshot,
    _source_collection_team_member_snapshot,
    _source_collection_work_run_snapshot_is_stale,
    _source_collection_work_run_store,
    _source_collection_work_run_terminal_phase,
    _source_collection_work_run_terminal_status,
    _source_collection_work_run_terminal_summary,
    _source_collection_workflow_kind,
    _source_collection_writeback_contract,
    _source_kind_from_data_record,
    _stage_rounds,
    _stage_source_collection_payload,
    _sync_source_collection_stage_round_from_latest_work_run,
    _update_source_candidate_content_extraction,
    _validate_source_manifest,
    _write_source_collection_exclusion_store,
    _write_source_collection_search_plan,
    get_source_collection_exclusion_ledger,
)
from core.web.services.team_workflow.workflow_ops import (
    _active_stage_round,
    _build_stage_round,
    _continued_stage_round_payload,
    _default_workflow,
    _find_stage_round,
    _legacy_research_lifecycle_memory_contexts,
    _load_or_create_workflow,
    _reconcile_superseded_research_stage_rounds,
    _research_memory_context_summary,
    _stage_phase_status,
    _stage_round_store_path,
    _submit_team_workflow_inbox_via_kernel,
    _team_workflow_inbox_message_from_kernel_delivery,
    _team_workflow_kernel_delivery,
    _team_workflow_root,
    _validate_algorithm_hypothesis_candidate,
    _validate_mechanism_mapping_candidate,
    _validate_neuro_mechanism_candidate,
    export_deliverables,
    propose_iteration,
    validate_candidate_record,
)
from core.web.services.team_workflow.facade_helpers import (
    _active_research_loop_projection,
    _append_jsonl,
    _arxiv_search_query,
    _arxiv_search_url,
    _openalex_search_url,
    _dashscope_search_api_key,
    _dashscope_search_model,
    _qwen_deep_search_request_payload,
    _qwen_deep_search_task,
    _qwen_deep_search_max_output_tokens,
    _DASHSCOPE_RESPONSES_ENDPOINT,
    _best_research_loop_evidence_id,
    _bounded_log_items,
    _bounded_text_items,
    _candidate_needs_rework,
    _clamp_score,
    _compact_text,
    _crossref_search_url,
    _current_research_stage,
    _decode_local_workspace_sample,
    _dedupe_text_values,
    _ensure_project_child,
    _filtered_candidates,
    _find_candidate_by_id,
    _find_candidate_imported_from_data_record,
    _first_non_empty_text,
    _has_any_list_value,
    _has_citation_anchor,
    _has_neuro_term_or_unknown,
    _has_value,
    _is_over_analogy_risky,
    _load_data_processing_record,
    _looks_like_url,
    _metadata_text_values,
    _normalize_candidate_type,
    _normalize_int,
    _normalize_metadata,
    _normalize_metadata_list,
    _normalize_metadata_value,
    _normalize_rating_enum,
    _normalize_ref_list,
    _normalize_required_id,
    _normalize_stage_start_mode,
    _normalize_stage_type,
    _normalize_text_list,
    _normalize_workflow_kind,
    _open_local_path,
    _page_numbers_from_scope,
    _parse_first_json_object,
    _payload_score,
    _project_root,
    _read_jsonl,
    _relative_path,
    _repair_workflow,
    _requires_terminology_uncertain,
    _research_stage_boundaries,
    _risk_flags_include,
    _safe_token,
    _slice_first_json_object,
    _source_extraction_anchor_id,
    _stage_agent_binding_warnings,
    _stage_default_goal,
    _stage_default_topic,
    _stage_label,
    _stage_memory_record,
    _stage_next_actions,
    _stage_planning_contract,
    _stage_query_seeds,
    _stage_readiness,
    _stage_upstream_round_ids,
    _strip_html,
    _suggest_stage_query_seeds,
    _sync_owner_policy,
    _sync_transfer_policy,
    _team_workflow_kernel_summary,
    _trim_text,
    _upsert_active_item,
    _workflow_path,
    _workflow_timestamp_sort_key,
    _workflow_to_api,
    _write_json,
    utc_now_iso,
)
from core.web.services.team_workflow.source_collection.stage_reconcile import (
    _source_collection_stage_task_writeback_contract,
    _source_collection_finding_prior_query_memory_message,
    _normalize_source_collection_stage_id,
    _normalize_source_collection_agent_role,
    _ensure_source_collection_stage_agent_direct_session,
    _source_collection_stage_session_previous_round_evidence,
    _ensure_source_collection_stage_agent_session_isolated,
    _attach_source_collection_stage_card_projections,
    _source_collection_stage_session_task_store_path,
    _find_source_collection_context_message,
    _source_collection_stage_session_task_boundaries,
    _source_collection_memory_steward_action_packet,
    _normalize_source_collection_stage_session_task_status,
    _load_source_collection_stage_session_task_store,
    _write_source_collection_stage_session_task_store,
    _source_collection_stage_session_tasks,
    _reconcile_source_collection_stage_session_task_turn_status,
    _reconcile_source_collection_stage_session_task_retry_coverage,
    _reconcile_source_collection_stage_session_tasks,
    _reconcile_source_collection_stage_session_tasks_for_run,
    _reconcile_source_collection_stage_session_task,
    _source_collection_stage_session_task_with_continuation_turn,
    _source_collection_stage_task_turn_ids,
    _source_collection_stage_task_turn_id_sequence,
    _source_collection_stage_session_task_turn_references_task,
    _source_collection_stage_task_id_from_metadata,
    _source_collection_stage_task_id_from_tool_call,
    _repair_missing_source_collection_stage_round,
    _source_collection_stage_task_refs,
    _source_collection_stage_cards_projection,
    _source_collection_stage_tasks_for_current_team,
    _source_collection_stage_task_groups_after_completion_supersession,
    _source_collection_stage_task_superseded_by_completion,
    _reconcile_source_collection_stage_session_task_sources,
    _reconcile_source_collection_stage_session_task_completion_gate,
    _reconcile_source_collection_stage_session_task_from_turn_result,
    _source_collection_stage_session_task_turn_result,
    _source_collection_stage_conversation_events,
    _source_collection_stage_session_task_turn_journal_result,
    _source_collection_stage_session_task_completion_snapshot_result,
    _source_collection_stage_task_status_from_turn_result,
    _rank_source_collection_context_records,
    _rank_source_collection_context_candidates,
    _source_collection_context_run_summary,
    _source_collection_context_task_summary,
    _source_collection_context_assignment_summary,
    _source_collection_context_record_summary,
    _source_collection_context_candidate_summary,
    _source_collection_stage_retry_focus,
    _source_collection_stage_evidence_retry_focus,
    _find_source_collection_stage_session_task,
    _find_source_collection_stage_session_task_by_id,
    _upsert_source_collection_stage_session_task,
    _source_collection_stage_task_idempotency_key,
    _source_collection_stage_task_tool_progress_from_trace,
    _source_collection_stage_persisted_writeback_after_turn,
    _source_collection_stage_task_trace_start_sequence,
    _source_collection_stage_task_trace_end_sequence,
    _source_collection_stage_event_metadata,
    _source_collection_stage_tool_calls_from_event,
    _source_collection_stage_tool_call_name,
    _source_collection_stage_tool_call_args,
    _source_collection_stage_tool_call_succeeded,
    _source_collection_stage_task_tool_item_id,
    _source_collection_stage_task_chat_route,
    _source_collection_agent_context_message,
    _source_collection_stage_previous_attempt_lines,
    _source_collection_stage_task_has_missing_coverage,
    _source_collection_stage_task_needs_writeback_resume,
    _source_collection_stage_task_context_mode,
    _source_collection_stage_session_task_message,
    _sync_stage_round_with_source_collection_stage_task,
    _latest_stage_round,
    _stage_round_number,
    _record_source_collection_stage_task_tool_policy_event,
)
from core.web.services.team_workflow.source_collection.stages import (
    get_source_collection_stage_task_context,
    reconcile_source_collection_stage_session_task_after_turn,
    seed_source_collection_agent_session_context,
    start_source_collection_stage_session_task,
    writeback_source_collection_stage_session_task,
)
from core.web.services.team_workflow.source_collection.storage import (
    open_source_collection_storage_target,
)
from core.web.services.team_workflow.experiment import (
    bind_frozen_protocol_to_experiment_plan,
    create_experiment_plan,
    complete_experiment_hypothesis_from_design,
    create_experiment_plan_revision_from_hypothesis,
    create_experiment_plan_revision_from_iteration,
    execute_experiment_full_run,
    freeze_experiment_design,
    get_experiment_method_catalog,
    get_experiment_planning_status,
    materialize_experiment_proxy_hypothesis,
    prepare_experiment_full_run,
    reconcile_experiment_knowledge_ingestion,
    register_experiment_baseline_artifact,
    register_experiment_full_run_result,
    register_experiment_smoke_result,
    request_experiment_result_knowledge_ingestion,
    resume_experiment_hypothesis,
    run_experiment_smoke_run,
)
from core.web.services.team_workflow.challenge_question_runs import (
    challenge_question_run_summary,
    bind_challenge_research_task_model,
    derive_challenge_required_model_policy,
    get_challenge_question_run_detail,
    get_challenge_question_run_status,
    normalize_challenge_research_task_policy,
    publish_research_project_challenge_question_output,
    register_challenge_task_model_evidence,
    register_challenge_question_output,
    review_challenge_question_output,
)
from core.web.services.team_workflow.challenge_program import (
    build_competition_program_projection,
    build_challenge_submission_readiness,
)
from core.web.services.team_workflow.challenge_cup_dev_controls import (
    ChallengeCupDevControlsError,
    DevControlsStorageError,
    DevFlowConflict,
    get_challenge_cup_catalog_overview,
    get_challenge_cup_dev_control_snapshot,
    get_challenge_cup_token_usage,
    run_challenge_cup_dev_batch,
    run_challenge_cup_dev_readiness,
)
from core.web.services.team_workflow.challenge_catalog_readiness import (
    CatalogReadinessStorageError,
    get_catalog_hypothesis_flow_readiness,
)
from core.web.services.team_workflow.experiment_kernel import (
    _require_formal_full_run_ready,
    _require_explicit_experiment_design_frozen,
    _record_formal_full_run_execution,
    _experiment_result_steward_notification_child_log_payload,
    _load_experiment_plan_store,
    _research_stage_memory_context,
    _experiment_plan_revision,
    _experiment_design_is_frozen,
    _latest_frozen_experiment_design,
    _best_validated_experiment_plan,
    _experiment_lifecycle_projection,
    _experiment_planning_status,
    _select_experiment_stage_round,
    _select_experiment_hypothesis_candidates,
    _build_experiment_plan_record,
    _experiment_hypothesis_candidates,
    _experiment_hypothesis_is_ready,
    _experiment_hypothesis_review_state,
    _experiment_hypothesis_summaries,
    _experiment_hypothesis_summary,
    _experiment_hypothesis_missing_fields,
    _experiment_proxy_hypothesis_fingerprint,
    _find_reusable_experiment_proxy_hypothesis,
    _scientific_hypothesis_completion_fingerprint,
    _find_reusable_scientific_hypothesis_completion,
    _scientific_hypothesis_design_request,
    _build_scientific_hypothesis_completion_record,
    _build_experiment_proxy_hypothesis_record,
    _find_experiment_plan,
    _experiment_baseline_artifact_record,
    _experiment_smoke_result_record,
    _experiment_full_run_result_record,
    _experiment_result_ingestion_pack_record,
    _notify_knowledge_steward_for_experiment_result,
    _refresh_experiment_bounded_smoke_readiness,
    _refresh_experiment_plan_readiness,
    _refresh_hypothesis_progress,
    _hypothesis_progress_find,
    _hypothesis_progress_plan_tracks,
    _hypothesis_progress_summary,
    _active_experiment_smoke_evidence,
    _experiment_plan_checklist,
    _experiment_checklist_item,
    _experiment_planning_gaps,
    _experiment_planning_readiness_reason,
    _experiment_planning_next_actions,
    _experiment_planning_boundaries,
    _experiment_plans,
    _active_experiment_plan,
    _experiment_plan_store_path,
)
from core.web.services.team_workflow.research_loop import (
    get_research_stage_round_status,
    retry_research_stage_round_coordination,
    retry_research_stage_round_memory_record,
    start_research_stage_round,
)
from core.web.services.team_workflow.knowledge import (
    extract_candidate_source_pages,
    draft_paper_note_from_source_candidate,
    extract_neuro_mechanism_from_paper_note,
    map_mechanism_to_abstraction,
    generate_algorithm_hypothesis_from_mechanism_mapping,
    decide_research_review,
    validate_prd,
    sync_official_research_graph,
    rollback_official_research_graph,
    plan_paper_note_chunks_from_source_candidate,
    get_paper_note_chunk_status,
    assess_source_candidate_quality,
    assess_source_quality_batch,
    get_source_quality_status,
    get_knowledge_ingestion_status,
    get_official_model_evidence_status,
    register_official_model_evidence,
    get_team_workflow_coordination_status,
    build_candidate_graph,
    run_knowledge_ingestion_precheck,
    submit_transfer_request,
    decide_transfer_request,
    build_local_research_model_task,
    record_local_research_model_output,
    invoke_local_research_model,
    submit_steward_pack_to_knowledge_ingestion,
    review_steward_pack_knowledge_ingestion,
    start_knowledge_collection_completion_background,
    run_knowledge_collection_completion,
    start_knowledge_collection_ingestion_background,
    run_knowledge_collection_ingestion,
    validate_local_research_model_output,
)
from core.web.services.team_workflow.knowledge_kernel import (
    _source_collection_stage_candidate_graph_materialization_child_summary,
    _source_collection_stage_knowledge_ingestion_materialization_child_summary,
    _source_collection_stage_knowledge_ingestion_child_log_payload,
    _attach_candidate_graph_stage_writeback_metadata,
    _research_review_checklist,
    _team_aggregate_workflow_scope,
    _notify_knowledge_steward_for_ingestion,
    _record_knowledge_steward_activation_event,
    _knowledge_steward_activation_log_payload,
    _resolve_team_review_agent_id,
    _knowledge_ingestion_work_run_store,
    _persist_knowledge_ingestion_work_run,
    _knowledge_ingestion_snapshot_is_active,
    _decorate_knowledge_ingestion_work_run_snapshot,
    _knowledge_collection_failed_step_for_snapshot,
    _knowledge_ingestion_background_response,
    _knowledge_collection_completion_payload,
    _knowledge_collection_completion_step,
    _knowledge_base_raw_id,
    _knowledge_base_scoped_id_for_team,
    _knowledge_collection_completion_steps_for_snapshot,
    _knowledge_collection_flow_step_status,
    _knowledge_collection_flow_node_status,
    _knowledge_collection_completion_flow_visualization,
    _knowledge_collection_completion_log_payload,
    _knowledge_collection_completion_steps_from_result,
    _attach_knowledge_completion_failure_payload,
    _run_knowledge_collection_completion_background,
    _run_knowledge_collection_ingestion_background,
    _local_research_output_state,
    _build_candidate_graph_payload,
    _candidate_graph_node,
    _candidate_is_archived,
    _candidate_graph_edges,
    _candidate_graph_edge,
    _candidate_ready_for_agent_graph,
    _candidate_allowed_for_agent_graph_input,
    _knowledge_collection_fingerprint,
    _candidate_knowledge_collection_fingerprint,
    _find_reusable_candidate_graph,
    _find_reusable_steward_pack,
    _latest_candidate_record,
    _dedupe_candidate_sequence,
    _candidate_precheck_ref,
    _build_knowledge_ingestion_precheck_output,
    _source_manifest_path,
    _source_manifest_label,
    _knowledge_ingestion_candidate_summary,
    _knowledge_ingestion_knowledge_summary,
    _knowledge_ingestion_stages,
    _knowledge_ingestion_stage,
    _knowledge_ingestion_action_items,
    _knowledge_ingestion_action_item,
    _knowledge_ingestion_overall_status,
    _candidate_breakdown,
    _coordination_queues,
    _coordination_summary,
    _coordination_action_items,
    _coordination_status,
    _coordination_item,
    _candidate_is_coordination_blocked,
    _coordination_candidate_reason,
    _coordination_communication_summary,
    _coordination_communication_brief,
    _coordination_target_agent_role,
    _coordination_brief_subject,
    _coordination_brief_message,
    _coordination_count_by,
    _knowledge_ingestion_knowledge_bases,
    _candidate_knowledge_ingestion_status,
    _source_manifest_source_ref,
    _ready_source_extraction,
    _ready_content_extraction_evidence_ledger,
    _source_extraction_evidence_refs,
    _merge_local_research_refs,
    _build_paper_note_chunks,
    _paper_note_chunk_by_id,
    _page_anchors_for_paper_note_chunk,
    _update_paper_note_chunk_plan_progress,
    _paper_note_chunk_plan_status,
    _source_candidate_has_ready_extraction,
    _candidate_paper_note_chunk_plan,
    _paper_note_chunk_plan_summary,
    _paper_note_chunk_action_items,
    _candidate_source_quality_assessment,
    _source_quality_bucket,
    _source_quality_scores,
    _default_source_quality_scores,
    _default_source_quality_decision,
    _source_quality_candidate_summary,
    _source_quality_batch_assessment_summary,
    _source_quality_action_items,
    _source_quality_next_actions,
    _resolve_source_path,
    _sha256_file,
    _extract_pdf_page_anchors,
    _page_scope_from_anchors,
    _excerpt_from_page_anchors,
    _normalize_id_values,
    _validate_paper_note_output,
    _validate_paper_note_candidate,
    _validate_neuro_mechanism_output,
    _validate_mechanism_mapping_output,
    _validate_algorithm_hypothesis_output,
    _validate_review_prefilter_output,
    _validate_review_record_candidate,
    _validate_steward_pack_output,
    _steward_pack_ingestion_payload,
    _steward_pack_rating_suggestion_payload,
    _migrate_steward_pack_rating_suggestion,
    _official_research_graph_record,
    _official_research_graph_edge,
    _normalize_steward_review_decision,
    _validate_candidate_graph_candidate,
    _normalize_optional_bool,
    _load_transfer_records,
    _append_transfer_record,
    _write_transfer_records,
    _find_candidate,
    _find_transfer,
    _normalize_local_research_task_type,
    _source_collection_team_agent_ids,
    _source_collection_prompt_cache_partition,
    _source_collection_candidate_trace_run_id,
    _source_collection_candidate_graph_matches_run,
    _source_collection_steward_candidate_matches_run,
    _stage_coordination_contract,
    _stage_coordination_manual_pending_result,
    _try_start_stage_coordination_round,
    _research_memory_knowledge_results,
    _stage_coordination_purpose,
    _load_official_model_evidence_store,
    _load_program_official_model_evidence_store,
    _official_model_evidence_entries,
    _build_official_model_evidence_record,
    _official_model_evidence_from_candidates,
    _dedupe_official_model_evidence,
    _official_model_evidence_coverage,
    _official_model_evidence_action_items,
    _official_model_evidence_boundary,
    _program_official_model_evidence_store_path,
    _normalize_official_model_task_type,
    _official_model_task_type_from_node,
    _normalize_official_model_evidence_kind,
    _infer_official_model_provider,
    _count_by_field,
    _local_research_llm_client,
    _local_research_model_messages,
    _extract_json_object_from_model_text,
    _local_research_model_instruction,
    _local_research_model_boundaries,
    _normalize_local_research_evidence_ledger,
    _workflow_log_sample_values,
    _workflow_log_count_sample,
    _workflow_log_queue_candidate_ids,
    _read_json,
    _candidate_store_path,
    _transfer_records_path,
    _official_model_evidence_store_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
WORKFLOW_LOG_SAMPLE_LIMIT = 8
WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH = "challenge_cup_research"
WORKFLOW_KIND_KNOWLEDGE_EXPANSION = "knowledge_expansion"
DEFAULT_OWNER_AGENT_ID = "Research Coordination Agent"
DEFAULT_WORKFLOW_ID = "challenge-cup-research-flow"
ALLOWED_WORKFLOW_KINDS = {WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH, WORKFLOW_KIND_KNOWLEDGE_EXPANSION}
CANDIDATE_TYPES = {
    "source_manifest",
    "paper_note",
    "neuro_mechanism",
    "mechanism_mapping",
    "algorithm_hypothesis",
    "review_record",
    "candidate_graph",
}
TRANSFER_DECISIONS = {"approved", "rejected", "returned"}
ARCHIVED_CANDIDATE_STATES = {"rejected", "archived"}
ARCHIVED_WORKFLOW_NODES = {"rejection_archive"}
LOCAL_RESEARCH_MODEL_ID = "houmo_qwen35_9b_agent"
LOCAL_RESEARCH_MODEL_NAME = "bossAGI-standard / qwen3.5-9b"
LOCAL_RESEARCH_MODEL_ROLE = "Local Research Worker Model"
LOCAL_RESEARCH_CONTEXT_WINDOW = 32_000
LOCAL_RESEARCH_EVIDENCE_TOKEN_TARGET = "18k-22k"
LOCAL_RESEARCH_INVOKE_PROFILE_ID = "__challenge_cup_local_research_model"
OFFICIAL_MODEL_EVIDENCE_KINDS = {"config", "invocation_log", "sample_output", "screenshot", "candidate_output", "manual_attestation"}
OFFICIAL_MODEL_EVIDENCE_REQUIRED_TASKS = (
    {"taskType": "source_screening", "workflowNode": "knowledge_collection", "label": "资料初筛"},
    {"taskType": "paper_note_draft", "workflowNode": "paper_note", "label": "论文笔记草稿"},
    {"taskType": "neuro_mechanism_extract", "workflowNode": "neuro_mechanism", "label": "神经机制抽取"},
    {"taskType": "mechanism_mapping", "workflowNode": "mechanism_mapping", "label": "机制映射"},
    {"taskType": "algorithm_hypothesis_draft", "workflowNode": "algorithm_hypothesis", "label": "算法假设"},
    {"taskType": "review_prefilter", "workflowNode": "review_record", "label": "预审筛选"},
)
SOURCE_EXTRACTION_DEFAULT_MAX_PAGES = 24
SOURCE_EXTRACTION_HARD_MAX_PAGES = 64
SOURCE_EXTRACTION_DEFAULT_MAX_CHARS_PER_PAGE = 1800
SOURCE_EXTRACTION_HARD_MAX_CHARS_PER_PAGE = 6000
SOURCE_EXTRACTION_EXCERPT_MAX_CHARS = 12000
PAPER_NOTE_CHUNK_DEFAULT_MAX_PAGES = 4
PAPER_NOTE_CHUNK_HARD_MAX_PAGES = 12
PAPER_NOTE_CHUNK_DEFAULT_MAX_CHARS = 12000
PAPER_NOTE_CHUNK_HARD_MAX_CHARS = 24000
PAPER_NOTE_CHUNK_MAX_CHUNKS = 24
SOURCE_QUALITY_DECISIONS = {"approved", "needs_revision", "rejected"}
SOURCE_QUALITY_APPROVED_STATUSES = {"source_quality_approved", "source_manifest_ready"}
SOURCE_QUALITY_NEEDS_REVISION_STATUSES = {"source_quality_needs_revision", "source_manifest_invalid"}
SOURCE_QUALITY_REJECTED_STATUSES = {"source_quality_rejected", "rejected"}
SOURCE_COLLECTION_DEFAULT_AGENT_ROLES = (
    "source_finder",
    "source_extractor",
    "source_relation_mapper",
    "source_ingestor",
)
SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES = {"source_finder"}
SOURCE_COLLECTION_COLLECTION_STAGE_AGENT_ROLES = {"source_finder"}
SOURCE_COLLECTION_DEFAULT_SEARCH_LANGUAGES = ("en", "zh")
SOURCE_COLLECTION_DEFAULT_SOURCE_TYPES = ("paper", "review", "dataset", "preprint")
SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY = 10
SOURCE_COLLECTION_MAX_QUERIES = 48
SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF = "crossref_rest_api"
SOURCE_COLLECTION_SEARCH_PROVIDER_ARXIV = "arxiv_api"
SOURCE_COLLECTION_SEARCH_PROVIDER_OPENALEX = "openalex_api"
# Default provider set executed for every source-collection query: each query
# runs once per provider and results merge through the existing
# sourceIdentityKey dedup semantics (first provider to return wins).  OpenAlex
# covers arXiv preprints (with rebuilt abstracts) and stays reachable when the
# export.arxiv.org channel is blocked; arXiv stays in the set so it resumes
# contributing automatically once connectivity returns.
SOURCE_COLLECTION_SEARCH_PROVIDER_QWEN_WEB_SEARCH = "qwen_web_search"
# Default provider set executed for every source-collection query: each query
# runs once per provider and results merge through the existing
# sourceIdentityKey dedup semantics (first provider to return wins).  OpenAlex
# covers arXiv preprints (with rebuilt abstracts) and stays reachable when the
# export.arxiv.org channel is blocked; arXiv stays in the set so it resumes
# contributing automatically once connectivity returns.
#
# qwen_web_search is deliberately NOT a per-query provider.  It is the layered
# run-level deep-search supplement (exactly one DashScope compatible-mode
# Responses API web_search call per run, executed from
# search_execution._execute_qwen_deep_search_for_run before the query loop);
# its records merge into the same pipeline through identity-key dedupe.
SOURCE_COLLECTION_SEARCH_PROVIDERS = (
    SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
    SOURCE_COLLECTION_SEARCH_PROVIDER_ARXIV,
    SOURCE_COLLECTION_SEARCH_PROVIDER_OPENALEX,
)
# arXiv's once-per-3-seconds API etiquette is now enforced globally by the
# per-provider pyrate-limiter registry in source_collection.search_execution.
SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_MAX_QUERIES = 4
SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_QUERIES = 12
SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_RESULTS_PER_QUERY = 2
SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_RESULTS_PER_QUERY = 5
SOURCE_COLLECTION_SUMMARY_SLOW_EVENT_MS = 1000
SOURCE_COLLECTION_SUMMARY_DEFAULT_RUN_LOOKUP_LIMIT = 20
SOURCE_COLLECTION_EXCLUSION_REASONS = {
    "no_effective_content",
    "unreadable",
    "unobtainable",
    "out_of_scope",
    "duplicate_invalid",
    "empty_page",
    "login_page",
    "advertisement",
}
SOURCE_COLLECTION_EXCLUSION_DECISIONS = {
    "exclude",
    "excluded",
    "discard",
    "discarded",
    "invalid",
    "no_effective_content",
    "unreadable",
    "unobtainable",
    "empty",
    "empty_page",
    "out_of_scope",
    "irrelevant",
    "reject",
    "rejected",
}
SOURCE_COLLECTION_KEEP_WITH_NOTES_DECISIONS = {
    "needs_more_info",
    "need_more_info",
    "needs_supplement",
    "needs_revision",
    "needs_review",
    "missing_source",
    "needs_fulltext",
    "conditional_keep",
    "keep_with_notes",
}
SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES = {
    "finding": ("source_finder",),
    "extraction": ("source_extractor",),
    "relations": ("source_relation_mapper",),
    "ingestion": ("source_ingestor",),
}
SOURCE_COLLECTION_AGENT_ROLES = set(SOURCE_COLLECTION_DEFAULT_AGENT_ROLES)
SOURCE_COLLECTION_STAGE_IDS = set(SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES)
SOURCE_COLLECTION_COLLECTION_MODES = {"web_search", "local_workspace", "mixed"}
SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_ROOTS = ("workspace/knowledge",)
SOURCE_COLLECTION_LOCAL_SCAN_EXTENSIONS = {".md", ".txt", ".json", ".jsonl", ".pdf"}
SOURCE_COLLECTION_LOCAL_SCAN_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "logs",
    "runtime_scenes",
    "dist",
    "build",
}
SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_MAX_FILES = 24
SOURCE_COLLECTION_LOCAL_SCAN_HARD_MAX_FILES = 100
SOURCE_COLLECTION_LOCAL_SCAN_MAX_BYTES = 256_000
SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND = "source_collection_stage_session_task"
SOURCE_COLLECTION_STAGE_REQUIRED_TOOLS = (
    "task_list_tool",
    "task_create_tool",
    "task_update_tool",
    "source_collection_context_tool",
    "source_collection_stage_writeback_tool",
)


SOURCE_COLLECTION_SEARCH_REQUIRED_TOOLS = (
    "batch_web_search_tool",
    "paper_search_tool",
)
SOURCE_COLLECTION_STAGE_SESSION_TASK_STATUSES = {
    "queued",
    "running",
    "completed",
    "needs_review",
    "blocked",
    "failed",
    "cancelled",
    "interrupted",
}
SOURCE_COLLECTION_STAGE_SESSION_TASK_ACTIVE_STATUSES = {"queued", "running"}
SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES = {"completed", "needs_review"}
SOURCE_COLLECTION_STORAGE_OPEN_TARGETS = {
    "run_directory",
    "artifacts_directory",
    "search_plan",
    "search_events",
    "records",
    "candidates",
    "candidate_store",
    "data_processing_run",
    "data_processing_records",
}
SOURCE_COLLECTION_PROMPT_CACHE_REQUIRED_MODES = {"required", "strict", "hard_required", "required_for_llm_execution"}
SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES = {"disabled", "off", "none"}
SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES = {"automatic", "explicit_cache_control"}
SOURCE_COLLECTION_PROMPT_CACHE_SCOPE = "research_team_knowledge_collection"
SOURCE_COLLECTION_WORK_RUN_KIND = "source_collection_run"
KNOWLEDGE_INGESTION_WORK_RUN_KIND = "knowledge_ingestion_run"
RESEARCH_STAGE_TYPES = ("knowledge_collection", "experiment", "iteration")
RESEARCH_STAGE_ACTIVE_STATUSES = {"running", "planning", "needs_attention"}
RESEARCH_STAGE_DEFAULTS = {
    "knowledge_collection": {
        "title": "Knowledge collection round",
        "currentNode": "knowledge_collection",
        "primaryActionZh": "启动知识搜集",
        "continueActionZh": "继续知识搜集",
        "newRoundActionZh": "开启新一轮知识搜集",
    },
    "experiment": {
        "title": "Experiment planning round",
        "currentNode": "experiment_planning",
        "primaryActionZh": "启动实验规划",
        "continueActionZh": "继续实验规划",
        "newRoundActionZh": "重新规划实验",
    },
    "iteration": {
        "title": "Iteration planning round",
        "currentNode": "iteration_planning",
        "primaryActionZh": "启动迭代",
        "continueActionZh": "继续迭代",
        "newRoundActionZh": "开启新一轮迭代",
    },
}
EXPERIMENT_PLAN_STORE_KIND = "team_workflow_experiment_plan_store"
EXPERIMENT_PLAN_REQUIRED_FIELDS = ("dataset", "metric", "baseline", "smokePlan")
EXPERIMENT_SMOKE_RESULT_STATUSES = {"passed", "failed", "needs_review"}
EXPERIMENT_FULL_RUN_RESULT_STATUSES = {"passed", "failed", "needs_review"}
LOCAL_RESEARCH_OUTPUT_FIELDS = (
    "candidateType",
    "sourceRefs",
    "evidenceRefs",
    "claims",
    "uncertainty",
    "riskFlags",
    "confidence",
    "nextAction",
    "requiresReview",
)
LOCAL_RESEARCH_TASKS = {
    "source_screening": {
        "workflowNode": "knowledge_collection",
        "targetCandidateType": "source_manifest",
        "purpose": "判断资料是否与神经机制启发神经网络算法相关。",
        "requiredOutput": ("candidateType", "sourceRefs", "evidenceRefs", "claims", "riskFlags", "confidence", "nextAction", "requiresReview"),
    },
    "paper_note_draft": {
        "workflowNode": "paper_note",
        "targetCandidateType": "paper_note",
        "purpose": "从资料片段生成 paper_note 草稿，保留 keyFindings、methods、limitations、uncertainty。",
        "requiredOutput": (*LOCAL_RESEARCH_OUTPUT_FIELDS, "keyFindings", "methods", "limitations", "citations"),
    },
    "neuro_mechanism_extract": {
        "workflowNode": "neuro_mechanism",
        "targetCandidateType": "neuro_mechanism",
        "purpose": "从 paper_note 与关键原文片段抽取 neuro_mechanism 候选。",
        "requiredOutput": (
            *LOCAL_RESEARCH_OUTPUT_FIELDS,
            "paperNoteIds",
            "description",
            "brainSystems",
            "cognitiveFunctions",
            "experimentalPhenomena",
            "authorInterpretation",
            "projectInterpretation",
        ),
    },
    "mechanism_mapping": {
        "workflowNode": "mechanism_mapping",
        "targetCandidateType": "mechanism_mapping",
        "purpose": "把神经机制映射为计算抽象，区分 factLayer、inferenceLayer 和 overAnalogyRisk。",
        "requiredOutput": (
            *LOCAL_RESEARCH_OUTPUT_FIELDS,
            "neuroMechanismIds",
            "computationalAbstraction",
            "factLayer",
            "inferenceLayer",
            "overAnalogyRisk",
            "engineeringImplication",
        ),
    },
    "algorithm_hypothesis_draft": {
        "workflowNode": "algorithm_hypothesis",
        "targetCandidateType": "algorithm_hypothesis",
        "purpose": "生成可审查 algorithm_hypothesis 草稿，必须包含 baseline 与 experimentPlan。",
        "requiredOutput": (
            *LOCAL_RESEARCH_OUTPUT_FIELDS,
            "mechanismMappingIds",
            "hypothesis",
            "baseline",
            "expectedBenefit",
            "expectedComputeCost",
            "experimentPlan",
        ),
    },
    "review_prefilter": {
        "workflowNode": "research_review",
        "targetCandidateType": "review_record",
        "purpose": "做 review prefilter，输出 riskFlags、requiredChanges 和 needsDecision，不写最终 review.decision。",
        "requiredOutput": (*LOCAL_RESEARCH_OUTPUT_FIELDS, "candidateIds", "checklist", "comments", "requiredChanges", "needsDecision"),
    },
    "steward_pack_draft": {
        "workflowNode": "steward_ingestion",
        "targetCandidateType": "review_record",
        "purpose": "生成 proposal/ingestion pack 草稿，供知识库管理员复核。",
        "requiredOutput": (
            *LOCAL_RESEARCH_OUTPUT_FIELDS,
            "candidateIds",
            "targetDomain",
            "sourceTrace",
            "riskSummary",
            "proposalPayload",
            "ratingSuggestion",
            "approvalRequired",
        ),
    },
}
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
_WORKFLOW_LOCK = threading.RLock()


class TeamWorkflowOrchestrationError(ValueError):
    """Raised when a Team workflow orchestration request is invalid."""


class SourceExtractionError(ValueError):
    """Raised when local source extraction cannot produce page anchors."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message






















_SMOKE_DECISION_TO_STATUS = {
    "accept": "passed",
    # iterate = weak improvement (threshold <= delta < 2*threshold): keep it
    # under human review instead of auto-unlocking the formal full-run gate.
    "iterate": "needs_review",
    "reject": "failed",
    "needs_full_run": "needs_review",
}











RESEARCH_REVIEW_DECISIONS = {"approve", "revise", "reject", "needs_human"}


ITERATION_ACTIONS = {"iterate", "reject", "merge", "hold"}


_PRD_EXPECTED_ENDPOINTS = (
    "knowledge-collection/extract",
    "research/mechanisms/extract",
    "research/mechanisms/map",
    "research/hypotheses/generate",
    "research/review/decide",
    "experiments/plans/{plan_id}/smoke-run",
    "iterations/propose",
    "deliverables/export",
)





# 可作为知识提案审批人的团队角色线索（coordinator / lead / owner）。
# 与 team_knowledge_service.REVIEW_ROLES 对应，但这里用子串匹配以兼容
# research_coordination 这类带前缀的研究流角色。
_TEAM_REVIEW_ROLE_HINTS = ("coordination", "coordinator", "lead", "owner")


_KNOWLEDGE_COLLECTION_COMPLETION_FLOW_STAGES: tuple[dict[str, Any], ...] = (
    {
        "stageId": "finding",
        "label": "资料寻找",
        "agentRole": "source_finder",
        "stepIds": {"remaining_search"},
    },
    {
        "stageId": "extraction",
        "label": "资料提炼",
        "agentRole": "source_extractor",
        "stepIds": {"candidate_extraction", "source_review"},
    },
    {
        "stageId": "relations",
        "label": "资料关系整理",
        "agentRole": "source_relation_mapper",
        "stepIds": {"candidate_graph"},
    },
    {
        "stageId": "ingestion",
        "label": "资料入库",
        "agentRole": "source_ingestor",
        "stepIds": {
            "steward_pack",
            "source_gate",
            "knowledge_proposal",
            "knowledge_ingestion",
            "official_knowledge",
            "knowledge_steward_request",
        },
    },
)


_SOURCE_COLLECTION_GENERIC_SEARCH_TERMS = {
    "paper",
    "papers",
    "preprint",
    "preprints",
    "benchmark",
    "benchmarks",
    "survey",
    "review",
    "reviews",
    "peer",
    "reviewed",
    "source",
    "sources",
    "dataset",
    "datasets",
    "data",
    "latest",
    "analysis",
    "study",
    "studies",
}
_SOURCE_COLLECTION_LOW_QUALITY_TERMS = {
    "高考",
    "志愿填报",
    "专业目录",
    "招生",
    "录取",
    "词典",
    "dictionary",
    "adjective",
    "noun",
    "quiz",
}
_SOURCE_COLLECTION_QUERY_TERM_TRANSLATIONS = {
    "预测": ("predictive", "prediction"),
    "编码": ("coding", "encoding"),
    "预测编码": ("predictive", "coding", "predictive coding"),
    "皮层": ("cortical", "cortex"),
    "层级": ("hierarchy", "hierarchical"),
    "突触": ("synaptic", "synapse"),
    "可塑性": ("plasticity",),
    "学习": ("learning",),
    "神经": ("neural", "neuron"),
    "门控": ("gating", "gate"),
    "注意": ("attention",),
    "机制": ("mechanism",),
}


def get_challenge_submission_readiness(team_id: str) -> dict[str, Any]:
    """Return the canonical, user-facing Challenge Cup submission readiness."""
    team_service.get_team(team_id)
    projection = build_competition_program_projection(
        question_run_summary=challenge_question_run_summary(team_id),
    )
    return build_challenge_submission_readiness(
        team_id=team_id,
        competition_program_projection=projection,
    )
