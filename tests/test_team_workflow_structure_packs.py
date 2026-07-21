"""Focused tests for team_workflow structure packs (Stage 3)."""

from __future__ import annotations

from core.web.services import team_workflow_orchestration_service as facade
from core.web.services.team_workflow import orchestration_core
from core.web.services.team_workflow import experiment, research_loop
from core.web.services.team_workflow.source_collection import candidates, runs, stages, storage
from core.web.services.team_workflow.source_collection import search_execution
from core.web.services.team_workflow.source_collection import writeback_materialize


def test_facade_reexports_orchestration_core() -> None:
    assert facade.get_team_workflow_orchestration is orchestration_core.get_team_workflow_orchestration
    assert facade.ensure_team_workflow_orchestration is orchestration_core.ensure_team_workflow_orchestration


def test_facade_reexports_candidates_pack() -> None:
    assert facade.register_candidate_source is candidates.register_candidate_source
    assert facade.import_data_record_as_source_candidate is candidates.import_data_record_as_source_candidate
    assert facade.extract_source_collection_candidates is candidates.extract_source_collection_candidates
    assert facade.list_candidate_store is candidates.list_candidate_store
    assert facade.validate_candidate_store is candidates.validate_candidate_store


def test_facade_reexports_runs_pack() -> None:
    assert facade.start_source_collection_run is runs.start_source_collection_run
    assert facade.execute_source_collection_search is runs.execute_source_collection_search
    assert facade.start_source_collection_search_background is runs.start_source_collection_search_background
    assert facade.get_source_collection_summary is runs.get_source_collection_summary
    assert facade.load_source_collection_work_run_summary is runs.load_source_collection_work_run_summary


def test_facade_reexports_search_execution_pack() -> None:
    assert facade._execute_source_collection_search_impl is search_execution._execute_source_collection_search_impl
    assert facade._run_source_collection_search_background is search_execution._run_source_collection_search_background
    assert facade._execute_source_collection_query is search_execution._execute_source_collection_query
    assert facade._sync_source_collection_stage_round_after_search is search_execution._sync_source_collection_stage_round_after_search
    assert (
        facade._source_collection_search_result_quality_gate
        is search_execution._source_collection_search_result_quality_gate
    )


def test_facade_reexports_writeback_materialize_pack() -> None:
    assert (
        facade._materialize_source_collection_stage_writeback_sources
        is writeback_materialize._materialize_source_collection_stage_writeback_sources
    )
    assert (
        facade._materialize_source_collection_stage_writeback_quality
        is writeback_materialize._materialize_source_collection_stage_writeback_quality
    )
    assert (
        facade._materialize_source_collection_stage_writeback_candidate_graph
        is writeback_materialize._materialize_source_collection_stage_writeback_candidate_graph
    )
    assert (
        facade._materialize_source_collection_stage_writeback_knowledge_ingestion
        is writeback_materialize._materialize_source_collection_stage_writeback_knowledge_ingestion
    )
    assert (
        facade._normalize_source_collection_stage_writeback_result_payload
        is writeback_materialize._normalize_source_collection_stage_writeback_result_payload
    )
    assert (
        facade._source_collection_stage_writeback_candidate_coverage
        is writeback_materialize._source_collection_stage_writeback_candidate_coverage
    )


def test_facade_reexports_stages_and_storage_packs() -> None:
    assert facade.start_source_collection_stage_session_task is stages.start_source_collection_stage_session_task
    assert facade.writeback_source_collection_stage_session_task is stages.writeback_source_collection_stage_session_task
    assert facade.get_source_collection_stage_task_context is stages.get_source_collection_stage_task_context
    assert facade.seed_source_collection_agent_session_context is stages.seed_source_collection_agent_session_context
    assert (
        facade.reconcile_source_collection_stage_session_task_after_turn
        is stages.reconcile_source_collection_stage_session_task_after_turn
    )
    assert facade.open_source_collection_storage_target is storage.open_source_collection_storage_target


def test_facade_reexports_experiment_and_research_loop_packs() -> None:
    assert facade.create_experiment_plan is experiment.create_experiment_plan
    assert facade.run_experiment_smoke_run is experiment.run_experiment_smoke_run
    assert facade.execute_experiment_full_run is experiment.execute_experiment_full_run
    assert facade.get_experiment_planning_status is experiment.get_experiment_planning_status
    assert facade.start_research_stage_round is research_loop.start_research_stage_round
    assert facade.get_research_stage_round_status is research_loop.get_research_stage_round_status
    assert facade.retry_research_stage_round_coordination is research_loop.retry_research_stage_round_coordination


def test_get_orchestration_rejects_blank_team_id() -> None:
    try:
        facade.get_team_workflow_orchestration("  ")
        raised = False
    except facade.TeamWorkflowOrchestrationError:
        raised = True
    assert raised
