"""Source-collection storage open target entrypoint.

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable during P0 mechanical splits.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def open_source_collection_storage_target(team_id: str, run_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._normalize_required_id(run_id, "Data processing run id is required.")
    s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    target = s._trim_text(request_payload.get("target"), max_length=80).lower() or "run_directory"
    if target not in s.SOURCE_COLLECTION_STORAGE_OPEN_TARGETS:
        raise s.TeamWorkflowOrchestrationError(f"Unsupported source collection storage target: {target or '<empty>'}")
    try:
        run = s.data_processing_service.get_processing_run(normalized_run_id)
    except s.data_processing_service.DataProcessingError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = s._trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != normalized_team_id:
        raise s.TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")
    target_path = s._source_collection_storage_target_path(normalized_team_id, normalized_run_id, target)
    if target in {"run_directory", "artifacts_directory"}:
        target_path.mkdir(parents=True, exist_ok=True)
        opened_path = target_path
        target_exists = True
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_exists = target_path.exists()
        opened_path = target_path if target_exists else target_path.parent
    s._ensure_project_child(opened_path)
    s._open_local_path(opened_path)
    storage_artifacts = s._source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    s._record_workflow_event(
        "source_collection.storage_opened",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "target": target,
            "path": s._relative_path(target_path),
            "openedPath": s._relative_path(opened_path),
            "targetExists": target_exists,
        },
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "target": target,
        "path": s._relative_path(target_path),
        "openedPath": s._relative_path(opened_path),
        "targetExists": target_exists,
        "storageArtifacts": storage_artifacts,
    }
