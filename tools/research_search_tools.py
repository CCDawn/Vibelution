# -*- coding: utf-8 -*-
"""No-quota web research helpers for source discovery agents."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from tools import research_search_backends
from tools.web_search_tool import public_web_search


_MAX_BATCH_QUERIES = 8
_MAX_WORKERS = 4
_MAX_RESULTS_PER_QUERY = 10

_PAPER_DOMAINS = (
    "arxiv.org",
    "openreview.net",
    "aclanthology.org",
    "paperswithcode.com",
    "pubmed.ncbi.nlm.nih.gov",
)
_PROJECT_DOMAINS = (
    "github.com",
    "gitlab.com",
    "pypi.org",
    "npmjs.com",
    "readthedocs.io",
)
_NEWS_DOMAINS = (
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "theverge.com",
    "technologyreview.com",
)


def _clamp_int(value: int, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _parse_items(value: str, *, max_items: int = _MAX_BATCH_QUERIES) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    parsed: object | None = None
    if raw.startswith(("[", "{")):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None
    if isinstance(parsed, dict):
        source = parsed.get("queries") or parsed.get("items") or parsed.get("urls") or []
        values = source if isinstance(source, list) else [source]
    elif isinstance(parsed, list):
        values = parsed
    else:
        delimiter = r"[\n;]+"
        if "\n" not in raw and ";" not in raw and "," in raw:
            delimiter = r"[,]+"
        values = re.split(delimiter, raw)

    items: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        if text in seen:
            continue
        items.append(text)
        seen.add(text)
        if len(items) >= max_items:
            break
    return items


def _domain_query(domains: tuple[str, ...] | list[str]) -> str:
    normalized = [domain.strip().lower() for domain in domains if str(domain or "").strip()]
    if not normalized:
        return ""
    return " (" + " OR ".join(f"site:{domain}" for domain in normalized) + ")"


def _merge_domains(defaults: tuple[str, ...], include_domains: str) -> list[str]:
    result = list(defaults)
    for item in _parse_items(include_domains, max_items=8):
        domain = item.removeprefix("http://").removeprefix("https://").split("/", 1)[0].strip().lower()
        if domain and domain not in result:
            result.append(domain)
    return result


def _render_batch_result(title: str, rows: list[tuple[str, str]]) -> str:
    if not rows:
        return "[错误] 未提供有效搜索词"
    low_quality_count = sum(1 for _, result in rows if str(result or "").strip().startswith("[搜索质量不足]"))
    error_count = sum(1 for _, result in rows if str(result or "").strip().startswith("[错误]"))
    if low_quality_count == len(rows):
        prefix = f"[搜索质量不足] {title} 全部查询都未返回可采信结果。共执行 {len(rows)} 个查询。"
    elif low_quality_count or error_count:
        prefix = f"[{title}] 共执行 {len(rows)} 个查询；低质量 {low_quality_count} 个，失败 {error_count} 个。"
    else:
        prefix = f"[{title}] 共执行 {len(rows)} 个查询。"
    parts = [prefix]
    for index, (query, result) in enumerate(rows, 1):
        parts.append(f"\n## {index}. {query}\n{result}")
    return "\n".join(parts)


def _render_provider_payload(title: str, payload: dict) -> str:
    query = str(payload.get("query") or "").strip()
    providers = [
        f"{item.get('provider')}:{item.get('status')}({item.get('resultCount', 0)})"
        for item in list(payload.get("providers") or [])
        if isinstance(item, dict)
    ]
    results = [item for item in list(payload.get("results") or []) if isinstance(item, dict)]
    if not results:
        return (
            f"[搜索质量不足] {title} 未返回可采信结果。"
            f"providerTrace={'; '.join(providers) or 'none'}; "
            f"rawResultCount={payload.get('rawResultCount', 0)}; "
            f"rejectedCount={payload.get('rejectedCount', 0)}; "
            f"query={query}"
        )
    parts = [
        f"[{title}] 找到 {len(results)} 条可采信结果。"
        f"providerTrace={'; '.join(providers) or 'none'}; "
        f"rejectedCount={payload.get('rejectedCount', 0)}"
    ]
    for index, result in enumerate(results, 1):
        title_text = str(result.get("title") or result.get("url") or "Untitled").strip()
        url = str(result.get("url") or "").strip()
        snippet = str(result.get("snippet") or "").strip()
        provider = str(result.get("provider") or "").strip()
        metadata = []
        for key in ("sourceType", "published", "doi", "stars", "language", "source"):
            value = str(result.get(key) or "").strip()
            if value:
                metadata.append(f"{key}={value}")
        parts.append(f"\n{index}. [{title_text}]({url})")
        if provider or metadata:
            parts.append(f"   - provider={provider}{'; ' + '; '.join(metadata) if metadata else ''}")
        if snippet:
            parts.append(f"   - {snippet[:500]}")
    return "\n".join(parts)


def _provider_or_legacy_web_search(
    query: str,
    *,
    max_results: int,
    allowed_domains: str = "",
    blocked_domains: str = "",
) -> str:
    payload = research_search_backends.collect_provider_results(
        query,
        [
            ("searxng", lambda: research_search_backends.searxng_search(query, max_results=max_results)),
            ("ddgs", lambda: research_search_backends.ddgs_search(query, max_results=max_results)),
        ],
        max_results=max_results,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
    )
    if payload.get("results"):
        return _render_provider_payload("批量公开搜索", payload)
    return public_web_search(
        query=query,
        max_results=max_results,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
    )


def _run_searches(
    queries: list[str],
    *,
    max_results_per_query: int,
    allowed_domains: str = "",
    blocked_domains: str = "",
    max_workers: int = _MAX_WORKERS,
) -> list[tuple[str, str]]:
    limit = _clamp_int(max_results_per_query, default=5, minimum=1, maximum=_MAX_RESULTS_PER_QUERY)
    workers = _clamp_int(max_workers, default=_MAX_WORKERS, minimum=1, maximum=_MAX_WORKERS)
    if not queries:
        return []
    rows: list[tuple[str, str] | None] = [None] * len(queries)

    def _search_one(query: str) -> str:
        return _provider_or_legacy_web_search(
            query=query,
            max_results=limit,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
        )

    with ThreadPoolExecutor(max_workers=min(workers, len(queries)), thread_name_prefix="research-search") as pool:
        futures = {pool.submit(_search_one, query): index for index, query in enumerate(queries)}
        for future in as_completed(futures):
            index = futures[future]
            query = queries[index]
            try:
                rows[index] = (query, future.result())
            except Exception as exc:
                rows[index] = (query, f"[错误] 查询失败但批量任务继续: {type(exc).__name__}: {exc}")
    return [row for row in rows if row is not None]


def batch_web_search(
    queries: str,
    max_results_per_query: int = 5,
    allowed_domains: str = "",
    blocked_domains: str = "",
    max_workers: int = _MAX_WORKERS,
) -> str:
    """Run several public web searches concurrently and keep failures isolated."""
    parsed_queries = _parse_items(queries)
    rows = _run_searches(
        parsed_queries,
        max_results_per_query=max_results_per_query,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
        max_workers=max_workers,
    )
    return _render_batch_result("批量公开搜索", rows)


def paper_search(topic: str, max_results: int = 8, year_hint: str = "", include_domains: str = "") -> str:
    """Search public paper pages without paid scholarly APIs."""
    topic_text = str(topic or "").strip()
    if not topic_text:
        return "[错误] 论文搜索主题不能为空"
    domains = _merge_domains(_PAPER_DOMAINS, include_domains)
    year = f" {str(year_hint).strip()}" if str(year_hint or "").strip() else ""
    provider_query = f"{topic_text}{year}".strip()
    provider_payload = research_search_backends.collect_provider_results(
        provider_query,
        [
            ("openalex", lambda: research_search_backends.openalex_paper_search(provider_query, max_results=max_results)),
            ("arxiv", lambda: research_search_backends.arxiv_paper_search(provider_query, max_results=max_results)),
            ("searxng", lambda: research_search_backends.searxng_search(provider_query, max_results=max_results, category="science")),
            ("ddgs", lambda: research_search_backends.ddgs_search(provider_query, max_results=max_results)),
        ],
        max_results=max_results,
    )
    if provider_payload.get("results"):
        return _render_provider_payload("论文公开搜索", provider_payload)
    query = f'{topic_text} paper OR preprint OR benchmark OR survey{year}{_domain_query(domains)}'
    return public_web_search(query=query, max_results=max_results, allowed_domains=",".join(domains))


def project_search(topic: str, max_results: int = 8, language: str = "", include_domains: str = "") -> str:
    """Search public project/package/repository pages without GitHub or package registry APIs."""
    topic_text = str(topic or "").strip()
    if not topic_text:
        return "[错误] 项目搜索主题不能为空"
    domains = _merge_domains(_PROJECT_DOMAINS, include_domains)
    language_hint = f" {str(language).strip()}" if str(language or "").strip() else ""
    provider_query = f"{topic_text}{language_hint}".strip()
    provider_payload = research_search_backends.collect_provider_results(
        provider_query,
        [
            ("github_public_rest", lambda: research_search_backends.github_project_search(provider_query, max_results=max_results, language=str(language or "").strip())),
            ("searxng", lambda: research_search_backends.searxng_search(provider_query, max_results=max_results)),
            ("ddgs", lambda: research_search_backends.ddgs_search(provider_query, max_results=max_results)),
        ],
        max_results=max_results,
    )
    if provider_payload.get("results"):
        return _render_provider_payload("项目公开搜索", provider_payload)
    query = f'{topic_text}{language_hint} open source project repository package docs{_domain_query(domains)}'
    return public_web_search(query=query, max_results=max_results, allowed_domains=",".join(domains))


def news_search(topic: str, max_results: int = 8, date_hint: str = "") -> str:
    """Search current public news pages without NewsAPI or quota-backed providers."""
    topic_text = str(topic or "").strip()
    if not topic_text:
        return "[错误] 新闻搜索主题不能为空"
    date_part = f" {str(date_hint).strip()}" if str(date_hint or "").strip() else " 2026"
    provider_query = f"{topic_text}{date_part}".strip()
    provider_payload = research_search_backends.collect_provider_results(
        provider_query,
        [
            ("google_news_rss", lambda: research_search_backends.google_news_rss_search(provider_query, max_results=max_results)),
            ("searxng", lambda: research_search_backends.searxng_search(provider_query, max_results=max_results, category="news")),
            ("ddgs", lambda: research_search_backends.ddgs_search(provider_query, max_results=max_results, kind="news")),
        ],
        max_results=max_results,
    )
    if provider_payload.get("results"):
        return _render_provider_payload("新闻公开搜索", provider_payload)
    query = f'{topic_text} news latest analysis{date_part}{_domain_query(_NEWS_DOMAINS)}'
    return public_web_search(query=query, max_results=max_results, allowed_domains=",".join(_NEWS_DOMAINS))


def search_summarize_sources(search_outputs: str, max_sources: int = 20) -> str:
    """Extract and deduplicate source links from prior search output."""
    limit = _clamp_int(max_sources, default=20, minimum=1, maximum=50)
    text = str(search_outputs or "")
    if not text.strip():
        return "[错误] 搜索结果内容不能为空"

    link_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)|(?<!\()(?P<bare>https?://[^\s)>\"]+)")
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in link_pattern.finditer(text):
        title = (match.group(1) or "").strip()
        url = (match.group(2) or match.group("bare") or "").strip().rstrip(".,;")
        if not url:
            continue
        parsed = urlparse(url)
        key = f"{parsed.scheme}://{parsed.netloc.lower()}{parsed.path}".rstrip("/")
        if not parsed.netloc or key in seen:
            continue
        sources.append(
            {
                "title": title or parsed.netloc,
                "url": url,
                "domain": parsed.netloc.lower(),
            }
        )
        seen.add(key)
        if len(sources) >= limit:
            break

    if not sources:
        return "[来源整理] 未从输入中识别出 URL。"
    return json.dumps(
        {
            "status": "ok",
            "sourceCount": len(sources),
            "sources": sources,
        },
        ensure_ascii=False,
        indent=2,
    )
