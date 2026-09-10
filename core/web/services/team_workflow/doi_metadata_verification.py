"""DOI metadata verification fallback for citation receipts.

Challenge Cup citation receipts fail closed when the evidence page could not
be fetched (publisher auth walls / paywalls redirect or block the fetch), even
when the underlying publication is real and DOI-addressable.  This module adds
one sanctioned fallback authority: when a failing receipt's URL resolves to a
DOI, the DOI registry itself (Crossref metadata API, else doi.org content
negotiation) confirms the publication exists.

The fallback is deliberately narrow and fail-closed:

* only receipts that would otherwise fail are verified;
* no DOI in the hint or URL, or any network/parse failure, keeps ``failed``;
* every network call carries an explicit timeout and swallows all exceptions;
* callers decide whether verification runs at all (package builders and the
  challenge-question re-verification entry point), so pure projections and
  existing tests stay offline and deterministic.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlparse
from urllib.request import Request, urlopen

# Crossref DOI pattern: `10.` + registrant code + `/` + suffix.  Used both to
# recognize explicit DOIs and to reject accidental matches from free text.
_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)

# `https://doi.org/10.1103/PhysRevLett...` -> `10.1103/PhysRevLett...`
_DOI_ORG_PATH = re.compile(r"^/(?:doi(?:\.org)?/)?(10\.\d{4,9}/\S+)$", re.IGNORECASE)

_CROSSREF_WORKS_URL = "https://api.crossref.org/works/{doi}"
_DOI_ORG_URL = "https://doi.org/{doi}"
_CSL_JSON_ACCEPT = "application/vnd.citationstyles.csl+json"

DEFAULT_TIMEOUT_SECONDS = 5.0

# Bounded fan-out: the observed failing batches are 8-12 publisher URLs; a
# package build or re-verification pass must never sweep an unbounded list.
DEFAULT_MAX_VERIFICATIONS = 12

# Default network authority.  Injectable so tests (and future offline
# registries) never touch the real network.
default_doi_verifier: Callable[[str], Mapping[str, Any] | None] = lambda doi: (
    fetch_doi_metadata(doi)
)


def normalize_doi(value: object) -> str:
    """Return a canonical DOI string, or "" when the value is not DOI-shaped."""

    doi = str(value or "").strip()
    # Strip common URL/citation prefixes so an evidence `doi` field carrying a
    # resolved link still normalizes to the bare DOI.
    doi = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = doi.removeprefix("doi:").strip()
    doi = doi.strip().rstrip(".,;")
    return doi if _DOI_PATTERN.fullmatch(doi) else ""


def extract_doi(source_url: object, doi_hint: object = "") -> str:
    """Resolve the DOI behind an evidence source URL.

    Priority: an explicit ``doi`` field on the evidence row, then
    ``https://doi.org/10.x/...`` links, then ``?doi=``/``&doi=`` query
    parameters on publisher landing pages.  Returns "" when nothing
    DOI-shaped is present — callers must treat that as "no fallback
    authority" and keep the receipt failed.
    """

    hinted = normalize_doi(doi_hint)
    if hinted:
        return hinted
    url = str(source_url or "").strip()
    if not url:
        return ""
    direct = normalize_doi(url)
    if direct:
        return direct
    parsed = urlparse(url)
    if (parsed.hostname or "").lower().rstrip(".") in {"doi.org", "dx.doi.org"}:
        # doi.org links may be percent-encoded; decode before matching.
        match = _DOI_ORG_PATH.fullmatch(unquote(parsed.path or ""))
        if match:
            candidate = normalize_doi(match.group(1))
            if candidate:
                return candidate
    try:
        query_pairs = parse_qsl(parsed.query or "", keep_blank_values=True)
    except Exception:  # noqa: BLE001 - malformed query must never raise here
        query_pairs = []
    for key, value in query_pairs:
        if key.lower() in {"doi", "doi_org", "ddoi"}:
            candidate = normalize_doi(value)
            if candidate:
                return candidate
    return ""


def _read_json_response(response: Any) -> Mapping[str, Any] | None:
    try:
        with response:
            payload = response.read(1024 * 1024)
        data = json.loads(payload.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 - any decode/IO failure is "unverified"
        return None
    return data if isinstance(data, Mapping) else None


def _crossref_metadata(doi: str, timeout: float) -> Mapping[str, Any] | None:
    request = Request(  # noqa: S310 - fixed https registry host
        _CROSSREF_WORKS_URL.format(doi=quote(doi, safe="/")),
        headers={"Accept": "application/json", "User-Agent": "Vibelution-citation-verify/1.0"},
    )
    try:
        response = urlopen(request, timeout=timeout)  # noqa: S310 - see above
    except Exception:  # noqa: BLE001 - network failures are "unverified"
        return None
    data = _read_json_response(response)
    if data is None:
        return None
    if str(data.get("status") or "") == "ok" or isinstance(data.get("message"), Mapping):
        message = data.get("message")
        return message if isinstance(message, Mapping) else data
    return None


def _doi_org_metadata(doi: str, timeout: float) -> Mapping[str, Any] | None:
    request = Request(  # noqa: S310 - fixed https registry host
        _DOI_ORG_URL.format(doi=quote(doi, safe="/")),
        headers={"Accept": _CSL_JSON_ACCEPT, "User-Agent": "Vibelution-citation-verify/1.0"},
    )
    try:
        response = urlopen(request, timeout=timeout)  # noqa: S310 - see above
    except Exception:  # noqa: BLE001 - network failures are "unverified"
        return None
    return _read_json_response(response)


def fetch_doi_metadata(
    doi: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Mapping[str, Any] | None:
    """Return DOI registry metadata for ``doi``, else None.

    Crossref is queried first; whenever it does not return metadata (unknown
    DOI, network trouble, non-JSON body) the doi.org content-negotiation
    endpoint is tried as the second registry.  Every failure mode — timeout,
    HTTP error, non-JSON body — collapses to None so callers keep the
    fail-closed receipt.
    """

    normalized = normalize_doi(doi)
    if not normalized:
        return None
    timeout = max(0.5, float(timeout_seconds))
    metadata = _crossref_metadata(normalized, timeout)
    if metadata is not None:
        return metadata
    return _doi_org_metadata(normalized, timeout)


def verify_failed_receipt_dois(
    checks: Sequence[Mapping[str, Any]],
    *,
    verifier: Callable[[str], Mapping[str, Any] | None] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_verifications: int = DEFAULT_MAX_VERIFICATIONS,
) -> dict[str, Any]:
    """Verify failing citation receipts against DOI registry metadata.

    Only receipts whose ``status`` is not ``passed`` and whose ``sourceUrl``
    (or ``doi`` hint) resolves to a DOI are verified, up to
    ``max_verifications`` network attempts.  Returns a report::

        {
            "verifiedSourceUrls": {url: True, ...},   # DOI confirmed only
            "attemptedCount": int,                    # network attempts made
            "verifiedCount": int,
            "unresolvedSourceUrls": [url, ...],       # attempted but unconfirmed
        }

    Callers merge ``verifiedSourceUrls`` into their receipt projection; this
    function never mutates receipts and never raises on network trouble.
    """

    verify = verifier if verifier is not None else default_doi_verifier
    use_timeout = verifier is None and timeout_seconds != DEFAULT_TIMEOUT_SECONDS
    verified: dict[str, bool] = {}
    unresolved: list[str] = []
    attempted = 0
    for item in checks:
        if not isinstance(item, Mapping):
            continue
        source_url = str(item.get("sourceUrl") or item.get("source_url") or "").strip()
        if not source_url or source_url in verified:
            continue
        if str(item.get("status") or "").lower() == "passed":
            continue
        doi = extract_doi(source_url, item.get("doi"))
        if not doi:
            continue  # no DOI authority -> keep failed, no network attempt
        if attempted >= max_verifications:
            break
        attempted += 1
        try:
            if use_timeout:
                metadata = fetch_doi_metadata(doi, timeout_seconds=timeout_seconds)
            else:
                metadata = verify(doi)
        except Exception:  # noqa: BLE001 - injected verifiers may raise too
            metadata = None
        if metadata is not None:
            verified[source_url] = True
        else:
            unresolved.append(source_url)
    return {
        "verifiedSourceUrls": verified,
        "attemptedCount": attempted,
        "verifiedCount": len(verified),
        "unresolvedSourceUrls": unresolved,
    }


__all__ = [
    "DEFAULT_MAX_VERIFICATIONS",
    "DEFAULT_TIMEOUT_SECONDS",
    "extract_doi",
    "fetch_doi_metadata",
    "normalize_doi",
    "verify_failed_receipt_dois",
]
