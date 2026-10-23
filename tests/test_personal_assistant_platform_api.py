"""Platform API gateway stays GET-only, allowlisted and bounded."""

import io
import json
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

import pytest

from core.web.services.personal_assistant_platform_api import api
from tools import personal_assistant_tools as tools
from tests.test_personal_assistant_tools import assistant_runtime
from tests.test_personal_assistant_service import finance_env, personal_env

RAW_SPEC = {
    "/api/agents/avatar-options": {"get": {"tags": ["agents"], "summary": "List agents"}},
    "/api/launcher/freshness": {"get": {"tags": ["launcher"], "summary": "Launcher freshness"}},
    "/api/sessions/{sessionId}/messages": {"get": {"tags": ["sessions"], "summary": "Messages"}},
    "/api/teams/{team_id}/member-messages": {"get": {"tags": ["teams"], "summary": "Member messages"}},
    "/api/runtime/code-freshness": {"get": {"tags": ["runtime"], "summary": "Runtime code freshness"}},
    "/api/agents/{agentId}": {"post": {"tags": ["agents"], "summary": "Mutate"}},
    "/api/memory/agents": {"get": {"tags": ["memory"], "summary": "Private memory"}},
}


def _patch_endpoints(monkeypatch, raw=None):
    raw = RAW_SPEC if raw is None else raw
    monkeypatch.setattr(
        api, "_allowlisted_get_endpoints", lambda: api._filter_get_endpoints(raw)
    )


def _patch_urlopen(monkeypatch, handler):
    monkeypatch.setattr(api, "_open_get", handler)


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    @property
    def status(self):
        return 200


def test_filter_drops_private_tags_post_ops_and_private_path_words():
    result = api._filter_get_endpoints(RAW_SPEC)
    assert set(result) == {"/api/agents/avatar-options", "/api/launcher/freshness", "/api/runtime/code-freshness"}


def test_new_static_route_cannot_inherit_access_from_an_allowed_tag(monkeypatch):
    raw = {**RAW_SPEC, "/api/agents/future-private-status": {
        "get": {"tags": ["agents"], "summary": "Future route"},
    }}
    _patch_endpoints(monkeypatch, raw)
    assert "/api/agents/future-private-status" not in api._filter_get_endpoints(raw)
    _patch_urlopen(monkeypatch, lambda *_a, **_k: pytest.fail("new route opened a socket"))
    assert api.platform_api_get("/api/agents/future-private-status")["ok"] is False


@pytest.mark.parametrize("path,tag", [
    ("/api/session-archive", "session-archive"),
    ("/api/sessions/active", "sessions"),
    ("/api/agent-plugins/virtual-human-life/companions", "agent-plugins"),
    ("/api/agent-plugins/virtual-human-life/companion-bindings", "agent-plugins"),
    ("/api/agent-plugins/virtual-human-life/companion-activity", "agent-plugins"),
    ("/api/agent-plugins/companion-activity", "agent-plugins"),
    ("/api/companions", "virtual-human-life"),
    ("/api/runtime/summary", "runtime"),
    ("/api/diagnostics/health", "diagnostics"),
    ("/api/prompt-templates", "agents"),
    ("/api/git/diff", "git"),
])
def test_static_private_aggregates_never_return_raw_content(monkeypatch, path, tag):
    _patch_endpoints(monkeypatch, {path: {"get": {"tags": [tag]}}})
    _patch_urlopen(monkeypatch, lambda *_a, **_k: pytest.fail("private aggregate opened a socket"))
    assert api.platform_api_get(path)["ok"] is False
    assert api.platform_api_index(tag=tag)["endpoints"] == []


