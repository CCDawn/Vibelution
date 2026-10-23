"""Platform API gateway stays GET-only, allowlisted and bounded."""

import io
import json
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit

import pytest

from core.web.services.personal_assistant_platform_api import api
from tools import personal_assistant_tools as tools
from tests.test_personal_assistant_tools import assistant_runtime
from tests.test_personal_assistant_service import finance_env, personal_env

RAW_SPEC = {
    "/api/agents": {"get": {"tags": ["agents"], "summary": "List agents"}},
    "/api/runtime/tasks": {"get": {"tags": ["runtime-tasks"], "summary": "List runtime tasks"}},
    "/api/sessions/{sessionId}/messages": {"get": {"tags": ["sessions"], "summary": "Messages"}},
    "/api/teams/{team_id}/member-messages": {"get": {"tags": ["teams"], "summary": "Member messages"}},
    "/api/runtime/messaging-status": {"get": {"tags": ["runtime"], "summary": "Messaging relay status"}},
    "/api/agents/{agentId}": {"post": {"tags": ["agents"], "summary": "Mutate"}},
    "/api/memory/agents": {"get": {"tags": ["memory"], "summary": "Private memory"}},
}


def _patch_endpoints(monkeypatch, raw=None):
    raw = RAW_SPEC if raw is None else raw
    monkeypatch.setattr(
        api, "_allowlisted_get_endpoints", lambda: api._filter_get_endpoints(raw)
    )


def _patch_urlopen(monkeypatch, handler):
    monkeypatch.setattr(api.urllib.request, "urlopen", handler)


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
    assert set(result) == {"/api/agents", "/api/runtime/tasks", "/api/runtime/messaging-status"}


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


def test_index_overview_counts_only_allowlisted_tags(monkeypatch):
    _patch_endpoints(monkeypatch)
    result = api.platform_api_index()
    assert result["ok"] is True and result["untrustedContent"] is True
    assert result["source"] == "loopback-workbench-api" and result["observedAt"]
    tags = result["tags"]
    assert tags["agents"]["endpointCount"] == 1
    assert tags["runtime-tasks"]["endpointCount"] == 1
    assert tags["runtime"]["endpointCount"] == 1
    # sessions/teams exist in the raw spec but their GETs carry denied words
    assert "sessions" not in tags and "teams" not in tags
    assert "memory" not in tags


def test_index_tag_mode_lists_paths_and_summaries(monkeypatch):
    _patch_endpoints(monkeypatch)
    result = api.platform_api_index(tag="runtime-tasks")
    assert result["mode"] == "tag" and result["tag"] == "runtime-tasks"
    assert result["endpoints"] == [
        {"path": "/api/runtime/tasks", "summary": "List runtime tasks"}
    ]
    assert result["endpointCount"] == 1 and result["truncated"] is False


@pytest.mark.parametrize("tag", ["memory", "logs", "config", "external-agent", "unknown-tag", "Memory"])
def test_index_rejects_tags_outside_the_allowlist(monkeypatch, tag):
    _patch_endpoints(monkeypatch)
    assert api.platform_api_index(tag=tag)["ok"] is False


def test_index_caps_large_tag_listings(monkeypatch):
    raw = {
        f"/api/agents/{index}": {"get": {"tags": ["agents"], "summary": f"Agent {index}"}}
        for index in range(api.INDEX_ENDPOINTS_CAP + 5)
    }
    _patch_endpoints(monkeypatch, raw)
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
    result = api.platform_api_get("/api/agents", query="filter=a/b&flag=")
    assert result["ok"] is True
    assert seen["url"].endswith("/api/agents?filter=a/b&flag=")
    assert api.platform_api_get("/api/agents")["ok"] is True
    assert seen["url"].endswith("/api/agents")
    assert "?" not in seen["url"].rsplit("/api/agents", 1)[-1]


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
    assert api.platform_api_get("/api/agents")["ok"] is True


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


def test_session_index_contains_only_active_id_and_audited_config_routes(monkeypatch):
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
        "/api/sessions/active", "/api/sessions/{session_id}/llm-options",
        "/api/sessions/{session_id}/budget-parameters",
    }
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(b'{"activeSessionId": "current"}'))
    assert api.platform_api_get("/api/sessions/active")["data"] == {"activeSessionId": "current"}


def test_get_maps_success_truncation_and_untrusted_content(monkeypatch):
    _patch_endpoints(monkeypatch)
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(b'{"items": [1, 2, 3]}'))
    result = api.platform_api_get("/api/agents")
    assert result["ok"] is True
    assert result["httpStatus"] == 200 and result["truncated"] is False
    assert result["data"] == {"items": [1, 2, 3]}
    assert result["untrustedContent"] is True

    big = "x" * (api.MAX_RESPONSE_CHARS + 10)
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(big.encode()))
    truncated = api.platform_api_get("/api/agents")
    assert truncated["truncated"] is True
    assert len(truncated["data"]) == api.MAX_RESPONSE_CHARS

    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(b"plain text, not json"))
    textual = api.platform_api_get("/api/agents")
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
    assert api.platform_api_get("/api/agents")["ok"] is True
    assert seen["token"] == "test-token-value"


def test_get_maps_http_error_detail_and_unreachable(monkeypatch):
    _patch_endpoints(monkeypatch)

    def raise_http_error(*_a, **_k):
        raise urllib.error.HTTPError(
            "url", 404, "Not Found", hdrs=None, fp=io.BytesIO(b'{"detail": "agent not found"}')
        )

    _patch_urlopen(monkeypatch, raise_http_error)
    missing = api.platform_api_get("/api/agents")
    assert missing["ok"] is False and missing["httpStatus"] == 404
    assert missing["message"] == "agent not found"

    def raise_unreachable(*_a, **_k):
        raise urllib.error.URLError("connection refused")

    _patch_urlopen(monkeypatch, raise_unreachable)
    down = api.platform_api_get("/api/agents")
    assert down["ok"] is False and "unreachable" in down["message"]


def test_shell_tool_returns_json_envelope_and_navigates(assistant_runtime, monkeypatch):
    _patch_endpoints(monkeypatch)
    overview = json.loads(tools.personal_assistant_platform_api_tool(path="index"))
    assert overview["ok"] is True and "tags" in overview
    listing = json.loads(
        tools.personal_assistant_platform_api_tool(path="index", tag="agents")
    )
    assert listing["endpoints"][0]["path"] == "/api/agents"
    blocked = json.loads(tools.personal_assistant_platform_api_tool(path="/api/memory/agents"))
    assert blocked["ok"] is False


def test_shell_tool_blocks_unbound_identity(personal_env, monkeypatch):
    monkeypatch.setattr(
        tools.directory, "current_agent_runtime", lambda: {"agentId": personal_env["owner"]}
    )
    result = json.loads(tools.personal_assistant_platform_api_tool(path="/api/agents"))
    assert result["ok"] is False and result["status"] == "blocked"
