"""Shared pure helpers for source-collection projections."""

from __future__ import annotations

import re
from typing import Any


def trim_text(value: Any, *, max_length: int) -> str:
    text = str(value or "").strip()
    return text[:max_length]


def source_collection_count(value: Any, *, maximum: int = 100_000) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(maximum, number))


def normalize_source_collection_stage_id(value: Any, *, default: str = "finding") -> str:
    stage_id = trim_text(value, max_length=80)
    if not stage_id:
        return default
    return stage_id


def normalize_source_collection_agent_role(value: Any) -> str:
    return trim_text(value, max_length=80)


def normalize_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        trim_text(key, max_length=80): normalize_metadata_value(item)
        for key, item in value.items()
        if trim_text(key, max_length=80)
    }


def normalize_metadata_value(value: Any) -> Any:
    if isinstance(value, str):
        return trim_text(value, max_length=1000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [normalize_metadata_value(item) for item in value[:24]]
    if isinstance(value, dict):
        return normalize_metadata(value)
    return trim_text(value, max_length=1000)


def normalize_text_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value[:max_items]:
        text = trim_text(item, max_length=max_length)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


_RESEARCH_SQUARE_VERSION_DOI = re.compile(
    r"^(10\.21203/rs\.3\.[^/\s]+?)/v([1-9]\d*)$",
    re.IGNORECASE,
)


def _source_version_doi_text(value: Any) -> str:
    text = trim_text(value, max_length=320).strip()
    if not text:
        return ""
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    match = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(0).rstrip(").,;").lower()


def source_version_family_identity(value: Any) -> dict[str, Any] | None:
    """Return a bounded version-family identity for supported versioned sources.

    The full DOI remains the record identity. This helper only adds an
    independent evidence-family identity, so append-only source records are
    never collapsed or rewritten.
    """

    doi = _source_version_doi_text(value)
    match = _RESEARCH_SQUARE_VERSION_DOI.fullmatch(doi)
    if not match:
        return None
    version = int(match.group(2))
    return {
        "familyKey": f"doi:{match.group(1).lower()}",
        "version": version,
        "versionLabel": f"v{version}",
        "sourceKind": "research_square_preprint",
        "evidencePolicy": "hypothesis_generation_only",
    }


def _candidate_source_version_identity(candidate: dict[str, Any]) -> dict[str, Any] | None:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    imported_from = (
        metadata.get("importedFromDataRecord")
        if isinstance(metadata.get("importedFromDataRecord"), dict)
        else {}
    )
    for value in (
        metadata.get("doi"),
        imported_from.get("doi"),
        metadata.get("sourceIdentityKey"),
        imported_from.get("sourceIdentityKey"),
        candidate.get("sourceUrl"),
        candidate.get("sourceRef"),
    ):
        identity = source_version_family_identity(value)
        if identity:
            return identity
    return None


def project_source_version_families(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Project source records into independent evidence families.

    Version members remain in their original order. Only the highest numeric
    Research Square version counts as the current independent source; earlier
    versions are audit-only. Other sources remain standalone.
    """

    projected = [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]
    version_groups: dict[str, list[tuple[int, dict[str, Any], dict[str, Any]]]] = {}

    for index, candidate in enumerate(projected):
        if trim_text(candidate.get("candidateType"), max_length=80) != "source_manifest":
            continue
        identity = _candidate_source_version_identity(candidate)
        if identity:
            version_groups.setdefault(str(identity["familyKey"]), []).append((index, candidate, identity))

    for family_key, members in version_groups.items():
        _current_index, current_candidate, current_identity = max(
            members,
            key=lambda item: (
                int(item[2]["version"]),
                trim_text(item[1].get("updatedAt") or item[1].get("createdAt"), max_length=80),
                trim_text(item[1].get("candidateId"), max_length=160),
            ),
        )
        current_candidate_id = trim_text(current_candidate.get("candidateId"), max_length=160)
        current_version_label = str(current_identity["versionLabel"])
        for _index, candidate, identity in members:
            is_current = candidate is current_candidate
            candidate["sourceVersionFamily"] = {
                "familyKey": family_key,
                "version": int(identity["version"]),
                "versionLabel": str(identity["versionLabel"]),
                "state": "current" if is_current else "superseded",
                "familySize": len(members),
                "currentCandidateId": current_candidate_id,
                "currentVersionLabel": current_version_label,
                "countsAsIndependentSource": is_current,
                "sourceKind": str(identity["sourceKind"]),
                "evidencePolicy": str(identity["evidencePolicy"]),
            }

    return projected, summarize_projected_source_version_families(projected)


def summarize_projected_source_version_families(
    candidates: list[dict[str, Any]],
) -> dict[str, int]:
    source_candidates = [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict)
        and trim_text(candidate.get("candidateType"), max_length=80) == "source_manifest"
    ]
    independent_source_count = sum(
        1
        for candidate in source_candidates
        if not isinstance(candidate.get("sourceVersionFamily"), dict)
        or bool(candidate["sourceVersionFamily"].get("countsAsIndependentSource"))
    )
    version_family_keys = {
        str(candidate["sourceVersionFamily"].get("familyKey") or "")
        for candidate in source_candidates
        if isinstance(candidate.get("sourceVersionFamily"), dict)
        and candidate["sourceVersionFamily"].get("version") is not None
    }
    superseded_count = sum(
        1
        for candidate in source_candidates
        if isinstance(candidate.get("sourceVersionFamily"), dict)
        and candidate["sourceVersionFamily"].get("state") == "superseded"
    )
    return {
        "sourceRecordCount": len(source_candidates),
        "independentSourceCount": independent_source_count,
        "versionFamilyCount": len(version_family_keys),
        "supersededRecordCount": superseded_count,
    }
