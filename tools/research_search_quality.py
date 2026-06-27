"""Quality gates shared by no-key research search tools."""

from __future__ import annotations

import re
from urllib.parse import urlparse


GENERIC_SEARCH_TERMS = {
    "paper",
    "papers",
    "preprint",
    "preprints",
    "benchmark",
    "benchmarks",
    "survey",
    "surveys",
    "review",
    "reviews",
    "project",
    "repository",
    "package",
    "docs",
    "documentation",
    "news",
    "latest",
    "analysis",
    "open",
    "source",
    "peer",
    "reviewed",
}

LOW_QUALITY_TERMS = {
    "高考",
    "志愿填报",
    "专业目录",
    "招生",
    "录取",
    "词典",
    "dictionary",
    "adjective",
    "noun",
    "quiz",
}

CJK_TERM_TRANSLATIONS = {
    "预测": ("predictive", "prediction"),
    "编码": ("coding", "encoding"),
    "预测编码": ("predictive", "coding", "predictive coding"),
    "皮层": ("cortical", "cortex"),
    "层级": ("hierarchy", "hierarchical"),
    "突触": ("synaptic", "synapse"),
    "可塑性": ("plasticity",),
    "学习": ("learning",),
    "神经": ("neural", "neuron"),
    "门控": ("gating", "gate"),
    "注意": ("attention",),
    "机制": ("mechanism",),
}


def parse_domain_list(value: str) -> set[str]:
    domains: set[str] = set()
    for item in re.split(r"[\s,;]+", str(value or "").strip()):
        cleaned = item.strip().lower()
        if not cleaned:
            continue
        cleaned = cleaned.removeprefix("http://").removeprefix("https://").split("/", 1)[0]
        if cleaned:
            domains.add(cleaned)
    return domains


def domain_allowed(url: str, *, allowed_domains: str = "", blocked_domains: str = "") -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    if not host:
        return False
    blocked = parse_domain_list(blocked_domains)
    if any(host == domain or host.endswith("." + domain) for domain in blocked):
        return False
    allowed = parse_domain_list(allowed_domains)
    if allowed and not any(host == domain or host.endswith("." + domain) for domain in allowed):
        return False
    return True


def query_terms(query: str) -> set[str]:
    text = str(query or "")
    lowered = text.lower()
    terms = {
        token
        for token in re.findall(r"[a-z][a-z0-9_-]{3,}", lowered)
        if token not in GENERIC_SEARCH_TERMS
    }
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    for size in (2, 3, 4):
        for index in range(0, max(0, len(cjk_chars) - size + 1)):
            terms.add("".join(cjk_chars[index : index + size]))
    for cjk_term, translations in CJK_TERM_TRANSLATIONS.items():
        if cjk_term in text:
            terms.update(translations)
    return {term for term in terms if len(term.strip()) >= 2}


def evaluate_search_result(query: str, result: dict[str, str]) -> dict[str, object]:
    terms = query_terms(query)
    haystack = " ".join(
        str(result.get(key) or "")
        for key in ("title", "snippet", "summary", "url", "source", "published")
    ).lower()
    blocking_terms = sorted(term for term in LOW_QUALITY_TERMS if term.lower() in haystack)
    matched_terms = sorted(term for term in terms if term.lower() in haystack)
    required_matches = 1 if len(terms) <= 1 else 2
    accepted = bool(terms) and len(matched_terms) >= required_matches and not blocking_terms
    reasons: list[str] = []
    if not terms:
        reasons.append("query_has_no_quality_terms")
    if len(matched_terms) < required_matches:
        reasons.append("insufficient_query_overlap")
    if blocking_terms:
        reasons.append("low_quality_context_terms")
    return {
        "accepted": accepted,
        "matchedTerms": matched_terms[:12],
        "blockingTerms": blocking_terms[:12],
        "requiredMatchCount": required_matches,
        "queryTermCount": len(terms),
        "reasons": reasons,
    }


def filter_search_results(
    query: str,
    results: list[dict[str, str]],
    *,
    max_results: int,
    allowed_domains: str = "",
    blocked_domains: str = "",
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for result in results:
        if not domain_allowed(str(result.get("url") or ""), allowed_domains=allowed_domains, blocked_domains=blocked_domains):
            rejected.append({**result, "qualityGate": {"accepted": False, "reasons": ["domain_rejected"]}})
            continue
        gate = evaluate_search_result(query, result)
        next_result = {**result, "qualityGate": gate}
        if gate["accepted"]:
            accepted.append(next_result)
        else:
            rejected.append(next_result)
        if len(accepted) >= max_results:
            break
    return accepted, rejected