def test_closed_policy_references_existing_native_get_routes():
    # Read source instead of booting the app (which requires a pinned frontend).
    import ast

    routes_root = Path(api.__file__).resolve().parents[2] / "routes"
    native_gets = set()
    for name in (
        "agents.py", "chat_rooms.py", "runtime.py", "launcher.py", "usage.py", "sessions.py",
        "financial_assistant.py", "financial_research.py", "financial_preferences.py",
        "financial_portfolio.py", "financial_jobs.py", "knowledge.py", "research.py",
    ):
        tree = ast.parse((routes_root / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == "get"
                        and decorator.args
                        and isinstance(decorator.args[0], ast.Constant)):
                    native_gets.add(("GET", f"/api{decorator.args[0].value}"))
    assert api.PUBLIC_GET_OPERATIONS <= native_gets
    assert {path for method, path in api.PUBLIC_GET_OPERATIONS if "{" in path} == api.PUBLIC_DYNAMIC_PATHS


PROJECTED_CASES = [
    ("/api/financial-assistants", "financial-assistant",
     [{"agentId": "finance-1", "displayName": "Finance", "status": "active", "directSessionId": "private-marker"}],
     [{"agentId": "finance-1", "displayName": "Finance", "status": "active"}]),
    ("/api/financial-market/search", "financial-assistant",
     [{"symbol": "600000", "name": "Stock", "market": "CN", "providerConfig": "private-marker"}],
     [{"symbol": "600000", "name": "Stock", "market": "CN"}]),
    ("/api/financial-market/quotes", "financial-research",
     {"fetchedAt": "now", "items": [{"symbol": "600000", "error": "private-marker", "quote": {"price": 10.5, "prompt": "private-marker"}}]},
     {"fetchedAt": "now", "items": [{"symbol": "600000", "quote": {"price": 10.5}}]}),
    ("/api/financial-market/screen", "financial-research",
     {"page": 1, "items": [{"symbol": "600000", "price": 10, "lastPreview": "private-marker"}], "coverage": {"complete": True, "loaded": 50, "summary": "private-marker"}},
     {"page": 1, "items": [{"symbol": "600000", "price": 10}], "coverage": {"complete": True, "loaded": 50}}),
    ("/api/financial-preferences/{agent_id}/workspace", "financial-preferences", {
        "agentId": "private-marker", "revision": 3,
        "watchlist": [{"symbol": "600000", "name": "Stock", "tags": ["bank"], "note": "private-marker"}],
        "manualPositions": [{"id": "holding-1", "stock": {"symbol": "600000", "name": "Stock"}, "quantity": 100.0, "costPrice": 10.0, "note": "private-marker"}],
        "investmentProfile": {"budgetCny": 10000.0, "horizonMonths": 12, "prompt": "private-marker"},
        "profiles": [{"id": "basic", "name": "Basic", "depth": "brief", "instructions": "private-marker"}],
        "investmentPlans": [{"id": "plan-1", "status": "adopted", "rationale": "private-marker", "source": {"sessionId": "private-marker"}}],
        "reviewCases": [{"title": "private-marker"}], "memory": "private-marker",
    }, {
        "revision": 3,
        "watchlist": [{"symbol": "600000", "name": "Stock", "tags": ["bank"]}],
        "manualPositions": [{"id": "holding-1", "stock": {"symbol": "600000", "name": "Stock"}, "quantity": 100.0, "costPrice": 10.0}],
        "investmentProfile": {"budgetCny": 10000.0, "horizonMonths": 12},
        "profiles": [{"id": "basic", "name": "Basic", "depth": "brief"}],
        "investmentPlans": [{"id": "plan-1", "status": "adopted"}],
    }),
    ("/api/financial-portfolios/{agentId}/research", "financial-portfolio", {
        "accountId": "account-1", "simulationOnly": True,
        "summary": {"positionCount": 1, "equityYuan": "1500.00", "valuationComplete": True, "privateContext": "private-marker"},
        "positions": [{"symbol": "600000", "quantity": 100, "valuationStatus": "fresh", "summary": "private-marker"}],
        "report": "private-marker", "notice": "private-marker",
    }, {
        "accountId": "account-1", "simulationOnly": True,
        "summary": {"positionCount": 1, "equityYuan": "1500.00", "valuationComplete": True},
        "positions": [{"symbol": "600000", "quantity": 100, "valuationStatus": "fresh"}],
    }),
    ("/api/financial-jobs/{assistant_agent_id}/schedules", "financial-jobs", {
        "schedules": [{"scheduleId": "schedule-1", "symbols": ["600000"], "enabled": True, "execution": {"kind": "daily", "timeOfDay": "09:00", "script": "private-marker"}, "prompt": "private-marker"}],
    }, {"schedules": [{"scheduleId": "schedule-1", "symbols": ["600000"], "enabled": True, "execution": {"kind": "daily", "timeOfDay": "09:00"}}]}),
    ("/api/financial-jobs/{assistant_agent_id}/batches", "financial-jobs", {
        "batches": [{"batchId": "batch-1", "status": "running", "terminalReason": "private-marker", "items": [{"symbol": "600000", "status": "running", "runId": "run-1", "turnRefs": [{"sessionId": "private-marker"}], "logs": "private-marker"}]}],
    }, {"batches": [{"batchId": "batch-1", "status": "running", "items": [{"symbol": "600000", "status": "running", "runId": "run-1"}]}]}),
    *[(path, "knowledge", {
        "agentId": "private-marker", "summary": {"itemCount": 999},
        "knowledgeBases": [
            {"ownerType": "agent", "name": "private-marker", "stats": {"itemCount": 900}},
            {"ownerType": "team", "knowledgeBaseId": "kb-1", "name": "Library", "stats": {"itemCount": 2, "sourceArtifactCount": 1, "pendingProposalCount": 0},
             "description": "private-marker", "pendingProposals": [{"content": "private-marker"}], "acl": {"private": "private-marker"}},
        ],
    }, {
        "knowledgeBases": [{"ownerType": "team", "knowledgeBaseId": "kb-1", "name": "Library", "stats": {"itemCount": 2, "sourceArtifactCount": 1, "pendingProposalCount": 0}}],
        "summary": {"knowledgeBaseCount": 1, "itemCount": 2, "sourceArtifactCount": 1, "pendingProposalCount": 0},
    }) for path in ("/api/knowledge/overview", "/api/knowledge/team-catalog")],
    ("/api/research/knowledge-base", "research", {
        "entries": [{"knowledgeId": "source-1", "title": "Paper", "url": "https://example.org/paper", "categories": ["paper"], "tags": ["private-marker"], "summary": "private-marker", "queries": ["private-marker"], "sessionIds": ["private-marker"]}],
        "agentContext": {"recentQueries": ["private-marker"]}, "claims": [{"content": "private-marker"}],
        "summary": {"entryCount": 1, "claimCount": 3, "private": "private-marker"},
    }, {
        "entries": [{"knowledgeId": "source-1", "title": "Paper", "url": "https://example.org/paper", "categories": ["paper"]}],
        "summary": {"entryCount": 1, "claimCount": 3},
    }),
    ("/api/research/theme-discovery/sessions", "research", {
        "sessions": [{"sessionId": "discovery-1", "status": "draft", "candidateCount": 5, "openGoal": "private-marker", "constraints": "private-marker", "preferences": "private-marker", "summary": {"sourceCount": 3, "private": "private-marker"}}],
        "summary": {"sessionCount": 1, "selectedCount": 0},
    }, {"sessions": [{"sessionId": "discovery-1", "status": "draft", "candidateCount": 5, "summary": {"sourceCount": 3}}], "summary": {"sessionCount": 1, "selectedCount": 0}}),
]


def _concrete_path(template):
    return template.replace("{agent_id}", "finance-1").replace("{agentId}", "finance-1").replace("{assistant_agent_id}", "finance-1")


@pytest.mark.parametrize("template,tag,payload,expected", PROJECTED_CASES)
def test_public_business_gets_preserve_metadata_and_remove_nested_private_content(monkeypatch, template, tag, payload, expected):
    _patch_endpoints(monkeypatch, {template: {"get": {"tags": [tag]}}})
    seen = []

    def handler(request, **_kwargs):
        seen.append(request.full_url)
        return _FakeResponse(json.dumps(payload).encode())

    _patch_urlopen(monkeypatch, handler)
    result = api.platform_api_get(_concrete_path(template), query="limit=2&agentId=other")
    assert result["ok"] is True and result["data"] == expected
    assert result["truncated"] is False
    assert "private-marker" not in json.dumps(result)
    assert seen[0].endswith(f"{_concrete_path(template)}?limit=2&agentId=other")
    assert api.platform_api_index(tag=tag)["endpoints"][0]["path"] == template


@pytest.mark.parametrize("template,tag,payload,expected", PROJECTED_CASES)
def test_public_business_projection_over_real_loopback_get(monkeypatch, template, tag, payload, expected):
    _patch_endpoints(monkeypatch, {template: {"get": {"tags": [tag]}}})
    monkeypatch.setattr("core.web.control.get_control_token", lambda: "projection-test-token")
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append((self.path, self.headers.get("X-Vibelution-Control-Token")))
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        monkeypatch.setenv("VIBELUTION_PORT", str(server.server_port))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = api.platform_api_get(_concrete_path(template), "limit=2")
        finally:
            server.shutdown()
            thread.join(timeout=2)
    assert result["ok"] is True and result["data"] == expected
    assert received == [(f"{_concrete_path(template)}?limit=2", "projection-test-token")]
    assert "private-marker" not in json.dumps(result)
    assert "projection-test-token" not in json.dumps(result)


@pytest.mark.parametrize("payload", [
    b'not-json-private-marker', b'null', b'{"watchlist":[{"symbol":{"body":"private-marker"}}]}',
    b'{"watchlist":"private-marker"}', b'{"investmentProfile":{"budgetCny":true}}',
    b'{"investmentProfile":{"budgetCny":NaN}}',
])
def test_projected_route_fails_closed_on_malformed_or_non_json_payload(monkeypatch, payload):
    template = "/api/financial-preferences/{agent_id}/workspace"
    _patch_endpoints(monkeypatch, {template: {"get": {"tags": ["financial-preferences"]}}})
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(payload))
    result = api.platform_api_get(_concrete_path(template))
    assert result["ok"] is False
    assert "data" not in result and "private-marker" not in json.dumps(result)


