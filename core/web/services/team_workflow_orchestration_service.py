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
    _load_candidate_store,
    _load_source_collection_exclusion_store,
    _load_stage_round_store,
    _mark_source_collection_work_run_stale,
    _new_record_id,
    _normalize_source_collection_exclusion_reason,
    _normalize_source_collection_prompt_cache_requirement,
    _normalize_source_collection_roles,
    _persist_source_collection_work_run,
    _record_source_collection_exclusion,
    _record_source_collection_summary_timing,
    _record_workflow_event,
    _resolve_source_collection_record_id,
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
    _source_collection_result_from_crossref_item,
    _source_collection_result_identity_key,
    _source_collection_role_assignment_inputs,
    _source_collection_run_belongs_to_team,
    _source_collection_run_context_bundle,
    _source_collection_run_has_usable_outputs,
    _source_collection_search_languages,
    _source_collection_search_plan_ref,
    _source_collection_seed_from_input_ref,
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
from core.web.services.team_workflow.source_collection.stage_reconcile import (
    _source_collection_stage_task_writeback_contract,
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
    create_experiment_plan,
    create_experiment_plan_revision_from_iteration,
    execute_experiment_full_run,
    freeze_experiment_design,
    get_experiment_method_catalog,
    get_experiment_planning_status,
    prepare_experiment_full_run,
    reconcile_experiment_knowledge_ingestion,
    register_experiment_baseline_artifact,
    register_experiment_full_run_result,
    register_experiment_smoke_result,
    request_experiment_result_knowledge_ingestion,
    run_experiment_smoke_run,
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
    _experiment_hypothesis_summaries,
    _experiment_hypothesis_summary,
    _experiment_hypothesis_missing_fields,
    _find_experiment_plan,
    _experiment_baseline_artifact_record,
    _experiment_smoke_result_record,
    _experiment_full_run_result_record,
    _experiment_result_ingestion_pack_record,
    _notify_knowledge_steward_for_experiment_result,
    _refresh_experiment_plan_readiness,
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
    _official_model_evidence_entries,
    _build_official_model_evidence_record,
    _official_model_evidence_from_candidates,
    _dedupe_official_model_evidence,
    _official_model_evidence_coverage,
    _official_model_evidence_action_items,
    _official_model_evidence_boundary,
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
    "web_search_tool",
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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
















def _bounded_text_items(value: Any, *, max_items: int, max_length: int) -> list[str]:
    return [
        _trim_text(item, max_length=max_length)
        for item in list(value or [])[:max_items]
        if _trim_text(item, max_length=max_length)
    ]


def _bounded_log_items(value: Any, keys: tuple[str, ...], *, max_items: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in list(value or [])[:max_items]:
        if not isinstance(item, dict):
            continue
        bounded: dict[str, Any] = {}
        for key in keys:
            raw = item.get(key)
            if isinstance(raw, list):
                text_items = _bounded_text_items(raw, max_items=12, max_length=160)
                if text_items:
                    bounded[key] = text_items
            elif isinstance(raw, (int, float, bool)) or raw is None:
                if raw is not None:
                    bounded[key] = raw
            else:
                text = _trim_text(raw, max_length=240 if key in {"title", "error"} else 160)
                if text:
                    bounded[key] = text
        if bounded:
            items.append(bounded)
    return items








_SMOKE_DECISION_TO_STATUS = {
    "accept": "passed",
    "iterate": "passed",
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





def _team_workflow_kernel_summary(kernel_result: dict[str, Any]) -> dict[str, Any]:
    event = kernel_result.get("event") if isinstance(kernel_result.get("event"), dict) else {}
    task = kernel_result.get("task") if isinstance(kernel_result.get("task"), dict) else {}
    execution = kernel_result.get("execution") if isinstance(kernel_result.get("execution"), dict) else {}
    outcome = kernel_result.get("outcome") if isinstance(kernel_result.get("outcome"), dict) else {}
    adapter = kernel_result.get("adapter") if isinstance(kernel_result.get("adapter"), dict) else {}
    return {
        "eventId": str(adapter.get("eventId") or event.get("eventId") or "").strip(),
        "taskId": str(task.get("taskId") or "").strip(),
        "workRunId": str(execution.get("workRunId") or "").strip(),
        "outcomeId": str(outcome.get("outcomeId") or "").strip(),
        "outcomeStatus": str(outcome.get("status") or "").strip(),
        "adapterVersion": str(adapter.get("adapterVersion") or "").strip(),
        "reused": bool(kernel_result.get("reused", False)),
    }


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


def _workflow_to_api(
    team_id: str,
    workflow: dict[str, Any],
    candidate_store: dict[str, Any],
) -> dict[str, Any]:
    candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    return {
        **workflow,
        "candidateStore": {
            "schemaVersion": SCHEMA_VERSION,
            "candidateCount": len(candidates),
            "candidateTypes": sorted({str(item.get("candidateType") or "") for item in candidates if item.get("candidateType")}),
            "updatedAt": str(candidate_store.get("updatedAt") or ""),
            "storagePath": _relative_path(_candidate_store_path(team_id)),
        },
        "transferRecordsPath": _relative_path(_transfer_records_path(team_id)),
        "storagePath": _relative_path(_workflow_path(team_id)),
    }


def _filtered_candidates(
    candidate_store: dict[str, Any],
    *,
    candidate_type: str,
    current_state: str,
    quality_status: str,
) -> list[dict[str, Any]]:
    candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    filtered: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate_type and str(candidate.get("candidateType") or "") != candidate_type:
            continue
        if current_state and str(candidate.get("currentState") or "") != current_state:
            continue
        if quality_status and str(candidate.get("qualityStatus") or "") != quality_status:
            continue
        filtered.append(candidate)
    return filtered


def _candidate_needs_rework(candidate: dict[str, Any], validation_reports: dict[str, dict[str, Any]]) -> bool:
    state = str(candidate.get("currentState") or "")
    quality_status = str(candidate.get("qualityStatus") or "")
    if "needs_revision" in state or quality_status == "needs_revision":
        return True
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if isinstance(output.get("requiredChanges"), list) and output.get("requiredChanges"):
        return True
    validation = validation_reports.get(str(candidate.get("candidateId") or ""))
    return bool(validation and not validation.get("valid", True))


def _source_extraction_anchor_id(candidate: dict[str, Any], anchor: dict[str, Any]) -> str:
    page = int(anchor.get("page") or 0)
    source_token = _safe_token(candidate.get("candidateId"), default="source", max_length=48)
    return _trim_text(anchor.get("id"), max_length=240) or f"{source_token}-p{page}"


def _payload_score(payload: dict[str, Any], key: str, default: int) -> int:
    if key not in payload or payload.get(key) is None:
        return _clamp_score(default)
    return _clamp_score(_normalize_int(payload.get(key), default=default, minimum=0, maximum=100))


def _clamp_score(value: int) -> int:
    return max(0, min(int(value or 0), 100))


def _page_numbers_from_scope(page_scope: str, *, total_pages: int, max_pages: int) -> list[int]:
    if total_pages <= 0 or max_pages <= 0:
        return []
    normalized_scope = _trim_text(page_scope, max_length=160)
    if not normalized_scope:
        return list(range(1, min(total_pages, max_pages) + 1))
    page_numbers: list[int] = []
    for part in re.split(r"[,;，；\s]+", normalized_scope):
        token = part.strip()
        if not token:
            continue
        range_match = re.fullmatch(r"(\d+)\s*[-~]\s*(\d+)", token)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start > end:
                start, end = end, start
            page_numbers.extend(range(start, end + 1))
        elif token.isdigit():
            page_numbers.append(int(token))
    normalized: list[int] = []
    for number in page_numbers:
        if 1 <= number <= total_pages and number not in normalized:
            normalized.append(number)
        if len(normalized) >= max_pages:
            break
    return normalized or list(range(1, min(total_pages, max_pages) + 1))


def _compact_text(value: Any, *, max_length: int) -> str:
    text = str(value or "").replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_length]


def _normalize_rating_enum(value: Any, allowed: set[str], *, default: str) -> str:
    normalized = _trim_text(value, max_length=80).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "reviewable": "medium",
        "needs_review": "elevated",
        "pending_review": "elevated",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in allowed else default


def _has_any_list_value(value: Any) -> bool:
    return isinstance(value, list) and any(_has_value(item) for item in value)


def _has_neuro_term_or_unknown(value: Any) -> bool:
    if isinstance(value, list):
        return any(_has_value(item) for item in value)
    text = _trim_text(value, max_length=160).lower()
    return bool(text)


def _requires_terminology_uncertain(output: dict[str, Any]) -> bool:
    terms = [output.get("brainSystems"), output.get("cognitiveFunctions"), output.get("uncertainty")]
    for value in terms:
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = _trim_text(item, max_length=400).lower()
            if text in {"unknown", "uncertain", "不确定", "未知"} or "terminology" in text or "术语" in text:
                return True
    return False


def _risk_flags_include(output: dict[str, Any], flag: str) -> bool:
    risk_flags = output.get("riskFlags")
    return isinstance(risk_flags, list) and flag in {str(item) for item in risk_flags}


def _is_over_analogy_risky(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        level = _trim_text(value.get("level") or value.get("severity") or value.get("riskLevel"), max_length=80).lower()
        status = _trim_text(value.get("status"), max_length=80).lower()
        return level in {"high", "critical", "severe", "高", "严重"} or status in {"unresolved", "open", "未解决"}
    if isinstance(value, list):
        return any(_is_over_analogy_risky(item) for item in value)
    text = _trim_text(value, max_length=400).lower()
    return text in {"high", "critical", "severe", "高", "严重"} or "over" in text or "过度" in text or "unsupported" in text or "unresolved" in text


def _has_citation_anchor(value: dict[str, Any]) -> bool:
    source_ref = _trim_text(value.get("sourceRef") or value.get("sourceRefId") or value.get("sourceId"), max_length=240)
    page = _trim_text(value.get("page") or value.get("pageAnchor") or value.get("pageRange"), max_length=120)
    citation = _trim_text(value.get("citation") or value.get("citationAnchor"), max_length=240)
    evidence_ref = _trim_text(value.get("evidenceRef") or value.get("evidenceRefId"), max_length=240)
    return bool(source_ref and (page or citation or evidence_ref))


def _normalize_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _sync_owner_policy(value: Any, owner_agent_id: str) -> dict[str, Any]:
    policy = value if isinstance(value, dict) else {}
    return {
        **policy,
        "coordinationAgentId": owner_agent_id,
        "functionalAgentsMayRequestTransfer": True,
        "finalStateWriter": owner_agent_id,
    }


def _sync_transfer_policy(value: Any, owner_agent_id: str) -> dict[str, Any]:
    policy = value if isinstance(value, dict) else {}
    return {
        **policy,
        "requiresUserConfirmation": False,
        "requestedBy": "functional_agent",
        "decidedBy": owner_agent_id,
        "recordDecidedByAgent": True,
    }


def _repair_workflow(payload: dict[str, Any], team_id: str) -> dict[str, Any]:
    base = _default_workflow(
        team_id,
        workflow_kind=_normalize_workflow_kind(payload.get("workflowKind") or WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH),
        owner_agent_id=_trim_text(payload.get("ownerAgentId"), max_length=160) or DEFAULT_OWNER_AGENT_ID,
    )
    for key in (
        "workflowId",
        "status",
        "stateMachine",
        "routingPolicy",
        "transferPolicy",
        "activeWorkflowItems",
        "createdAt",
        "updatedAt",
    ):
        if key in payload:
            base[key] = payload[key]
    base["schemaVersion"] = SCHEMA_VERSION
    base["teamId"] = team_id
    base["workflowId"] = _trim_text(base.get("workflowId"), max_length=120) or DEFAULT_WORKFLOW_ID
    base["status"] = _trim_text(base.get("status"), max_length=32) or "active"
    if not isinstance(base.get("activeWorkflowItems"), list):
        base["activeWorkflowItems"] = []
    base["routingPolicy"] = _sync_owner_policy(base.get("routingPolicy"), str(base.get("ownerAgentId") or DEFAULT_OWNER_AGENT_ID))
    base["transferPolicy"] = _sync_transfer_policy(base.get("transferPolicy"), str(base.get("ownerAgentId") or DEFAULT_OWNER_AGENT_ID))
    return base


def _upsert_active_item(
    items: Any,
    *,
    candidate_id: str,
    current_node: str,
    status: str,
    transfer_id: str,
) -> list[dict[str, Any]]:
    normalized_items = [item for item in list(items or []) if isinstance(item, dict)]
    now = utc_now_iso()
    next_item = {
        "candidateId": candidate_id,
        "currentNode": current_node,
        "status": status,
        "pendingTransferId": transfer_id,
        "updatedAt": now,
    }
    for index, item in enumerate(normalized_items):
        if str(item.get("candidateId") or "") == candidate_id:
            normalized_items[index] = {**item, **next_item}
            return normalized_items
    normalized_items.append(next_item)
    return normalized_items


def _normalize_workflow_kind(value: Any) -> str:
    normalized = _trim_text(value, max_length=80) or WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH
    if normalized not in ALLOWED_WORKFLOW_KINDS:
        raise TeamWorkflowOrchestrationError("Workflow kind is not enabled.")
    return normalized


def _normalize_candidate_type(value: Any) -> str:
    normalized = _trim_text(value, max_length=80) or "source_manifest"
    if normalized not in CANDIDATE_TYPES:
        raise TeamWorkflowOrchestrationError("Candidate type is invalid.")
    return normalized


def _load_data_processing_record(run_id: str, record_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        run = data_processing_service.get_processing_run(run_id)
        records = data_processing_service.list_records(run_id).get("records", [])
    except data_processing_service.DataProcessingNotFoundError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    except data_processing_service.DataProcessingError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    record = next((item for item in records if isinstance(item, dict) and str(item.get("recordId") or "") == record_id), None)
    if record is None:
        raise TeamWorkflowOrchestrationError(f"Data processing record not found: {record_id}")
    return run, record


def _find_candidate_imported_from_data_record(candidate_store: dict[str, Any], run_id: str, record_id: str) -> dict[str, Any] | None:
    for candidate in list(candidate_store.get("candidates") or []):
        if not isinstance(candidate, dict):
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        if str(imported_from.get("runId") or "") == run_id and str(imported_from.get("recordId") or "") == record_id:
            return candidate
    return None


def _looks_like_url(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _decode_local_workspace_sample(sample_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return sample_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return sample_bytes.decode("utf-8", errors="ignore")


def _crossref_search_url(query_text: str, *, rows: int) -> str:
    params = urllib.parse.urlencode(
        {
            "query": query_text,
            "rows": str(rows),
            "select": "DOI,title,URL,container-title,published-print,published-online,issued,author,type,abstract,score",
        }
    )
    return f"https://api.crossref.org/works?{params}"


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



def _workflow_timestamp_sort_key(value: Any) -> tuple[float, str]:
    text = _trim_text(value, max_length=120)
    if not text:
        return (0.0, "")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (parsed.timestamp(), text)
    except ValueError:
        return (0.0, text)


def _append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _ensure_project_child(path: Path) -> Path:
    resolved = path.resolve()
    project_root = _project_root().resolve()
    workspace_root = resolve_workspace_home().resolve()
    for allowed_root in (project_root, workspace_root):
        try:
            resolved.relative_to(allowed_root)
            return resolved
        except ValueError:
            continue
    raise TeamWorkflowOrchestrationError("Source collection storage path must stay inside the Vibelution project or workspace data root.")


def _open_local_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _strip_html(value: str) -> str:
    if not value:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()


def _metadata_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [_trim_text(value, max_length=220)] if _trim_text(value, max_length=220) else []
    if isinstance(value, list):
        results: list[str] = []
        for item in value[:24]:
            results.extend(_metadata_text_values(item))
        return results
    if isinstance(value, dict):
        results: list[str] = []
        for item in value.values():
            results.extend(_metadata_text_values(item))
        return results
    return []


def _normalize_stage_type(value: Any) -> str:
    normalized = _trim_text(value, max_length=80)
    if normalized not in RESEARCH_STAGE_TYPES:
        raise TeamWorkflowOrchestrationError("Unsupported research stage type.")
    return normalized


def _normalize_stage_start_mode(value: Any) -> str:
    normalized = _trim_text(value, max_length=80)
    return "new_round" if normalized in {"new_round", "new", "restart"} else "continue_or_start"


def _stage_query_seeds(payload: dict[str, Any], previous_round: dict[str, Any] | None, *, topic: str, goal: str) -> list[str]:
    seeds = _normalize_text_list(payload.get("querySeeds"), max_items=40, max_length=220)
    if seeds:
        return seeds
    suggested = _suggest_stage_query_seeds(previous_round, topic=topic, goal=goal)
    if suggested:
        return suggested[:8]
    return [item for item in [topic, goal] if item][:2]


def _suggest_stage_query_seeds(previous_round: dict[str, Any] | None, *, topic: str, goal: str) -> list[str]:
    seeds: list[str] = []
    if previous_round:
        for warning in list(previous_round.get("warnings") or []):
            if isinstance(warning, dict):
                _append_source_collection_seed(seeds, warning.get("message"))
        for item in list(previous_round.get("suggestedQuerySeeds") or [])[:6]:
            _append_source_collection_seed(seeds, item)
        for item in list(previous_round.get("querySeeds") or [])[:6]:
            _append_source_collection_seed(seeds, f"{item} missing evidence")
    _append_source_collection_seed(seeds, topic)
    if goal:
        _append_source_collection_seed(seeds, goal)
    return seeds[:10]


def _stage_upstream_round_ids(
    payload: dict[str, Any],
    rounds: list[dict[str, Any]],
    stage_type: str,
    previous_round: dict[str, Any] | None,
) -> list[str]:
    explicit = _normalize_text_list(payload.get("upstreamRoundIds"), max_items=24, max_length=160)
    if explicit:
        return explicit
    if stage_type == "knowledge_collection":
        return [str(previous_round.get("stageRoundId"))] if previous_round and previous_round.get("stageRoundId") else []
    if stage_type == "experiment":
        latest_collection = _latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "knowledge_collection"])
        return [str(latest_collection.get("stageRoundId"))] if latest_collection and latest_collection.get("stageRoundId") else []
    latest_experiment = _latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "experiment"])
    return [str(latest_experiment.get("stageRoundId"))] if latest_experiment and latest_experiment.get("stageRoundId") else []


def _stage_default_topic(stage_type: str, previous_round: dict[str, Any] | None) -> str:
    if previous_round:
        inherited = _trim_text(previous_round.get("topic"), max_length=500)
        if inherited:
            return inherited
    return {
        "experiment": "challenge cup experiment planning",
        "iteration": "challenge cup iteration planning",
    }.get(stage_type, "challenge cup research")


def _stage_default_goal(stage_type: str, previous_round: dict[str, Any] | None) -> str:
    if previous_round:
        inherited = _trim_text(previous_round.get("goal"), max_length=1000)
        if inherited:
            return inherited
    if stage_type == "experiment":
        return "Plan experiments from accepted knowledge-collection candidates without executing them automatically."
    if stage_type == "iteration":
        return "Plan the next improvement round from experiment evidence and unresolved risks."
    return "Collect traceable research sources for neuroscience-inspired algorithm discovery."


def _stage_memory_record(stage_round: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "recordId": _new_record_id("stagemem"),
        "recordKind": "team_workflow_stage_record",
        "workflowId": workflow.get("workflowId", DEFAULT_WORKFLOW_ID),
        "stageRoundId": stage_round.get("stageRoundId", ""),
        "stageType": stage_round.get("stageType", ""),
        "roundNumber": stage_round.get("roundNumber", 0),
        "status": stage_round.get("status", ""),
        "topic": stage_round.get("topic", ""),
        "goal": stage_round.get("goal", ""),
        "sourceRunIds": list(stage_round.get("sourceRunIds") or []),
        "upstreamRoundIds": list(stage_round.get("upstreamRoundIds") or []),
        "promptCachePolicyRef": _source_collection_prompt_cache_policy_ref(stage_round.get("promptCachePolicy") if isinstance(stage_round.get("promptCachePolicy"), dict) else {}),
        "memoryContextId": str((stage_round.get("memoryContext") or {}).get("contextId") or ""),
        "boundary": "runtime_stage_record_only_not_formal_team_knowledge",
        "createdAt": utc_now_iso(),
    }


def _stage_planning_contract(stage_type: str, stage_round: dict[str, Any]) -> dict[str, Any]:
    if stage_type == "experiment":
        expected_outputs = ["experiment_plan", "baseline_selection", "success_metrics", "risk_controls"]
    elif stage_type == "iteration":
        expected_outputs = ["iteration_goal", "change_list", "evidence_to_compare", "next_round_entry"]
    else:
        expected_outputs = ["source_manifest_candidates"]
    return {
        "contractKind": f"{stage_type}_planning_contract",
        "stageRoundId": stage_round.get("stageRoundId", ""),
        "expectedOutputs": expected_outputs,
        "autoExecution": False,
        "requiresUserDecision": True,
    }


def _active_research_loop_projection(team_id: str) -> dict[str, Any] | None:
    store = _read_json(_team_workflow_root(team_id) / "research_loops" / "index.json")
    loops = [item for item in list(store.get("loops") or []) if isinstance(item, dict)]
    active_loop_id = str(store.get("activeLoopId") or "")
    for loop in loops:
        if str(loop.get("loopId") or "") == active_loop_id:
            return loop
    return loops[-1] if loops else None


def _best_research_loop_evidence_id(loop: dict[str, Any] | None) -> str:
    evidence_records = [item for item in list((loop or {}).get("evidenceRecords") or []) if isinstance(item, dict)]
    for evidence_type in ("benchmark_result", "full_run_result", "metric_report"):
        for evidence in reversed(evidence_records):
            if (
                str(evidence.get("evidenceType") or "") == evidence_type
                and str(evidence.get("status") or "").lower() == "passed"
            ):
                return str(evidence.get("evidenceId") or evidence.get("resultId") or "")
    return ""


def _first_non_empty_text(*values: Any) -> str:
    for value in values:
        text = _trim_text(value, max_length=1200)
        if text:
            return text
    return ""


def _dedupe_text_values(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _trim_text(value, max_length=500)
        if text and text not in result:
            result.append(text)
    return result


def _stage_agent_binding_warnings(assignments: list[dict[str, Any]]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for item in assignments:
        agent_role = str(item.get("agentRole") or "")
        agent_id = str(item.get("agentId") or "")
        if agent_role and agent_id == agent_role:
            warnings.append(
                {
                    "code": "agent_binding_missing",
                    "severity": "warning",
                    "message": f"{agent_role} has no concrete team agent binding.",
                }
            )
    return warnings


def _stage_readiness(stage_type: str, rounds: list[dict[str, Any]]) -> dict[str, Any]:
    if stage_type == "knowledge_collection":
        return {"ready": True, "reason": "知识搜集可随时多轮启动。"}
    if stage_type == "experiment":
        latest_collection = _latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "knowledge_collection"])
        return {
            "ready": bool(latest_collection),
            "reason": "已有知识搜集轮次，可由用户决定进入实验规划。" if latest_collection else "需要先启动至少一轮知识搜集。",
        }
    latest_experiment = _latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "experiment"])
    return {
        "ready": bool(latest_experiment),
        "reason": "已有实验规划轮次，可进入迭代规划。" if latest_experiment else "需要先启动实验规划。",
    }


