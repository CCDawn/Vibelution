"""OpenAlex title-lookup DOI enrichment for source-collection candidates.

Production gap (SCI-021): finding-stage candidates materialized from providers
that return bare publisher URLs (``www.mdpi.com/...``) carry no
``metadata.doi``.  After the publisher answers 403 there is nothing for the
agent to reroute through ``https://doi.org/<doi>`` into the EuropePMC mirror
fallback, so the candidate can only end up ``missing_evidence_anchor``.  This
module reverse-looks-up the DOI by exact normalized-title match against the
OpenAlex ``/works?search=`` endpoint — strictly fail-open: any transport,
HTTP, or parse failure returns ``None`` and never raises.

Persistence contract: candidates live in the run-scoped candidate store
(``candidate_store/index.json`` under the run workflow root), which is the
authoritative metadata surface both the extraction context and the writeback
audit read.  Enrichment hits are written back there idempotently.
"""

from __future__ import annotations

import threading
import urllib.parse
from collections.abc import Mapping
from typing import Any

_OPENALEX_WORKS_ENDPOINT = "https://api.openalex.org/works"
_OPENALEX_RESULT_WINDOW = 5
_OPENALEX_TIMEOUT_SECONDS = 10.0
# Shared per-provider etiquette limiter key (search_execution registry).
_OPENALEX_PROVIDER_KEY = "openalex_api"
_DOI_URL_PREFIXES = ("https://doi.org/", "https://dx.doi.org/")

# Read-path network budget: one context read performs at most this many real
# OpenAlex lookups (cache hits are free), so a page full of DOI-less
# candidates can never stall the context tool behind dozens of timeouts.
READ_PATH_MAX_NETWORK_LOOKUPS = 4

_ENRICHMENT_CACHE_LOCK = threading.Lock()
# normalized title -> bare DOI (positive hit) or ``None`` (negative result);
# both polarities are cached so repeated reads never re-hit the network.
_ENRICHMENT_CACHE: dict[str, str | None] = {}

# Punctuation stripped from both title ends before comparison: ASCII marks
# plus the typographic quotes/dashes that survive copy-paste from publisher
# pages.  Interior punctuation stays significant on purpose.
_TITLE_EDGE_PUNCTUATION = (
    " \t\r\n\f\v.,;:!?…·‐‑‒–—―\"'ʼ`´«»„“”‘’()[]{}<>*#|/_\\+=@$%^&~"
)


def normalize_enrichment_title(title: str) -> str:
    """Casefold, collapse whitespace, and strip edge punctuation from a title."""
    collapsed = " ".join(str(title or "").split())
    return collapsed.casefold().strip(_TITLE_EDGE_PUNCTUATION)


def bare_doi(value: Any) -> str:
    """Normalize one DOI-ish value to a bare DOI (``https://doi.org/`` stripped)."""
    doi = str(value or "").strip()
    for prefix in _DOI_URL_PREFIXES:
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi.strip().rstrip(".,;:")


def source_metadata_doi(source: Mapping[str, Any]) -> str:
    """Bare DOI carried by one candidate/record metadata envelope, or ``""``."""
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    doi = bare_doi(metadata.get("doi"))
    if doi:
        return doi
    imported = (
        metadata.get("importedFromDataRecord")
        if isinstance(metadata.get("importedFromDataRecord"), dict)
        else {}
    )
    return bare_doi(imported.get("doi"))


def _openalex_transport_fetch(url: str) -> Any:
    """Single proxy-aware network attempt; the only real-network touch point.

    Reuses the research providers ``_fetch_json`` helper so the operator proxy
    configuration (``network.proxy_enabled``/``proxy_url``) applies.  Tests
    pin/replace exactly this seam; everything above it stays live.
    """
    from core.research.providers import _fetch_json

    return _fetch_json(url, timeout=_OPENALEX_TIMEOUT_SECONDS, accept="application/json")


