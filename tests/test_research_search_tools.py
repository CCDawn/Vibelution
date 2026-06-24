import json
import time

import httpx

from tools import research_search_tools, web_search_tool


class FakeClient:
    def __init__(self, handler, *args, **kwargs):
        self.handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        return self.handler("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.handler("POST", url, **kwargs)


def install_fake_client(monkeypatch, handler):
    monkeypatch.setattr(web_search_tool.httpx, "Client", lambda *args, **kwargs: FakeClient(handler, *args, **kwargs))


def bing_html(*items):
    blocks = []
    for title, url, snippet in items:
        blocks.append(
            f'<li class="b_algo"><h2><a href="{url}">{title}</a></h2><p>{snippet}</p></li>'
        )
    return "<html><body><ol>" + "\n".join(blocks) + "</ol></body></html>"


def test_public_web_search_parses_and_filters_results(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "GET"
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text=bing_html(
                ("Good Paper", "https://arxiv.org/abs/1234.5678", "agent paper snippet"),
                ("Blocked Repo", "https://github.com/example/repo", "repo snippet"),
            ),
        )

    install_fake_client(monkeypatch, fake_request)

    result = web_search_tool.public_web_search(
        "agent paper",
        max_results=5,
        allowed_domains="arxiv.org",
    )

    assert "Good Paper" in result
    assert "https://arxiv.org/abs/1234.5678" in result
    assert "Blocked Repo" not in result
    assert "域名过滤: allowed=arxiv.org" in result


def test_public_web_search_infers_site_domain_and_rejects_cross_domain_noise(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "GET"
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text=bing_html(
                ("ChatGPT DAN", "https://github.com/0xk1h0/ChatGPT_DAN", "ChatGPT jailbreak prompt"),
                ("Bing quiz", "https://www.wikihow.com/Play-Bing-Homepage-Quiz", "Play the Bing quiz"),
            ),
        )

    install_fake_client(monkeypatch, fake_request)

    result = web_search_tool.public_web_search('"predictive coding" site:arxiv.org', max_results=5)

    assert result.startswith("[搜索质量不足]")
    assert "违反 site/allowed_domains 域名约束" in result
    assert "allowed=arxiv.org" in result
    assert "ChatGPT_DAN" not in result


def test_public_web_search_rejects_low_relevance_same_domain_results(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "GET"
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text=bing_html(
                ("unrelated repository", "https://github.com/example/support", "Microsoft support account help"),
            ),
        )

    install_fake_client(monkeypatch, fake_request)

    result = web_search_tool.public_web_search(
        "predictive coding implementation site:github.com",
        max_results=5,
    )

    assert result.startswith("[搜索质量不足]")
    assert "相关性不足" in result
    assert "unrelated repository" not in result


def test_web_search_does_not_fallback_when_token_service_unavailable(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        if "get_token" in url:
            raise httpx.ConnectError("refused", request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text=bing_html(("Fallback Source", "https://example.com/source", "fallback snippet")),
        )

    install_fake_client(monkeypatch, fake_request)
    monkeypatch.setattr(web_search_tool, "_record_dependency_event", lambda error: None)

    result = web_search_tool.web_search("fallback query", max_results=3)

    assert result.startswith("[错误]")
    assert "本地 AutoGLM token 服务不可用" in result
    assert "Fallback Source" not in result
    assert [method for method, _ in calls] == ["GET"]


def test_batch_web_search_runs_queries_concurrently_and_isolates_failures(monkeypatch):
    starts = []

    def fake_public_web_search(query, max_results=10, allowed_domains="", blocked_domains=""):
        starts.append((query, time.perf_counter()))
        if "bad" in query:
            raise RuntimeError("boom")
        time.sleep(0.05)
        return f"result for {query}"

    monkeypatch.setattr(research_search_tools, "public_web_search", fake_public_web_search)

    started_at = time.perf_counter()
    result = research_search_tools.batch_web_search("alpha\nbad query\nbeta", max_workers=3)
    elapsed = time.perf_counter() - started_at

    assert "result for alpha" in result
    assert "result for beta" in result
    assert "bad query" in result
    assert "查询失败但批量任务继续" in result
    assert elapsed < 0.13


def test_batch_web_search_handles_empty_input():
    assert research_search_tools.batch_web_search(" \n ") == "[错误] 未提供有效搜索词"


def test_paper_project_and_news_search_build_no_quota_queries(monkeypatch):
    calls = []

    def fake_public_web_search(query, max_results=10, allowed_domains="", blocked_domains=""):
        calls.append(
            {
                "query": query,
                "max_results": max_results,
                "allowed_domains": allowed_domains,
                "blocked_domains": blocked_domains,
            }
        )
        return "ok"

    monkeypatch.setattr(research_search_tools, "public_web_search", fake_public_web_search)

    assert research_search_tools.paper_search("agentic rag", year_hint="2025") == "ok"
    assert research_search_tools.project_search("agent harness", language="Python") == "ok"
    assert research_search_tools.news_search("OpenAI research", date_hint="2026-06") == "ok"

    assert "Semantic Scholar" not in json.dumps(calls)
    assert "site:arxiv.org" in calls[0]["query"]
    assert "agentic rag" in calls[0]["query"]
    assert "2025" in calls[0]["query"]
    assert "site:github.com" in calls[1]["query"]
    assert "Python" in calls[1]["query"]
    assert "news latest analysis" in calls[2]["query"]
    assert "reuters.com" in calls[2]["allowed_domains"]


def test_search_summarize_sources_dedupes_markdown_and_bare_urls():
    payload = """
    1. [Paper](https://arxiv.org/abs/1234.5678)
    2. [Duplicate](https://arxiv.org/abs/1234.5678#section)
    3. https://github.com/example/repo
    """

    result = json.loads(research_search_tools.search_summarize_sources(payload, max_sources=10))

    assert result["status"] == "ok"
    assert result["sourceCount"] == 2
    assert result["sources"][0]["title"] == "Paper"
    assert result["sources"][1]["domain"] == "github.com"


def test_web_fetch_blocks_private_hosts_before_network(monkeypatch):
    def fake_client(*args, **kwargs):
        raise AssertionError("private URLs must be rejected before network access")

    monkeypatch.setattr(web_search_tool.httpx, "Client", fake_client)

    result = web_search_tool.web_fetch("http://127.0.0.1:8000/private")

    assert result.startswith("[错误]")
    assert "不允许访问本机或内部网络地址" in result


def test_web_fetch_stops_cross_host_redirect(monkeypatch):
    def fake_request(method, url, **kwargs):
        return httpx.Response(
            302,
            request=httpx.Request("GET", url),
            headers={"location": "https://other.example.com/final"},
        )

    install_fake_client(monkeypatch, fake_request)

    result = web_search_tool.web_fetch("https://example.com/start")

    assert "跨主机重定向" in result
    assert "https://other.example.com/final" in result