def test_projected_route_never_falls_back_to_raw_truncated_body(monkeypatch):
    template = "/api/financial-preferences/{agent_id}/workspace"
    _patch_endpoints(monkeypatch, {template: {"get": {"tags": ["financial-preferences"]}}})
    payload = {"memory": "private-marker" * api.MAX_PROJECTION_BYTES}
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(json.dumps(payload).encode()))
    result = api.platform_api_get(_concrete_path(template))
    assert result["ok"] is False and result["truncated"] is True
    assert "data" not in result and "private-marker" not in json.dumps(result)


def test_large_private_fields_are_discarded_before_model_output_limit(monkeypatch):
    template = "/api/financial-preferences/{agent_id}/workspace"
    _patch_endpoints(monkeypatch, {template: {"get": {"tags": ["financial-preferences"]}}})
    payload = {"revision": 2, "memory": "private-marker" * api.MAX_RESPONSE_CHARS}
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(json.dumps(payload).encode()))
    result = api.platform_api_get(_concrete_path(template))
    assert result["ok"] is True and result["data"] == {"revision": 2}
    assert result["truncated"] is False
    assert "private-marker" not in json.dumps(result)


def test_projected_output_budget_never_returns_partial_json_or_raw_data(monkeypatch):
    template = "/api/financial-market/screen"
    _patch_endpoints(monkeypatch, {template: {"get": {"tags": ["financial-research"]}}})
    payload = {"items": [{"symbol": str(index), "name": "x" * 512} for index in range(100)]}
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(json.dumps(payload).encode()))
    result = api.platform_api_get(template)
    assert result["ok"] is False and result["truncated"] is True
    assert "data" not in result


