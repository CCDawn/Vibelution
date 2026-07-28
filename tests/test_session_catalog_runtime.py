from __future__ import annotations

import time

import pytest

from config.models import AppConfig
from core.chat.session_catalog import resolve_session_catalog_path
from core.ui.chat_state import save_chat_state
from core.web.services import session_service
from core.web.services.session import catalog_bridge, catalog_runtime
from core.web.services.session.catalog_runtime import initialize_session_catalog_runtime
from tests.session_catalog_fixtures import build_session_query_summaries


@pytest.fixture(autouse=True)
def _isolated_catalog_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    monkeypatch.setattr(
        catalog_runtime.developer_sandbox,
        "is_developer_mode_enabled",
        lambda: False,
    )
    monkeypatch.setattr(catalog_runtime, "record_runtime_scene_event", lambda *_args, **_kwargs: {})
    catalog_bridge.set_session_query_shadow_provider(None)
    yield
    catalog_runtime.shutdown_session_catalog_runtime()


@pytest.mark.parametrize("mode", ["shadow", "read_preferred"])
def test_catalog_runtime_rebuilds_and_registers_sql_provider(tmp_path, mode):
    summaries = build_session_query_summaries(5)
    config = AppConfig.model_validate(
        {"session_catalog": {"mode": mode, "incremental_reconcile_delay_ms": 150}}
    ).session_catalog

    status = initialize_session_catalog_runtime(
        project_root=tmp_path,
        catalog_config=config,
        summary_loader=lambda: summaries,
    )

    workspace = catalog_runtime._active_workspace_root(tmp_path)
    catalog_path = resolve_session_catalog_path(
        workspace,
        environment="formal",
        local_app_data=tmp_path / "local-app-data",
        project_root=tmp_path,
    )
    comparison = catalog_bridge.run_session_query_shadow(
        {
            "items": summaries[:2],
            "nextCursor": "2",
            "totalEstimate": len(summaries),
        },
        request={"limit": 2, "sort": "updatedAt_desc"},
    )

    assert status.status == "ready"
    assert status.session_count == len(summaries)
    assert catalog_path.exists()
    assert comparison.status == "match"
    assert not (workspace / "chat" / "chat_state.json").exists()

    save_chat_state(tmp_path, {"version": 1, "conversations": []})
    stale = catalog_bridge.run_session_query_shadow(
        {"items": summaries[:2], "nextCursor": "2", "totalEstimate": len(summaries)},
        request={"limit": 2, "sort": "updatedAt_desc"},
    )

    assert stale.status == "degraded"

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        refreshed = catalog_bridge.run_session_query_shadow(
            {"items": summaries[:2], "nextCursor": "2", "totalEstimate": len(summaries)},
            request={"limit": 2, "sort": "updatedAt_desc"},
        )
        if refreshed.status == "match":
            break
        time.sleep(0.01)

    assert refreshed.status == "match"


def test_read_preferred_runtime_serves_sql_provider_without_legacy_projection(
    tmp_path,
    monkeypatch,
):
    summaries = build_session_query_summaries(5)
    app_config = AppConfig.model_validate(
        {"session_catalog": {"mode": "read_preferred"}}
    )
    status = initialize_session_catalog_runtime(
        project_root=tmp_path,
        catalog_config=app_config.session_catalog,
        summary_loader=lambda: summaries,
    )
    observed_reads: list[dict] = []
    monkeypatch.setattr(session_service, "get_config", lambda: app_config)
    monkeypatch.setattr(
        session_service,
        "_get_cached_session_query_sessions",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("fresh read_preferred queries must not load legacy projection")
        ),
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_list_query_event",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_catalog_read_event",
        lambda **kwargs: observed_reads.append(kwargs),
        raising=False,
    )

    payload = session_service.query_sessions(limit=2, q="needle")

    assert status.status == "ready"
    assert payload["items"] == [summaries[-1]]
    assert payload["nextCursor"] == ""
    assert payload["totalEstimate"] == 1
    assert observed_reads[-1]["source"] == "catalog"
    assert observed_reads[-1]["catalog_status"] == "healthy"


def test_off_runtime_keeps_shadow_provider_disabled(tmp_path):
    status = initialize_session_catalog_runtime(
        project_root=tmp_path,
        catalog_config=AppConfig().session_catalog,
        summary_loader=lambda: build_session_query_summaries(1),
    )

    comparison = catalog_bridge.run_session_query_shadow(
        {"items": [], "nextCursor": "", "totalEstimate": 0},
        request={"limit": 1},
    )

    assert status.status == "disabled"
    assert comparison.status == "disabled"


def test_runtime_shutdown_removes_candidate_provider(tmp_path):
    config = AppConfig.model_validate({"session_catalog": {"mode": "shadow"}}).session_catalog
    status = initialize_session_catalog_runtime(
        project_root=tmp_path,
        catalog_config=config,
        summary_loader=lambda: build_session_query_summaries(1),
    )

    catalog_runtime.shutdown_session_catalog_runtime()
    comparison = catalog_bridge.run_session_query_shadow(
        {"items": [], "nextCursor": "", "totalEstimate": 0},
        request={"limit": 1},
    )

    assert status.status == "ready"
    assert comparison.status == "disabled"


def test_shadow_runtime_source_failure_degrades_to_legacy(tmp_path):
    config = AppConfig.model_validate({"session_catalog": {"mode": "shadow"}}).session_catalog

    def fail_source_loader():
        raise RuntimeError("source failed")

    status = initialize_session_catalog_runtime(
        project_root=tmp_path,
        catalog_config=config,
        summary_loader=fail_source_loader,
    )
    comparison = catalog_bridge.run_session_query_shadow(
        {"items": [], "nextCursor": "", "totalEstimate": 0},
        request={"limit": 1},
    )

    assert status.status == "degraded"
    assert status.error_type == "RuntimeError"
    assert comparison.status == "disabled"


def test_default_runtime_source_loader_disables_legacy_repairs(monkeypatch, tmp_path):
    observed_options: list[bool] = []
    summaries = build_session_query_summaries(2)
    config = AppConfig.model_validate({"session_catalog": {"mode": "shadow"}}).session_catalog

    def load_sessions(*, repair_collisions=True, **_kwargs):
        observed_options.append(bool(repair_collisions))
        return summaries

    monkeypatch.setattr(session_service, "list_sessions", load_sessions)

    status = initialize_session_catalog_runtime(
        project_root=tmp_path,
        catalog_config=config,
    )

    assert status.status == "ready"
    assert observed_options == [False, False, False]
