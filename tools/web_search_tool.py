# -*- coding: utf-8 -*-
"""
网络搜索工具 - 基于 AutoGLM Web Search API

调用 AutoGLM Web Search 接口进行网络搜索，返回格式化的摘要和参考来源。

API 协议（参考 C:\\Users\\17533\\.agents\\skills\\autoglm-websearch\\SKILL.md）：
- Token:  GET http://127.0.0.1:53699/get_token  →  Bearer xxx
- Search: POST https://autoglm-api.zhipuai.cn/agentdr/v1/assistant/skills/web-search
- Headers: X-Auth-Appid=100003, X-Auth-TimeStamp, X-Auth-Sign(MD5)
- Body:    {"queries": [{"query": "<搜索词>"}]}
"""

from __future__ import annotations

import os
import json
import time
import hashlib
import base64
import html as html_lib
import ipaddress
import re
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from typing import List, Dict, Any

import httpx


# ============================================================================
# API 常量 — 从环境变量读取，避免硬编码凭据
# ============================================================================

_APP_ID = os.environ.get("AUTOGLM_APP_ID", "")
_APP_KEY = os.environ.get("AUTOGLM_APP_KEY", "")
_API_URL = "https://autoglm-api.zhipuai.cn/agentdr/v1/assistant/skills/web-search"
_DEFAULT_TOKEN_URL = "http://127.0.0.1:53699/get_token"
_TOKEN_URL = os.environ.get("AUTOGLM_TOKEN_URL", _DEFAULT_TOKEN_URL).strip() or _DEFAULT_TOKEN_URL
_REQUEST_TIMEOUT = 30.0  # 秒
_TOKEN_TIMEOUT = 10.0  # 秒
_PUBLIC_SEARCH_URL = "https://www.bing.com/search"
_PUBLIC_SEARCH_TIMEOUT = 12.0
_PUBLIC_SEARCH_MAX_RESULTS = 20
_WEB_FETCH_TIMEOUT = 30.0
_WEB_FETCH_MAX_BYTES = 2 * 1024 * 1024
_WEB_FETCH_MAX_REDIRECTS = 5
_USER_AGENT = "Mozilla/5.0 (compatible; Vibelution/1.0; research search tools)"
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")


class AutoGLMTokenServiceError(RuntimeError):
    """Structured failure raised when the local AutoGLM token dependency is unavailable."""

    def __init__(self, status: str, message: str, *, token_url: str = _TOKEN_URL, http_status: int | None = None):
        super().__init__(message)
        self.status = status
        self.token_url = token_url
        self.http_status = http_status

    def to_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "dependency": "autoglm_token_service",
            "stage": "token_fetch",
            "status": self.status,
            "tokenUrl": self.token_url,
            "searchApiCalled": False,
        }
        if self.http_status is not None:
            fields["httpStatus"] = self.http_status
        return fields


# ============================================================================
# Token 获取
# ============================================================================

def _record_dependency_event(error: AutoGLMTokenServiceError) -> None:
    """Record token dependency failures without leaking token or full query text."""
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "tool",
            "web_search",
            "tool.web_search.dependency_unavailable",
            message=f"web_search_tool dependency failed: {error.status}",
            level="warning",
            outcome="failed",
            fields=error.to_fields(),
            lifecycle=True,
        )
    except Exception:
        return


def _format_token_service_error(error: AutoGLMTokenServiceError) -> str:
    fields = error.to_fields()
    diagnostic = (
        "\n"
        f"依赖: {fields['dependency']}\n"
        f"阶段: {fields['stage']}\n"
        f"状态: {fields['status']}\n"
        f"tokenUrl: {fields['tokenUrl']}\n"
        f"searchApiCalled: {str(fields['searchApiCalled']).lower()}\n"
        "建议: 请先启动或恢复本地 AutoGLM token 服务；如果端口已变化，设置 AUTOGLM_TOKEN_URL。"
    )
    return f"[错误] {error}{diagnostic}"


def check_autoglm_token_service() -> dict[str, Any]:
    """Probe the configured local AutoGLM token service without returning the token."""
    try:
        token = _get_bearer_token()
    except AutoGLMTokenServiceError as error:
        return {
            "available": False,
            **error.to_fields(),
        }
    return {
        "available": True,
        "dependency": "autoglm_token_service",
        "stage": "token_fetch",
        "status": "available",
        "tokenUrl": _TOKEN_URL,
        "tokenPresent": bool(token),
    }


