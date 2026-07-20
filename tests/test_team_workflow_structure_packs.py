"""Focused tests for team_workflow structure packs (Stage 3)."""

from __future__ import annotations

from core.web.services import team_workflow_orchestration_service as facade
from core.web.services.team_workflow import orchestration_core
from core.web.services.team_workflow.source_collection import candidates, runs


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


def test_get_orchestration_rejects_blank_team_id() -> None:
    try:
        facade.get_team_workflow_orchestration("  ")
        raised = False
    except facade.TeamWorkflowOrchestrationError:
        raised = True
    assert raised
