import json
from datetime import datetime
from pathlib import Path

from core.web.services import runtime_scene_service


def _seed_runtime_scene_bundle(project_root: Path, scene_id: str = "scene-1", status: str = "stopped") -> Path:
    scene_dir = project_root / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}"
    events_dir = scene_dir / "events"
    raw_dir = scene_dir / "raw"
    events_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime_scene_id": scene_id,
                "title": f"Managed workbench run {scene_id}",
                "package": {
                    "schema_version": 2,
                    "timeline_path": "timeline.jsonl",
                    "lifecycle_path": "lifecycle.jsonl",
                    "raw_dir": "raw",
                    "conversations_dir": "conversations",
                    "agent_dir": "agent",
                    "artifacts_dir": "artifacts",
                },
                "started_at": "2026-05-18T12:00:00Z",
                "ended_at": "" if status == "running" else "2026-05-18T12:03:00Z",
                "status": status,
                "result": "" if status == "running" else "explicit_stop",
                "stop_reason": "" if status == "running" else "explicit stop",
                "trigger": "start",
                "session_mode": "managed",
                "project_root": str(project_root),
                "host": "127.0.0.1",
                "port": 8000,
                "url": "http://127.0.0.1:8000",
                "frontend": {
                    "build_status": "success",
                    "build_reason": "frontend sources changed",
                    "log_path": "raw/frontend.build.log",
                },
                "backend": {
                    "pid": 12345,
                    "health_status": "stopped",
                    "stdout_path": "raw/backend.stdout.log",
                    "stderr_path": "raw/backend.stderr.log",
                },
                "browser": {
                    "managed": True,
                    "status": "stopped",
                    "log_path": "raw/browser.log",
                    "launch_pid": 222,
                    "window_pid": 333,
                },
                "supervisor": {
                    "pid": 444,
                    "status": "stopped",
                    "log_path": "raw/supervisor.log",
                    "stderr_path": "raw/supervisor.stderr.log",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (events_dir / "frontend.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "runtime_scene_id": scene_id,
                        "ts": "2026-05-18T12:00:01Z",
                        "seq": 1,
                        "component": "frontend",
                        "phase": "build",
                        "event_code": "frontend.build.started",
                        "level": "info",
                        "outcome": "started",
                        "message": "Starting frontend build.",
                        "fields": {"reason": "frontend sources changed"},
                        "raw_refs": [{"path": "raw/frontend.build.log", "tail_lines": 40}],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "runtime_scene_id": scene_id,
                        "ts": "2026-05-18T12:00:03Z",
                        "seq": 2,
                        "component": "frontend",
                        "phase": "build",
                        "event_code": "frontend.build.succeeded",
                        "level": "info",
                        "outcome": "succeeded",
                        "message": "Frontend build completed successfully.",
                        "fields": {"output": "web/dist/index.html"},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "runtime_scene_id": scene_id,
                        "ts": "2026-05-18T12:00:04Z",
                        "seq": 3,
                        "component": "frontend",
                        "phase": "build",
                        "event_code": "frontend.build.cache_warning",
                        "level": "warning",
                        "outcome": "succeeded",
                        "message": "Frontend build cache was cold.",
                        "fields": {},
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (events_dir / "backend.jsonl").write_text(
        json.dumps(
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:05Z",
                "seq": 1,
                "component": "backend",
                "phase": "health",
                "event_code": "backend.health.succeeded",
                "level": "info",
                "outcome": "succeeded",
                "message": "Backend passed health checks.",
                "fields": {"pid": 12345, "url": "http://127.0.0.1:8000"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (events_dir / "supervisor.jsonl").write_text(
        json.dumps(
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:06Z",
                "seq": 1,
                "component": "supervisor",
                "phase": "session",
                "event_code": "supervisor.unexpected_exit",
                "level": "info",
                "outcome": "failed",
                "message": "Supervisor exited unexpectedly.",
                "fields": {"errorType": "SupervisorExited"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (raw_dir / "frontend.build.log").write_text("vite build ok\n", encoding="utf-8")
    (raw_dir / "backend.stdout.log").write_text("uvicorn started\n", encoding="utf-8")
    (raw_dir / "backend.stderr.log").write_text("", encoding="utf-8")
    (raw_dir / "supervisor.log").write_text("supervisor ok\n", encoding="utf-8")
    (raw_dir / "supervisor.stderr.log").write_text("", encoding="utf-8")
    (raw_dir / "browser.log").write_text("browser open\n", encoding="utf-8")
    timeline_payloads = [
        line
        for path in sorted(events_dir.glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    (scene_dir / "timeline.jsonl").write_text("\n".join(timeline_payloads) + "\n", encoding="utf-8")
    (scene_dir / "lifecycle.jsonl").write_text("\n".join(timeline_payloads) + "\n", encoding="utf-8")
    (scene_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "package_id": scene_id,
                "event_counts": {
                    "timeline_events": len(timeline_payloads),
                    "raw_logs": len(list(raw_dir.glob("*.log"))),
                    "conversation_logs": 0,
                    "agent_logs": 0,
                    "artifacts": 0,
                    "event_logs": len(list(events_dir.glob("*.jsonl"))),
                    "research_files": 0,
                    "errors": 1,
                    "warnings": 1,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest = runtime_scene_service._load_scene_manifest(scene_dir)
    runtime_scene_service._update_runtime_scene_package_manifest(scene_dir, manifest)
    return scene_dir

def _runtime_scene_local_index_parts(iso_value: str) -> tuple[str, str, str]:
    parsed = datetime.fromisoformat(iso_value.replace("Z", "+00:00")).astimezone()
    return parsed.strftime("%Y-%m-%d"), parsed.strftime("%H:%M:%S"), parsed.strftime("%H-%M-%S")
