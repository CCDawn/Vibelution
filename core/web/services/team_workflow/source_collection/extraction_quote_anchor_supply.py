"""Verbatim quote-anchor supply chain for source-collection extraction.

Production blocker (run-882610596ddb): the extraction agent systematically
wrote ``quote=''`` and only record-anchor reference ids, so the hardened
writeback contract (verbatim-quote-anchored claims) rejected every completed
writeback, zero claims materialized, and the run blocked on
``required_artifact_missing: evidence_card_batch``.  Root cause: the stage
task context never contained copyable source text — compact candidate
summaries stop at a 24-char preview, so there was nothing verbatim to quote.

This module owns the supply side once, as importable pure functions, so the
context boundary and the writeback boundary enforce one rule set:

1. ``extraction_quotable_sources`` builds, per candidate/record, the quotable
   source blocks embedded into the stage task context.  Block priority
   follows evidence quality: fetched body text (linked data record
   ``content``) first, then the stored abstract (record ``summary``), then
   the candidate's own stored ``summary``.  Blocks are length-capped and the
   total char budget is bounded, so a large candidate page cannot explode the
   prompt.  Every source also carries a ``sourceAccess`` marker
   (``full_text`` / ``abstract_only`` / ``no_quotable_text``) so fetch
   failures (403/auth wall) degrade the source to abstract-level evidence
   instead of inviting fabricated full-text quotes.
2. ``audit_extraction_quote_anchors`` classifies each non-exclude extraction
   entry against the exact same block texts: ``has_anchor`` (verbatim quote
   found), ``mismatched_quote`` (quotes supplied but never verbatim),
   ``missing_quote`` (no quote at all — still a hard contract rejection) and
   ``empty_source`` (no quotable text stored; the entry must honestly declare
   ``evidenceStatus=missing_evidence_anchor``).
3. ``build_quote_anchor_remediation`` renders the structured one-shot
   remediation feedback (nearest matching snippet + similarity per failing
   source).  The writeback boundary parks the first mismatching completed
   writeback at ``needs_review`` with this payload; a second mismatch falls
   through to the existing hard rejection, so the loop is bounded.

Zero-diff contract: every quote that the pre-existing validator accepted
(verbatim substring of the stored candidate summary / record summary or
content) is still accepted — the audit only widens acceptance to the linked
record blocks it now supplies to the context, and only downgrades one
failure shape (first-time mismatched quote) from rejection to remediation.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable, Iterable, Mapping
from typing import Any

# Per-source quotable block cap (characters).  Large bodies/abstracts are
# truncated at this bound with an explicit ``truncated`` marker; the context
# instruction tells the agent to quote only inside the provided text.
QUOTE_BLOCK_MAX_CHARS = 2400

# Total characters of quotable block text embedded in one context response.
# Sources beyond the budget keep their metadata and ``quoteAvailable`` flag
# but omit block text (the agent pages via candidate_offset/record_offset).
QUOTE_SOURCES_TOTAL_CHAR_BUDGET = 24000

# Bounded diagnostics for remediation feedback snippets.
QUOTE_SNIPPET_MAX_CHARS = 240

# At most this many findings are rendered into one remediation payload.
_REMEDIATION_FINDING_LIMIT = 8

# Supplied quotes are excerpted at this length inside audit findings.
_SUPPLIED_QUOTE_EXCERPT_CHARS = 200

# Nested claim lists that may carry a verbatim ``quote`` (mirrors the
# claim materializer's materializable-claim lists).
_CLAIM_LIST_KEYS = ("claims", "keyFindings", "key_findings", "findings")

# Candidate metadata keys that link a candidate to its origin data record.
_LINKED_RECORD_KEYS = ("importedFromDataRecord", "sourceRecordRef")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clip_at_boundary(text: str, max_chars: int) -> tuple[str, bool]:
    """Clip ``text`` to ``max_chars``, preferring a whitespace boundary."""
    if len(text) <= max_chars:
        return text, False
    window = text[:max_chars]
    cut = window.rfind(" ")
    if cut < max_chars // 2:
        cut = max_chars - 1
    return window[: cut + 1].rstrip(), True


def _record_content(record: Mapping[str, Any]) -> str:
    return _clean(record.get("content"))


def source_quotable_blocks(
    source: Mapping[str, Any],
    record_by_id: Mapping[str, Mapping[str, Any]],
    *,
    block_max_chars: int = QUOTE_BLOCK_MAX_CHARS,
) -> list[dict[str, Any]]:
    """Return the ordered quotable blocks for one candidate/record.

    Priority: fetched body text (linked data record ``content``) → abstract
    (record ``summary``) → the source's own stored ``summary``.  Identical
    texts are deduped so an imported candidate does not repeat the abstract
    of its origin record twice.
    """
    candidates_for_blocks: list[tuple[str, str]] = []
    if source.get("candidateId"):
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        linked_record_id = _clean(metadata.get("sourceRecordId"))
        if not linked_record_id:
            for key in _LINKED_RECORD_KEYS:
                linked = metadata.get(key) if isinstance(metadata.get(key), dict) else {}
                linked_record_id = _clean(linked.get("recordId"))
                if linked_record_id:
                    break
        linked_record = record_by_id.get(linked_record_id) if linked_record_id else None
        if linked_record:
            candidates_for_blocks.append(("fetched_body", _record_content(linked_record)))
            candidates_for_blocks.append(("abstract", _clean(linked_record.get("summary"))))
        candidates_for_blocks.append(("stored_summary", _clean(source.get("summary"))))
    else:
        record_content = _record_content(source)
        if record_content:
            candidates_for_blocks.append(("fetched_body", record_content))
        candidates_for_blocks.append(("abstract", _clean(source.get("summary"))))

    blocks: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for origin, text in candidates_for_blocks:
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        clipped, truncated = _clip_at_boundary(text, block_max_chars)
        if not clipped:
            continue
        blocks.append(
            {
                "origin": origin,
                "text": clipped,
                "chars": len(clipped),
                "truncated": truncated,
            }
        )
    return blocks


def source_access_marker(
    blocks: list[dict[str, Any]],
    *,
    fetch_failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the ``sourceAccess`` marker for a source's quotable blocks.

    A failed full-text fetch (403/auth wall/PDF failure recorded in
    ``evidenceFetchAttempts``) degrades the source to abstract-level
    evidence; sources with no quotable text at all are marked so the
    extraction agent skips their quote honestly instead of emitting an empty
    one.
    """
    if not blocks:
        return {"access": "no_quotable_text", "reason": "no_stored_quotable_text"}
    has_full_text = any(block.get("origin") == "fetched_body" for block in blocks)
    if has_full_text:
        return {"access": "full_text", "reason": ""}
    if fetch_failure:
        failure_code = _clean(fetch_failure.get("failureCode")) or "fetch_failed"
        return {"access": "abstract_only", "reason": f"fetch_failed:{failure_code}"}
    return {"access": "abstract_only", "reason": "metadata_only_download"}


