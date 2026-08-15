"""S5 contract: leftover session side routes are typed without rewriting documents."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import sessions as session_routes
from core.web.routes.session_side_models import (
    SessionChatReviewCandidateResponse,
    SessionChildCreateResponse,
    SessionToolApprovalItem,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSIONS_ROUTE = REPO_ROOT / "core" / "web" / "routes" / "sessions.py"

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

TYPED_SIDE_ROUTES = {
    "session_child_sessions",
    "session_create_child_session",
    "session_tool_approvals",
    "session_resolve_tool_approval",
    "session_create_chat_review_candidate",
}


def _route_decorators() -> dict[str, ast.Call]:
    tree = ast.parse(SESSIONS_ROUTE.read_text(encoding="utf-8"))
    found: dict[str, ast.Call] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                found[node.name] = decorator
    return found


def test_session_side_routes_declare_response_model() -> None:
    decorators = _route_decorators()
    missing = []
    for name in sorted(TYPED_SIDE_ROUTES):
        decorator = decorators.get(name)
        if decorator is None:
            missing.append(name)
            continue
        has_response_model = False
        for keyword in decorator.keywords:
            if keyword.arg != "response_model":
                continue
            if isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
                continue
            has_response_model = True
        if not has_response_model:
            missing.append(name)
    assert missing == [], f"session side routes must declare response_model: {missing}"


def test_session_side_response_models_keep_unknown_fields(monkeypatch) -> None:
    created = SessionChildCreateResponse.model_validate(
        {
            "status": "created",
            "parentSessionId": "session-live",
            "childSessionId": "child-1",
            "childSession": {"id": "child-1", "customChild": True},
            "parentSession": {"id": "session-live", "customParent": True},
            "customCreate": True,
        }
    )
    created_dump = created.model_dump(exclude_unset=True)
    assert created_dump["childSession"]["customChild"] is True
    assert created_dump["customCreate"] is True

    approval = SessionToolApprovalItem.model_validate(
        {
            "requestId": "req-1",
            "sessionId": "session-live",
            "status": "pending",
            "customApproval": True,
        }
    )
    assert approval.model_dump(exclude_unset=True)["customApproval"] is True

    review = SessionChatReviewCandidateResponse.model_validate(
        {
            "candidateId": "cand-1",
            "sessionId": "session-live",
            "summary": "ok",
            "customReview": True,
        }
    )
    assert review.model_dump(exclude_unset=True)["customReview"] is True

    expected_children = [
        {
            "id": "child-1",
            "title": "child",
            "sessionKind": "child",
            "customChild": True,
        }
    ]
    monkeypatch.setattr(session_routes, "list_child_sessions", lambda *_args, **_kwargs: expected_children)
    listed = client.get("/api/sessions/session-live/child-sessions")
    assert listed.status_code == 200
    assert listed.json() == expected_children

    expected_created = {
        "status": "created",
        "parentSessionId": "session-live",
        "childSessionId": "child-1",
        "childSession": {"id": "child-1", "messages": [{"role": "user", "content": "hi"}]},
        "parentSession": {"id": "session-live", "customParent": True},
        "switched": False,
        "autoStarted": True,
        "customCreate": True,
    }
    monkeypatch.setattr(session_routes, "create_child_session", lambda *_args, **_kwargs: expected_created)
    created_response = client.post(
        "/api/sessions/session-live/child-sessions",
        json={"userRequest": "split", "taskTitle": "child", "autoStart": False},
    )
    assert created_response.status_code == 201
    assert created_response.json() == expected_created

    expected_approvals = [
        {
            "requestId": "req-1",
            "sessionId": "session-live",
            "status": "pending",
            "customApproval": True,
        }
    ]
    monkeypatch.setattr(
        session_routes,
        "list_tool_approval_requests",
        lambda *_args, **_kwargs: expected_approvals,
    )
    approvals = client.get("/api/sessions/session-live/tool-approvals?status=pending")
    assert approvals.status_code == 200
    assert approvals.json() == expected_approvals

    expected_review = {
        "candidateId": "cand-1",
        "sessionId": "session-live",
        "status": "queued",
        "topicSummary": "t",
        "turnCount": 2,
        "qualitySignals": ["ok"],
        "rawExcerptPath": "p",
        "summary": "s",
        "customReview": True,
    }
    monkeypatch.setattr(
        session_routes,
        "create_chat_review_candidate_from_session",
        lambda *_args, **_kwargs: expected_review,
    )
    review_response = client.post("/api/sessions/session-live/chat-review-candidate")
    assert review_response.status_code == 201
    assert review_response.json() == expected_review
