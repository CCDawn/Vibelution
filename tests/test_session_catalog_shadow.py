from __future__ import annotations

from config.models import AppConfig
from core.chat.session_catalog import SessionCatalogStore
from core.web.services import session_service
from core.web.services.session import catalog_bridge
from tests.session_catalog_fixtures import build_session_query_summaries


def test_typed_config_allows_all_guarded_rollout_modes():
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
    assert (
        AppConfig.model_validate(
            {"session_catalog": {"mode": "read_preferred"}}
        ).session_catalog.mode
        == "read_preferred"
    )

    try:
        AppConfig.model_validate({"session_catalog": {"mode": "unknown"}})
    except ValueError as exc:
        assert "session_catalog.mode" in str(exc)
    else:
        raise AssertionError("unknown catalog modes must remain unavailable")


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


def test_sql_catalog_preserves_canonical_order_for_timestamps_and_title_ties(
    monkeypatch,
    tmp_path,
):
    """The SQLite candidate must preserve the legacy list's stable order."""

    def summary(session_id: str, *, title: str, updated_at: str) -> dict[str, str]:
        return {
            "id": session_id,
            "title": title,
            "taskTitle": title,
            "taskSummary": "bounded metadata",
            "agentId": "agent-a",
            "agentCode": "A001",
            "agentDisplayName": "Agent A",
            "dialogueModelId": "model-a",
            "sessionKind": "main",
            "status": "ready",
            "currentPhase": "idle",
            "childStatus": "",
            "conversationIndexVisibility": "user_visible",
            "updatedAt": updated_at,
            "lastActive": updated_at,
        }

    # This is the already-canonical legacy list order. The offset timestamp is
    # earlier than the UTC timestamp despite sorting later as raw text; the
    # same-title rows deliberately oppose lexical session-id tie breaking.
    summaries = [
        summary(
            "session-later-utc",
            title="Zulu",
            updated_at="2026-01-01T00:30:00Z",
        ),
        summary(
            "session-offset-earlier",
            title="same",
            updated_at="2026-01-01T01:00:00+01:00",
        ),
        summary(
            "session-z-title-tie",
            title="same",
            updated_at="2026-01-01T00:00:00Z",
        ),
        summary(
            "session-a-title-tie",
            title="same",
            updated_at="not-a-timestamp",
        ),
    ]
    snapshot = catalog_bridge.build_catalog_snapshot(
        summaries,
        {},
        workspace_key="workspace-test",
        indexed_at="2026-07-28T00:00:00Z",
    )
    store = SessionCatalogStore(
        tmp_path / "catalog" / "session_catalog.sqlite3",
        workspace_key="workspace-test",
    )
    store.initialize()
    reconcile_result = catalog_bridge.CatalogReconciler(
        store,
        source_loader=lambda: snapshot,
    ).reconcile(
        owner="test-order-parity",
        now="2026-07-28T00:00:00Z",
        lease_expires_at="2026-07-28T00:01:00Z",
    )
    assert reconcile_result.status == "complete"

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
    catalog_bridge.set_session_query_shadow_provider(
        catalog_bridge.build_session_catalog_query_provider(store)
    )
    try:
        for query_args in (
            {"sort": "updatedAt_desc", "limit": 2},
            {"sort": "updatedAt_desc", "cursor": "2", "limit": 2},
            {"sort": "updatedAt_asc", "limit": 4},
            {"sort": "title_asc", "limit": 4},
            {"sort": "title_desc", "limit": 4},
        ):
            legacy = session_service.query_sessions(**query_args)
            request = {
                "q": "",
                "agent_id": "",
                "session_kind": "",
                "state": "",
                "sort": query_args["sort"],
                "limit": query_args["limit"],
                "cursor": query_args.get("cursor", ""),
            }

            comparison = catalog_bridge.run_session_query_shadow(
                legacy,
                request=request,
            )

            assert comparison.status == "match", query_args
    finally:
        catalog_bridge.set_session_query_shadow_provider(None)


def test_session_query_cache_lookup_never_runs_collision_repair(monkeypatch):
    monkeypatch.setattr(session_service, "_sync_agent_directory_project_root", lambda: None)
    monkeypatch.setattr(session_service, "_session_list_source_signature", lambda: ("source",))

    def should_not_repair(**_kwargs):
        raise AssertionError("query must not repair")

    monkeypatch.setattr(
        session_service,
        "_repair_agent_direct_session_collisions",
        should_not_repair,
    )
    monkeypatch.setattr(session_service, "_get_session_list_cache", lambda **_kwargs: None)

    assert session_service._get_cached_session_query_sessions(now=0.0) is None