def _current_research_stage(phases: list[dict[str, Any]], workflow: dict[str, Any]) -> str:
    for phase in phases:
        if phase.get("activeRoundId"):
            return str(phase.get("stageType") or "")
    state_machine = workflow.get("stateMachine") if isinstance(workflow.get("stateMachine"), dict) else {}
    return str(state_machine.get("currentStage") or "knowledge_collection")


def _stage_next_actions(stage_type: str, *, reused: bool) -> list[str]:
    if reused:
        return ["Continue the active stage round instead of creating a duplicate.", "Open the matching research workspace view."]
    if stage_type == "knowledge_collection":
        return [
            "Open Source collection to inspect query seeds, assignments, and writeback contract.",
            "Functional agents submit CollectionOutput records before candidate import.",
            "User decides whether to start experiment after screening.",
        ]
    if stage_type == "experiment":
        return ["Review upstream knowledge-collection evidence.", "Draft experiment plan; do not auto-run experiments."]
    return ["Review experiment evidence.", "Plan the next iteration round; do not auto-apply changes."]


def _research_stage_boundaries() -> dict[str, bool]:
    return {
        "externalSearchTriggered": False,
        "writesFormalKnowledge": False,
        "writesRag": False,
        "writesOfficialGraph": False,
        "autoTransitionsNextStage": False,
        "stageRecordsOnly": True,
    }