def _openalex_exact_title_doi(title: str) -> str | None:
    """One single-attempt OpenAlex lookup; returns a bare DOI or ``None``.

    The shared ``openalex_api`` etiquette limiter keeps enrichment inside the
    same polite-pool budget as formal searches.  Exact normalized-title match
    only: a fuzzy hit would attach the wrong DOI and silently reroute the
    mirror fallback to a different paper — a miss is strictly better than a
    wrong enrichment.
    """
    from ..facade_helpers import _SOURCE_COLLECTION_OPENALEX_MAILTO
    from .search_execution import _source_collection_rate_limiter

    query = urllib.parse.urlencode(
        {
            "search": title,
            "per-page": str(_OPENALEX_RESULT_WINDOW),
            "mailto": _SOURCE_COLLECTION_OPENALEX_MAILTO,
        }
    )
    url = f"{_OPENALEX_WORKS_ENDPOINT}?{query}"
    limiter = _source_collection_rate_limiter(_OPENALEX_PROVIDER_KEY)
    if limiter is not None:
        limiter.try_acquire(_OPENALEX_PROVIDER_KEY)
    payload = _openalex_transport_fetch(url)
    if not isinstance(payload, dict):
        return None
    expected = normalize_enrichment_title(title)
    if not expected:
        return None
    for work in list(payload.get("results") or [])[:_OPENALEX_RESULT_WINDOW]:
        if not isinstance(work, dict):
            continue
        if normalize_enrichment_title(str(work.get("display_name") or "")) != expected:
            continue
        doi = bare_doi(work.get("doi"))
        if doi:
            return doi
    return None


def _lookup_with_cache(title: str) -> tuple[str | None, bool]:
    """Return ``(doi, hit_network)``; both polarities cached per normalized title."""
    key = normalize_enrichment_title(title)
    if not key:
        return None, False
    with _ENRICHMENT_CACHE_LOCK:
        if key in _ENRICHMENT_CACHE:
            return _ENRICHMENT_CACHE[key], False
    doi: str | None = None
    try:
        doi = _openalex_exact_title_doi(title)
    except Exception:  # noqa: BLE001 - fail-open by contract; enrichment never raises
        doi = None
    with _ENRICHMENT_CACHE_LOCK:
        _ENRICHMENT_CACHE[key] = doi
    return doi, True


def enrich_missing_doi(title: str) -> str | None:
    """Best-effort bare DOI for one title (cached, fail-open, exact match only)."""
    return _lookup_with_cache(title)[0]


def enrich_candidates_missing_doi(
    team_id: str,
    run_id: str,
    candidates: list[dict[str, Any]],
) -> list[str]:
    """Enrich in-page candidates lacking DOI metadata; persist hits to the store.

    Mutates the in-memory candidate dicts (``metadata.doi``) so the context
    response and the quote-anchor supply see the enriched DOI immediately,
    then writes each hit back to the run candidate store idempotently — a
    store record that already carries a DOI (enriched concurrently or by an
    earlier read) keeps the stored value.  Real network lookups are bounded
    per call by ``READ_PATH_MAX_NETWORK_LOOKUPS``; never raises.
    """
    enriched: dict[str, str] = {}
    network_calls = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("candidateId") or "").strip()
        title = str(candidate.get("title") or "").strip()
        if not candidate_id or not title or source_metadata_doi(candidate):
            continue
        if network_calls >= READ_PATH_MAX_NETWORK_LOOKUPS:
            break
        doi, hit_network = _lookup_with_cache(title)
        if hit_network:
            network_calls += 1
        if not doi:
            continue
        enriched[candidate_id] = doi
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        metadata["doi"] = doi
        candidate["metadata"] = metadata
    if not enriched:
        return []
    try:
        _persist_candidate_doi_enrichments(team_id, run_id, enriched)
    except Exception:  # noqa: BLE001 - read-path enrichment is best-effort
        pass
    return sorted(enriched)


def _persist_candidate_doi_enrichments(team_id: str, run_id: str, enriched: dict[str, str]) -> None:
    """Write enriched DOIs into the run candidate store under the workflow lock."""
    from core.web.services import team_workflow_orchestration_service as s

    normalized_team_id = s._trim_text(team_id, max_length=128)
    normalized_run_id = s._trim_text(run_id, max_length=128)
    if not normalized_team_id or not normalized_run_id:
        return
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id, run_id=normalized_run_id)
        changed = False
        for item in list(candidate_store.get("candidates") or []):
            if not isinstance(item, dict):
                continue
            candidate_id = s._trim_text(item.get("candidateId"), max_length=160)
            doi = enriched.get(candidate_id)
            if not candidate_id or not doi:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if bare_doi(metadata.get("doi")):
                continue
            metadata["doi"] = doi
            metadata["doiEnrichment"] = {
                "provider": "openalex_title_lookup",
                "recordedAt": now,
            }
            item["metadata"] = metadata
            item["updatedAt"] = now
            changed = True
        if changed:
            candidate_store["updatedAt"] = now
            s._write_json(
                s._candidate_store_path(normalized_team_id, normalized_run_id),
                candidate_store,
            )