def test_projection_rejects_overflowing_numeric_field_without_throwing(monkeypatch):
    template = "/api/financial-preferences/{agent_id}/workspace"
    _patch_endpoints(monkeypatch, {template: {"get": {"tags": ["financial-preferences"]}}})
    payload = {"investmentProfile": {"budgetCny": 10 ** 1000}}
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(json.dumps(payload).encode()))
    assert api.platform_api_get(_concrete_path(template))["ok"] is False


def test_projected_business_lists_are_bounded_and_signal_truncation(monkeypatch):
    template = "/api/financial-preferences/{agent_id}/workspace"
    _patch_endpoints(monkeypatch, {template: {"get": {"tags": ["financial-preferences"]}}})
    payload = {"watchlist": [{"symbol": str(index)} for index in range(55)]}
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(json.dumps(payload).encode()))
    result = api.platform_api_get(_concrete_path(template))
    assert result["ok"] is True and result["truncated"] is True
    assert len(result["data"]["watchlist"]) == 50


def test_new_financial_dynamic_detail_cannot_inherit_an_audited_projection(monkeypatch):
    template = "/api/financial-jobs/{assistant_agent_id}/batches/{batch_id}"
    _patch_endpoints(monkeypatch, {template: {"get": {"tags": ["financial-jobs"]}}})
    _patch_urlopen(monkeypatch, lambda *_a, **_k: pytest.fail("unaudited detail opened a socket"))
    assert api.platform_api_get("/api/financial-jobs/finance-1/batches/batch-1")["ok"] is False


