"""Bulk Agent edit orchestration helpers."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from .agent_directory_service import (
    AgentDirectoryError,
    AgentNotFoundError,
    get_agent,
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