def latest_failed_fetch_attempts(
    task_results: Iterable[Any],
) -> dict[str, dict[str, Any]]:
    """Fold stage-task ``evidenceFetchAttempts`` into latest-failed-per-candidate.

    Later entries win per candidateId (same ordering rule as the writeback
    merge), and only ``failed`` attempts are kept: they are the auth-wall /
    403 / PDF-failure signal for abstract-only degradation.
    """
    failed: dict[str, dict[str, Any]] = {}
    for result in task_results:
        attempts = result.get("evidenceFetchAttempts") if isinstance(result, dict) else None
        if not isinstance(attempts, list):
            continue
        for item in attempts:
            if not isinstance(item, dict):
                continue
            candidate_id = _clean(item.get("candidateId"))
            status = _clean(item.get("status")).lower()
            if not candidate_id or status != "failed":
                continue
            attempt: dict[str, Any] = {
                "locator": _clean(item.get("locator"))[:1000],
                "failureCode": _clean(item.get("failureCode"))[:160],
            }
            failed[candidate_id] = attempt
    return failed


def extraction_quotable_sources(
    candidates: list[Mapping[str, Any]],
    records: list[Mapping[str, Any]],
    *,
    failed_fetch_by_candidate_id: Mapping[str, Mapping[str, Any]] | None = None,
    block_max_chars: int = QUOTE_BLOCK_MAX_CHARS,
    total_char_budget: int = QUOTE_SOURCES_TOTAL_CHAR_BUDGET,
) -> list[dict[str, Any]]:
    """Build the context ``quotableSources`` list for an extraction task.

    Candidates come first (in the given — already ranked — order), then
    records that are not already the linked origin of some candidate.  Block
    text stops when the total budget is exhausted; exhausted sources keep
    their metadata with ``blockOmitted: "budget_exhausted"`` so the agent
    knows to page for the remaining text instead of guessing.
    """
    record_by_id = {
        _clean(record.get("recordId")): record
        for record in records
        if _clean(record.get("recordId"))
    }
    failed_fetch_by_candidate_id = failed_fetch_by_candidate_id or {}
    sources: list[dict[str, Any]] = []
    linked_record_ids: set[str] = set()
    used = 0
    for candidate in candidates:
        candidate_id = _clean(candidate.get("candidateId"))
        if not candidate_id:
            continue
        blocks = source_quotable_blocks(
            candidate,
            record_by_id,
            block_max_chars=block_max_chars,
        )
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        linked_record_id = _clean(metadata.get("sourceRecordId"))
        if not linked_record_id:
            for key in _LINKED_RECORD_KEYS:
                linked = metadata.get(key) if isinstance(metadata.get(key), dict) else {}
                linked_record_id = _clean(linked.get("recordId"))
                if linked_record_id:
                    break
        if linked_record_id:
            linked_record_ids.add(linked_record_id)
        source = _quotable_source_entry(
            source_id=candidate_id,
            source_kind="candidate",
            source=candidate,
            blocks=blocks,
            fetch_failure=failed_fetch_by_candidate_id.get(candidate_id),
            budget_left=max(0, total_char_budget - used),
        )
        used += sum(int(block.get("chars") or 0) for block in source.get("blocks") or [])
        sources.append(source)
    for record in records:
        record_id = _clean(record.get("recordId"))
        if not record_id or record_id in linked_record_ids:
            continue
        blocks = source_quotable_blocks(
            record,
            {},
            block_max_chars=block_max_chars,
        )
        source = _quotable_source_entry(
            source_id=record_id,
            source_kind="record",
            source=record,
            blocks=blocks,
            fetch_failure=None,
            budget_left=max(0, total_char_budget - used),
        )
        used += sum(int(block.get("chars") or 0) for block in source.get("blocks") or [])
        sources.append(source)
    return sources


