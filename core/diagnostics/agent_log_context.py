from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.diagnostics.session_turn_diagnosis import build_session_turn_diagnosis
from vibelution_storage import resolve_active_project_storage_paths

AGENT_LOG_CONTEXT_SCHEMA_VERSION = 2
LARGE_LOG_BYTES = 8 * 1024 * 1024
ACTIVE_RUNTIME_SCENE_NAME = "active-runtime-scene.json"
SUMMARY_FILE_NAME = "summary.json"
LAUNCHER_LOG_NAMES = frozenset(
    {
        "backend.stdout.log",
        "backend.stderr.log",
        "launcher-control.log",
        "frontend-build.log",
    }
)
SCENE_RAW_TO_LAUNCHER = {
    "raw/backend.stdout.log": "backend.stdout.log",
    "raw/backend.stderr.log": "backend.stderr.log",
    "raw/launcher-control.log": "launcher-control.log",
    "raw/frontend.build.log": "frontend-build.log",
}

USAGE_GUIDANCE = [
    "Always start with agent_log_context before grep, read_file, or raw log expansion.",
    "Read summary.json agent_brief and follow resolvedEvidenceRefs.absolutePath before opening timeline or stdout logs.",
    "Use conversation_log_inspect_tool or agent_log_context with log_path only for a narrow deep read.",
    "Resolve paths from activePaths; never assume logs live under the git checkout root after migration.",
]


