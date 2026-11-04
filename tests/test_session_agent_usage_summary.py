"""Explicit Session/Agent intersection without changing legacy usage scopes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.llm import usage_ledger
from core.web.routes import usage as usage_routes


def _record(session_id, agent_id, tokens, cached, order, *, provider="provider-a", model="model-a"):
    usage_ledger.record_usage_event(usage_ledger.UsageLedgerEvent(
        event_id=f"event-{order}", recorded_at=f"2026-11-04T10:00:{order:02d}Z", source="provider_usage",
        session_id=session_id, agent_id=agent_id, provider=provider, model=model,
        input_tokens=tokens, cached_input_tokens=cached, cache_read_input_tokens=cached,
        total_tokens=tokens, cache_usage_observed=True,
    ))


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(usage_ledger, "PROJECT_ROOT", tmp_path)
    _record("session-a", "foreign-agent", 10000, 10000, 1)
    _record("session-a", "agent-a", 100, 100, 2)
    _record("other-session", "agent-a", 400, 400, 3)
    _record("session-a", "agent-a", 900, 0, 4)


def test_joint_scope_excludes_earlier_foreign_agents_and_other_sessions_from_both_views(ledger):
    summary = usage_ledger.build_usage_summary(scope="session_agent", session_id="session-a", agent_id="agent-a")
    rollup = summary["sessionTokenUsage"]
    assert summary["scope"] == "session_agent"
    assert summary["scopeTokenUsage"] == rollup
    assert rollup["callCount"] == 2
    assert rollup["inputTokens"] == rollup["cacheObservedInputTokens"] == 1000
    assert rollup["cachedInputTokens"] == 100
    assert rollup["cacheHitRate"] == 0.1
    assert summary["lastTokenUsage"]["eventId"] == "event-4"
    assert summary["lastTokenUsage"]["sessionId"] == "session-a"
    assert summary["lastTokenUsage"]["agentId"] == "agent-a"
    assert summary["lastTokenUsage"]["cacheHitRate"] == 0

    # A later foreign-Agent call in the same Session must not replace either view.
    _record("session-a", "foreign-agent", 50, 50, 5)
    again = usage_ledger.build_usage_summary(scope="session_agent", session_id="session-a", agent_id="agent-a")
    assert again["sessionTokenUsage"] == rollup
    assert again["lastTokenUsage"] == summary["lastTokenUsage"]


def test_joint_scope_keeps_provider_and_model_filters_on_cumulative_and_last_usage(ledger):
    _record("session-a", "agent-a", 200, 200, 5, provider="provider-b", model="model-b")
    summary = usage_ledger.build_usage_summary(scope="session_agent", session_id="session-a", agent_id="agent-a",
                                              provider="provider-a", model="model-a")
    assert summary["sessionTokenUsage"]["callCount"] == 2
    assert summary["sessionTokenUsage"]["cacheHitRate"] == 0.1
    assert summary["lastTokenUsage"]["eventId"] == "event-4"


def test_joint_scope_has_no_global_or_other_agent_fallback_for_an_empty_intersection(ledger):
    summary = usage_ledger.build_usage_summary(scope="session_agent", session_id="session-a", agent_id="missing-agent")
    assert summary["sessionTokenUsage"]["callCount"] == 0
    assert summary["sessionTokenUsage"]["cacheUsageObserved"] is False
    assert summary["lastTokenUsage"]["source"] == "not_called"
    assert summary["scopeTokenUsage"] == summary["sessionTokenUsage"]


def test_joint_cache_numerator_uses_the_same_provider_rows_as_its_denominator(tmp_path, monkeypatch):
    from core.llm.client import _record_usage_ledger_event
    from core.llm.usage import usage_stats_from_payload

    monkeypatch.setattr(usage_ledger, "PROJECT_ROOT", tmp_path)
    usage = usage_stats_from_payload({"prompt_tokens": 100, "completion_tokens": 0,
                                      "prompt_tokens_details": {"cached_tokens": 25}})
    common = {"usage": usage, "metadata": {"sessionId": "session-estimate", "agentId": "agent-estimate"},
              "provider": "provider-a", "model": "model-a", "profile_id": "profile-a", "transport": "test"}
    _record_usage_ledger_event(**common)
    # The real finalize path retains provider cache observations when output
    # estimation makes the overall event's source "estimated".
    _record_usage_ledger_event(**common, estimated_output_tokens=10)

    summary = usage_ledger.build_usage_summary(scope="session_agent", session_id="session-estimate", agent_id="agent-estimate")
    rollup = summary["sessionTokenUsage"]
    assert rollup["inputTokens"] == 200
    assert rollup["cachedInputTokens"] == rollup["cacheReadInputTokens"] == 25
    assert rollup["cacheObservedInputTokens"] == 100
    assert rollup["cacheHitRate"] == 0.25
    assert rollup["callCount"] == 2
    assert rollup["estimatedCallCount"] == 1
    assert rollup["cacheObservedCallCount"] == rollup["cacheUnobservedCallCount"] == 1
    assert rollup["cacheUsageComplete"] is False
    assert rollup["cacheUsageMissingReason"] == "partial_provider_cache_usage"
    assert summary["scopeTokenUsage"] == rollup
    assert not any(key.startswith("provider_") for key in rollup)
    # Keep the actual latest source visible so consumers cannot mistake an
    # estimated call for the earlier provider-confirmed call.
    assert summary["lastTokenUsage"]["source"] == "estimated"
    assert summary["lastTokenUsage"]["cacheUsageObserved"] is True
    assert summary["lastTokenUsage"]["outputTokens"] == 10

    for scope in ("session", "global", "agent", "model"):
        legacy = usage_ledger.build_usage_summary(scope=scope, session_id="session-estimate", agent_id="agent-estimate",
                                                 provider="provider-a", model="model-a")
        assert legacy["scopeTokenUsage"]["cachedInputTokens"] == 50
        assert legacy["scopeTokenUsage"]["cacheReadInputTokens"] == 50
        assert legacy["scopeTokenUsage"]["cacheHitRate"] == 0.5
        assert legacy["scopeTokenUsage"]["cacheUnobservedCallCount"] == 0
        assert legacy["scopeTokenUsage"]["cacheUsageComplete"] is True
        assert legacy["lastTokenUsage"] == summary["lastTokenUsage"]


@pytest.mark.parametrize("source,observed,unobserved", [
    ("estimated", True, 1), ("estimated", False, 1), ("missing", False, 1), ("not_called", False, 0),
])
def test_joint_cache_coverage_counts_nonprovider_calls_but_excludes_not_called(tmp_path, monkeypatch, source, observed, unobserved):
    monkeypatch.setattr(usage_ledger, "PROJECT_ROOT", tmp_path)
    _record("session-a", "agent-a", 100, 25, 1)
    usage_ledger.record_usage_event(usage_ledger.UsageLedgerEvent(
        source=source, session_id="session-a", agent_id="agent-a", recorded_at="2026-11-04T10:00:02Z",
        input_tokens=100 if source != "not_called" else 0, cached_input_tokens=25 if observed else 0,
        cache_read_input_tokens=25 if observed else 0, cache_usage_observed=observed,
    ))
    summary = usage_ledger.build_usage_summary(scope="session_agent", session_id="session-a", agent_id="agent-a")
    rollup = summary["sessionTokenUsage"]
    assert rollup["cacheHitRate"] == 0.25
    assert rollup["cachedInputTokens"] == rollup["cacheReadInputTokens"] == 25
    assert rollup["cacheObservedCallCount"] == 1
    assert rollup["cacheUnobservedCallCount"] == unobserved
    assert rollup["cacheUsageComplete"] is (unobserved == 0)
    assert summary["lastTokenUsage"]["source"] == source


def test_joint_estimated_only_usage_cannot_claim_an_observed_zero_or_complete_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(usage_ledger, "PROJECT_ROOT", tmp_path)
    usage_ledger.record_usage_event(usage_ledger.UsageLedgerEvent(
        source="estimated", session_id="session-a", agent_id="agent-a", input_tokens=100,
        cached_input_tokens=25, cache_read_input_tokens=25, cache_usage_observed=True,
    ))
    summary = usage_ledger.build_usage_summary(scope="session_agent", session_id="session-a", agent_id="agent-a")
    rollup = summary["sessionTokenUsage"]
    assert rollup["cachedInputTokens"] == rollup["cacheReadInputTokens"] == 0
    assert rollup["cacheObservedInputTokens"] == rollup["cacheObservedCallCount"] == 0
    assert rollup["cacheUnobservedCallCount"] == 1
    assert rollup["cacheUsageObserved"] is False
    assert rollup["cacheUsageComplete"] is False
    assert rollup["cacheUsageMissingReason"] == "provider_cache_usage_missing"
    assert summary["lastTokenUsage"]["source"] == "estimated"


@pytest.mark.parametrize("session_id,agent_id", [("", "agent-a"), ("session-a", ""), ("", ""), ("  ", "agent-a")])
def test_joint_scope_requires_both_identities_before_opening_a_ledger(monkeypatch, session_id, agent_id):
    monkeypatch.setattr(usage_ledger, "usage_ledger_path", lambda *_a: pytest.fail("Invalid identity reached ledger"))
    with pytest.raises(ValueError, match="sessionId and agentId"):
        usage_ledger.build_usage_summary(scope="session_agent", session_id=session_id, agent_id=agent_id)


@pytest.mark.parametrize("scope,filters,calls,tokens", [
    ("global", {}, 4, 11400),
    # Legacy session scope intentionally ignores its echoed Agent filter.
    ("session", {"session_id": "session-a", "agent_id": "foreign-agent"}, 3, 11000),
    ("agent", {"agent_id": "agent-a", "session_id": "session-a"}, 3, 1400),
    ("model", {"provider": "provider-a", "model": "model-a"}, 4, 11400),
])
def test_existing_scopes_keep_their_original_filtering(ledger, scope, filters, calls, tokens):
    summary = usage_ledger.build_usage_summary(scope=scope, **filters)
    assert summary["scopeTokenUsage"]["callCount"] == calls
    assert summary["scopeTokenUsage"]["inputTokens"] == tokens
    assert summary["lastTokenUsage"]["eventId"] == "event-4"


def _client():
    app = FastAPI()
    app.include_router(usage_routes.router, prefix="/api")
    return TestClient(app)


def test_usage_route_accepts_the_explicit_joint_scope_and_preserves_its_filters(ledger):
    response = _client().get("/api/usage/summary", params={
        "scope": "session_agent", "sessionId": "session-a", "agentId": "agent-a",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "session_agent"
    assert payload["filters"]["sessionId"] == "session-a"
    assert payload["filters"]["agentId"] == "agent-a"
    assert payload["sessionTokenUsage"]["callCount"] == 2
    assert payload["sessionTokenUsage"]["cacheHitRate"] == 0.1
    assert payload["lastTokenUsage"]["agentId"] == "agent-a"


@pytest.mark.parametrize("filters", [{}, {"sessionId": "session-a"}, {"agentId": "agent-a"},
                                    {"sessionId": " ", "agentId": "agent-a"}])
def test_joint_route_rejects_missing_identity_without_querying_the_ledger(monkeypatch, filters):
    monkeypatch.setattr(usage_routes, "build_usage_summary", lambda **_kw: pytest.fail("Missing identity reached ledger"))
    response = _client().get("/api/usage/summary", params={"scope": "session_agent", **filters})
    assert response.status_code == 400
    assert "sessionId and agentId" in response.json()["detail"]
