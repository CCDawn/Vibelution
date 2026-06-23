# -*- coding: utf-8 -*-
"""Controlled source-collection stage tools for Challenge Cup Agents."""

from __future__ import annotations

import json
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def source_collection_context_tool(
    team_id: str = "",
    run_id: str = "",
    stage_id: str = "",
    task_id: str = "",
    max_records: int = 24,
    include_candidates: bool = True,
) -> str:
    """Return bounded source-collection task context without exposing local file access."""

    try:
        from core.web.services import team_workflow_orchestration_service as workflow_service

        resolved_team_id, resolution = _resolve_source_collection_team_id(
            team_id=team_id,
            run_id=run_id,
            task_id=task_id,
        )
        payload = workflow_service.get_source_collection_stage_task_context(
            resolved_team_id,
            run_id=run_id,
            stage_id=stage_id,
            task_id=task_id,
            max_records=max_records,
            include_candidates=include_candidates,
        )
        if isinstance(payload, dict) and resolution:
            payload.setdefault("toolResolution", resolution)
    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                "errorType": type(exc).__name__,
                "message": str(exc),
                "teamId": _text(team_id),
                "runId": _text(run_id),
                "taskId": _text(task_id),
                "recovery": _source_collection_context_recovery_hint(
                    team_id=team_id,
                    run_id=run_id,
                    task_id=task_id,
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def source_collection_stage_writeback_tool(
    team_id: str = "",
    task_id: str = "",
    status: str = "completed",
    summary: str = "",
    result_json: str = "",
    evidence_refs_json: str = "",
    next_actions_json: str = "",
    recorded_by_agent: str = "",
    metadata_json: str = "",
) -> str:
    """Write structured stage task results back to the team workflow."""

    try:
        from core.web.services import team_workflow_orchestration_service as workflow_service

        resolved_team_id, resolution = _resolve_source_collection_team_id(
            team_id=team_id,
            task_id=task_id,
        )
        payload = {
            "status": status,
            "summary": summary,
            "result": _json_object(result_json),
            "evidenceRefs": _json_list(evidence_refs_json),
            "nextActions": _json_list(next_actions_json),
            "recordedByAgent": recorded_by_agent,
            "metadata": _json_object(metadata_json),
        }
        if resolution:
            metadata = dict(payload.get("metadata") or {})
            metadata.setdefault("toolResolution", resolution)
            payload["metadata"] = metadata
        response = workflow_service.writeback_source_collection_stage_session_task(resolved_team_id, task_id, payload)
    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                "errorType": type(exc).__name__,
                "message": str(exc),
                "teamId": str(team_id or "").strip(),
                "taskId": str(task_id or "").strip(),
                "recovery": _source_collection_context_recovery_hint(
                    team_id=team_id,
                    task_id=task_id,
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True)


def _resolve_source_collection_team_id(
    *,
    team_id: str = "",
    run_id: str = "",
    task_id: str = "",
) -> tuple[str, dict[str, Any]]:
    normalized_team_id = _text(team_id)
    if normalized_team_id:
        return normalized_team_id, {}

    normalized_run_id = _text(run_id)
    if normalized_run_id:
        run_team_id = _team_id_from_run(normalized_run_id)
        if run_team_id:
            return run_team_id, {
                "teamIdSource": "data_processing_run",
                "runId": normalized_run_id,
            }

    normalized_task_id = _text(task_id)
    if normalized_task_id:
        task_match = _team_id_from_stage_task(normalized_task_id)
        if task_match.get("teamId"):
            return str(task_match["teamId"]), {
                "teamIdSource": "source_collection_stage_task",
                "taskId": normalized_task_id,
                "runId": str(task_match.get("runId") or ""),
            }

    return normalized_team_id, {}


def _team_id_from_run(run_id: str) -> str:
    try:
        from core.web.services import data_processing_service

        run = data_processing_service.get_processing_run(run_id)
    except Exception:
        return ""
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    return _text(scope.get("teamId") or metadata.get("teamId"))


def _team_id_from_stage_task(task_id: str) -> dict[str, str]:
    try:
        from core.web.services import team_service
        from core.web.services import team_workflow_orchestration_service as workflow_service
    except Exception:
        return {}

    try:
        teams_payload = team_service.list_teams(include_archived=True)
    except Exception:
        teams_payload = {}
    teams = teams_payload.get("teams") if isinstance(teams_payload, dict) else []
    for team in list(teams or []):
        if not isinstance(team, dict):
            continue
        candidate_team_id = _text(team.get("teamId"))
        if not candidate_team_id:
            continue
        try:
            payload = workflow_service.get_source_collection_stage_task_context(
                candidate_team_id,
                task_id=task_id,
                max_records=1,
                include_candidates=False,
            )
        except Exception:
            continue
        if isinstance(payload, dict) and _text(payload.get("taskId")) == task_id:
            return {
                "teamId": _text(payload.get("teamId") or candidate_team_id),
                "runId": _text(payload.get("runId")),
            }
    return {}


def _source_collection_context_recovery_hint(
    *,
    team_id: str = "",
    run_id: str = "",
    task_id: str = "",
) -> str:
    if not _text(team_id):
        if _text(run_id):
            inferred = _team_id_from_run(_text(run_id))
            if inferred:
                return f"Retry with team_id={inferred!r}; this was inferred from the data processing run."
        if _text(task_id):
            match = _team_id_from_stage_task(_text(task_id))
            if match.get("teamId"):
                return f"Retry with team_id={str(match['teamId'])!r}; this was inferred from the stage task."
        return "Provide team_id from the stage task message. If run_id is available, use the run's scope.teamId; for Challenge Cup source collection this is usually 'research-team'."
    return "Use source_collection_stage_writeback_tool with status=blocked if this context is required to finish the stage task."


def _json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {"text": text}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _json_list(raw: str) -> list[Any]:
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return [item.strip() for item in text.splitlines() if item.strip()]
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return [parsed]
    return [parsed]
