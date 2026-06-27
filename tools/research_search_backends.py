"""No-key search backends for research-oriented agent tools."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlencode

import httpx

from tools.research_search_quality import filter_search_results


_HTTP_TIMEOUT_SECONDS = 10.0
_USER_AGENT = "Vibelution-ResearchSearch/1.0 no-key metadata search"
_OPENALEX_URL = "https://api.openalex.org/works"
_ARXIV_URL = "https://export.arxiv.org/api/query"
_GITHUB_REPOSITORY_SEARCH_URL = "https://api.github.com/search/repositories"
_GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"


def _provider_event(provider: str, status: str, *, result_count: int = 0, error: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": provider,
        "status": status,
        "resultCount": int(result_count),
    }
    if error:
        payload["error"] = str(error)[:240]
    return payload


def _http_get_json(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        response = client.get(url, params=params or {}, headers=headers or {"User-Agent": _USER_AGENT})
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}


def _http_get_text(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> str:
    with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        response = client.get(url, params=params or {}, headers=headers or {"User-Agent": _USER_AGENT})
        response.raise_for_status()
        return response.text


def _result(
    *,
    title: str,
    url: str,
    snippet: str = "",
    provider: str,
    source_type: str,
    **metadata: Any,
) -> dict[str, str]:
    payload: dict[str, str] = {
        "title": str(title or "").strip(),
        "url": str(url or "").strip(),
        "snippet": str(snippet or "").strip(),
        "provider": provider,
        "sourceType": source_type,
    }
    for key, value in metadata.items():
        if value not in (None, ""):
            payload[key] = str(value)
    return payload


def _openalex_abstract(item: dict[str, Any]) -> str:
    inverted = item.get("abstract_inverted_index")
    if not isinstance(inverted, dict):
        return ""
    words: dict[int, str] = {}
    for word, positions in inverted.items():
        for position in positions if isinstance(positions, list) else []:
            try:
                words[int(position)] = str(word)
            except (TypeError, ValueError):
                continue
    return " ".join(words[index] for index in sorted(words))[:700]


def openalex_paper_search(query: str, *, max_results: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
    try:
        payload = _http_get_json(
            _OPENALEX_URL,
            params={
                "search": query,
                "per-page": str(max(1, min(int(max_results), 25))),
                "select": "id,doi,display_name,publication_year,primary_location,abstract_inverted_index",
            },
        )
    except Exception as exc:
        return [], _provider_event("openalex", "failed", error=f"{type(exc).__name__}: {exc}")
    items = payload.get("results") if isinstance(payload, dict) else []
    results: list[dict[str, str]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        primary = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
        source = primary.get("source") if isinstance(primary.get("source"), dict) else {}
        landing_page_url = str(primary.get("landing_page_url") or item.get("doi") or item.get("id") or "").strip()
        results.append(
            _result(
                title=str(item.get("display_name") or ""),
                url=landing_page_url,
                snippet=_openalex_abstract(item) or str(source.get("display_name") or ""),
                provider="openalex",
                source_type="paper",
                doi=item.get("doi") or "",
                published=item.get("publication_year") or "",
                source=source.get("display_name") or "",
            )
        )
    return results, _provider_event("openalex", "ok", result_count=len(results))


def arxiv_paper_search(query: str, *, max_results: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
    try:
        text = _http_get_text(
            _ARXIV_URL,
            params={
                "search_query": f"all:{query}",
                "start": "0",
                "max_results": str(max(1, min(int(max_results), 25))),
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
        )
    except Exception as exc:
        return [], _provider_event("arxiv", "failed", error=f"{type(exc).__name__}: {exc}")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [], _provider_event("arxiv", "failed", error=f"ParseError: {exc}")
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    results: list[dict[str, str]] = []
    for entry in root.findall("atom:entry", ns):
        title = re.sub(r"\s+", " ", (entry.findtext("atom:title", default="", namespaces=ns) or "")).strip()
        summary = re.sub(r"\s+", " ", (entry.findtext("atom:summary", default="", namespaces=ns) or "")).strip()
        link = entry.findtext("atom:id", default="", namespaces=ns) or ""
        published = entry.findtext("atom:published", default="", namespaces=ns) or ""
        results.append(
            _result(
                title=title,
                url=link,
                snippet=summary[:700],
                provider="arxiv",
                source_type="paper",
                published=published[:10],
            )
        )
    return results, _provider_event("arxiv", "ok", result_count=len(results))


def searxng_search(query: str, *, max_results: int, category: str = "general") -> tuple[list[dict[str, str]], dict[str, Any]]:
    base_url = os.environ.get("VIBELUTION_SEARXNG_URL", "").strip().rstrip("/")
    if not base_url:
        return [], _provider_event("searxng", "skipped", error="VIBELUTION_SEARXNG_URL not configured")
    try:
        payload = _http_get_json(
            f"{base_url}/search",
            params={
                "q": query,
                "format": "json",
                "categories": category,
            },
        )
    except Exception as exc:
        return [], _provider_event("searxng", "failed", error=f"{type(exc).__name__}: {exc}")
    items = payload.get("results") if isinstance(payload, dict) else []
    results = [
        _result(
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            snippet=str(item.get("content") or ""),
            provider="searxng",
            source_type=category,
        )
        for item in items[:max_results] if isinstance(item, dict)
    ]
    return results, _provider_event("searxng", "ok", result_count=len(results))


def ddgs_search(query: str, *, max_results: int, kind: str = "text") -> tuple[list[dict[str, str]], dict[str, Any]]:
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore
    except Exception as exc:
        return [], _provider_event("ddgs", "skipped", error=f"{type(exc).__name__}: {exc}")
    try:
        with DDGS() as searcher:
            if kind == "news" and hasattr(searcher, "news"):
                raw_items = list(searcher.news(query, max_results=max_results))
            else:
                raw_items = list(searcher.text(query, max_results=max_results))
    except Exception as exc:
        return [], _provider_event("ddgs", "failed", error=f"{type(exc).__name__}: {exc}")
    results = [
        _result(
            title=str(item.get("title") or item.get("heading") or ""),
            url=str(item.get("href") or item.get("url") or ""),
            snippet=str(item.get("body") or item.get("snippet") or item.get("excerpt") or ""),
            provider="ddgs",
            source_type=kind,
            published=item.get("date") or "",
        )
        for item in raw_items[:max_results] if isinstance(item, dict)
    ]
    return results, _provider_event("ddgs", "ok", result_count=len(results))


def github_project_search(query: str, *, max_results: int, language: str = "") -> tuple[list[dict[str, str]], dict[str, Any]]:
    query_text = query
    if language:
        query_text = f"{query_text} language:{language}"
    try:
        payload = _http_get_json(
            _GITHUB_REPOSITORY_SEARCH_URL,
            params={
                "q": query_text,
                "sort": "stars",
                "order": "desc",
                "per_page": str(max(1, min(int(max_results), 20))),
            },
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": _USER_AGENT,
            },
        )
    except Exception as exc:
        return [], _provider_event("github_public_rest", "failed", error=f"{type(exc).__name__}: {exc}")
    items = payload.get("items") if isinstance(payload, dict) else []
    results = [
        _result(
            title=str(item.get("full_name") or item.get("name") or ""),
            url=str(item.get("html_url") or ""),
            snippet=str(item.get("description") or ""),
            provider="github_public_rest",
            source_type="project",
            stars=item.get("stargazers_count") or "",
            language=item.get("language") or "",
        )
        for item in items[:max_results] if isinstance(item, dict)
    ]
    return results, _provider_event("github_public_rest", "ok", result_count=len(results))


def google_news_rss_search(query: str, *, max_results: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
    try:
        text = _http_get_text(
            f"{_GOOGLE_NEWS_RSS_URL}?{urlencode({'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})}"
        )
    except Exception as exc:
        return [], _provider_event("google_news_rss", "failed", error=f"{type(exc).__name__}: {exc}")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [], _provider_event("google_news_rss", "failed", error=f"ParseError: {exc}")
    results: list[dict[str, str]] = []
    for item in root.findall("./channel/item")[:max_results]:
        results.append(
            _result(
                title=item.findtext("title", default="") or "",
                url=item.findtext("link", default="") or "",
                snippet=item.findtext("description", default="") or "",
                provider="google_news_rss",
                source_type="news",
                published=item.findtext("pubDate", default="") or "",
            )
        )
    return results, _provider_event("google_news_rss", "ok", result_count=len(results))


def collect_provider_results(
    query: str,
    providers: list[tuple[str, Any]],
    *,
    max_results: int,
    allowed_domains: str = "",
    blocked_domains: str = "",
) -> dict[str, Any]:
    provider_events: list[dict[str, Any]] = []
    raw_results: list[dict[str, str]] = []
    for provider_name, provider_call in providers:
        results, event = provider_call()
        provider_events.append(event or _provider_event(provider_name, "unknown"))
        raw_results.extend([item for item in results if item.get("title") and item.get("url")])
        if len(raw_results) >= max_results * 3:
            break
    accepted, rejected = filter_search_results(
        query,
        raw_results,
        max_results=max_results,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
    )
    status = "ok" if accepted else ("degraded" if raw_results or provider_events else "failed")
    return {
        "status": status,
        "query": query,
        "results": accepted,
        "rejected": rejected[:20],
        "resultCount": len(accepted),
        "rawResultCount": len(raw_results),
        "rejectedCount": len(rejected),
        "providers": provider_events,
    }
