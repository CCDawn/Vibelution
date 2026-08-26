"""Agent-facing tools for the memory-library GitHub project index.

Clone is the GitHub default-branch tip at depth 1 (no history, no submodules).
"""

from __future__ import annotations

import json
from typing import Any

from core.chat.chat_task_types import trim_lines

GITHUB_PROJECT_LIBRARY_SEARCH_TOOL_NAME = "github_project_library_search_tool"
GITHUB_PROJECT_LIBRARY_CLONE_TOOL_NAME = "github_project_library_clone_tool"


def github_project_library_search_tool(query: str = "", limit: int = 12) -> str:
    """
    Search the local memory-library GitHub project index before implementing a
    non-trivial or unfamiliar feature.

    Multiword Chinese or English capability queries are ranked over project
    metadata and a bounded local README token index. Results are discovery
    cards with relevance explanations, never repository bodies. Compare the
    best-fitting candidates, then inspect exact files in the fixed local clone
    before treating a project as implementation evidence.
    """

    runtime = _current_runtime()
    try:
        from core.web.services import github_project_library_service

        payload = github_project_library_service.list_github_projects(
            query=trim_lines(str(query or ""), max_lines=2).strip(),
        )
        projects = list(payload.get("projects") or [])[: max(1, min(int(limit or 12), 25))]
        _record_event(
            "github_project_library.tool.search.succeeded",
            runtime=runtime,
            fields={"resultCount": len(projects), "queryLength": len(str(query or ""))},
        )
        return _json_result(
            {
                "ok": True,
                "status": "succeeded",
                "summary": payload.get("summary") or {},
                "projects": projects,
                "indexPath": payload.get("indexPath") or "",
                "hint": (
                    "按 searchScore 和 matchedTerms 选择最贴合的候选，再读取 localPath/absolutePath "
                    "下固定 HEAD 的具体文件；不要把项目卡、README token 或网页摘要当实现结论。"
                ),
            }
        )
    except Exception as exc:
        _record_event(
            "github_project_library.tool.search.failed",
            runtime=runtime,
            level="error",
            outcome="failed",
            fields={"errorType": type(exc).__name__},
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
            }
        )


def github_project_library_clone_tool(
    repo: str,
    confirm: bool = False,
    action: str = "clone",
) -> str:
    """
    Clone a high-value public GitHub repo into the memory library, or fetch an existing clone.

    Clone first, then research the local copy. Depth-1 default branch only, no submodules.
    confirmation_required means ask the user before retrying with confirm=true.
    """

    runtime = _current_runtime()
    normalized_action = str(action or "clone").strip().lower() or "clone"
    try:
        from core.web.services import github_project_library_service

        if normalized_action == "fetch":
            payload = github_project_library_service.fetch_github_project(str(repo or "").strip())
        else:
            payload = github_project_library_service.clone_github_project(
                str(repo or "").strip(),
                confirm=bool(confirm),
            )
        _record_event(
            "github_project_library.tool.clone.succeeded",
            runtime=runtime,
            fields={"action": normalized_action, "status": str(payload.get("status") or "")},
        )
        return _json_result(payload)
    except Exception as exc:
        _record_event(
            "github_project_library.tool.clone.failed",
            runtime=runtime,
            level="error",
            outcome="failed",
            fields={"errorType": type(exc).__name__, "action": normalized_action},
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=3),
            }
        )


def _current_runtime() -> dict[str, Any]:
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
        return runtime if isinstance(runtime, dict) else {}
    except Exception:
        return {}


def _record_event(
    event_code: str,
    *,
    runtime: dict[str, Any],
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            event_code,
            level=level,
            outcome=outcome,
            agent_id=str(runtime.get("agentId") or ""),
            fields=fields or {},
        )
    except Exception:
        return


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
