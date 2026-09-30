"""URL 出口防护（egress guard）单测。

覆盖：
- core.infrastructure.url_guard 纯函数判定（基准段/special-use IPv6/mapped-NAT64 还原）；
- web_fetch 受控重定向链「公网首跳 → 私网二跳」被拒；
- DOI registry 兜底的路径注入清洗与受控重定向；
- SearxNG 环境变量入口指向内网被拒。
"""

from __future__ import annotations

import email.message
from urllib.request import Request as UrllibRequest

import httpx
import pytest

from core.infrastructure.url_guard import (
    is_public_ip_address,
    validate_public_http_url,
)
from core.web.services.team_workflow.doi_metadata_verification import (
    _crossref_metadata,
    _EgressGuardedRedirectHandler,
    sanitize_doi_for_url,
)
from tools import research_search_backends, web_search_tool

# ============================================================================
# url_guard：URL 字面量纯函数判定
# ============================================================================


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/page",
        "http://8.8.8.8/",
        "http://1.1.1.1:443/x",
        "http://[2606:4700::1111]/",
        "http://[::ffff:8.8.8.8]/",  # IPv4-mapped 公网地址，还原后放行
        "http://[64:ff9b::808:808]/",  # NAT64 well-known 前缀编码的公网 IPv4
        "https://sub-domain.example.co.uk/path?q=1",
    ],
)
def test_guard_allows_public_targets(url):
    assert validate_public_http_url(url) == ""


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/x",
        "http://LOCALHOST:8000/",
        "http://svc.localhost/",
        "http://printer.local/",
        "http://db.internal/",
        "http://127.0.0.1/",  # 旧版显式本机字面量集合，保留「本机」文案
        "http://[::1]/",
    ],
)
def test_guard_blocks_local_hostnames(url):
    assert "本机或内部网络地址" in validate_public_http_url(url)


def test_guard_allows_public_domain_with_local_looking_label():
    """`localhost.evil.com` 是 evil.com 的公网子域，不在后缀拦截范围。"""
    assert validate_public_http_url("http://localhost.evil.com/") == ""


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.1/",
        "http://172.16.0.9/",
        "http://172.31.255.254/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",  # 云元数据端点
        "http://100.64.0.1/",  # CGN 共享地址
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://240.0.0.1/",
        "http://255.255.255.255/",
        "http://192.0.2.1/",  # TEST-NET-1 文档段
        "http://198.51.100.7/",  # TEST-NET-2
        "http://203.0.113.9/",  # TEST-NET-3
        "http://198.18.0.1/",  # 基准测试网段（RFC 2544）
        "http://198.19.255.4/",  # 基准测试网段上限方向
    ],
)
def test_guard_blocks_private_ipv4_literals(url):
    assert "私有、环回或保留 IP" in validate_public_http_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://[fe80::1]/",
        "http://[fc00::1]/",
        "http://[fd12::1]/",
        "http://[ff02::1]/",
        "http://[2001:db8::1]/",  # 文档段
        "http://[64:ff9b:1::1]/",  # NAT64 local-use 前缀（RFC 8215）
        "http://[100::1]/",  # discard-only
        "http://[2001:2::1]/",  # IPv6 基准段
        "http://[2001:10::1]/",  # ORCHID
        "http://[2001:20::1]/",  # ORCHIDv2
        "http://[2001::1]/",  # Teredo 所在 IETF 协议段
        "http://[2002:7f00:1::]/",  # 6to4 内嵌 127.0.0.1，整体拒绝
    ],
)
def test_guard_blocks_special_use_ipv6_literals(url):
    assert "私有、环回或保留 IP" in validate_public_http_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://[::ffff:10.0.0.1]/",  # mapped 私网 IPv4
        "http://[::ffff:169.254.169.254]/",  # mapped 云元数据端点
        "http://[64:ff9b::7f00:1]/",  # NAT64 编码 127.0.0.1
        "http://[64:ff9b::a9fe:a9fe]/",  # NAT64 编码 169.254.169.254
        "http://[fe80::1%25eth0]/",  # 带 zone id 的链路本地地址
    ],
)
def test_guard_unwraps_carrier_prefixes_before_policy(url):
    """mapped/NAT64 编码的私网目标必须先还原再判定，zone id fail closed。"""
    assert "私有、环回或保留 IP" in validate_public_http_url(url)


