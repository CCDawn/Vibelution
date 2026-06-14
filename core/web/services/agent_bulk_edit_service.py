"""Bulk Agent edit orchestration helpers."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from .agent_directory_service import (
    AgentDirectoryError,
    AgentNotFoundError,
    agent_archive_protected,
    get_agent,
    normalize_agent_llm_bindings,
    update_agent_instance,
)
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _dedupe_agent_ids(agent_ids: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in list(agent_ids or []):
        agent_id = str(item or "").strip()
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        deduped.append(agent_id)
    return deduped


def _status(success_count: int, skipped_count: int, failed_count: int) -> str:
    if failed_count:
        return "partial_failed" if success_count or skipped_count else "failed"
    return "completed"


def _summary(requested_count: int, success: list[dict[str, Any]], skipped: list[dict[str, Any]], failed: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "requestedCount": requested_count,
        "successCount": len(success),
        "skippedCount": len(skipped),
        "failedCount": len(failed),
    }


def _skip_item(agent_id: str, reason: str, message: str) -> dict[str, str]:
    return {"agentId": agent_id, "reason": reason, "message": message}


def _failed_item(agent_id: str, reason: str, message: str) -> dict[str, str]:
    return {"agentId": agent_id, "reason": reason, "message": message}


_BULK_CONFIG_FIELDS = {
    "llmBindings",
    "promptTemplateId",
    "primaryMode",
    "roleKey",
    "personaProfile",
    "taskProfile",
}
_IDENTITY_FIELDS = {"primaryMode", "roleKey", "personaProfile", "taskProfile"}


def _clean_apply_fields(apply_fields: list[str] | None, patch: dict[str, Any]) -> list[str]:
    requested = [
        str(item or "").strip()
        for item in list(apply_fields or [])
        if str(item or "").strip()
    ]
    if not requested:
        requested = [field for field in _BULK_CONFIG_FIELDS if field in patch]
    deduped: list[str] = []
    seen: set[str] = set()
    for field in requested:
        if field not in _BULK_CONFIG_FIELDS or field in seen or field not in patch:
            continue
        seen.add(field)
        deduped.append(field)
    return deduped


def _merged_llm_bindings(agent: dict[str, Any], patch_bindings: Any) -> dict[str, Any]:
    current = normalize_agent_llm_bindings(agent.get("llmBindings"))
    updates = normalize_agent_llm_bindings(patch_bindings)
    for slot, binding in updates.items():
        model_id = str((binding or {}).get("modelId") or "").strip()
        if model_id:
            current[slot] = {"modelId": model_id}
        else:
            current.pop(slot, None)
    return current


def _bulk_update_kwargs(agent: dict[str, Any], patch: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if "llmBindings" in fields:
        kwargs["llm_bindings"] = _merged_llm_bindings(agent, patch.get("llmBindings"))
    if "promptTemplateId" in fields:
        kwargs["prompt_template_id"] = str(patch.get("promptTemplateId") or "").strip()
    if "primaryMode" in fields:
        kwargs["primary_mode"] = str(patch.get("primaryMode") or "").strip()
    if "roleKey" in fields:
        kwargs["role_key"] = str(patch.get("roleKey") or "").strip()
    if "personaProfile" in fields:
        kwargs["persona_profile"] = patch.get("personaProfile") if isinstance(patch.get("personaProfile"), dict) else {}
    if "taskProfile" in fields:
        kwargs["task_profile"] = patch.get("taskProfile") if isinstance(patch.get("taskProfile"), dict) else {}
    return kwargs


def bulk_update_agent_config(agent_ids: list[str] | None, patch: dict[str, Any] | None, apply_fields: list[str] | None = None) -> dict[str, Any]:
    """Apply selected safe configuration fields to many active Agents."""

    requested_agent_ids = _dedupe_agent_ids(agent_ids)
    patch_payload = dict(patch or {})
    fields = _clean_apply_fields(apply_fields, patch_payload)
    if not fields:
        raise AgentDirectoryError("At least one bulk Agent config field is required.")

    started_at = perf_counter()
    success: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    identity_update = any(field in _IDENTITY_FIELDS for field in fields)
    for agent_id in requested_agent_ids:
        try:
            agent = get_agent(agent_id, include_archived=True)
            if not agent:
                skipped.append(_skip_item(agent_id, "not_found", f"Agent not found: {agent_id}"))
                continue
            if str(agent.get("status") or "active").strip() == "archived":
                skipped.append(_skip_item(agent_id, "archived", "Archived Agent cannot be updated."))
                continue
            if identity_update and agent_archive_protected(agent):
                skipped.append(_skip_item(agent_id, "protected_identity", "Protected system Agent identity cannot be bulk edited."))
                continue
            updated = update_agent_instance(agent_id, **_bulk_update_kwargs(agent, patch_payload, fields))
            success.append(updated)
        except AgentDirectoryError as exc:
            failed.append(_failed_item(agent_id, "invalid", str(exc)))
        except AgentNotFoundError as exc:
            skipped.append(_skip_item(agent_id, "not_found", str(exc)))
        except Exception as exc:
            failed.append(_failed_item(agent_id, type(exc).__name__, str(exc)))

    result = {
        "status": _status(len(success), len(skipped), len(failed)),
        "requestedAgentIds": requested_agent_ids,
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "summary": _summary(len(requested_agent_ids), success, skipped, failed),
        "appliedFields": fields,
        "durationMs": round((perf_counter() - started_at) * 1000, 3),
    }
    _record_bulk_config_update_event(result)
    return result


def bulk_update_agent_prompt_template(agent_ids: list[str] | None, prompt_template_id: str) -> dict[str, Any]:
    """Apply one prompt template to many active Agents."""

    requested_agent_ids = _dedupe_agent_ids(agent_ids)
    normalized_template_id = str(prompt_template_id or "").strip()
    if not normalized_template_id:
        raise AgentDirectoryError("Prompt template id is required.")

    started_at = perf_counter()
    success: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for agent_id in requested_agent_ids:
        try:
            agent = get_agent(agent_id, include_archived=True)
            if not agent:
                skipped.append(_skip_item(agent_id, "not_found", f"Agent not found: {agent_id}"))
                continue
            if str(agent.get("status") or "active").strip() == "archived":
                skipped.append(_skip_item(agent_id, "archived", "Archived Agent cannot be updated."))
                continue
            updated = update_agent_instance(agent_id, prompt_template_id=normalized_template_id)
            success.append(updated)
        except AgentDirectoryError as exc:
            failed.append(_failed_item(agent_id, "invalid", str(exc)))
        except AgentNotFoundError as exc:
            skipped.append(_skip_item(agent_id, "not_found", str(exc)))
        except Exception as exc:
            failed.append(_failed_item(agent_id, type(exc).__name__, str(exc)))

    result = {
        "status": _status(len(success), len(skipped), len(failed)),
        "requestedAgentIds": requested_agent_ids,
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "summary": _summary(len(requested_agent_ids), success, skipped, failed),
        "promptTemplateId": normalized_template_id,
        "durationMs": round((perf_counter() - started_at) * 1000, 3),
    }
    _record_bulk_prompt_update_event(result)
    return result


def _record_bulk_prompt_update_event(result: dict[str, Any]) -> None:
    try:
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        record_runtime_scene_event(
            "agent_directory",
            "bulk_edit",
            "agent.bulk_prompt_template.updated",
            message="Bulk Agent prompt template update completed.",
            outcome=str(result.get("status") or "").strip() or "completed",
            fields={
                "promptTemplateId": str(result.get("promptTemplateId") or "").strip(),
                "requestedCount": int(summary.get("requestedCount") or 0),
                "successCount": int(summary.get("successCount") or 0),
                "skippedCount": int(summary.get("skippedCount") or 0),
                "failedCount": int(summary.get("failedCount") or 0),
                "durationMs": float(result.get("durationMs") or 0.0),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_bulk_config_update_event(result: dict[str, Any]) -> None:
    try:
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        record_runtime_scene_event(
            "agent_directory",
            "bulk_edit",
            "agent.bulk_config.updated",
            message="Bulk Agent config update completed.",
            outcome=str(result.get("status") or "").strip() or "completed",
            fields={
                "appliedFields": list(result.get("appliedFields") or []),
                "requestedCount": int(summary.get("requestedCount") or 0),
                "successCount": int(summary.get("successCount") or 0),
                "skippedCount": int(summary.get("skippedCount") or 0),
                "failedCount": int(summary.get("failedCount") or 0),
                "durationMs": float(result.get("durationMs") or 0.0),
            },
            lifecycle=True,
        )
    except Exception:
        return
