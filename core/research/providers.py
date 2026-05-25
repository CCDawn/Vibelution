"""Search provider boundary for Research theme discovery."""

from __future__ import annotations

import hashlib
import json
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Protocol

from config.settings import get_network_config

from .models import SourceKind, SourceReliability, new_id


@dataclass(frozen=True)
class SearchResult:
    kind: SourceKind
    title: str
    url: str
    snippet: str
    reliability: SourceReliability = "normal"


class ResearchSearchProvider(Protocol):
    provider_name: str

    def search_papers(self, query: str) -> list[SearchResult]:
        ...

    def search_github(self, query: str) -> list[SearchResult]:
        ...

    def search_datasets(self, query: str) -> list[SearchResult]:
        ...

    def search_web(self, query: str) -> list[SearchResult]:
        ...


class DeterministicResearchSearchProvider:
    """Stable provider used by the first MVP and tests.

    It preserves the live-search boundary while keeping the workflow runnable
    without credentials. Real providers can replace this class without changing
    the repository, service, or frontend contracts.
    """

    provider_name = "deterministic-research-search"

    def search_papers(self, query: str) -> list[SearchResult]:
        topic = _topic(query)
        return [
            SearchResult(
                kind="paper",
                title=f"Survey signals for {topic} in automated scientific discovery",
                url=f"https://example.org/papers/{_stable_slug(query)}-survey",
                snippet=(
                    f"Paper-like source discussing methods, gaps, and evaluation needs around {topic}. "
                    "Use as a verified placeholder until a live scholarly provider is configured."
                ),
                reliability="verified",
            ),
            SearchResult(
                kind="paper",
                title=f"Falsifiable hypothesis generation with {topic}",
                url=f"https://example.org/papers/{_stable_slug(query)}-hypothesis",
                snippet=(
                    f"Academic placeholder emphasizing falsifiability, mechanism claims, and evidence limits for {topic}."
                ),
                reliability="verified",
            ),
        ]

    def search_github(self, query: str) -> list[SearchResult]:
        topic = _topic(query)
        return [
            SearchResult(
                kind="github",
                title=f"Open-source prototype patterns for {topic}",
                url=f"https://github.com/example/{_stable_slug(query)}-prototype",
                snippet=(
                    f"Repository-style source indicating implementation patterns and possible baselines for {topic}."
                ),
                reliability="verified",
            )
        ]

    def search_datasets(self, query: str) -> list[SearchResult]:
        topic = _topic(query)
        return [
            SearchResult(
                kind="dataset",
                title=f"Public benchmark clues for {topic}",
                url=f"https://huggingface.co/datasets/example/{_stable_slug(query)}",
                snippet=(
                    f"Dataset-style source suggesting public validation signals and measurable tasks for {topic}."
                ),
                reliability="verified",
            )
        ]

    def search_web(self, query: str) -> list[SearchResult]:
        topic = _topic(query)
        return [
            SearchResult(
                kind="web",
                title=f"Background and competition fit for {topic}",
                url=f"https://example.org/web/{_stable_slug(query)}",
                snippet=(
                    f"Web background source connecting {topic} to AI Scientist workflows, tooling, and application context."
                ),
                reliability="normal",
            )
        ]


