from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.probe_user_action_telemetry import (
    _control_token_headers,
    _fetch_control_token,
    _find_backend_client_operation_hits,
    _scan_scene_for_codes,
)


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


def test_fetch_control_token_reads_header_and_token() -> None:
    with patch(
        "scripts.probe_user_action_telemetry._request_json",
        return_value={"header": "X-Custom-Control-Token", "controlToken": "probe-token"},
    ):
        header, token = _fetch_control_token("http://127.0.0.1:8100")
        assert header == "X-Custom-Control-Token"
        assert token == "probe-token"
        assert _control_token_headers("http://127.0.0.1:8100") == {
            "X-Custom-Control-Token": "probe-token",
        }


def test_fetch_control_token_rejects_empty_token() -> None:
    with patch("scripts.probe_user_action_telemetry._request_json", return_value={"controlToken": ""}):
        with pytest.raises(RuntimeError, match="empty token"):
            _fetch_control_token("http://127.0.0.1:8100")


def test_find_backend_client_operation_hits_filters_by_operation_id(tmp_path: Path) -> None:
    scene_dir = tmp_path / "scene"
    events_dir = scene_dir / "events"
    events_dir.mkdir(parents=True)
    (events_dir / "backend.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"fields": {"clientOperationId": "other-id", "pathTemplate": "/api/other"}}),
                json.dumps(
                    {
                        "fields": {
                            "clientOperationId": "probe-user-action-1",
                            "pathTemplate": "/api/sessions/{session_id}/select",
                            "statusCode": 404,
                        }
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    hits = _find_backend_client_operation_hits(scene_dir, "probe-user-action-1")

    assert hits == [{"path": "/api/sessions/{session_id}/select", "statusCode": 404}]