@pytest.mark.parametrize("path,tag", [
    ("/api/runtime/code-freshness", "runtime"),
    ("/api/launcher/freshness", "launcher"),
    ("/api/launcher/settings/startup", "launcher"),
    ("/api/usage/summary", "usage"),
])
def test_audited_public_status_routes_remain_callable(monkeypatch, path, tag):
    _patch_endpoints(monkeypatch, {path: {"get": {"tags": [tag]}}})
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(b'{"state":"ready"}'))
    assert api.platform_api_get(path)["data"] == {"state": "ready"}


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_real_http_redirect_never_follows_private_target_or_exposes_body(monkeypatch, status):
    _patch_endpoints(monkeypatch)
    monkeypatch.setattr("core.web.control.get_control_token", lambda: "private-control-token")
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.path)
            self.send_response(status if len(received) == 1 else 200)
            self.send_header("Location", "/api/control-token")
            self.end_headers()
            self.wfile.write(b'{"detail":"private-control-token private-error-body"}')

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        monkeypatch.setenv("VIBELUTION_PORT", str(server.server_port))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = api.platform_api_get("/api/agents/avatar-options")
        finally:
            server.shutdown()
            thread.join(timeout=2)
    assert result["ok"] is False and result["httpStatus"] == status
    assert received == ["/api/agents/avatar-options"]
    assert "private-control-token" not in json.dumps(result)
    assert "private-error-body" not in json.dumps(result)


