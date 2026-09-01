"""Evidence-request circuit: duplicate detection, query rewrite, gap marker.

Claim scope: pure decision kernel plus the small persistence wrappers for the
per-team source-collection search-circuit ledger.  This module owns:

1. ``canonical_goal_key`` / ``normalized_goal`` — canonical identity of one
   evidence request (normalized keyword set + sourceTypes + evidenceLevels).
2. ``decide_circuit_action`` — compare an incoming goal against prior attempts
   of the same team/question and return ``execute_original``,
   ``reuse_in_flight``, ``execute_rewrite`` or ``mark_unavailable``.
3. ``build_rewrite_variants`` — deterministic query rewrites (keyword
   synonym/hypernym expansion, provider priority rotation, evidence-level
   relaxation).  No LLM on this path; rules only.
4. ``build_evidence_gap_marker`` — the structured ``evidence_gap_unavailable``
   marker recorded when the rewrite space is exhausted.

Determinism and fail-open are hard requirements: every IO wrapper swallows
storage errors so the collection flow degrades to the exact legacy behavior
(brand-new requests never see any difference).

The retrieval-layer marker recorded here is the contract for the (future,
out-of-scope) review-side consumer: read
``load_evidence_gap_marker(team_id, run_id)`` / the facade response field
``evidenceGap`` for the full shape.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from typing import Any

CIRCUIT_SCHEMA_VERSION = 1

CIRCUIT_MARKER_KIND = "evidence_gap_unavailable"

CIRCUIT_STORE_DIRNAME = "source_collection_search_circuit"
CIRCUIT_STORE_FILENAME = "index.json"

# Default rewrite budget N: after N rewrite attempts that still added zero new
# relevant records, the goal is marked ``evidence_gap_unavailable``.
DEFAULT_MAX_REWRITE_ATTEMPTS = 3

MAX_STORED_ENTRIES = 240
MAX_STORED_MARKERS = 40

_STRATEGY_KEYWORD_EXPANSION = "keyword_synonym_expansion"
_STRATEGY_PROVIDER_ROTATION = "provider_priority_rotation"
_STRATEGY_EVIDENCE_RELAXATION = "evidence_level_relaxation"

_EVIDENCE_RELAX_EXTRA_LEVELS = ("secondary", "preprint")

# Deterministic bilingual synonym/hypernym table used by the keyword-expansion
# rewrite strategy.  Keys are matched case-insensitively as substrings of the
# keyword (CJK keywords match via contained terms, English keywords via
# contained phrases).  Values are expansion terms appended to the goal's
# keyword set.  Keep entries conservative: only terms that stay inside the
# same research concept (synonym or hypernym), never unrelated broad topics.
_DEFAULT_KEYWORD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "预测编码": ("predictive coding",),
    "预测": ("prediction",),
    "编码": ("encoding",),
    "皮层": ("cortex",),
    "层级": ("hierarchical",),
    "突触": ("synapse",),
    "可塑性": ("plasticity",),
    "学习": ("learning",),
    "神经": ("neural",),
    "门控": ("gating",),
    "注意": ("attention",),
    "机制": ("mechanism",),
    "幻觉": ("hallucination",),
    "大语言模型": ("large language model", "llm"),
    "predictive coding": ("predictive processing",),
    "free energy": ("free-energy principle",),
    "federated learning": ("distributed learning",),
    "large language model": ("llm",),
    "llm": ("large language model",),
    "reinforcement learning": ("reward learning",),
    "graph neural network": ("message passing network",),
    "active inference": ("free energy principle",),
    "self-supervised": ("self-supervision",),
    "recommendation": ("recommender",),
    "anomaly detection": ("out-of-distribution detection",),
    "continual learning": ("lifelong learning",),
    "hallucination": ("factuality",),
}


def _collapse(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _norm_list(values: Any, *, lower: bool = True) -> list[str]:
    items: set[str] = set()
    if not isinstance(values, (list, tuple, set)):
        values = []
    for value in values:
        text = _collapse(value)
        if not text:
            continue
        items.add(text.lower() if lower else text)
    return sorted(items)


def normalized_goal(search_envelope: dict[str, Any] | None) -> dict[str, list[str]]:
    """Canonical projection of one evidence request goal.

    Keywords are lowercased, whitespace-collapsed, deduplicated and sorted, so
    ordering/casing differences never split one identical request into two
    identities.  sourceTypes/evidenceLevels are lowercased sorted sets.  All
    other envelope fields (timeRange, domains, ...) deliberately do not
    participate: the executed provider queries derive from keywords, and the
    circuit's job is to catch *the same retrieval goal being re-run*.
    """
    envelope = search_envelope if isinstance(search_envelope, dict) else {}
    return {
        "keywords": _norm_list(envelope.get("keywords")),
        "sourceTypes": _norm_list(envelope.get("sourceTypes")),
        "evidenceLevels": _norm_list(envelope.get("evidenceLevels")),
    }


def canonical_goal_key(search_envelope: dict[str, Any] | None) -> str:
    """Stable sha256 identity of one evidence request goal."""
    canonical = json.dumps(
        normalized_goal(search_envelope),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def goal_scope_key(question: str = "", theme: str = "") -> str:
    """Ledger partition key: one question (fallback theme, fallback team)."""
    text = _collapse(question).lower()
    if text:
        return f"question:{text[:160]}"
    text = _collapse(theme).lower()
    if text:
        return f"theme:{text[:160]}"
    return "team"


def _merge_synonym_table(extra: dict[str, tuple[str, ...]] | None) -> dict[str, tuple[str, ...]]:
    table = dict(_DEFAULT_KEYWORD_SYNONYMS)
    for key, values in (extra or {}).items():
        normalized = _collapse(key).lower()
        expansions = tuple(_collapse(value) for value in (values or ()) if _collapse(value))
        if normalized and expansions:
            table[normalized] = expansions
    return table


def expand_keywords(keywords: list[str], synonym_table: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    """Deterministic synonym/hypernym expansion of a normalized keyword set.

    Returns a new sorted deduplicated list; identical to the input when no
    table entry matches (callers then skip the expansion variant).  ASCII
    terms match on word boundaries so short tokens like ``llm`` never match
    inside unrelated longer words; CJK terms match by containment.
    """
    table = synonym_table if synonym_table is not None else _DEFAULT_KEYWORD_SYNONYMS
    base = _norm_list(keywords)
    expanded = set(base)
    for keyword in base:
        for term, expansions in table.items():
            if term.isascii():
                if not re.search(rf"\b{re.escape(term)}\b", keyword):
                    continue
            elif term not in keyword:
                continue
            expanded.update(_norm_list(expansions))
    return sorted(expanded)[:40]


def rewrite_query_seeds(
    keywords: list[str],
    *,
    synonym_table: dict[str, tuple[str, ...]] | None = None,
    extra_seeds: list[str] | None = None,
) -> list[str]:
    """Explicit query seeds for a rewrite run.

    Legacy collection runs seed their search plan from the first keyword
    only (``topic``).  Rewrite runs receive an explicit seed list so the
    executed queries really differ: expanded keywords, never-queried
    non-first keywords, and any strategy-specific extras, capped at the
    plan builder's 12-seed limit.
    """
    seeds = _norm_list([*expand_keywords(keywords, synonym_table), *(extra_seeds or [])], lower=False)
    seen: set[str] = set()
    unique: list[str] = []
    for seed in seeds:
        key = seed.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(seed)
        if len(unique) >= 12:
            break
    return unique


def _rotate(providers: list[str], offset: int) -> list[str]:
    if len(providers) < 2:
        return []
    offset = offset % len(providers)
    return list(providers[offset:] + providers[:offset])


def _relax_evidence_levels(levels: list[str], extra: tuple[str, ...] = _EVIDENCE_RELAX_EXTRA_LEVELS) -> list[str]:
    current = _norm_list(levels)
    relaxed = sorted(set(current) | set(extra))
    return relaxed if relaxed != current else []


def build_rewrite_variants(
    search_envelope: dict[str, Any] | None,
    *,
    providers: list[str],
    max_variants: int = DEFAULT_MAX_REWRITE_ATTEMPTS,
    synonym_table: dict[str, tuple[str, ...]] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic rewrite variants for one evidence request goal.

    Each variant is a full replacement search envelope plus an explicit
    query-seed list and an optional provider priority order, materially
    changing at least one of: the executed query text, the provider corpus
    order, or the accepted evidence levels.  Strategy menu per contract:
    keyword synonym/hypernym expansion, provider priority rotation,
    evidence-level relaxation.  No LLM anywhere on this path.
    """
    envelope = search_envelope if isinstance(search_envelope, dict) else {}
    base_keywords = _norm_list(envelope.get("keywords"))
    base_levels = _norm_list(envelope.get("evidenceLevels"))
    provider_list = [item for item in (providers or []) if _collapse(item)]
    variants: list[dict[str, Any]] = []

    expanded = expand_keywords(base_keywords, synonym_table)
    if expanded and expanded != base_keywords:
        variants.append(
            {
                "strategy": _STRATEGY_KEYWORD_EXPANSION,
                "searchEnvelope": {**envelope, "keywords": expanded},
                "providerOrder": [],
                "querySeeds": rewrite_query_seeds(base_keywords, synonym_table=synonym_table),
            }
        )

    rotated = _rotate(provider_list, 1)
    secondary_levels = _relax_evidence_levels(base_levels, ("secondary",))
    if rotated:
        review_seeds = [f"{keyword} review" for keyword in base_keywords[:3]]
        variants.append(
            {
                "strategy": _STRATEGY_PROVIDER_ROTATION,
                "searchEnvelope": {
                    **envelope,
                    "keywords": expanded or base_keywords,
                    **({"evidenceLevels": secondary_levels} if secondary_levels else {}),
                },
                "providerOrder": rotated,
                "querySeeds": rewrite_query_seeds(
                    base_keywords,
                    synonym_table=synonym_table,
                    extra_seeds=review_seeds,
                ),
            }
        )

    relaxed = _relax_evidence_levels(base_levels)
    second_rotation = _rotate(provider_list, 2)
    if relaxed:
        variants.append(
            {
                "strategy": _STRATEGY_EVIDENCE_RELAXATION,
                "searchEnvelope": {
                    **envelope,
                    "keywords": base_keywords,
                    "evidenceLevels": relaxed,
                },
                # The relaxation also rotates providers and decomposes the
                # keyword set into individual seeds, so the executed queries
                # differ from both the original run and the earlier variants.
                "providerOrder": second_rotation,
                "querySeeds": rewrite_query_seeds(
                    base_keywords,
                    synonym_table=synonym_table,
                    extra_seeds=[f"{keyword} survey" for keyword in base_keywords[:2]],
                ),
            }
        )

    return variants[: max(0, int(max_variants))]