def _quotable_source_entry(
    *,
    source_id: str,
    source_kind: str,
    source: Mapping[str, Any],
    blocks: list[dict[str, Any]],
    fetch_failure: Mapping[str, Any] | None,
    budget_left: int,
) -> dict[str, Any]:
    kept_blocks: list[dict[str, Any]] = []
    omitted = False
    for block in blocks:
        if budget_left <= 0:
            omitted = True
            break
        text = str(block.get("text") or "")
        if len(text) > budget_left:
            clipped, truncated = _clip_at_boundary(text, budget_left)
            if clipped:
                kept_blocks.append({**block, "text": clipped, "chars": len(clipped), "truncated": True})
            omitted = True
            budget_left = 0
            break
        kept_blocks.append(block)
        budget_left -= len(text)
    entry: dict[str, Any] = {
        "sourceId": source_id,
        "sourceKind": source_kind,
        "title": _clean(source.get("title"))[:240],
        "quoteAvailable": bool(kept_blocks),
        "blocks": kept_blocks,
        "blockOrigin": kept_blocks[0]["origin"] if kept_blocks else "",
        "sourceAccess": source_access_marker(blocks, fetch_failure=fetch_failure),
    }
    if omitted:
        entry["blockOmitted"] = "budget_exhausted"
    # ``blocks`` stays explicit even when empty: "no quotable text" is a
    # meaningful supply state for the agent, not a missing field.
    return {
        key: value
        for key, value in entry.items()
        if value not in ("", [], None) or key == "blocks"
    }


