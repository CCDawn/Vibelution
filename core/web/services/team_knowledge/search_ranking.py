"""Pure team-knowledge search ranking helpers.

Claim scope: payload text extraction, tokenization, BM25 ranking,
semantic token overlap, match reason, and metadata filters.
Late-binds constants via module-level imports from constants.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from .constants import BM25_B, BM25_K1, _SEARCH_TOKEN_PATTERN

def _search_text_for_payload(payload: Any) -> str:
    values: list[str] = []

    def collect(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                values.append(text)
            return
        if isinstance(value, (int, float)):
            values.append(str(value))
            return
        if isinstance(value, dict):
            for nested in value.values():
                collect(nested)
            return
        if isinstance(value, (list, tuple, set)):
            for nested in value:
                collect(nested)

    collect(payload)
    return " ".join(values).lower()


def _tokenize_search_text(text: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in _SEARCH_TOKEN_PATTERN.finditer(str(text or "").lower())
        if match.group(0).strip()
    }


def _tokenize_bm25_text(text: str) -> list[str]:
    return [
        match.group(0).lower()
        for match in _SEARCH_TOKEN_PATTERN.finditer(str(text or "").lower())
        if match.group(0).strip()
    ]


def _rank_bm25_search_results(results: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    normalized_query = str(query or "").strip().lower()
    if not results:
        return []
    if not normalized_query:
        ranked = []
        for result in results:
            item = dict(result)
            item["semanticScore"] = 1.0
            item["bm25Score"] = 1.0
            item["matchReason"] = "no_query"
            ranked.append(item)
        ranked.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
        return ranked

    query_terms = list(dict.fromkeys(_tokenize_bm25_text(normalized_query)))
    if not query_terms:
        return []
    document_terms = [_tokenize_bm25_text(_bm25_text_for_result(item)) for item in results]
    document_term_sets = [set(terms) for terms in document_terms]
    document_lengths = [len(terms) for terms in document_terms]
    document_count = len(document_terms)
    average_document_length = max(1.0, sum(document_lengths) / max(document_count, 1))
    document_frequencies = {
        term: sum(1 for terms in document_term_sets if term in terms)
        for term in query_terms
    }
    ranked: list[dict[str, Any]] = []
    for result, terms, document_length in zip(results, document_terms, document_lengths):
        counts = Counter(terms)
        score = 0.0
        for term in query_terms:
            term_frequency = counts.get(term, 0)
            if term_frequency <= 0:
                continue
            document_frequency = document_frequencies.get(term, 0)
            if document_frequency <= 0:
                continue
            idf = math.log(1.0 + ((document_count - document_frequency + 0.5) / (document_frequency + 0.5)))
            denominator = term_frequency + BM25_K1 * (
                1.0 - BM25_B + BM25_B * (document_length / average_document_length)
            )
            if denominator <= 0:
                continue
            score += idf * ((term_frequency * (BM25_K1 + 1.0)) / denominator)
        item = dict(result)
        rounded_score = round(score, 6)
        item["semanticScore"] = rounded_score
        item["bm25Score"] = rounded_score
        item["searchMode"] = "bm25"
        item["matchReason"] = "bm25" if rounded_score > 0 else "metadata_filter"
        ranked.append(item)
    ranked.sort(
        key=lambda item: (
            float(item.get("semanticScore") or 0.0),
            str(item.get("updatedAt") or item.get("createdAt") or ""),
        ),
        reverse=True,
    )
    return ranked


def _bm25_text_for_result(result: dict[str, Any]) -> str:
    tags = " ".join(str(tag or "").strip() for tag in list(result.get("tags") or []) if str(tag or "").strip())
    source_parts: list[str] = []
    for source in list(result.get("sourceSummaries") or []):
        if not isinstance(source, dict):
            continue
        source_parts.extend(
            [
                str(source.get("title") or "").strip(),
                str(source.get("summary") or "").strip(),
            ]
        )
    parts = [
        " ".join([str(result.get("title") or "").strip()] * 3),
        " ".join([str(result.get("summary") or "").strip()] * 2),
        str(result.get("content") or "").strip(),
        tags,
        " ".join(part for part in source_parts if part),
    ]
    return " ".join(part for part in parts if part)


def _semantic_match_score(payload: Any, query: str) -> float:
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        return 1.0
    haystack = payload if isinstance(payload, str) else _search_text_for_payload(payload)
    if normalized_query in haystack:
        return 1.0
    query_tokens = _tokenize_search_text(normalized_query)
    if not query_tokens:
        return 0.0
    haystack_tokens = _tokenize_search_text(haystack)
    if not haystack_tokens:
        return 0.0
    return round(len(query_tokens.intersection(haystack_tokens)) / len(query_tokens), 4)


def _search_match_reason(view: dict[str, Any], query: str, score: float) -> str:
    if not str(query or "").strip():
        return "no_query"
    if str(query or "").strip().lower() in _search_text_for_payload(view):
        return "exact_phrase"
    if score > 0:
        return "token_overlap"
    return "metadata_filter"


def _item_matches_filters(
    item: dict[str, Any],
    *,
    query: str,
    tags: set[str],
    source_type: str,
    importance_level: str,
    confidence_min: float | None,
    stability: str,
    created_from: str,
    created_to: str,
    artifacts_by_id: dict[str, dict[str, Any]],
    search_mode: str = "exact",
) -> bool:
    if query:
        normalized_search_mode = str(search_mode or "exact").strip().lower()
        haystack = _search_text_for_payload([item, list(artifacts_by_id.values())])
        exact_match = query in haystack
        semantic_score = _semantic_match_score(haystack, query)
        if normalized_search_mode == "exact" and not exact_match:
            return False
        if normalized_search_mode == "semantic" and semantic_score <= 0:
            return False
        if normalized_search_mode == "hybrid" and not exact_match and semantic_score <= 0:
            return False
    if tags and not tags.issubset({str(tag or "").strip().lower() for tag in list(item.get("tags") or [])}):
        return False
    if source_type:
        source_ids = [str(value or "") for value in list(item.get("sourceArtifactIds") or [])]
        if not any(str((artifacts_by_id.get(source_id) or {}).get("sourceType") or "") == source_type for source_id in source_ids):
            return False
    if importance_level and str(item.get("importanceLevel") or "") != importance_level:
        return False
    if confidence_min is not None:
        try:
            if float(item.get("confidence") or 0.0) < float(confidence_min):
                return False
        except (TypeError, ValueError):
            return False
    if stability and str(item.get("stability") or "") != stability:
        return False
    created_at = str(item.get("createdAt") or item.get("appliedAt") or "")
    if created_from and created_at < str(created_from):
        return False
    if created_to and created_at > str(created_to):
        return False
    return True
