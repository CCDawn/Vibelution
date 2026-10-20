"""Bounded original-text supply and quote validation for source extraction.

Only successful web_fetch_tool results from the task's Session Journal are
quotable. Search Agent summaries remain discovery hints, never source text.
The same receipt-backed blocks feed context and writeback validation.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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


# arXiv /abs/ paper id with an optional trailing version suffix, e.g.
# ``/abs/2502.01542v2`` (new style) or ``/abs/math.GT/0309136v2`` (old style).
_ARXIV_VERSIONED_ABS_PATH = re.compile(r"^(?P<base>/abs/.+?)v\d+$")

# DOI path segment for cross-host receipt bridging: a registrant prefix plus
# suffix, e.g. ``/10.21656/1000-0887.390245`` on doi.org itself or
# ``/EN/10.21656/1000-0887.390245`` / ``/doi/10.21656/...`` on a publisher
# mirror.  The leading-slash boundary keeps version-ish substrings
# (``.../v10.1234/...``) from matching.  The suffix charset excludes ``/``, so
# a DOI embedded mid-path (``/articles/10.3389/fmicb.2023.1104454/full`` on
# frontiersin.org) bridges without swallowing the trailing path segment — the
# old end-anchored ``\S+$`` form produced ``doi:...1104454/full``, a key no
# candidate could ever emit.  Legacy slash-bearing DOI suffixes stay
# unbridgeable by this key rather than risking overmatch.
_DOI_PATH_SEGMENT = re.compile(r"(?<=/)(10\.\d{4,9}/[^\s/?#]+)")

# Publisher article URLs that embed the DOI *suffix* while the prefix is
# implicit in the host's URL scheme — pure normalization cannot derive these.
# Scoped exactly like the PMC mirror hosts: host + path shape must both match.
_HOST_DOI_ARTICLE_PATHS = {
    # nature.com/articles/<doi-suffix> ↔ doi:<prefix>/<doi-suffix>
    "nature.com": ("10.1038", re.compile(r"^/articles/(?P<suffix>[^/?#]+)/?$")),
}

# PMC article id as one complete path segment (slash-bounded both sides), e.g.
# ``/articles/PMC1234567/`` on pmc.ncbi.nlm.nih.gov or
# ``/europepmc/webservices/rest/PMC1234567/fullTextXML`` on ebi.ac.uk.
_PMC_PATH_SEGMENT = re.compile(r"(?i)(?<=/)PMC\d+(?=/|$)")

# The two official PMC mirrors whose URLs may carry the article id anywhere in
# the path.  Other hosts never emit a ``pmc:`` key even with a PMC-ish segment.
_PMC_ARTICLE_HOSTS = ("pmc.ncbi.nlm.nih.gov", "ebi.ac.uk")


def _doi_locator_key(path: str) -> str:
    """Canonical ``doi:<doi>`` bridge key for one URL path, or ``""``.

    DOI-registered sources are otherwise a structural dead end: fetching the
    ``doi.org`` locator is rejected as a cross-host redirect while the fetched
    publisher mirror never string-matches the DOI locator.  The key carries no
    scheme/host, so both receipt and candidate sides agree on it.
    """
    match = _DOI_PATH_SEGMENT.search(path)
    if not match:
        return ""
    doi = match.group(1).rstrip(".,;:")
    return f"doi:{doi.lower()}" if doi else ""


def _host_doi_locator_key(host: str, path: str) -> str:
    """``doi:<prefix>/<suffix>`` key for hosts whose article URL embeds only the DOI suffix.

    nature.com serves ``https://www.nature.com/articles/<doi-suffix>`` where the
    registrant prefix (10.1038) is carried by the host, not the path — the
    generic path-segment key can never fire.  Registration is deliberately
    narrow (one host, one path shape) and mirrors the PMC mirror-host rule.
    """
    entry = _HOST_DOI_ARTICLE_PATHS.get(host)
    if not entry:
        return ""
    doi_prefix, path_shape = entry
    match = path_shape.match(path)
    if not match:
        return ""
    suffix = match.group("suffix").rstrip(".,;:")
    return f"doi:{doi_prefix}/{suffix.lower()}" if suffix else ""


def _pmc_locator_key(host: str, path: str) -> str:
    """Canonical ``pmc:PMC1234567`` bridge key for one PMC mirror URL, or ``""``.

    Pure URL normalization — no DOI↔PMCID network lookup. The same full text is
    served under both mirrors, so a candidate on one host should match a fetch
    receipt on the other. The key requires a complete PMC id path segment on the
    two official mirror hosts, keeping the bridge narrow enough not to overmatch.
    """
    if host not in _PMC_ARTICLE_HOSTS:
        return ""
    match = _PMC_PATH_SEGMENT.search(path)
    if not match:
        return ""
    return f"pmc:{match.group(0).upper()}"


def _normalized_locator_keys(url: Any) -> list[str]:
    """Candidate match keys for one source locator: raw form first, then one
    normalized form.

    Receipt locators are the exact ``web_fetch_tool`` arguments, while record
    locators may carry a cosmetic variant of the same page.  Normalization is
    conservative: lowercase host, drop a ``www.`` prefix, fold the
    ``export.arxiv.org`` mirror onto ``arxiv.org``, and — only for arXiv
    ``/abs/`` pages — strip the optional trailing ``vN`` version suffix from
    the paper id (``/abs/2502.01542v2`` and ``/abs/2502.01542`` serve the same
    page).  Paths on every other site are never rewritten; URLs whose path
    carries a DOI segment (anywhere, bounded by ``/``) additionally emit a
    scheme-free ``doi:<doi>`` bridge key so a DOI locator matches its
    publisher-mirror fetch receipt, registered hosts whose article URL embeds
    only the DOI suffix (nature.com) emit their implicit-prefix ``doi:`` key,
    and URLs on the two PMC mirrors additionally emit ``pmc:<PMC id>`` so a
    pmc.ncbi.nlm.nih.gov candidate matches an ebi.ac.uk receipt (and vice
    versa) for the same article.
    """
    raw = _clean(url)
    if not raw:
        return []
    keys = [raw]
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return keys
    host = (parsed.hostname or "").lower()
    if not parsed.scheme or not host:
        return keys
    if host.startswith("www."):
        host = host[len("www."):]
    if host == "export.arxiv.org":
        host = "arxiv.org"
    path = parsed.path
    if host == "arxiv.org":
        versioned = _ARXIV_VERSIONED_ABS_PATH.match(path)
        if versioned:
            path = versioned.group("base")
    netloc = host if port is None else f"{host}:{port}"
    normalized = urlunsplit((parsed.scheme, netloc, path, parsed.query, parsed.fragment))
    if normalized != raw and normalized not in keys:
        keys.append(normalized)
    doi_key = _doi_locator_key(path)
    if doi_key and doi_key not in keys:
        keys.append(doi_key)
    host_doi_key = _host_doi_locator_key(host, path)
    if host_doi_key and host_doi_key not in keys:
        keys.append(host_doi_key)
    pmc_key = _pmc_locator_key(host, path)
    if pmc_key and pmc_key not in keys:
        keys.append(pmc_key)
    return keys


def source_quotable_blocks(
    source: Mapping[str, Any],
    record_by_id: Mapping[str, Mapping[str, Any]],
    *,
    fetched_text_by_locator: Mapping[str, Mapping[str, str]] | None = None,
    block_max_chars: int = QUOTE_BLOCK_MAX_CHARS,
) -> list[dict[str, Any]]:
    """Bind a source locator to original text from this task's fetch receipts."""
    from .doi_enrichment import source_metadata_doi

    records = [source]
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    linked_id = _clean(metadata.get("sourceRecordId"))
    if not linked_id:
        for key in _LINKED_RECORD_KEYS:
            linked = metadata.get(key) if isinstance(metadata.get(key), dict) else {}
            linked_id = _clean(linked.get("recordId"))
            if linked_id:
                break
    if linked_id in record_by_id:
        records.append(record_by_id[linked_id])
    fetched = fetched_text_by_locator or {}
    # Receipt keys are exact web_fetch_tool arguments; record locators may be
    # a variant form of the same page (arXiv vN suffix, www./case, export
    # mirror).  Index each receipt under every candidate key, exact form
    # first; block fields keep pointing at the original receipt.
    fetched_by_key: dict[str, Mapping[str, str]] = {}
    for locator, receipt in fetched.items():
        keys = _normalized_locator_keys(locator)
        if isinstance(receipt, Mapping):
            keys.extend(_normalized_locator_keys(receipt.get("locator")))
            # Bare-URL redirect variant: the receipt header carries the final
            # (resolved) URL of the fetch, so it joins the index under its own
            # normalized keys — a record whose locator is the post-redirect
            # form then binds the receipt fetched through the original URL.
            keys.extend(_normalized_locator_keys(receipt.get("resolvedUrl")))
        for key in keys:
            fetched_by_key.setdefault(key, receipt)
    blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        locator_keys = [_clean(record.get(key)) for key in ("sourceUrl", "sourceRef", "rawLocation")]
        # SCI-021: a candidate enriched with ``metadata.doi`` must bind a
        # receipt fetched through its ``https://doi.org/<doi>`` form — the
        # publisher 403 hint reroutes exactly there, and the EuropePMC mirror
        # fallback answers inside that same tool call.  The DOI locator emits
        # the ``doi:<doi>`` bridge key on the candidate side, matching the
        # doi.org receipt (or any publisher-mirror URL ending in the DOI).
        record_doi = source_metadata_doi(record)
        if record_doi:
            doi_locator = f"https://doi.org/{record_doi}"
            if doi_locator not in locator_keys:
                locator_keys.append(doi_locator)
        for key in locator_keys:
            receipt = None
            for candidate_key in _normalized_locator_keys(key):
                receipt = fetched_by_key.get(candidate_key)
                if receipt:
                    break
            if not receipt:
                continue
            text = _clean(receipt.get("text"))
            if not text or text in seen:
                continue
            seen.add(text)
            clipped, truncated = _clip_at_boundary(text, block_max_chars)
            if clipped:
                blocks.append({
                    **{k: receipt[k] for k in ("locator", "resolvedUrl", "eventId", "sessionId", "turnId") if k in receipt},
                    "origin": "fetched_text", "text": clipped,
                    "chars": len(clipped), "truncated": truncated,
                })
    return blocks