def quotable_sources_to_blocks_by_id(
    sources: list[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Index quotable sources into the ``{sourceId: blocks}`` audit shape."""
    blocks_by_id: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        source_id = _clean(source.get("sourceId"))
        if not source_id:
            continue
        blocks_by_id[source_id] = [
            dict(block) for block in (source.get("blocks") or []) if isinstance(block, dict)
        ]
    return blocks_by_id


def _quote_text(value: Any) -> str:
    """Trim a supplied quote with the same 4000 bound the old gate used."""
    return _clean(value)[:4000]


def supplied_quotes(entry: Mapping[str, Any]) -> list[str]:
    """Return every non-empty quote supplied by one extraction entry.

    Only the shapes the historical gate read: nested
    ``claims[]``/``keyFindings[]`` items and ``evidenceRefs[]`` items.  A
    bare top-level ``entry["quote"]`` was never part of the contract and
    stays ignored.
    """
    quotes: list[str] = []
    for list_key in _CLAIM_LIST_KEYS:
        items = entry.get(list_key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            quote = _quote_text(item.get("quote"))
            if quote:
                quotes.append(quote)
    refs = entry.get("evidenceRefs") or entry.get("evidence_refs")
    if isinstance(refs, list):
        for item in refs:
            if not isinstance(item, dict):
                continue
            quote = _quote_text(item.get("quote"))
            if quote:
                quotes.append(quote)
    return quotes


def has_verbatim_anchor(entry: Mapping[str, Any], blocks: list[Mapping[str, Any]]) -> bool:
    """True when any nested claim/evidenceRef quote is a verbatim block substring.

    Mirrors the pre-existing acceptance rule exactly: nested
    ``claims[]``/``keyFindings[]`` items with a verbatim ``quote``, or
    ``evidenceRefs[]`` items with ``{id, quote}`` whose quote is verbatim
    (the ref id is required on that path — a bare quote there was never an
    anchor).
    """
    block_texts = [str(block.get("text") or "") for block in blocks]
    for list_key in _CLAIM_LIST_KEYS:
        items = entry.get(list_key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            quote = _quote_text(item.get("quote"))
            if quote and any(quote in text for text in block_texts):
                return True
    refs = entry.get("evidenceRefs") or entry.get("evidence_refs")
    if isinstance(refs, list):
        for item in refs:
            if not isinstance(item, dict):
                continue
            quote = _quote_text(item.get("quote"))
            ref_id = _clean(item.get("id") or item.get("evidenceRefId") or item.get("refId"))
            if ref_id and quote and any(quote in text for text in block_texts):
                return True
    return False


def nearest_verbatim_hint(
    quote: str,
    blocks: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the closest block region for a non-verbatim supplied quote.

    Uses ``difflib`` against each block: similarity is the ratio of matched
    characters, and the snippet is the best matching block region widened to
    a bounded window so the agent can see the text it should have copied.
    """
    best: dict[str, Any] = {}
    for block in blocks:
        text = str(block.get("text") or "")
        if not text:
            continue
        matcher = difflib.SequenceMatcher(None, quote, text, autojunk=False)
        matched = sum(match.size for match in matcher.get_matching_blocks())
        similarity = matched / max(1, len(quote) + len(text)) * 2
        if best and similarity <= float(best.get("similarity") or 0.0):
            continue
        match = matcher.find_longest_match(0, len(quote), 0, len(text))
        if match.size <= 0:
            snippet = text[:QUOTE_SNIPPET_MAX_CHARS]
        else:
            start = max(0, match.b - QUOTE_SNIPPET_MAX_CHARS // 3)
            end = min(len(text), match.b + match.size + QUOTE_SNIPPET_MAX_CHARS - (match.b - start))
            snippet = text[start:end]
        best = {
            "blockOrigin": str(block.get("origin") or ""),
            "snippet": snippet[:QUOTE_SNIPPET_MAX_CHARS],
            "similarity": round(similarity, 3),
        }
    return best


def audit_extraction_quote_anchors(
    entries: Iterable[Mapping[str, Any]],
    blocks_by_id: Mapping[str, list[dict[str, Any]]],
    *,
    resolve_source_id: Callable[[Mapping[str, Any]], str],
    is_honest_skip: Callable[[Mapping[str, Any]], bool] | None = None,
    entry_path_prefix: str = "candidateExtractions",
    source_kind: str = "candidate",
    resolve_source_kind: Callable[[Mapping[str, Any]], str] | None = None,
) -> list[dict[str, Any]]:
    """Classify extraction entries against the quotable blocks.

    Returns findings for every non-passing entry; ``has_anchor`` findings are
    omitted (they carry no action).  ``mismatched_quote`` is the only
    remediation-eligible kind; ``missing_quote`` and ``empty_source`` are
    hard contract rejections exactly like the pre-existing gate.
    ``resolve_source_kind`` optionally derives the per-entry source kind
    (candidate vs record) with the historical resolution order.
    """
    findings: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        decision = _clean(entry.get("decision")).lower()
        if decision == "exclude":
            continue
        source_id = resolve_source_id(entry)
        if not source_id:
            continue
        entry_kind = resolve_source_kind(entry) if resolve_source_kind else source_kind
        blocks = blocks_by_id.get(source_id)
        if blocks is None:
            # Unknown ids stay with candidate-coverage invalid-id handling.
            continue
        path = f"{entry_path_prefix}[{index}]"
        if not blocks:
            honest = is_honest_skip(entry) if is_honest_skip else False
            if not honest:
                findings.append(
                    {
                        "finding": "empty_source",
                        "sourceId": source_id,
                        "sourceKind": entry_kind,
                        "entryPath": path,
                        "quoteAvailable": False,
                    }
                )
            continue
        if has_verbatim_anchor(entry, blocks):
            continue
        quotes = supplied_quotes(entry)
        finding: dict[str, Any] = {
            "finding": "mismatched_quote" if quotes else "missing_quote",
            "sourceId": source_id,
            "sourceKind": entry_kind,
            "entryPath": path,
            "quoteAvailable": True,
        }
        if quotes:
            finding["suppliedQuote"] = quotes[0][:_SUPPLIED_QUOTE_EXCERPT_CHARS]
            finding["suppliedQuoteCount"] = len(quotes)
        findings.append(finding)
    return findings


def build_quote_anchor_remediation(
    mismatch_findings: list[Mapping[str, Any]],
    blocks_by_id: Mapping[str, list[dict[str, Any]]],
    *,
    recorded_at: str,
    attempt: int = 1,
) -> dict[str, Any]:
    """Render the structured one-shot remediation payload.

    Each finding carries the nearest matching block snippet plus a similarity
    score, so the agent can copy the exact verbatim text on its single
    rewrite.  The payload explicitly warns that a second mismatch is a hard
    rejection — the loop is bounded by construction.
    """
    rendered: list[dict[str, Any]] = []
    for finding in mismatch_findings[:_REMEDIATION_FINDING_LIMIT]:
        source_id = _clean(finding.get("sourceId"))
        blocks = blocks_by_id.get(source_id) or []
        hint: dict[str, Any] = {}
        if str(finding.get("finding")) == "mismatched_quote":
            hint = nearest_verbatim_hint(
                _clean(finding.get("suppliedQuote")),
                blocks,
            )
        item: dict[str, Any] = {
            "finding": _clean(finding.get("finding")),
            "sourceId": source_id,
            "sourceKind": _clean(finding.get("sourceKind")),
            "entryPath": _clean(finding.get("entryPath")),
            "quoteAvailable": bool(finding.get("quoteAvailable")),
        }
        if finding.get("suppliedQuote"):
            item["suppliedQuote"] = _clean(finding.get("suppliedQuote"))
        if hint:
            item["nearestMatch"] = hint
        rendered.append({key: value for key, value in item.items() if value not in ("", None)})
    return {
        "schemaVersion": 1,
        "attempt": attempt,
        "reason": "quote_not_verbatim",
        "parkedStatus": "needs_review",
        "instruction": (
            "至少一个 quote 不是该来源 quotableSources[].blocks 原文块的逐字子串。"
            "请打开最新 source_collection_context_tool 读取 quotableSources，"
            "把 findings[] 里每个 sourceId 的 quote 原样替换为对应 blocks[].text 中的逐字片段"
            "（禁止改写、拼接、凭记忆重写或写空串），然后重新回写 completed。"
            "这是唯一一次修正机会：再次出现不匹配 quote 将按契约直接拒绝。"
            "没有 blocks 的来源跳过 quote（evidenceStatus=missing_evidence_anchor）。"
        ),
        "findings": rendered,
        "recordedAt": recorded_at,
    }


def quote_anchor_error_message(
    findings: list[Mapping[str, Any]],
) -> list[str]:
    """Render the pre-existing human-readable rejection messages.

    Message texts intentionally match the historical gate strings so the
    hard-rejection semantics (missing quote / dishonest empty source /
    second-attempt mismatch) keep their exact contract wording, including
    the ``candidate <id>`` / ``record <id>`` source labels.
    """
    errors: list[str] = []
    for finding in findings:
        kind = _clean(finding.get("finding"))
        source_id = _clean(finding.get("sourceId"))
        source_kind = _clean(finding.get("sourceKind")) or "source"
        source_label = f"{source_kind} {source_id}"
        if kind == "empty_source":
            errors.append(
                f"{source_label} 存储摘要为空：条目必须声明 evidenceStatus=missing_evidence_anchor 诚实跳过，"
                "不能在没有任何锚点的情况下声称证据。"
            )
        elif kind == "missing_quote":
            errors.append(
                f"{source_label} 缺少逐字 quote 锚：嵌套 claims[]/keyFindings[] 项需含 quote，"
                "或 evidenceRefs[] 项需含 {id, quote}（quote 为存储 summary 的逐字子串）。"
            )
        elif kind == "mismatched_quote":
            errors.append(
                f"{source_label} 的 quote 不是存储 summary 的逐字子串："
                "quote 必须从 candidates[].summary 原样复制，禁止改写、拼接或凭记忆重写。"
            )
    return errors