def _get_bearer_token() -> str:
    """从本地服务获取 Bearer token"""
    try:
        with httpx.Client(timeout=_TOKEN_TIMEOUT) as client:
            response = client.get(_TOKEN_URL)
            response.raise_for_status()
            token = response.text.strip()
    except httpx.ConnectError as e:
        raise AutoGLMTokenServiceError(
            "unavailable",
            "本地 AutoGLM token 服务不可用，无法连接 "
            f"{_TOKEN_URL}。这一步发生在调用外网搜索 API 之前，"
            "因此当前不是外网搜索接口失败；请先启动或恢复本地 token 服务。"
        ) from e
    except httpx.TimeoutException as e:
        raise AutoGLMTokenServiceError(
            "timeout",
            "本地 AutoGLM token 服务响应超时，无法获取 token。"
            f"请检查 {_TOKEN_URL} 是否卡住或负载过高。"
        ) from e
    except httpx.HTTPStatusError as e:
        raise AutoGLMTokenServiceError(
            "http_error",
            "本地 AutoGLM token 服务返回错误状态："
            f"HTTP {e.response.status_code} {e.response.text[:200]}",
            http_status=e.response.status_code,
        ) from e
    except httpx.RequestError as e:
        raise AutoGLMTokenServiceError("request_error", f"本地 AutoGLM token 服务请求失败: {e}") from e
    except Exception as e:
        raise AutoGLMTokenServiceError("unknown_error", f"无法从本地服务获取 token: {type(e).__name__}: {e}") from e

    if not token:
        raise AutoGLMTokenServiceError("empty_token", "获取到的 token 为空")

    if not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    return token


# ============================================================================
# 签名生成
# ============================================================================

def _build_headers(token: str, query: str) -> Dict[str, str]:
    """构建带签名的请求头"""
    timestamp = str(int(time.time()))
    sign_data = f"{_APP_ID}&{timestamp}&{_APP_KEY}"
    sign = hashlib.md5(sign_data.encode("utf-8")).hexdigest()

    payload = json.dumps({"queries": [{"query": query}]}).encode("utf-8")

    return {
        "Authorization": token,
        "Content-Type": "application/json",
        "X-Auth-Appid": _APP_ID,
        "X-Auth-TimeStamp": timestamp,
        "X-Auth-Sign": sign,
    }, payload


# ============================================================================
# 响应解析
# ============================================================================

