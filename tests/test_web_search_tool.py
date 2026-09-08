import importlib
import sys
import threading
import time
import types

import httpx
import pytest

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


def wait_for_condition(predicate, *, description: str, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        threading.Event().wait(0.01)
    pytest.fail(f"Timed out waiting for {description}")


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
    assert "公开搜索降级" not in result


def test_autoglm_search_tool_availability_reports_block_reason(monkeypatch):
    def fake_get(method, url, **kwargs):
        request = httpx.Request("GET", web_search_tool._TOKEN_URL)
        raise httpx.ConnectError("refused", request=request)

    install_fake_client(monkeypatch, fake_get)
    web_search_tool._TOKEN_HEALTH_CACHE["checkedAt"] = 0.0
    web_search_tool._TOKEN_HEALTH_CACHE["status"] = None

    status = web_search_tool.autoglm_search_tool_availability(force=True)

    assert status["available"] is False
    assert status["dependency"] == "autoglm_token_service"
    assert "web_search_tool 已临时禁用" in status["blockReason"]


def test_stale_autoglm_availability_returns_immediately_and_refreshes_in_background(monkeypatch):
    main_thread_id = threading.get_ident()
    web_search_tool._TOKEN_HEALTH_CACHE.clear()
    web_search_tool._TOKEN_HEALTH_CACHE.update(
        {
            "checkedAt": 0.0,
            "status": {"available": False, "status": "unavailable"},
            "refreshing": False,
        }
    )

    def check_in_background(*, timeout=None):
        assert threading.get_ident() != main_thread_id
        return {"available": True, "status": "available", "tokenPresent": True}

    monkeypatch.setattr(web_search_tool, "check_autoglm_token_service", check_in_background)

    status = web_search_tool.autoglm_search_tool_availability()

    assert status == {"available": False, "status": "unavailable"}
    refreshed = wait_for_condition(
        lambda: web_search_tool._TOKEN_HEALTH_CACHE.get("status", {}).get("available") is True,
        description="stale AutoGLM availability refresh",
    )
    assert refreshed is True


def test_missing_autoglm_availability_is_provisional_and_never_blocks_first_turn(monkeypatch):
    main_thread_id = threading.get_ident()
    web_search_tool._TOKEN_HEALTH_CACHE.clear()
    web_search_tool._TOKEN_HEALTH_CACHE.update({"checkedAt": 0.0, "status": None, "refreshing": False})

    def check_in_background(*, timeout=None):
        assert threading.get_ident() != main_thread_id
        return {"available": False, "status": "unavailable"}

    monkeypatch.setattr(web_search_tool, "check_autoglm_token_service", check_in_background)

    status = web_search_tool.autoglm_search_tool_availability()

    assert status["available"] is True
    assert status["status"] == "checking"
    assert status["availabilityProvisional"] is True
    wait_for_condition(
        lambda: web_search_tool._TOKEN_HEALTH_CACHE.get("status", {}).get("status") == "unavailable",
        description="initial AutoGLM availability refresh",
    )


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


def test_web_search_reports_malformed_result_shape(monkeypatch):
    def fake_request(method, url, **kwargs):
        request = httpx.Request(method, url)
        if method == "GET":
            return httpx.Response(200, request=request, text="token-123")
        return httpx.Response(
            200,
            request=request,
            json={"code": 0, "msg": "SUCCESS", "data": {"results": [None]}},
        )

    install_fake_client(monkeypatch, fake_request)

    result = web_search_tool.web_search("AI Agent", max_results=3)

    assert result.startswith("[错误] 搜索响应解析失败")
    assert "搜索响应结构异常：AttributeError" in result


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


def test_extract_plain_text_prefers_trafilatura_when_available(monkeypatch):
    fake_trafilatura = types.SimpleNamespace(
        extract=lambda *args, **kwargs: "Main article text\n\nMain article text"
    )
    monkeypatch.setitem(sys.modules, "trafilatura", fake_trafilatura)

    text = web_search_tool._extract_plain_text("<html><body><script>x()</script><article>fallback</article></body></html>")

    assert text == "Main article text\n\nMain article text"


# ============================================================================
# web_fetch: PDF 提取与同站（注册域）重定向跟随
# ============================================================================


def _build_pdf_bytes(*page_texts: str) -> bytes:
    """Assemble a minimal valid multi-page PDF with one text line per page."""
    page_count = len(page_texts)
    font_num = 3 + 2 * page_count
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(page_count))
    bodies = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode("ascii"),
        font_num: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for index, text in enumerate(page_texts):
        page_num = 3 + 2 * index
        content_num = page_num + 1
        stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("ascii")
        bodies[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_num} 0 R /Resources << /Font << /F1 {font_num} 0 R >> >> >>"
        ).encode("ascii")
        bodies[content_num] = (
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(bodies):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode("ascii")
        out += bodies[num]
        out += b"\nendobj\n"
    xref_pos = len(out)
    max_num = max(bodies)
    out += f"xref\n0 {max_num + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for num in range(1, max_num + 1):
        out += f"{offsets[num]:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<< /Size {max_num + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    return bytes(out)


def test_web_fetch_extracts_pdf_text(monkeypatch):
    pdf_bytes = _build_pdf_bytes("Alpha page one marker", "Bravo page two marker")

    def fake_get(method, url, **kwargs):
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=pdf_bytes,
            request=httpx.Request("GET", url),
        )

    install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_fetch("https://repository.example.com/report.pdf")

    assert result.startswith("[PDF 文本] https://repository.example.com/report.pdf")
    assert "Alpha page one marker" in result
    assert "Bravo page two marker" in result


