# -*- coding: utf-8 -*-
"""Controlled source-collection stage tools for Challenge Cup Agents."""

from __future__ import annotations

import json
import re
import time
from collections import OrderedDict
from threading import RLock
from typing import Any


_SOURCE_CONTEXT_CACHE_TTL_SECONDS = 60.0
_SOURCE_CONTEXT_CACHE_MAX_ENTRIES = 128
_SOURCE_CONTEXT_CACHE_LOCK = RLock()
_SOURCE_CONTEXT_CACHE: OrderedDict[tuple[Any, ...], tuple[float, str]] = OrderedDict()


def _source_context_cache_get(key: tuple[Any, ...]) -> dict[str, Any] | None:
    now = time.monotonic()
    with _SOURCE_CONTEXT_CACHE_LOCK:
        cached = _SOURCE_CONTEXT_CACHE.get(key)
        if cached is None:
            return None
        stored_at, serialized = cached
        if now - stored_at > _SOURCE_CONTEXT_CACHE_TTL_SECONDS:
            _SOURCE_CONTEXT_CACHE.pop(key, None)
            return None
        _SOURCE_CONTEXT_CACHE.move_to_end(key)
    payload = json.loads(serialized)
    return payload if isinstance(payload, dict) else None


def _source_context_cache_put(key: tuple[Any, ...], payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with _SOURCE_CONTEXT_CACHE_LOCK:
        _SOURCE_CONTEXT_CACHE[key] = (time.monotonic(), serialized)
        _SOURCE_CONTEXT_CACHE.move_to_end(key)
        while len(_SOURCE_CONTEXT_CACHE) > _SOURCE_CONTEXT_CACHE_MAX_ENTRIES:
            _SOURCE_CONTEXT_CACHE.popitem(last=False)


def _invalidate_source_context_cache(*, team_id: str, task_id: str) -> None:
    normalized_team_id = _text(team_id)
    normalized_task_id = _text(task_id)
    with _SOURCE_CONTEXT_CACHE_LOCK:
        stale_keys = [
            key
            for key in _SOURCE_CONTEXT_CACHE
            if (not normalized_team_id or key[0] == normalized_team_id)
            and (not normalized_task_id or key[3] == normalized_task_id)
        ]
        for key in stale_keys:
            _SOURCE_CONTEXT_CACHE.pop(key, None)


def _text(value: Any) -> str:
    return str(value or "").strip()


def source_collection_context_tool(
    team_id: str = "",
    run_id: str = "",
    stage_id: str = "",
    task_id: str = "",
    max_records: int = 5,
    include_candidates: bool = True,
    record_offset: int = 0,
    record_limit: int = 5,
    candidate_offset: int = 0,
    candidate_limit: int = 5,
    context_mode: str = "compact",
) -> str:
    """Return paged source-collection task context without exposing local file access.

    Excluded sources are removed from records and summarized in excludedSourceSummary.
    """

    try:
        from core.web.services import team_workflow_orchestration_service as workflow_service

        resolved_team_id, resolution = _resolve_source_collection_team_id(
            team_id=team_id,
            run_id=run_id,
            task_id=task_id,
        )
        cache_key = (
            _text(resolved_team_id),
            _text(run_id),
            _text(stage_id),
            _text(task_id),
            int(max_records),
            bool(include_candidates),
            int(record_offset),
            int(record_limit),
            int(candidate_offset),
            int(candidate_limit),
            _text(context_mode).lower(),
        )
        payload = _source_context_cache_get(cache_key)
        cache_hit = payload is not None
        if payload is None:
            payload = workflow_service.get_source_collection_stage_task_context(
                resolved_team_id,
                run_id=run_id,
                stage_id=stage_id,
                task_id=task_id,
                max_records=max_records,
                include_candidates=include_candidates,
                record_offset=record_offset,
                record_limit=record_limit or None,
                candidate_offset=candidate_offset,
                candidate_limit=candidate_limit or None,
                context_mode=context_mode,
            )
            if isinstance(payload, dict):
                _source_context_cache_put(cache_key, payload)
        if isinstance(payload, dict) and resolution:
            payload.setdefault("toolResolution", resolution)
        _record_stage_tool_event(
            "tool.source_collection_context.completed",
            outcome="completed",
            fields={
                "teamId": resolved_team_id,
                "runId": _text(payload.get("runId")) if isinstance(payload, dict) else _text(run_id),
                "stageId": _text(payload.get("stageId")) if isinstance(payload, dict) else _text(stage_id),
                "taskId": _text(payload.get("taskId")) if isinstance(payload, dict) else _text(task_id),
                "recordCount": _safe_count((payload.get("counts") or {}).get("recordCount")) if isinstance(payload, dict) else 0,
                "excludedSourceCount": _safe_count((payload.get("counts") or {}).get("excludedSourceCount")) if isinstance(payload, dict) else 0,
                "returnedRecordCount": _safe_count((payload.get("counts") or {}).get("returnedRecordCount")) if isinstance(payload, dict) else 0,
                "recordOffset": _safe_count(((payload.get("recordPage") or {}) if isinstance(payload, dict) else {}).get("offset")),
                "recordLimit": _safe_count(((payload.get("recordPage") or {}) if isinstance(payload, dict) else {}).get("limit")),
                "candidateCount": _safe_count((payload.get("counts") or {}).get("candidateCount")) if isinstance(payload, dict) else 0,
                "returnedCandidateCount": _safe_count((payload.get("counts") or {}).get("returnedCandidateCount")) if isinstance(payload, dict) else 0,
                "candidateOffset": _safe_count(((payload.get("candidatePage") or {}) if isinstance(payload, dict) else {}).get("offset")),
                "candidateLimit": _safe_count(((payload.get("candidatePage") or {}) if isinstance(payload, dict) else {}).get("limit")),
                "contextMode": _text(payload.get("contextMode")) if isinstance(payload, dict) else _text(context_mode),
                "teamIdSource": _text(resolution.get("teamIdSource")) if resolution else "",
                "cacheHit": cache_hit,
            },
        )
    except Exception as exc:
        _record_stage_tool_event(
            "tool.source_collection_context.failed",
            level="warning",
            outcome="failed",
            fields={
                "teamId": _text(team_id),
                "runId": _text(run_id),
                "stageId": _text(stage_id),
                "taskId": _text(task_id),
                "errorType": type(exc).__name__,
            },
        )
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
    """Write structured stage results; server gates own any formal materialization.

    ``result_json`` contains the stage result object. Its fields must not be
    expanded into top-level tool arguments.
    """

    # All parameters are optional in the signature, so executor-side signature
    # binding cannot reject an empty-arguments call (e.g. streaming arguments
    # loss). An empty writeback target must fail closed instead of silently
    # writing an empty result into the team workflow.
    if not _text(team_id) and not _text(task_id):
        _record_stage_tool_event(
            "tool.source_collection_stage_writeback.failed",
            level="warning",
            outcome="failed",
            fields={
                "teamId": "",
                "taskId": "",
                "status": _text(status),
                "recordedByAgent": _text(recorded_by_agent),
                "errorType": "missing_writeback_target",
            },
        )
        return json.dumps(
            {
                "status": "error",
                "errorType": "missing_writeback_target",
                "message": (
                    "[工具参数错误] source_collection_stage_writeback_tool 收到空参数："
                    "回写必须指向具体的阶段任务，请携带 team_id 与 task_id（以及 result_json）重试。"
                ),
                "teamId": "",
                "taskId": "",
                "recovery": _source_collection_context_recovery_hint(
                    team_id="",
                    task_id="",
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

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
        _invalidate_source_context_cache(team_id=resolved_team_id, task_id=task_id)
        compact_response = _compact_source_collection_stage_writeback_response(response, payload)
        _record_stage_tool_event(
            "tool.source_collection_stage_writeback.completed",
            outcome="completed",
            fields={
                "teamId": resolved_team_id,
                "runId": _text(response.get("runId")) if isinstance(response, dict) else "",
                "stageId": _text(response.get("stageId")) if isinstance(response, dict) else "",
                "taskId": _text(task_id),
                "status": _text(status),
                "recordedByAgent": _text(recorded_by_agent),
                "evidenceRefCount": len(payload["evidenceRefs"]),
                "nextActionCount": len(payload["nextActions"]),
                "responseBytes": len(json.dumps(compact_response, ensure_ascii=False)),
                "teamIdSource": _text(resolution.get("teamIdSource")) if resolution else "",
            },
        )
    except Exception as exc:
        _record_stage_tool_event(
            "tool.source_collection_stage_writeback.failed",
            level="warning",
            outcome="failed",
            fields={
                "teamId": _text(team_id),
                "taskId": _text(task_id),
                "status": _text(status),
                "recordedByAgent": _text(recorded_by_agent),
                "errorType": type(exc).__name__,
            },
        )
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
    return json.dumps(compact_response, ensure_ascii=False, indent=2, sort_keys=True)


def _compact_source_collection_stage_writeback_response(response: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    writeback = response.get("writeback") if isinstance(response.get("writeback"), dict) else {}
    task = response.get("task") if isinstance(response.get("task"), dict) else {}
    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    closure_summary = writeback.get("closureSummary") if isinstance(writeback.get("closureSummary"), dict) else {}
    return {
        "schemaVersion": response.get("schemaVersion", 1),
        "status": _text(writeback.get("status") or task.get("status") or payload.get("status")),
        "requestedStatus": _text(writeback.get("agentRequestedStatus") or payload.get("status")),
        "teamId": _text(response.get("teamId")),
        "runId": _text(response.get("runId")),
        "taskId": _text(response.get("taskId") or task.get("taskId")),
        "stageId": _text(response.get("stageId") or task.get("stageId")),
        "agentId": _text(response.get("agentId") or task.get("agentId")),
        "agentRole": _text(response.get("agentRole") or task.get("agentRole")),
        "summary": _text(writeback.get("summary") or payload.get("summary"))[:600],
        "coverageSummary": _compact_count_summary(writeback.get("coverageSummary") or result.get("coverageSummary")),
        "materializedSources": _compact_count_summary(writeback.get("materializedSources") or result.get("materializedSources")),
        "materializedContentExtraction": _compact_count_summary(
            writeback.get("materializedContentExtraction") or result.get("materializedContentExtraction")
        ),
        "materializedSourceQuality": _compact_count_summary(writeback.get("materializedSourceQuality") or result.get("materializedSourceQuality")),
        "materializedCandidateGraph": _compact_count_summary(
            writeback.get("materializedCandidateGraph") or result.get("materializedCandidateGraph")
        ),
        "materializedKnowledgeIngestion": _compact_count_summary(
            writeback.get("materializedKnowledgeIngestion") or result.get("materializedKnowledgeIngestion")
        ),
        "closureSummary": _compact_count_summary(closure_summary),
        "completionGate": closure_summary.get("completionGate") if isinstance(closure_summary.get("completionGate"), dict) else {},
        "evidenceRefCount": len(payload.get("evidenceRefs") or []),
        "nextActionCount": len(payload.get("nextActions") or []),
        "nextStep": "Use source_collection_context_tool for details if another page or retry is needed.",
    }


def _compact_count_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compact: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"message", "nextAction", "retryInstruction", "instructions", "guidance"}:
            continue
        if isinstance(item, str) and len(item) > 240:
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            compact[key] = item
    return compact


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


def _record_stage_tool_event(
    event_code: str,
    *,
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any],
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "tool",
            "source_collection_stage",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields=fields,
            lifecycle=level in {"warning", "error"},
        )
    except Exception:
        return


def _safe_count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    parsed = _parse_json_object_text(text)
    if parsed is not None:
        return parsed
    extracted = _extract_json_object_text(text)
    if extracted:
        parsed = _parse_json_object_text(extracted)
        if parsed is not None:
            parsed.setdefault("_structuredResultRecoveredFromText", True)
            return parsed
    return {"text": text}


def _parse_json_object_text(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        nested = _extract_json_object_text(parsed) or parsed.strip()
        if nested and nested != text:
            return _parse_json_object_text(nested)
    return {"value": parsed}


def _extract_json_object_text(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        candidate = text[match.start():]
        try:
            parsed, end_index = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return candidate[:end_index].strip()
    return ""


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
