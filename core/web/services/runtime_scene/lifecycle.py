"""Runtime scene lifecycle: one fresh scene per backend startup, sealed exits.

Claim scope: backend-start scene creation, active-runtime-scene pointer
rotation, and idempotent sealing of the previous scene.

Ported from the retired Python launcher path ``scripts/vibelution_launcher.py``
(``_start_runtime_scene`` / ``_seal_active_runtime_scene``): every backend
start first seals the still-active scene as ``orphan_reconciled``, then creates
a fresh timestamped scene directory and atomically repoints
``active-runtime-scene.json``. Without this rotation the pointer froze on a
single ever-growing scene and query-side retention never had a chance to prune.

Path authority: the scene root comes from the service's own
``_runtime_scene_root()`` and the pointer file is the exact file
``record._load_active_runtime_scene_reference`` reads
(``LAUNCHER_STATE_PATH.with_name("active-runtime-scene.json")``), so the
backend can always read back what it writes here. The launcher keeps its own
identical copy of these paths; both writers are idempotent so whichever path
starts first simply seals the older scene.

Windows no-console red line: pure Python file operations only — this module
must never spawn a subprocess.

Late-bound facade keeps monkeypatches stable (same pattern as record/query).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

BACKEND_STARTUP_TRIGGER = "backend_startup"


def _service():
    from core.web.services import runtime_scene_service

    return runtime_scene_service


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _active_runtime_scene_pointer_path() -> Path:
    """Pointer file read by ``record._load_active_runtime_scene_reference``."""
    s = _service()
    return s.LAUNCHER_STATE_PATH.with_name("active-runtime-scene.json")


def start_runtime_scene(trigger: str) -> dict[str, str]:
    """Seal any active scene, create a fresh one, and atomically repoint.

    Mirrors ``scripts/vibelution_launcher.py`` ``_start_runtime_scene``: the
    pointer keeps the ``runtimeSceneId`` / ``runtimeSceneDir`` / ``startedAt``
    / ``launcherPid`` / ``trigger`` schema; ``launcherPid`` here is the backend
    process pid.
    """
    s = _service()
    seal_active_runtime_scene(
        "orphan_reconciled",
        "Previous active scene was superseded by a fresh backend start.",
    )
    started_at = datetime.now(timezone.utc)
    scene_id = uuid.uuid4().hex[:12]
    directory_name = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}__{scene_id}"
    scene_dir = s._runtime_scene_root() / directory_name
    for relative_dir in ("events", "raw", "conversations", "agent", "artifacts"):
        (scene_dir / relative_dir).mkdir(parents=True, exist_ok=True)

    reference = {
        "runtimeSceneId": scene_id,
        "runtimeSceneDir": str(scene_dir.resolve()),
        "startedAt": started_at.isoformat(),
        "launcherPid": os.getpid(),
        "trigger": str(trigger or BACKEND_STARTUP_TRIGGER),
    }
    pointer_path = _active_runtime_scene_pointer_path()
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = pointer_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(pointer_path)

    # Seed a minimal manifest so the fresh scene is well-formed for the whole
    # service from the first read (project-bound, status "running").
    s._save_scene_manifest(
        scene_dir,
        {
            "schema_version": 2,
            "runtime_scene_id": scene_id,
            "started_at": started_at.isoformat(),
            "status": "running",
            "trigger": reference["trigger"],
            "project_root": str(s.PROJECT_ROOT),
        },
    )
    return reference


def seal_active_runtime_scene(result: str, stop_reason: str) -> dict[str, object]:
    """Idempotently seal the active scene without clearing its current pointer.

    Mirrors ``scripts/vibelution_launcher.py`` ``_seal_active_runtime_scene``.
    The pointer is deliberately left in place (see
    ``record._resolve_pointer_runtime_scene_dir``); the only launcher-specific
    step that does not port over is syncing launcher control logs into
    ``raw/`` — the backend writes its own raw logs directly into the scene.
    """
    s = _service()
    pointer_path = _active_runtime_scene_pointer_path()
    try:
        reference = json.loads(pointer_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"sealed": False, "reason": "active_scene_unavailable"}
    if not isinstance(reference, dict):
        return {"sealed": False, "reason": "active_scene_invalid"}
    scene_dir_text = str(reference.get("runtimeSceneDir") or "").strip()
    if not scene_dir_text:
        return {"sealed": False, "reason": "scene_dir_missing"}
    try:
        scene_dir = Path(scene_dir_text).resolve()
        scene_dir.relative_to(s._runtime_scene_root())
    except (OSError, ValueError):
        return {"sealed": False, "reason": "scene_dir_outside_root"}
    if not scene_dir.is_dir():
        return {"sealed": False, "reason": "scene_dir_unavailable"}

    manifest_path = scene_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}
    if str(manifest.get("ended_at") or "").strip():
        return {"sealed": False, "reason": "already_sealed", "sceneDir": str(scene_dir)}

    ended_at = _now_iso()
    manifest.update(
        {
            "schema_version": int(manifest.get("schema_version") or 2),
            "runtime_scene_id": str(
                manifest.get("runtime_scene_id") or reference.get("runtimeSceneId") or scene_dir.name
            ),
            "started_at": str(manifest.get("started_at") or reference.get("startedAt") or ended_at),
            "ended_at": ended_at,
            "status": "stopped",
            "result": str(result or "orphan_reconciled"),
            "stop_reason": str(stop_reason or "Runtime scene reconciled closed."),
            "project_root": str(manifest.get("project_root") or s.PROJECT_ROOT),
        }
    )
    temp_path = manifest_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(manifest_path)
    return {"sealed": True, "reason": manifest["result"], "sceneDir": str(scene_dir)}
