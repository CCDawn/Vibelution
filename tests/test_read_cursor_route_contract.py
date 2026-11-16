"""Contract tests for the read-cursor store and its HTTP routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes import read_cursors as route_module
from core.web.services import read_cursors


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(read_cursors, "READ_CURSOR_DB_PATH", tmp_path / "read_cursors.sqlite3")
    monkeypatch.setattr(read_cursors, "_SCHEMA_READY", False)
    return read_cursors


@pytest.fixture()
def client(store, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(route_module.router, prefix="/api")
    return TestClient(app)


def test_mark_read_upserts_and_never_moves_backwards(store) -> None:
    first = store.mark_read(
        [{"scopeKind": "conversation", "scopeId": "session-1", "readAt": "2026-01-02T00:00:00+00:00"}],
    )
    assert first == [
        {"scopeKind": "conversation", "scopeId": "session-1", "readAt": "2026-01-02T00:00:00+00:00"},
    ]
    store.mark_read(
        [{"scopeKind": "conversation", "scopeId": "session-1", "readAt": "2026-01-01T00:00:00+00:00"}],
    )
    assert store.list_read_cursors()[0]["readAt"] == "2026-01-02T00:00:00+00:00"


def test_mark_read_rejects_unknown_scope(store) -> None:
    with pytest.raises(ValueError):
        store.mark_read([{"scopeKind": "agent", "scopeId": "agent-1"}])


def test_route_round_trip(client: TestClient) -> None:
    response = client.post(
        "/api/read-cursors",
        json={
            "entries": [
                {"scopeKind": "team", "scopeId": "team-1", "readAt": "2026-01-02T00:00:00+00:00"},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["cursors"] == [
        {"scopeKind": "team", "scopeId": "team-1", "readAt": "2026-01-02T00:00:00+00:00"},
    ]

    snapshot = client.get("/api/read-cursors")
    assert snapshot.status_code == 200
    assert snapshot.json()["cursors"] == response.json()["cursors"]


def test_route_rejects_unknown_scope(client: TestClient) -> None:
    response = client.post(
        "/api/read-cursors",
        json={"entries": [{"scopeKind": "agent", "scopeId": "agent-1"}]},
    )
    assert response.status_code == 422