def source_access_marker(
    blocks: list[dict[str, Any]],
    *,
    fetch_failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetching a page proves text access, not access to the full paper."""
    if blocks:
        return {"access": "retrieved_text", "reason": "page_text_not_full_paper_verification"}
    reason = "no_fetched_source_text"
    if fetch_failure:
        reason = "fetch_failed:" + (_clean(fetch_failure.get("failureCode")) or "fetch_failed")
    return {"access": "no_quotable_text", "reason": reason}


def latest_failed_fetch_attempts(
    task_results: Iterable[Any],
) -> dict[str, dict[str, Any]]:
    """Fold stage-task ``evidenceFetchAttempts`` into latest-failed-per-candidate.

    Later entries win per candidateId (same ordering rule as the writeback
    merge), and only ``failed`` attempts are kept: they are the auth-wall /
    403 / PDF-failure signal when no original text is available.
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
            if candidate_id and status == "fetched":
                failed.pop(candidate_id, None)
                continue
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
    fetched_text_by_locator: Mapping[str, Mapping[str, str]] | None = None,
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
            fetched_text_by_locator=fetched_text_by_locator,
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
            fetched_text_by_locator=fetched_text_by_locator,
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
    from .doi_enrichment import source_metadata_doi

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
    # Fetchable locator surface (SCI-021): the original URL stays first and a
    # known DOI additionally surfaces as its fetchable ``https://doi.org/``
    # form, so the agent can follow the 403 hint onto the DOI link (whose
    # EuropePMC mirror fallback answers inside the same tool call).
    locators: list[str] = []
    for key in ("sourceUrl", "sourceRef", "rawLocation"):
        value = _clean(source.get(key))
        if value.startswith(("http://", "https://")) and value not in locators:
            locators.append(value[:1000])
    doi = source_metadata_doi(source)
    if doi:
        doi_link = f"https://doi.org/{doi}"[:1000]
        if doi_link not in locators:
            locators.append(doi_link)
    entry: dict[str, Any] = {
        "sourceId": source_id,
        "sourceKind": source_kind,
        "title": _clean(source.get("title"))[:240],
        "quoteAvailable": bool(kept_blocks),
        "blocks": kept_blocks,
        "blockOrigin": kept_blocks[0]["origin"] if kept_blocks else "",
        "sourceAccess": source_access_marker(blocks, fetch_failure=fetch_failure),
    }
    if doi:
        entry["doi"] = doi[:240]
    if locators:
        entry["locators"] = locators
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


# Typographic variants that PDF/HTML extraction routinely introduces and
# LLM tokenizers cannot reliably reproduce byte-for-byte.  They carry no
# evidence semantics, so verbatim anchoring folds them to ASCII form:
# curly quotes → " ', NBSP → space, zero-width characters dropped,
# en/em dashes → "-".
_VERBATIM_TYPOGRAPHIC_ASCII = str.maketrans({
    "\u201c": '"',  # LEFT DOUBLE QUOTATION MARK
    "\u201d": '"',  # RIGHT DOUBLE QUOTATION MARK
    "\u2018": "'",  # LEFT SINGLE QUOTATION MARK
    "\u2019": "'",  # RIGHT SINGLE QUOTATION MARK
    "\u00a0": " ",  # NO-BREAK SPACE
    "\u200b": "",   # ZERO WIDTH SPACE
    "\u200c": "",   # ZERO WIDTH NON-JOINER
    "\u200d": "",   # ZERO WIDTH JOINER
    "\ufeff": "",   # ZERO WIDTH NO-BREAK SPACE / BOM
    "\u2013": "-",  # EN DASH
    "\u2014": "-",  # EM DASH
})

# Every whitespace run (spaces, tabs, newlines, NBSP folded above) collapses
# to a single space, and the single spaces are then dropped from the
# containment key: extraction artifacts both duplicate and LOSE inter-word
# spaces (the production incident had ``ends withZ = 164`` where the quote
# read ``ends with Z = 164``), and whitespace placement carries no evidence
# semantics.
_VERBATIM_WHITESPACE_RUN = re.compile(r"\s+")


def _normalize_verbatim_text(text: str) -> str:
    """Whitespace/typographic-insensitive containment key for verbatim quotes.

    Verbatim means identical except whitespace runs and typographic
    artifacts, with case still sensitive.  Whitespace runs collapse to a
    single space, the ends are stripped, and the remaining spaces drop out
    of the key; typographic variants fold to their ASCII forms.  Wording and
    case are never touched — a paraphrase or a case change still mismatches.
    """
    collapsed = _VERBATIM_WHITESPACE_RUN.sub(
        " ", text.translate(_VERBATIM_TYPOGRAPHIC_ASCII)
    ).strip()
    return collapsed.replace(" ", "")


def has_verbatim_anchor(entry: Mapping[str, Any], blocks: list[Mapping[str, Any]]) -> bool:
    """True when any nested claim/evidenceRef quote is a verbatim block substring.

    Verbatim = identical except whitespace runs and typographic artifacts
    (case-sensitive): both the quote and every block text pass through
    ``_normalize_verbatim_text`` before the containment check, so an
    extraction artifact like ``ends withZ = 164`` still anchors the quote
    ``ends with Z = 164``, while a paraphrase or a case change still
    mismatches.

    Mirrors the pre-existing acceptance rule otherwise: nested
    ``claims[]``/``keyFindings[]`` items with a verbatim ``quote``, or
    ``evidenceRefs[]`` items with ``{id, quote}`` whose quote is verbatim
    (the ref id is required on that path — a bare quote there was never an
    anchor).
    """
    # Normalize each block once per call; quotes normalize once each below.
    block_keys = [
        _normalize_verbatim_text(str(block.get("text") or "")) for block in blocks
    ]
    for list_key in _CLAIM_LIST_KEYS:
        items = entry.get(list_key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            quote_key = _normalize_verbatim_text(_quote_text(item.get("quote")))
            if quote_key and any(quote_key in key for key in block_keys):
                return True
    refs = entry.get("evidenceRefs") or entry.get("evidence_refs")
    if isinstance(refs, list):
        for item in refs:
            if not isinstance(item, dict):
                continue
            quote_key = _normalize_verbatim_text(_quote_text(item.get("quote")))
            ref_id = _clean(item.get("id") or item.get("evidenceRefId") or item.get("refId"))
            if ref_id and quote_key and any(quote_key in key for key in block_keys):
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
    remediation-eligible kind; ``missing_quote``, ``empty_source`` and
    ``false_honest_skip`` are hard contract rejections exactly like the
    pre-existing gate.  ``resolve_source_kind`` optionally derives the
    per-entry source kind (candidate vs record) with the historical
    resolution order.
    """
    findings: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        decision = _clean(entry.get("decision")).lower()
        if decision == "exclude":
            # False honest skip: an exclude that declares
            # ``missing_evidence_anchor`` while the source actually stores
            # real fetched blocks is a false "no quotable text" declaration
            # (the production incident excluded every candidate this way and
            # materialized zero evidence cards).  A genuine ruling — exclude
            # with a real reason (irrelevant/duplicate/...), a source with no
            # blocks, or an unknown source id — stays untouched.
            source_id = resolve_source_id(entry)
            if not source_id:
                continue
            blocks = blocks_by_id.get(source_id)
            if not blocks:
                continue
            if is_honest_skip and is_honest_skip(entry):
                findings.append(
                    {
                        "finding": "false_honest_skip",
                        "sourceId": source_id,
                        "sourceKind": (
                            resolve_source_kind(entry) if resolve_source_kind else source_kind
                        ),
                        "entryPath": f"{entry_path_prefix}[{index}]",
                        "quoteAvailable": True,
                        "blockCount": len(blocks),
                    }
                )
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


# Per-kind one-line guidance for honest-skip findings: mixed batches park
# with both mismatch snippets and hard-error candidates, so the agent can fix
# both classes in a single rewrite.  The wording mirrors the historical
# hard-rejection contract text (``quote_anchor_error_message``).
# ``false_honest_skip`` intentionally has no entry: it hard-rejects through
# ``quote_anchor_error_message`` only — rendering declare-skip guidance for
# the very declaration it forbids would mislead the agent, and its absence
# makes the remediation builder drop it silently (no duplicate reporting).
_HONEST_SKIP_GUIDANCE = {
    "empty_source": (
        "该来源没有真实抓取原文：声明 evidenceStatus=missing_evidence_anchor"
        " 且 decision=exclude 诚实跳过，不要保留空 quote 或声称证据。"
    ),
    "missing_quote": (
        "该来源有可引用原文但条目缺少逐字 quote 锚：从 quotableSources[].blocks[].text"
        " 原样复制 quote 补上，或声明 evidenceStatus=missing_evidence_anchor"
        " 且 decision=exclude 跳过。"
    ),
}


def build_quote_anchor_remediation(
    mismatch_findings: list[Mapping[str, Any]],
    blocks_by_id: Mapping[str, list[dict[str, Any]]],
    *,
    recorded_at: str,
    attempt: int = 1,
    hard_findings: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Render the structured one-shot remediation payload.

    Each finding carries the nearest matching block snippet plus a similarity
    score, so the agent can copy the exact verbatim text on its single
    rewrite.  ``hard_findings`` (mixed batches: e.g. a 403 candidate with no
    original text next to a fetchable candidate whose quote is paraphrased)
    render as ``honestSkipFindings`` — candidate ids plus the exact
    declare-skip guidance — so one rewrite fixes both classes.  The payload
    explicitly warns that a second mismatch is a hard rejection — the loop is
    bounded by construction.
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
    honest_skip: list[dict[str, Any]] = []
    for finding in (hard_findings or [])[:_REMEDIATION_FINDING_LIMIT]:
        kind = _clean(finding.get("finding"))
        guidance = _HONEST_SKIP_GUIDANCE.get(kind)
        if not guidance:
            continue
        honest_skip.append({
            "finding": kind,
            "sourceId": _clean(finding.get("sourceId")),
            "sourceKind": _clean(finding.get("sourceKind")),
            "entryPath": _clean(finding.get("entryPath")),
            "guidance": guidance,
        })
    instruction = (
        "至少一个 quote 不是该来源 quotableSources[].blocks 原文块的逐字子串。"
        "请打开最新 source_collection_context_tool 读取 quotableSources，"
        "把 findings[] 里每个 sourceId 的 quote 原样替换为对应 blocks[].text 中的逐字片段"
        "（禁止改写、拼接、凭记忆重写或写空串），然后重新回写 completed。"
        "这是唯一一次修正机会：再次出现不匹配 quote 将按契约直接拒绝。"
        "没有 blocks 的来源跳过 quote（evidenceStatus=missing_evidence_anchor）。"
    )
    if honest_skip:
        instruction += (
            " 同批还有无真实抓取原文/缺锚的条目：按 honestSkipFindings[] 里每个"
            " sourceId 的指引声明 evidenceStatus=missing_evidence_anchor 且"
            " decision=exclude 诚实跳过，一次重写同时修两类问题。"
        )
    remediation: dict[str, Any] = {
        "schemaVersion": 1,
        "attempt": attempt,
        "reason": "quote_not_verbatim",
        "parkedStatus": "needs_review",
        "instruction": instruction,
        "findings": rendered,
        "recordedAt": recorded_at,
    }
    if honest_skip:
        remediation["honestSkipFindings"] = honest_skip
    return remediation


def quote_anchor_error_message(
    findings: list[Mapping[str, Any]],
) -> list[str]:
    """Render the pre-existing human-readable rejection messages.

    Message texts intentionally match the historical gate strings so the
    hard-rejection semantics (missing quote / dishonest empty source /
    false honest skip / second-attempt mismatch) keep their exact contract
    wording, including the ``candidate <id>`` / ``record <id>`` source labels.
    """
    errors: list[str] = []
    for finding in findings:
        kind = _clean(finding.get("finding"))
        source_id = _clean(finding.get("sourceId"))
        source_kind = _clean(finding.get("sourceKind")) or "source"
        source_label = f"{source_kind} {source_id}"
        if kind == "empty_source":
            errors.append(
                f"{source_label} 没有真实抓取原文：条目必须声明 evidenceStatus=missing_evidence_anchor 诚实跳过，"
                "不能在没有任何锚点的情况下声称证据。"
            )
        elif kind == "missing_quote":
            errors.append(
                f"{source_label} 缺少逐字 quote 锚：嵌套 claims[]/keyFindings[] 项需含 quote，"
                "或 evidenceRefs[] 项需含 {id, quote}（quote 为 quotableSources 原文块的逐字子串）。"
            )
        elif kind == "mismatched_quote":
            errors.append(
                f"{source_label} 的 quote 不是 quotableSources 原文块的逐字子串："
                "quote 必须从 quotableSources[].blocks[].text 原样复制，禁止改写、拼接或凭记忆重写。"
            )
        elif kind == "false_honest_skip":
            block_count = _clean(finding.get("blockCount")) or "0"
            errors.append(
                f"{source_label} 存在真实抓取原文块（{block_count} 块）："
                "声明 evidenceStatus=missing_evidence_anchor 属虚假诚实跳过。"
                "两条出路：改 decision=keep 并从 quotableSources[].blocks[].text 逐字引用 quote 锚；"
                "或按真实理由排除（如 irrelevant/duplicate/low_quality），"
                "不得声明 missing_evidence_anchor。"
            )
    return errors