def test_real_cross_origin_redirect_does_not_forward_control_token(monkeypatch):
    _patch_endpoints(monkeypatch)
    monkeypatch.setattr("core.web.control.get_control_token", lambda: "private-control-token")
    target_requests = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            target_requests.append(self.headers.get("X-Vibelution-Control-Token"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler) as target:
        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{target.server_port}/capture")
                self.end_headers()

            def log_message(self, *_args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler) as server:
            monkeypatch.setenv("VIBELUTION_PORT", str(server.server_port))
            threads = [Thread(target=item.serve_forever, daemon=True) for item in (target, server)]
            for thread in threads:
                thread.start()
            try:
                result = api.platform_api_get("/api/agents/avatar-options")
            finally:
                for item in (server, target):
                    item.shutdown()
                for thread in threads:
                    thread.join(timeout=2)
    assert result["ok"] is False and result["httpStatus"] == 302
    assert target_requests == []
    assert "private-control-token" not in json.dumps(result)


@pytest.mark.parametrize("body", [
    b'{"detail":"private-control-token private-request-echo"}',
    b'{"message":"private-control-token private-request-echo"}',
    b'private-control-token private-request-echo',
])
def test_http_error_body_is_never_read_or_returned(monkeypatch, body):
    _patch_endpoints(monkeypatch)

    class ErrorBody(io.BytesIO):
        def read(self, *_args):
            pytest.fail("gateway read an untrusted HTTP error body")

    def handler(*_args, **_kwargs):
        raise urllib.error.HTTPError("url", 500, "private-control-token", None, ErrorBody(body))

    _patch_urlopen(monkeypatch, handler)
    result = api.platform_api_get("/api/agents/avatar-options")
    assert result["ok"] is False and result["httpStatus"] == 500
    assert "private-control-token" not in json.dumps(result)
    assert "private-request-echo" not in json.dumps(result)


def test_denied_path_matching_is_word_level_not_substring():
    # compound segments carrying a private-content word stay denied
    for path in ("/api/teams/{team_id}/member-messages",
                 "/api/teams/x/workflow/chain/anomaly-inbox",
                 "/api/agents/x/messages-latest",
                 "/api/chat-rooms/{room_id}/timeline"):
        assert api._has_denied_path_word(path) is True, path
    # unrelated words that merely share letters stay visible
    for path in ("/api/runtime/messaging-status", "/api/agents/messagesdigest"):
        assert api._has_denied_path_word(path) is False, path


def test_agent_full_config_projections_are_documented_but_not_readable():
    paths = {path: {"get": {"tags": ["agents"]}} for path in
             ("/api/agents", "/api/agents/config-workspace", "/api/agents/avatar-options")}
    assert set(api._filter_get_endpoints(paths)) == {"/api/agents/avatar-options"}


def test_index_overview_counts_only_allowlisted_tags(monkeypatch):
    _patch_endpoints(monkeypatch)
    result = api.platform_api_index()
    assert result["ok"] is True and result["untrustedContent"] is True
    assert result["source"] == "loopback-workbench-api" and result["observedAt"]
    tags = result["tags"]
    assert tags["agents"]["endpointCount"] == 1
    assert tags["launcher"]["endpointCount"] == 1
    assert tags["runtime"]["endpointCount"] == 1
    # sessions/teams exist in the raw spec but their GETs carry denied words
    assert "sessions" not in tags and "teams" not in tags
    assert "memory" not in tags


def test_index_tag_mode_lists_paths_and_summaries(monkeypatch):
    _patch_endpoints(monkeypatch)
    result = api.platform_api_index(tag="launcher")
    assert result["mode"] == "tag" and result["tag"] == "launcher"
    assert result["endpoints"] == [
        {"path": "/api/launcher/freshness", "summary": "Launcher freshness"}
    ]
    assert result["endpointCount"] == 1 and result["truncated"] is False


@pytest.mark.parametrize("tag", ["memory", "logs", "config", "external-agent", "unknown-tag", "Memory"])
def test_index_rejects_tags_outside_the_allowlist(monkeypatch, tag):
    _patch_endpoints(monkeypatch)
    assert api.platform_api_index(tag=tag)["ok"] is False


def test_index_caps_large_tag_listings(monkeypatch):
    # Exercise presentation independently of the fixed authorization policy.
    endpoints = {
        f"/api/agents/{index}": {"tags": frozenset({"agents"}), "summary": f"Agent {index}"}
        for index in range(api.INDEX_ENDPOINTS_CAP + 5)
    }
    monkeypatch.setattr(api, "_allowlisted_get_endpoints", lambda: endpoints)
    result = api.platform_api_index(tag="agents")
    assert result["endpointCount"] == api.INDEX_ENDPOINTS_CAP + 5
    assert len(result["endpoints"]) == api.INDEX_ENDPOINTS_CAP
    assert result["truncated"] is True


def test_get_rejects_paths_outside_the_registered_surface(monkeypatch):
    _patch_endpoints(monkeypatch)
    _patch_urlopen(monkeypatch, lambda *_a, **_k: pytest.fail("rejected path must not open a socket"))
    for path in ("index", "api/agents", "/api/agents?limit=1", "/api/agents#x",
                 "/api/agents/{agentId}", "/api/control-token", "/api/openapi.json",
                 "/api/sessions/x/messages", "/api/teams/x/member-messages",
                 "/api/memory/agents"):
        assert api.platform_api_get(path)["ok"] is False


def test_get_passes_query_through_untouched_and_omits_empty(monkeypatch):
    _patch_endpoints(monkeypatch)
    seen = {}

    def handler(request, **_kwargs):
        seen["url"] = request.full_url
        return _FakeResponse(b'{"data": []}')

    _patch_urlopen(monkeypatch, handler)
    # the server owns query parsing; the gateway forwards verbatim
    result = api.platform_api_get("/api/agents/avatar-options", query="filter=a/b&flag=")
    assert result["ok"] is True
    assert seen["url"].endswith("/api/agents/avatar-options?filter=a/b&flag=")
    assert api.platform_api_get("/api/agents/avatar-options")["ok"] is True
    assert seen["url"].endswith("/api/agents/avatar-options")
    assert "?" not in seen["url"].rsplit("/api/agents/avatar-options", 1)[-1]


def test_get_builds_loopback_hostname_and_port(monkeypatch):
    _patch_endpoints(monkeypatch)
    monkeypatch.setenv("VIBELUTION_PORT", "8123")

    def handler(request, **_kwargs):
        parsed = urlsplit(request.full_url)
        assert parsed.hostname == "127.0.0.1"
        assert parsed.port == 8123
        assert request.get_method() == "GET"
        return _FakeResponse(b"{}")

    _patch_urlopen(monkeypatch, handler)
    assert api.platform_api_get("/api/agents/avatar-options")["ok"] is True


def test_get_substituted_object_id_roundtrip_on_loopback(monkeypatch):
    _patch_endpoints(monkeypatch, {
        "/api/sessions/{session_id}/llm-options": {"get": {"tags": ["sessions"]}},
    })
    monkeypatch.setattr("core.web.control.get_control_token", lambda: "test-loopback-token")
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append((self.path, self.headers.get("X-Vibelution-Control-Token")))
            body = b'{"state": "ready"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        monkeypatch.setenv("VIBELUTION_PORT", str(server.server_port))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = api.platform_api_get("/api/sessions/session-123/llm-options", "filter=a/b&flag=")
        finally:
            server.shutdown()
            thread.join(timeout=2)
    assert result["ok"] is True
    assert result["data"] == {"state": "ready"}
    assert received == [("/api/sessions/session-123/llm-options?filter=a/b&flag=", "test-loopback-token")]
    assert "test-loopback-token" not in json.dumps(result)


@pytest.mark.parametrize("path", [
    "https://example.com/api/sessions/x/llm-options", "//example.com/api/sessions/x/llm-options",
    "/api/sessions/x/llm-options?limit=1", "/api/sessions/x/llm-options#fragment",
    "/api/sessions/x/../llm-options", "/api/sessions/../llm-options", "/api/sessions/./llm-options",
    "/api/sessions/x%2fother/llm-options", "/api/sessions/x%5Cother/llm-options",
    "/api/sessions/%2e%2e/llm-options", "/api/sessions/%252e%252e/llm-options",
    "/api/sessions/x\\other/llm-options", "/api/sessions//llm-options",
    "/api/sessions/{session_id}/llm-options", "/api/sessions/x/llm-options/extra",
    "/api/sessions/x\n/llm-options", "/api/sessions/x%3Fq=1/llm-options",
])
def test_dynamic_path_rejects_routing_bypasses(monkeypatch, path):
    _patch_endpoints(monkeypatch, {
        "/api/sessions/{session_id}/llm-options": {"get": {"tags": ["sessions"]}},
    })
    _patch_urlopen(monkeypatch, lambda *_a, **_k: pytest.fail("blocked path opened a socket"))
    assert api.platform_api_get(path)["ok"] is False


@pytest.mark.parametrize("suffix", ["llm-options", "budget-parameters"])
def test_only_audited_dynamic_metadata_routes_are_listed_and_callable(monkeypatch, suffix):
    template = f"/api/sessions/{{session_id}}/{suffix}"
    raw = {
        template: {"get": {"tags": ["sessions"]}},
        "/api/agents/{agent_id}": {"get": {"tags": ["agents"]}},
        "/api/sessions/{session_id}/future-detail": {"get": {"tags": ["sessions"]}},
    }
    _patch_endpoints(monkeypatch, raw)
    assert set(api._filter_get_endpoints(raw)) == {template}
    assert api.platform_api_index(tag="sessions")["endpoints"][0]["path"] == template
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(b"{}"))
    assert api.platform_api_get(f"/api/sessions/session-123/{suffix}")["ok"] is True
    _patch_urlopen(monkeypatch, lambda *_a, **_k: pytest.fail("private path opened a socket"))
    assert api.platform_api_get("/api/agents/agent-123")["ok"] is False
    assert api.platform_api_get("/api/sessions/session-123/future-detail")["ok"] is False


