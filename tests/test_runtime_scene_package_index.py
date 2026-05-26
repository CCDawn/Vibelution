import json
from datetime import UTC, datetime, timedelta

from core.web.services import runtime_scene_service


def _local_index_key_prefix(iso_value: str) -> str:
    parsed = datetime.fromisoformat(iso_value.replace("Z", "+00:00")).astimezone()
    return parsed.strftime("%Y-%m-%d_%H-%M-%S")


def test_runtime_scene_event_writes_standalone_package_index(tmp_path, monkeypatch):
    scene_id = "scene-package-index"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_scene_id": scene_id,
                "started_at": "2026-05-18T12:00:00Z",
                "status": "running",
                "trigger": "start",
                "session_mode": "managed",
                "package": {
                    "schema_version": 2,
                    "timeline_path": "timeline.jsonl",
                    "lifecycle_path": "lifecycle.jsonl",
                    "raw_dir": "raw",
                    "conversations_dir": "conversations",
                    "agent_dir": "agent",
                    "artifacts_dir": "artifacts",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": scene_id,
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = runtime_scene_service.record_runtime_scene_event(
        "work_run",
        "state",
        "work_run.snapshot.persisted",
        message="Snapshot persisted",
        level="info",
        outcome="succeeded",
        fields={"runId": "run-1"},
        lifecycle=True,
    )
    runtime_scene_service.record_runtime_scene_event(
        "llm",
        "invoke",
        "llm.invoke.failed",
        message="Provider failed",
        level="error",
        outcome="failed",
        fields={"errorType": "RuntimeError"},
        lifecycle=True,
    )
    runtime_scene_service.record_runtime_scene_event(
        "browser_page",
        "console",
        "browser.console.warn",
        message="Console warning",
        level="warning",
        outcome="observed",
        fields={},
    )

    assert response["accepted"] is True
    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    package_index = json.loads((scene_dir / "package_index.json").read_text(encoding="utf-8"))
    summary = json.loads((scene_dir / "summary.json").read_text(encoding="utf-8"))
    assert manifest["package"]["package_index_path"] == "package_index.json"
    assert manifest["package"]["summary_path"] == "summary.json"
    assert package_index["schema_version"] == 2
    assert package_index["package_id"] == scene_id
    assert package_index["index_key"] == manifest["package"]["index_key"]
    assert package_index["search_text"] == manifest["package"]["search_text"]
    assert package_index["summary_ref"] == "summary.json"
    assert "diagnosis" not in package_index
    assert package_index["timeline_path"] == "timeline.jsonl"
    assert package_index["lifecycle_path"] == "lifecycle.jsonl"
    assert package_index["research_dir"] == "research"
    assert summary["schema_version"] == 2
    assert summary["package_id"] == scene_id
    assert summary["display_name"] == package_index["display_name"]
    assert summary["primary_files"]["package_index"] == "package_index.json"
    assert summary["primary_files"]["manifest"] == "manifest.json"
    assert summary["primary_files"]["timeline"] == "timeline.jsonl"
    assert summary["primary_files"]["lifecycle"] == "lifecycle.jsonl"
    assert summary["primary_files"]["research"] == "research/summary.json"
    assert summary["sections"]["conversations"]["path"] == "conversations"
    assert summary["sections"]["research"]["path"] == "research"
    assert summary["sections"]["research"]["events_path"] == "research/events.jsonl"
    assert summary["sections"]["research"]["summary_path"] == "research/summary.json"
    assert summary["sections"]["supervised_evolution"]["path"] == "agent/supervised_runs"
    assert summary["sections"]["supervised_evolution"]["worktree_path"] == "agent/supervised_worktree_runs"
    assert summary["sections"]["self_evolution"]["path"] == "agent/self_evolution_runs"
    assert summary["event_counts"]["timeline_events"] == 3
    assert summary["event_counts"]["lifecycle_events"] == 2
    assert summary["event_counts"]["errors"] == 1
    assert summary["event_counts"]["warnings"] == 1
    assert summary["event_counts"]["research_logs"] == 0
    assert summary["diagnosis"]["severity"] == "error"
    assert summary["diagnosis"]["issueState"]["activeClusterCount"] == 2
    assert summary["diagnosis"]["evidencePaths"][0] == "events/llm.jsonl"
    assert "rawRefs" not in summary["diagnosis"]["agentNextStep"]
    assert "evidence_paths" in summary["diagnosis"]["agentNextStep"]
    assert "llm-llm-invoke-failed" in package_index["search_text"]
    assert "diagnosis-active-issue" in package_index["tags"]
    assert summary["diagnosis"]["agentNextStep"]
    assert summary["diagnostic_entrypoint"]["first_read"] == "summary.json"
    assert summary["diagnostic_entrypoint"]["package_root"] == f"logs/runtime_scenes/{scene_dir.name}"
    assert summary["diagnostic_entrypoint"]["path_mode"] == "package_relative"
    assert summary["diagnostic_entrypoint"]["evidence_paths"] == summary["diagnosis"]["evidencePaths"]
    assert "research/summary.json" in summary["diagnostic_entrypoint"]["recommended_order"]
    assert "research/events.jsonl" in summary["diagnostic_entrypoint"]["recommended_order"]
    assert summary["diagnostic_entrypoint"]["recommended_order"][:6] == [
        "summary.json",
        "package_index.json",
        "raw/desktop-entry-vbs.log",
        "raw/desktop-entry.log",
        "raw/launcher-control.log",
        "timeline.jsonl",
    ]


def test_research_scene_event_writes_dedicated_research_package_section(tmp_path, monkeypatch):
    scene_id = "scene-research-package"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    scene_dir.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_scene_id": scene_id,
                "started_at": "2026-05-18T12:00:00Z",
                "status": "running",
                "trigger": "start",
                "project_root": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps({"runtimeSceneId": scene_id, "runtimeSceneDir": str(scene_dir)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = runtime_scene_service.record_research_scene_event(
        "research.prompt.updated",
        phase="prompt_config",
        message="Research prompt updated",
        fields={"agentKey": "broad", "filename": "broad.md"},
        agent_key="broad",
    )

    assert response["accepted"] is True
    assert response["path"] == "research/events.jsonl"
    research_events = [json.loads(line) for line in scene_dir.joinpath("research/events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert research_events[0]["event_code"] == "research.prompt.updated"
    assert research_events[0]["agent_key"] == "broad"
    research_summary = json.loads(scene_dir.joinpath("research/summary.json").read_text(encoding="utf-8"))
    assert research_summary["event_count"] == 1
    assert research_summary["event_codes"]["research.prompt.updated"] == 1
    assert research_summary["agents"]["broad"] == 1
    summary = json.loads(scene_dir.joinpath("summary.json").read_text(encoding="utf-8"))
    assert summary["event_counts"]["research_logs"] == 2
    assert summary["sections"]["research"]["path"] == "research"


def test_runtime_scene_event_can_target_recent_completed_package_when_allowed(tmp_path, monkeypatch):
    scene_id = "recent-failed-scene"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260524T111509Z__{scene_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    ended_at = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_scene_id": scene_id,
                "started_at": "2026-05-24T11:15:09Z",
                "ended_at": ended_at,
                "status": "failed",
                "trigger": "internal-start",
                "session_mode": "managed",
                "project_root": str(tmp_path),
                "package": {
                    "schema_version": 2,
                    "timeline_path": "timeline.jsonl",
                    "lifecycle_path": "lifecycle.jsonl",
                    "raw_dir": "raw",
                    "conversations_dir": "conversations",
                    "agent_dir": "agent",
                    "artifacts_dir": "artifacts",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    blocked = runtime_scene_service.record_runtime_scene_event(
        "runtime_manager",
        "command",
        "command.failed",
        fields={"commandId": "cmd-open"},
    )
    accepted = runtime_scene_service.record_runtime_scene_event(
        "runtime_manager",
        "command",
        "command.failed",
        fields={"commandId": "cmd-open"},
        level="error",
        outcome="failed",
        lifecycle=True,
        allow_recent_completed=True,
    )

    assert blocked["accepted"] is False
    assert accepted["accepted"] is True
    assert accepted["runtimeSceneId"] == scene_id
    timeline = (scene_dir / "timeline.jsonl").read_text(encoding="utf-8")
    assert "command.failed" in timeline
    summary = json.loads((scene_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["event_counts"]["errors"] == 1
    assert summary["diagnosis"]["issueState"]["activeClusterCount"] == 1
    assert summary["diagnosis"]["evidencePaths"][0] == "events/runtime_manager.jsonl"


def test_runtime_scene_list_sorts_by_package_timestamp_when_started_at_missing(tmp_path, monkeypatch):
    root = tmp_path / "logs" / "runtime_scenes"
    old_dir = root / "20260524T104120Z__old-scene"
    new_dir = root / "20260524T112017Z__new-scene"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    old_dir.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "runtime_scene_id": "old-scene",
                "started_at": "2026-05-24T10:41:20Z",
                "status": "stopped",
                "project_root": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    new_dir.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "runtime_scene_id": "new-scene",
                "status": "unknown",
                "project_root": str(tmp_path),
                "package": {"started_at": "", "sortable_timestamp": "2026-05-24T11:20:17+00:00"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    scenes = runtime_scene_service.list_runtime_scenes(limit=2)

    assert [scene["runtimeSceneId"] for scene in scenes] == ["new-scene", "old-scene"]
    assert scenes[0]["startedAt"] == "2026-05-24T11:20:17+00:00"
    assert scenes[0]["status"] == "running"
    assert scenes[0]["packageIndex"]["indexKey"] == (
        f"{_local_index_key_prefix(scenes[0]['startedAt'])}_workbench-run_running"
    )


def test_runtime_scene_status_defaults_to_running_until_ended(tmp_path, monkeypatch):
    scene_id = "statusless-running-scene"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260524T120001Z__{scene_id}"
    scene_dir.mkdir(parents=True)
    scene_dir.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "runtime_scene_id": scene_id,
                "started_at": "2026-05-24T12:00:01Z",
                "ended_at": "",
                "project_root": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    scenes = runtime_scene_service.list_runtime_scenes(limit=1)
    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    assert scenes[0]["status"] == "running"
    assert scenes[0]["startedAt"] == "2026-05-24T12:00:01Z"
    assert detail["status"] == "running"


def test_runtime_scene_detail_refreshes_stale_package_sidecars(tmp_path, monkeypatch):
    scene_id = "stale-sidecars-scene"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260524T120001Z__{scene_id}"
    scene_dir.mkdir(parents=True)
    scene_dir.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "runtime_scene_id": scene_id,
                "started_at": "2026-05-24T12:00:01Z",
                "ended_at": "",
                "status": "unknown",
                "trigger": "internal-start",
                "project_root": str(tmp_path),
                "package": {
                    "index_key": "stale",
                    "package_index_path": "package_index.json",
                    "summary_path": "summary.json",
                },
            }
        ),
        encoding="utf-8",
    )
    scene_dir.joinpath("package_index.json").write_text('{"index_key":"stale"}', encoding="utf-8")
    scene_dir.joinpath("summary.json").write_text('{"package_id":"stale"}', encoding="utf-8")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    manifest = json.loads(scene_dir.joinpath("manifest.json").read_text(encoding="utf-8"))
    package_index = json.loads(scene_dir.joinpath("package_index.json").read_text(encoding="utf-8"))
    summary = json.loads(scene_dir.joinpath("summary.json").read_text(encoding="utf-8"))
    assert detail["status"] == "running"
    assert package_index["package_id"] == scene_id
    assert package_index["index_key"] == detail["packageIndex"]["indexKey"]
    assert package_index["summary_ref"] == "summary.json"
    assert "diagnosis" not in package_index
    assert summary["package_id"] == scene_id
    assert summary["display_name"] == detail["packageIndex"]["displayName"]
    assert summary["diagnosis"]["issueState"]["activeClusterCount"] == 0
    assert manifest["package"]["index_key"] == detail["packageIndex"]["indexKey"]


def test_runtime_scene_static_summary_distinguishes_recovered_issue_from_active_failure(tmp_path, monkeypatch):
    scene_id = "static-recovered-scene"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260524T120001Z__{scene_id}"
    scene_dir.mkdir(parents=True)
    scene_dir.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "runtime_scene_id": scene_id,
                "started_at": "2026-05-24T12:00:01Z",
                "ended_at": "",
                "status": "running",
                "trigger": "internal-start",
                "project_root": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (scene_dir / "timeline.jsonl").write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in [
                {
                    "runtime_scene_id": scene_id,
                    "ts": "2026-05-24T12:00:02Z",
                    "seq": 1,
                    "component": "llm",
                    "phase": "invoke",
                    "event_code": "llm.invoke.failed.retrying",
                    "level": "warning",
                    "outcome": "retrying",
                    "message": "LLM invoke retrying after timeout.",
                    "fields": {"errorType": "timeout", "retryable": True},
                },
                {
                    "runtime_scene_id": scene_id,
                    "ts": "2026-05-24T12:00:03Z",
                    "seq": 2,
                    "component": "llm",
                    "phase": "invoke",
                    "event_code": "llm.invoke.succeeded",
                    "level": "info",
                    "outcome": "succeeded",
                    "message": "LLM invoke succeeded.",
                    "fields": {},
                },
                {
                    "runtime_scene_id": scene_id,
                    "ts": "2026-05-24T12:00:04Z",
                    "seq": 3,
                    "component": "conversation",
                    "phase": "next_state_signal",
                    "event_code": "conversation.next_state_signal.recorded",
                    "level": "warning",
                    "outcome": "user_stops",
                    "message": "用户请求停止当前对话轮次。",
                    "fields": {"kind": "user_stops"},
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    package_index = json.loads(scene_dir.joinpath("package_index.json").read_text(encoding="utf-8"))
    summary = json.loads(scene_dir.joinpath("summary.json").read_text(encoding="utf-8"))
    assert detail["packageDiagnosis"]["severity"] == "info"
    assert package_index["summary_ref"] == "summary.json"
    assert "diagnosis" not in package_index
    assert summary["diagnosis"]["severity"] == "info"
    assert summary["diagnosis"]["issueState"]["activeClusterCount"] == 0
    assert summary["diagnosis"]["issueState"]["historicalClusterCount"] == 1
    assert summary["diagnosis"]["issueState"]["controlSignalCount"] == 1
    assert summary["diagnosis"]["firstSignal"]["eventCode"] == "llm.invoke.failed.retrying"
    assert summary["diagnosis"]["evidencePaths"][0] == "events/llm.jsonl"
    assert "避免把已恢复错误当成当前阻塞" in summary["diagnosis"]["agentNextStep"]
    assert "diagnosis-recovered-issue" in package_index["tags"]
    assert "recovered_issue" in package_index["search_text"]
