import importlib

import httpx

from tools import web_search_tool


class FakeClient:
    def __init__(self, handler):
        self.handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        return self.handler("GET", url)

    def post(self, url, **kwargs):
        return self.handler("POST", url, **kwargs)


def install_fake_client(monkeypatch, handler):
    monkeypatch.setattr(web_search_tool.httpx, "Client", lambda *args, **kwargs: FakeClient(handler))


def test_web_search_reports_local_token_service_connection_failure(monkeypatch):
    event_args = []

    def fake_get(method, url, **kwargs):
        request = httpx.Request("GET", web_search_tool._TOKEN_URL)
        raise httpx.ConnectError("[WinError 10061] 由于目标计算机积极拒绝，无法连接。", request=request)

    install_fake_client(monkeypatch, fake_get)
    monkeypatch.setattr(web_search_tool, "_record_dependency_event", lambda error: event_args.append(error.to_fields()))

    result = web_search_tool.web_search("AI Agent", max_results=3)

    assert result.startswith("[错误]")
    assert "本地 AutoGLM token 服务不可用" in result
    assert "调用外网搜索 API 之前" in result
    assert web_search_tool._TOKEN_URL in result
    assert "依赖: autoglm_token_service" in result
    assert "阶段: token_fetch" in result
    assert "状态: unavailable" in result
    assert "searchApiCalled: false" in result
    assert event_args == [
        {
            "dependency": "autoglm_token_service",
            "stage": "token_fetch",
            "status": "unavailable",
            "tokenUrl": web_search_tool._TOKEN_URL,
            "searchApiCalled": False,
        }
    ]


def test_web_search_reports_token_service_timeout(monkeypatch):
    def fake_get(method, url, **kwargs):
        request = httpx.Request("GET", web_search_tool._TOKEN_URL)
        raise httpx.TimeoutException("timeout", request=request)

    install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_search("AI Agent", max_results=3)

    assert result.startswith("[错误]")
    assert "状态: timeout" in result
    assert "searchApiCalled: false" in result


def test_web_search_reports_token_service_http_error(monkeypatch):
    def fake_get(method, url, **kwargs):
        request = httpx.Request("GET", web_search_tool._TOKEN_URL)
        response = httpx.Response(500, request=request, text="boom")
        raise httpx.HTTPStatusError("server error", request=request, response=response)

    install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_search("AI Agent", max_results=3)

    assert "状态: http_error" in result
    assert "HTTP 500" in result


def test_web_search_reports_empty_token_without_calling_search_api(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        if method == "GET":
            return httpx.Response(200, request=httpx.Request("GET", url), text="")
        raise AssertionError("Search API should not be called when token is empty")

    install_fake_client(monkeypatch, fake_request)

    result = web_search_tool.web_search("AI Agent", max_results=3)

    assert "状态: empty_token" in result
    assert "searchApiCalled: false" in result
    assert calls == [("GET", web_search_tool._TOKEN_URL)]


def test_check_autoglm_token_service_returns_structured_status(monkeypatch):
    def fake_get(method, url, **kwargs):
        request = httpx.Request("GET", web_search_tool._TOKEN_URL)
        raise httpx.ConnectError("refused", request=request)

    install_fake_client(monkeypatch, fake_get)

    status = web_search_tool.check_autoglm_token_service()

    assert status == {
        "available": False,
        "dependency": "autoglm_token_service",
        "stage": "token_fetch",
        "status": "unavailable",
        "tokenUrl": web_search_tool._TOKEN_URL,
        "searchApiCalled": False,
    }


def test_autoglm_token_url_can_be_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("AUTOGLM_TOKEN_URL", "http://127.0.0.1:59999/get_token")

    reloaded = importlib.reload(web_search_tool)
    try:
        assert reloaded._TOKEN_URL == "http://127.0.0.1:59999/get_token"
    finally:
        monkeypatch.delenv("AUTOGLM_TOKEN_URL", raising=False)
        importlib.reload(web_search_tool)
