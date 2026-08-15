"""S4 contract: chat-room JSON routes are typed without rewriting room documents."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import chat_rooms as chat_room_routes
from core.web.routes.chat_room_models import (
    ChatRoomCatalogOption,
    ChatRoomDeleteResponse,
    ChatRoomDetailResponse,
    ChatRoomRoundResponse,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_ROOMS_ROUTE = REPO_ROOT / "core" / "web" / "routes" / "chat_rooms.py"

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

JSON_ROUTE_FUNCTIONS = {
    "chat_room_modes",
    "chat_room_purposes",
    "chat_room_list",
    "chat_room_create",
    "chat_room_detail",
    "chat_room_update",
    "chat_room_delete",
    "chat_room_reset",
    "chat_room_start_round",
    "chat_room_stop_round",
}


def _route_decorators() -> dict[str, ast.Call]:
    tree = ast.parse(CHAT_ROOMS_ROUTE.read_text(encoding="utf-8"))
    found: dict[str, ast.Call] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                found[node.name] = decorator
    return found


def test_chat_room_json_routes_declare_response_model() -> None:
    decorators = _route_decorators()
    missing = []
    for name in sorted(JSON_ROUTE_FUNCTIONS):
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
    assert missing == [], f"chat-room JSON routes must declare response_model: {missing}"


def test_chat_room_events_declares_streaming_response_class() -> None:
    decorator = _route_decorators()["chat_room_events"]
    has_response_class = False
    for keyword in decorator.keywords:
        if keyword.arg != "response_class":
            continue
        if isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
            continue
        has_response_class = True
    assert has_response_class, "GET /chat-rooms/{id}/events must declare response_class"


def test_chat_room_response_models_keep_unknown_fields(monkeypatch) -> None:
    option = ChatRoomCatalogOption.model_validate(
        {"id": "round_robin", "label": "Round robin", "status": "ready", "customFlag": True}
    )
    option_dump = option.model_dump(exclude_unset=True)
    assert option_dump["customFlag"] is True
    assert option_dump["status"] == "ready"

    detail = ChatRoomDetailResponse.model_validate(
        {
            "roomId": "room-live",
            "title": "live",
            "participants": [{"sessionId": "s1", "enabled": True}],
            "rounds": [{"roundId": "r1", "customRound": True}],
            "customDetailFlag": True,
        }
    )
    detail_dump = detail.model_dump(exclude_unset=True)
    assert detail_dump["participants"] == [{"sessionId": "s1", "enabled": True}]
    assert detail_dump["customDetailFlag"] is True
    assert "status" not in detail_dump

    accepted = ChatRoomRoundResponse.model_validate(
        {
            "accepted": True,
            "roomId": "room-live",
            "roundId": "round-1",
            "activeRoundId": "round-1",
            "status": "running",
            "acceptedAt": "now",
            "customAccept": True,
        }
    )
    accepted_dump = accepted.model_dump(exclude_unset=True)
    assert accepted_dump["customAccept"] is True
    assert "title" not in accepted_dump

    full_round = ChatRoomRoundResponse.model_validate(
        {
            "roomId": "room-live",
            "title": "live",
            "participants": [{"sessionId": "s1"}],
            "customDetailFlag": True,
        }
    )
    full_round_dump = full_round.model_dump(exclude_unset=True)
    assert full_round_dump["customDetailFlag"] is True
    assert "accepted" not in full_round_dump

    deleted = ChatRoomDeleteResponse.model_validate(
        {"deleted": True, "roomId": "room-live", "customDelete": True}
    )
    assert deleted.model_dump(exclude_unset=True)["customDelete"] is True

    expected_detail = {
        "roomId": "room-live",
        "title": "live",
        "participants": [{"sessionId": "s1", "enabled": True}],
        "rounds": [{"roundId": "r1"}],
        "customDetailFlag": True,
    }
    monkeypatch.setattr(chat_room_routes, "get_chat_room_detail", lambda *_args, **_kwargs: expected_detail)
    monkeypatch.setattr(chat_room_routes, "list_chat_rooms", lambda: [expected_detail])
    monkeypatch.setattr(
        chat_room_routes,
        "list_chat_room_modes",
        lambda: [{"id": "round_robin", "label": "Round robin", "status": "ready", "customFlag": True}],
    )

    listed = client.get("/api/chat-rooms")
    assert listed.status_code == 200
    assert listed.json()[0] == expected_detail

    detail_response = client.get("/api/chat-rooms/room-live")
    assert detail_response.status_code == 200
    assert detail_response.json() == expected_detail
    assert "status" not in detail_response.json()

    modes = client.get("/api/chat-rooms/modes")
    assert modes.status_code == 200
    assert modes.json()[0]["customFlag"] is True

    expected_accept = {
        "accepted": True,
        "roomId": "room-live",
        "roundId": "round-1",
        "activeRoundId": "round-1",
        "status": "running",
        "topic": "go",
        "mode": "round_robin",
        "purpose": "discussion",
        "speakerOrder": ["s1"],
        "acceptedAt": "now",
        "customAccept": True,
    }
    monkeypatch.setattr(
        chat_room_routes,
        "start_chat_room_round",
        lambda *_args, **_kwargs: expected_accept,
    )
    accepted_response = client.post(
        "/api/chat-rooms/room-live/rounds",
        json={"topic": "go", "mode": "round_robin", "purpose": "discussion"},
        headers={"Prefer": "respond-async"},
    )
    assert accepted_response.status_code == 202
    assert accepted_response.json() == expected_accept
    assert "title" not in accepted_response.json()