class PublicResearchSearchProvider:
    """No-key public search provider for the first live Research MVP."""

    provider_name = "public-research-search"

    def __init__(self, *, timeout: float | None = None, per_kind_limit: int = 2):
        self.timeout = timeout
        self.per_kind_limit = max(1, min(5, int(per_kind_limit or 3)))

    def search_papers(self, query: str) -> list[SearchResult]:
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": self.per_kind_limit,
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
        )
        text = _fetch_text(url, timeout=self._timeout(), accept="application/atom+xml")
        if not text:
            return []
        results: list[SearchResult] = []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns)[: self.per_kind_limit]:
            title = _clean_text(entry.findtext("atom:title", default="", namespaces=ns))
            summary = _clean_text(entry.findtext("atom:summary", default="", namespaces=ns))
            link = entry.findtext("atom:id", default="", namespaces=ns).strip()
            if title and link:
                results.append(SearchResult("paper", title, link, summary[:900], "verified"))
        return results

    def search_github(self, query: str) -> list[SearchResult]:
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": self.per_kind_limit,
            }
        )
        payload = _fetch_json(url, timeout=self._timeout(), accept="application/vnd.github+json")
        if not isinstance(payload, dict):
            return []
        results: list[SearchResult] = []
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("full_name") or item.get("name") or "").strip()
            html_url = str(item.get("html_url") or "").strip()
            description = str(item.get("description") or "").strip()
            stars = item.get("stargazers_count")
            snippet = f"{description} Stars: {stars}.".strip()
            if title and html_url:
                results.append(SearchResult("github", title, html_url, snippet[:900], "verified"))
        return results

    def search_datasets(self, query: str) -> list[SearchResult]:
        url = "https://huggingface.co/api/datasets?" + urllib.parse.urlencode(
            {
                "search": query,
                "limit": self.per_kind_limit,
            }
        )
        payload = _fetch_json(url, timeout=self._timeout(), accept="application/json")
        if not isinstance(payload, list):
            return []
        results: list[SearchResult] = []
        for item in payload[: self.per_kind_limit]:
            if not isinstance(item, dict):
                continue
            dataset_id = str(item.get("id") or "").strip()
            likes = item.get("likes")
            downloads = item.get("downloads")
            snippet = f"HuggingFace dataset. Likes: {likes}; downloads: {downloads}."
            if dataset_id:
                results.append(
                    SearchResult(
                        "dataset",
                        dataset_id,
                        f"https://huggingface.co/datasets/{dataset_id}",
                        snippet,
                        "verified",
                    )
                )
        return results

    def search_web(self, query: str) -> list[SearchResult]:
        url = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})
        text = _fetch_text(url, timeout=self._timeout(), accept="text/html")
        if not text:
            return []
        results: list[SearchResult] = []
        # DuckDuckGo Lite returns simple anchor rows. Keep this parser deliberately
        # conservative; failed parsing simply yields no web results.
        for href, label in re.findall(r'<a rel="nofollow" href="([^"]+)"[^>]*>(.*?)</a>', text, flags=re.I | re.S):
            title = _strip_html(label)
            target = _duckduckgo_target(href)
            if not title or not target:
                continue
            results.append(SearchResult("web", title[:240], target, f"General web result for {query}.", "normal"))
            if len(results) >= self.per_kind_limit:
                break
        return results

    def _timeout(self) -> float:
        if self.timeout is not None:
            return float(self.timeout)
        try:
            return float(get_network_config().timeout)
        except Exception:
            return 30.0


def stable_source_id(session_id: str, run_id: str, result: SearchResult) -> str:
    digest = hashlib.sha1(f"{session_id}|{run_id}|{result.kind}|{result.url}".encode("utf-8")).hexdigest()[:12]
    return f"src-{digest}"


def stable_evidence_id(source_id: str, evidence_type: str) -> str:
    digest = hashlib.sha1(f"{source_id}|{evidence_type}".encode("utf-8")).hexdigest()[:12]
    return f"ev-{digest}"


def new_session_id() -> str:
    return new_id("research-session")


def _stable_slug(value: str) -> str:
    words = [part for part in "".join(ch.lower() if ch.isalnum() else "-" for ch in value).split("-") if part]
    slug = "-".join(words[:8]) or "query"
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def _topic(query: str) -> str:
    words = [word for word in query.strip().split() if word]
    return " ".join(words[:7]) if words else "AI Scientist theme discovery"


def _fetch_text(url: str, *, timeout: float, accept: str) -> str:
    network = get_network_config()
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": network.user_agent or "VibelutionResearchWorkbench/0.1 (+local)",
        },
    )
    opener = _build_network_opener(network)
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(1024 * 1024)
    return raw.decode("utf-8", errors="replace")


def _fetch_json(url: str, *, timeout: float, accept: str):
    text = _fetch_text(url, timeout=timeout, accept=accept)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _build_network_opener(network=None) -> urllib.request.OpenerDirector:
    network = network or get_network_config()
    handlers: list[urllib.request.BaseHandler] = []
    proxy_url = str(getattr(network, "proxy_url", "") or "").strip()
    if bool(getattr(network, "proxy_enabled", False)):
        if not proxy_url:
            raise ValueError("network.proxy_url is required when network.proxy_enabled is true")
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    if not bool(getattr(network, "verify_ssl", True)):
        handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    return urllib.request.build_opener(*handlers)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _strip_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    value = urllib.parse.unquote(value)
    return _clean_text(value)


def _duckduckgo_target(href: str) -> str:
    href = href.replace("&amp;", "&")
    parsed = urllib.parse.urlparse(href)
    query = urllib.parse.parse_qs(parsed.query)
    uddg = query.get("uddg")
    if uddg:
        return str(uddg[0]).strip()
    if parsed.scheme in {"http", "https"}:
        return href
    return ""