def build_agent_log_context(
    project_root: Path | str,
    *,
    session_id: str = "",
    turn_id: str = "",
    scene_id: str = "",
    recent_scene_limit: int = 3,
    max_runtime_matches: int = 20,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    storage = resolve_active_project_storage_paths(root)
    active_paths = storage.as_dict()
    launcher_dir = storage.runtime / "launcher"
    active_reference = _load_json_object(launcher_dir / ACTIVE_RUNTIME_SCENE_NAME)
    scene_dir = _resolve_scene_dir(
        root,
        storage,
        scene_id=scene_id,
        active_reference=active_reference,
    )
    summary_payload = _load_json_object(scene_dir / SUMMARY_FILE_NAME) if scene_dir else {}
    agent_brief = (
        summary_payload.get("agent_brief")
        if isinstance(summary_payload.get("agent_brief"), dict)
        else {}
    )
    diagnostic_entrypoint = (
        summary_payload.get("diagnostic_entrypoint")
        if isinstance(summary_payload.get("diagnostic_entrypoint"), dict)
        else {}
    )
    selection_status = _selection_status(scene_dir, active_reference)
    recent_scenes = _recent_scene_summaries(root, limit=recent_scene_limit)
    session_payload = None
    normalized_session_id = str(session_id or "").strip()
    if normalized_session_id:
        session_payload = build_session_turn_diagnosis(
            root,
            normalized_session_id,
            turn_id,
            max_runtime_matches=max_runtime_matches,
        )
    resolved_evidence_refs = _resolve_evidence_refs(
        root,
        storage,
        scene_dir=scene_dir,
        launcher_dir=launcher_dir,
        agent_brief=agent_brief,
        diagnostic_entrypoint=diagnostic_entrypoint,
    )

    return {
        "status": "ok",
        "schemaVersion": AGENT_LOG_CONTEXT_SCHEMA_VERSION,
        "tool": "agent_log_context",
        "mode": "context",
        "inspectedAt": datetime.now(timezone.utc).isoformat(),
        "projectRoot": str(root),
        "activePaths": active_paths,
        "selectionStatus": selection_status,
        "currentScene": _scene_pointer(
            root,
            scene_dir,
            active_reference,
            summary_payload,
        ),
        "agentBrief": agent_brief,
        "diagnosticEntrypoint": diagnostic_entrypoint,
        "resolvedEvidenceRefs": resolved_evidence_refs,
        "recentScenes": recent_scenes,
        "launcherRuntime": _launcher_runtime_hints(launcher_dir),
        "session": session_payload,
        "identityFilters": {
            "sessionId": normalized_session_id,
            "turnId": str(turn_id or "").strip(),
            "sceneId": str(scene_id or "").strip(),
        },
        "usageGuidance": list(USAGE_GUIDANCE),
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_scene_dir(
    project_root: Path,
    storage: Any,
    *,
    scene_id: str,
    active_reference: dict[str, Any],
) -> Path | None:
    runtime_scenes_root = storage.logs / "runtime_scenes"
    normalized_scene_id = str(scene_id or "").strip()
    if normalized_scene_id:
        matched = _find_scene_dir_by_id(runtime_scenes_root, normalized_scene_id)
        if matched is not None:
            return matched

    raw_dir = str(active_reference.get("runtimeSceneDir") or "").strip()
    if raw_dir:
        candidate = Path(raw_dir).resolve()
        if candidate.exists() and candidate.is_dir():
            try:
                candidate.relative_to(runtime_scenes_root.resolve())
                return candidate
            except ValueError:
                pass

    try:
        from core.web.services.runtime_scene.record import _resolve_current_runtime_scene_dir

        resolved = _resolve_current_runtime_scene_dir()
        if resolved is not None:
            return resolved.resolve()
    except Exception:
        return None
    return None


def _find_scene_dir_by_id(runtime_scenes_root: Path, scene_id: str) -> Path | None:
    if not runtime_scenes_root.exists():
        return None
    token = scene_id.lower()
    for child in sorted(runtime_scenes_root.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        if token in child.name.lower():
            return child.resolve()
        manifest = _load_json_object(child / "manifest.json")
        package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
        candidates = {
            str(manifest.get("runtime_scene_id") or "").strip().lower(),
            str(manifest.get("package_id") or "").strip().lower(),
            str(package.get("package_id") or "").strip().lower(),
        }
        if token in candidates:
            return child.resolve()
    return None


def _selection_status(scene_dir: Path | None, active_reference: dict[str, Any]) -> str:
    if scene_dir is not None:
        return "active_scene"
    if active_reference:
        return "active_reference_missing_dir"
    return "no_active_scene"


def _scene_pointer(
    project_root: Path,
    scene_dir: Path | None,
    active_reference: dict[str, Any],
    summary_payload: dict[str, Any],
) -> dict[str, Any]:
    if scene_dir is None:
        return {
            "present": False,
            "runtimeSceneId": str(active_reference.get("runtimeSceneId") or "").strip(),
            "runtimeSceneDir": str(active_reference.get("runtimeSceneDir") or "").strip(),
            "logicalPackageRoot": "",
            "summaryPath": "",
            "status": "",
        }

    package_id = str(summary_payload.get("package_id") or active_reference.get("runtimeSceneId") or "").strip()
    logical_root = f"logs/runtime_scenes/{scene_dir.name}"
    return {
        "present": True,
        "runtimeSceneId": package_id or scene_dir.name,
        "runtimeSceneDir": str(scene_dir),
        "logicalPackageRoot": logical_root,
        "summaryPath": _display_path(scene_dir / SUMMARY_FILE_NAME, project_root),
        "status": str(summary_payload.get("status") or "").strip(),
        "displayName": str(summary_payload.get("display_name") or scene_dir.name),
    }


def _recent_scene_summaries(project_root: Path, *, limit: int) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(int(limit or 3), 10))
    try:
        from core.web.services.runtime_scene_service import list_runtime_scenes

        scenes = list_runtime_scenes(limit=bounded_limit)
    except Exception:
        return _recent_scene_summaries_from_disk(project_root, limit=bounded_limit)

    recent: list[dict[str, Any]] = []
    for item in scenes:
        if not isinstance(item, dict):
            continue
        package_index = item.get("packageIndex") if isinstance(item.get("packageIndex"), dict) else {}
        diagnosis_summary = (
            item.get("diagnosisSummary") if isinstance(item.get("diagnosisSummary"), dict) else {}
        )
        recent.append(
            {
                "runtimeSceneId": str(item.get("runtimeSceneId") or "").strip(),
                "directoryName": str(item.get("directoryName") or "").strip(),
                "displayName": str(item.get("displayName") or "").strip(),
                "status": str(item.get("status") or "").strip(),
                "logicalPackageRoot": f"logs/runtime_scenes/{item.get('directoryName')}",
                "diagnosisSummary": diagnosis_summary,
                "startedAt": str(package_index.get("startedAt") or item.get("startedAt") or "").strip(),
            }
        )
    return recent


def _recent_scene_summaries_from_disk(project_root: Path, *, limit: int) -> list[dict[str, Any]]:
    storage = resolve_active_project_storage_paths(project_root)
    runtime_scenes_root = storage.logs / "runtime_scenes"
    if not runtime_scenes_root.exists():
        return []

    recent: list[dict[str, Any]] = []
    for child in sorted(runtime_scenes_root.iterdir(), reverse=True):
        if not child.is_dir() or len(recent) >= limit:
            break
        summary_payload = _load_json_object(child / SUMMARY_FILE_NAME)
        agent_brief = (
            summary_payload.get("agent_brief")
            if isinstance(summary_payload.get("agent_brief"), dict)
            else {}
        )
        recent.append(
            {
                "runtimeSceneId": str(summary_payload.get("package_id") or child.name).strip(),
                "directoryName": child.name,
                "displayName": str(summary_payload.get("display_name") or child.name).strip(),
                "status": str(summary_payload.get("status") or "").strip(),
                "logicalPackageRoot": f"logs/runtime_scenes/{child.name}",
                "diagnosisSummary": {
                    "status": str(agent_brief.get("diagnosis_status") or "").strip(),
                    "severity": str(agent_brief.get("severity") or "").strip(),
                    "primaryIssue": str(agent_brief.get("primary_issue") or "").strip(),
                    "needsAction": bool(agent_brief.get("needs_action")),
                },
                "startedAt": str(summary_payload.get("started_at") or "").strip(),
            }
        )
    return recent


def _launcher_runtime_hints(launcher_dir: Path) -> dict[str, Any]:
    hints: dict[str, Any] = {
        "launcherDir": str(launcher_dir),
        "activeRuntimeScenePath": str(launcher_dir / ACTIVE_RUNTIME_SCENE_NAME),
        "largeLogs": [],
    }
    for name in (
        "backend.stdout.log",
        "backend.stderr.log",
        "launcher-control.log",
        "frontend-build.log",
    ):
        path = launcher_dir / name
        if not path.is_file():
            continue
        try:
            size_bytes = path.stat().st_size
        except OSError:
            continue
        entry: dict[str, Any] = {
            "name": name,
            "path": str(path),
            "sizeBytes": size_bytes,
        }
        if size_bytes >= LARGE_LOG_BYTES:
            entry["warning"] = "do_not_read_full_file_use_scene_raw_or_tail"
            hints["largeLogs"].append(entry)
    return hints


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def _append_unique_ref(refs: list[str], value: str) -> None:
    normalized = str(value or "").strip()
    if not normalized or normalized in refs:
        return
    refs.append(normalized)


def _collect_evidence_ref_strings(
    agent_brief: dict[str, Any],
    diagnostic_entrypoint: dict[str, Any],
) -> list[str]:
    refs: list[str] = []
    for item in agent_brief.get("evidence_refs") if isinstance(agent_brief.get("evidence_refs"), list) else []:
        _append_unique_ref(refs, str(item or ""))
    for item in (
        diagnostic_entrypoint.get("evidence_paths")
        if isinstance(diagnostic_entrypoint.get("evidence_paths"), list)
        else []
    ):
        _append_unique_ref(refs, str(item or ""))
    for item in (
        diagnostic_entrypoint.get("recommended_order")
        if isinstance(diagnostic_entrypoint.get("recommended_order"), list)
        else []
    ):
        _append_unique_ref(refs, str(item or ""))
    return refs


def _resolve_evidence_refs(
    project_root: Path,
    storage: Any,
    *,
    scene_dir: Path | None,
    launcher_dir: Path,
    agent_brief: dict[str, Any],
    diagnostic_entrypoint: dict[str, Any],
) -> list[dict[str, Any]]:
    refs = _collect_evidence_ref_strings(agent_brief, diagnostic_entrypoint)
    return [
        _resolve_single_evidence_ref(
            ref,
            project_root=project_root,
            storage=storage,
            scene_dir=scene_dir,
            launcher_dir=launcher_dir,
        )
        for ref in refs
    ]


def _resolve_single_evidence_ref(
    ref: str,
    *,
    project_root: Path,
    storage: Any,
    scene_dir: Path | None,
    launcher_dir: Path,
) -> dict[str, Any]:
    normalized = str(ref or "").strip().replace("\\", "/")
    if not normalized:
        return {
            "ref": ref,
            "absolutePath": "",
            "displayPath": "",
            "exists": False,
        }

    candidates: list[Path] = []
    absolute_candidate = Path(normalized)
    if absolute_candidate.is_absolute():
        candidates.append(absolute_candidate)

    if normalized.startswith("logs/"):
        candidates.append(project_root / normalized)
        logs_relative = normalized.removeprefix("logs/").lstrip("/")
        if logs_relative:
            candidates.append(storage.logs / logs_relative)

    if scene_dir is not None:
        candidates.append(scene_dir / Path(normalized))

    mapped_launcher_name = SCENE_RAW_TO_LAUNCHER.get(normalized)
    if mapped_launcher_name:
        candidates.append(launcher_dir / mapped_launcher_name)

    launcher_name = Path(normalized).name
    if launcher_name in LAUNCHER_LOG_NAMES:
        candidates.append(launcher_dir / launcher_name)

    scene_candidate = scene_dir / Path(normalized) if scene_dir is not None else None
    launcher_candidate: Path | None = None
    if mapped_launcher_name:
        launcher_candidate = launcher_dir / mapped_launcher_name
    elif launcher_name in LAUNCHER_LOG_NAMES:
        launcher_candidate = launcher_dir / launcher_name

    resolved: Path | None = None
    source = ""
    if scene_candidate is not None:
        try:
            scene_resolved = scene_candidate.resolve()
            if scene_resolved.is_file() and scene_resolved.stat().st_size > 0:
                resolved = scene_resolved
                source = "runtime_scene_raw"
        except OSError:
            pass
    if resolved is None and launcher_candidate is not None:
        try:
            launcher_resolved = launcher_candidate.resolve()
            if launcher_resolved.is_file():
                resolved = launcher_resolved
                source = "launcher_runtime"
        except OSError:
            pass
    if resolved is None:
        for candidate in candidates:
            try:
                resolved_candidate = candidate.resolve()
            except OSError:
                continue
            if resolved_candidate.is_file():
                resolved = resolved_candidate
                break

    if resolved is None and candidates:
        try:
            resolved = candidates[0].resolve()
        except OSError:
            resolved = candidates[0]

    entry: dict[str, Any] = {
        "ref": ref,
        "absolutePath": str(resolved) if resolved is not None else "",
        "displayPath": _display_path(resolved, project_root) if resolved is not None else normalized,
        "exists": bool(resolved is not None and resolved.is_file()),
    }
    if source:
        entry["source"] = source
    if entry["exists"] and resolved is not None:
        try:
            size_bytes = resolved.stat().st_size
        except OSError:
            size_bytes = None
        if size_bytes is not None:
            entry["sizeBytes"] = size_bytes
            if size_bytes >= LARGE_LOG_BYTES:
                entry["warning"] = "do_not_read_full_file_use_scene_raw_or_tail"
    return entry