def _stage_label(stage_type: str) -> str:
    return {
        "knowledge_collection": "知识搜集",
        "experiment": "实验",
        "iteration": "迭代",
    }.get(stage_type, stage_type)


def _find_candidate_by_id(candidate_store: dict[str, Any], candidate_id: str) -> dict[str, Any] | None:
    for candidate in [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]:
        if str(candidate.get("candidateId") or "") == candidate_id:
            return candidate
    return None


def _parse_first_json_object(text: Any) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(raw)
    sliced = _slice_first_json_object(raw)
    if sliced and sliced not in candidates:
        candidates.append(sliced)
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _slice_first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _normalize_ref_list(value: Any, *, max_items: int) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    refs: list[dict[str, str]] = []
    for item in value[:max_items]:
        if isinstance(item, dict):
            ref_type = _trim_text(item.get("type"), max_length=80)
            ref_id = _trim_text(item.get("id"), max_length=240)
            label = _trim_text(item.get("label"), max_length=240)
            if ref_type or ref_id or label:
                refs.append({"type": ref_type, "id": ref_id, "label": label})
        else:
            label = _trim_text(item, max_length=240)
            if label:
                refs.append({"type": "text", "id": "", "label": label})
    return refs


def _normalize_metadata_list(value: Any, *, max_items: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_normalize_metadata(item) for item in value[:max_items] if isinstance(item, dict)]


def _normalize_text_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value[:max_items]:
        text = _trim_text(item, max_length=max_length)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        _trim_text(key, max_length=80): _normalize_metadata_value(item)
        for key, item in value.items()
        if _trim_text(key, max_length=80)
    }


def _normalize_metadata_value(value: Any) -> Any:
    if isinstance(value, str):
        return _trim_text(value, max_length=1000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_normalize_metadata_value(item) for item in value[:24]]
    if isinstance(value, dict):
        return _normalize_metadata(value)
    return _trim_text(value, max_length=1000)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _workflow_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "workflow_orchestration.json"


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_project_root())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _normalize_required_id(value: Any, message: str) -> str:
    normalized = _safe_token(value, default="", max_length=128)
    if not normalized:
        raise TeamWorkflowOrchestrationError(message)
    return normalized


def _safe_token(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    text = _SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return (text or default)[:max_length]


def _trim_text(value: Any, *, max_length: int) -> str:
    text = str(value or "").strip()
    return text[:max_length]
