from __future__ import annotations

import json
from pathlib import Path

from core.web.services import runtime_scene_service
from core.web.services.runtime_scene.query import (
    _runtime_scene_user_action_signal_line,
    _split_user_action_event_code,
    build_runtime_scene_prompt_index,
    query_browser_user_action_telemetry,
)
from tools.user_action_telemetry_tools import user_action_telemetry_query_tool

from tests.helpers.web_runtime_scene import _seed_runtime_scene_bundle


def _point_runtime_scene_root(tmp_path: Path, monkeypatch) -> None:
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps({"runtimeSceneId": "", "runtimeSceneDir": ""}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)


def _write_browser_events(scene_dir: Path, entries: list[dict]) -> None:
    events_path = scene_dir / "events" / "browser_page.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
        encoding="utf-8",
    )


def _browser_event(
    event_code: str,
    ts: str,
    *,
    level: str = "info",
    fields: dict | None = None,
    message: str = "",
) -> dict:
    return {
        "schema_version": 1,
        "runtime_scene_id": "scene",
        "ts": ts,
        "component": "browser_page",
        "phase": "observed",
        "event_code": event_code,
        "level": level,
        "outcome": "observed",
        "message": message or event_code,
        "fields": fields or {},
        "raw_refs": [],
    }


def test_split_user_action_event_code_parses_phase_suffix() -> None:
    assert _split_user_action_event_code("browser.user_action.challenge_real_batch_start_started") == (
        "challenge_real_batch_start",
        "started",
    )
    assert _split_user_action_event_code("browser.user_action.challenge_stream_interrupted_observed") == (
        "challenge_stream_interrupted",
        "observed",
    )
    assert _split_user_action_event_code("browser.memory.sampled") is None
    assert _split_user_action_event_code("browser.user_action.unphased") is None
    assert _split_user_action_event_code("") is None


def test_query_aggregates_user_actions_across_scenes(tmp_path, monkeypatch) -> None:
    _point_runtime_scene_root(tmp_path, monkeypatch)
    scene_a = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-a", status="stopped")
    scene_b = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-b", status="stopped")

    _write_browser_events(
        scene_a,
        [
            _browser_event(
                "browser.user_action.challenge_real_batch_start_started",
                "2026-08-27T01:00:00Z",
            ),
            _browser_event(
                "browser.user_action.challenge_real_batch_start_failed",
                "2026-08-27T01:00:04Z",
                level="warning",
                fields={"durationMs": 4000, "errorName": "TimeoutError", "teamId": "research-team"},
                message="real batch start failed",
            ),
            _browser_event(
                "browser.user_action.challenge_question_review_submit_succeeded",
                "2026-08-27T01:01:00Z",
                fields={"durationMs": "1500.5", "teamId": "research-team"},
            ),
            _browser_event("browser.memory.sampled", "2026-08-27T01:02:00Z"),
        ],
    )
    _write_browser_events(
        scene_b,
        [
            _browser_event(
                "browser.user_action.challenge_real_batch_start_succeeded",
                "2026-08-27T02:00:00Z",
                fields={"durationMs": 2500},
            ),
            _browser_event(
                "browser.user_action.challenge_stream_interrupted_observed",
                "2026-08-27T02:05:00Z",
                level="warning",
                fields={"teamId": "research-team"},
            ),
            _browser_event(
                "browser.user_action.agent_create_succeeded",
                "2026-08-27T02:06:00Z",
                fields={"durationMs": 100},
            ),
        ],
    )

    payload = runtime_scene_service.query_browser_user_action_telemetry("challenge_")

    assert payload["actionPrefix"] == "challenge_"
    assert payload["scenesScanned"] == 2
    assert payload["scenesWithUserActions"] == 2
    assert payload["totals"] == {
        "started": 1,
        "succeeded": 2,
        "failed": 1,
        "blocked": 0,
        "observed": 1,
    }

    actions = {item["action"]: item for item in payload["actions"]}
    assert set(actions) == {
        "challenge_real_batch_start",
        "challenge_question_review_submit",
        "challenge_stream_interrupted",
    }
    batch_start = actions["challenge_real_batch_start"]
    assert batch_start["counts"] == {"started": 1, "succeeded": 1, "failed": 1, "blocked": 0, "observed": 0}
    assert batch_start["avgDurationMs"] == 3250.0
    assert batch_start["maxDurationMs"] == 4000.0
    assert batch_start["lastSeenAt"] == "2026-08-27T02:00:00Z"
    assert batch_start["lastSceneDirectory"].endswith("scene-b")

    signals = payload["recentSignals"]
    assert [item["action"] for item in signals] == [
        "challenge_stream_interrupted",
        "challenge_real_batch_start",
    ]
    assert signals[0]["level"] == "warning"
    assert signals[1]["errorName"] == "TimeoutError"
    assert signals[1]["teamId"] == "research-team"

    unprefixed = runtime_scene_service.query_browser_user_action_telemetry("")
    assert "agent_create" in {item["action"] for item in unprefixed["actions"]}

    full_code_prefix = runtime_scene_service.query_browser_user_action_telemetry(
        "browser.user_action.challenge_"
    )
    assert full_code_prefix["actionPrefix"] == "challenge_"
    assert "agent_create" not in {item["action"] for item in full_code_prefix["actions"]}


