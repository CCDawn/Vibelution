from __future__ import annotations

from config.models import AppConfig
from core.web.services import session_service
from core.web.services.session import catalog_bridge
from tests.session_catalog_fixtures import build_session_query_summaries


def test_typed_config_allows_only_off_or_shadow_before_canary():
    assert AppConfig().session_catalog.mode == "off"
    assert (
        AppConfig.model_validate(
            {
                "session_catalog": {
                    "mode": "SHADOW",
                    "reconcile_on_startup": False,
                    "busy_timeout_ms": 250,
                }
            }
        ).session_catalog.mode
        == "shadow"
    )

    try:
        AppConfig.model_validate({"session_catalog": {"mode": "read_preferred"}})
    except ValueError as exc:
        assert "session_catalog.mode" in str(exc)
    else:
        raise AssertionError("read_preferred must remain unavailable before the canary stage")


def test_shadow_comparator_reports_only_bounded_contract_mismatches():
    legacy = {
        "items": [
            {
                "id": "session-a",
                "title": "private legacy title",
                "status": "ready",
                "currentPhase": "idle",
                "sessionKind": "main",
                "conversationIndexVisibility": "normal",
            }
        ],
        "nextCursor": "",
        "totalEstimate": 1,
    }
    candidate = {
        "items": [
            {
                "id": "session-b",
                "title": "private candidate title",
                "status": "running",
                "currentPhase": "model_request",
                "sessionKind": "main",
                "conversationIndexVisibility": "normal",
            }
        ],
        "nextCursor": "1",
        "totalEstimate": 2,
    }

    comparison = catalog_bridge.compare_session_query_payloads(legacy, candidate)

    assert comparison.status == "mismatch"
    assert set(comparison.mismatch_kinds) == {
        "item_ids",
        "item_state",
        "next_cursor",
        "total_estimate",
    }
    assert "private" not in repr(comparison)
    assert not hasattr(comparison, "items")


def test_query_shadow_match_never_changes_legacy_response(monkeypatch):
    summaries = build_session_query_summaries(5)
    monkeypatch.setattr(
        session_service,
        "get_config",
        lambda: AppConfig.model_validate({"session_catalog": {"mode": "shadow"}}),
    )
    monkeypatch.setattr(
        session_service,
        "_get_cached_session_query_sessions",
        lambda **_kwargs: [dict(item) for item in summaries],
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_list_query_event",
        lambda **_kwargs: None,
    )
    observed = []
    real_run = catalog_bridge.run_session_query_shadow

    def capture_shadow(*args, **kwargs):
        result = real_run(*args, **kwargs)
        observed.append(result)
        return result

    monkeypatch.setattr(catalog_bridge, "run_session_query_shadow", capture_shadow)
    catalog_bridge.set_session_query_shadow_provider(
        lambda request: {
            "items": summaries[: int(request["limit"])],
            "nextCursor": str(request["limit"]),
            "totalEstimate": len(summaries),
        }
    )
    try:
        payload = session_service.query_sessions(limit=2)
    finally:
        catalog_bridge.set_session_query_shadow_provider(None)

    assert [item["id"] for item in payload["items"]] == [
        item["id"] for item in summaries[:2]
    ]
    assert observed[-1].status == "match"


def test_query_shadow_records_only_bounded_comparison_evidence(monkeypatch):
    summaries = build_session_query_summaries(2)
    monkeypatch.setattr(
        session_service,
        "get_config",
        lambda: AppConfig.model_validate({"session_catalog": {"mode": "shadow"}}),
    )
    monkeypatch.setattr(
        session_service,
        "_get_cached_session_query_sessions",
        lambda **_kwargs: [dict(item) for item in summaries],
    )
    monkeypatch.setattr(session_service, "_record_session_list_query_event", lambda **_kwargs: None)
    observed: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_record_session_catalog_shadow_query_event",
        lambda **kwargs: observed.append(kwargs),
        raising=False,
    )
    catalog_bridge.set_session_query_shadow_provider(
        lambda _request: {
            "items": [
                {
                    "id": "different-session",
                    "title": "private candidate title",
                    "status": "running",
                }
            ],
            "nextCursor": "",
            "totalEstimate": 1,
        }
    )
    try:
        payload = session_service.query_sessions(limit=1)
    finally:
        catalog_bridge.set_session_query_shadow_provider(None)

    assert payload["items"] == summaries[:1]
    assert observed[-1]["comparison"].status == "mismatch"
    assert observed[-1]["limit"] == 1
    assert "private" not in repr(observed[-1])


