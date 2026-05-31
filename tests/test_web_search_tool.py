import httpx

from tools import web_search_tool


def test_web_search_reports_local_token_service_connection_failure(monkeypatch):
    def fake_get(*args, **kwargs):
        request = httpx.Request("GET", web_search_tool._TOKEN_URL)
        raise httpx.ConnectError("[WinError 10061] 由于目标计算机积极拒绝，无法连接。", request=request)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        get = fake_get

    monkeypatch.setattr(web_search_tool.httpx, "Client", FakeClient)

    result = web_search_tool.web_search("AI Agent", max_results=3)

    assert result.startswith("[错误]")
    assert "本地 AutoGLM token 服务不可用" in result
    assert "调用外网搜索 API 之前" in result
    assert web_search_tool._TOKEN_URL in result