def test_guard_unwrap_semantics_on_bare_addresses():
    assert is_public_ip_address("::ffff:8.8.8.8") is True
    assert is_public_ip_address("::ffff:127.0.0.1") is False
    assert is_public_ip_address("64:ff9b::808:808") is True
    assert is_public_ip_address("64:ff9b::7f00:1") is False
    assert is_public_ip_address("8.8.8.8") is True
    assert is_public_ip_address("198.18.0.1") is False
    assert is_public_ip_address("not-an-ip") is False


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "file:///etc/passwd",
        "example.com",
        "",
        "http:///no-host",
        "http://user:pass@example.com/",
        "http://user@example.com/",
    ],
)
def test_guard_blocks_bad_shape(url):
    error = validate_public_http_url(url)
    assert error != ""


# ============================================================================
# web_fetch：受控重定向链，二跳落私网必须被拒
# ============================================================================


class _FakeClient:
    def __init__(self, handler):
        self.handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        return self.handler("GET", url, **kwargs)


def _install_fake_client(monkeypatch, handler):
    monkeypatch.setattr(
        web_search_tool.httpx, "Client", lambda *args, **kwargs: _FakeClient(handler)
    )


def test_web_fetch_rejects_redirect_to_private_ipv4(monkeypatch):
    def fake_get(method, url, **kwargs):
        return httpx.Response(
            302,
            headers={"location": "http://169.254.169.254/latest/meta-data/"},
            request=httpx.Request("GET", url),
        )

    _install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_fetch("https://example.com/redirect")

    assert "重定向目标被拒绝" in result
    assert "169.254.169.254" in result


def test_web_fetch_rejects_redirect_to_benchmark_ipv4(monkeypatch):
    def fake_get(method, url, **kwargs):
        return httpx.Response(
            302,
            headers={"location": "http://198.18.0.1/"},
            request=httpx.Request("GET", url),
        )

    _install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_fetch("https://example.com/redirect")

    assert "重定向目标被拒绝" in result


def test_web_fetch_rejects_redirect_to_nat64_encoded_loopback(monkeypatch):
    def fake_get(method, url, **kwargs):
        return httpx.Response(
            302,
            headers={"location": "http://[64:ff9b::7f00:1]/"},
            request=httpx.Request("GET", url),
        )

    _install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_fetch("https://example.com/redirect")

    assert "重定向目标被拒绝" in result


def test_web_fetch_rejects_mapped_private_redirect(monkeypatch):
    def fake_get(method, url, **kwargs):
        return httpx.Response(
            302,
            headers={"location": "http://[::ffff:10.0.0.1]/"},
            request=httpx.Request("GET", url),
        )

    _install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_fetch("https://example.com/redirect")

    assert "重定向目标被拒绝" in result


def test_web_fetch_rejects_cross_site_redirect_to_internal_hostname(monkeypatch):
    def fake_get(method, url, **kwargs):
        return httpx.Response(
            302,
            headers={"location": "http://db.internal/secret"},
            request=httpx.Request("GET", url),
        )

    _install_fake_client(monkeypatch, fake_get)

    result = web_search_tool.web_fetch("https://example.com/redirect")

    assert "重定向目标被拒绝" in result


# ============================================================================
# DOI registry 兜底：路径注入清洗 + 宿主白名单 + 受控重定向
# ============================================================================