def test_session_query_cache_miss_loads_without_legacy_repair(monkeypatch):
    summaries = build_session_query_summaries(2)
    observed_repair_flags: list[bool] = []
    monkeypatch.setattr(session_service, "get_config", lambda: AppConfig())
    monkeypatch.setattr(session_service, "_get_cached_session_query_sessions", lambda **_kwargs: None)
    monkeypatch.setattr(session_service, "_record_session_list_query_event", lambda **_kwargs: None)

    def load_sessions(*, repair_collisions=True, **_kwargs):
        observed_repair_flags.append(bool(repair_collisions))
        return summaries

    monkeypatch.setattr(session_service, "list_sessions", load_sessions)

    payload = session_service.query_sessions(limit=1)

    assert payload["items"] == summaries[:1]
    assert observed_repair_flags == [False]


def test_session_list_prewarm_loads_without_legacy_repair(monkeypatch):
    summaries = build_session_query_summaries(2)
    observed_repair_flags: list[bool] = []
    monkeypatch.setattr(session_service, "_record_session_list_prewarm_event", lambda **_kwargs: None)

    def load_sessions(*, repair_collisions=True, **_kwargs):
        observed_repair_flags.append(bool(repair_collisions))
        return summaries

    monkeypatch.setattr(session_service, "list_sessions", load_sessions)

    result = session_service.prewarm_session_list_cache(reason="test")

    assert result["status"] == "completed"
    assert observed_repair_flags == [False]


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