def test_session_private_details_are_hidden(monkeypatch):
    raw = {
        "/api/sessions/query": {"get": {"tags": ["sessions"]}},
        "/api/sessions/{session_id}": {"get": {"tags": ["sessions"]}},
        "/api/sessions/{session_id}/queued-turns": {"get": {"tags": ["sessions"]}},
        "/api/sessions/{session_id}/artifacts/{artifact_id}": {"get": {"tags": ["sessions"]}},
        "/api/sessions/{session_id}/messages": {"get": {"tags": ["sessions"]}},
        "/api/sessions/{session_id}/events": {"get": {"tags": ["sessions"]}},
        "/api/chat-rooms/{room_id}": {"get": {"tags": ["chat-rooms"]}},
        "/api/chat-rooms": {"get": {"tags": ["chat-rooms"]}},
    }
    _patch_endpoints(monkeypatch, raw)
    assert api._filter_get_endpoints(raw) == {}
    assert api.platform_api_index(tag="sessions")["endpointCount"] == 0
    _patch_urlopen(monkeypatch, lambda *_a, **_k: pytest.fail("private path opened a socket"))
    for path in ("/api/sessions/other", "/api/sessions/{session_id}",
                 "/api/sessions/other/queued-turns", "/api/sessions/other/artifacts/file",
                 "/api/sessions/other/messages", "/api/sessions/other/events",
                 "/api/chat-rooms/room-123", "/api/chat-rooms"):
        assert api.platform_api_get(path, query="transcriptScope=none")["ok"] is False


@pytest.mark.parametrize("template,path", [
    ("/api/sessions", "/api/sessions"),
    ("/api/sessions/query", "/api/sessions/query"),
    ("/api/sessions/bootstrap", "/api/sessions/bootstrap"),
    ("/api/sessions/{session_id}/child-sessions", "/api/sessions/other/child-sessions"),
])
def test_raw_session_catalogs_with_body_previews_are_blocked(monkeypatch, template, path):
    _patch_endpoints(monkeypatch, {template: {"get": {"tags": ["sessions"]}}})
    requests = []

    def handler(request, **_kwargs):
        requests.append(request.full_url)
        return _FakeResponse(b'{"items": [{"taskSummary": "private-preview", "searchSnippets": ["private-body"]}]}')

    _patch_urlopen(monkeypatch, handler)
    result = api.platform_api_get(path, query="q=private-body&limit=1")
    assert result["ok"] is False
    assert "personal_assistant_query_tool" in result["message"]
    assert "private-preview" not in json.dumps(result)
    assert "private-body" not in json.dumps(result)
    assert requests == []
    assert api.platform_api_index(tag="sessions")["endpoints"] == []