def _entry_outcome_zero_new(entry: dict[str, Any]) -> bool:
    outcome = entry.get("outcome") if isinstance(entry.get("outcome"), dict) else {}
    if str(entry.get("status") or "") != "executed":
        return False
    try:
        return int(outcome.get("newRecordCount") or 0) <= 0
    except (TypeError, ValueError):
        return True


def decide_circuit_action(
    entries: list[dict[str, Any]],
    search_envelope: dict[str, Any] | None,
    *,
    providers: list[str],
    goal_key: str = "",
    max_rewrite_attempts: int = DEFAULT_MAX_REWRITE_ATTEMPTS,
    synonym_table: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """Decide how the retrieval layer must treat an incoming evidence request.

    ``entries`` are the prior attempt ledger entries for the same
    team/question goal scope.  Pure function; no IO, no service imports.
    """
    envelope = search_envelope if isinstance(search_envelope, dict) else {}
    key = goal_key or canonical_goal_key(envelope)
    max_rewrites = max(1, int(max_rewrite_attempts))
    goal_entries = [
        dict(item)
        for item in (entries or [])
        if isinstance(item, dict) and str(item.get("goalKey") or "") == key
    ]
    if not goal_entries:
        return {"action": "execute_original", "goalKey": key, "priorAttemptCount": 0}

    # An attempt whose execution has not produced an outcome yet is reused
    # as-is (the background worker is still draining it).
    in_flight = [
        item
        for item in goal_entries
        if str(item.get("status") or "") in {"starting", "executing"}
    ]
    if in_flight:
        latest = in_flight[-1]
        return {
            "action": "reuse_in_flight",
            "goalKey": key,
            "runId": str(latest.get("runId") or ""),
            "priorAttemptCount": len(goal_entries),
        }

    used_variant_indexes = sorted(
        {
            int(item.get("variantIndex") or 0)
            for item in goal_entries
            if str(item.get("attemptKind") or "") == "rewrite"
            and int(item.get("variantIndex") or 0) > 0
        }
    )
    variants = build_rewrite_variants(
        envelope,
        providers=providers,
        max_variants=max_rewrites,
        synonym_table=synonym_table,
    )
    remaining = [
        (index, item)
        for index, item in enumerate(variants, start=1)
        if index not in used_variant_indexes
    ]
    zero_new_rewrites = sum(
        1
        for item in goal_entries
        if str(item.get("attemptKind") or "") == "rewrite" and _entry_outcome_zero_new(item)
    )
    exhausted = (
        zero_new_rewrites >= max_rewrites
        or not remaining
    )
    if exhausted:
        latest = goal_entries[-1]
        return {
            "action": "mark_unavailable",
            "goalKey": key,
            "latestAttemptRunId": str(latest.get("runId") or ""),
            "priorAttemptCount": len(goal_entries),
            "attempts": goal_entries,
        }

    variant_index, variant = remaining[0]
    return {
        "action": "execute_rewrite",
        "goalKey": key,
        "variant": variant,
        "variantIndex": variant_index,
        "priorAttemptCount": len(goal_entries),
        "zeroNewRewriteCount": zero_new_rewrites,
    }


def new_attempt_entry(
    *,
    goal_key: str,
    goal_scope: str,
    question: str,
    run_id: str,
    search_envelope: dict[str, Any] | None,
    fingerprint: str,
    attempt_kind: str,
    variant_index: int = 0,
    strategy: str = "",
    provider_order: list[str] | None = None,
    query_seeds: list[str] | None = None,
    original_search_envelope: dict[str, Any] | None = None,
    now_iso: str = "",
    entry_id: str = "",
) -> dict[str, Any]:
    """Build one ledger entry for a started attempt (original or rewrite)."""
    return {
        "entryId": entry_id or f"scrc-{uuid.uuid4().hex[:20]}",
        "goalKey": goal_key,
        "goalScopeKey": goal_scope,
        "question": _collapse(question)[:200],
        "attemptKind": attempt_kind,
        "variantIndex": int(variant_index),
        "strategy": str(strategy or ""),
        "runId": _collapse(run_id)[:160],
        "searchEnvelope": normalized_goal(search_envelope),
        "originalSearchEnvelope": normalized_goal(original_search_envelope or search_envelope),
        "providerOrder": [str(item) for item in (provider_order or [])][:8],
        "querySeeds": [_collapse(item)[:220] for item in (query_seeds or []) if _collapse(item)][:12],
        "fingerprint": _collapse(fingerprint)[:128],
        "status": "starting",
        "outcome": {},
        "createdAt": now_iso,
        "updatedAt": now_iso,
    }


def apply_attempt_outcome(
    entries: list[dict[str, Any]],
    run_id: str,
    result: dict[str, Any],
    *,
    now_iso: str = "",
) -> list[dict[str, Any]]:
    """Merge one finished search execution back into the ledger (pure).

    ``result`` is the ``execute_source_collection_search`` response; the new
    relevant-record count is ``recordCount`` (quality-gate-passed, duplicate-
    skipped records created by this execution).
    """
    payload = result if isinstance(result, dict) else {}
    normalized_run_id = _collapse(run_id)[:160]
    if not normalized_run_id:
        return list(entries or [])
    changed = False
    updated: list[dict[str, Any]] = []
    for entry in list(entries or []):
        item = dict(entry) if isinstance(entry, dict) else {}
        if str(item.get("runId") or "") == normalized_run_id and str(item.get("status") or "") != "executed":
            try:
                new_records = int(payload.get("recordCount") or 0)
            except (TypeError, ValueError):
                new_records = 0
            item["outcome"] = {
                "terminalStatus": _collapse(payload.get("status"))[:80],
                "executedQueryCount": _int_or_zero(payload.get("executedQueryCount")),
                "attemptedQueryCount": _int_or_zero(payload.get("attemptedQueryCount")),
                "resultCount": _int_or_zero(payload.get("resultCount")),
                "newRecordCount": new_records,
                "importedCount": _int_or_zero(payload.get("importedCount")),
                "rejectedResultCount": _int_or_zero(payload.get("rejectedResultCount")),
                "skippedDuplicateCount": _int_or_zero(payload.get("skippedDuplicateCount")),
                "filteredExcludedCount": _int_or_zero(payload.get("filteredExcludedCount")),
                "recordedAt": now_iso,
            }
            item["status"] = "executed"
            item["updatedAt"] = now_iso
            changed = True
        updated.append(item)
    return updated if changed else list(entries or [])


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build_evidence_gap_marker(
    *,
    goal_key: str,
    goal_scope: str,
    question: str,
    original_search_envelope: dict[str, Any] | None,
    attempts: list[dict[str, Any]],
    latest_attempt_run_id: str,
    max_rewrite_attempts: int = DEFAULT_MAX_REWRITE_ATTEMPTS,
    now_iso: str = "",
    marker_id: str = "",
) -> dict[str, Any]:
    """Build the structured ``evidence_gap_unavailable`` marker.

    This marker is the retrieval-layer contract for the future review-side
    consumer: it carries the original request goal, every attempted rewrite,
    and a summary of why retrieved material did not add relevant records.
    """
    attempt_payloads: list[dict[str, Any]] = []
    totals = {
        "resultCount": 0,
        "newRecordCount": 0,
        "importedCount": 0,
        "rejectedResultCount": 0,
        "skippedDuplicateCount": 0,
        "filteredExcludedCount": 0,
    }
    for entry in attempts or []:
        if not isinstance(entry, dict):
            continue
        outcome = entry.get("outcome") if isinstance(entry.get("outcome"), dict) else {}
        attempt_payloads.append(
            {
                "runId": str(entry.get("runId") or ""),
                "attemptKind": str(entry.get("attemptKind") or ""),
                "variantIndex": _int_or_zero(entry.get("variantIndex")),
                "strategy": str(entry.get("strategy") or ""),
                "searchEnvelope": entry.get("searchEnvelope") if isinstance(entry.get("searchEnvelope"), dict) else {},
                "querySeeds": [str(item) for item in list(entry.get("querySeeds") or [])][:12],
                "status": str(entry.get("status") or ""),
                "outcome": dict(outcome),
            }
        )
        for key in totals:
            totals[key] += _int_or_zero(outcome.get(key))
    summary = (
        f"{totals['resultCount']} 条原始检索结果中，"
        f"{totals['rejectedResultCount']} 条未通过质量相关性门、"
        f"{totals['skippedDuplicateCount']} 条为已存重复、"
        f"{totals['filteredExcludedCount']} 条命中排除清单，"
        f"最终仅新增 {totals['newRecordCount']} 条相关记录；"
        f"{max(0, int(max_rewrite_attempts))} 次改写后仍无新增，判定该证据请求当前不可得。"
    )
    return {
        "marker": CIRCUIT_MARKER_KIND,
        "schemaVersion": CIRCUIT_SCHEMA_VERSION,
        "markerId": marker_id or f"scrgap-{uuid.uuid4().hex[:20]}",
        "goalKey": goal_key,
        "goalScopeKey": goal_scope,
        "question": _collapse(question)[:200],
        "originalSearchEnvelope": normalized_goal(original_search_envelope),
        "attempts": attempt_payloads,
        "rewriteAttemptCount": sum(1 for item in attempt_payloads if item.get("attemptKind") == "rewrite"),
        "maxRewriteAttempts": max(0, int(max_rewrite_attempts)),
        "latestAttemptRunId": _collapse(latest_attempt_run_id)[:160],
        "unavailableReasonsSummary": {**totals, "summary": summary},
        "policyVersion": str(CIRCUIT_SCHEMA_VERSION),
        "markedAt": now_iso,
    }


# ---------------------------------------------------------------------------
# Persistence wrappers (late-bound service; fail-open everywhere).
# ---------------------------------------------------------------------------

# Serializes every read-modify-write cycle on the per-team circuit ledger.
# Each individual store write is already atomic (temp + fsync + os.replace),
# but without this lock two concurrent RMW cycles lose updates (last writer
# overwrites the other's appended entry / recorded outcome).  Read-only
# helpers stay lock-free: they observe either the old or the new complete
# file, which is safe under the atomic replace.
_LEDGER_LOCK = threading.RLock()


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def circuit_store_path(team_id: str):
    s = _service()
    return s._team_workflow_root(team_id) / CIRCUIT_STORE_DIRNAME / CIRCUIT_STORE_FILENAME


def load_circuit_store(team_id: str) -> dict[str, Any]:
    s = _service()
    default = {
        "schemaVersion": CIRCUIT_SCHEMA_VERSION,
        "storeKind": "source_collection_search_circuit_store",
        "teamId": team_id,
        "entries": [],
        "markers": [],
        "createdAt": "",
        "updatedAt": "",
    }
    try:
        payload = s._read_json(circuit_store_path(team_id))
    except Exception:  # noqa: BLE001 - unreadable ledger degrades to legacy path
        return default
    if not isinstance(payload, dict):
        return default
    default["entries"] = [item for item in list(payload.get("entries") or []) if isinstance(item, dict)]
    default["markers"] = [item for item in list(payload.get("markers") or []) if isinstance(item, dict)]
    default["createdAt"] = str(payload.get("createdAt") or "")
    return default


def save_circuit_store(team_id: str, store: dict[str, Any]) -> None:
    s = _service()
    payload = dict(store)
    payload["schemaVersion"] = CIRCUIT_SCHEMA_VERSION
    payload["storeKind"] = "source_collection_search_circuit_store"
    payload["teamId"] = team_id
    payload["entries"] = list(payload.get("entries") or [])[-MAX_STORED_ENTRIES:]
    payload["markers"] = list(payload.get("markers") or [])[-MAX_STORED_MARKERS:]
    payload["updatedAt"] = s.utc_now_iso()
    if not payload.get("createdAt"):
        payload["createdAt"] = payload["updatedAt"]
    s._write_json(circuit_store_path(team_id), payload)


def load_goal_entries(team_id: str, goal_scope: str) -> list[dict[str, Any]]:
    """All ledger entries for one goal scope (question/theme partition)."""
    store = load_circuit_store(team_id)
    return [
        item
        for item in store.get("entries")
        if str(item.get("goalScopeKey") or "") == goal_scope
    ]


def append_attempt_entry(team_id: str, entry: dict[str, Any]) -> None:
    """Record a started attempt; swallow failures (circuit must fail open)."""
    try:
        with _LEDGER_LOCK:
            store = load_circuit_store(team_id)
            entries = list(store.get("entries") or [])
            entries.append(entry)
            store["entries"] = entries
            save_circuit_store(team_id, store)
    except Exception:  # noqa: BLE001
        return


def record_attempt_outcome(team_id: str, run_id: str, result: dict[str, Any]) -> None:
    """Merge one finished execution into the ledger; fail-open."""
    try:
        with _LEDGER_LOCK:
            store = load_circuit_store(team_id)
            entries = apply_attempt_outcome(
                store.get("entries"),
                run_id,
                result,
                now_iso=_service().utc_now_iso(),
            )
            if entries == store.get("entries"):
                return
            store["entries"] = entries
            save_circuit_store(team_id, store)
    except Exception:  # noqa: BLE001
        return


def record_evidence_gap_marker(
    team_id: str,
    marker: dict[str, Any],
    *,
    latest_attempt_run_id: str = "",
) -> None:
    """Persist the ``evidence_gap_unavailable`` marker; fail-open."""
    try:
        with _LEDGER_LOCK:
            store = load_circuit_store(team_id)
            markers = [item for item in list(store.get("markers") or []) if isinstance(item, dict)]
            goal_key = str(marker.get("goalKey") or "")
            markers = [item for item in markers if str(item.get("goalKey") or "") != goal_key]
            stored = dict(marker)
            if latest_attempt_run_id:
                stored["latestAttemptRunId"] = str(latest_attempt_run_id)[:160]
            markers.append(stored)
            store["markers"] = markers
            save_circuit_store(team_id, store)
    except Exception:  # noqa: BLE001
        return


def exhausted_duplicate_marker_for_run(team_id: str, run_id: str) -> dict[str, Any]:
    """Return the gap marker when re-executing a run would repeat a dead goal.

    Matches only when ``run_id`` is the marker's latest attempt run, i.e. a
    duplicate request was routed back to the last attempt's run after the
    rewrite space was exhausted.  Fail-open: unreadable ledger returns {}.
    """
    try:
        normalized = _collapse(run_id)[:160]
        if not normalized:
            return {}
        store = load_circuit_store(team_id)
        for marker in reversed(list(store.get("markers") or [])):
            if not isinstance(marker, dict):
                continue
            if str(marker.get("marker") or "") != CIRCUIT_MARKER_KIND:
                continue
            if str(marker.get("latestAttemptRunId") or "") == normalized:
                return dict(marker)
        return {}
    except Exception:  # noqa: BLE001
        return {}


def build_exhausted_duplicate_result(
    marker: dict[str, Any],
    *,
    run: dict[str, Any] | None,
    run_status: dict[str, Any] | None,
    assignments: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Terminal search result for an exhausted-duplicate replay.

    Zero provider calls, zero queries; ``status`` deliberately is
    ``evidence_gap_unavailable`` while every count stays at zero so the shared
    terminal mapping in ``runs.execute_source_collection_search`` resolves to
    ``completed`` (the chain bridge only handoffs on ``completed``).
    """
    return {
        "status": CIRCUIT_MARKER_KIND,
        "attemptedQueryCount": 0,
        "executedQueryCount": 0,
        "skippedQueryCount": 0,
        "failedQueryCount": 0,
        "resultCount": 0,
        "recordCount": 0,
        "createdUniqueRecordCount": 0,
        "outputCount": 0,
        "importedCount": 0,
        "remainingQueryCount": 0,
        "hasMore": False,
        "run": dict(run or {}),
        "runStatus": dict(run_status or {}),
        "sourceCollectionSummary": {},
        "assignments": [item for item in list(assignments or []) if isinstance(item, dict)],
        "evidenceGap": dict(marker),
        "nextActions": [
            "This evidence request already exhausted its rewrite budget; no provider search was repeated.",
            "Consume the structured evidenceGap marker when planning the next review round.",
        ],
    }


# ---------------------------------------------------------------------------
# Review-side consumer API (read / clear).  Pure additions on top of the
# retrieval kernel: no circuit decision path imports or changes below.


def live_evidence_gap_marker_for_goal(
    team_id: str,
    search_envelope: dict[str, Any] | None,
    *,
    goal_key: str = "",
) -> dict[str, Any]:
    """Return the live ``evidence_gap_unavailable`` marker for one goal, else {}.

    Read-only consumer API for the hypothesis-first chain: checked before an
    evidence request reaches the collection facade so an already-exhausted
    goal never triggers a new retrieval attempt.  Fail-open: an unreadable
    ledger behaves exactly like "no marker" (legacy path).
    """
    try:
        key = goal_key or canonical_goal_key(search_envelope)
        if not key:
            return {}
        store = load_circuit_store(team_id)
        for marker in reversed(list(store.get("markers") or [])):
            if not isinstance(marker, dict):
                continue
            if str(marker.get("marker") or "") != CIRCUIT_MARKER_KIND:
                continue
            if str(marker.get("goalKey") or "") == key:
                return dict(marker)
        return {}
    except Exception:  # noqa: BLE001 - a missing marker must never block collection
        return {}


def marker_retry_hint(marker: dict[str, Any]) -> str:
    """Operator-facing hint returned when clearing one marker (pure).

    The quote-anchor remediation (verbatim quote-anchor blocks plus
    abstract-only degradation) makes sources that previously failed full-text
    fetch (auth wall / fetch failures) usable as abstract-level evidence.  A
    marker whose attempts did retrieve results that never converted into new
    relevant records is exactly that failure class, so a retry may now
    succeed.  Attempts that retrieved nothing at all stay unpromising.
    """
    attempts = [item for item in list((marker or {}).get("attempts") or []) if isinstance(item, dict)]
    saw_results = any(
        _int_or_zero((item.get("outcome") if isinstance(item.get("outcome"), dict) else {}).get("resultCount")) > 0
        for item in attempts
    )
    if saw_results:
        return (
            "该判定期间检索曾命中结果但未能形成新增相关记录；quote 锚摘要降级已上线，"
            "原 auth wall/fetch 失败的源现可以摘要级证据参与，重试可能可得。"
        )
    return "清除后该证据请求将重新走检索熔断判定（重新检索/重判）。"


def clear_evidence_gap_marker(team_id: str, marker_id: str) -> dict[str, Any]:
    """Remove one ``evidence_gap_unavailable`` marker by id (operator action).

    No TTL/auto-expiry by design: reopening a dead retrieval goal is an
    explicit operator decision, never a silent background restart.  After a
    successful clear the same goal re-enters the circuit as a brand-new
    request.  Returns ``{"cleared": bool, "marker": dict, "retryHint": str}``
    plus ``"error"`` only when persistence failed (the operator retry is
    safe; an unknown id simply reports ``cleared: False``).
    """
    normalized = _collapse(marker_id)[:80]
    if not normalized:
        return {"cleared": False, "marker": {}, "retryHint": "", "error": "marker_id is required"}
    try:
        store = load_circuit_store(team_id)
        markers = [item for item in list(store.get("markers") or []) if isinstance(item, dict)]
        found: dict[str, Any] | None = None
        kept: list[dict[str, Any]] = []
        for marker in markers:
            if found is None and str(marker.get("markerId") or "") == normalized:
                found = marker
                continue
            kept.append(marker)
        if found is None:
            return {"cleared": False, "marker": {}, "retryHint": ""}
        store["markers"] = kept
        save_circuit_store(team_id, store)
        return {
            "cleared": True,
            "marker": dict(found),
            "retryHint": marker_retry_hint(found),
        }
    except Exception as exc:  # noqa: BLE001 - surface failure, never corrupt the ledger
        return {"cleared": False, "marker": {}, "retryHint": "", "error": str(exc) or type(exc).__name__}