def test_web_fetch_pdf_over_size_limit_rejected(monkeypatch):
    oversized = b"%PDF-1.4\n" + b"0" * (web_search_tool._WEB_FETCH_MAX_PDF_BYTES + 1)

    def fake_get(method, url, **kwargs):
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=oversized,
            request=httpx.Request("GET", url),
        )

    install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_fetch("https://repository.example.com/huge.pdf")

    assert result.startswith("[错误]")
    assert "超过安全上限" in result


def test_web_fetch_pdf_accepts_repository_sized_files_under_html_cap(monkeypatch):
    # Repository full texts commonly exceed the HTML cap; the PDF cap must let
    # them through to text extraction (bounded separately by the page limit).
    body = _build_pdf_bytes("plastic export estimate", "uncertainty envelope")
    assert len(body) <= web_search_tool._WEB_FETCH_MAX_PDF_BYTES
    monkeypatch.setattr(web_search_tool, "_WEB_FETCH_MAX_BYTES", max(1, len(body) - 1))

    def fake_get(method, url, **kwargs):
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=body,
            request=httpx.Request("GET", url),
        )

    install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_fetch("https://edepot.example.org/577712.pdf")

    assert result.startswith("[PDF 文本]")
    assert "plastic export estimate" in result


def test_web_fetch_pdf_without_text_reports_scanned(monkeypatch):
    blank_pdf = _build_pdf_bytes("", "")

    def fake_get(method, url, **kwargs):
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=blank_pdf,
            request=httpx.Request("GET", url),
        )

    install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_fetch("https://repository.example.com/scanned.pdf")

    assert result.startswith("[错误]")
    assert "PDF 无可提取文本" in result
    assert "扫描件" in result


def test_web_fetch_follows_same_site_idp_redirect_with_cookies(monkeypatch):
    article = "https://www.nature.com/articles/s41586-026-1"
    idp = "https://idp.nature.com/authorize?redirect_uri=abc"
    article_gets = []

    def fake_get(method, url, **kwargs):
        request = httpx.Request("GET", url)
        if url == article:
            article_gets.append(url)
            if len(article_gets) == 1:
                # 真实 nature 链路：文章 303 → idp/authorize（设 cookie）。
                return httpx.Response(303, headers={"location": idp}, request=request)
            # idp 回跳原样 URL；同 client cookie jar 让第二次请求落到 200。
            return httpx.Response(
                200,
                request=request,
                text="<html><body><article>Full text unlocked</article></body></html>",
            )
        if url == idp:
            return httpx.Response(302, headers={"location": article}, request=request)
        raise AssertionError(f"Unexpected fetch: {url}")

    install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_fetch(article)

    assert "跨主机重定向" not in result
    assert article in result
    assert "Full text unlocked" in result
    assert article_gets == [article, article]


def test_web_fetch_stops_cross_site_redirect(monkeypatch):
    springer = "https://link.springer.com/article/10.1007/example"

    def fake_get(method, url, **kwargs):
        return httpx.Response(
            302,
            headers={"location": springer},
            request=httpx.Request("GET", url),
        )

    install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_fetch("https://doi.org/10.1007/example")

    assert "跨主机重定向" in result
    assert "停止自动跟随" in result
    assert springer in result


def test_web_fetch_detects_redirect_loop(monkeypatch):
    calls = []

    def fake_get(method, url, **kwargs):
        calls.append(url)
        target = "https://example.com/b" if url == "https://example.com/a" else "https://example.com/a"
        return httpx.Response(
            302,
            headers={"location": target},
            request=httpx.Request("GET", url),
        )

    install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_fetch("https://example.com/a")

    # 同一 URL 允许到达 2 次（cookie 预授权回跳），第 3 次出现判真实环路。
    assert result == "[错误] 重定向循环: https://example.com/a"
    assert calls == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_registrable_host_suffix_rules():
    registrable = web_search_tool._registrable_host

    assert registrable("nature.com") == registrable("idp.nature.com") == "nature.com"
    assert registrable("doi.org") != registrable("link.springer.com")
    assert registrable("www.oecd.org") == registrable("oecd.org") == "oecd.org"
    assert registrable("bbc.co.uk") == registrable("www.bbc.co.uk") == "bbc.co.uk"
    assert registrable("bbc.co.uk") != registrable("itv.co.uk")