def test_session_index_contains_only_audited_config_routes(monkeypatch):
    raw = {
        path: {"get": {"tags": ["sessions"]}}
        for path in (
            "/api/sessions", "/api/sessions/query", "/api/sessions/bootstrap",
            "/api/sessions/active", "/api/sessions/{session_id}/child-sessions",
            "/api/sessions/{session_id}/llm-options",
            "/api/sessions/{session_id}/budget-parameters",
        )
    }
    _patch_endpoints(monkeypatch, raw)
    assert {entry["path"] for entry in api.platform_api_index(tag="sessions")["endpoints"]} == {
        "/api/sessions/{session_id}/llm-options",
        "/api/sessions/{session_id}/budget-parameters",
    }
    _patch_urlopen(monkeypatch, lambda *_a, **_k: pytest.fail("active session lookup opened a socket"))
    assert api.platform_api_get("/api/sessions/active")["ok"] is False


def test_get_maps_success_truncation_and_untrusted_content(monkeypatch):
    _patch_endpoints(monkeypatch)
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(b'{"items": [1, 2, 3]}'))
    result = api.platform_api_get("/api/agents/avatar-options")
    assert result["ok"] is True
    assert result["httpStatus"] == 200 and result["truncated"] is False
    assert result["data"] == {"items": [1, 2, 3]}
    assert result["untrustedContent"] is True

    big = "x" * (api.MAX_RESPONSE_CHARS + 10)
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(big.encode()))
    truncated = api.platform_api_get("/api/agents/avatar-options")
    assert truncated["truncated"] is True
    assert len(truncated["data"]) == api.MAX_RESPONSE_CHARS

    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(b"plain text, not json"))
    textual = api.platform_api_get("/api/agents/avatar-options")
    assert textual["ok"] is True and textual["data"].startswith("plain text")


def test_get_sends_control_token_header_in_process(monkeypatch):
    _patch_endpoints(monkeypatch)
    seen = {}

    def handler(request, **_kwargs):
        seen["token"] = request.get_header("X-vibelution-control-token")
        return _FakeResponse(b"{}")

    _patch_urlopen(monkeypatch, handler)
    monkeypatch.setattr(
        "core.web.control.get_control_token", lambda: "test-token-value"
    )
    assert api.platform_api_get("/api/agents/avatar-options")["ok"] is True
    assert seen["token"] == "test-token-value"


def test_get_maps_http_error_status_and_unreachable(monkeypatch):
    _patch_endpoints(monkeypatch)

    def raise_http_error(*_a, **_k):
        raise urllib.error.HTTPError(
            "url", 404, "Not Found", hdrs=None, fp=io.BytesIO(b'{"detail": "agent not found"}')
        )

    _patch_urlopen(monkeypatch, raise_http_error)
    missing = api.platform_api_get("/api/agents/avatar-options")
    assert missing["ok"] is False and missing["httpStatus"] == 404
    assert missing["message"] == "endpoint returned an HTTP error"
    assert "agent not found" not in json.dumps(missing)

    def raise_unreachable(*_a, **_k):
        raise urllib.error.URLError("connection refused")

    _patch_urlopen(monkeypatch, raise_unreachable)
    down = api.platform_api_get("/api/agents/avatar-options")
    assert down["ok"] is False and "unreachable" in down["message"]


def test_shell_tool_returns_json_envelope_and_navigates(assistant_runtime, monkeypatch):
    _patch_endpoints(monkeypatch)
    overview = json.loads(tools.personal_assistant_platform_api_tool(path="index"))
    assert overview["ok"] is True and "tags" in overview
    listing = json.loads(
        tools.personal_assistant_platform_api_tool(path="index", tag="agents")
    )
    assert listing["endpoints"][0]["path"] == "/api/agents/avatar-options"
    blocked = json.loads(tools.personal_assistant_platform_api_tool(path="/api/memory/agents"))
    assert blocked["ok"] is False


def test_shell_tool_blocks_unbound_identity(personal_env, monkeypatch):
    monkeypatch.setattr(
        tools.directory, "current_agent_runtime", lambda: {"agentId": personal_env["owner"]}
    )
    result = json.loads(tools.personal_assistant_platform_api_tool(path="/api/agents/avatar-options"))
    assert result["ok"] is False and result["status"] == "blocked"
