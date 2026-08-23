"""Normalize source-extraction results into traceable Challenge v2 evidence cards.

The formal Challenge Cup path treats an evidence card as a factual record, not
as a projection of a source URL or a free-form summary.  The canonical fields
are therefore required at this boundary and missing values fail closed.  The
old permissive projection remains available only through the explicit
``mode=\"legacy\"`` compatibility mode; production artifact construction uses
the default ``challenge_v2`` mode.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlparse


class SourceExtractionEvidenceContractError(ValueError):
    """Raised when formal source evidence is incomplete or ambiguously linked."""


_PARENT_CONTEXT_KEYS = (
    "decision",
    "evidenceStatus",
    "relevance",
)

_CHALLENGE_EVIDENCE_REQUIRED_FIELDS = (
    "title",
    "source_type",
    "source_url",
    "retrieved_at",
    "fact",
    "relation",
    "verification_status",
)

_CHALLENGE_EVIDENCE_OPTIONAL_FIELDS = ("doi", "date", "limitations")

_SOURCE_TYPES = {
    "peer_reviewed_paper",
    "preprint",
    "dataset",
    "standard",
    "official_document",
    "book",
    "other",
}

_RELATIONS = {"supports", "challenges", "context", "method", "boundary"}

_VERIFICATION_STATUSES = {
    "unverified",
    "metadata_checked",
    "full_text_checked",
    "human_verified",
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _required_text(
    item: Mapping[str, Any],
    parent: Mapping[str, Any],
    key: str,
    *,
    path: str,
    aliases: tuple[str, ...] = (),
) -> str:
    names = (key, *aliases)
    for candidate in (item, parent):
        for name in names:
            value = _text(candidate.get(name))
            if value:
                return value
    raise SourceExtractionEvidenceContractError(
        f"{path} is missing explicit {key}; URL, summary and sourceKind are not substitutes"
    )


def _optional_text(
    item: Mapping[str, Any],
    parent: Mapping[str, Any],
    key: str,
    *,
    aliases: tuple[str, ...] = (),
) -> str:
    names = (key, *aliases)
    for candidate in (item, parent):
        for name in names:
            value = _text(candidate.get(name))
            if value:
                return value
    return ""


def _string_list(value: Any, *, field: str, path: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise SourceExtractionEvidenceContractError(
            f"{path}.{field} must be an array of strings"
        )
    result: list[str] = []
    for index, raw in enumerate(value):
        text = _text(raw)
        if not text:
            raise SourceExtractionEvidenceContractError(
                f"{path}.{field}[{index}] must be a non-empty string"
            )
        if text not in result:
            result.append(text)
    return result


def _validate_url(value: str, *, path: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SourceExtractionEvidenceContractError(
            f"{path}.source_url must be an explicit https URL"
        )
    return value


def _validate_timestamp(value: str, *, path: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceExtractionEvidenceContractError(
            f"{path}.retrieved_at must be an RFC3339 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise SourceExtractionEvidenceContractError(
            f"{path}.retrieved_at must include a timezone"
        )
    return value


def _linkage(
    item: Mapping[str, Any],
    parent: Mapping[str, Any],
    *,
    path: str,
) -> dict[str, str]:
    candidate_id = _optional_text(item, parent, "candidateId")
    record_id = _optional_text(item, parent, "recordId")
    identity = candidate_id or record_id
    if not identity:
        raise SourceExtractionEvidenceContractError(
            f"{path} requires candidateId or recordId linked to a source candidate"
        )
    explicit_source_id = _optional_text(item, parent, "sourceId")
    if explicit_source_id and explicit_source_id != identity:
        raise SourceExtractionEvidenceContractError(
            f"{path}.sourceId must equal its candidateId/recordId linkage; "
            "a URL cannot be used as the source identity"
        )
    result = {
        "sourceId": explicit_source_id or identity,
    }
    if candidate_id:
        result["candidateId"] = candidate_id
    if record_id:
        result["recordId"] = record_id
    return result


def normalize_challenge_evidence_fields(
    item: Mapping[str, Any],
    parent: Mapping[str, Any] | None = None,
    *,
    path: str = "evidence",
) -> dict[str, Any]:
    """Return explicit, schema-shaped v2 fields without inventing facts.

    Shared source metadata may live on the extraction parent and per-claim
    fields may live on a nested finding.  Either location is accepted, but the
    resulting card always contains every required field.  Only spelling
    aliases (camelCase for the same explicit field) are accepted; no value is
    derived from ``sourceKind``, URL, summary, or a candidate title.
    """

    parent_mapping = parent if isinstance(parent, Mapping) else {}
    title = _required_text(item, parent_mapping, "title", path=path)
    source_type = _required_text(
        item,
        parent_mapping,
        "source_type",
        path=path,
        aliases=("sourceType",),
    )
    if source_type not in _SOURCE_TYPES:
        raise SourceExtractionEvidenceContractError(
            f"{path}.source_type must be one of {sorted(_SOURCE_TYPES)}"
        )
    source_url = _validate_url(
        _required_text(
            item,
            parent_mapping,
            "source_url",
            path=path,
            aliases=("sourceUrl",),
        ),
        path=path,
    )
    retrieved_at = _validate_timestamp(
        _required_text(
            item,
            parent_mapping,
            "retrieved_at",
            path=path,
            aliases=("retrievedAt",),
        ),
        path=path,
    )
    # A nested finding is its own evidence card.  Source metadata may be
    # shared by the extraction parent, but the factual claim must be explicit
    # on the finding itself so sibling cards cannot silently inherit one
    # generic parent fact.  Flat cards pass the same mapping as item/parent.
    fact = _required_text(item, {}, "fact", path=path)
    relation = _required_text(item, parent_mapping, "relation", path=path).lower()
    if relation not in _RELATIONS:
        raise SourceExtractionEvidenceContractError(
            f"{path}.relation must be one of {sorted(_RELATIONS)}"
        )
    verification_status = _required_text(
        item,
        parent_mapping,
        "verification_status",
        path=path,
        aliases=("verificationStatus",),
    ).lower()
    if verification_status not in _VERIFICATION_STATUSES:
        raise SourceExtractionEvidenceContractError(
            f"{path}.verification_status must be one of {sorted(_VERIFICATION_STATUSES)}"
        )

    optional: dict[str, Any] = {}
    doi = _optional_text(item, parent_mapping, "doi")
    if doi:
        optional["doi"] = doi
    date = _optional_text(
        item,
        parent_mapping,
        "date",
        aliases=("publication_date", "publicationDate"),
    )
    if date:
        optional["date"] = date
        # ``result_package_v2`` consumes the schema spelling.  Keep the
        # user-facing ``date`` too so the source extraction contract remains
        # lossless at this boundary.
        optional["publication_date"] = date
    limitations_value = None
    for candidate in (item, parent_mapping):
        if "limitations" in candidate:
            limitations_value = candidate.get("limitations")
            break
    limitations = _string_list(limitations_value, field="limitations", path=path)
    if limitations:
        optional["limitations"] = limitations

    return {
        **_linkage(item, parent_mapping, path=path),
        "title": title,
        "source_type": source_type,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "fact": fact,
        "relation": relation,
        "verification_status": verification_status,
        **optional,
    }


def _has_locator_value(locator: Mapping[str, Any]) -> bool:
    return any(value not in (None, "") for value in locator.values())


def _direct_citation_locator(item: Mapping[str, Any]) -> dict[str, Any]:
    locator: dict[str, Any] = {}
    for key in ("evidenceRef", "sourceRef", "locator", "doi"):
        value = item.get(key)
        if value not in (None, ""):
            locator[key] = value
    return locator


def _first_nested_citation_locator(item: Mapping[str, Any]) -> dict[str, Any]:
    for collection_key in ("claims", "evidenceRefs"):
        for raw in item.get(collection_key) or []:
            if not isinstance(raw, Mapping):
                continue
            explicit = raw.get("citationLocator")
            if isinstance(explicit, Mapping) and _has_locator_value(explicit):
                return dict(explicit)
            locator = _direct_citation_locator(raw)
            if _has_locator_value(locator):
                return locator
    return {}


def _source_ref_from_parent(item: Mapping[str, Any]) -> str:
    for raw in item.get("sourceRefs") or []:
        if isinstance(raw, str) and raw:
            return raw
        if isinstance(raw, Mapping):
            source_ref = _text(raw.get("sourceRef"))
            if source_ref:
                return source_ref
    return ""


def _citation_locator(item: Mapping[str, Any]) -> dict[str, Any]:
    explicit = item.get("citationLocator")
    if isinstance(explicit, Mapping) and _has_locator_value(explicit):
        return dict(explicit)
    locator = _direct_citation_locator(item)
    if _has_locator_value(locator):
        return locator

    nested_locator = _first_nested_citation_locator(item)
    if not _has_locator_value(nested_locator):
        return {}
    if "sourceRef" not in nested_locator:
        source_ref = _source_ref_from_parent(item)
        if source_ref:
            nested_locator["sourceRef"] = source_ref
    return nested_locator


def _parent_context(parent: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: parent[key]
        for key in _PARENT_CONTEXT_KEYS
        if parent.get(key) not in (None, "")
    }


def _v2_card(
    item: Mapping[str, Any],
    parent: Mapping[str, Any],
    *,
    path: str,
) -> dict[str, Any]:
    fields = normalize_challenge_evidence_fields(item, parent, path=path)
    locator = _citation_locator(item)
    if not _has_locator_value(locator):
        locator = _citation_locator(parent)
    if not _has_locator_value(locator):
        raise SourceExtractionEvidenceContractError(
            f"{path} requires an explicit citationLocator/evidence anchor"
        )
    return {
        **fields,
        # Existing artifact quality/readiness consumers still use ``claim``;
        # it is an exact alias of the explicit v2 ``fact``, never a summary.
        "claim": fields["fact"],
        "citationLocator": locator,
        **_parent_context(parent),
    }


def _source_id(item: Mapping[str, Any], parent: Mapping[str, Any]) -> str:
    for candidate in (parent, item):
        for key in ("candidateId", "recordId", "sourceId"):
            value = _text(candidate.get(key))
            if value:
                return value
    return ""


def _claim(item: Mapping[str, Any], parent: Mapping[str, Any]) -> str:
    for candidate in (item, parent):
        for key in ("claim", "finding", "conclusion", "summary", "valueSummary"):
            value = _text(candidate.get(key))
            if value:
                return value
    return ""


def _legacy_nested_cards(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    findings = [
        dict(item)
        for item in extraction.get("keyFindings") or []
        if isinstance(item, dict)
    ]
    return [
        {
            "sourceId": _source_id(finding, extraction),
            "claim": _claim(finding, extraction),
            "citationLocator": _citation_locator(finding),
            **_parent_context(extraction),
        }
        for finding in findings
    ]


def _legacy_flat_card(extraction: dict[str, Any]) -> dict[str, Any]:
    return {
        **extraction,
        "sourceId": _source_id(extraction, extraction),
        "claim": _claim(extraction, extraction),
        "citationLocator": _citation_locator(extraction),
    }


def _build_legacy_source_extraction_evidence_cards(
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("candidateExtractions", "recordExtractions"):
        for raw in result.get(key) or []:
            if not isinstance(raw, dict):
                continue
            extraction = dict(raw)
            normalized = _legacy_nested_cards(extraction) or [_legacy_flat_card(extraction)]
            for card in normalized:
                identity = json.dumps(
                    card,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                if identity in seen:
                    continue
                seen.add(identity)
                cards.append(card)
    return cards


def build_source_extraction_evidence_cards(
    result: dict[str, Any],
    *,
    mode: str = "challenge_v2",
) -> list[dict[str, Any]]:
    """Build canonical cards; legacy projection requires an explicit mode."""

    if mode == "legacy":
        return _build_legacy_source_extraction_evidence_cards(result)
    if mode != "challenge_v2":
        raise ValueError("source extraction evidence mode must be challenge_v2 or legacy")

    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("candidateExtractions", "recordExtractions"):
        for extraction_index, raw in enumerate(result.get(key) or []):
            if not isinstance(raw, Mapping):
                raise SourceExtractionEvidenceContractError(
                    f"{key}[{extraction_index}] must be an object"
                )
            extraction = dict(raw)
            findings_value = extraction.get("keyFindings")
            if isinstance(findings_value, list) and findings_value:
                for finding_index, raw_finding in enumerate(findings_value):
                    if not isinstance(raw_finding, Mapping):
                        raise SourceExtractionEvidenceContractError(
                            f"{key}[{extraction_index}].keyFindings[{finding_index}] must be an object"
                        )
                    card = _v2_card(
                        dict(raw_finding),
                        extraction,
                        path=f"{key}[{extraction_index}].keyFindings[{finding_index}]",
                    )
                    identity = json.dumps(
                        card,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    )
                    if identity not in seen:
                        seen.add(identity)
                        cards.append(card)
                continue
            cards.append(
                _v2_card(
                    extraction,
                    extraction,
                    path=f"{key}[{extraction_index}]",
                )
            )
    return cards


__all__ = [
    "SourceExtractionEvidenceContractError",
    "build_source_extraction_evidence_cards",
    "normalize_challenge_evidence_fields",
]
