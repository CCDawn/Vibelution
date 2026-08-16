from __future__ import annotations

import json
from pathlib import Path

from scripts.probe_user_action_telemetry import _scan_scene_for_codes


def test_scan_scene_for_codes_reads_browser_page_events(tmp_path: Path) -> None:
    scene_dir = tmp_path / "scene"
    events_dir = scene_dir / "events"
    events_dir.mkdir(parents=True)
    (events_dir / "browser_page.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event_code": "browser.user_action.session_create_started"}),
                json.dumps({"eventCode": "browser.user_action.session_delete_succeeded"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    found = _scan_scene_for_codes(
        scene_dir,
        (
            "browser.user_action.session_create_started",
            "browser.user_action.session_delete_succeeded",
            "browser.user_action.session_create_succeeded",
        ),
    )

    assert found["browser.user_action.session_create_started"] is True
    assert found["browser.user_action.session_delete_succeeded"] is True
    assert found["browser.user_action.session_create_succeeded"] is False