@pytest.mark.parametrize(
    ("doi", "expected"),
    [
        ("10.1103/PhysRevLett.116.061102", "10.1103/PhysRevLett.116.061102"),
        ("10.1002/(SICI)1097-4628(19970321)63:11", "10.1002/(SICI)1097-4628(19970321)63:11"),
        ("10.48550/arXiv.1802.06039", "10.48550/arXiv.1802.06039"),
        ("10.1234/../../etc/passwd", ""),  # 路径穿越
        ("10.1234/a..b", ""),  # 穿越变体
        ("10.1234/%2e%2e/admin", ""),  # 编码穿越
        ("10.1234/x?next=http://evil", ""),  # 查询注入
        ("10.1234/x#fragment", ""),  # 分段注入
        ("10.1234/admin@host/x", ""),  # userinfo 注入
        ("10.1234/a b", ""),  # 空白
        ("10.1234/a\x00b", ""),  # 空字符
        ("10.1234//double", ""),  # 空路径段
        ("not-a-doi", ""),
        ("", ""),
    ],
)
def test_sanitize_doi_for_url(doi, expected):
    assert sanitize_doi_for_url(doi) == expected


def test_crossref_metadata_skips_network_for_injection_doi(monkeypatch):
    def _fail_open(*args, **kwargs):
        raise AssertionError("injection DOI must not reach the network")

    monkeypatch.setattr(
        "core.web.services.team_workflow.doi_metadata_verification._open_registry_url",
        _fail_open,
    )
    assert _crossref_metadata("10.1234/../../admin", 1.0) is None
    assert _crossref_metadata("10.1234/x?y=1", 1.0) is None


def _redirect_handler_case(allowed_hosts, target):
    handler = _EgressGuardedRedirectHandler(allowed_hosts)
    request = UrllibRequest("https://api.crossref.org/works/10.1234/x")
    return handler.redirect_request(
        request,
        None,
        302,
        "Found",
        email.message.Message(),
        target,
    )


def test_doi_redirect_handler_rejects_private_target():
    import urllib.error

    with pytest.raises(urllib.error.HTTPError):
        _redirect_handler_case(frozenset({"api.crossref.org"}), "http://10.0.0.1/steal")


def test_doi_redirect_handler_rejects_host_outside_allowlist():
    import urllib.error

    with pytest.raises(urllib.error.HTTPError):
        _redirect_handler_case(
            frozenset({"api.crossref.org"}), "https://evil.example.com/payload"
        )


def test_doi_redirect_handler_allows_allowlisted_target():
    request = _redirect_handler_case(
        frozenset({"api.crossref.org"}), "https://api.crossref.org/works/10.1234/y"
    )
    assert isinstance(request, UrllibRequest)
    assert request.full_url == "https://api.crossref.org/works/10.1234/y"


def test_doi_org_redirect_allows_public_publisher_host():
    request = _redirect_handler_case(None, "https://publisher.example.org/article")
    assert isinstance(request, UrllibRequest)


def test_doi_org_redirect_rejects_internal_target():
    import urllib.error

    with pytest.raises(urllib.error.HTTPError):
        _redirect_handler_case(None, "http://192.168.1.1/admin")


# ============================================================================
# SearxNG 环境变量入口：指向内网被拒
# ============================================================================


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:8888",
        "http://169.254.169.254",
        "http://192.168.1.10:8080",
        "http://searx.internal",
        "https://searx.local",
        "ftp://searx.example.org",
    ],
)
def test_searxng_env_internal_target_rejected(monkeypatch, base_url):
    def _fail(*args, **kwargs):
        raise AssertionError("internal SearxNG target must not reach the network")

    monkeypatch.setenv("VIBELUTION_SEARXNG_URL", base_url)
    monkeypatch.setattr(research_search_backends, "_http_get_json", _fail)

    results, event = research_search_backends.searxng_search("query", max_results=3)

    assert results == []
    assert event["status"] == "skipped"
    assert "egress guard" in event["error"]
    assert event["resultCount"] == 0


def test_guard_initial_url_helper_rejects_private(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("must not reach the network")

    monkeypatch.setattr(research_search_backends.httpx, "Client", _fail)
    with pytest.raises(ValueError, match="egress guard"):
        research_search_backends._guard_initial_url("http://10.1.2.3/search")
