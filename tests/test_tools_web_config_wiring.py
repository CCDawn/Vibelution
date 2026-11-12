"""tools.web.* must drive the web search entry points."""

from __future__ import annotations

from types import SimpleNamespace

import tools.web_search_tool as web


def _cfg(*, enabled: bool = True, max_results: int = 10, timeout: int = 30):
    return SimpleNamespace(
        tools=SimpleNamespace(
            web=SimpleNamespace(
                search_enabled=enabled,
                max_search_results=max_results,
                search_timeout=timeout,
            )
        )
    )


def test_policy_reads_config(monkeypatch):
    import config

    monkeypatch.setattr(config, "get_config", lambda: _cfg(enabled=False, max_results=4, timeout=7))
    assert web._web_search_policy() == (False, 4, 7.0)


def test_policy_falls_back_when_config_breaks(monkeypatch):
    import config

    def _boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(config, "get_config", _boom)
    assert web._web_search_policy() == (True, 10, 30.0)


def test_disabled_search_short_circuits(monkeypatch):
    import config

    monkeypatch.setattr(config, "get_config", lambda: _cfg(enabled=False))
    result = web.web_search("anything")
    assert "禁用" in result
    assert "tools.web.search_enabled" in result


def test_disabled_public_search_short_circuits(monkeypatch):
    import config

    monkeypatch.setattr(config, "get_config", lambda: _cfg(enabled=False))
    result = web.public_web_search("anything")
    assert "禁用" in result


def test_public_search_clamps_to_configured_cap(monkeypatch):
    import config
    import httpx

    seen = {}

    class _Client:
        def __init__(self, **kwargs):
            seen["timeout"] = kwargs.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, headers=None):
            seen["url"] = url
            raise httpx.RequestError("stop here")

    monkeypatch.setattr(config, "get_config", lambda: _cfg(max_results=3, timeout=9))
    monkeypatch.setattr(web, "_guard_validate_public_http_url", lambda url: "")
    monkeypatch.setattr(web.httpx, "Client", _Client)
    web.public_web_search("q", max_results=50)
    assert "count=3" in seen["url"]
    assert seen["timeout"] == 9.0
