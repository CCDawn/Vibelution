import json
from datetime import datetime, timedelta, timezone

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
    assert summary["agent_brief"]["diagnosis_status"] == "active_issue"
    assert summary["agent_brief"]["needs_action"] is True
    assert summary["agent_brief"]["actionability"] == "fix_required"
    assert summary["agent_brief"]["primary_issue"] == "llm.invoke.failed"
    assert summary["agent_brief"]["active_cluster_count"] == 1
    assert summary["agent_brief"]["evidence_refs"]
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
    assert summary["event_counts"]["research_files"] == 0
    assert summary["event_counts"]["research_events"] == 0
    assert "research_logs" not in summary["event_counts"]
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


def test_runtime_scene_event_keeps_diagnostic_only_observations_out_of_first_read_logs(tmp_path, monkeypatch):
    scene_id = "scene-first-read-noise"
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

    noisy_events = [
        ("conversation", "session_detail", "session.detail_snapshot.published"),
        ("conversation", "session_detail", "session.detail_snapshot.throttled"),
        ("conversation_service", "session_index", "conversation.index.filtered_archived_team_rooms"),
        ("browser_page", "session_stream", "browser.session_stream.opened"),
        ("browser_page", "session_stream", "browser.session_stream.closed"),
        ("agent_directory", "agent", "agent.repaired"),
        ("agent_directory", "territory", "agent_territory.resolved"),
        ("runtime_manager", "runtime", "runtime.snapshot.reconciled"),
    ]
    for component, phase, event_code in noisy_events:
        runtime_scene_service.record_runtime_scene_event(
            component,
            phase,
            event_code,
            message=event_code,
            outcome="observed",
            fields={"status": "ok"},
            lifecycle=True,
        )
    runtime_scene_service.record_runtime_scene_event(
        "conversation",
        "session_detail",
        "session.detail_snapshot.published",
        message="Session detail publish failed.",
        level="warning",
        outcome="degraded",
        fields={"status": "degraded"},
        lifecycle=True,
    )

    event_codes_by_file = {
        path.name: [
            json.loads(line)["event_code"]
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for path in sorted((scene_dir / "events").glob("*.jsonl"))
    }
    assert event_codes_by_file["conversation.jsonl"].count("session.detail_snapshot.published") == 2
    assert "conversation.index.filtered_archived_team_rooms" in event_codes_by_file["conversation_service.jsonl"]
    assert "agent.repaired" in event_codes_by_file["agent_directory.jsonl"]
    assert "runtime.snapshot.reconciled" in event_codes_by_file["runtime_manager.jsonl"]

    timeline_events = [
        json.loads(line)
        for line in (scene_dir / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    lifecycle_events = [
        json.loads(line)
        for line in (scene_dir / "lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    diagnostic_detail_events = [
        event
        for event in timeline_events
        if event["event_code"] == "session.detail_snapshot.published"
    ]
    assert len(diagnostic_detail_events) == 1
    assert diagnostic_detail_events[0]["level"] == "warning"
    assert "session.detail_snapshot.throttled" not in {event["event_code"] for event in timeline_events}
    assert "conversation.index.filtered_archived_team_rooms" not in {event["event_code"] for event in timeline_events}
    assert "browser.session_stream.opened" not in {event["event_code"] for event in timeline_events}
    assert "agent.repaired" not in {event["event_code"] for event in timeline_events}
    assert "agent_territory.resolved" not in {event["event_code"] for event in lifecycle_events}
    assert "runtime.snapshot.reconciled" not in {event["event_code"] for event in lifecycle_events}


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
    assert summary["event_counts"]["research_files"] == 2
    assert summary["event_counts"]["research_events"] == 1
    assert "research_logs" not in summary["event_counts"]
    assert summary["sections"]["research"]["path"] == "research"


def test_runtime_scene_event_can_target_recent_completed_package_when_allowed(tmp_path, monkeypatch):
    scene_id = "recent-failed-scene"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260524T111509Z__{scene_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    ended_at = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
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


def test_runtime_scene_list_uses_lightweight_package_summary_without_timeline_reads(tmp_path, monkeypatch):
    scene_id = "lightweight-list-scene"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260524T120001Z__{scene_id}"
    scene_dir.mkdir(parents=True)
    scene_dir.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "runtime_scene_id": scene_id,
                "started_at": "2026-05-24T12:00:01Z",
                "status": "running",
                "trigger": "internal-start",
                "project_root": str(tmp_path),
                "backend": {"health_status": "healthy"},
                "frontend": {"build_status": "current"},
                "browser": {"status": "open"},
                "package": {
                    "index_schema_version": 2,
                    "package_id": scene_id,
                    "display_name": "cached scene",
                    "index_key": "cached-index",
                    "search_text": "cached diagnosis text",
                    "tags": ["runtime-scene", "diagnosis-active-issue"],
                    "package_index_path": "package_index.json",
                    "summary_path": "summary.json",
                    "research_dir": "research",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    scene_dir.joinpath("summary.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "package_id": scene_id,
                "display_name": "cached scene",
                "index_key": "cached-index",
                "event_counts": {
                    "timeline_events": 42,
                    "raw_logs": 7,
                    "conversation_logs": 3,
                    "agent_logs": 5,
                    "artifacts": 2,
                    "event_logs": 4,
                    "research_files": 1,
                    "errors": 6,
                    "warnings": 8,
                },
                "diagnosis": {
                    "severity": "error",
                    "userSummary": "cached diagnosis text",
                    "agentNextStep": "read cached summary",
                    "issueState": {
                        "activeClusterCount": 1,
                        "policyClusterCount": 0,
                        "historicalClusterCount": 0,
                        "controlSignalCount": 0,
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    def fail_heavy_read(*_args, **_kwargs):
        raise AssertionError("list_runtime_scenes should not read timeline or raw child logs")

    monkeypatch.setattr(runtime_scene_service, "_read_scene_timeline", fail_heavy_read)
    monkeypatch.setattr(runtime_scene_service, "_list_raw_files", fail_heavy_read)
    monkeypatch.setattr(runtime_scene_service, "_list_conversation_logs", fail_heavy_read)
    monkeypatch.setattr(runtime_scene_service, "_list_agent_logs", fail_heavy_read)
    monkeypatch.setattr(runtime_scene_service, "_list_artifacts", fail_heavy_read)
    monkeypatch.setattr(runtime_scene_service, "_list_event_logs", fail_heavy_read)
    monkeypatch.setattr(runtime_scene_service, "_list_research_logs", fail_heavy_read)

    scenes = runtime_scene_service.list_runtime_scenes(limit=1)

    assert scenes[0]["runtimeSceneId"] == scene_id
    assert scenes[0]["eventCount"] == 42
    assert scenes[0]["rawLogCount"] == 7
    assert scenes[0]["conversationCount"] == 3
    assert scenes[0]["agentLogCount"] == 5
    assert scenes[0]["artifactCount"] == 2
    assert scenes[0]["eventLogCount"] == 4
    assert scenes[0]["researchLogCount"] == 1
    assert scenes[0]["errorCount"] == 6
    assert scenes[0]["warningCount"] == 8
    assert "diagnosis-active-issue" in scenes[0]["packageIndex"]["tags"]


def test_runtime_scene_list_prunes_old_packages_to_retention_limit(tmp_path, monkeypatch):
    root = tmp_path / "logs" / "runtime_scenes"
    other_log = tmp_path / "logs" / "keep.log"
    other_log.parent.mkdir(parents=True, exist_ok=True)
    other_log.write_text("outside runtime scene retention\n", encoding="utf-8")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    for index in range(35):
        _write_runtime_scene_for_retention(root, tmp_path, index, status="stopped")

    scenes = runtime_scene_service.list_runtime_scenes(limit=80)

    remaining_dirs = sorted(path.name for path in root.iterdir() if path.is_dir())
    assert len(remaining_dirs) == 30
    assert len(scenes) == 30
    assert not (root / "20260501T000000Z__scene-00").exists()
    assert not (root / "20260501T000100Z__scene-01").exists()
    assert not (root / "20260501T000400Z__scene-04").exists()
    assert (root / "20260501T000500Z__scene-05").exists()
    assert (root / "20260501T003400Z__scene-34").exists()
    assert other_log.exists()


def test_runtime_scene_retention_protects_current_package_inside_thirty_total(tmp_path, monkeypatch):
    root = tmp_path / "logs" / "runtime_scenes"
    current_dir = _write_runtime_scene_for_retention(root, tmp_path, 0, status="running")
    for index in range(1, 32):
        _write_runtime_scene_for_retention(root, tmp_path, index, status="stopped")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps({"runtimeSceneId": "scene-00", "runtimeSceneDir": str(current_dir)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    scenes = runtime_scene_service.list_runtime_scenes(limit=80)

    remaining_dirs = sorted(path.name for path in root.iterdir() if path.is_dir())
    assert len(remaining_dirs) == 30
    assert len(scenes) == 30
    assert current_dir.exists()
    assert not (root / "20260501T000100Z__scene-01").exists()
    assert not (root / "20260501T000200Z__scene-02").exists()
    assert (root / "20260501T000300Z__scene-03").exists()
    assert (root / "20260501T003100Z__scene-31").exists()
    retention_events = (current_dir / "events" / "runtime_manager.jsonl").read_text(encoding="utf-8")
    assert "runtime_scene.retention.pruned" in retention_events
    assert "scene-01" in retention_events


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


def _write_runtime_scene_for_retention(root, project_root, index: int, *, status: str):
    started = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=index)
    scene_id = f"scene-{index:02d}"
    scene_dir = root / f"{started.strftime('%Y%m%dT%H%M%SZ')}__{scene_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "runtime_scene_id": scene_id,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "status": status,
        "trigger": "internal-start",
        "project_root": str(project_root),
    }
    if status != "running":
        payload["ended_at"] = (started + timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    scene_dir.joinpath("manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    return scene_dir
