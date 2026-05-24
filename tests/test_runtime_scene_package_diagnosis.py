import json
from pathlib import Path

from core.web.services import runtime_scene_service


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _seed_scene(tmp_path: Path, scene_id: str, rows: list[dict], *, status: str = "stopped") -> Path:
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "raw").mkdir(parents=True, exist_ok=True)
    (scene_dir / "summary.json").write_text("{}", encoding="utf-8")
    (scene_dir / "package_index.json").write_text("{}", encoding="utf-8")
    (scene_dir / "raw" / "backend.stderr.log").write_text("traceback: provider failed\n", encoding="utf-8")
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_scene_id": scene_id,
                "started_at": "2026-05-18T12:00:00Z",
                "ended_at": "" if status == "running" else "2026-05-18T12:02:00Z",
                "status": status,
                "result": "failed" if status == "failed" else "explicit_stop",
                "trigger": "start",
                "session_mode": "managed",
                "project_root": str(tmp_path),
                "backend": {
                    "stderr_path": "raw/backend.stderr.log",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_jsonl(scene_dir / "timeline.jsonl", rows)
    _write_jsonl(
        scene_dir / "lifecycle.jsonl",
        [row for row in rows if row.get("phase") in {"startup", "shutdown", "health"}],
    )
    return scene_dir


def test_runtime_scene_detail_exposes_package_diagnosis_first_signal(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    _seed_scene(
        tmp_path,
        "scene-diagnosis-error",
        [
            {
                "runtime_scene_id": "scene-diagnosis-error",
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "backend",
                "phase": "startup",
                "event_code": "backend.start.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Backend failed to start.",
                "fields": {"errorType": "RuntimeError"},
                "raw_refs": [{"path": "raw/backend.stderr.log", "tail_lines": 80}],
            }
        ],
        status="failed",
    )

    detail = runtime_scene_service.get_runtime_scene_detail("scene-diagnosis-error")

    diagnosis = detail["packageDiagnosis"]
    assert diagnosis["severity"] == "error"
    assert "错误信号" in diagnosis["userSummary"]
    assert diagnosis["firstSignal"]["eventCode"] == "backend.start.failed"
    assert diagnosis["firstSignal"]["rawRefs"] == [{"path": "raw/backend.stderr.log", "tail_lines": 80}]
    assert diagnosis["recommendedOrder"][:5] == [
        "summary.json",
        "package_index.json",
        "timeline.jsonl",
        "lifecycle.jsonl",
        "raw/backend.stderr.log",
    ]
    assert diagnosis["keyEntries"][0]["path"] == "summary.json"
    assert any(item["path"] == "raw/backend.stderr.log" for item in diagnosis["keyEntries"])
    assert "logs/runtime_scenes/20260518T120000Z__scene-diagnosis-error/summary.json" in diagnosis["agentNextStep"]


def test_runtime_scene_detail_exposes_clean_package_diagnosis(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    _seed_scene(
        tmp_path,
        "scene-diagnosis-clean",
        [
            {
                "runtime_scene_id": "scene-diagnosis-clean",
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "backend",
                "phase": "health",
                "event_code": "backend.health.succeeded",
                "level": "info",
                "outcome": "succeeded",
                "message": "Backend passed health checks.",
                "fields": {},
            }
        ],
    )

    detail = runtime_scene_service.get_runtime_scene_detail("scene-diagnosis-clean")

    diagnosis = detail["packageDiagnosis"]
    assert diagnosis["severity"] == "info"
    assert "未发现明显错误或警告" in diagnosis["userSummary"]
    assert diagnosis["firstSignal"]["eventCode"] == "backend.health.succeeded"
    assert diagnosis["firstSignal"]["severity"] == "info"
    assert diagnosis["recommendedOrder"][:4] == [
        "summary.json",
        "package_index.json",
        "timeline.jsonl",
        "lifecycle.jsonl",
    ]
    assert "推荐阅读顺序" in diagnosis["agentNextStep"]