def _parse_response(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    从 API 响应中提取搜索结果

    响应结构:
    {
      "code": 0,
      "msg": "SUCCESS",
      "data": {
        "results": [
          {
            "webPages": {
              "value": [
                {"name": "...", "url": "...", "snippet": "..."}
              ]
            }
          }
        ]
      }
    }
    """
    results: List[Dict[str, str]] = []

    try:
        results_list = data.get("data", {}).get("results", [])
        for result_item in results_list:
            web_pages = result_item.get("webPages", {})
            values = web_pages.get("value", [])
            for item in values:
                results.append({
                    "name": item.get("name", "无标题"),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                })
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"搜索响应结构异常：{type(exc).__name__}") from exc

    return results


def _clamp_int(value: int, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _split_domain_list(value: str | None) -> list[str]:
    if not value:
        return []
    domains: list[str] = []
    for item in re.split(r"[\n,;]+", str(value)):
        normalized = item.strip().lower()
        normalized = normalized.removeprefix("http://").removeprefix("https://")
        normalized = normalized.split("/", 1)[0].strip(".")
        if normalized:
            domains.append(normalized)
    return list(dict.fromkeys(domains))


def _host_matches_domain(host: str, domain: str) -> bool:
    normalized_host = host.lower().strip(".")
    normalized_domain = domain.lower().strip(".")
    return normalized_host == normalized_domain or normalized_host.endswith(f".{normalized_domain}")


def _domain_filter_allows(url: str, *, allowed_domains: str = "", blocked_domains: str = "") -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    blocked = _split_domain_list(blocked_domains)
    if any(_host_matches_domain(host, domain) for domain in blocked):
        return False
    allowed = _split_domain_list(allowed_domains)
    return not allowed or any(_host_matches_domain(host, domain) for domain in allowed)


def _validate_public_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "URL 必须使用 http:// 或 https://"
    if not parsed.hostname:
        return "URL 缺少主机名"
    if parsed.username or parsed.password:
        return "URL 不能包含用户名或密码"
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return "出于安全原因，不允许访问本机或内部网络地址"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return ""
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return "出于安全原因，不允许访问私有、环回或保留 IP 地址"
    return ""


def _clean_html_fragment(fragment: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", fragment, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _decode_search_result_url(url: str) -> str:
    candidate = html_lib.unescape(str(url or "").strip())
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if (not parsed.hostname or parsed.hostname.lower().endswith("bing.com")) and parsed.path.startswith("/ck/"):
        encoded = parse_qs(parsed.query).get("u", [""])[0]
        encoded = unquote(encoded)
        if encoded.startswith("a1"):
            encoded = encoded[2:]
        if encoded:
            try:
                padded = encoded + "=" * (-len(encoded) % 4)
                decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
                if decoded.startswith(("http://", "https://")):
                    return decoded
            except Exception:
                pass
    return candidate


def _parse_public_search_html(document: str, *, max_results: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    blocks = re.findall(
        r"<li\b[^>]*class=[\"'][^\"']*\bb_algo\b[^\"']*[\"'][^>]*>(.*?)</li>",
        document,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not blocks:
        blocks = re.findall(r"<h2\b[^>]*>.*?</h2>.*?(?=<h2\b|$)", document, flags=re.DOTALL | re.IGNORECASE)
    for block in blocks:
        anchor = re.search(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", block, flags=re.DOTALL | re.IGNORECASE)
        if not anchor:
            continue
        url = _decode_search_result_url(anchor.group(1))
        if _validate_public_http_url(url):
            continue
        normalized_url = url.split("#", 1)[0]
        if normalized_url in seen_urls:
            continue
        title = _clean_html_fragment(anchor.group(2)) or "无标题"
        snippet_match = re.search(r"<p\b[^>]*>(.*?)</p>", block, flags=re.DOTALL | re.IGNORECASE)
        snippet = _clean_html_fragment(snippet_match.group(1)) if snippet_match else ""
        results.append({"name": title, "url": url, "snippet": snippet})
        seen_urls.add(normalized_url)
        if len(results) >= max_results:
            break
    return results


def _format_search_results(
    query: str,
    results: list[dict[str, str]],
    *,
    provider: str,
    note: str = "",
) -> str:
    if not results:
        return f"[搜索] 未找到与「{query}」相关的结果\n来源: {provider}"

    snippets = [item.get("snippet", "") for item in results if item.get("snippet")]
    summary = f"关于「{query}」，通过 {provider} 搜索到 {len(results)} 条相关结果：\n\n"
    if snippets:
        summary += " | ".join(f"• {snippet[:150]}{'...' if len(snippet) > 150 else ''}" for snippet in snippets[:3])
        if len(snippets) > 3:
            summary += f"\n（另有 {len(snippets) - 3} 条相关结果）"
    else:
        summary += "搜索结果包含标题和链接，但无摘要信息。"
    if note:
        summary += f"\n\n{note}"

    sources = "\n\n**参考来源：**\n"
    for index, item in enumerate(results, 1):
        title = item.get("name") or "无标题"
        url = item.get("url") or ""
        snippet = item.get("snippet") or ""
        if url:
            sources += f"{index}. [{title}]({url})"
        else:
            sources += f"{index}. {title}"
        if snippet:
            sources += f"\n   - {snippet[:220]}{'...' if len(snippet) > 220 else ''}"
        sources += "\n"
    return summary + sources


def public_web_search(
    query: str,
    max_results: int = 10,
    allowed_domains: str = "",
    blocked_domains: str = "",
) -> str:
    """Use a keyless public search result page as a bounded no-quota fallback."""
    if not query or not query.strip():
        return "[错误] 搜索关键词不能为空"
    limit = _clamp_int(max_results, default=10, minimum=1, maximum=_PUBLIC_SEARCH_MAX_RESULTS)
    search_url = f"{_PUBLIC_SEARCH_URL}?q={quote_plus(query.strip())}&count={limit}"
    try:
        with httpx.Client(timeout=_PUBLIC_SEARCH_TIMEOUT, follow_redirects=True) as client:
            try:
                response = client.get(search_url, headers={"User-Agent": _USER_AGENT})
            except TypeError:
                response = client.get(search_url)
            response.raise_for_status()
            document = response.text
    except httpx.HTTPStatusError as exc:
        return f"[错误] 公开搜索页请求失败: HTTP {exc.response.status_code}"
    except httpx.TimeoutException:
        return f"[错误] 公开搜索页请求超时 ({_PUBLIC_SEARCH_TIMEOUT:g}s)"
    except httpx.RequestError as exc:
        return f"[错误] 公开搜索页请求失败: {exc}"
    except Exception as exc:
        return f"[错误] 公开搜索页解析失败: {type(exc).__name__}: {exc}"

    results = [
        item
        for item in _parse_public_search_html(document, max_results=limit * 2)
        if _domain_filter_allows(item.get("url", ""), allowed_domains=allowed_domains, blocked_domains=blocked_domains)
    ][:limit]
    domain_note = ""
    if allowed_domains or blocked_domains:
        domain_note = f"域名过滤: allowed={allowed_domains or '*'}, blocked={blocked_domains or '-'}"
    return _format_search_results(query.strip(), results, provider="public_web_search", note=domain_note)


def _maybe_public_search_fallback(error: AutoGLMTokenServiceError, query: str, max_results: int) -> str | None:
    if error.status == "empty_token":
        return None
    fallback = public_web_search(query=query, max_results=max_results)
    if fallback.startswith("[错误]"):
        return f"\n\n[公开搜索降级失败]\n{fallback}"
    return (
        "\n\n[公开搜索降级]\n"
        "AutoGLM token 服务当前不可用，已改用无需 API key 的公开搜索页解析结果。\n"
        f"{fallback}"
    )


# ============================================================================
# 核心搜索函数
# ============================================================================

def web_search(query: str, max_results: int = 10) -> str:
    """
    执行网络搜索并返回格式化结果

    Args:
        query: 搜索关键词
        max_results: 最大返回结果数（默认 10）

    Returns:
        格式化字符串，包含搜索摘要和参考来源列表
    """
    if not query or not query.strip():
        return "[错误] 搜索关键词不能为空"

    # 1. 获取 token
    try:
        token = _get_bearer_token()
    except AutoGLMTokenServiceError as e:
        _record_dependency_event(e)
        diagnostic = _format_token_service_error(e)
        fallback = _maybe_public_search_fallback(e, query.strip(), max_results)
        if fallback and fallback.startswith("\n\n[公开搜索降级]\n"):
            return fallback.strip() + "\n\n[AutoGLM token 诊断]\n" + diagnostic
        return diagnostic + (fallback or "")

    # 2. 构建请求
    headers, payload = _build_headers(token, query.strip())

    # 3. 发起请求
    try:
        with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
            response = client.post(_API_URL, headers=headers, content=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        return f"[错误] HTTP 请求失败: {e.response.status_code} {e.response.text[:200]}"
    except httpx.RequestError as e:
        return f"[错误] 网络请求失败: {e}"
    except json.JSONDecodeError as e:
        return f"[错误] 响应 JSON 解析失败: {e}"

    # 4. 检查 API 返回码
    code = data.get("code", -1)
    if code != 0:
        msg = data.get("msg", "未知错误")
        return f"[错误] API 返回错误: code={code}, msg={msg}"

    # 5. 解析结果
    try:
        results = _parse_response(data)
    except ValueError as exc:
        return f"[错误] 搜索响应解析失败: {exc}"

    if not results:
        return f"[搜索] 未找到与「{query}」相关的结果"

    # 6. 限制结果数量并格式化
    limit = _clamp_int(max_results, default=10, minimum=1, maximum=50)
    return _format_search_results(query.strip(), results[:limit], provider="AutoGLM Web Search")


# ============================================================================
# 网页内容抓取
# ============================================================================

def _read_response_text(response: httpx.Response) -> str:
    content_type = str(response.headers.get("content-type") or "").lower()
    if content_type and not any(
        marker in content_type
        for marker in ("text/", "html", "xml", "json", "javascript", "xhtml")
    ):
        return f"[错误] 不支持的内容类型: {content_type[:120]}"
    content = response.content
    if len(content) > _WEB_FETCH_MAX_BYTES:
        return f"[错误] 网页内容超过安全上限 {_WEB_FETCH_MAX_BYTES} bytes，已停止处理。"
    encoding = response.encoding or "utf-8"
    return content.decode(encoding, errors="replace")


def _extract_plain_text(document: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", document, flags=re.DOTALL)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<noscript[^>]*>.*?</noscript>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|section|article|li|h[1-6]|tr)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip()


def _fetch_with_same_host_redirects(url: str) -> tuple[str, httpx.Response | None]:
    current_url = url
    original_host = (urlparse(url).hostname or "").lower()
    try:
        with httpx.Client(timeout=_WEB_FETCH_TIMEOUT, follow_redirects=False) as client:
            for _ in range(_WEB_FETCH_MAX_REDIRECTS + 1):
                validation_error = _validate_public_http_url(current_url)
                if validation_error:
                    return f"[错误] {validation_error}: {current_url}", None
                try:
                    response = client.get(current_url, headers={"User-Agent": _USER_AGENT})
                except TypeError:
                    response = client.get(current_url)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location", "")
                    if not location:
                        return f"[错误] 重定向响应缺少 Location: {current_url}", None
                    next_url = urljoin(current_url, location)
                    validation_error = _validate_public_http_url(next_url)
                    if validation_error:
                        return f"[错误] 重定向目标被拒绝: {validation_error}: {next_url}", None
                    next_host = (urlparse(next_url).hostname or "").lower()
                    if next_host != original_host:
                        return (
                            "[网页抓取] 目标发生跨主机重定向，已按安全策略停止自动跟随。\n"
                            f"原 URL: {url}\n"
                            f"重定向目标: {next_url}\n"
                            "如确认该目标可信，请直接用 web_fetch_tool 抓取重定向后的 URL。",
                            None,
                        )
                    current_url = next_url
                    continue
                response.raise_for_status()
                return current_url, response
            return f"[错误] 重定向次数超过上限 {_WEB_FETCH_MAX_REDIRECTS}: {url}", None
    except httpx.ConnectError:
        return f"[错误] 无法连接到服务器: {current_url}", None
    except httpx.TimeoutException:
        return f"[错误] 请求超时 ({_WEB_FETCH_TIMEOUT:g}s): {current_url}", None
    except httpx.HTTPStatusError as exc:
        return f"[错误] HTTP {exc.response.status_code}: {current_url}", None
    except Exception as exc:
        return f"[错误] 请求失败: {type(exc).__name__}: {exc}", None


def web_fetch(url: str, max_chars: int = 8000, prompt: str = "") -> str:
    """
    获取网页内容并返回纯文本

    Args:
        url: 要抓取的网页 URL
        max_chars: 最大返回字符数，默认 8000
        prompt: 可选聚焦提示词；不调用模型，只用于标注本次抓取关注点

    Returns:
        网页文本内容（已去除 HTML 标签）
    """
    if not url or not url.strip():
        return "[错误] URL 不能为空"

    url = url.strip()
    validation_error = _validate_public_http_url(url)
    if validation_error:
        return f"[错误] {validation_error}: {url}"

    final_url_or_error, response = _fetch_with_same_host_redirects(url)
    if response is None:
        return final_url_or_error

    document_or_error = _read_response_text(response)
    if document_or_error.startswith("[错误]"):
        return document_or_error

    text = _extract_plain_text(document_or_error)

    limit = _clamp_int(max_chars, default=8000, minimum=500, maximum=50000)
    if len(text) > limit:
        text = text[:limit] + f"\n\n... [截断，原内容 {len(text)} 字符]"

    if not text:
        return f"[网页抓取] URL 内容为空: {final_url_or_error}"

    focus = f"\n关注点: {prompt.strip()[:240]}" if prompt and prompt.strip() else ""
    return f"[网页内容] {final_url_or_error}{focus}\n\n{text}"


# ============================================================================
# LangChain @tool 装饰器接口（供 Key_Tools.py 使用）
# ============================================================================

from langchain_core.tools import tool


@tool
def web_search_tool(query: str, max_results: int = 10) -> str:
    """
    网络搜索工具 - 基于 AutoGLM Web Search API。

    当需要获取实时信息、最新资讯、网络资料时使用此工具。
    支持联网搜索，返回网页摘要和参考来源链接。

    Args:
        query: 搜索关键词（必填），尽量具体以获得更准确的结果
        max_results: 最大返回结果数，默认 10，建议 5-20

    Returns:
        包含搜索摘要和参考来源链接的格式化字符串

    Example:
        web_search_tool(query="Python 异步编程 async await 最佳实践")
    """
    return web_search(query=query, max_results=max_results)
