from __future__ import annotations

from fastapi.testclient import TestClient

from core.infrastructure import developer_sandbox
from core.llm.usage_ledger import UsageLedgerEvent, record_usage_event
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token


def test_usage_summary_route_returns_codex_style_global_summary(tmp_path, monkeypatch):
    _isolate_usage_workspace(tmp_path, monkeypatch)
    client = _client()
    record_usage_event(
        UsageLedgerEvent(
            source="provider_usage",
            scope_kind="chat_session",
            session_id="session-api",
            provider="openai",
            model="gpt-5",
            input_tokens=100,
            cached_input_tokens=25,
            cache_read_input_tokens=25,
            uncached_input_tokens=75,
            output_tokens=50,
            reasoning_output_tokens=10,
            total_tokens=150,
        ),
        project_root=tmp_path,
    )

    response = client.get("/api/usage/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["lastTokenUsage"]["totalTokens"] == 150
    assert payload["globalTokenUsage"]["allTime"]["inputTokens"] == 100
    assert payload["globalTokenUsage"]["allTime"]["cachedInputTokens"] == 25
    assert payload["globalTokenUsage"]["allTime"]["reasoningOutputTokens"] == 10
    assert payload["globalTokenUsage"]["allTime"]["cacheHitRate"] == 0.25
    assert payload["diagnostics"]["source"] == "usage_ledger"
    assert payload["updatedAt"]
    assert payload["breakdowns"] == {"models": [], "providers": [], "sources": []}


def test_usage_summary_route_filters_by_session(tmp_path, monkeypatch):
    _isolate_usage_workspace(tmp_path, monkeypatch)
    client = _client()
    record_usage_event(
        UsageLedgerEvent(source="provider_usage", session_id="a", input_tokens=10, output_tokens=1, total_tokens=11),
        project_root=tmp_path,
    )
    record_usage_event(
        UsageLedgerEvent(source="provider_usage", session_id="b", input_tokens=20, output_tokens=2, total_tokens=22),
        project_root=tmp_path,
    )

    response = client.get("/api/usage/summary?scope=session&sessionId=b")

    assert response.status_code == 200
    assert response.json()["sessionTokenUsage"]["totalTokens"] == 22


def test_usage_summary_route_rejects_missing_session_id():
    client = _client()

    response = client.get("/api/usage/summary?scope=session")

    assert response.status_code == 400
    assert "sessionId" in response.json()["detail"]


def test_usage_summary_route_rejects_missing_model_filter():
    client = _client()

    response = client.get("/api/usage/summary?scope=model")

    assert response.status_code == 400
    assert "provider or model" in response.json()["detail"]


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _isolate_usage_workspace(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: tmp_path / "workspace")
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
