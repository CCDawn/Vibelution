"""Deterministic relation-endpoint registry and resolver (pure functions).

Claim scope: closed-set endpoint registries plus deterministic semantic
endpoint binding for relations-stage candidate-graph writebacks.

Two-part structural binding, adapted from established KG-construction
practice:

- Closed-set extraction (LlamaIndex ``SchemaLLMPathExtractor`` style):
  only registered endpoint ids may appear on edges; the writeback contract
  enumerates this batch's candidate ids up front.
- Post-hoc entity resolution (Neo4j graphrag Entity Resolution style):
  agents may also emit human-readable endpoints (candidate titles / theme
  labels); the server resolves them to registry ids deterministically.
  Endpoints that resolve nowhere stay dangling and keep the existing
  fail-closed semantics: the edge degrades into a missingLink and is
  counted by ``danglingEdgeCount``.

This module stays pure (no service state) so registries can be built from
merged graph nodes in one call and unit-tested without fixtures.
"""

from __future__ import annotations

import unicodedata
from typing import Any

_SOURCE_THEME_PREFIX = "source-theme:"
_THEME_NODE_CANDIDATE_TYPES = {"source_topic"}


def normalize_relation_endpoint_token(value: Any) -> str:
    """Normalize an endpoint token for deterministic matching.

    NFKC + casefold + whitespace collapse + surrounding punctuation strip.
    No fuzzy matching: equal normalized forms compare, everything else does
    not. Normalization must be injective enough that distinct candidates
    with identical titles collapse deterministically to the first entry.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = " ".join(text.split()).casefold()
    return text.strip(" \t\r\n-–—_·.,;:!?()[]{}<>\"'`~*|/")


def build_relation_endpoint_registry(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the closed-set endpoint registry from merged graph nodes.

    Accepts the full node view of a writeback merge: server-built candidate
    graph nodes plus agent-declared nodes (including ``themeNodes``
    materialized as ``source-theme:<themeId>``). Theme nodes register their
    label/title AND raw theme id as aliases; ordinary nodes register only
    their title. First registration wins so resolution is deterministic.
    """
    registry: dict[str, Any] = {
        "ids": set(),
        "titles": {},
        "themes": {},
    }
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("candidateId") or node.get("id") or "").strip()
        if not node_id:
            continue
        registry["ids"].add(node_id)
        is_theme_node = bool(
            node_id.startswith(_SOURCE_THEME_PREFIX)
            or str(node.get("candidateType") or node.get("type") or "")
            in _THEME_NODE_CANDIDATE_TYPES
        )
        labels = [
            node.get("title"),
            node.get("label"),
        ]
        if node_id.startswith(_SOURCE_THEME_PREFIX):
            labels.append(node_id.split(":", 1)[1])
        for label in labels:
            normalized = normalize_relation_endpoint_token(label)
            if not normalized:
                continue
            if is_theme_node:
                registry["themes"].setdefault(normalized, node_id)
            else:
                registry["titles"].setdefault(normalized, node_id)
    return registry


def resolve_relation_endpoint(token: str, registry: dict[str, Any]) -> str:
    """Resolve an endpoint token against the registry; "" when unresolvable.

    Resolution order (deterministic):

    1. exact registry id hit;
    2. normalized title match against ordinary nodes;
    3. normalized match against theme nodes (labels, raw theme ids);
    4. unresolved -> "" (caller keeps fail-closed dangling handling).
    """
    raw = str(token or "").strip()
    if not raw or not isinstance(registry, dict):
        return ""
    ids = registry.get("ids")
    if isinstance(ids, set) and raw in ids:
        return raw
    normalized = normalize_relation_endpoint_token(raw)
    if not normalized:
        return ""
    titles = registry.get("titles")
    if isinstance(titles, dict):
        resolved = titles.get(normalized)
        if resolved:
            return str(resolved)
    themes = registry.get("themes")
    if isinstance(themes, dict):
        resolved = themes.get(normalized)
        if resolved:
            return str(resolved)
    if raw.startswith(_SOURCE_THEME_PREFIX):
        prefixed_normalized = normalize_relation_endpoint_token(raw)
        resolved = themes.get(prefixed_normalized) if isinstance(themes, dict) else None
        if resolved:
            return str(resolved)
    return ""
