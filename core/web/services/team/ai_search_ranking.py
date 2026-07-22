"""Pure AI-search source page ranking helpers.

Claim scope: keyword tokenize, clean titles, and rank candidate page links.
No HTTP, disk, or team registry IO.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse


def ai_search_source_page_keywords(text: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", str(text or "").lower()):
        if token not in tokens:
            tokens.append(token)
    return tokens[:16]


def clean_ai_search_source_text(text: str, *, max_length: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned[:max_length]


def rank_ai_search_source_page_references(
    links: list[dict[str, str]],
    *,
    topic: str,
    source_name: str,
    base_url: str,
    max_results: int,
) -> list[dict[str, str]]:
    topic_terms = ai_search_source_page_keywords(f"{topic} {source_name}")
    positive_terms = {
        "ai",
        "agent",
        "agents",
        "model",
        "models",
        "research",
        "release",
        "releases",
        "news",
        "blog",
        "product",
        "developer",
        "paper",
        "benchmark",
        "eval",
        "safety",
        "open-source",
        "open_source",
        "新闻",
        "动态",
        "发布",
        "模型",
        "研究",
        "论文",
        "产品",
        "开发者",
        "开源",
        "安全",
        "评测",
    }
    skip_terms = {
        "privacy",
        "terms",
        "cookie",
        "login",
        "signin",
        "signup",
        "sign-up",
        "careers",
        "jobs",
        "contact",
        "about",
        "subscribe",
        "rss",
        "twitter",
        "linkedin",
        "facebook",
        "instagram",
        "隐私",
        "条款",
        "登录",
        "注册",
        "招聘",
        "联系",
    }
    ranked: list[tuple[int, int, dict[str, str]]] = []
    for index, raw_link in enumerate(links):
        url = urljoin(base_url, str(raw_link.get("url") or "").strip())
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        title = clean_ai_search_source_text(str(raw_link.get("title") or url), max_length=180)
        combined = f"{title} {parsed.netloc} {parsed.path} {parsed.query}".lower()
        if any(term in combined for term in skip_terms):
            continue
        score = 0
        for term in topic_terms:
            if term and term in combined:
                score += 4
        for term in positive_terms:
            if term in combined:
                score += 3
        if parsed.netloc == urlparse(base_url).netloc:
            score += 1
        if score <= 0:
            continue
        ranked.append((score, -index, {"title": title or url, "url": url}))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    references: list[dict[str, str]] = []
    seen: set[str] = set()
    for _score, _index, reference in ranked:
        url = reference["url"]
        if url in seen:
            continue
        seen.add(url)
        references.append(reference)
        if len(references) >= max_results:
            break
    return references


# Historical private aliases.
_ai_search_source_page_keywords = ai_search_source_page_keywords
_clean_ai_search_source_text = clean_ai_search_source_text
_rank_ai_search_source_page_references = rank_ai_search_source_page_references
