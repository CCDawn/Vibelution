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








def _source_collection_default_stage_agent(stage_id: str, *, agent_role: str = "") -> dict[str, Any] | None:
    return None


def _source_collection_stage_id_for_agent_role(agent_role: str) -> str:
    normalized_role = _normalize_source_collection_agent_role(agent_role)
    for stage_id, roles in SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES.items():
        if normalized_role in roles:
            return stage_id
    return "finding"


def _clean_source_collection_stage_agent_sessions_for_new_round(
    team_id: str,
    roles: list[str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized_team_id = _trim_text(team_id, max_length=160)
    cleanup: dict[str, Any] = {
        "status": "completed",
        "reason": "new_source_collection_round",
        "cleanedCount": 0,
        "items": [],
        "skipped": [],
    }
    agent_ids = payload.get("agentIds") if isinstance(payload.get("agentIds"), dict) else {}
    seen_agent_ids: set[str] = set()
    for role in roles:
        normalized_role = _normalize_source_collection_agent_role(role)
        if not normalized_role:
            continue
        agent_id = _trim_text(agent_ids.get(normalized_role), max_length=160)
        if not agent_id or agent_id in seen_agent_ids:
            continue
        seen_agent_ids.add(agent_id)
        agent = agent_directory_service.get_agent(agent_id)
        if not isinstance(agent, dict):
            cleanup["skipped"].append({"agentRole": normalized_role, "agentId": agent_id, "reason": "missing_agent"})
            continue
        session_id = _trim_text(agent.get("directSessionId"), max_length=160)
        if not session_id:
            cleanup["skipped"].append({"agentRole": normalized_role, "agentId": agent_id, "reason": "missing_direct_session"})
            continue
        evidence = _source_collection_stage_session_previous_round_evidence(session_id, run_id="")
        if not evidence:
            continue
        stage_id = _normalize_source_collection_stage_id(
            evidence.get("previousStageId") or _source_collection_stage_id_for_agent_role(normalized_role),
            default="finding",
        )
        try:
            reset_result = session_service.reset_agent_direct_session_lightweight(
                session_id,
                agent_id=agent_id,
                title=_source_collection_stage_task_title(stage_id),
            )
        except session_service.SessionNotFoundError:
            cleanup["skipped"].append({"agentRole": normalized_role, "agentId": agent_id, "sessionId": session_id, "reason": "missing_session"})
            continue
        except Exception as exc:
            _record_workflow_event(
                "source_collection.stage_session_cleanup_failed",
                normalized_team_id,
                level="warning",
                fields={
                    "agentRole": normalized_role,
                    "agentId": agent_id,
                    "previousDirectSessionId": session_id,
                    "previousSourceRunId": evidence.get("previousSourceRunId", ""),
                    "errorType": type(exc).__name__,
                },
            )
            raise TeamWorkflowOrchestrationError(
                f"Previous source collection Agent session records could not be cleaned: {exc}"
            ) from exc
        replacement_session_id = (
            _trim_text(reset_result.get("replacementDirectSessionId"), max_length=160)
            or _trim_text(reset_result.get("nextActiveSessionId"), max_length=160)
        )
        item = {
            "status": "cleaned",
            "reason": "previous_source_collection_round",
            "agentRole": normalized_role,
            "agentId": agent_id,
            "previousDirectSessionId": session_id,
            "replacementDirectSessionId": replacement_session_id,
            "previousSourceRunId": evidence.get("previousSourceRunId", ""),
            "previousTeamId": evidence.get("previousTeamId", ""),
            "previousMessageKind": evidence.get("previousMessageKind", ""),
        }
        cleanup["items"].append(item)
        _record_workflow_event(
            "source_collection.stage_session_cleaned_for_new_round",
            normalized_team_id,
            fields=item,
        )
    cleanup["cleanedCount"] = len(cleanup["items"])
    return cleanup








def _source_collection_background_snapshot_is_active(snapshot: dict[str, Any] | None, team_id: str, run_id: str) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if _source_collection_work_run_snapshot_is_stale(snapshot):
        return False
    if _trim_text(snapshot.get("runId"), max_length=160) != run_id:
        return False
    if _trim_text(snapshot.get("teamId"), max_length=160) != team_id:
        return False
    status = _trim_text(snapshot.get("status"), max_length=80).lower()
    current_phase = _trim_text(snapshot.get("currentPhase"), max_length=80).lower()
    return status in {"queued", "running"} or current_phase in {"queued", "running"}


def _coerce_source_collection_storage_path_soft(
    source_collection_work_run: dict[str, Any],
    *,
    team_id: str,
    run_id: str,
) -> tuple[Path | None, str]:
    raw_path = str(source_collection_work_run.get("storagePath") or "").strip()
    if not raw_path:
        return None, ""
    try:
        storage_path = Path(raw_path).expanduser()
    except Exception:
        return None, f"source collection storage path 无法解析（runId={run_id}）：{raw_path}"
    try:
        if not storage_path.is_absolute():
            storage_path = _project_root() / storage_path
        storage_path = storage_path.resolve()
        project_root = _project_root().resolve()
    except Exception:
        return None, f"source collection storage path 解析失败（runId={run_id}）：{raw_path}"
    if not storage_path.exists():
        return None, f"source collection storage path 不存在（runId={run_id}）：{storage_path}"
    if not storage_path.is_dir():
        return None, f"source collection storage path 不是目录（runId={run_id}）：{storage_path}"
    if storage_path == project_root:
        return None, f"source collection storage path 不可与主项目目录一致（runId={run_id}）。"
    try:
        storage_path.relative_to(project_root)
    except ValueError:
        return None, f"source collection storage path 不在项目目录内（runId={run_id}）：{storage_path}"
    normalized_team_id = _trim_text(team_id, max_length=96)
    normalized_run_id = _trim_text(run_id, max_length=96)
    if normalized_team_id and normalized_run_id:
        expected_run_directory = _source_collection_storage_artifact_paths(
            normalized_team_id,
            normalized_run_id,
        )["runDirectory"]
        try:
            expected_resolved = expected_run_directory.resolve()
        except Exception:
            expected_resolved = expected_run_directory
        if storage_path != expected_resolved:
            return (
                None,
                "source collection storage path 与历史快照中 teamId/runId 的预期路径不一致。"
                f" expected={_relative_path(expected_resolved)}",
            )
    return storage_path, ""


def _decorate_source_collection_work_run_snapshot(
    source_collection_work_run: dict[str, Any] | None,
    *,
    team_id: str = "",
    run_id: str = "",
) -> dict[str, Any] | None:
    if not isinstance(source_collection_work_run, dict):
        return None
    payload = dict(source_collection_work_run)
    normalized_team_id = team_id or _trim_text(payload.get("teamId"), max_length=96)
    normalized_run_id = run_id or _trim_text(payload.get("runId"), max_length=96)
    _, reason = _coerce_source_collection_storage_path_soft(
        payload,
        team_id=normalized_team_id,
        run_id=normalized_run_id,
    )
    if reason:
        payload.pop("storagePath", None)
        existing_reason = str(payload.get("pathValidationError") or "").strip()
        payload["pathValidationError"] = (
            f"{existing_reason}; {reason}" if existing_reason and existing_reason != reason else reason
        )
    if normalized_run_id:
        data_run_exists = _source_collection_data_run_exists(normalized_run_id)
        payload["dataRunExists"] = data_run_exists
        if not data_run_exists:
            _mark_source_collection_work_run_stale(payload, "missing_data_processing_run")
    return payload


def _source_collection_data_run_exists(run_id: str) -> bool:
    normalized_run_id = _trim_text(run_id, max_length=160)
    if not normalized_run_id:
        return False
    try:
        data_processing_service.get_processing_run(normalized_run_id)
    except data_processing_service.DataProcessingError:
        return False
    return True


def _mark_source_collection_work_run_stale(payload: dict[str, Any], reason: str) -> None:
    normalized_reason = _trim_text(reason, max_length=160)
    if not normalized_reason:
        return
    reasons = [
        _trim_text(item, max_length=160)
        for item in list(payload.get("staleReasons") or [])
        if _trim_text(item, max_length=160)
    ]
    if normalized_reason not in reasons:
        reasons.append(normalized_reason)
    payload["staleReasons"] = reasons
    payload["staleReason"] = reasons[0]


def _source_collection_work_run_snapshot_is_stale(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if snapshot.get("dataRunExists") is False:
        return True
    return bool([item for item in list(snapshot.get("staleReasons") or []) if _trim_text(item, max_length=160)])




def _sync_source_collection_stage_round_from_latest_work_run(team_id: str, run_id: str) -> dict[str, Any] | None:
    latest = load_source_collection_work_run_summary().get("latest")
    if not isinstance(latest, dict) or str(latest.get("runId") or "") != run_id:
        return None
    latest_status = str(latest.get("status") or "").lower()
    if latest_status in {"queued", "running"}:
        return None
    result = {
        "status": latest_status,
        "provider": SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
        "executedQueryCount": _source_collection_count(latest.get("executedQueryCount")),
        "failedQueryCount": _source_collection_count(latest.get("failedQueryCount")),
        "recordCount": _source_collection_count(latest.get("recordCount")),
        "importedCount": _source_collection_count(latest.get("importedCount")),
        "skippedDuplicateCount": _source_collection_count(latest.get("skippedDuplicateCount")),
        "remainingQueryCount": _source_collection_count(latest.get("searchOpenAssignmentCount")),
        "hasMore": latest_status == "needs_continue",
        "sourceCollectionSummary": latest.get("sourceCollection") if isinstance(latest.get("sourceCollection"), dict) else {},
    }
    synced = _sync_source_collection_stage_round_after_search(
        team_id,
        run_id,
        result,
        terminal_status=latest_status or "completed",
        terminal_summary=_trim_text(latest.get("summary"), max_length=500) or "资料搜索已结束。",
    )
    if synced is not None:
        _record_workflow_event(
            "research_stage_round.source_collection_search_recovered_from_work_run",
            team_id,
            fields={
                "runId": run_id,
                "stageRoundId": synced.get("stageRoundId", ""),
                "status": synced.get("status", ""),
                "searchStatus": latest_status or "completed",
                "recordCount": _source_collection_count(latest.get("recordCount")),
                "importedCount": _source_collection_count(latest.get("importedCount")),
                "remainingQueryCount": _source_collection_count(latest.get("searchOpenAssignmentCount")),
            },
        )
    return synced


def _source_collection_stage_records_for_run(run_id: str) -> list[dict[str, Any]]:
    try:
        payload = data_processing_service.list_records(run_id)
    except data_processing_service.DataProcessingError:
        return []
    return [item for item in list(payload.get("records") or []) if isinstance(item, dict)]


def _source_collection_record_id_suffix_lookup(records: list[dict[str, Any]]) -> dict[str, str]:
    buckets: dict[str, set[str]] = {}
    for record in records:
        record_id = _trim_text(record.get("recordId"), max_length=160)
        if not record_id:
            continue
        suffixes = {record_id}
        if "-" in record_id:
            suffixes.add(record_id.rsplit("-", 1)[-1])
        if len(record_id) >= 8:
            suffixes.add(record_id[-8:])
        for suffix in suffixes:
            if suffix:
                buckets.setdefault(suffix, set()).add(record_id)
    return {suffix: next(iter(values)) for suffix, values in buckets.items() if len(values) == 1}


def _resolve_source_collection_record_id(raw_record_id: str, records: list[dict[str, Any]]) -> tuple[str, str]:
    candidate = _trim_text(raw_record_id, max_length=160)
    if not candidate:
        return "", "missing_record_id"
    record_ids = {
        _trim_text(record.get("recordId"), max_length=160)
        for record in records
        if _trim_text(record.get("recordId"), max_length=160)
    }
    if candidate in record_ids:
        return candidate, ""
    suffix_lookup = _source_collection_record_id_suffix_lookup(records)
    matched = suffix_lookup.get(candidate)
    if matched:
        return matched, "record_id_suffix_matched"
    return "", "record_not_in_source_collection_run"


def _source_collection_record_extraction_effective_texts(extraction: dict[str, Any], record: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for key in (
        "valueSummary",
        "value_summary",
        "summary",
        "finding",
        "notes",
        "abstract",
        "usableContent",
        "usable_content",
    ):
        text = _trim_text(extraction.get(key), max_length=2000)
        if text:
            texts.append(text)
    for key in ("keyFindings", "key_findings", "findings"):
        for item in _normalize_text_list(extraction.get(key), max_items=12, max_length=300):
            if item:
                texts.append(item)
    record_summary = _trim_text(record.get("summary"), max_length=2000)
    if record_summary:
        texts.append(record_summary)
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    for key in ("abstract", "description"):
        text = _trim_text(metadata.get(key), max_length=2000)
        if text:
            texts.append(text)
    return texts


def _source_collection_record_extraction_has_effective_content(extraction: dict[str, Any], record: dict[str, Any]) -> bool:
    negative_fragments = (
        "no abstract",
        "no summary",
        "no usable",
        "placeholder",
        "landing page",
        "没有摘要",
        "没有正文",
        "无有效内容",
        "无法验证",
        "仅有占位",
    )
    for text in _source_collection_record_extraction_effective_texts(extraction, record):
        normalized = re.sub(r"\s+", " ", text.lower()).strip()
        if len(normalized) < 24:
            continue
        if any(fragment in normalized for fragment in negative_fragments):
            continue
        return True
    return False


def _source_collection_record_extraction_kept_status(extraction: dict[str, Any]) -> str:
    decision = _source_collection_stage_writeback_record_extraction_decision(extraction)
    has_defects = bool(
        _normalize_text_list(
            extraction.get("defects")
            or extraction.get("limitations")
            or extraction.get("riskFlags")
            or extraction.get("risk_flags"),
            max_items=12,
            max_length=180,
        )
        or _trim_text(extraction.get("followUpSuggestion") or extraction.get("follow_up_suggestion"), max_length=500)
    )
    if decision in SOURCE_COLLECTION_KEEP_WITH_NOTES_DECISIONS or has_defects:
        return "kept_with_notes"
    return "kept"


def _source_collection_extraction_key_finding_texts(extraction: dict[str, Any]) -> list[str]:
    raw_findings = extraction.get("keyFindings") or extraction.get("key_findings") or extraction.get("findings")
    if not isinstance(raw_findings, list):
        return []
    findings: list[str] = []
    for item in raw_findings[:12]:
        if isinstance(item, dict):
            text = _trim_text(
                item.get("finding")
                or item.get("claim")
                or item.get("summary")
                or item.get("text"),
                max_length=240,
            )
        else:
            text = _trim_text(item, max_length=240)
        if text and text not in findings:
            findings.append(text)
    return findings


def _source_collection_extraction_claim_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    claims: list[dict[str, str]] = []
    for item in value[:24]:
        if isinstance(item, dict):
            claim = _trim_text(item.get("claim") or item.get("finding") or item.get("summary") or item.get("text"), max_length=600)
            normalized = {
                "claim": claim,
                "sourceRef": _trim_text(item.get("sourceRef") or item.get("sourceRefId") or item.get("sourceId"), max_length=240),
                "page": _trim_text(item.get("page") or item.get("pageAnchor") or item.get("pageRange"), max_length=120),
                "citation": _trim_text(item.get("citation") or item.get("citationAnchor"), max_length=300),
                "evidenceRef": _trim_text(item.get("evidenceRef") or item.get("evidenceRefId"), max_length=240),
                "supportLevel": _trim_text(item.get("supportLevel") or item.get("support") or item.get("confidence"), max_length=80),
            }
        else:
            normalized = {
                "claim": _trim_text(item, max_length=600),
                "sourceRef": "",
                "page": "",
                "citation": "",
                "evidenceRef": "",
                "supportLevel": "",
            }
        compact = {key: item_value for key, item_value in normalized.items() if item_value}
        if compact:
            claims.append(compact)
    return claims


def _source_collection_extraction_key_finding_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    findings: list[dict[str, str]] = []
    for item in value[:24]:
        if isinstance(item, dict):
            finding = _trim_text(item.get("finding") or item.get("claim") or item.get("summary") or item.get("text"), max_length=600)
            normalized = {
                "finding": finding,
                "sourceRef": _trim_text(item.get("sourceRef") or item.get("sourceRefId") or item.get("sourceId"), max_length=240),
                "page": _trim_text(item.get("page") or item.get("pageAnchor") or item.get("pageRange"), max_length=120),
                "citation": _trim_text(item.get("citation") or item.get("citationAnchor"), max_length=300),
                "evidenceRef": _trim_text(item.get("evidenceRef") or item.get("evidenceRefId"), max_length=240),
                "supportLevel": _trim_text(item.get("supportLevel") or item.get("support") or item.get("confidence"), max_length=80),
            }
        else:
            normalized = {
                "finding": _trim_text(item, max_length=600),
                "sourceRef": "",
                "page": "",
                "citation": "",
                "evidenceRef": "",
                "supportLevel": "",
            }
        compact = {key: item_value for key, item_value in normalized.items() if item_value}
        if compact:
            findings.append(compact)
    return findings


def _source_collection_extraction_citation_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    citations: list[dict[str, str]] = []
    for item in value[:24]:
        if isinstance(item, dict):
            normalized = {
                "sourceRef": _trim_text(item.get("sourceRef") or item.get("sourceRefId") or item.get("sourceId"), max_length=240),
                "page": _trim_text(item.get("page") or item.get("pageAnchor") or item.get("pageRange"), max_length=120),
                "citation": _trim_text(item.get("citation") or item.get("citationAnchor") or item.get("text"), max_length=300),
                "evidenceRef": _trim_text(item.get("evidenceRef") or item.get("evidenceRefId"), max_length=240),
            }
        else:
            normalized = {
                "sourceRef": "",
                "page": "",
                "citation": _trim_text(item, max_length=300),
                "evidenceRef": "",
            }
        compact = {key: item_value for key, item_value in normalized.items() if item_value}
        if compact:
            citations.append(compact)
    return citations


def _source_collection_extraction_has_evidence_anchor(ledger: dict[str, Any]) -> bool:
    if _normalize_ref_list(ledger.get("evidenceRefs"), max_items=24):
        return True
    for key in ("claims", "keyFindings", "citations"):
        for item in list(ledger.get(key) or []):
            if isinstance(item, dict) and _has_citation_anchor(item):
                return True
    return False


def _source_collection_extraction_evidence_ledger(
    extraction: dict[str, Any],
    *,
    fallback_evidence_refs: Any = None,
) -> dict[str, Any]:
    key_findings_value = extraction.get("keyFindings") or extraction.get("key_findings") or extraction.get("findings")
    evidence_refs = _normalize_ref_list(
        extraction.get("evidenceRefs") or extraction.get("evidence_refs") or fallback_evidence_refs,
        max_items=24,
    )
    ledger = {
        "sourceRefs": _normalize_ref_list(extraction.get("sourceRefs") or extraction.get("source_refs"), max_items=24),
        "evidenceRefs": evidence_refs,
        "claims": _source_collection_extraction_claim_items(extraction.get("claims")),
        "keyFindings": _source_collection_extraction_key_finding_items(key_findings_value),
        "citations": _source_collection_extraction_citation_items(extraction.get("citations")),
        "limitations": _normalize_text_list(
            extraction.get("limitations") or extraction.get("defects"),
            max_items=12,
            max_length=240,
        ),
        "uncertainty": _normalize_text_list(extraction.get("uncertainty"), max_items=12, max_length=240),
        "riskFlags": _normalize_text_list(
            extraction.get("riskFlags") or extraction.get("risk_flags") or extraction.get("risks"),
            max_items=12,
            max_length=120,
        ),
        "supportLevel": _trim_text(extraction.get("supportLevel") or extraction.get("support") or extraction.get("confidence"), max_length=80),
        "nextAction": _trim_text(extraction.get("nextAction") or extraction.get("next_action") or extraction.get("followUpSuggestion"), max_length=240),
    }
    compact = {key: value for key, value in ledger.items() if value not in ("", [], {})}
    if not compact:
        return {}
    compact["status"] = "evidence_ready" if _source_collection_extraction_has_evidence_anchor(compact) else "missing_evidence_anchor"
    return compact


def _source_collection_record_extraction_metadata(
    extraction: dict[str, Any],
    *,
    record_id: str,
    task_id: str,
    run_id: str,
    stage_id: str,
    recorded_by_agent: str,
) -> dict[str, Any]:
    value_summary = _trim_text(extraction.get("valueSummary") or extraction.get("value_summary"), max_length=2000)
    defects = _normalize_text_list(
        extraction.get("defects")
        or extraction.get("limitations")
        or extraction.get("riskFlags")
        or extraction.get("risk_flags"),
        max_items=12,
        max_length=180,
    )
    follow_up = _trim_text(
        extraction.get("followUpSuggestion")
        or extraction.get("follow_up_suggestion")
        or extraction.get("nextStep")
        or extraction.get("next_step"),
        max_length=600,
    )
    decision = _source_collection_stage_writeback_record_extraction_decision(extraction)
    content_extraction = {
        "status": _source_collection_record_extraction_kept_status(extraction),
        "decision": decision,
        "valueSummary": value_summary,
        "defects": defects,
        "followUpSuggestion": follow_up,
        "summary": _trim_text(
            value_summary
            or extraction.get("summary")
            or extraction.get("finding")
            or extraction.get("notes")
            or extraction.get("reason"),
            max_length=2000,
        ),
        "keyFindings": _source_collection_extraction_key_finding_texts(extraction)
        or _normalize_text_list(
            extraction.get("keyFindings") or extraction.get("key_findings") or extraction.get("findings"),
            max_items=12,
            max_length=240,
        ),
        "riskFlags": _normalize_text_list(
            extraction.get("riskFlags") or extraction.get("risk_flags") or extraction.get("risks"),
            max_items=12,
            max_length=120,
        ),
        "evidenceRefs": _normalize_ref_list(
            extraction.get("evidenceRefs") or extraction.get("evidence_refs"),
            max_items=24,
        ),
        "sourceRecordId": record_id,
        "taskId": task_id,
        "runId": _trim_text(run_id, max_length=160),
        "stageId": stage_id,
        "recordedByAgent": recorded_by_agent,
        "recordedAt": utc_now_iso(),
    }
    evidence_ledger = _source_collection_extraction_evidence_ledger(extraction)
    if evidence_ledger:
        content_extraction["evidenceLedger"] = evidence_ledger
        content_extraction["evidenceStatus"] = evidence_ledger["status"]
    return content_extraction


def _update_source_candidate_content_extraction(
    team_id: str,
    candidate_id: str,
    content_extraction: dict[str, Any],
) -> None:
    normalized_candidate_id = _trim_text(candidate_id, max_length=160)
    if not normalized_candidate_id:
        return
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(team_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
        changed = False
        for candidate in candidates:
            if _trim_text(candidate.get("candidateId"), max_length=160) != normalized_candidate_id:
                continue
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            metadata["contentExtraction"] = _normalize_metadata(content_extraction)
            candidate["metadata"] = metadata
            candidate["updatedAt"] = utc_now_iso()
            changed = True
            break
        if changed:
            candidate_store["updatedAt"] = utc_now_iso()
            _write_json(_candidate_store_path(team_id), candidate_store)


def _source_collection_agent_graph_nodes(agent_graph: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for item in list(agent_graph.get("nodes") or []):
        if not isinstance(item, dict):
            continue
        node_id = _trim_text(item.get("candidateId") or item.get("id"), max_length=160)
        if not node_id:
            continue
        nodes.append(
            {
                "candidateId": node_id,
                "candidateType": _trim_text(item.get("candidateType") or item.get("type"), max_length=80) or "agent_relation_node",
                "title": _trim_text(item.get("title") or item.get("label") or node_id, max_length=240),
                "currentWorkflowNode": _trim_text(item.get("currentWorkflowNode"), max_length=120) or "candidate_graph",
                "currentState": _trim_text(item.get("currentState"), max_length=120) or "candidate_graph_visible",
                "qualityStatus": _trim_text(item.get("qualityStatus"), max_length=120) or "preview_ready",
                "valid": bool(item.get("valid", True)),
                "requiresReview": bool(item.get("requiresReview", False)),
                "officialState": _trim_text(item.get("officialState"), max_length=80) or "candidate_only",
            }
        )
    for item in list(agent_graph.get("themeNodes") or []):
        if not isinstance(item, dict):
            continue
        theme_id = _source_collection_agent_graph_theme_id(item)
        if not theme_id:
            continue
        nodes.append(
            {
                "candidateId": _source_collection_agent_graph_theme_node_id(theme_id),
                "candidateType": "source_topic",
                "title": _trim_text(item.get("label") or item.get("title") or theme_id, max_length=240),
                "currentWorkflowNode": "candidate_graph",
                "currentState": "candidate_graph_visible",
                "qualityStatus": "preview_ready",
                "valid": True,
                "requiresReview": False,
                "officialState": "candidate_only",
            }
        )
    return nodes


def _source_collection_agent_graph_edges(agent_graph: dict[str, Any]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for item in list(agent_graph.get("edges") or []):
        if not isinstance(item, dict):
            continue
        source_id = _trim_text(item.get("sourceCandidateId") or item.get("source") or item.get("from"), max_length=160)
        target_id = _trim_text(item.get("targetCandidateId") or item.get("target") or item.get("to"), max_length=160)
        relation = _trim_text(item.get("relation") or item.get("relationType") or item.get("type"), max_length=160)
        if source_id and target_id and relation:
            edges.append(_candidate_graph_edge(source_id, target_id, relation))
    for item in list(agent_graph.get("sourceThemeEdges") or []):
        if not isinstance(item, dict):
            continue
        source_id = _trim_text(
            item.get("candidateId") or item.get("candidate_id") or item.get("sourceCandidateId") or item.get("source_candidate_id"),
            max_length=160,
        )
        theme_id = _source_collection_agent_graph_theme_id(item)
        relation = _trim_text(item.get("relation") or item.get("relationType") or item.get("relation_type"), max_length=160) or "source_supports_theme"
        if source_id and theme_id:
            edges.append(_candidate_graph_edge(source_id, _source_collection_agent_graph_theme_node_id(theme_id), relation))
    for item in list(agent_graph.get("topicRelations") or []):
        if not isinstance(item, dict):
            continue
        source_theme_id = _trim_text(
            item.get("from")
            or item.get("fromThemeId")
            or item.get("from_theme_id")
            or item.get("sourceThemeId")
            or item.get("source_theme_id"),
            max_length=160,
        )
        target_theme_id = _trim_text(
            item.get("to")
            or item.get("toThemeId")
            or item.get("to_theme_id")
            or item.get("targetThemeId")
            or item.get("target_theme_id"),
            max_length=160,
        )
        relation = _trim_text(item.get("relation") or item.get("relationType") or item.get("relation_type"), max_length=160)
        if source_theme_id and target_theme_id and relation:
            edges.append(
                _candidate_graph_edge(
                    _source_collection_agent_graph_theme_node_id(source_theme_id),
                    _source_collection_agent_graph_theme_node_id(target_theme_id),
                    relation,
                )
            )
    return edges


def _source_collection_agent_graph_theme_id(item: dict[str, Any]) -> str:
    return _trim_text(
        item.get("themeId") or item.get("theme_id") or item.get("topicId") or item.get("topic_id") or item.get("id"),
        max_length=160,
    )


def _source_collection_agent_graph_theme_node_id(theme_id: str) -> str:
    normalized = _trim_text(theme_id, max_length=160)
    return f"source-theme:{normalized}" if normalized and not normalized.startswith("source-theme:") else normalized


def _source_collection_stage_quality_materialization_child_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": _trim_text(summary.get("status"), max_length=80),
        "assessedCandidateCount": _source_collection_count(summary.get("assessedCandidateCount")),
        "approvedCandidateCount": _source_collection_count(summary.get("approvedCandidateCount")),
        "needsRevisionCandidateCount": _source_collection_count(summary.get("needsRevisionCandidateCount")),
        "rejectedCandidateCount": _source_collection_count(summary.get("rejectedCandidateCount")),
        "skippedCandidateCount": _source_collection_count(summary.get("skippedCandidateCount")),
        "failedCandidateCount": _source_collection_count(summary.get("failedCandidateCount")),
        "assessedCandidates": _bounded_log_items(summary.get("assessedCandidates"), ("candidateId", "decision", "assessmentId"), max_items=40),
        "skippedCandidates": _bounded_log_items(summary.get("skippedCandidates"), ("candidateId", "reason"), max_items=40),
        "failedCandidates": _bounded_log_items(summary.get("failedCandidates"), ("candidateId", "reason", "errorType", "error"), max_items=24),
    }


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


def _source_collection_stage_invalid_source_record(source: dict[str, Any]) -> dict[str, Any]:
    doi = _source_collection_extract_doi(
        source.get("doi"),
        source.get("DOI"),
        source.get("locator"),
        source.get("sourceRef"),
        source.get("sourceUrl"),
        source.get("url"),
    )
    source_ref = _trim_text(
        source.get("sourceRef")
        or source.get("source_ref")
        or source.get("sourceUrl")
        or source.get("url")
        or source.get("locator"),
        max_length=2000,
    )
    if doi and not source_ref:
        source_ref = f"https://doi.org/{doi}"
    raw_location = _trim_text(source.get("rawLocation") or source.get("raw_location") or source.get("url"), max_length=2000)
    metadata = _normalize_metadata(source.get("metadata"))
    if doi:
        metadata["doi"] = doi
    container = _trim_text(source.get("container") or source.get("venue") or source.get("journal"), max_length=240)
    if container:
        metadata["containerTitle"] = container
    published = _trim_text(source.get("published") or source.get("year"), max_length=80)
    if published:
        metadata["published"] = published
    return {
        "recordId": _trim_text(source.get("recordId") or source.get("record_id"), max_length=160),
        "title": _trim_text(source.get("title"), max_length=260),
        "sourceType": _trim_text(source.get("sourceType") or source.get("type") or "invalid_source", max_length=80),
        "sourceRef": source_ref,
        "rawLocation": raw_location or source_ref,
        "metadata": metadata,
    }


def _source_collection_candidate_count_for_run(candidate_store: dict[str, Any], run_id: str) -> int:
    count = 0
    for candidate in list(candidate_store.get("candidates") or []):
        if not isinstance(candidate, dict) or _candidate_is_archived(candidate):
            continue
        if str(candidate.get("candidateType") or "") != "source_manifest":
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        if str(imported_from.get("runId") or "") == run_id:
            count += 1
    return count



def _reconcile_superseded_research_stage_rounds(team_id: str) -> bool:
    now = utc_now_iso()
    superseded_pairs: list[tuple[str, str]] = []
    with _WORKFLOW_LOCK:
        store = _load_stage_round_store(team_id)
        rounds = _stage_rounds(store)
        for stage_type in RESEARCH_STAGE_TYPES:
            stage_rounds = [
                item
                for item in rounds
                if _trim_text(item.get("stageType"), max_length=80) == stage_type
            ]
            if len(stage_rounds) < 2:
                continue
            latest_round = max(
                stage_rounds,
                key=lambda item: (
                    _source_collection_count(item.get("roundNumber")),
                    _trim_text(item.get("createdAt"), max_length=120),
                    _trim_text(item.get("updatedAt"), max_length=120),
                ),
            )
            latest_round_id = _trim_text(latest_round.get("stageRoundId"), max_length=160)
            for stage_round in stage_rounds:
                stage_round_id = _trim_text(stage_round.get("stageRoundId"), max_length=160)
                if stage_round is latest_round or not stage_round_id:
                    continue
                if _trim_text(stage_round.get("status"), max_length=80) not in RESEARCH_STAGE_ACTIVE_STATUSES:
                    continue
                stage_round["status"] = "superseded"
                stage_round["supersededByStageRoundId"] = latest_round_id
                stage_round["supersededAt"] = now
                stage_round["updatedAt"] = now
                warnings = [item for item in list(stage_round.get("warnings") or []) if isinstance(item, dict)]
                if not any(_trim_text(item.get("code"), max_length=120) == "stage_round_superseded" for item in warnings):
                    warnings.append(
                        {
                            "code": "stage_round_superseded",
                            "severity": "info",
                            "message": "A newer round of the same research stage superseded this active round.",
                        }
                    )
                stage_round["warnings"] = warnings
                superseded_pairs.append((stage_round_id, latest_round_id))
        if superseded_pairs:
            store["updatedAt"] = now
            _write_json(_stage_round_store_path(team_id), store)
    for stage_round_id, latest_round_id in superseded_pairs:
        _record_workflow_event(
            "research_stage_round.superseded_by_newer_round",
            team_id,
            fields={
                "stageRoundId": stage_round_id,
                "supersededByStageRoundId": latest_round_id,
            },
            outcome="reconciled",
            lifecycle=True,
        )
    return bool(superseded_pairs)







_SMOKE_DECISION_TO_STATUS = {
    "accept": "passed",
    "iterate": "passed",
    "reject": "failed",
    "needs_full_run": "needs_review",
}











RESEARCH_REVIEW_DECISIONS = {"approve", "revise", "reject", "needs_human"}


ITERATION_ACTIONS = {"iterate", "reject", "merge", "hold"}


def propose_iteration(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-12：持续迭代与版本化（节点 11）。根据 RunnerResult/审稿/steward 决策提出迭代提案。

    硬约束：不覆盖原候选，只新建版本/归档；无 changeReason 的状态变化拒绝写入；检测并拒绝
    circular supersedes。版本链边记录在父候选 metadata.versionEdges（supersedes / rejected_because /
    merged_with），提案记录在 metadata.iterationProposals。
    """
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    parent_id = _normalize_required_id(payload.get("parentCandidateId") or payload.get("candidateId"), "parentCandidateId is required.")
    action = _trim_text(payload.get("action"), max_length=40).strip().lower()
    if action not in ITERATION_ACTIONS:
        raise TeamWorkflowOrchestrationError("action must be iterate/reject/merge/hold.")
    change_reason = _trim_text(payload.get("changeReason"), max_length=2000)
    if action != "hold" and not change_reason:
        raise TeamWorkflowOrchestrationError(f"{action} iteration requires a changeReason.")
    proposed_by = _trim_text(payload.get("proposedByAgent"), max_length=160) or "Iteration Versioning Agent"
    merge_with = _trim_text(payload.get("mergeWithCandidateId"), max_length=128)
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(normalized_team_id)
        parent = _find_candidate(candidate_store, parent_id)
        if parent is None:
            raise TeamWorkflowOrchestrationError("Candidate not found.")
        metadata = parent.get("metadata") if isinstance(parent.get("metadata"), dict) else {}
        version_edges = metadata.get("versionEdges") if isinstance(metadata.get("versionEdges"), list) else []
        proposal_id = _new_record_id("iteration")
        new_edges: list[dict[str, Any]] = []
        new_draft: dict[str, Any] | None = None
        rejection_archive: dict[str, Any] | None = None
        if action == "iterate":
            draft_id = _new_record_id("candidate")
            new_draft = {
                "candidateId": draft_id,
                "parentCandidateId": parent_id,
                "candidateType": str(parent.get("candidateType") or ""),
                "status": "iteration_draft",
                "changeReason": change_reason,
            }
            new_edges.append({"edgeType": "supersedes", "from": draft_id, "to": parent_id})
        elif action == "reject":
            rejection_archive = {
                "parentCandidateId": parent_id,
                "reason": change_reason,
                "evidenceRefs": _normalize_ref_list(payload.get("evidenceRefs"), max_items=24),
                "archivedAt": now,
            }
            new_edges.append({"edgeType": "rejected_because", "from": parent_id, "to": proposal_id})
        elif action == "merge":
            if not merge_with:
                raise TeamWorkflowOrchestrationError("merge iteration requires mergeWithCandidateId.")
            new_edges.append({"edgeType": "merged_with", "from": parent_id, "to": merge_with})
        for edge in new_edges:
            if edge["edgeType"] != "supersedes":
                continue
            for existing in version_edges:
                if (
                    existing.get("edgeType") == "supersedes"
                    and existing.get("from") == edge["to"]
                    and existing.get("to") == edge["from"]
                ):
                    raise TeamWorkflowOrchestrationError("Circular supersedes detected; cannot create version cycle.")
        proposal = {
            "proposalId": proposal_id,
            "parentCandidateId": parent_id,
            "action": action,
            "changeReason": change_reason,
            "versionEdges": new_edges,
            "newCandidateDraft": new_draft,
            "rejectionArchive": rejection_archive,
            "mergeWithCandidateId": merge_with,
            "proposedByAgent": proposed_by,
            "createdAt": now,
        }
        proposals = metadata.get("iterationProposals") if isinstance(metadata.get("iterationProposals"), list) else []
        metadata["iterationProposals"] = [*proposals[-23:], proposal]
        metadata["versionEdges"] = [*version_edges, *new_edges]
        parent["metadata"] = metadata
        parent["updatedAt"] = now
        candidate_store["updatedAt"] = now
        _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        workflow = _load_or_create_workflow(normalized_team_id)
        version_edges_after = list(metadata["versionEdges"])
    _record_workflow_event(
        "candidate.iteration_proposed",
        normalized_team_id,
        fields={"parentCandidateId": parent_id, "proposalId": proposal_id, "action": action},
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "parentCandidateId": parent_id,
        "action": action,
        "proposal": proposal,
        "versionEdges": version_edges_after,
        "workflowId": workflow["workflowId"],
    }


def export_deliverables(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-13：交付材料导出（节点 12）。只读 official/approved/明确标注的证据，生成
    deliverable_manifest + blockers；不反写知识库。证据不足时输出 blocker 清单而非伪造完整材料。
    """
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    requested_by = _trim_text(payload.get("requestedByAgent"), max_length=160) or "Challenge Cup Delivery Agent"
    now = utc_now_iso()

    candidate_store = _load_candidate_store(normalized_team_id)
    candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    candidate_breakdown: dict[str, int] = {}
    for candidate in candidates:
        candidate_type = str(candidate.get("candidateType") or "")
        candidate_breakdown[candidate_type] = candidate_breakdown.get(candidate_type, 0) + 1

    reviewed_hypotheses = [
        candidate
        for candidate in candidates
        if candidate.get("candidateType") == "algorithm_hypothesis"
        and isinstance(candidate.get("metadata"), dict)
        and any(
            str(record.get("decision")) == "approve"
            for record in (candidate["metadata"].get("reviewRecords") or [])
            if isinstance(record, dict)
        )
    ]

    plan_store = _load_experiment_plan_store(normalized_team_id)
    artifact_refs: list[dict[str, Any]] = []
    for plan in list(plan_store.get("plans") or []):
        if not isinstance(plan, dict):
            continue
        for run in plan.get("smokeRunResults") or []:
            if isinstance(run, dict) and run.get("artifactHash"):
                artifact_refs.append(
                    {
                        "planId": plan.get("planId"),
                        "smokeRunId": run.get("smokeRunId"),
                        "artifactHash": run.get("artifactHash"),
                        "status": run.get("status"),
                    }
                )

    ingestion_status = get_knowledge_ingestion_status(normalized_team_id)
    formal_item_count = int((ingestion_status.get("summary") or {}).get("formalKnowledgeItemCount") or 0)

    evidence_refs: list[dict[str, str]] = []
    for candidate in reviewed_hypotheses:
        evidence_refs.extend(_normalize_ref_list(candidate.get("evidenceRefs"), max_items=24))

    blockers: list[dict[str, str]] = []
    if not reviewed_hypotheses:
        blockers.append({"code": "no_reviewed_hypothesis", "message": "至少需要 1 个已审稿通过的 algorithm_hypothesis。"})
    if not artifact_refs:
        blockers.append({"code": "experiment_loop_incomplete", "message": "缺 runner_result/artifactHash；实验闭环未完成。"})
    if formal_item_count <= 0:
        blockers.append({"code": "no_official_knowledge", "message": "尚无正式 KnowledgeItem（official_synced）。"})

    sections = [
        {"key": "problem", "label": "问题定义", "ready": bool(reviewed_hypotheses)},
        {"key": "architecture", "label": "方法/架构", "ready": bool(reviewed_hypotheses)},
        {"key": "experiment", "label": "实验与证据", "ready": bool(artifact_refs)},
        {"key": "reproducibility", "label": "复现包", "ready": bool(artifact_refs)},
        {"key": "official_knowledge", "label": "正式知识", "ready": formal_item_count > 0},
    ]
    manifest = {
        "deliverableId": _new_record_id("deliverable"),
        "teamId": normalized_team_id,
        "generatedAt": now,
        "requestedByAgent": requested_by,
        "sections": sections,
        "evidenceRefs": evidence_refs[:48],
        "artifactRefs": artifact_refs[:48],
        "officialBoundary": {
            "formalKnowledgeItemCount": formal_item_count,
            "reusesOfficialOnly": True,
            "writesBackToKnowledge": False,
        },
        "candidateBreakdown": candidate_breakdown,
        "blockers": blockers,
        "status": "ready" if not blockers else "blocked",
    }
    _record_workflow_event(
        "deliverables.exported",
        normalized_team_id,
        fields={"deliverableId": manifest["deliverableId"], "status": manifest["status"], "blockerCount": len(blockers)},
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "deliverableManifest": manifest,
        "status": manifest["status"],
        "blockers": blockers,
    }


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



def _source_collection_phase_close_gate(
    run_id: str,
    *,
    projection: dict[str, Any],
    stage_round_ref: dict[str, Any],
) -> dict[str, Any]:
    normalized_run_id = _trim_text(run_id, max_length=160)
    cards_by_stage = {
        _normalize_source_collection_stage_id(item.get("stageId"), default=""): item
        for item in list(projection.get("cards") or [])
        if isinstance(item, dict) and _normalize_source_collection_stage_id(item.get("stageId"), default="")
    }
    stages: list[dict[str, Any]] = []
    blocking_reasons: list[str] = []
    for stage_id in SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
        card = cards_by_stage.get(stage_id, {})
        passed = bool(card.get("isClosedLoop"))
        card_reasons = [
            _trim_text(item, max_length=500)
            for item in list(card.get("blockingReasons") or [])
            if _trim_text(item, max_length=500)
        ]
        if not passed and not card_reasons:
            card_reasons = [f"{stage_id} 阶段尚未形成闭环。"]
        blocking_reasons.extend(card_reasons)
        stages.append(
            {
                "stageId": stage_id,
                "status": _trim_text(card.get("status"), max_length=80) or "not_started",
                "passed": passed,
                "artifactStatus": _trim_text(card.get("artifactStatus"), max_length=80),
                "agentTaskStatus": _trim_text(card.get("agentTaskStatus"), max_length=80) or "not_started",
                "currentCoverageSummary": card.get("currentCoverageSummary")
                if isinstance(card.get("currentCoverageSummary"), dict)
                else {},
                "blockingReasons": card_reasons,
            }
        )
    stage_count = len(stages)
    closed_loop_count = sum(1 for stage in stages if stage["passed"])
    stage_gate_passed = (
        bool(normalized_run_id)
        and stage_count == len(SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES)
        and closed_loop_count == stage_count
    )
    stage_round_status = _trim_text(stage_round_ref.get("status"), max_length=80).lower()
    state_reconciliation_required = stage_gate_passed and stage_round_status not in {"completed", "closed_loop"}
    if not normalized_run_id:
        gate_status = "idle"
        blocking_reasons = ["尚未选择资料搜集运行批次。"]
    elif not stage_gate_passed:
        gate_status = "needs_continue"
    elif state_reconciliation_required:
        gate_status = "ready_to_close"
        blocking_reasons.append("四个阶段产物已齐备，等待阶段轮次状态收口。")
    else:
        gate_status = "closed_loop"
    return {
        "runId": normalized_run_id,
        "stageRoundId": _trim_text(stage_round_ref.get("stageRoundId"), max_length=160),
        "stageRoundStatus": stage_round_status,
        "status": gate_status,
        "passed": gate_status == "closed_loop",
        "stageGatePassed": stage_gate_passed,
        "stateReconciliationRequired": state_reconciliation_required,
        "stageCount": stage_count,
        "closedLoopCount": closed_loop_count,
        "stages": stages,
        "blockingReasons": list(dict.fromkeys(blocking_reasons)),
    }


def _record_source_collection_summary_timing(
    team_id: str,
    run_id: str,
    payload: dict[str, Any],
    started_at: float,
) -> None:
    duration_ms = int(round((time.perf_counter() - started_at) * 1000))
    if duration_ms < SOURCE_COLLECTION_SUMMARY_SLOW_EVENT_MS:
        return
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    phase_close_gate = payload.get("phaseCloseGate") if isinstance(payload.get("phaseCloseGate"), dict) else {}
    _record_workflow_event(
        "source_collection.summary.slow",
        team_id,
        level="warning",
        outcome="degraded",
        fields={
            "runId": _trim_text(run_id, max_length=160),
            "durationMs": duration_ms,
            "recordCount": _source_collection_count(summary.get("recordCount")),
            "sourceCandidateCount": _source_collection_count(summary.get("sourceCandidateCount")),
            "stageCardCount": len(list(payload.get("stageCards") or [])),
            "phaseCloseGateStatus": _trim_text(phase_close_gate.get("status"), max_length=80),
            "phaseCloseGatePassed": bool(phase_close_gate.get("passed")),
            "activeWorkRun": bool(payload.get("activeWorkRun")),
        },
    )




def _team_workflow_kernel_delivery(kernel_result: dict[str, Any], target_agent_id: str) -> dict[str, Any]:
    outcome = kernel_result.get("outcome") if isinstance(kernel_result.get("outcome"), dict) else {}
    deliveries = outcome.get("deliveries") if isinstance(outcome.get("deliveries"), list) else []
    normalized_target_agent_id = str(target_agent_id or "").strip()
    for delivery in deliveries:
        if not isinstance(delivery, dict):
            continue
        if str(delivery.get("targetAgentId") or "").strip() == normalized_target_agent_id:
            return dict(delivery)
    return dict(deliveries[0]) if deliveries and isinstance(deliveries[0], dict) else {}


def _team_workflow_inbox_message_from_kernel_delivery(
    target_agent_id: str,
    delivery: dict[str, Any],
    *,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    message_id = str(
        delivery.get("inboxMessageId")
        or (delivery.get("wake", {}) if isinstance(delivery.get("wake"), dict) else {}).get("messageId")
        or ""
    ).strip()
    if message_id:
        for message in agent_directory_service.list_agent_inbox_messages_for_agent(
            target_agent_id,
            limit=100,
            status="",
        ):
            if str(message.get("messageId") or message.get("eventId") or "").strip() == message_id:
                return message
    message = dict(fallback)
    if message_id:
        message["messageId"] = message_id
        message.setdefault("eventId", message_id)
    message["targetAgentId"] = str(target_agent_id or "").strip()
    message["targetSessionId"] = str(
        delivery.get("targetSessionId")
        or (delivery.get("wake", {}) if isinstance(delivery.get("wake"), dict) else {}).get("targetSessionId")
        or ""
    ).strip()
    return message


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


def _submit_team_workflow_inbox_via_kernel(
    *,
    target_agent_id: str,
    content: str,
    source_agent_id: str,
    thread_id: str,
    kind: str,
    summary: str,
    created_by: str,
    metadata: dict[str, Any],
    wake_target: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from core.agent_kernel.adapters import submit_agent_message_event

    normalized_metadata = dict(metadata or {})
    source_id = str(thread_id or normalized_metadata.get("sourceMessageId") or "").strip()
    created_by_value = str(created_by or source_agent_id or "team_workflow").strip()
    kernel_metadata = {
        **normalized_metadata,
        "source": "team_workflow_orchestration",
        "sourceSurface": "team_workflow",
        "sourceMessageId": source_id,
        "projectionRef": {"kind": kind, "id": source_id},
        "senderAgentId": source_agent_id,
        "sourceAgentId": source_agent_id,
        "inboxKind": kind,
        "messageSummary": summary,
        "inboxCreatedBy": created_by_value,
    }
    if normalized_metadata:
        kernel_metadata["agentToolMetadataJson"] = json.dumps(normalized_metadata, ensure_ascii=False, sort_keys=True)
    sender = (
        {"type": "agent", "id": source_agent_id, "agentId": source_agent_id}
        if source_agent_id
        else {"type": "system", "id": created_by_value}
    )
    kernel_result = submit_agent_message_event(
        source="team_workflow",
        sender=sender,
        recipient_agent_ids=[target_agent_id],
        content=content,
        correlation_id=thread_id,
        wake_target=wake_target,
        metadata=kernel_metadata,
        source_id=source_id,
    )
    kernel_delivery = _team_workflow_kernel_delivery(kernel_result, target_agent_id)
    if str(kernel_delivery.get("status") or "").strip() != "delivered":
        raise agent_directory_service.AgentDirectoryError(str(kernel_delivery.get("reason") or "Kernel delivery failed."))
    message = _team_workflow_inbox_message_from_kernel_delivery(
        target_agent_id,
        kernel_delivery,
        fallback={
            "sourceAgentId": source_agent_id,
            "targetAgentId": target_agent_id,
            "threadId": thread_id,
            "kind": kind,
            "summary": summary,
            "metadata": kernel_metadata,
        },
    )
    delivery = (
        kernel_delivery.get("wake")
        if isinstance(kernel_delivery.get("wake"), dict)
        else {
            "wakeRequested": bool(wake_target),
            "wakeStatus": "not_requested" if not wake_target else "skipped",
            "messageId": str(message.get("messageId") or message.get("eventId") or "").strip(),
            "targetAgentId": target_agent_id,
            "targetSessionId": str(message.get("targetSessionId") or "").strip(),
            "turnId": "",
            "reason": "",
        }
    )
    return message, delivery, kernel_result


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


def validate_candidate_record(candidate: dict[str, Any]) -> dict[str, Any]:
    candidate_type = _trim_text(candidate.get("candidateType"), max_length=80)
    issues: list[dict[str, str]] = []
    if not candidate_type:
        issues.append({"severity": "error", "code": "missing_candidate_type", "message": "candidateType is required."})
    elif candidate_type not in CANDIDATE_TYPES:
        issues.append({"severity": "error", "code": "invalid_candidate_type", "message": "candidateType is not supported."})
    if not _has_value(candidate.get("candidateId")):
        issues.append({"severity": "error", "code": "missing_candidate_id", "message": "candidateId is required."})
    if not _has_value(candidate.get("teamId")):
        issues.append({"severity": "error", "code": "missing_team_id", "message": "teamId is required."})
    if candidate_type == "source_manifest":
        issues.extend(_validate_source_manifest(candidate))
    elif candidate_type == "paper_note":
        issues.extend(_validate_paper_note_candidate(candidate))
    elif candidate_type == "neuro_mechanism":
        issues.extend(_validate_neuro_mechanism_candidate(candidate))
    elif candidate_type == "mechanism_mapping":
        issues.extend(_validate_mechanism_mapping_candidate(candidate))
    elif candidate_type == "algorithm_hypothesis":
        issues.extend(_validate_algorithm_hypothesis_candidate(candidate))
    elif candidate_type == "review_record":
        issues.extend(_validate_review_record_candidate(candidate))
    elif candidate_type == "candidate_graph":
        issues.extend(_validate_candidate_graph_candidate(candidate))
    elif candidate_type in {"paper_note", "neuro_mechanism", "mechanism_mapping", "algorithm_hypothesis", "review_record"}:
        if not _normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
            issues.append({"severity": "error", "code": "missing_source_refs", "message": f"{candidate_type} must keep sourceRefs."})
        if not _normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
            issues.append({"severity": "warning", "code": "missing_evidence_refs", "message": f"{candidate_type} should include evidenceRefs before review."})
    return {
        "schemaVersion": SCHEMA_VERSION,
        "candidateType": candidate_type,
        "valid": not any(item["severity"] == "error" for item in issues),
        "issues": issues,
    }


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


def _validate_source_manifest(candidate: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    source_kind = _trim_text(candidate.get("sourceKind"), max_length=80)
    source_url = _trim_text(candidate.get("sourceUrl"), max_length=2000)
    source_path = _trim_text(candidate.get("sourcePath"), max_length=2000)
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    metadata_path = _trim_text(metadata.get("path") or metadata.get("sourcePath"), max_length=2000)
    metadata_sha = _trim_text(metadata.get("sha256") or metadata.get("hash"), max_length=128)
    sha256 = _trim_text(candidate.get("sha256"), max_length=128) or metadata_sha
    allowed = candidate.get("allowedForAnalysis")
    if allowed is None and "allowedForAnalysis" in metadata:
        allowed = _normalize_optional_bool(metadata.get("allowedForAnalysis"))
    page_scope = _trim_text(candidate.get("pageScope") or metadata.get("pageScope"), max_length=160)
    if not source_kind or source_kind == "unknown":
        issues.append({"severity": "warning", "code": "unknown_source_kind", "message": "sourceKind should identify pdf, paper, note, or competition_doc."})
    if not (source_url or source_path or metadata_path):
        issues.append({"severity": "error", "code": "missing_source_location", "message": "source_manifest requires sourceUrl, sourcePath, or metadata.path."})
    is_pdf = source_kind == "pdf" or source_path.lower().endswith(".pdf") or metadata_path.lower().endswith(".pdf")
    if is_pdf:
        if not (source_path or metadata_path):
            issues.append({"severity": "error", "code": "missing_pdf_path", "message": "PDF source_manifest requires sourcePath or metadata.path."})
        if not sha256:
            issues.append({"severity": "error", "code": "missing_sha256", "message": "PDF source_manifest requires sha256 before screening."})
        if allowed is not True:
            issues.append({"severity": "error", "code": "analysis_not_allowed", "message": "PDF source_manifest requires allowedForAnalysis=true."})
        if not page_scope:
            issues.append({"severity": "warning", "code": "missing_page_scope", "message": "PDF source_manifest should include pageScope for later citation anchors."})
        extraction = metadata.get("sourceExtraction") if isinstance(metadata.get("sourceExtraction"), dict) else {}
        if extraction:
            extraction_status = _trim_text(extraction.get("status"), max_length=80)
            if extraction_status == "failed":
                issues.append({"severity": "error", "code": "source_extraction_failed", "message": "PDF source_manifest extraction failed and needs confirmation before screening."})
            elif extraction_status == "extracted" and not isinstance(extraction.get("pageAnchors"), list):
                issues.append({"severity": "error", "code": "missing_page_anchors", "message": "PDF source_manifest extraction must include pageAnchors."})
    return issues


def _validate_neuro_mechanism_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not _normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "neuro_mechanism must keep sourceRefs."})
    if not _normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "neuro_mechanism requires evidenceRefs before mapping."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        issues.extend(_validate_neuro_mechanism_output(output))
    return issues


def _validate_mechanism_mapping_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not _normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "mechanism_mapping must keep sourceRefs."})
    if not _normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "mechanism_mapping requires evidenceRefs before hypothesis generation."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        issues.extend(_validate_mechanism_mapping_output(output))
    return issues


def _validate_algorithm_hypothesis_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not _normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "algorithm_hypothesis must keep sourceRefs."})
    if not _normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "algorithm_hypothesis requires evidenceRefs before review."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        issues.extend(_validate_algorithm_hypothesis_output(output))
    return issues


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


def _default_workflow(team_id: str, *, workflow_kind: str, owner_agent_id: str) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "workflowId": DEFAULT_WORKFLOW_ID,
        "teamId": team_id,
        "workflowKind": workflow_kind,
        "status": "active",
        "ownerAgentId": owner_agent_id,
        "stateMachine": {
            "currentStage": "knowledge_collection",
            "nodes": [
                {"nodeId": "knowledge_collection", "label": "知识搜集"},
            {"nodeId": "source_screening", "label": "资料审查"},
            {"nodeId": "candidate_ingestion", "label": "资料入库"},
            {"nodeId": "team_memory_ready", "label": "团队知识库已接入"},
            ],
            "transitions": [
                {"from": "knowledge_collection", "to": "source_screening"},
                {"from": "source_screening", "to": "candidate_ingestion"},
                {"from": "candidate_ingestion", "to": "team_memory_ready"},
                {"from": "source_screening", "to": "knowledge_collection", "type": "rework"},
                {"from": "candidate_ingestion", "to": "source_screening", "type": "rework"},
            ],
        },
        "routingPolicy": {
            "coordinationAgentId": owner_agent_id,
            "functionalAgentsMayRequestTransfer": True,
            "finalStateWriter": owner_agent_id,
        },
        "transferPolicy": {
            "requiresUserConfirmation": False,
            "requestedBy": "functional_agent",
            "decidedBy": owner_agent_id,
            "recordDecidedByAgent": True,
        },
        "activeWorkflowItems": [],
        "createdAt": now,
        "updatedAt": now,
    }


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


def _load_or_create_workflow(team_id: str, *, persist_repair: bool = True) -> dict[str, Any]:
    path = _workflow_path(team_id)
    if path.exists():
        raw_workflow = _read_json(path)
        workflow = _repair_workflow(raw_workflow, team_id)
        if persist_repair and workflow != raw_workflow:
            _write_json(path, workflow)
        return workflow
    workflow = _default_workflow(
        team_id,
        workflow_kind=WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH,
        owner_agent_id=DEFAULT_OWNER_AGENT_ID,
    )
    _write_json(path, workflow)
    _record_workflow_event(
        "workflow.created",
        team_id,
        fields={"workflowId": workflow["workflowId"], "workflowKind": workflow["workflowKind"]},
    )
    return workflow


def _load_candidate_store(team_id: str) -> dict[str, Any]:
    path = _candidate_store_path(team_id)
    if path.exists():
        payload = _read_json(path)
        if isinstance(payload.get("candidates"), list):
            return payload
    now = utc_now_iso()
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "storeKind": "team_workflow_candidate_store",
        "candidates": [],
        "createdAt": now,
        "updatedAt": now,
    }
    _write_json(path, payload)
    return payload


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


def _find_source_candidate_by_identity_key(candidate_store: dict[str, Any], source_identity_key: str) -> dict[str, Any] | None:
    if not source_identity_key:
        return None
    for candidate in list(candidate_store.get("candidates") or []):
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("candidateType") or "") != "source_manifest" or _candidate_is_archived(candidate):
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        if source_identity_key in {
            _trim_text(metadata.get("sourceIdentityKey"), max_length=160),
            _trim_text(imported_from.get("sourceIdentityKey"), max_length=160),
        }:
            return candidate
    return None


def _source_candidate_payload_from_data_record(run: dict[str, Any], record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    source_type = _trim_text(record.get("sourceType"), max_length=80) or "unknown"
    source_ref = _trim_text(record.get("sourceRef"), max_length=2000)
    raw_location = _trim_text(record.get("rawLocation"), max_length=2000)
    source_kind = _trim_text(payload.get("sourceKind"), max_length=80) or _source_kind_from_data_record(source_type, source_ref, raw_location)
    source_url = _trim_text(payload.get("sourceUrl"), max_length=2000)
    source_path = _trim_text(payload.get("sourcePath"), max_length=2000)
    if not source_url and _looks_like_url(source_ref):
        source_url = source_ref
    if not source_path and not source_url:
        source_path = raw_location or (source_ref if source_type in {"file", "paper", "dataset"} else "")
    title = _trim_text(payload.get("title"), max_length=240) or _trim_text(record.get("title"), max_length=240) or source_ref or raw_location
    if not title and not source_url and not source_path:
        raise TeamWorkflowOrchestrationError("Data processing record cannot be imported without title, sourceRef, or rawLocation.")
    metadata = _normalize_metadata(payload.get("metadata"))
    record_metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    quality_signals = record.get("qualitySignals") if isinstance(record.get("qualitySignals"), dict) else {}
    collection_trace = record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {}
    source_trace = record_metadata.get("sourceCollectionTrace") if isinstance(record_metadata.get("sourceCollectionTrace"), dict) else collection_trace
    source_category = _source_collection_source_category(
        source_kind=source_kind,
        source_ref=source_ref,
        raw_location=raw_location,
        source_url=source_url,
        source_path=source_path,
    )
    doi = _source_collection_extract_doi(source_ref, source_url, raw_location, record_metadata.get("doi"))
    imported_from = _data_record_ref(run, record)
    metadata.update(
        {
            "importedFromDataRecord": imported_from,
            "dataProcessingQualitySignals": _normalize_metadata(quality_signals),
            "dataProcessingCollectionTrace": _normalize_metadata(collection_trace),
            "dataProcessingRecordMetadata": _normalize_metadata(record_metadata),
            "sourceCollectionTrace": _normalize_metadata(source_trace),
            "sourceRunId": imported_from["runId"],
            "sourceRecordId": imported_from["recordId"],
            "sourceCategory": source_category,
            "sourceRef": source_ref or raw_location,
            "sourceUrl": source_url,
            "sourcePath": source_path,
            "assignmentId": _trim_text(source_trace.get("assignmentId"), max_length=128),
            "agentRole": _trim_text(source_trace.get("agentRole"), max_length=80),
            "queryId": _trim_text(source_trace.get("queryId"), max_length=160),
            "query": _trim_text(source_trace.get("query"), max_length=1000),
            "searchProvider": _trim_text(source_trace.get("searchProvider") or record_metadata.get("searchProvider"), max_length=80),
            "searchUrl": _trim_text(source_trace.get("searchUrl") or record_metadata.get("searchUrl"), max_length=1000),
        }
    )
    if doi:
        metadata["doi"] = doi
        metadata["importedFromDataRecord"]["doi"] = doi
    source_identity_key = _source_collection_record_identity_key(record)
    if source_identity_key:
        metadata["sourceIdentityKey"] = source_identity_key
        metadata["importedFromDataRecord"]["sourceIdentityKey"] = source_identity_key
    return {
        "candidateType": "source_manifest",
        "title": title,
        "sourceUrl": source_url,
        "sourcePath": source_path,
        "sourceKind": source_kind,
        "sha256": _trim_text(payload.get("sha256") or record_metadata.get("sha256"), max_length=128),
        "allowedForAnalysis": _normalize_optional_bool(payload.get("allowedForAnalysis")) if "allowedForAnalysis" in payload else _normalize_optional_bool(record_metadata.get("allowedForAnalysis")),
        "pageScope": _trim_text(payload.get("pageScope") or record_metadata.get("pageScope"), max_length=160),
        "summary": _trim_text(payload.get("summary"), max_length=4000) or _trim_text(record.get("summary"), max_length=4000),
        "tags": _normalize_text_list(payload.get("tags"), max_items=24, max_length=80),
        "evidenceRefs": _data_record_evidence_refs(run, record, payload),
        "metadata": metadata,
        "createdByAgent": _trim_text(payload.get("createdByAgent"), max_length=160) or "data_intake_coordinator",
    }


def _data_record_ref(run: dict[str, Any], record: dict[str, Any]) -> dict[str, str]:
    return {
        "runId": _trim_text(run.get("runId"), max_length=128),
        "recordId": _trim_text(record.get("recordId"), max_length=128),
        "profileId": _trim_text(run.get("profileId"), max_length=128),
        "sourceType": _trim_text(record.get("sourceType"), max_length=80),
        "sourceRef": _trim_text(record.get("sourceRef") or record.get("rawLocation"), max_length=240),
        "title": _trim_text(record.get("title"), max_length=240),
    }


def _data_record_evidence_refs(run: dict[str, Any], record: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, str]]:
    refs = _normalize_ref_list(payload.get("evidenceRefs"), max_items=20)
    refs.append(
        {
            "type": "data_record",
            "id": _trim_text(record.get("recordId"), max_length=240),
            "label": _trim_text(record.get("title"), max_length=240) or _trim_text(record.get("sourceRef"), max_length=240) or "DataRecord",
        }
    )
    run_id = _trim_text(run.get("runId"), max_length=240)
    if run_id:
        refs.append({"type": "data_processing_run", "id": run_id, "label": _trim_text(run.get("title"), max_length=240) or run_id})
    return refs[:24]


def _source_kind_from_data_record(source_type: str, source_ref: str, raw_location: str) -> str:
    if source_type in {"paper", "dataset", "file", "url", "api", "note", "manual"}:
        return source_type
    if _looks_like_url(source_ref):
        return "url"
    if raw_location or source_ref:
        return "file"
    return "unknown"


def _source_collection_extract_doi(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
        match = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", text, flags=re.IGNORECASE)
        if match:
            return match.group(0).rstrip(").,;")
    return ""


def _source_collection_source_category(
    *,
    source_kind: str,
    source_ref: str,
    raw_location: str,
    source_url: str,
    source_path: str,
) -> str:
    normalized = str(source_kind or "").strip().lower()
    refs = " ".join([source_ref, raw_location, source_url, source_path]).lower()
    if "dataset" in normalized:
        return "dataset"
    if ".pdf" in refs or "application/pdf" in refs:
        return "pdf"
    if source_path and not _looks_like_url(source_path):
        return "local_file"
    if normalized in {"file", "manual", "note"}:
        return "local_file"
    if _source_collection_extract_doi(source_ref, source_url, raw_location) or _looks_like_url(source_ref) or _looks_like_url(source_url):
        return "paper_web"
    return "missing"


def _looks_like_url(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _source_collection_workflow_kind(payload: dict[str, Any], team: dict[str, Any]) -> str:
    raw = _safe_token(
        payload.get("workflowKind") or payload.get("workflowPurpose") or team.get("teamKind") or "",
        default=WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH,
        max_length=80,
    )
    if raw == "knowledge_expansion":
        return WORKFLOW_KIND_KNOWLEDGE_EXPANSION
    return WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH


def _source_collection_collection_mode(value: Any) -> str:
    normalized = _safe_token(value, default="web_search", max_length=80)
    return normalized if normalized in SOURCE_COLLECTION_COLLECTION_MODES else "web_search"


def _source_collection_local_scan_summary(
    *,
    status: str,
    imported: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    imported_items = list(imported or [])
    skipped_items = list(skipped or [])
    failed_items = list(failed or [])
    return {
        "status": status,
        "importedCount": len(imported_items),
        "skippedCount": len(skipped_items),
        "failedCount": len(failed_items),
        "imported": imported_items[:40],
        "skipped": skipped_items[:40],
        "failed": failed_items[:40],
    }


def _import_source_collection_local_workspace_sources(
    team_id: str,
    run_id: str,
    payload: dict[str, Any],
    *,
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    scan_scope = payload.get("localScanScope") if isinstance(payload.get("localScanScope"), dict) else {}
    roots = _normalize_text_list(
        scan_scope.get("roots") or scan_scope.get("rootRefs") or SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_ROOTS,
        max_items=8,
        max_length=240,
    ) or list(SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_ROOTS)
    max_files = _normalize_int(
        scan_scope.get("maxFiles"),
        default=SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_MAX_FILES,
        minimum=1,
        maximum=SOURCE_COLLECTION_LOCAL_SCAN_HARD_MAX_FILES,
    )
    base_root = Path(PROJECT_ROOT).resolve()
    candidates: list[Path] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for root_ref in roots:
        root_path = (base_root / root_ref).resolve()
        try:
            root_path.relative_to(base_root)
        except ValueError:
            skipped.append({"root": root_ref, "reason": "outside_project_root"})
            continue
        if not root_path.exists():
            skipped.append({"root": root_ref, "reason": "missing_root"})
            continue
        if root_path.is_file():
            iterable = [root_path]
        else:
            iterable = sorted(path for path in root_path.rglob("*") if path.is_file())
        for file_path in iterable:
            if len(candidates) >= max_files:
                break
            relative_parts = {part.lower() for part in file_path.relative_to(base_root).parts}
            if relative_parts & SOURCE_COLLECTION_LOCAL_SCAN_EXCLUDED_PARTS:
                skipped.append({"path": _relative_path(file_path), "reason": "excluded_path"})
                continue
            if file_path.suffix.lower() not in SOURCE_COLLECTION_LOCAL_SCAN_EXTENSIONS:
                skipped.append({"path": _relative_path(file_path), "reason": "unsupported_extension"})
                continue
            candidates.append(file_path)
        if len(candidates) >= max_files:
            break

    source_assignment = next(
        (
            item for item in assignments
            if isinstance(item, dict)
            and _trim_text(item.get("agentRole"), max_length=80) in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
        ),
        {},
    )
    record_payloads: list[dict[str, Any]] = []
    for file_path in candidates:
        try:
            file_bytes = file_path.read_bytes()
        except OSError as exc:
            failed.append({"path": _relative_path(file_path), "reason": "read_failed", "error": str(exc)})
            continue
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        truncated = len(file_bytes) > SOURCE_COLLECTION_LOCAL_SCAN_MAX_BYTES
        sample_bytes = file_bytes[:SOURCE_COLLECTION_LOCAL_SCAN_MAX_BYTES]
        summary = _source_collection_local_file_summary(file_path, sample_bytes)
        relative_path = _relative_path(file_path)
        record_payloads.append(
            {
                "sourceType": "note" if file_path.suffix.lower() in {".md", ".txt"} else "file",
                "sourceRef": relative_path,
                "rawLocation": str(file_path),
                "title": _source_collection_local_file_title(file_path, sample_bytes),
                "summary": summary,
                "metadata": {
                    "sourceCollectionRunId": run_id,
                    "sha256": sha256,
                    "localWorkspaceImport": {
                        "relativePath": relative_path,
                        "extension": file_path.suffix.lower(),
                        "sizeBytes": len(file_bytes),
                        "truncated": truncated,
                    },
                    "allowedForAnalysis": True,
                },
                "qualitySignals": {
                    "localWorkspaceImport": True,
                    "sizeBytes": len(file_bytes),
                    "truncated": truncated,
                },
                "collectionTrace": {
                    "sourceCollectionRunId": run_id,
                    "assignmentId": _trim_text(source_assignment.get("assignmentId"), max_length=160),
                    "agentRole": _trim_text(source_assignment.get("agentRole"), max_length=80) or "source_intake",
                    "agentId": _trim_text(source_assignment.get("agentId"), max_length=160),
                    "collectionMode": "local_workspace",
                },
            }
        )

    imported: list[dict[str, Any]] = []
    created_records: list[dict[str, Any]] = []
    assignment_id = _trim_text(source_assignment.get("assignmentId"), max_length=160)
    try:
        if assignment_id:
            output = data_processing_service.record_collection_output(
                run_id,
                assignment_id,
                {
                    "status": "completed",
                    "records": record_payloads,
                    "notes": f"Imported {len(record_payloads)} local workspace source files.",
                    "qualitySignals": {"localWorkspaceImport": True, "recordCount": len(record_payloads)},
                },
            )
            created_records = [item for item in list(output.get("createdRecords") or []) if isinstance(item, dict)]
        else:
            created_records = [data_processing_service.add_record(run_id, item) for item in record_payloads]
    except data_processing_service.DataProcessingError as exc:
        failed.append({"reason": "record_create_failed", "error": str(exc)})
        created_records = []

    for record in created_records:
        try:
            import_response = import_data_record_as_source_candidate(
                team_id,
                run_id,
                _trim_text(record.get("recordId"), max_length=160),
                {
                    "sourcePath": _trim_text((record.get("metadata") or {}).get("localWorkspaceImport", {}).get("relativePath") if isinstance(record.get("metadata"), dict) else "", max_length=2000),
                    "createdByAgent": _trim_text(source_assignment.get("agentId"), max_length=160) or "source_finder",
                    "tags": ["source_collection", "local_workspace", "knowledge_expansion"],
                    "metadata": {
                        "sourceCollectionRunId": run_id,
                        "sourceCollectionLocalWorkspaceImport": True,
                        "localWorkspaceImport": (
                            record.get("metadata", {}).get("localWorkspaceImport")
                            if isinstance(record.get("metadata"), dict)
                            else {}
                        ),
                    },
                },
            )
        except TeamWorkflowOrchestrationError as exc:
            failed.append({"recordId": _trim_text(record.get("recordId"), max_length=160), "reason": "candidate_import_failed", "error": str(exc)})
            continue
        candidate = import_response.get("candidate") if isinstance(import_response.get("candidate"), dict) else {}
        imported.append(
            {
                "recordId": _trim_text(record.get("recordId"), max_length=160),
                "candidateId": _trim_text(candidate.get("candidateId"), max_length=160),
                "created": bool(import_response.get("created")),
                "path": _trim_text((record.get("metadata") or {}).get("localWorkspaceImport", {}).get("relativePath") if isinstance(record.get("metadata"), dict) else "", max_length=500),
            }
        )

    status = "completed" if imported and not failed else ("partial" if imported else ("failed" if failed else "empty"))
    summary = _source_collection_local_scan_summary(status=status, imported=imported, skipped=skipped, failed=failed)
    _record_workflow_event(
        "source_collection.local_workspace_imported",
        team_id,
        fields={
            "runId": run_id,
            "status": status,
            "importedCount": summary["importedCount"],
            "skippedCount": summary["skippedCount"],
            "failedCount": summary["failedCount"],
        },
        level="warning" if failed else "info",
        outcome="failed" if failed and not imported else "completed",
    )
    return summary


def _source_collection_local_file_title(file_path: Path, sample_bytes: bytes) -> str:
    text = _decode_local_workspace_sample(sample_bytes)
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return _trim_text(stripped, max_length=240)
    return _trim_text(file_path.stem.replace("_", " "), max_length=240) or file_path.name


def _source_collection_local_file_summary(file_path: Path, sample_bytes: bytes) -> str:
    if file_path.suffix.lower() == ".pdf":
        return "Local PDF source; metadata imported for downstream extraction."
    text = _decode_local_workspace_sample(sample_bytes)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return _trim_text(" ".join(lines[:12]), max_length=1200)


def _decode_local_workspace_sample(sample_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return sample_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return sample_bytes.decode("utf-8", errors="ignore")


def _normalize_source_collection_roles(value: Any) -> list[str]:
    raw_roles = value if isinstance(value, list) else list(SOURCE_COLLECTION_DEFAULT_AGENT_ROLES)
    roles: list[str] = []
    for item in raw_roles[:8]:
        role = _normalize_source_collection_agent_role(item)
        if role in SOURCE_COLLECTION_AGENT_ROLES and role not in roles:
            roles.append(role)
    return roles or list(SOURCE_COLLECTION_DEFAULT_AGENT_ROLES)


def _source_collection_owner_agent_id(team: dict[str, Any], payload: dict[str, Any]) -> str:
    explicit = _trim_text(payload.get("ownerAgentId"), max_length=160)
    if explicit:
        return explicit
    canvas = team.get("canvas") if isinstance(team.get("canvas"), dict) else {}
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    preferred_roles = ("research_coordination", "data_intake_coordinator", "ceo", "organization_coordinator")
    for preferred_role in preferred_roles:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            role = _trim_text(node.get("role"), max_length=80)
            agent_id = _trim_text(node.get("agentId"), max_length=160)
            if role == preferred_role and agent_id:
                return agent_id
    return DEFAULT_OWNER_AGENT_ID


def _source_collection_agent_id(role: str, payload: dict[str, Any]) -> str:
    agent_ids = payload.get("agentIds") if isinstance(payload.get("agentIds"), dict) else {}
    explicit = _trim_text(agent_ids.get(role), max_length=160)
    return explicit or role


def _source_collection_agent_role_for_id(assignments: list[dict[str, Any]], agent_id: str, stage_id: str) -> str:
    normalized_agent_id = _trim_text(agent_id, max_length=160)
    allowed_roles = SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES.get(stage_id, ())
    for assignment in assignments:
        if _trim_text(assignment.get("agentId"), max_length=160) != normalized_agent_id:
            continue
        role = _trim_text(assignment.get("agentRole"), max_length=80)
        if role in allowed_roles:
            return role
    for assignment in assignments:
        role = _trim_text(assignment.get("agentRole"), max_length=80)
        if role in allowed_roles:
            return role
    return allowed_roles[0] if allowed_roles else ""


def _source_collection_prompt_cache_policy(team_id: str, payload: dict[str, Any], roles: list[str]) -> dict[str, Any]:
    raw_policy = payload.get("promptCachePolicy") if isinstance(payload.get("promptCachePolicy"), dict) else {}
    requirement = _normalize_source_collection_prompt_cache_requirement(raw_policy, payload)
    requested_model_id = (
        _trim_text(raw_policy.get("modelId"), max_length=160)
        or _trim_text(payload.get("modelId"), max_length=160)
    )
    model_id, model_entry, model_resolution = _source_collection_resolve_prompt_cache_model(requested_model_id)
    prompt_cache_mode = _source_collection_prompt_cache_mode(model_entry)
    model_name = _trim_text(model_entry.get("model") or model_entry.get("label"), max_length=240) or model_id
    provider_id = _trim_text(model_entry.get("provider_id") or model_entry.get("provider"), max_length=160)
    hard_block = requirement in SOURCE_COLLECTION_PROMPT_CACHE_REQUIRED_MODES
    gate_status = "disabled" if requirement in SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES else "satisfied"
    gate_reason = ""
    if requirement not in SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES and not model_entry:
        gate_status = "blocked" if hard_block else "warning"
        requested_for_message = _trim_text(model_resolution.get("requestedModelId"), max_length=160)
        gate_reason = (
            f"Prompt cache model is not configured: {requested_for_message}"
            if requested_for_message
            else "No prompt-cache-capable model is configured for knowledge collection."
        )
    elif hard_block and prompt_cache_mode not in SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES:
        gate_status = "blocked"
        gate_reason = (
            "Knowledge collection requires prompt cache/KV reuse, but "
            f"model `{model_id}` has prompt_cache.mode `{prompt_cache_mode}`."
        )
    elif requirement not in SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES and prompt_cache_mode not in SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES:
        gate_status = "warning"
        gate_reason = f"Prompt cache is not guaranteed for model `{model_id}`."
    role_partitions = [
        {
            "agentRole": role,
            "agentId": _source_collection_agent_id(role, payload),
            "promptCachePartition": _source_collection_prompt_cache_partition(team_id, role, model_id=model_id),
        }
        for role in roles
    ]
    policy = {
        "schemaVersion": SCHEMA_VERSION,
        "policyId": _new_record_id("cachepolicy"),
        "policyKind": "source_collection_prompt_cache_policy",
        "scope": SOURCE_COLLECTION_PROMPT_CACHE_SCOPE,
        "requirement": requirement,
        "modelId": model_id,
        "modelName": model_name,
        "providerId": provider_id,
        "promptCacheMode": prompt_cache_mode,
        "modelResolution": model_resolution,
        "supportedPromptCacheModes": sorted(SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES),
        "partitionTemplate": "research-team:{teamId}:knowledge_collection:{agentRole}:{modelId}",
        "rolePartitions": role_partitions,
        "stablePrefixContract": _source_collection_stable_prefix_contract(),
        "dynamicDeltaContract": _source_collection_dynamic_delta_contract(),
        "gate": {
            "status": gate_status,
            "passed": gate_status in {"satisfied", "disabled", "warning"},
            "hardBlock": hard_block,
            "reason": gate_reason,
            "checkedAt": utc_now_iso(),
        },
    }
    if gate_status == "blocked":
        _record_workflow_event(
            "source_collection.prompt_cache_blocked",
            team_id,
            fields={
                "policyId": policy["policyId"],
                "requirement": requirement,
                "modelId": model_id,
                "requestedModelId": model_resolution.get("requestedModelId", ""),
                "modelResolutionStatus": model_resolution.get("status", ""),
                "promptCacheMode": prompt_cache_mode,
                "outcome": "blocked",
                "reason": gate_reason,
            },
        )
        raise TeamWorkflowOrchestrationError(
            f"{gate_reason} Knowledge collection requires prompt cache/KV reuse. "
            "Set prompt_cache.mode to automatic or explicit_cache_control before starting knowledge collection."
        )
    return policy


def _normalize_source_collection_prompt_cache_requirement(raw_policy: dict[str, Any], payload: dict[str, Any]) -> str:
    raw = (
        _trim_text(raw_policy.get("requirement"), max_length=80)
        or _trim_text(raw_policy.get("mode"), max_length=80)
        or _trim_text(payload.get("promptCacheRequirement"), max_length=80)
        or "required_for_llm_execution"
    ).lower()
    if raw in SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES:
        return "disabled"
    if raw in {"advisory", "optional", "warn", "warning"}:
        return "advisory"
    return "required_for_llm_execution"


def _source_collection_model_library() -> dict[str, Any]:
    try:
        public_config = load_public_config()
    except Exception:
        public_config = {}
    llm = public_config.get("llm") if isinstance(public_config, dict) else {}
    model_library = llm.get("model_library") if isinstance(llm, dict) else {}
    return dict(model_library) if isinstance(model_library, dict) else {}


def _source_collection_prompt_cache_mode(model_entry: dict[str, Any]) -> str:
    prompt_cache = model_entry.get("prompt_cache") if isinstance(model_entry.get("prompt_cache"), dict) else {}
    return _trim_text(prompt_cache.get("mode"), max_length=80).lower() or "disabled"


def _source_collection_is_text_model(model_id: str, model_entry: dict[str, Any]) -> bool:
    descriptor = " ".join(
        [
            str(model_id or ""),
            str(model_entry.get("model") or ""),
            str(model_entry.get("label") or ""),
            str(model_entry.get("transport") or ""),
        ]
    ).lower()
    if "image2" in descriptor or "image" in descriptor:
        return False
    return True


def _source_collection_prompt_cache_model_score(model_id: str, model_entry: dict[str, Any]) -> tuple[int, str]:
    descriptor = " ".join(
        [
            str(model_id or ""),
            str(model_entry.get("model") or ""),
            str(model_entry.get("label") or ""),
            str((model_entry.get("provider") or {}).get("kind") if isinstance(model_entry.get("provider"), dict) else model_entry.get("provider") or ""),
        ]
    ).lower()
    score = 0
    if _source_collection_is_text_model(model_id, model_entry):
        score += 100
    if "qwen" in descriptor or "local" in descriptor:
        score += 30
    if "relay" in descriptor or "openai" in descriptor or "gpt" in descriptor:
        score += 20
    return (-score, str(model_id or ""))


def _source_collection_resolve_prompt_cache_model(requested_model_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    model_library = _source_collection_model_library()
    requested_entry = model_library.get(requested_model_id) if requested_model_id else {}
    if isinstance(requested_entry, dict) and _source_collection_prompt_cache_mode(requested_entry) in SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES:
        return requested_model_id, dict(requested_entry), {
            "status": "requested",
            "requestedModelId": requested_model_id,
            "reason": "",
        }

    candidates: list[tuple[tuple[int, str], str, dict[str, Any]]] = []
    for candidate_id, candidate_entry in model_library.items():
        if not isinstance(candidate_entry, dict):
            continue
        if _source_collection_prompt_cache_mode(candidate_entry) not in SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES:
            continue
        if not _source_collection_is_text_model(str(candidate_id), candidate_entry):
            continue
        candidates.append((_source_collection_prompt_cache_model_score(str(candidate_id), candidate_entry), str(candidate_id), dict(candidate_entry)))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        resolved_id = candidates[0][1]
        resolved_entry = candidates[0][2]
        return resolved_id, resolved_entry, {
            "status": "fallback" if requested_model_id and resolved_id != requested_model_id else "auto",
            "requestedModelId": requested_model_id,
            "reason": "requested_model_unavailable" if requested_model_id and not requested_entry else "requested_model_prompt_cache_unsupported" if requested_model_id else "auto_selected",
        }

    if isinstance(requested_entry, dict) and requested_entry:
        return requested_model_id, dict(requested_entry), {
            "status": "unavailable",
            "requestedModelId": requested_model_id,
            "reason": "requested_model_prompt_cache_unsupported",
        }
    return requested_model_id, {}, {
        "status": "unavailable",
        "requestedModelId": requested_model_id,
        "reason": "requested_model_not_configured" if requested_model_id else "no_prompt_cache_model_configured",
    }


def _source_collection_prompt_cache_policy_ref(policy: dict[str, Any]) -> dict[str, Any]:
    gate = policy.get("gate") if isinstance(policy.get("gate"), dict) else {}
    return {
        "policyId": _trim_text(policy.get("policyId"), max_length=160),
        "scope": _trim_text(policy.get("scope"), max_length=120),
        "requirement": _trim_text(policy.get("requirement"), max_length=80),
        "modelId": _trim_text(policy.get("modelId"), max_length=160),
        "promptCacheMode": _trim_text(policy.get("promptCacheMode"), max_length=80),
        "gateStatus": _trim_text(gate.get("status"), max_length=80),
    }


def _source_collection_stable_prefix_contract() -> dict[str, Any]:
    return {
        "cacheableBlocks": [
            "ai科学研究团队身份与知识搜集阶段规则",
            "source collection assignment/output/DataRecord/source_manifest schema",
            "禁止直接写正式 Team Knowledge/RAG/official graph 的边界",
            "功能 Agent 职责、回写合同和质量审查规则",
        ],
        "forbiddenDynamicFields": [
            "currentQuery",
            "currentUrl",
            "downloadedText",
            "rawPageContent",
            "latestToolResult",
            "fullConversationHistory",
        ],
        "expectedUsage": "Stable prefix is cacheable; each step sends only the current query/result refs as dynamic delta.",
    }


def _source_collection_dynamic_delta_contract() -> dict[str, Any]:
    return {
        "allowedFields": [
            "queryId",
            "query",
            "sourceRef",
            "rawLocation",
            "resultSummary",
            "recordId",
            "collectionTrace",
            "cacheObservation",
        ],
        "maxRawContentPolicy": "Do not replay full pages; store artifacts as DataRecord/source refs and pass excerpts or summaries only.",
        "conversationTraceRequired": True,
    }


def _source_collection_assignment_scope(role: str, base_scope: dict[str, Any], *, search_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    role_purposes = {
        "data_intake_coordinator": "Coordinate source collection and handoff to source_manifest import.",
        "source_finder": "Find, fetch, download, and register traceable source records for the run.",
        "source_extractor": "Extract useful source content and make source-quality decisions in one pass.",
        "source_relation_mapper": "Build candidate-only topic, source, and evidence relationships.",
        "source_ingestor": "Perform governed final ingestion into formal team knowledge.",
    }
    scope = {
        **base_scope,
        "agentRole": role,
        "rolePurpose": role_purposes.get(role, "Collect data records for downstream processing."),
    }
    if isinstance(search_plan, dict):
        assigned_queries = _source_collection_queries_for_role(search_plan, role)
        prompt_cache_policy = search_plan.get("promptCachePolicy") if isinstance(search_plan.get("promptCachePolicy"), dict) else {}
        scope["dataSearchPlanRef"] = _source_collection_search_plan_ref(search_plan)
        scope["assignedQueries"] = assigned_queries
        scope["queryCount"] = len(assigned_queries)
        scope["resultWritebackContract"] = search_plan.get("resultWritebackContract", {})
        scope["promptCachePolicyRef"] = _source_collection_prompt_cache_policy_ref(prompt_cache_policy)
        scope["promptCachePartition"] = _source_collection_prompt_cache_partition(
            str(base_scope.get("teamId") or search_plan.get("teamId") or ""),
            role,
            model_id=str(prompt_cache_policy.get("modelId") or ""),
        )
        scope["conversationTraceRequired"] = bool((prompt_cache_policy.get("dynamicDeltaContract") or {}).get("conversationTraceRequired", True))
    return scope


def _build_source_collection_search_plan(
    *,
    team_id: str,
    run_id: str,
    payload: dict[str, Any],
    scope: dict[str, Any],
    input_refs: list[str],
    roles: list[str],
    prompt_cache_policy: dict[str, Any],
    plan_id: str = "",
) -> dict[str, Any]:
    normalized_plan_id = _trim_text(plan_id, max_length=128) or _new_record_id("searchplan")
    topic = _trim_text(scope.get("topic") or payload.get("topic"), max_length=500)
    goal = _trim_text(scope.get("goal") or payload.get("goal"), max_length=1000)
    query_seeds = _source_collection_query_seeds(payload, scope, input_refs, topic=topic, goal=goal)
    languages = _source_collection_search_languages(payload.get("searchLanguages"))
    source_types = _source_collection_source_types(payload.get("sourceTypes"))
    max_results = _normalize_int(
        payload.get("maxResultsPerQuery"),
        default=SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY,
        minimum=1,
        maximum=100,
    )
    search_roles = [role for role in roles if role in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES]
    role_cycle = search_roles or ["source_finder"]
    queries: list[dict[str, Any]] = []
    for seed in query_seeds:
        for source_type in source_types:
            for language in languages:
                if len(queries) >= SOURCE_COLLECTION_MAX_QUERIES:
                    break
                assigned_role = role_cycle[len(queries) % len(role_cycle)]
                query_id = f"{normalized_plan_id}-q{len(queries) + 1:03d}"
                queries.append(
                    {
                        "queryId": query_id,
                        "query": _source_collection_query_text(seed, source_type=source_type, language=language),
                        "seed": seed,
                        "language": language,
                        "sourceType": source_type,
                        "assignedAgentRole": assigned_role,
                        "maxResults": max_results,
                        "status": "planned",
                        "execution": {
                            "mode": "contract_only",
                            "externalSearchTriggered": False,
                            "conversationTraceRequired": True,
                            "promptCacheRequired": prompt_cache_policy.get("requirement") in SOURCE_COLLECTION_PROMPT_CACHE_REQUIRED_MODES,
                            "promptCachePartition": _source_collection_prompt_cache_partition(
                                team_id,
                                assigned_role,
                                model_id=str(prompt_cache_policy.get("modelId") or ""),
                            ),
                        },
                        "writeback": {
                            "target": "CollectionOutput.records",
                            "recordStatus": "collected",
                            "candidateImportTarget": "source_manifest",
                        },
                    }
                )
            if len(queries) >= SOURCE_COLLECTION_MAX_QUERIES:
                break
        if len(queries) >= SOURCE_COLLECTION_MAX_QUERIES:
            break
    writeback_contract = _source_collection_writeback_contract(team_id, run_id)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "planId": normalized_plan_id,
        "planKind": "source_collection_data_search",
        "status": "planned",
        "teamId": team_id,
        "runId": run_id,
        "topic": topic,
        "goal": goal,
        "querySeeds": query_seeds,
        "queryCount": len(queries),
        "sourceTypes": source_types,
        "searchLanguages": languages,
        "maxResultsPerQuery": max_results,
        "queries": queries,
        "promptCachePolicy": prompt_cache_policy,
        "roleAssignmentInputs": _source_collection_role_assignment_inputs(queries, roles, payload),
        "resultWritebackContract": writeback_contract,
        "boundaries": {
            "externalSearchTriggered": False,
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesKnowledgeGraph": False,
            "requiresPromptCacheForAgentExecution": prompt_cache_policy.get("requirement") in SOURCE_COLLECTION_PROMPT_CACHE_REQUIRED_MODES,
        },
    }


def _source_collection_search_plan_ref(search_plan: dict[str, Any]) -> dict[str, Any]:
    prompt_cache_policy = search_plan.get("promptCachePolicy") if isinstance(search_plan.get("promptCachePolicy"), dict) else {}
    return {
        "planId": _trim_text(search_plan.get("planId"), max_length=128),
        "planKind": _trim_text(search_plan.get("planKind"), max_length=120) or "source_collection_data_search",
        "status": _trim_text(search_plan.get("status"), max_length=80) or "planned",
        "queryCount": _normalize_int(search_plan.get("queryCount"), default=0, minimum=0, maximum=SOURCE_COLLECTION_MAX_QUERIES),
        "externalSearchTriggered": False,
        "promptCachePolicyId": _trim_text(prompt_cache_policy.get("policyId"), max_length=160),
        "promptCacheRequirement": _trim_text(prompt_cache_policy.get("requirement"), max_length=80),
        "promptCacheGateStatus": _trim_text((prompt_cache_policy.get("gate") or {}).get("status") if isinstance(prompt_cache_policy.get("gate"), dict) else "", max_length=80),
    }


def _source_collection_writeback_contract(team_id: str, run_id: str) -> dict[str, Any]:
    run_ref = _trim_text(run_id, max_length=128) or "{runId}"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "target": "data_processing.collection_output.records",
        "recordContract": {
            "requiredAnyOf": ["sourceRef", "rawLocation", "title"],
            "recordFields": ["sourceType", "sourceRef", "rawLocation", "title", "summary", "metadata", "qualitySignals", "collectionTrace"],
            "collectionTraceFields": ["planId", "queryId", "assignmentId", "agentRole"],
        },
        "candidateImport": {
            "targetCandidateType": "source_manifest",
            "route": f"/api/teams/{team_id}/workflow-orchestration/data-processing/runs/{run_ref}/records/{{recordId}}/source-candidate",
            "idempotencyKey": "metadata.importedFromDataRecord.recordId",
        },
        "formalKnowledgeWrites": False,
        "ragWrites": False,
        "officialGraphWrites": False,
    }


def _source_collection_open_assignments(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item for item in assignments
        if str(item.get("status") or "").strip().lower() in {"open", "in_progress", "returned"}
    ]


def _source_collection_assignment_stage_summary(assignments: list[dict[str, Any]]) -> dict[str, int]:
    open_assignments = _source_collection_open_assignments(assignments)
    search_assignments = [
        item for item in assignments
        if _normalize_source_collection_agent_role(item.get("agentRole")) in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
    ]
    search_open_assignments = [
        item for item in open_assignments
        if _normalize_source_collection_agent_role(item.get("agentRole")) in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
    ]
    collection_assignments = [
        item for item in assignments
        if _normalize_source_collection_agent_role(item.get("agentRole")) in SOURCE_COLLECTION_COLLECTION_STAGE_AGENT_ROLES
    ]
    collection_open_assignments = [
        item for item in open_assignments
        if _normalize_source_collection_agent_role(item.get("agentRole")) in SOURCE_COLLECTION_COLLECTION_STAGE_AGENT_ROLES
    ]
    downstream_assignments = [
        item for item in assignments
        if _normalize_source_collection_agent_role(item.get("agentRole")) not in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
    ]
    downstream_open_assignments = [
        item for item in open_assignments
        if _normalize_source_collection_agent_role(item.get("agentRole")) not in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
    ]
    return {
        "assignmentCount": len(assignments),
        "openAssignmentCount": len(open_assignments),
        "searchAssignmentCount": len(search_assignments),
        "searchOpenAssignmentCount": len(search_open_assignments),
        "collectionAssignmentCount": len(collection_assignments),
        "collectionOpenAssignmentCount": len(collection_open_assignments),
        "downstreamAssignmentCount": len(downstream_assignments),
        "downstreamOpenAssignmentCount": len(downstream_open_assignments),
    }


def _source_collection_existing_query_ids(records: list[dict[str, Any]]) -> set[str]:
    query_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        traces = [
            record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {},
            metadata.get("sourceCollectionTrace") if isinstance(metadata.get("sourceCollectionTrace"), dict) else {},
        ]
        for trace in traces:
            query_id = _trim_text(trace.get("queryId"), max_length=160)
            if query_id:
                query_ids.add(query_id)
    return query_ids


def _source_collection_output_query_ids(outputs: list[dict[str, Any]]) -> set[str]:
    query_ids: set[str] = set()
    for output in outputs:
        if not isinstance(output, dict):
            continue
        quality_signals = output.get("qualitySignals") if isinstance(output.get("qualitySignals"), dict) else {}
        query_id = _trim_text(quality_signals.get("queryId"), max_length=160)
        if query_id:
            query_ids.add(query_id)
    return query_ids


def _source_collection_result_identity_key(result: dict[str, Any]) -> str:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    quality_signals = result.get("qualitySignals") if isinstance(result.get("qualitySignals"), dict) else {}
    return _source_collection_identity_key(
        source_ref=result.get("sourceRef"),
        raw_location=result.get("rawLocation"),
        doi=metadata.get("doi") or result.get("doi") or quality_signals.get("doi"),
        url=metadata.get("url") or result.get("url") or quality_signals.get("url"),
        title=result.get("title"),
        container=result.get("container") or metadata.get("containerTitle") or metadata.get("container") or quality_signals.get("containerTitle") or quality_signals.get("container"),
        published=result.get("published") or metadata.get("issued") or metadata.get("published") or quality_signals.get("issued") or quality_signals.get("published"),
    )


def _source_collection_identity_key(
    *,
    source_ref: Any,
    raw_location: Any,
    doi: Any = "",
    url: Any = "",
    title: Any,
    container: Any = "",
    published: Any = "",
) -> str:
    for value in (doi, source_ref, raw_location):
        doi = _source_collection_normalized_doi(value)
        if doi:
            return f"doi:{doi}"
    for value in (url, source_ref, raw_location):
        url_key = _source_collection_normalized_url(value)
        if url_key:
            return f"url:{url_key}"
    normalized_title = re.sub(r"\s+", " ", _trim_text(title, max_length=260).lower()).strip()
    if len(normalized_title) < 16:
        return ""
    normalized_container = re.sub(r"\s+", " ", _trim_text(container, max_length=160).lower()).strip()
    year_match = re.search(r"(19|20)\d{2}", _trim_text(published, max_length=80))
    if not normalized_container and not year_match:
        return ""
    fingerprint_source = "|".join([normalized_title, normalized_container, year_match.group(0) if year_match else ""])
    return f"title:{hashlib.sha256(fingerprint_source.encode('utf-8')).hexdigest()[:24]}"


def _source_collection_exclusion_scope(run: dict[str, Any]) -> dict[str, str]:
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    topic = _trim_text(
        scope.get("topic")
        or metadata.get("topic")
        or run.get("title")
        or scope.get("goal")
        or metadata.get("title"),
        max_length=500,
    )
    normalized = re.sub(r"\s+", " ", topic.lower()).strip()
    scope_key = f"topic:{hashlib.sha256(normalized.encode('utf-8', errors='replace')).hexdigest()[:24]}" if normalized else "team"
    return {
        "scope": "team_topic" if normalized else "team",
        "scopeKey": scope_key,
        "topic": topic,
    }


def _source_collection_exclusion_store_default(team_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "entries": [],
        "updatedAt": "",
    }


def _load_source_collection_exclusion_store(team_id: str) -> dict[str, Any]:
    store = _read_json(_source_collection_exclusion_store_path(team_id))
    if not store:
        return _source_collection_exclusion_store_default(team_id)
    entries = [item for item in list(store.get("entries") or []) if isinstance(item, dict)]
    store["schemaVersion"] = _source_collection_count(store.get("schemaVersion")) or SCHEMA_VERSION
    store["teamId"] = _trim_text(store.get("teamId"), max_length=160) or team_id
    store["entries"] = entries
    return store


def _write_source_collection_exclusion_store(team_id: str, store: dict[str, Any]) -> None:
    payload = dict(store)
    payload["schemaVersion"] = _source_collection_count(payload.get("schemaVersion")) or SCHEMA_VERSION
    payload["teamId"] = team_id
    payload["entries"] = [item for item in list(payload.get("entries") or []) if isinstance(item, dict)]
    payload["updatedAt"] = utc_now_iso()
    _write_json(_source_collection_exclusion_store_path(team_id), payload)


def get_source_collection_exclusion_ledger(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.assert_team_exists(normalized_team_id)
    with _WORKFLOW_LOCK:
        store = _load_source_collection_exclusion_store(normalized_team_id)
    entries = [dict(item) for item in list(store.get("entries") or []) if isinstance(item, dict)]
    entries.sort(key=lambda item: str(item.get("updatedAt") or item.get("lastSeenAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "excludedCount": len(entries),
        "entries": entries,
        "storagePath": _relative_path(_source_collection_exclusion_store_path(normalized_team_id)),
        "updatedAt": _trim_text(store.get("updatedAt"), max_length=120),
    }


def _source_collection_record_source_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    trace = record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {}
    return {
        "recordId": _trim_text(record.get("recordId"), max_length=160),
        "title": _trim_text(record.get("title"), max_length=260),
        "sourceType": _trim_text(record.get("sourceType"), max_length=80),
        "sourceRef": _trim_text(record.get("sourceRef"), max_length=500),
        "rawLocation": _trim_text(record.get("rawLocation"), max_length=1000),
        "doi": _source_collection_extract_doi(record.get("sourceRef"), record.get("rawLocation"), metadata.get("doi")),
        "containerTitle": _trim_text(metadata.get("containerTitle") or metadata.get("container"), max_length=240),
        "queryId": _trim_text(trace.get("queryId") or metadata.get("queryId"), max_length=160),
        "query": _trim_text(trace.get("query") or metadata.get("query"), max_length=500),
    }


def _source_collection_record_identity_or_record_key(record: dict[str, Any]) -> str:
    identity_key = _source_collection_record_identity_key(record)
    if identity_key:
        return identity_key
    record_id = _trim_text(record.get("recordId"), max_length=160)
    return f"record:{record_id}" if record_id else ""


def _source_collection_record_is_excluded(team_id: str, run: dict[str, Any], record: dict[str, Any]) -> dict[str, Any] | None:
    return _source_collection_exclusion_match(
        team_id,
        run,
        _source_collection_record_identity_or_record_key(record),
    )


def _record_source_collection_exclusion(
    team_id: str,
    run: dict[str, Any],
    record: dict[str, Any],
    *,
    reason: str,
    evidence: list[str] | None = None,
    task_id: str = "",
    agent_id: str = "",
    stage_id: str = "",
    source: str = "stage_writeback",
) -> dict[str, Any]:
    source_identity_key = _source_collection_record_identity_or_record_key(record)
    if not source_identity_key:
        return {}
    normalized_reason = _normalize_source_collection_exclusion_reason(reason) or "no_effective_content"
    now = utc_now_iso()
    scope = _source_collection_exclusion_scope(run)
    record_id = _trim_text(record.get("recordId"), max_length=160)
    run_id = _trim_text(run.get("runId"), max_length=160)
    evidence_items = _normalize_text_list(evidence or [], max_items=8, max_length=500)
    with _WORKFLOW_LOCK:
        store = _load_source_collection_exclusion_store(team_id)
        entries = [item for item in list(store.get("entries") or []) if isinstance(item, dict)]
        matched: dict[str, Any] | None = None
        for entry in entries:
            if (
                _trim_text(entry.get("sourceIdentityKey"), max_length=240) == source_identity_key
                and _trim_text(entry.get("scopeKey"), max_length=120) == scope["scopeKey"]
            ):
                matched = entry
                break
        if matched is None:
            matched = {
                "exclusionId": _new_record_id("srcexcl"),
                "sourceIdentityKey": source_identity_key,
                "scope": scope["scope"],
                "scopeKey": scope["scopeKey"],
                "topic": scope["topic"],
                "reason": normalized_reason,
                "evidence": evidence_items,
                "sourceSnapshot": _source_collection_record_source_snapshot(record),
                "firstSeenAt": now,
                "lastSeenAt": now,
                "updatedAt": now,
                "hitCount": 1,
                "createdByTaskId": _trim_text(task_id, max_length=160),
                "createdByAgent": _trim_text(agent_id, max_length=160),
                "stageId": _trim_text(stage_id, max_length=80),
                "source": _trim_text(source, max_length=80),
                "runIds": [run_id] if run_id else [],
                "recordIds": [record_id] if record_id else [],
                "restoreAllowed": True,
            }
            entries.append(matched)
        else:
            matched["reason"] = normalized_reason or _trim_text(matched.get("reason"), max_length=120)
            if evidence_items:
                previous_evidence = _normalize_text_list(matched.get("evidence"), max_items=8, max_length=500)
                matched["evidence"] = _normalize_text_list([*previous_evidence, *evidence_items], max_items=8, max_length=500)
            matched["sourceSnapshot"] = _source_collection_record_source_snapshot(record)
            matched["lastSeenAt"] = now
            matched["updatedAt"] = now
            matched["hitCount"] = max(1, _source_collection_count(matched.get("hitCount")))
            run_ids = _normalize_text_list(matched.get("runIds"), max_items=40, max_length=160)
            if run_id and run_id not in run_ids:
                run_ids.append(run_id)
            matched["runIds"] = run_ids[:40]
            record_ids = _normalize_text_list(matched.get("recordIds"), max_items=80, max_length=160)
            if record_id and record_id not in record_ids:
                record_ids.append(record_id)
            matched["recordIds"] = record_ids[:80]
        store["entries"] = entries
        _write_source_collection_exclusion_store(team_id, store)
        stored = dict(matched)
    _record_workflow_event(
        "source_collection.source_excluded",
        team_id,
        fields={
            "runId": run_id,
            "recordId": record_id,
            "taskId": _trim_text(task_id, max_length=160),
            "stageId": _trim_text(stage_id, max_length=80),
            "sourceIdentityKey": source_identity_key,
            "reason": normalized_reason,
            "scopeKey": scope["scopeKey"],
        },
        level="warning",
        outcome="completed",
    )
    return stored


def _source_collection_filter_active_records(
    team_id: str,
    run: dict[str, Any],
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    active_records: list[dict[str, Any]] = []
    excluded_refs: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        excluded = _source_collection_record_is_excluded(team_id, run, record)
        if excluded:
            excluded_refs.append(
                {
                    "recordId": _trim_text(record.get("recordId"), max_length=160),
                    "sourceIdentityKey": _trim_text(excluded.get("sourceIdentityKey"), max_length=240),
                    "reason": _trim_text(excluded.get("reason"), max_length=120),
                    "title": _trim_text(record.get("title") or (excluded.get("sourceSnapshot") or {}).get("title"), max_length=240),
                }
            )
            continue
        active_records.append(record)
    return active_records, {
        "excludedCount": len(excluded_refs),
        "activeRecordCount": len(active_records),
        "rawRecordCount": len([item for item in records if isinstance(item, dict)]),
        "excluded": excluded_refs[:40],
    }


def _normalize_source_collection_exclusion_reason(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", _trim_text(value, max_length=120).lower()).strip("_")
    aliases = {
        "no_content": "no_effective_content",
        "empty": "no_effective_content",
        "invalid": "no_effective_content",
        "exclude": "no_effective_content",
        "excluded": "no_effective_content",
        "discard": "no_effective_content",
        "discarded": "no_effective_content",
        "irrelevant": "out_of_scope",
        "topic_mismatch": "out_of_scope",
        "not_relevant": "out_of_scope",
        "not_obtainable": "unobtainable",
        "not_accessible": "unobtainable",
        "cannot_access": "unobtainable",
        "unavailable": "unobtainable",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in SOURCE_COLLECTION_EXCLUSION_REASONS else ""


def _source_collection_normalized_doi(value: Any) -> str:
    text = _trim_text(value, max_length=1000).strip()
    if not text:
        return ""
    match = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(0).rstrip(".,;)").lower()


def _source_collection_normalized_url(value: Any) -> str:
    text = _trim_text(value, max_length=1000).strip()
    if not _looks_like_url(text):
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return ""
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if not netloc:
        return ""
    query_pairs = sorted(
        [
        (key, val)
        for key, val in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid"}
        ]
    )
    query = urllib.parse.urlencode(query_pairs, doseq=True)
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def _crossref_search_url(query_text: str, *, rows: int) -> str:
    params = urllib.parse.urlencode(
        {
            "query": query_text,
            "rows": str(rows),
            "select": "DOI,title,URL,container-title,published-print,published-online,issued,author,type,abstract,score",
        }
    )
    return f"https://api.crossref.org/works?{params}"


def _source_collection_result_from_crossref_item(item: dict[str, Any], *, fallback_source_type: str) -> dict[str, Any]:
    doi = _trim_text(item.get("DOI"), max_length=500)
    source_ref = f"https://doi.org/{doi}" if doi else _trim_text(item.get("URL"), max_length=1000)
    title = _first_crossref_text(item.get("title")) or doi or source_ref
    container_title = _first_crossref_text(item.get("container-title"))
    issued = _crossref_date(item.get("published-print")) or _crossref_date(item.get("published-online")) or _crossref_date(item.get("issued"))
    abstract = _strip_html(_trim_text(item.get("abstract"), max_length=5000))
    authors = _crossref_authors(item.get("author"))
    crossref_type = _trim_text(item.get("type"), max_length=80)
    source_type = _source_collection_data_processing_source_type(fallback_source_type or crossref_type)
    summary_parts = [
        f"Container: {container_title}" if container_title else "",
        f"Published: {issued}" if issued else "",
        abstract,
    ]
    return {
        "title": title,
        "sourceRef": source_ref,
        "rawLocation": _trim_text(item.get("URL"), max_length=1000) or source_ref,
        "summary": _trim_text(" ".join(part for part in summary_parts if part), max_length=1600),
        "sourceType": source_type,
        "providerType": crossref_type,
        "metadata": {
            "doi": doi,
            "containerTitle": container_title,
            "issued": issued,
            "authors": authors,
            "crossrefType": crossref_type,
        },
        "qualitySignals": {
            "providerScore": item.get("score"),
            "hasDoi": bool(doi),
            "hasAbstract": bool(abstract),
        },
    }


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


def _source_collection_storage_refs(run: dict[str, Any]) -> list[str]:
    storage = run.get("storage") if isinstance(run.get("storage"), dict) else {}
    return [
        _trim_text(storage.get("recordsPath"), max_length=240),
        _trim_text(storage.get("collectionOutputsPath"), max_length=240),
    ]


def _source_collection_storage_artifact_paths(team_id: str, run_id: str) -> dict[str, Path]:
    normalized_team_id = _safe_token(team_id, default="team", max_length=96)
    normalized_run_id = _safe_token(run_id, default="run", max_length=96)
    run_directory = _team_workflow_root(normalized_team_id) / "source_collection_runs" / normalized_run_id
    data_processing_directory = developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "data_processing",
        "runs",
        normalized_run_id,
    )
    return {
        "runDirectory": run_directory,
        "artifactsDirectory": run_directory / "artifacts",
        "searchPlanPath": run_directory / "search_plan.json",
        "searchEventsPath": run_directory / "search_events.jsonl",
        "recordsPath": run_directory / "records.jsonl",
        "candidatesPath": run_directory / "candidates.jsonl",
        "candidateStorePath": _candidate_store_path(normalized_team_id),
        "dataProcessingRunPath": data_processing_directory / "run.json",
        "dataProcessingRecordsPath": data_processing_directory / "records.jsonl",
    }


def _source_collection_storage_artifacts(team_id: str, run_id: str) -> dict[str, str]:
    return {
        key: _relative_path(path)
        for key, path in _source_collection_storage_artifact_paths(team_id, run_id).items()
    }


def _source_collection_candidates_for_run(team_id: str, run_id: str) -> list[dict[str, Any]]:
    normalized_run_id = _trim_text(run_id, max_length=128)
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(team_id)
    candidates: list[dict[str, Any]] = []
    for item in list(candidate_store.get("candidates") or []):
        if not isinstance(item, dict) or item.get("candidateType") != "source_manifest":
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        candidate_run_id = (
            _trim_text(imported_from.get("runId"), max_length=128)
            or _trim_text(metadata.get("sourceCollectionRunId"), max_length=128)
        )
        if candidate_run_id == normalized_run_id:
            candidates.append(item)
    return candidates


def _source_collection_run_context_bundle(team_id: str, run_id: str) -> dict[str, Any]:
    try:
        run = data_processing_service.get_processing_run(run_id)
        assignments_payload = data_processing_service.list_collection_assignments(run_id)
        records_payload = data_processing_service.list_records(run_id)
        run_status = data_processing_service.get_processing_status(run_id)
    except data_processing_service.DataProcessingError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = _trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != team_id:
        raise TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")
    assignments = [item for item in list(assignments_payload.get("assignments") or []) if isinstance(item, dict)]
    all_records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    records, excluded_source_summary = _source_collection_filter_active_records(team_id, run, all_records)
    source_candidates = _source_collection_candidates_for_run(team_id, run_id)
    active_snapshot = _source_collection_work_run_store().load_active_snapshot(SOURCE_COLLECTION_WORK_RUN_KIND)
    active_snapshot = _decorate_source_collection_work_run_snapshot(
        active_snapshot,
        team_id=team_id,
        run_id=run_id,
    )
    active_work_run = (
        active_snapshot
        if _source_collection_background_snapshot_is_active(active_snapshot, team_id, run_id)
        else {}
    )
    return {
        "run": run,
        "assignments": assignments,
        "records": records,
        "allRecords": all_records,
        "excludedSourceSummary": excluded_source_summary,
        "runStatus": run_status,
        "sourceCandidates": source_candidates,
        "activeWorkRun": active_work_run,
    }


def _source_collection_matching_assignments(
    assignments: list[dict[str, Any]],
    *,
    agent_id: str,
    agent_role: str,
) -> list[dict[str, Any]]:
    return [
        item
        for item in assignments
        if (
            (agent_role and _trim_text(item.get("agentRole"), max_length=80) == agent_role)
            or _trim_text(item.get("agentId"), max_length=160) == agent_id
        )
    ]


def _source_collection_stage_retry_ancestor_results(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
) -> list[dict[str, Any]]:
    task_id = _trim_text(task.get("taskId"), max_length=160)
    parent_task_id = _trim_text(task.get("retrySourceTaskId"), max_length=160)
    seen = {task_id} if task_id else set()
    results: list[dict[str, Any]] = []
    while parent_task_id and parent_task_id not in seen and len(results) < 24:
        seen.add(parent_task_id)
        parent_task, parent_run_id = _find_source_collection_stage_session_task_by_id(team_id, parent_task_id)
        if parent_task is None or parent_run_id != run_id:
            break
        parent_writeback = parent_task.get("writeback") if isinstance(parent_task.get("writeback"), dict) else {}
        parent_result = parent_writeback.get("result") if isinstance(parent_writeback.get("result"), dict) else {}
        if not parent_result and isinstance(parent_task.get("result"), dict):
            parent_result = parent_task["result"]
        if parent_result:
            results.append(parent_result)
        parent_task_id = _trim_text(parent_task.get("retrySourceTaskId"), max_length=160)
    return list(reversed(results))



def _source_collection_run_belongs_to_team(run: dict[str, Any], team_id: str) -> bool:
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    run_team_id = _trim_text(scope.get("teamId") or metadata.get("teamId"), max_length=160)
    started_from = _trim_text(metadata.get("startedFrom"), max_length=160)
    workflow_stage = _trim_text(scope.get("workflowStage"), max_length=120)
    return run_team_id == team_id and (
        started_from == "team_workflow_source_collection"
        or workflow_stage == "knowledge_collection"
    )


def _source_collection_run_has_usable_outputs(run: dict[str, Any]) -> bool:
    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    processing_status = run.get("processingStatus") if isinstance(run.get("processingStatus"), dict) else {}
    processing_summary = processing_status.get("summary") if isinstance(processing_status.get("summary"), dict) else {}
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    for source in (summary, processing_summary, scope.get("sourceCollectionSummary"), metadata.get("sourceCollectionSummary"), scope, metadata):
        if not isinstance(source, dict):
            continue
        if any(
            _source_collection_count(source.get(key)) > 0
            for key in ("recordCount", "rawRecordCount", "createdUniqueRecordCount", "sourceCandidateCount", "candidateCount", "importedCount")
        ):
            return True
    return False


def _source_collection_stage_round_ref_for_run(team_id: str, run_id: str) -> dict[str, Any]:
    normalized_run_id = _trim_text(run_id, max_length=160)
    if not normalized_run_id:
        return {}
    with _WORKFLOW_LOCK:
        store = _load_stage_round_store(team_id)
    rounds = [
        item for item in _stage_rounds(store)
        if isinstance(item, dict)
        and str(item.get("stageType") or "") == "knowledge_collection"
        and normalized_run_id in {str(source_run_id) for source_run_id in list(item.get("sourceRunIds") or [])}
    ]
    latest_round = _latest_stage_round(rounds)
    if not latest_round:
        return {}
    return {
        "stageRoundId": _trim_text(latest_round.get("stageRoundId"), max_length=160),
        "stageType": "knowledge_collection",
        "roundNumber": _source_collection_count(latest_round.get("roundNumber")),
        "status": _trim_text(latest_round.get("status"), max_length=80),
        "sourceRunIds": [str(item) for item in list(latest_round.get("sourceRunIds") or []) if str(item or "").strip()],
        "updatedAt": _trim_text(latest_round.get("updatedAt"), max_length=120),
    }


def _source_collection_completion_superseded_stage_cutoffs(team_id: str, run_id: str) -> dict[str, str]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = _trim_text(run_id, max_length=160)
    if not normalized_run_id:
        return {}
    try:
        snapshot = _decorate_knowledge_ingestion_work_run_snapshot(
            _knowledge_ingestion_work_run_store().load_latest_snapshot(KNOWLEDGE_INGESTION_WORK_RUN_KIND)
        )
    except Exception:
        return {}
    if not isinstance(snapshot, dict):
        return {}
    if _trim_text(snapshot.get("teamId"), max_length=160) != normalized_team_id:
        return {}
    if _trim_text(snapshot.get("sourceRunId"), max_length=160) != normalized_run_id:
        return {}
    if _knowledge_collection_flow_step_status(snapshot.get("status")) == "failed":
        return {}
    flow = snapshot.get("flowVisualization") if isinstance(snapshot.get("flowVisualization"), dict) else {}
    nodes = [item for item in list(flow.get("nodes") or []) if isinstance(item, dict)]
    updated_at = _trim_text(snapshot.get("finishedAt") or snapshot.get("updatedAt"), max_length=120)
    if not nodes or not updated_at:
        return {}
    cutoffs: dict[str, str] = {}
    for node in nodes:
        stage_id = _normalize_source_collection_stage_id(node.get("stageId"), default="")
        if stage_id not in SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
            continue
        raw_status = _trim_text(node.get("status"), max_length=120).lower()
        normalized_status = _knowledge_collection_flow_step_status(raw_status)
        if raw_status == "executed" or normalized_status in {"completed", "skipped"}:
            cutoffs[stage_id] = updated_at
    return cutoffs


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


def _source_collection_team_member_snapshot(team_id: str) -> list[dict[str, Any]]:
    try:
        with team_service._TEAM_LOCK:  # type: ignore[attr-defined]
            state = team_service._load_index()  # type: ignore[attr-defined]
            team = team_service._find_team(state, team_id)  # type: ignore[attr-defined]
    except Exception:
        try:
            team = team_service.get_team(team_id)
        except Exception:
            team = {}
    return [
        dict(member)
        for member in list((team or {}).get("members") or [])
        if isinstance(member, dict)
    ]


def _source_collection_team_identity_snapshot(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    try:
        with team_service._TEAM_LOCK:  # type: ignore[attr-defined]
            state = team_service._load_index()  # type: ignore[attr-defined]
            team = team_service._find_team(state, normalized_team_id)  # type: ignore[attr-defined]
    except Exception:
        team = None
    if isinstance(team, dict):
        return {
            "teamId": normalized_team_id,
            "name": _trim_text(team.get("name"), max_length=160),
            "linkedChatRoomId": _trim_text(team.get("linkedChatRoomId"), max_length=160),
        }
    team_service.assert_team_exists(normalized_team_id)
    return {"teamId": normalized_team_id, "name": "", "linkedChatRoomId": ""}


def _source_collection_current_stage_agent_ids_by_stage(team_id: str, stage_ids: Iterable[str]) -> dict[str, set[str]]:
    normalized_stage_ids = [
        _normalize_source_collection_stage_id(stage_id, default="")
        for stage_id in stage_ids
        if _normalize_source_collection_stage_id(stage_id, default="") in SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES
    ]
    result = {stage_id: set() for stage_id in normalized_stage_ids}
    if not result:
        return result
    role_to_stage_ids: dict[str, list[str]] = {}
    for stage_id in result:
        for role in SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES.get(stage_id, ()):
            role_to_stage_ids.setdefault(role, []).append(stage_id)
    for member in _source_collection_team_member_snapshot(team_id):
        member_role = _normalize_source_collection_agent_role(member.get("role") or member.get("agentRole"))
        member_agent_id = _trim_text(member.get("agentId"), max_length=160)
        if not member_agent_id:
            continue
        for stage_id in role_to_stage_ids.get(member_role, ()):
            result[stage_id].add(member_agent_id)
    return result


def _source_collection_current_stage_agent_ids(team_id: str, stage_id: str) -> set[str]:
    return _source_collection_current_stage_agent_ids_by_stage(team_id, [stage_id]).get(stage_id, set())


def _source_collection_stage_task_has_evidence_gaps(task: dict[str, Any] | None) -> bool:
    if not isinstance(task, dict) or not task:
        return False
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    materialized = (
        writeback.get("materializedContentExtraction")
        if isinstance(writeback.get("materializedContentExtraction"), dict)
        else {}
    )
    if _source_collection_count(materialized.get("missingEvidenceAnchorCount")) > 0:
        return True
    coverage = _source_collection_stage_task_coverage_summary(task)
    return bool(
        isinstance(coverage, dict)
        and bool(coverage.get("applicable"))
        and bool(coverage.get("complete"))
        and coverage.get("blockedCandidateIds")
    )


def _source_collection_agent_context_next_actions(stage_id: str, record_count: int, candidate_count: int, open_assignment_count: int) -> list[str]:
    if stage_id == "finding":
        if record_count <= 0:
            return ["继续等待或执行资料搜索，先形成 DataRecord。"]
        return ["检查 DataRecord 覆盖面，必要时补充查询词或来源类型。"]
    if stage_id == "extraction":
        if candidate_count <= 0:
            return ["从 DataRecord 提炼 source_manifest 候选。"]
        return ["完成候选内容提炼，并对相关性、可靠性、可访问性和入库价值给出审查结论。"]
    if stage_id == "relations":
        return ["基于已通过质量评估的候选构建候选关系图。"]
    if stage_id == "ingestion":
        return ["审核通过候选入库包；正式知识写入仍受审核门禁控制。"]
    if open_assignment_count:
        return ["继续处理未完成的本角色分派任务。"]
    return []


def _source_collection_work_run_store() -> work_run_store.WorkRunStore:
    return work_run_store.WorkRunStore(root=work_run_store.WORK_RUNS_DIR)


def _persist_source_collection_work_run(
    team_id: str,
    run_id: str,
    *,
    status: str,
    current_phase: str,
    run: dict[str, Any],
    team: dict[str, Any],
    assignments: list[dict[str, Any]],
    records: list[dict[str, Any]],
    summary: str,
    active: bool,
    error: str = "",
    error_type: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now_iso()
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    assignment_summary = _source_collection_assignment_stage_summary(assignments)
    search_plan_ref = run_scope.get("dataSearchPlanRef") if isinstance(run_scope.get("dataSearchPlanRef"), dict) else {}
    query_count = _normalize_int(
        run_metadata.get("queryCount") or search_plan_ref.get("queryCount"),
        default=0,
        minimum=0,
        maximum=SOURCE_COLLECTION_MAX_QUERIES * 4,
    )
    snapshot: dict[str, Any] = {
        "runId": run_id,
        "runKind": SOURCE_COLLECTION_WORK_RUN_KIND,
        "kind": SOURCE_COLLECTION_WORK_RUN_KIND,
        "status": status,
        "currentPhase": current_phase,
        "stageType": "knowledge_collection",
        "teamId": team_id,
        "teamName": _trim_text(team.get("name"), max_length=160) or team_id,
        "title": _trim_text(run.get("title"), max_length=180) or "知识搜集批次",
        "topic": _trim_text(run_scope.get("topic"), max_length=500),
        "summary": _trim_text(summary, max_length=500),
        "currentTask": _trim_text(summary, max_length=500),
        "assignmentCount": len(assignments),
        "openAssignmentCount": assignment_summary["openAssignmentCount"],
        "searchAssignmentCount": assignment_summary["searchAssignmentCount"],
        "searchOpenAssignmentCount": assignment_summary["searchOpenAssignmentCount"],
        "collectionAssignmentCount": assignment_summary["collectionAssignmentCount"],
        "collectionOpenAssignmentCount": assignment_summary["collectionOpenAssignmentCount"],
        "downstreamAssignmentCount": assignment_summary["downstreamAssignmentCount"],
        "downstreamOpenAssignmentCount": assignment_summary["downstreamOpenAssignmentCount"],
        "recordCount": len(records),
        "queryCount": query_count,
        "storagePath": _source_collection_storage_artifacts(team_id, run_id)["runDirectory"],
        "updatedAt": now,
        "sourceCollection": {
            "teamId": team_id,
            "stageType": "knowledge_collection",
            "openAssignmentCount": assignment_summary["openAssignmentCount"],
            "searchAssignmentCount": assignment_summary["searchAssignmentCount"],
            "searchOpenAssignmentCount": assignment_summary["searchOpenAssignmentCount"],
            "collectionAssignmentCount": assignment_summary["collectionAssignmentCount"],
            "collectionOpenAssignmentCount": assignment_summary["collectionOpenAssignmentCount"],
            "downstreamAssignmentCount": assignment_summary["downstreamAssignmentCount"],
            "downstreamOpenAssignmentCount": assignment_summary["downstreamOpenAssignmentCount"],
            "recordCount": len(records),
            "queryCount": query_count,
        },
    }
    started_at = _trim_text(run.get("createdAt"), max_length=80) or _trim_text(run.get("startedAt"), max_length=80)
    if started_at:
        snapshot["startedAt"] = started_at
    if not active:
        snapshot["finishedAt"] = now
    if error:
        snapshot["error"] = _trim_text(error, max_length=500)
    if error_type:
        snapshot["errorType"] = _trim_text(error_type, max_length=120)
    if extra:
        snapshot.update(extra)
        source_collection = snapshot.get("sourceCollection") if isinstance(snapshot.get("sourceCollection"), dict) else {}
        source_collection.update({key: value for key, value in extra.items() if key.endswith("Count")})
        snapshot["sourceCollection"] = source_collection
    return _source_collection_work_run_store().persist_snapshot(
        SOURCE_COLLECTION_WORK_RUN_KIND,
        snapshot,
        active_run_id=run_id if active else "",
    )


def _source_collection_work_run_terminal_status(result: dict[str, Any]) -> str:
    if str(result.get("status") or "") == "duplicates_skipped":
        return "completed"
    if _source_collection_count(result.get("failedQueryCount")) and not _source_collection_count(result.get("executedQueryCount")):
        return "failed"
    if bool(result.get("hasMore")) or _source_collection_count(result.get("remainingQueryCount")):
        return "needs_continue"
    source_collection_summary = result.get("sourceCollectionSummary") if isinstance(result.get("sourceCollectionSummary"), dict) else {}
    if _source_collection_count(source_collection_summary.get("searchOpenAssignmentCount")):
        return "needs_continue"
    return "completed"


def _source_collection_work_run_terminal_phase(result: dict[str, Any]) -> str:
    status = _source_collection_work_run_terminal_status(result)
    if status == "failed":
        return "failed"
    if status == "needs_continue":
        return "waiting_for_next_batch"
    return "completed"


def _source_collection_work_run_terminal_summary(result: dict[str, Any]) -> str:
    if _source_collection_work_run_terminal_status(result) == "failed":
        return "资料搜索执行失败，等待检查搜索错误。"
    record_count = _source_collection_count(result.get("recordCount"))
    imported_count = _source_collection_count(result.get("importedCount"))
    skipped_duplicate_count = _source_collection_count(result.get("skippedDuplicateCount"))
    if str(result.get("status") or "") == "duplicates_skipped":
        return f"本轮资料搜索完成，跳过 {skipped_duplicate_count} 条重复资料，未新增资料。"
    if _source_collection_work_run_terminal_status(result) == "needs_continue":
        return f"本轮已写入 {record_count} 条资料、导入 {imported_count} 个候选、跳过 {skipped_duplicate_count} 条重复资料，仍有任务可继续。"
    return f"本轮资料搜索完成，写入 {record_count} 条资料、导入 {imported_count} 个候选、跳过 {skipped_duplicate_count} 条重复资料。"


def _source_collection_count(value: Any) -> int:
    return _normalize_int(value, default=0, minimum=0, maximum=100_000)


def _source_collection_storage_target_path(team_id: str, run_id: str, target: str) -> Path:
    paths = _source_collection_storage_artifact_paths(team_id, run_id)
    target_to_path = {
        "run_directory": paths["runDirectory"],
        "artifacts_directory": paths["artifactsDirectory"],
        "search_plan": paths["searchPlanPath"],
        "search_events": paths["searchEventsPath"],
        "records": paths["recordsPath"],
        "candidates": paths["candidatesPath"],
        "candidate_store": paths["candidateStorePath"],
        "data_processing_run": paths["dataProcessingRunPath"],
        "data_processing_records": paths["dataProcessingRecordsPath"],
    }
    path = target_to_path.get(target)
    if path is None:
        raise TeamWorkflowOrchestrationError(f"Unsupported source collection storage target: {target or '<empty>'}")
    return _ensure_project_child(path)


def _write_source_collection_search_plan(team_id: str, run_id: str, search_plan: dict[str, Any]) -> None:
    paths = _source_collection_storage_artifact_paths(team_id, run_id)
    paths["runDirectory"].mkdir(parents=True, exist_ok=True)
    paths["artifactsDirectory"].mkdir(parents=True, exist_ok=True)
    _write_json(paths["searchPlanPath"], search_plan)
    for path_key in ("searchEventsPath", "recordsPath", "candidatesPath"):
        paths[path_key].touch(exist_ok=True)


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


def _source_collection_data_processing_source_type(value: Any) -> str:
    source_type = _trim_text(value, max_length=80).lower()
    if source_type in data_processing_service.SOURCE_TYPES:
        return source_type
    if source_type in {"review", "preprint", "journal-article", "proceedings-article", "book-chapter"}:
        return "paper"
    if source_type in {"posted-content"}:
        return "paper"
    if source_type in {"dataset", "data"}:
        return "dataset"
    return "url"


def _first_crossref_text(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = _trim_text(item, max_length=500)
            if text:
                return html.unescape(text)
        return ""
    return html.unescape(_trim_text(value, max_length=500))


def _crossref_authors(value: Any) -> list[str]:
    authors: list[str] = []
    for item in list(value or [])[:8]:
        if not isinstance(item, dict):
            continue
        name = " ".join(
            part
            for part in [
                _trim_text(item.get("given"), max_length=80),
                _trim_text(item.get("family"), max_length=120),
            ]
            if part
        ).strip()
        if name:
            authors.append(name)
    return authors


def _crossref_date(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    date_parts = value.get("date-parts")
    if not isinstance(date_parts, list) or not date_parts:
        return ""
    first = date_parts[0]
    if not isinstance(first, list) or not first:
        return ""
    parts = [str(part).zfill(2) for part in first[:3] if isinstance(part, int)]
    if not parts:
        return ""
    if parts:
        parts[0] = parts[0].lstrip("0") or "0"
    return "-".join(parts)


def _strip_html(value: str) -> str:
    if not value:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()


def _source_collection_role_assignment_inputs(queries: list[dict[str, Any]], roles: list[str], payload: dict[str, Any]) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for role in roles:
        role_queries = _source_collection_queries_for_role({"queries": queries}, role)
        prompt_cache_partition = ""
        for query in role_queries:
            execution = query.get("execution") if isinstance(query.get("execution"), dict) else {}
            prompt_cache_partition = _trim_text(execution.get("promptCachePartition"), max_length=160)
            if prompt_cache_partition:
                break
        assignments.append(
            {
                "agentRole": role,
                "agentId": _source_collection_agent_id(role, payload),
                "queryIds": [item["queryId"] for item in role_queries],
                "queryCount": len(role_queries),
                "promptCachePartition": prompt_cache_partition,
                "conversationTraceRequired": True,
                "expectedAction": _source_collection_expected_action(role),
            }
        )
    return assignments


def _source_collection_queries_for_role(search_plan: dict[str, Any], role: str) -> list[dict[str, Any]]:
    queries = search_plan.get("queries")
    if not isinstance(queries, list):
        return []
    return [item for item in queries if isinstance(item, dict) and item.get("assignedAgentRole") == role]


def _source_collection_expected_action(role: str) -> str:
    actions = {
        "data_intake_coordinator": "Coordinate planned query execution and ensure outputs follow the writeback contract.",
        "source_finder": "Find, fetch, download, and register traceable DataRecord sources.",
        "source_extractor": "Extract useful content and review source quality with per-source decisions.",
        "source_relation_mapper": "Organize approved sources into candidate-only topic and evidence relationships.",
        "source_ingestor": "Review approved candidates and write governed formal Team Knowledge.",
    }
    return actions.get(role, "Collect data records under the source-collection run contract.")


def _source_collection_query_seeds(payload: dict[str, Any], scope: dict[str, Any], input_refs: list[str], *, topic: str, goal: str) -> list[str]:
    seeds: list[str] = []
    for value in _normalize_text_list(payload.get("querySeeds"), max_items=40, max_length=220):
        _append_source_collection_seed(seeds, value)
    _append_source_collection_seed(seeds, topic)
    for key in ("researchQuestion", "domain", "dataset", "benchmark", "organism", "method"):
        _append_source_collection_seed(seeds, scope.get(key))
    for value in _metadata_text_values(scope.get("keywords")):
        _append_source_collection_seed(seeds, value)
    for value in _metadata_text_values(scope.get("seedQueries")):
        _append_source_collection_seed(seeds, value)
    for ref in input_refs:
        _append_source_collection_seed(seeds, _source_collection_seed_from_input_ref(ref))
    if not seeds:
        _append_source_collection_seed(seeds, goal)
    if not seeds:
        _append_source_collection_seed(seeds, "challenge cup research source collection")
    return seeds[:12]


def _append_source_collection_seed(seeds: list[str], value: Any) -> None:
    text = _trim_text(value, max_length=220)
    if not text:
        return
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return
    seen = {item.lower() for item in seeds}
    if normalized.lower() not in seen:
        seeds.append(normalized)


def _source_collection_seed_from_input_ref(value: Any) -> str:
    text = _trim_text(value, max_length=220)
    lowered = text.lower()
    for prefix in ("seed-query:", "query:", "keyword:", "topic:"):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


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


def _source_collection_search_languages(value: Any) -> list[str]:
    languages = _normalize_text_list(value, max_items=8, max_length=16)
    return languages or list(SOURCE_COLLECTION_DEFAULT_SEARCH_LANGUAGES)


def _source_collection_source_types(value: Any) -> list[str]:
    source_types = _normalize_text_list(value, max_items=16, max_length=40)
    return source_types or list(SOURCE_COLLECTION_DEFAULT_SOURCE_TYPES)


def _source_collection_query_text(seed: str, *, source_type: str, language: str) -> str:
    normalized_seed = _trim_text(seed, max_length=220)
    normalized_source_type = _trim_text(source_type, max_length=40).lower()
    normalized_language = _trim_text(language, max_length=16).lower()
    if normalized_language.startswith("zh") or normalized_language in {"cn", "chinese"}:
        suffixes = {
            "paper": "论文",
            "review": "综述",
            "dataset": "数据集",
            "preprint": "预印本",
        }
        suffix = suffixes.get(normalized_source_type, normalized_source_type or "资料")
        return _trim_text(f"{normalized_seed} {suffix}", max_length=260)
    suffixes = {
        "paper": "peer reviewed paper",
        "review": "review",
        "dataset": "dataset",
        "preprint": "preprint",
    }
    suffix = suffixes.get(normalized_source_type, normalized_source_type or "source")
    return _trim_text(f"{normalized_seed} {suffix}", max_length=260)


def _normalize_stage_type(value: Any) -> str:
    normalized = _trim_text(value, max_length=80)
    if normalized not in RESEARCH_STAGE_TYPES:
        raise TeamWorkflowOrchestrationError("Unsupported research stage type.")
    return normalized


def _normalize_stage_start_mode(value: Any) -> str:
    normalized = _trim_text(value, max_length=80)
    return "new_round" if normalized in {"new_round", "new", "restart"} else "continue_or_start"


def _load_stage_round_store(team_id: str) -> dict[str, Any]:
    path = _stage_round_store_path(team_id)
    if path.exists():
        payload = _read_json(path)
        if isinstance(payload.get("rounds"), list):
            return payload
    now = utc_now_iso()
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "storeKind": "research_stage_round_store",
        "rounds": [],
        "createdAt": now,
        "updatedAt": now,
    }
    _write_json(path, payload)
    return payload


def _stage_rounds(store: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in list(store.get("rounds") or []) if isinstance(item, dict)]


def _find_stage_round(rounds: list[dict[str, Any]], stage_round_id: str) -> dict[str, Any] | None:
    for item in rounds:
        if str(item.get("stageRoundId") or "") == stage_round_id:
            return item
    return None


def _active_stage_round(rounds: list[dict[str, Any]], stage_type: str) -> dict[str, Any] | None:
    candidates = [
        item
        for item in rounds
        if str(item.get("stageType") or "") == stage_type and str(item.get("status") or "") in RESEARCH_STAGE_ACTIVE_STATUSES
    ]
    return _latest_stage_round(candidates)


def _continued_stage_round_payload(stage_round: dict[str, Any], stage_type: str) -> dict[str, Any]:
    """Return enough context for the UI to show that an active stage was reused."""

    if stage_type != "knowledge_collection":
        return {}
    source_run_ids = [str(item) for item in list(stage_round.get("sourceRunIds") or []) if str(item or "").strip()]
    source_run_id = source_run_ids[0] if source_run_ids else ""
    if not source_run_id:
        return {
            "continuedSourceRunRef": {
                "runId": "",
                "status": "missing",
                "recordCount": 0,
                "assignmentCount": 0,
                "openAssignmentCount": 0,
                "message": "Active knowledge-collection round has no source run id.",
            }
        }
    try:
        run = data_processing_service.get_processing_run(source_run_id)
        assignment_payload = data_processing_service.list_collection_assignments(source_run_id)
    except data_processing_service.DataProcessingNotFoundError:
        return {
            "continuedSourceRunRef": {
                "runId": source_run_id,
                "status": "missing",
                "recordCount": 0,
                "assignmentCount": 0,
                "openAssignmentCount": 0,
                "message": "Active knowledge-collection round points to a missing source run.",
            }
        }
    assignments = [item for item in list(assignment_payload.get("assignments") or []) if isinstance(item, dict)]
    assignment_summary = _source_collection_assignment_stage_summary(assignments)
    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    data_search_plan_ref = scope.get("dataSearchPlanRef") if isinstance(scope.get("dataSearchPlanRef"), dict) else {}
    return {
        "run": run,
        "assignments": assignments,
        "assignmentCount": len(assignments),
        "continuedSourceRunRef": {
            "runId": source_run_id,
            "status": str(run.get("status") or ""),
            "recordCount": _normalize_int(summary.get("recordCount"), default=0, minimum=0, maximum=100000),
            "assignmentCount": _normalize_int(summary.get("assignmentCount"), default=len(assignments), minimum=0, maximum=100000),
            "openAssignmentCount": _normalize_int(summary.get("openAssignmentCount"), default=0, minimum=0, maximum=100000),
            "searchOpenAssignmentCount": assignment_summary["searchOpenAssignmentCount"],
            "collectionOpenAssignmentCount": assignment_summary["collectionOpenAssignmentCount"],
            "downstreamOpenAssignmentCount": assignment_summary["downstreamOpenAssignmentCount"],
            "queryCount": _normalize_int(data_search_plan_ref.get("queryCount"), default=0, minimum=0, maximum=SOURCE_COLLECTION_MAX_QUERIES),
            "planId": _trim_text(data_search_plan_ref.get("planId"), max_length=160),
            "externalSearchTriggered": bool(data_search_plan_ref.get("externalSearchTriggered")),
            "message": "Reused the active source-collection run instead of creating a new one.",
        },
    }


def _build_stage_round(
    team_id: str,
    stage_type: str,
    payload: dict[str, Any],
    rounds: list[dict[str, Any]],
    *,
    previous_round: dict[str, Any] | None,
    requested_by_agent: str,
    team: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now_iso()
    round_number = _stage_round_number(rounds, stage_type)
    topic = _trim_text(payload.get("topic"), max_length=500) or _trim_text(previous_round.get("topic") if previous_round else "", max_length=500)
    goal = _trim_text(payload.get("goal"), max_length=1000) or _trim_text(previous_round.get("goal") if previous_round else "", max_length=1000)
    if stage_type == "knowledge_collection" and not topic:
        raise TeamWorkflowOrchestrationError("Research topic is required to start knowledge collection.")
    if not topic:
        topic = _stage_default_topic(stage_type, previous_round)
    if not goal:
        goal = _stage_default_goal(stage_type, previous_round)
    query_seeds = _stage_query_seeds(payload, previous_round, topic=topic, goal=goal)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "stageRoundId": _new_record_id("stage"),
        "teamId": team_id,
        "stageType": stage_type,
        "roundNumber": round_number,
        "status": "initializing",
        "title": _trim_text(payload.get("title"), max_length=180) or f"{RESEARCH_STAGE_DEFAULTS[stage_type]['title']} {round_number}",
        "topic": topic,
        "goal": goal,
        "requestedByAgent": requested_by_agent,
        "ownerAgentId": _source_collection_owner_agent_id(team, payload),
        "upstreamRoundIds": _stage_upstream_round_ids(payload, rounds, stage_type, previous_round),
        "sourceRunIds": [],
        "assignmentIds": [],
        "agentRoleAssignments": [],
        "querySeeds": query_seeds,
        "suggestedQuerySeeds": _suggest_stage_query_seeds(previous_round, topic=topic, goal=goal),
        "inputRefs": _normalize_text_list(payload.get("inputRefs"), max_items=120, max_length=240),
        "searchLanguages": _source_collection_search_languages(payload.get("searchLanguages")),
        "sourceTypes": _source_collection_source_types(payload.get("sourceTypes")),
        "maxResultsPerQuery": _normalize_int(
            payload.get("maxResultsPerQuery"),
            default=SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY,
            minimum=1,
            maximum=100,
        ),
        "workflowItemRef": {},
        "dataSearchPlanRef": {},
        "teamMemoryRecordId": "",
        "teamMemoryRecord": {},
        "coordinationContract": {},
        "planningContract": {},
        "warnings": [],
        "boundaries": _research_stage_boundaries(),
        "createdAt": now,
        "updatedAt": now,
    }


def _stage_source_collection_payload(stage_round: dict[str, Any], payload: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    scope = _normalize_metadata(payload.get("scope"))
    scope.update(
        {
            "workflowStage": "knowledge_collection",
            "researchStageRoundId": stage_round["stageRoundId"],
            "researchStageRoundNumber": stage_round["roundNumber"],
            "uiEntry": _trim_text(scope.get("uiEntry"), max_length=120) or "teams_research_stage_launcher",
            "upstreamRoundIds": list(stage_round.get("upstreamRoundIds") or []),
        }
    )
    roles = _normalize_source_collection_roles(payload.get("agentRoles"))
    return {
        "title": stage_round["title"],
        "topic": stage_round["topic"],
        "goal": stage_round["goal"],
        "ownerAgentId": stage_round["ownerAgentId"],
        "requestedByAgent": stage_round["requestedByAgent"],
        "agentRoles": payload.get("agentRoles") or list(SOURCE_COLLECTION_DEFAULT_AGENT_ROLES),
        "agentIds": payload.get("agentIds") if isinstance(payload.get("agentIds"), dict) else _source_collection_team_agent_ids(team, roles, payload),
        "inputRefs": list(stage_round.get("inputRefs") or []),
        "querySeeds": list(stage_round.get("querySeeds") or []),
        "searchLanguages": list(stage_round.get("searchLanguages") or []),
        "sourceTypes": list(stage_round.get("sourceTypes") or []),
        "maxResultsPerQuery": int(stage_round.get("maxResultsPerQuery") or SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY),
        "promptCachePolicy": payload.get("promptCachePolicy") if isinstance(payload.get("promptCachePolicy"), dict) else {},
        "scope": scope,
    }


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


def _research_memory_context_summary(value: Any) -> dict[str, Any]:
    context = value if isinstance(value, dict) else {}
    retrieval = context.get("retrieval") if isinstance(context.get("retrieval"), dict) else {}
    claim_map = [
        item
        for item in list(context.get("claimMap") or [])
        if isinstance(item, dict)
    ]
    claim_status_counts = {
        status: sum(
            1
            for item in claim_map
            if str(item.get("status") or "") == status
        )
        for status in ("qualified", "unsupported", "rejected", "not_established")
    }
    allowed_variable_contract = (
        context.get("allowedVariableContract")
        if isinstance(context.get("allowedVariableContract"), dict)
        else {}
    )
    allowed_variables = [
        str(item.get("path") or "")
        for item in list(allowed_variable_contract.get("variables") or [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ][:16]
    allowed_variable_details = [
        {
            "path": str(item.get("path") or "")[:240],
            "source": str(item.get("source") or "")[:80],
            "evidenceRef": str(item.get("evidenceRef") or "")[:240],
        }
        for item in list(allowed_variable_contract.get("variables") or [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ][:16]
    claim_details = [
        {
            "claimId": str(item.get("claimId") or "")[:160],
            "claim": str(item.get("claim") or "")[:800],
            "status": str(item.get("status") or "")[:64],
            "supportEvidenceRefs": [
                {
                    "type": str(ref.get("type") or "")[:80],
                    "id": str(ref.get("id") or "")[:500],
                }
                for ref in list(item.get("supportEvidenceRefs") or [])
                if isinstance(ref, dict) and str(ref.get("id") or "").strip()
            ][:8],
            "counterEvidenceRefs": [
                {
                    "type": str(ref.get("type") or "")[:80],
                    "id": str(ref.get("id") or "")[:500],
                }
                for ref in list(item.get("counterEvidenceRefs") or [])
                if isinstance(ref, dict) and str(ref.get("id") or "").strip()
            ][:8],
            "applicableBoundaries": [
                str(boundary)[:360]
                for boundary in list(item.get("applicableBoundaries") or [])
                if str(boundary).strip()
            ][:12],
            "sourcePlanIds": [
                str(plan_id)[:160]
                for plan_id in list(item.get("sourcePlanIds") or [])
                if str(plan_id).strip()
            ][:12],
        }
        for item in claim_map[:12]
    ]
    forbidden = [
        item
        for item in list(context.get("forbiddenDuplicateExperiments") or [])
        if isinstance(item, dict)
    ]
    return {
        "contextId": str(context.get("contextId") or ""),
        "knowledgeItemCount": int(retrieval.get("knowledgeItemCount") or 0),
        "reviewedSourceCount": int(retrieval.get("reviewedSourceCount") or 0),
        "negativeExperimentCount": int(retrieval.get("negativeExperimentCount") or 0),
        "successfulRunCount": int(retrieval.get("successfulRunCount") or 0),
        "forbiddenDuplicateExperimentCount": len(forbidden),
        "claimCount": len(claim_map),
        "claimStatusCounts": claim_status_counts,
        "allowedVariableCount": len(allowed_variables),
        "allowedVariables": allowed_variables,
        "allowedVariableContract": {
            "status": str(allowed_variable_contract.get("status") or "missing"),
            "variables": allowed_variable_details,
            "frozenControls": [
                str(item)[:360]
                for item in list(allowed_variable_contract.get("frozenControls") or [])
                if str(item).strip()
            ][:12],
        },
        "claimMap": claim_details,
        "claimMapPreview": [
            {
                "claimId": str(item.get("claimId") or ""),
                "claim": str(item.get("claim") or ""),
                "status": str(item.get("status") or ""),
            }
            for item in claim_map[:6]
        ],
        "missingEvidence": [
            str(item)
            for item in list(context.get("missingEvidence") or [])
            if str(item).strip()
        ][:12],
    }


def _legacy_research_lifecycle_memory_contexts(
    *,
    team_id: str,
    candidate_store: dict[str, Any],
    plans: list[dict[str, Any]],
    design_plan: dict[str, Any] | None,
    best_plan: dict[str, Any] | None,
    latest_experiment: dict[str, Any] | None,
    latest_iteration: dict[str, Any] | None,
    active_loop: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    design_contract = (
        design_plan.get("experimentContract")
        if isinstance((design_plan or {}).get("experimentContract"), dict)
        else {}
    )
    best_contract = (
        best_plan.get("experimentContract")
        if isinstance((best_plan or {}).get("experimentContract"), dict)
        else {}
    )
    research_question = _trim_text(
        design_contract.get("researchQuestion")
        or best_contract.get("researchQuestion")
        or (latest_experiment or {}).get("topic")
        or (latest_experiment or {}).get("goal")
        or (latest_iteration or {}).get("topic")
        or (latest_iteration or {}).get("goal")
        or (active_loop or {}).get("title")
        or "research lifecycle memory projection",
        max_length=1200,
    )
    actor_agent_id = _trim_text(
        (latest_experiment or {}).get("requestedByAgent")
        or (latest_experiment or {}).get("ownerAgentId")
        or (latest_iteration or {}).get("requestedByAgent")
        or (latest_iteration or {}).get("ownerAgentId"),
        max_length=160,
    )
    knowledge_results, retrieval_status = _research_memory_knowledge_results(
        team_id,
        research_question=research_question,
        actor_agent_id=actor_agent_id,
    )
    loop_store = _read_json(_team_workflow_root(team_id) / "research_loops" / "index.json")
    common = {
        "research_question": research_question,
        "candidates": [
            item
            for item in list(candidate_store.get("candidates") or [])
            if isinstance(item, dict)
        ],
        "plans": plans,
        "loops": [
            item
            for item in list(loop_store.get("loops") or [])
            if isinstance(item, dict)
        ],
        "knowledge_results": knowledge_results,
        "retrieval_status": retrieval_status,
    }
    return {
        "stage2": _build_research_memory_context(
            stage_type="experiment_design",
            control_plan=design_plan,
            **common,
        ),
        "stage3": _build_research_memory_context(
            stage_type="experiment_execution_iteration",
            control_plan=design_plan,
            **common,
        ),
    }


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


def _stage_phase_status(
    team_id: str,
    stage_type: str,
    rounds: list[dict[str, Any]],
    *,
    workflow: dict[str, Any],
    team: dict[str, Any],
) -> dict[str, Any]:
    stage_rounds = [item for item in rounds if str(item.get("stageType") or "") == stage_type]
    active_round = _active_stage_round(rounds, stage_type)
    latest_round = active_round or _latest_stage_round(stage_rounds)
    defaults = RESEARCH_STAGE_DEFAULTS[stage_type]
    return {
        "stageType": stage_type,
        "label": _stage_label(stage_type),
        "status": str(latest_round.get("status") if latest_round else "not_started"),
        "roundCount": len(stage_rounds),
        "activeRoundId": str(active_round.get("stageRoundId") if active_round else ""),
        "latestRound": latest_round,
        "primaryAction": defaults["continueActionZh"] if active_round else defaults["primaryActionZh"],
        "secondaryAction": defaults["newRoundActionZh"],
        "canStart": True,
        "canContinue": bool(active_round),
        "canNewRound": bool(stage_rounds),
        "requiresUserDecision": stage_type in {"experiment", "iteration"},
        "readiness": _stage_readiness(stage_type, rounds),
        "coordinationRoomId": str(team.get("linkedChatRoomId") or ""),
        "storagePath": _relative_path(_stage_round_store_path(team_id)),
    }


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


def _record_workflow_event(
    event_code: str,
    team_id: str,
    *,
    fields: dict[str, Any],
    level: str = "info",
    outcome: str = "observed",
    child_log_path: str = "",
    child_log_payload: dict[str, Any] | None = None,
    lifecycle: bool = False,
) -> None:
    try:
        record_runtime_scene_event(
            "team_workflow_orchestration",
            "workflow",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={"teamId": team_id, **fields},
            child_log_path=child_log_path,
            child_log_payload=child_log_payload,
            lifecycle=lifecycle,
        )
    except Exception:
        return


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


def _source_collection_exclusion_store_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "source_collection_exclusions" / "index.json"


def _stage_round_store_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "research_stage_rounds" / "index.json"


def _team_workflow_root(team_id: str) -> Path:
    return developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_token(team_id, default="team", max_length=96),
    )


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_project_root())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _new_record_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


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