def test_read_preferred_serves_catalog_without_loading_legacy_projection(monkeypatch):
    summaries = build_session_query_summaries(3)
    observed_reads: list[dict] = []
    observed_requests: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "get_config",
        lambda: AppConfig.model_validate(
            {"session_catalog": {"mode": "read_preferred"}}
        ),
    )
    monkeypatch.setattr(
        session_service,
        "_get_cached_session_query_sessions",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("fresh catalog reads must not load the legacy projection")
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

    def catalog_page(request):
        observed_requests.append(dict(request))
        return {
            "items": [dict(summaries[0])],
            "nextCursor": "1",
            "totalEstimate": len(summaries),
        }

    catalog_bridge.set_session_query_shadow_provider(catalog_page)
    try:
        payload = session_service.query_sessions(limit=1, q="needle")
    finally:
        catalog_bridge.set_session_query_shadow_provider(None)

    assert payload == {
        "items": [summaries[0]],
        "nextCursor": "1",
        "totalEstimate": len(summaries),
        "filters": {
            "q": "needle",
            "agentId": "",
            "sessionKind": "",
            "state": "",
            "sort": "updatedAt_desc",
            "limit": 1,
            "cursor": "",
        },
    }
    assert observed_requests == [
        {
            "limit": 1,
            "cursor": "",
            "q": "needle",
            "agent_id": "",
            "session_kind": "",
            "state": "",
            "sort": "updatedAt_desc",
        }
    ]
    assert observed_reads[-1]["source"] == "catalog"
    assert observed_reads[-1]["catalog_status"] == "healthy"


def test_read_preferred_provider_failure_returns_exact_legacy_payload(monkeypatch):
    summaries = build_session_query_summaries(3)
    observed_reads: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "get_config",
        lambda: AppConfig.model_validate(
            {"session_catalog": {"mode": "read_preferred"}}
        ),
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
    monkeypatch.setattr(
        session_service,
        "_record_session_catalog_read_event",
        lambda **kwargs: observed_reads.append(kwargs),
        raising=False,
    )

    def fail_catalog(_request):
        raise RuntimeError("private catalog failure")

    catalog_bridge.set_session_query_shadow_provider(fail_catalog)
    try:
        payload = session_service.query_sessions(limit=1)
    finally:
        catalog_bridge.set_session_query_shadow_provider(None)

    assert payload["items"] == summaries[:1]
    assert payload["nextCursor"] == "1"
    assert payload["totalEstimate"] == len(summaries)
    assert observed_reads[-1]["source"] == "legacy"
    assert observed_reads[-1]["catalog_status"] == "degraded"
    assert observed_reads[-1]["error_type"] == "RuntimeError"
    assert "private" not in repr(observed_reads[-1])


def test_read_preferred_invalid_catalog_payload_returns_legacy_payload(monkeypatch):
    summaries = build_session_query_summaries(3)
    observed_reads: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "get_config",
        lambda: AppConfig.model_validate(
            {"session_catalog": {"mode": "read_preferred"}}
        ),
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
    monkeypatch.setattr(
        session_service,
        "_record_session_catalog_read_event",
        lambda **kwargs: observed_reads.append(kwargs),
        raising=False,
    )
    catalog_bridge.set_session_query_shadow_provider(
        lambda _request: {
            "items": [dict(summaries[0])],
            "nextCursor": "",
            "totalEstimate": "invalid",
        }
    )
    try:
        payload = session_service.query_sessions(limit=1)
    finally:
        catalog_bridge.set_session_query_shadow_provider(None)

    assert payload["items"] == summaries[:1]
    assert payload["totalEstimate"] == len(summaries)
    assert observed_reads[-1]["source"] == "legacy"
    assert observed_reads[-1]["catalog_status"] == "degraded"
    assert observed_reads[-1]["error_type"]


def test_read_preferred_invalid_catalog_page_contract_returns_legacy_payload(monkeypatch):
    summaries = build_session_query_summaries(3)
    observed_reads: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "get_config",
        lambda: AppConfig.model_validate(
            {"session_catalog": {"mode": "read_preferred"}}
        ),
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
    monkeypatch.setattr(
        session_service,
        "_record_session_catalog_read_event",
        lambda **kwargs: observed_reads.append(kwargs),
        raising=False,
    )
    invalid_pages = (
        {
            "items": [dict(summaries[0])],
            "nextCursor": "not-a-cursor",
            "totalEstimate": len(summaries),
        },
        {
            "items": [{**summaries[0], "id": ""}],
            "nextCursor": "1",
            "totalEstimate": len(summaries),
        },
    )
    for invalid_page in invalid_pages:
        catalog_bridge.set_session_query_shadow_provider(
            lambda _request, page=invalid_page: page
        )
        try:
            payload = session_service.query_sessions(limit=1)
        finally:
            catalog_bridge.set_session_query_shadow_provider(None)

        assert payload["items"] == summaries[:1]
        assert payload["nextCursor"] == "1"
        assert payload["totalEstimate"] == len(summaries)
        assert observed_reads[-1]["source"] == "legacy"
        assert observed_reads[-1]["catalog_status"] == "degraded"
        assert observed_reads[-1]["error_type"]


def test_read_preferred_without_catalog_provider_returns_legacy_payload(monkeypatch):
    summaries = build_session_query_summaries(2)
    observed_reads: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "get_config",
        lambda: AppConfig.model_validate(
            {"session_catalog": {"mode": "read_preferred"}}
        ),
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
    monkeypatch.setattr(
        session_service,
        "_record_session_catalog_read_event",
        lambda **kwargs: observed_reads.append(kwargs),
        raising=False,
    )
    catalog_bridge.set_session_query_shadow_provider(None)

    payload = session_service.query_sessions(limit=1)

    assert payload["items"] == summaries[:1]
    assert payload["totalEstimate"] == len(summaries)
    assert observed_reads[-1]["source"] == "legacy"
    assert observed_reads[-1]["catalog_status"] == "disabled"
    assert observed_reads[-1]["error_type"] == ""


def test_read_preferred_fallback_event_never_contains_session_content(monkeypatch):
    observed: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: observed.append((args, kwargs)),
    )

    session_service._record_session_catalog_read_event(
        source="legacy",
        catalog_status="degraded",
        error_type="RuntimeError",
        result_count=1,
        matched_count=3,
        total_count=5,
        limit=20,
        cursor=0,
        has_query=True,
        has_agent_filter=False,
        has_kind_filter=False,
        has_state_filter=False,
        sort="updatedAt_desc",
        elapsed_ms=8,
    )

    args, kwargs = observed[-1]
    assert args[2] == "session_catalog.fallback"
    assert kwargs["outcome"] == "fallback"
    assert kwargs["fields"]["errorType"] == "RuntimeError"
    assert "private" not in repr(observed[-1])
    assert "session-" not in repr(observed[-1])


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
