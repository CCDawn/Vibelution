"""S3 contract: GET /sessions/{id} is typed without rewriting the detail document."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import sessions as session_routes

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSIONS_ROUTE = REPO_ROOT / "core" / "web" / "routes" / "sessions.py"

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _session_detail_decorator() -> ast.Call:
    tree = ast.parse(SESSIONS_ROUTE.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != "session_detail":
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                return decorator
    raise AssertionError("session_detail route decorator not found")


def test_session_detail_route_declares_response_model() -> None:
    decorator = _session_detail_decorator()
    has_response_model = False
    for keyword in decorator.keywords:
        if keyword.arg != "response_model":
            continue
        if isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
            continue
        has_response_model = True
    assert has_response_model, "GET /sessions/{id} must declare response_model"


def test_session_detail_response_keeps_unknown_fields(monkeypatch) -> None:
    expected = {
        "id": "session-live",
        "title": "live",
        "messages": [
            {
                "role": "user",
                "content": "hi",
                "turnItems": [{"type": "agent_message", "text": "hi"}],
            }
        ],
        "messageWindow": {
            "mode": "window",
            "totalMessages": 2,
            "hasEarlier": True,
        },
        "provisionalTranscript": False,
        "selectedLightweight": False,
        "customDetailFlag": True,
    }
    monkeypatch.setattr(session_routes, "get_session_detail", lambda *_args, **_kwargs: expected)

    response = client.get("/api/sessions/session-live?messageLimit=40&transcriptScope=window")

    assert response.status_code == 200
    assert response.json() == expected
    assert "status" not in response.json()
