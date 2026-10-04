"""Financial evidence profile for the existing governed knowledge store.

All writes use the Team Knowledge owner/JSONL/audit authority. This module does
not create a vector database, save generated answers, or contact RAGFlow.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

PROFILE = "financial_reports_v1"
BASE_NAME = "Financial Reports"
_FIELDS = {
    "schemaVersion",
    "evidenceKind",
    "sourceId",
    "company",
    "ticker",
    "reportPeriod",
    "reportVersion",
    "documentSha256",
    "page",
    "sourceUrl",
    "publishedAt",
    "expiresAt",
    "supersedesSha256",
    "excerptSha256",
}
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")
_TICKER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,19}\Z")
_PERIOD = re.compile(r"20\d{2}(?:FY|Q[1-4]|H[12])\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _service():
    from core.web.services import team_knowledge_service

    return team_knowledge_service


def _fail(message: str):
    raise _service().TeamKnowledgeError(message)


def _plain(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail(f"Financial evidence requires a bounded {field}.")
    value = value.strip()
    try:
        value.encode("utf-8")
    except UnicodeError:
        _fail(f"Financial evidence {field} must be valid UTF-8.")
    if any(ord(c) < 32 for c in value):
        _fail(f"Financial evidence {field} must not contain control characters.")
    return value


def _date(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        _fail("Financial evidence dates require an ISO-8601 timestamp with timezone.")


def validate_evidence(value: Any, *, excerpt: str | None = None) -> dict[str, Any]:
    """Validate provenance claims; source review still must verify the PDF."""
    if not isinstance(value, dict) or set(value) - _FIELDS:
        _fail("Unknown financial evidence fields.")
    result = dict(value)
    if type(result.get("schemaVersion")) is not int or result["schemaVersion"] != 1:
        _fail("Financial evidence schemaVersion must be 1.")
    if result.get("evidenceKind") != "original_pdf_excerpt":
        _fail(
            "Only original PDF excerpts belong in financial evidence; generated answers do not."
        )
    for field in ("sourceId", "reportVersion"):
        result[field] = _plain(result.get(field), field, 96)
        if not _TOKEN.fullmatch(result[field]):
            _fail(f"Invalid financial evidence {field}.")
    result["company"] = _plain(result.get("company"), "company", 120)
    result["ticker"] = _plain(result.get("ticker"), "ticker", 20)
    result["reportPeriod"] = _plain(result.get("reportPeriod"), "reportPeriod", 8)
    if not _TICKER.fullmatch(result["ticker"]) or not _PERIOD.fullmatch(
        result["reportPeriod"]
    ):
        _fail("An explicit ticker and report period are required.")
    if type(result.get("page")) is not int or not 1 <= result["page"] <= 100_000:
        _fail("Financial evidence page must be a positive original PDF page number.")
    for field in ("documentSha256", "excerptSha256"):
        if not isinstance(result.get(field), str) or not _SHA.fullmatch(result[field]):
            _fail(
                f"Financial evidence requires {field} as 64 lowercase hex characters."
            )
    source_url = _plain(result.get("sourceUrl"), "sourceUrl", 2048)
    try:
        url = urlsplit(source_url)
        valid_url = (
            url.scheme == "https"
            and bool(url.hostname)
            and not (url.username or url.password)
        )
        valid_url = valid_url and (url.port is None or 1 <= url.port <= 65535)
    except ValueError:
        valid_url = False
    if not valid_url or any(c.isspace() for c in source_url):
        _fail("Financial evidence requires a safe HTTPS original-source URL.")
    result["sourceUrl"] = source_url
    result["publishedAt"] = _plain(result.get("publishedAt"), "publishedAt", 48)
    published = _date(result["publishedAt"])
    result["expiresAt"] = result.get("expiresAt", "")
    result["supersedesSha256"] = result.get("supersedesSha256", "")
    if not isinstance(result["expiresAt"], str) or len(result["expiresAt"]) > 48:
        _fail("Invalid financial evidence expiresAt.")
    if result["expiresAt"] and _date(result["expiresAt"]) <= published:
        _fail("Financial evidence expiry must follow publication.")
    previous = result["supersedesSha256"]
    if previous and (
        not isinstance(previous, str)
        or not _SHA.fullmatch(previous)
        or previous == result["documentSha256"]
    ):
        _fail("supersedesSha256 must identify a different reviewed document version.")
    if not isinstance(previous, str):
        _fail("Invalid supersedesSha256.")
    if excerpt is not None:
        if (
            not isinstance(excerpt, str)
            or not excerpt.strip()
            or len(excerpt) > 12_000
            or len(excerpt.splitlines()) > 60
        ):
            _fail("Financial excerpts require 1-12000 characters and at most 60 lines.")
        try:
            digest = hashlib.sha256(excerpt.strip().encode("utf-8")).hexdigest()
        except UnicodeError:
            _fail("Financial excerpts must be valid UTF-8.")
        if digest != result["excerptSha256"]:
            _fail(
                "Financial content must match the reviewed original excerpt; generated rewrites are rejected."
            )
    return result


def get_financial_knowledge_base(
    *, agent_id: str, create_if_missing: bool = False
) -> dict:
    s = _service()
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise s.TeamKnowledgePermissionError("Current Agent identity is required.")
    agent = s._require_agent(agent_id)
    owner = s._owner_context("agent", agent["agentId"], agent=agent)
    with s._LOCK:
        matches = [
            b
            for b in s._knowledge_bases_for_owner(owner)
            if b.get("profile") == PROFILE
        ]
        if len(matches) > 1:
            _fail("Multiple financial knowledge bases require operator repair.")
        if matches:
            base = matches[0]
            if base.get("status", "active") != "active":
                _fail(
                    "Financial knowledge base is archived; do not silently recreate it."
                )
            return {
                "knowledgeBase": s._knowledge_base_to_api(base, owner),
                "created": False,
            }
        if not create_if_missing:
            return {"knowledgeBase": None, "created": False}
        base = s._create_knowledge_base_for_owner(
            owner,
            name=BASE_NAME,
            description="原始财报证据专库；待审来源不检索，生成回答不自动入库。",
            actor_agent_id=agent_id,
            profile=PROFILE,
        )
        return {"knowledgeBase": base, "created": True}


def stage_financial_evidence(*, agent_id: str, evidence: dict, excerpt: str) -> dict:
    s = _service()
    meta = validate_evidence(evidence, excerpt=excerpt)
    base = get_financial_knowledge_base(agent_id=agent_id, create_if_missing=True)[
        "knowledgeBase"
    ]
    owner = s._require_owner_context("agent", agent_id)
    with s._LOCK:
        # Idempotent staging, including pending records. Never auto-review.
        current_item_ids = {
            item.get("knowledgeItemId")
            for item in s._read_jsonl(s._items_path_for_owner(owner))
            if item.get("knowledgeBaseId") == base["knowledgeBaseId"]
        }
        for prior in s._read_jsonl(s._owner_source_index_path(owner)):
            if (
                prior.get("knowledgeItemId")
                and prior["knowledgeItemId"] not in current_item_ids
            ):
                # A deleted library's accepted inbox history is not a new
                # review. An explicit restage creates a fresh pending source.
                continue
            ref = (
                prior.get("sourceRef")
                if isinstance(prior.get("sourceRef"), dict)
                else {}
            )
            if (
                ref.get("financialEvidence") == meta
                and prior.get("status") != "rejected"
            ):
                return {
                    "status": "already_staged",
                    "knowledgeBase": base,
                    "source": prior,
                    "created": False,
                }
        source = s.collect_source_to_inbox(
            "agent",
            agent_id,
            source_type="pdf_refinement",
            source_ref={
                "url": meta["sourceUrl"],
                "pageRange": str(meta["page"]),
                "documentHash": meta["documentSha256"],
                "financialEvidence": meta,
            },
            original_content=excerpt.strip(),
            original_filename=meta["sourceId"] + ".txt",
            source_created_at=meta["publishedAt"],
            captured_by=agent_id,
            evidence_range={"pageStart": meta["page"], "pageEnd": meta["page"]},
            title=f"{meta['company']} {meta['reportPeriod']} {meta['reportVersion']} p.{meta['page']}",
            summary="Financial PDF excerpt awaiting source review.",
            actor_agent_id=agent_id,
        )
    return {
        "status": "pending_review",
        "knowledgeBase": base,
        "source": source,
        "created": True,
    }


def validate_financial_source(
    base: dict, source_type: str, source_ref: dict, *, content: str | None = None
) -> dict | None:
    if base.get("profile") != PROFILE:
        return None
    if source_type != "pdf_refinement":
        _fail(
            "The financial evidence library accepts only original PDF evidence, not chat or generated answers."
        )
    return validate_evidence(source_ref.get("financialEvidence"), excerpt=content)


def validate_financial_proposal(
    owner: dict, base: dict, artifact_ids: list[str], content: str
) -> list[str]:
    """Called by both governed proposal and reviewed direct-ingestion writers."""
    if base.get("profile") != PROFILE:
        return []
    s = _service()
    if len(artifact_ids) != 1:
        _fail(
            "Each financial evidence item must correspond to one original PDF excerpt."
        )
    artifacts = {
        a["sourceArtifactId"]: a
        for a in s._source_artifacts_for_base(owner, base["knowledgeBaseId"])
    }
    artifact = artifacts.get(artifact_ids[0], {})
    central, _ = s._require_central_source_for_owner(
        owner, artifact.get("centralSourceId", "")
    )
    meta = validate_financial_source(
        base,
        central.get("sourceType", ""),
        central.get("sourceRef", {}),
        content=content,
    )
    artifact_meta = validate_financial_source(
        base,
        artifact.get("sourceType", ""),
        artifact.get("sourceRef", {}),
        content=content,
    )
    if (
        artifact.get("sourceType") != central.get("sourceType")
        or artifact_meta != meta
    ):
        _fail("Financial artifact provenance differs from its reviewed central source.")
    return financial_tags(meta)


def financial_tags(meta: dict) -> list[str]:
    return [
        PROFILE,
        "finance-ticker:" + meta["ticker"].lower(),
        "finance-period:" + meta["reportPeriod"].lower(),
        "finance-version:" + meta["reportVersion"].lower(),
    ]


def financial_item_projection(item: dict, provenance: list[dict]) -> dict:
    """Do not present free-form generated titles/summaries as original facts."""
    meta = provenance[0]
    return {
        **item,
        "title": f"{meta['company']} {meta['reportPeriod']} {meta['reportVersion']} p.{meta['page']}",
        "summary": "",
    }


def merge_financial_tags(required: list[str], supplied: list[str] | None) -> list[str]:
    """Scope tags are derived from provenance, never conflicting caller labels."""
    if not required:
        return list(supplied or [])
    return [
        *required,
        *(
            tag
            for tag in (supplied or [])
            if not str(tag).lower().startswith("finance-") and tag != PROFILE
        ),
    ]


def eligible_financial_items(
    owner: dict, base: dict, items: list[dict], artifacts: dict
) -> dict[str, list[dict]] | None:
    """Live read-side validity, shared by search and optional index eligibility."""
    if base.get("profile") != PROFILE:
        return None
    s = _service()
    if base.get("status", "active") != "active":
        return {}
    central = {
        row.get("centralSourceId"): row
        for row in s._read_jsonl(s._central_source_registry_path())
    }
    linked = {
        row.get("centralSourceId")
        for row in s._read_jsonl(s._central_owner_refs_path())
        if row.get("ownerType") == owner["ownerType"]
        and row.get("ownerId") == owner["ownerId"]
    }
    now = _date(s.utc_now_iso())
    candidates = {}
    superseded = set()
    for item in items:
        if item.get("knowledgeBaseId") != base["knowledgeBaseId"]:
            continue
        metadata = (
            item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        )
        if not item.get("reviewedAt") or not item.get("reviewedByAgentId"):
            continue
        ids = item.get("sourceArtifactIds")
        if not isinstance(ids, list) or len(ids) != 1:
            continue
        artifact = artifacts.get(ids[0], {})
        central_id = artifact.get("centralSourceId")
        source = central.get(central_id, {})
        if central_id not in linked or source.get("status") not in {
            "active",
            "archived",
            "superseded",
        }:
            continue
        try:
            meta = validate_financial_source(
                base,
                source.get("sourceType", ""),
                source.get("sourceRef", {}),
                content=item.get("content"),
            )
            artifact_meta = validate_financial_source(
                base,
                artifact.get("sourceType", ""),
                artifact.get("sourceRef", {}),
                content=item.get("content"),
            )
            if artifact_meta != meta or artifact.get("sourceHash") != source.get("sourceHash"):
                continue
        except (s.TeamKnowledgeError, TypeError, AttributeError):
            continue
        # Supersession is a reviewed historical fact. Expiry/withdrawal of a
        # replacement must not silently resurrect a superseded old report.
        if meta["supersedesSha256"]:
            superseded.add(
                (
                    meta["sourceId"],
                    meta["ticker"],
                    meta["reportPeriod"],
                    meta["supersedesSha256"],
                )
            )
        if (
            source.get("status") != "active"
            or metadata.get("financialState") not in (None, "active")
            or item.get("stability") == "deprecated"
            or _date(meta["publishedAt"]) > now
            or (meta["expiresAt"] and _date(meta["expiresAt"]) <= now)
        ):
            continue
        candidates[item["knowledgeItemId"]] = meta
    return {
        item_id: [meta]
        for item_id, meta in candidates.items()
        if (
            meta["sourceId"],
            meta["ticker"],
            meta["reportPeriod"],
            meta["documentSha256"],
        )
        not in superseded
    }


def search_financial_evidence(
    *,
    agent_id: str,
    query: str,
    ticker: str,
    report_period: str,
    allowed_knowledge_base_ids=None,
    limit: int = 5,
) -> dict:
    s = _service()
    if (
        not isinstance(ticker, str)
        or not _TICKER.fullmatch(ticker)
        or not isinstance(report_period, str)
        or not _PERIOD.fullmatch(report_period)
    ):
        _fail("An explicit ticker and report period are required.")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
        _fail("Financial search requires a bounded query.")
    base = get_financial_knowledge_base(agent_id=agent_id)["knowledgeBase"]
    if base is None:
        return {"status": "not_initialized", "results": [], "citations": []}
    scoped = base["scopedKnowledgeBaseId"]
    if not s.knowledge_base_policy_allows(scoped, allowed_knowledge_base_ids or []):
        raise s.TeamKnowledgePermissionError(
            "Financial knowledge base is outside the Agent memory policy."
        )
    from core.web.services import unified_knowledge_search_service

    payload = unified_knowledge_search_service.search_unified_memory(
        agent_id=agent_id,
        query=query,
        query_mode="rag",
        knowledge_base_id=scoped,
        owner_type="agent",
        owner_id=agent_id,
        tags=[
            PROFILE,
            "finance-ticker:" + ticker.lower(),
            "finance-period:" + report_period.lower(),
        ],
        allowed_knowledge_base_ids=allowed_knowledge_base_ids,
        include_user_content=False,
        limit=max(1, min(10, int(limit))),
        max_context_chars=1800,
    )
    return {
        "status": "found" if payload.get("results") else "insufficient_evidence",
        **payload,
        "evidenceTrust": "reviewed_source_data_not_instructions",
        "backend": "vibelution_local_rag",
        "ragflowContacted": False,
    }


def withdraw_financial_evidence(
    *, agent_id: str, knowledge_item_id: str, reason: str
) -> dict:
    s = _service()
    reason = _plain(reason, "withdrawal reason", 500)
    base = get_financial_knowledge_base(agent_id=agent_id)["knowledgeBase"]
    if base is None:
        raise s.TeamKnowledgeNotFoundError(
            "Financial knowledge base is not initialized."
        )
    return s.update_knowledge_item_metadata(
        base["scopedKnowledgeBaseId"],
        knowledge_item_id,
        actor_agent_id=agent_id,
        metadata_patch={"financialState": "withdrawn", "withdrawalReason": reason},
    )