def test_query_without_scenes_returns_empty_totals(tmp_path, monkeypatch) -> None:
    _point_runtime_scene_root(tmp_path, monkeypatch)

    payload = runtime_scene_service.query_browser_user_action_telemetry()

    assert payload["scenesScanned"] == 0
    assert payload["scenesWithUserActions"] == 0
    assert payload["actions"] == []
    assert payload["recentSignals"] == []
    assert payload["totals"]["failed"] == 0


def test_user_action_signal_line_reports_failures_and_warnings(tmp_path, monkeypatch) -> None:
    _point_runtime_scene_root(tmp_path, monkeypatch)
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-signal", status="stopped")
    _write_browser_events(
        scene_dir,
        [
            _browser_event("browser.user_action.challenge_dev_batch_run_succeeded", "2026-08-27T03:00:00Z"),
            _browser_event(
                "browser.user_action.challenge_real_batch_cancel_blocked",
                "2026-08-27T03:01:00Z",
                level="warning",
            ),
            _browser_event(
                "browser.user_action.challenge_workflow_replay_failed_observed",
                "2026-08-27T03:02:00Z",
                level="warning",
            ),
        ],
    )

    line = _runtime_scene_user_action_signal_line(scene_dir)

    assert "challenge_real_batch_cancel failed/blocked=1" in line
    assert "challenge_workflow_replay_failed warned=1" in line
    assert "user_action_telemetry_query_tool" in line
    assert "challenge_dev_batch_run" not in line


def test_user_action_signal_line_is_empty_without_signals(tmp_path, monkeypatch) -> None:
    _point_runtime_scene_root(tmp_path, monkeypatch)
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-clean", status="stopped")
    _write_browser_events(
        scene_dir,
        [_browser_event("browser.user_action.challenge_dev_batch_run_succeeded", "2026-08-27T03:00:00Z")],
    )

    assert _runtime_scene_user_action_signal_line(scene_dir) == ""


def test_prompt_index_includes_user_action_signal_line(tmp_path, monkeypatch) -> None:
    _point_runtime_scene_root(tmp_path, monkeypatch)
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-prompt", status="stopped")
    _write_browser_events(
        scene_dir,
        [
            _browser_event(
                "browser.user_action.challenge_real_batch_start_failed",
                "2026-08-27T04:00:00Z",
                level="warning",
                fields={"errorName": "TimeoutError"},
            ),
        ],
    )

    rendered = build_runtime_scene_prompt_index(limit=3)

    assert rendered
    assert "用户动作异常" in rendered
    assert "challenge_real_batch_start failed/blocked=1" in rendered


def test_tool_wrapper_returns_json_aggregation(tmp_path, monkeypatch) -> None:
    _point_runtime_scene_root(tmp_path, monkeypatch)
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-tool", status="stopped")
    _write_browser_events(
        scene_dir,
        [
            _browser_event(
                "browser.user_action.challenge_question_register_submit_succeeded",
                "2026-08-27T05:00:00Z",
                fields={"durationMs": 900},
            ),
        ],
    )

    payload = json.loads(user_action_telemetry_query_tool(action_prefix="challenge_", scene_limit=5))

    assert payload["scenesScanned"] == 1
    assert payload["totals"]["succeeded"] == 1
    assert payload["actions"][0]["action"] == "challenge_question_register_submit"
