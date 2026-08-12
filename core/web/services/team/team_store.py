"""Team store IO, paths, locks, and small shared helpers.

Claim scope: teams index load/save, JSON file helpers, teams workspace paths,
team lock acquire/release, relative path projection, and id/validation helpers.
Late-binds ``team_service`` for PROJECT_ROOT, SCHEMA_VERSION, locks, and errors.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from core.infrastructure import developer_sandbox
from core.logging import debug as _debug_logger

from .. import project_agent_bus_service


def _service():
    from core.web.services import team_service

    return team_service


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _perf_counter() -> float:
    return perf_counter()


def _elapsed_ms(started_at: float) -> int:
    s = _service()
    return max(0, int(round((s._perf_counter() - started_at) * 1000)))


def _try_acquire_team_lock() -> bool:
    s = _service()
    try:
        return bool(s._TEAM_LOCK.acquire(blocking=False))
    except TypeError:
        return bool(s._TEAM_LOCK.acquire(False))


def _release_team_lock_if_acquired(acquired: bool) -> None:
    s = _service()
    if acquired:
        s._TEAM_LOCK.release()


def _load_index() -> dict[str, Any]:
    s = _service()
    path = s._teams_index_path()
    if not path.exists():
        return {"schemaVersion": s.SCHEMA_VERSION, "updatedAt": s.utc_now_iso(), "teams": []}
    try:
        data = s._read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        _debug_logger.warning(f"Failed to read Team index. path={path} error={type(exc).__name__}: {exc}")
        return {"schemaVersion": s.SCHEMA_VERSION, "updatedAt": s.utc_now_iso(), "teams": []}
    return data if isinstance(data, dict) else {"schemaVersion": s.SCHEMA_VERSION, "updatedAt": s.utc_now_iso(), "teams": []}


def _save_index(state: dict[str, Any]) -> None:
    s = _service()
    s._write_json(s._teams_index_path(), state)


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _teams_root() -> Path:
    s = _service()
    return developer_sandbox.seeded_sandbox_workspace_path(s._project_root(), "teams")


def _teams_index_path() -> Path:
    s = _service()
    return s._teams_root() / "teams.json"


def _team_canvas_path(team_id: str) -> Path:
    s = _service()
    return s._teams_root() / s._safe_token(team_id, default="team", max_length=96) / "canvas.json"


def _project_root() -> Path:
    s = _service()
    root = Path(s.PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _sync_project_bus_root() -> None:
    s = _service()
    if project_agent_bus_service.PROJECT_ROOT != s.PROJECT_ROOT:
        project_agent_bus_service.PROJECT_ROOT = s.PROJECT_ROOT


def _relative_path(path: Path) -> str:
    s = _service()
    resolved = path.resolve()
    workspace_root = developer_sandbox.formal_workspace_path(s._project_root()).resolve()
    try:
        return f"workspace/{resolved.relative_to(workspace_root).as_posix()}"
    except ValueError:
        pass
    sandbox_root = developer_sandbox.sandbox_workspace_path(s._project_root())
    if sandbox_root is not None:
        try:
            return f"workspace/{resolved.relative_to(sandbox_root.resolve()).as_posix()}"
        except ValueError:
            pass
    try:
        return str(resolved.relative_to(s._project_root())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _find_team(state: dict[str, Any], team_id: str) -> dict[str, Any] | None:
    for item in list(state.get("teams") or []):
        if isinstance(item, dict) and str(item.get("teamId") or "").strip() == team_id:
            return item
    return None


def _normalize_required_id(value: str, message: str) -> str:
    s = _service()
    normalized = s._safe_token(value, default="", max_length=96)
    if not normalized:
        raise s.TeamServiceError(message)
    return normalized


def _format_validation_error(validation: dict[str, Any]) -> str:
    issues = validation.get("issues") if isinstance(validation.get("issues"), list) else []
    details = "; ".join(str(item.get("message") or item.get("code") or "") for item in issues[:3] if isinstance(item, dict))
    return f"Team canvas contract invalid: {details or 'unknown validation error'}"
