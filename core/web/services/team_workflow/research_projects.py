"""Team-scoped research project registry and active workspace resolver."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.web.services import team_service
from core.web.services.runtime_scene_service import record_runtime_scene_event


SCHEMA_VERSION = 1
LEGACY_PROJECT_ID = "legacy-default"
_STORE_LOCK = threading.RLock()


class ResearchProjectError(RuntimeError):
    """Base error for research-project persistence."""


class ResearchProjectNotFoundError(ResearchProjectError):
    """Raised when a team research project does not exist."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _safe_team_id(team_id: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in str(team_id or ""))[:96] or "team"


def team_workspace_root(team_id: str) -> Path:
    return developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_team_id(team_id),
    )


def _store_path(team_id: str) -> Path:
    return team_workspace_root(team_id) / "research_projects" / "index.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _default_project(now: str) -> dict[str, Any]:
    return {
        "projectId": LEGACY_PROJECT_ID,
        "name": "默认研究项目",
        "topic": "",
        "experimentMethod": "",
        "storageMode": "legacy",
        "createdAt": now,
        "updatedAt": now,
    }


def _normalize_project(project: dict[str, Any], *, fallback_now: str) -> dict[str, Any]:
    project_id = str(project.get("projectId") or "").strip()
    storage_mode = "legacy" if project_id == LEGACY_PROJECT_ID else "isolated"
    return {
        "projectId": project_id,
        "name": str(project.get("name") or "未命名研究项目").strip()[:160] or "未命名研究项目",
        "topic": str(project.get("topic") or "").strip()[:1000],
        "experimentMethod": str(project.get("experimentMethod") or "").strip()[:120],
        "storageMode": storage_mode,
        "createdAt": str(project.get("createdAt") or fallback_now),
        "updatedAt": str(project.get("updatedAt") or fallback_now),
    }


def _load_store(team_id: str) -> dict[str, Any]:
    now = _utc_now()
    payload = _read_json(_store_path(team_id))
    raw_projects = payload.get("projects") if isinstance(payload.get("projects"), list) else []
    projects = [
        _normalize_project(item, fallback_now=now)
        for item in raw_projects
        if isinstance(item, dict) and str(item.get("projectId") or "").strip()
    ]
    if not any(item["projectId"] == LEGACY_PROJECT_ID for item in projects):
        projects.insert(0, _default_project(now))
    active_project_id = str(payload.get("activeProjectId") or LEGACY_PROJECT_ID).strip()
    if not any(item["projectId"] == active_project_id for item in projects):
        active_project_id = LEGACY_PROJECT_ID
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": str(team_id),
        "activeProjectId": active_project_id,
        "projects": projects,
        "updatedAt": str(payload.get("updatedAt") or now),
    }


def _persist_store(team_id: str, store: dict[str, Any]) -> None:
    store["updatedAt"] = _utc_now()
    _write_json(_store_path(team_id), store)


def _project_payload(store: dict[str, Any], project_id: str) -> dict[str, Any]:
    for project in store["projects"]:
        if project["projectId"] == project_id:
            return project
    raise ResearchProjectNotFoundError("Research project not found.")


def list_research_projects(team_id: str) -> dict[str, Any]:
    team_service.get_team(team_id)
    with _STORE_LOCK:
        store = _load_store(team_id)
        if not _store_path(team_id).exists():
            _persist_store(team_id, store)
        return store


def create_research_project(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    team_service.get_team(team_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ResearchProjectError("Research project name is required.")
    now = _utc_now()
    with _STORE_LOCK:
        store = _load_store(team_id)
        project = {
            "projectId": f"research-{uuid.uuid4().hex[:12]}",
            "name": name[:160],
            "topic": str(payload.get("topic") or "").strip()[:1000],
            "experimentMethod": str(payload.get("experimentMethod") or "").strip()[:120],
            "storageMode": "isolated",
            "createdAt": now,
            "updatedAt": now,
        }
        store["projects"].append(project)
        _persist_store(team_id, store)
    _record_project_event("research_project.created", team_id, project["projectId"])
    return {"project": project, **store}


def update_research_project(team_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    team_service.get_team(team_id)
    with _STORE_LOCK:
        store = _load_store(team_id)
        project = _project_payload(store, project_id)
        if "name" in payload:
            name = str(payload.get("name") or "").strip()
            if not name:
                raise ResearchProjectError("Research project name is required.")
            project["name"] = name[:160]
        if "topic" in payload and payload.get("topic") is not None:
            project["topic"] = str(payload.get("topic") or "").strip()[:1000]
        if "experimentMethod" in payload and payload.get("experimentMethod") is not None:
            project["experimentMethod"] = str(payload.get("experimentMethod") or "").strip()[:120]
        project["updatedAt"] = _utc_now()
        _persist_store(team_id, store)
    _record_project_event("research_project.updated", team_id, project_id)
    return {"project": project, **store}


def activate_research_project(team_id: str, project_id: str) -> dict[str, Any]:
    team_service.get_team(team_id)
    with _STORE_LOCK:
        store = _load_store(team_id)
        project = _project_payload(store, project_id)
        store["activeProjectId"] = project_id
        _persist_store(team_id, store)
    _record_project_event("research_project.activated", team_id, project_id)
    return {"project": project, **store}


def resolve_team_workflow_root(team_id: str) -> Path:
    """Resolve the canonical workflow root for the team's active research project."""
    with _STORE_LOCK:
        store = _load_store(team_id)
        active_project_id = store["activeProjectId"]
    base_root = team_workspace_root(team_id)
    if active_project_id == LEGACY_PROJECT_ID:
        return base_root
    return base_root / "research_projects" / active_project_id / "workspace"


def _record_project_event(event_name: str, team_id: str, project_id: str) -> None:
    try:
        record_runtime_scene_event(
            "team_workflow_orchestration",
            "research_project",
            event_name,
            outcome="succeeded",
            fields={
                "teamId": str(team_id)[:160],
                "projectId": str(project_id)[:160],
            },
        )
    except Exception:
        return
