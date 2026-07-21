"""Focused tests for runtime_scene structure packs (record/query/diagnosis)."""

from __future__ import annotations

from core.web.services import runtime_scene_service as facade
from core.web.services.runtime_scene import diagnosis, package_index, query, record


def test_facade_reexports_record_pack() -> None:
    assert facade.record_runtime_scene_event is record.record_runtime_scene_event
    assert facade.record_runtime_scene_conversation_event is record.record_runtime_scene_conversation_event
    assert facade.record_backend_api_event is record.record_backend_api_event
    assert facade.record_browser_telemetry is record.record_browser_telemetry
    assert facade.record_research_scene_event is record.record_research_scene_event
    assert facade.record_electron_supervisor_event is record.record_electron_supervisor_event
    assert facade.delete_runtime_scenes is record.delete_runtime_scenes


def test_facade_reexports_query_pack() -> None:
    assert facade.list_runtime_scenes is query.list_runtime_scenes
    assert facade.get_runtime_scene_detail is query.get_runtime_scene_detail
    assert facade.read_runtime_scene_file is query.read_runtime_scene_file
    assert facade.list_runtime_scene_evidence_for_agent is query.list_runtime_scene_evidence_for_agent
    assert facade.build_runtime_scene_prompt_index is query.build_runtime_scene_prompt_index


def test_facade_reexports_diagnosis_pack() -> None:
    assert facade._runtime_scene_package_diagnosis is diagnosis._runtime_scene_package_diagnosis
    assert facade._runtime_scene_agent_brief is diagnosis._runtime_scene_agent_brief
    assert facade._runtime_scene_issue_state is diagnosis._runtime_scene_issue_state
    assert facade._runtime_scene_key_entries is diagnosis._runtime_scene_key_entries
    assert facade._fold_repeated_work_run_snapshots is diagnosis._fold_repeated_work_run_snapshots
    assert facade._runtime_scene_diagnosis_next_step is diagnosis._runtime_scene_diagnosis_next_step


def test_facade_reexports_package_index_pack() -> None:
    assert (
        facade._sync_runtime_scene_package_index_if_stale
        is package_index._sync_runtime_scene_package_index_if_stale
    )
    assert (
        facade._runtime_scene_package_index_sidecar_is_stale
        is package_index._runtime_scene_package_index_sidecar_is_stale
    )
    assert (
        facade._update_runtime_scene_manifest_package_index_fields
        is package_index._update_runtime_scene_manifest_package_index_fields
    )