def test_shadow_query_runtime_event_never_contains_session_content(monkeypatch):
    observed: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *_args, **kwargs: observed.append(kwargs),
    )
    comparison = catalog_bridge.compare_session_query_payloads(
        {
            "items": [{"id": "session-a", "title": "private legacy title", "status": "ready"}],
            "nextCursor": "",
            "totalEstimate": 1,
        },
        {
            "items": [{"id": "session-b", "title": "private catalog title", "status": "running"}],
            "nextCursor": "",
            "totalEstimate": 1,
        },
    )

    session_service._record_session_catalog_shadow_query_event(
        comparison=comparison,
        limit=20,
        cursor=0,
        has_query=True,
        has_agent_filter=False,
        has_kind_filter=False,
        has_state_filter=False,
        sort="updatedAt_desc",
    )

    fields = observed[-1]["fields"]
    assert observed[-1]["outcome"] == "mismatch"
    assert fields["mismatchKinds"] == ["item_ids", "item_state"]
    assert fields["legacyCount"] == 1
    assert fields["candidateCount"] == 1
    assert "private" not in repr(observed[-1])
    assert "session-a" not in repr(observed[-1])
    assert "session-b" not in repr(observed[-1])


def test_shadow_provider_failure_falls_back_to_exact_legacy_payload(monkeypatch):
    summaries = build_session_query_summaries(3)
    monkeypatch.setattr(
        session_service,
        "get_config",
        lambda: AppConfig.model_validate({"session_catalog": {"mode": "shadow"}}),
    )
    monkeypatch.setattr(
        session_service,
        "_get_cached_session_query_sessions",
        lambda **_kwargs: [dict(item) for item in summaries],
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_list_query_event",
        lambda **_kwargs: None,
    )
    observed = []
    real_run = catalog_bridge.run_session_query_shadow

    def capture_shadow(*args, **kwargs):
        result = real_run(*args, **kwargs)
        observed.append(result)
        return result

    def fail_catalog(_request):
        raise RuntimeError("catalog unavailable with private details")

    monkeypatch.setattr(catalog_bridge, "run_session_query_shadow", capture_shadow)
    catalog_bridge.set_session_query_shadow_provider(fail_catalog)
    try:
        payload = session_service.query_sessions(limit=2)
    finally:
        catalog_bridge.set_session_query_shadow_provider(None)

    assert payload["items"] == summaries[:2]
    assert payload["totalEstimate"] == 3
    assert observed[-1].status == "degraded"
    assert observed[-1].error_type == "RuntimeError"
    assert "private details" not in repr(observed[-1])


def test_off_mode_never_invokes_registered_shadow_provider(monkeypatch):
    summaries = build_session_query_summaries(2)
    monkeypatch.setattr(session_service, "get_config", lambda: AppConfig())
    monkeypatch.setattr(
        session_service,
        "_get_cached_session_query_sessions",
        lambda **_kwargs: [dict(item) for item in summaries],
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_list_query_event",
        lambda **_kwargs: None,
    )

    def should_not_run(_request):
        raise AssertionError("off mode must not invoke the catalog")

    catalog_bridge.set_session_query_shadow_provider(should_not_run)
    try:
        payload = session_service.query_sessions(limit=1)
    finally:
        catalog_bridge.set_session_query_shadow_provider(None)

    assert payload["items"] == summaries[:1]
