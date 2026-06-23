# -*- coding: utf-8 -*-
"""Controlled source-collection stage tools for Challenge Cup Agents."""

from __future__ import annotations

import json
from typing import Any


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

        payload = workflow_service.get_source_collection_stage_task_context(
            team_id,
            run_id=run_id,
            stage_id=stage_id,
            task_id=task_id,
            max_records=max_records,
            include_candidates=include_candidates,
        )
    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                "errorType": type(exc).__name__,
                "message": str(exc),
                "recovery": "Use source_collection_stage_writeback_tool with status=blocked if this context is required to finish the stage task.",
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

        payload = {
            "status": status,
            "summary": summary,
            "result": _json_object(result_json),
            "evidenceRefs": _json_list(evidence_refs_json),
            "nextActions": _json_list(next_actions_json),
            "recordedByAgent": recorded_by_agent,
            "metadata": _json_object(metadata_json),
        }
        response = workflow_service.writeback_source_collection_stage_session_task(team_id, task_id, payload)
    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                "errorType": type(exc).__name__,
                "message": str(exc),
                "teamId": str(team_id or "").strip(),
                "taskId": str(task_id or "").strip(),
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True)


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
