"""Platform API gateway stays GET-only, allowlisted and bounded."""
import io
import json
import urllib.error
import pytest
from core.web.services.personal_assistant_platform_api import api
from tools import personal_assistant_tools as tools
from tests.test_personal_assistant_tools import assistant_runtime
from tests.test_personal_assistant_service import finance_env, personal_env
RAW_SPEC = {
    "/api/agents": {"get": {"tags": ["agents"], "summary": "List agents"}},
    "/api/runtime/tasks": {"get": {"tags": ["runtime-tasks"], "summary": "List runtime tasks"}},
    "/api/sessions/{sessionId}/messages": {"get": {"tags": ["sessions"], "summary": "Messages"}},
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
def test_filter_drops_private_tags_post_ops_and_private_path_tokens():
    result = api._filter_get_endpoints(RAW_SPEC)
    assert set(result) == {"/api/agents", "/api/runtime/tasks"}
    assert result["/api/agents"]["summary"] == "List agents"
def test_index_overview_counts_only_allowlisted_tags(monkeypatch):
    _patch_endpoints(monkeypatch)
    result = api.platform_api_index({})
    assert result["ok"] is True and result["untrustedContent"] is True
    assert result["source"] == "loopback-workbench-api" and result["observedAt"]
    tags = result["tags"]
    assert tags["agents"]["endpointCount"] == 1
    assert tags["runtime-tasks"]["endpointCount"] == 1
    # sessions exists in the raw spec but its only GET carries a denied path token
    assert "sessions" not in tags
    assert "memory" not in tags
def test_index_tag_mode_lists_paths_and_summaries(monkeypatch):
    _patch_endpoints(monkeypatch)
    result = api.platform_api_index({}, tag="runtime-tasks")
    assert result["mode"] == "tag" and result["tag"] == "runtime-tasks"
    assert result["endpoints"] == [
        {"path": "/api/runtime/tasks", "summary": "List runtime tasks"}
    ]
    assert result["endpointCount"] == 1 and result["truncated"] is False
@pytest.mark.parametrize("tag", ["memory", "logs", "config", "external-agent", "unknown-tag", "Memory"])
def test_index_rejects_tags_outside_the_allowlist(monkeypatch, tag):
    _patch_endpoints(monkeypatch)
    assert api.platform_api_index({}, tag=tag)["ok"] is False
def test_index_caps_large_tag_listings(monkeypatch):
    raw = {
        f"/api/agents/{index}": {"get": {"tags": ["agents"], "summary": f"Agent {index}"}}
        for index in range(api.INDEX_ENDPOINTS_CAP + 5)
    }
    _patch_endpoints(monkeypatch, raw)
    result = api.platform_api_index({}, tag="agents")
    assert result["endpointCount"] == api.INDEX_ENDPOINTS_CAP + 5
    assert len(result["endpoints"]) == api.INDEX_ENDPOINTS_CAP
    assert result["truncated"] is True
def test_get_rejects_paths_outside_the_registered_surface(monkeypatch):
    _patch_endpoints(monkeypatch)
    _patch_urlopen(monkeypatch, lambda *_a, **_k: pytest.fail("rejected path must not open a socket"))
    for path in ("index", "api/agents", "/api/agents?limit=1", "/api/agents#x",
                 "/api/agents/{agentId}", "/api/control-token", "/api/openapi.json",
                 "/api/sessions/x/messages", "/api/memory/agents"):
        assert api.platform_api_get({}, path)["ok"] is False
def test_get_rejects_malformed_query_but_accepts_pairs(monkeypatch):
    _patch_endpoints(monkeypatch)
    seen = {}
    def handler(request, **_kwargs):
        seen["url"] = request.full_url
        seen["accept"] = request.get_header("Accept")
        return _FakeResponse(b'{"data": []}')
    _patch_urlopen(monkeypatch, handler)
    for bad_query in ("not-a-pair", "limit=1&bare", "a=1#frag", "a=1?b=2", "a=../../x", "a=1 b"):
        assert api.platform_api_get({}, "/api/agents", query=bad_query)["ok"] is False
    result = api.platform_api_get({}, "/api/agents", query="limit=5&status=active")
    assert result["ok"] is True and result["data"]["data"] == []
    assert seen["url"].endswith("/api/agents?limit=5&status=active")
    assert seen["accept"] == "application/json"
def test_get_maps_success_truncation_and_untrusted_content(monkeypatch):
    _patch_endpoints(monkeypatch)
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(b'{"items": [1, 2, 3]}'))
    result = api.platform_api_get({}, "/api/agents")
    assert result["ok"] is True
    assert result["httpStatus"] == 200 and result["truncated"] is False
    assert result["data"] == {"items": [1, 2, 3]}
    assert result["untrustedContent"] is True
    big = "x" * (api.MAX_RESPONSE_CHARS + 10)
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(big.encode()))
    truncated = api.platform_api_get({}, "/api/agents")
    assert truncated["truncated"] is True
    assert len(truncated["data"]) == api.MAX_RESPONSE_CHARS
    _patch_urlopen(monkeypatch, lambda *_a, **_k: _FakeResponse(b"plain text, not json"))
    textual = api.platform_api_get({}, "/api/agents")
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
    assert api.platform_api_get({}, "/api/agents")["ok"] is True
    assert seen["token"] == "test-token-value"
def test_get_maps_http_error_detail_and_unreachable(monkeypatch):
    _patch_endpoints(monkeypatch)
    def raise_http_error(*_a, **_k):
        raise urllib.error.HTTPError(
            "url", 404, "Not Found", hdrs=None, fp=io.BytesIO(b'{"detail": "agent not found"}')
        )
    _patch_urlopen(monkeypatch, raise_http_error)
    missing = api.platform_api_get({}, "/api/agents")
    assert missing["ok"] is False and missing["httpStatus"] == 404
    assert missing["message"] == "agent not found"
    def raise_unreachable(*_a, **_k):
        raise urllib.error.URLError("connection refused")
    _patch_urlopen(monkeypatch, raise_unreachable)
    down = api.platform_api_get({}, "/api/agents")
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
