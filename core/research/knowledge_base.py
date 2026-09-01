"""Persistent research knowledge base for AI Scientist workflows."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from core.infrastructure.workspace_manager import get_workspace

from .models import ResearchDiscoverySession, ResearchSource, utcnow_iso


# Every reader and writer of knowledge_base.json lives inside the backend
# process, so an in-process RLock is sufficient for read-modify-write mutual
# exclusion (no filelock dependency). External handles that ignore in-process
# locks (AV scanners, indexers holding the target open across a restart
# window) are covered by the PermissionError backoff retry in
# ``ResearchKnowledgeBase._replace_atomically``.
_LOCK = threading.RLock()
_REPLACE_RETRY_BACKOFF_SECONDS = (0.05, 0.1, 0.2, 0.4)


class KnowledgeBaseWriteError(RuntimeError):
    """Raised when the knowledge base file cannot be atomically replaced."""


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}")
_STOPWORDS = {
    "about",
    "after",
    "agent",
    "based",
    "benchmark",
    "current",
    "data",
    "evidence",
    "from",
    "into",
    "method",
    "model",
    "open",
    "paper",
    "public",
    "research",
    "science",
    "scientist",
    "source",
    "study",
    "system",
    "that",
    "this",
    "with",
}
_KIND_CATEGORY = {
    "paper": "literature",
    "github": "open_source",
    "dataset": "dataset",
    "web": "web_background",
}


class ResearchKnowledgeBase:
    """JSON-backed cross-session store for research sources and distilled metadata."""

    def __init__(self, path: Path | None = None):
        if path is None:
            workspace = get_workspace()
            path = workspace.research_dir() / "knowledge_base.json"
        self.path = path.resolve()

    def payload(self, *, query: str = "", kind: str = "", category: str = "", limit: int = 100) -> dict[str, Any]:
        library = self._read()
        entries = self._filter_entries(library["entries"], query=query, kind=kind, category=category, limit=limit)
        visible_claims = self._filter_cognitive_records(library["claims"], query=query, limit=limit)
        visible_evidence = self._filter_cognitive_records(library["evidence"], query=query, limit=limit)
        visible_gaps = self._filter_cognitive_records(library["gaps"], query=query, limit=limit)
        summary = self._summary(
            library["entries"],
            entries,
            claims=library["claims"],
            evidence=library["evidence"],
            gaps=library["gaps"],
            visible_claims=visible_claims,
            visible_evidence=visible_evidence,
            visible_gaps=visible_gaps,
        )
        return {
            **library,
            "path": str(self.path),
            "entries": entries,
            "claims": visible_claims,
            "evidence": visible_evidence,
            "gaps": visible_gaps,
            "summary": summary,
            "agentContext": self._agent_context(entries, summary),
        }

    def ingest_sources(
        self,
        *,
        session: ResearchDiscoverySession,
        phase: str,
        sources: Iterable[ResearchSource],
        search_run: Any | None = None,
    ) -> dict[str, Any]:
        # Read-modify-write must be atomic: concurrent ingestion runs
        # (parallel theme-discovery phases) would otherwise lose entries via
        # last-writer-wins on the shared JSON file.
        with _LOCK:
            library = self._read()
            entries: list[dict[str, Any]] = [dict(item) for item in library["entries"]]
            claims: list[dict[str, Any]] = [dict(item) for item in library["claims"]]
            evidence_records: list[dict[str, Any]] = [dict(item) for item in library["evidence"]]
            gaps: list[dict[str, Any]] = [dict(item) for item in library["gaps"]]
            by_key = {_entry_key(item): index for index, item in enumerate(entries)}
            claim_keys = {str(item.get("dedupeKey") or "") for item in claims}
            evidence_keys = {str(item.get("dedupeKey") or "") for item in evidence_records}
            gap_keys = {str(item.get("dedupeKey") or "") for item in gaps}
            added = 0
            updated = 0
            now = utcnow_iso()
            for source in sources:
                entry = _entry_from_source(source, session=session, phase=phase, search_run=search_run, now=now)
                key = _entry_key(entry)
                index = by_key.get(key)
                if index is None:
                    entries.append(entry)
                    by_key[key] = len(entries) - 1
                    added += 1
                else:
                    entries[index] = _merge_entry(entries[index], entry, now=now)
                    updated += 1
                for claim in _claims_from_entry(entry, session=session, now=now):
                    if str(claim.get("dedupeKey") or "") not in claim_keys:
                        claims.append(claim)
                        claim_keys.add(str(claim.get("dedupeKey") or ""))
                for evidence in _evidence_from_entry(entry, session=session, now=now):
                    if str(evidence.get("dedupeKey") or "") not in evidence_keys:
                        evidence_records.append(evidence)
                        evidence_keys.add(str(evidence.get("dedupeKey") or ""))
                for gap in _gaps_from_entry(entry, session=session, phase=phase, now=now):
                    if str(gap.get("dedupeKey") or "") not in gap_keys:
                        gaps.append(gap)
                        gap_keys.add(str(gap.get("dedupeKey") or ""))
            library["entries"] = entries
            library["claims"] = claims
            library["evidence"] = evidence_records
            library["gaps"] = gaps
            library["hypotheses"] = _normalize_records(library.get("hypotheses") or [], "hypothesis")
            library["experiments"] = _normalize_records(library.get("experiments") or [], "experiment")
            library["agentEvolutionMemory"] = _normalize_agent_evolution_memory(library.get("agentEvolutionMemory"))
            library["updatedAt"] = now
            self._write(library)
            return {
                "added": added,
                "updated": updated,
                "total": len(entries),
                "claims": len(claims),
                "evidence": len(evidence_records),
                "gaps": len(gaps),
                "path": str(self.path),
            }

    def _read(self) -> dict[str, Any]:
        # Hold the same lock as writers for this short critical section so a
        # reader never keeps the target file handle open while a concurrent
        # writer calls os.replace (PermissionError on Windows without
        # FILE_SHARE_DELETE).
        with _LOCK:
            if self.path.exists():
                try:
                    payload = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = {}
            else:
                payload = {}
        entries = payload.get("entries") if isinstance(payload, dict) else []
        if not isinstance(entries, list):
            entries = []
        normalized_entries = [_normalize_entry(item) for item in entries if isinstance(item, dict)]
        claims = payload.get("claims") if isinstance(payload, dict) else []
        evidence = payload.get("evidence") if isinstance(payload, dict) else []
        gaps = payload.get("gaps") if isinstance(payload, dict) else []
        hypotheses = payload.get("hypotheses") if isinstance(payload, dict) else []
        experiments = payload.get("experiments") if isinstance(payload, dict) else []
        return {
            "schemaVersion": 2,
            "updatedAt": str(payload.get("updatedAt") or utcnow_iso()) if isinstance(payload, dict) else utcnow_iso(),
            "entries": normalized_entries,
            "claims": _normalize_records(claims, "claim"),
            "evidence": _normalize_records(evidence, "evidence"),
            "gaps": _normalize_records(gaps, "gap"),
            "hypotheses": _normalize_records(hypotheses, "hypothesis"),
            "experiments": _normalize_records(experiments, "experiment"),
            "agentEvolutionMemory": _normalize_agent_evolution_memory(
                payload.get("agentEvolutionMemory") if isinstance(payload, dict) else {}
            ),
        }

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            self._replace_atomically(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def _replace_atomically(self, temp_path: str) -> None:
        # Windows os.replace raises PermissionError (instead of swapping) when
        # an external process holds the target open without FILE_SHARE_DELETE;
        # such handles ignore in-process locks, so back off and retry, then
        # surface a structured error instead of failing silently.
        last_error: PermissionError | None = None
        attempts = 1 + len(_REPLACE_RETRY_BACKOFF_SECONDS)
        for backoff in (0.0, *_REPLACE_RETRY_BACKOFF_SECONDS):
            if backoff:
                time.sleep(backoff)
            try:
                os.replace(temp_path, self.path)
                return
            except PermissionError as error:
                last_error = error
        raise KnowledgeBaseWriteError(
            f"failed to replace knowledge base file '{self.path}' after {attempts} attempts"
        ) from last_error

    def _filter_entries(
        self,
        entries: list[dict[str, Any]],
        *,
        query: str,
        kind: str,
        category: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        normalized_query = str(query or "").strip().lower()
        normalized_kind = str(kind or "").strip().lower()
        normalized_category = str(category or "").strip().lower()
        result: list[dict[str, Any]] = []
        for entry in sorted(entries, key=lambda item: str(item.get("lastSeenAt") or ""), reverse=True):
            if normalized_kind and entry.get("kind") != normalized_kind:
                continue
            categories = [str(item).lower() for item in entry.get("categories") or []]
            if normalized_category and normalized_category not in categories:
                continue
            haystack = " ".join(
                [
                    str(entry.get("title") or ""),
                    str(entry.get("summary") or ""),
                    " ".join(str(item) for item in entry.get("tags") or []),
                ]
            ).lower()
            if normalized_query and normalized_query not in haystack:
                continue
            result.append(entry)
            if len(result) >= max(1, min(500, int(limit or 100))):
                break
        return result

    def _filter_cognitive_records(
        self,
        records: list[dict[str, Any]],
        *,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        normalized_query = str(query or "").strip().lower()
        result: list[dict[str, Any]] = []
        for record in sorted(records, key=lambda item: str(item.get("createdAt") or ""), reverse=True):
            haystack = " ".join(
                [
                    str(record.get("content") or ""),
                    str(record.get("summary") or ""),
                    str(record.get("status") or ""),
                    " ".join(str(item) for item in record.get("tags") or []),
                ]
            ).lower()
            if normalized_query and normalized_query not in haystack:
                continue
            result.append(record)
            if len(result) >= max(1, min(500, int(limit or 100))):
                break
        return result

    def _summary(
        self,
        all_entries: list[dict[str, Any]],
        visible_entries: list[dict[str, Any]],
        *,
        claims: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        gaps: list[dict[str, Any]],
        visible_claims: list[dict[str, Any]],
        visible_evidence: list[dict[str, Any]],
        visible_gaps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        kind_counts = Counter(str(item.get("kind") or "unknown") for item in all_entries)
        category_counts = Counter(
            category
            for item in all_entries
            for category in [str(value) for value in item.get("categories") or []]
            if category
        )
        return {
            "entryCount": len(all_entries),
            "visibleCount": len(visible_entries),
            "kindCounts": dict(kind_counts),
            "categoryCounts": dict(category_counts),
            "claimCount": len(claims),
            "visibleClaimCount": len(visible_claims),
            "evidenceCount": len(evidence),
            "visibleEvidenceCount": len(visible_evidence),
            "gapCount": len(gaps),
            "visibleGapCount": len(visible_gaps),
        }

    def _agent_context(self, entries: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
        recent_queries = _unique_strings(
            query
            for entry in entries[:30]
            for query in [str(item) for item in entry.get("queries") or []]
            if query
        )[:24]
        recent_sources = [
            {
                "knowledgeId": entry.get("knowledgeId"),
                "kind": entry.get("kind"),
                "title": entry.get("title"),
                "url": entry.get("url"),
                "lastSeenAt": entry.get("lastSeenAt"),
                "hitCount": entry.get("hitCount"),
                "tags": (entry.get("tags") or [])[:8],
            }
            for entry in entries[:12]
        ]
        return {
            "purpose": "Use this before web search to avoid repeating known sources and to identify evidence gaps.",
            "entryCount": summary["entryCount"],
            "visibleCount": summary["visibleCount"],
            "claimCount": summary.get("claimCount", 0),
            "evidenceCount": summary.get("evidenceCount", 0),
            "gapCount": summary.get("gapCount", 0),
            "recentQueries": recent_queries,
            "recentSources": recent_sources,
            "cognitiveLayers": ["source", "claim", "evidence", "gap", "hypothesis", "experiment", "agent_evolution_memory"],
            "reusePolicy": "Prefer reusing high-hit or recently seen entries; only search the web when the knowledge base has no matching source, stale evidence, or missing source kinds.",
        }


def _entry_from_source(
    source: ResearchSource,
    *,
    session: ResearchDiscoverySession,
    phase: str,
    search_run: Any | None,
    now: str,
) -> dict[str, Any]:
    categories = [_KIND_CATEGORY.get(source.kind, "uncategorized")]
    if phase:
        categories.append(f"phase_{phase}")
    tags = _tags_for_source(source, session=session)
    key = _source_key(source.kind, source.url, source.title)
    provider = str(getattr(search_run, "provider", "") or "")
    queries = [str(item) for item in (getattr(search_run, "queries", []) or []) if str(item).strip()]
    provenance = _provenance_from_source(
        source,
        phase=phase,
        provider=provider,
        queries=queries,
        seen_at=now,
    )
    return {
        "knowledgeId": f"rk-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}",
        "dedupeKey": key,
        "kind": source.kind,
        "title": source.title,
        "url": source.url,
        "summary": source.snippet,
        "reliability": source.reliability,
        "categories": _unique_strings(categories),
        "tags": tags,
        "sourceIds": [source.source_id],
        "sessionIds": [session.session_id],
        "searchRunIds": [source.search_run_id],
        "phases": _unique_strings([phase]),
        "providers": _unique_strings([provider]),
        "queries": _unique_strings(queries),
        "provenance": [provenance],
        "firstSeenAt": now,
        "lastSeenAt": now,
        "firstRetrievedAt": source.retrieved_at,
        "lastRetrievedAt": source.retrieved_at,
        "hitCount": 1,
        "metadata": {
            "openGoal": session.open_goal[:800],
            "constraints": session.constraints[:800],
            "preferences": session.preferences[:800],
        },
    }


def _merge_entry(current: dict[str, Any], incoming: dict[str, Any], *, now: str) -> dict[str, Any]:
    provenance = _merge_provenance(current.get("provenance") or [], incoming.get("provenance") or [])
    return {
        **current,
        "dedupeKey": current.get("dedupeKey") or incoming.get("dedupeKey"),
        "title": incoming.get("title") or current.get("title"),
        "summary": incoming.get("summary") or current.get("summary"),
        "reliability": _stronger_reliability(str(current.get("reliability") or ""), str(incoming.get("reliability") or "")),
        "categories": _unique_strings([*(current.get("categories") or []), *(incoming.get("categories") or [])]),
        "tags": _unique_strings([*(current.get("tags") or []), *(incoming.get("tags") or [])])[:24],
        "sourceIds": _unique_strings([*(current.get("sourceIds") or []), *(incoming.get("sourceIds") or [])]),
        "sessionIds": _unique_strings([*(current.get("sessionIds") or []), *(incoming.get("sessionIds") or [])]),
        "searchRunIds": _unique_strings([*(current.get("searchRunIds") or []), *(incoming.get("searchRunIds") or [])]),
        "phases": _unique_strings([*(current.get("phases") or []), *(incoming.get("phases") or [])]),
        "providers": _unique_strings([*(current.get("providers") or []), *(incoming.get("providers") or [])]),
        "queries": _unique_strings([*(current.get("queries") or []), *(incoming.get("queries") or [])])[:80],
        "provenance": provenance[-80:],
        "lastSeenAt": now,
        "firstRetrievedAt": current.get("firstRetrievedAt") or incoming.get("firstRetrievedAt"),
        "lastRetrievedAt": incoming.get("lastRetrievedAt") or current.get("lastRetrievedAt"),
        "hitCount": int(current.get("hitCount") or 1) + 1,
    }


def _normalize_entry(item: dict[str, Any]) -> dict[str, Any]:
    key = _source_key(str(item.get("kind") or ""), str(item.get("url") or ""), str(item.get("title") or ""))
    return {
        "knowledgeId": str(item.get("knowledgeId") or f"rk-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}"),
        "dedupeKey": str(item.get("dedupeKey") or key),
        "kind": str(item.get("kind") or "web").lower(),
        "title": str(item.get("title") or "Untitled source").strip()[:500],
        "url": str(item.get("url") or "").strip(),
        "summary": str(item.get("summary") or item.get("snippet") or "").strip()[:2000],
        "reliability": str(item.get("reliability") or "normal").lower(),
        "categories": _unique_strings(item.get("categories") or []),
        "tags": _unique_strings(item.get("tags") or [])[:24],
        "sourceIds": _unique_strings(item.get("sourceIds") or []),
        "sessionIds": _unique_strings(item.get("sessionIds") or []),
        "searchRunIds": _unique_strings(item.get("searchRunIds") or []),
        "phases": _unique_strings(item.get("phases") or []),
        "providers": _unique_strings(item.get("providers") or []),
        "queries": _unique_strings(item.get("queries") or [])[:80],
        "provenance": _merge_provenance([], item.get("provenance") or [])[-80:],
        "firstSeenAt": str(item.get("firstSeenAt") or utcnow_iso()),
        "lastSeenAt": str(item.get("lastSeenAt") or item.get("firstSeenAt") or utcnow_iso()),
        "firstRetrievedAt": str(item.get("firstRetrievedAt") or item.get("firstSeenAt") or utcnow_iso()),
        "lastRetrievedAt": str(item.get("lastRetrievedAt") or item.get("lastSeenAt") or utcnow_iso()),
        "hitCount": max(1, int(item.get("hitCount") or 1)),
        "metadata": dict(item.get("metadata") or {}),
    }


def _claims_from_entry(entry: dict[str, Any], *, session: ResearchDiscoverySession, now: str) -> list[dict[str, Any]]:
    summary = str(entry.get("summary") or "").strip()
    title = str(entry.get("title") or "").strip()
    content = summary or title
    if not content:
        return []
    key = f"claim|{entry.get('knowledgeId')}|source-summary"
    return [
        _normalize_record(
            {
                "recordId": f"rkc-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}",
                "dedupeKey": key,
                "type": "claim",
                "content": content[:1200],
                "summary": f"Source-level claim: {title or content[:80]}",
                "status": "extracted_from_source",
                "confidence": _confidence_for_reliability(str(entry.get("reliability") or "")),
                "sourceIds": entry.get("sourceIds") or [],
                "knowledgeIds": [entry.get("knowledgeId")],
                "sessionIds": _unique_strings([session.session_id, *(entry.get("sessionIds") or [])]),
                "evidenceIds": [],
                "claimIds": [],
                "gapIds": [],
                "tags": _unique_strings([*(entry.get("tags") or []), "claim"])[:24],
                "provenance": entry.get("provenance") or [],
                "metadata": {
                    "origin": "source_summary",
                    "kind": entry.get("kind"),
                    "url": entry.get("url"),
                },
                "createdAt": now,
                "updatedAt": now,
            },
            default_type="claim",
        )
    ]


def _evidence_from_entry(entry: dict[str, Any], *, session: ResearchDiscoverySession, now: str) -> list[dict[str, Any]]:
    key = f"evidence|{entry.get('knowledgeId')}|retrieval-provenance"
    content = str(entry.get("summary") or entry.get("title") or "").strip()
    if not content:
        content = f"Retrieved source: {entry.get('title') or entry.get('knowledgeId')}"
    return [
        _normalize_record(
            {
                "recordId": f"rke-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}",
                "dedupeKey": key,
                "type": "evidence",
                "content": content[:1200],
                "summary": "Source-level evidence from retrieval; later agents should deepen it with reading or experiments.",
                "status": "source_level_evidence",
                "confidence": _confidence_for_reliability(str(entry.get("reliability") or "")),
                "sourceIds": entry.get("sourceIds") or [],
                "knowledgeIds": [entry.get("knowledgeId")],
                "sessionIds": _unique_strings([session.session_id, *(entry.get("sessionIds") or [])]),
                "evidenceIds": [],
                "claimIds": [],
                "gapIds": [],
                "tags": _unique_strings([*(entry.get("tags") or []), "evidence"])[:24],
                "provenance": entry.get("provenance") or [],
                "metadata": {
                    "origin": "source_retrieval",
                    "kind": entry.get("kind"),
                    "url": entry.get("url"),
                    "reliability": entry.get("reliability"),
                },
                "createdAt": now,
                "updatedAt": now,
            },
            default_type="evidence",
        )
    ]


def _gaps_from_entry(
    entry: dict[str, Any],
    *,
    session: ResearchDiscoverySession,
    phase: str,
    now: str,
) -> list[dict[str, Any]]:
    if phase not in {"broad", "deep"}:
        return []
    if str(entry.get("kind") or "") not in {"paper", "github", "dataset"}:
        return []
    key = f"gap|{entry.get('knowledgeId')}|verification-needed"
    title = str(entry.get("title") or "this source").strip()
    return [
        _normalize_record(
            {
                "recordId": f"rkg-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}",
                "dedupeKey": key,
                "type": "gap",
                "content": f"Verify whether `{title}` already covers the target problem, what limitations remain, and whether it can combine with mechanisms from other fields into a new hypothesis.",
                "summary": "Source-level gap: requires close reading, comparison, and novelty checking.",
                "status": "needs_review",
                "confidence": 0.4,
                "sourceIds": entry.get("sourceIds") or [],
                "knowledgeIds": [entry.get("knowledgeId")],
                "sessionIds": _unique_strings([session.session_id, *(entry.get("sessionIds") or [])]),
                "evidenceIds": [],
                "claimIds": [],
                "gapIds": [],
                "tags": _unique_strings([*(entry.get("tags") or []), "gap", "needs_review"])[:24],
                "provenance": entry.get("provenance") or [],
                "metadata": {
                    "origin": "source_level_gap",
                    "kind": entry.get("kind"),
                    "phase": phase,
                    "openGoal": session.open_goal[:800],
                },
                "createdAt": now,
                "updatedAt": now,
            },
            default_type="gap",
        )
    ]


def _normalize_records(records: Any, default_type: str) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    return [_normalize_record(item, default_type=default_type) for item in records if isinstance(item, dict)]


def _normalize_record(item: dict[str, Any], *, default_type: str) -> dict[str, Any]:
    record_type = str(item.get("type") or default_type).strip().lower() or default_type
    content = str(item.get("content") or item.get("claim") or item.get("summary") or "").strip()[:5000]
    summary = str(item.get("summary") or _clip_text(content, 280)).strip()[:1000]
    dedupe_key = str(item.get("dedupeKey") or item.get("dedupe_key") or "").strip()
    if not dedupe_key:
        dedupe_key = f"{record_type}|{_stable_digest(content or summary or json.dumps(item, sort_keys=True, ensure_ascii=False))[:24]}"
    record_id = str(item.get("recordId") or item.get("record_id") or "").strip()
    if not record_id:
        prefix = {
            "claim": "rkc",
            "evidence": "rke",
            "gap": "rkg",
            "hypothesis": "rkh",
            "experiment": "rkx",
        }.get(record_type, "rkr")
        record_id = f"{prefix}-{_stable_digest(dedupe_key)[:16]}"
    created_at = str(item.get("createdAt") or item.get("created_at") or utcnow_iso())
    return {
        "recordId": record_id,
        "dedupeKey": dedupe_key,
        "type": record_type,
        "content": content,
        "summary": summary,
        "status": str(item.get("status") or "draft").strip().lower(),
        "confidence": _safe_confidence(item.get("confidence")),
        "sourceIds": _unique_strings(item.get("sourceIds") or item.get("source_ids") or []),
        "knowledgeIds": _unique_strings(item.get("knowledgeIds") or item.get("knowledge_ids") or []),
        "sessionIds": _unique_strings(item.get("sessionIds") or item.get("session_ids") or []),
        "evidenceIds": _unique_strings(item.get("evidenceIds") or item.get("evidence_ids") or []),
        "claimIds": _unique_strings(item.get("claimIds") or item.get("claim_ids") or []),
        "gapIds": _unique_strings(item.get("gapIds") or item.get("gap_ids") or []),
        "tags": _unique_strings(item.get("tags") or [])[:24],
        "provenance": _merge_provenance([], item.get("provenance") or [])[-80:],
        "metadata": dict(item.get("metadata") or {}),
        "createdAt": created_at,
        "updatedAt": str(item.get("updatedAt") or item.get("updated_at") or created_at),
    }


def _normalize_agent_evolution_memory(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    return {
        "schemaVersion": 1,
        "purpose": "Reserved bridge from research cognition to self-evolution experience/reflection/candidate memory.",
        "experienceRefs": _unique_strings(payload.get("experienceRefs") or []),
        "reflectionRefs": _unique_strings(payload.get("reflectionRefs") or []),
        "candidateRefs": _unique_strings(payload.get("candidateRefs") or []),
        "strategyNotes": _normalize_records(payload.get("strategyNotes") or [], "agent_strategy_note"),
    }


def _entry_key(entry: dict[str, Any]) -> str:
    return _source_key(str(entry.get("kind") or ""), str(entry.get("url") or ""), str(entry.get("title") or ""))


def _source_key(kind: str, url: str, title: str) -> str:
    normalized_url = str(url or "").strip().lower().rstrip("/")
    if normalized_url:
        return f"{str(kind or '').lower()}|{normalized_url}"
    return f"{str(kind or '').lower()}|title:{str(title or '').strip().lower()}"


def _provenance_from_source(
    source: ResearchSource,
    *,
    phase: str,
    provider: str,
    queries: list[str],
    seen_at: str,
) -> dict[str, Any]:
    return {
        "sourceId": source.source_id,
        "sessionId": source.session_id,
        "searchRunId": source.search_run_id,
        "phase": phase,
        "provider": provider,
        "queries": queries[:20],
        "retrievedAt": source.retrieved_at,
        "seenAt": seen_at,
    }


def _merge_provenance(current: Iterable[Any], incoming: Iterable[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in [*list(current), *list(incoming)]:
        if not isinstance(raw, dict):
            continue
        item = {
            "sourceId": str(raw.get("sourceId") or ""),
            "sessionId": str(raw.get("sessionId") or ""),
            "searchRunId": str(raw.get("searchRunId") or ""),
            "phase": str(raw.get("phase") or ""),
            "provider": str(raw.get("provider") or ""),
            "queries": _unique_strings(raw.get("queries") or [])[:20],
            "retrievedAt": str(raw.get("retrievedAt") or ""),
            "seenAt": str(raw.get("seenAt") or ""),
        }
        key = (item["sourceId"], item["sessionId"], item["searchRunId"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _tags_for_source(source: ResearchSource, *, session: ResearchDiscoverySession) -> list[str]:
    text = " ".join([source.title, source.snippet, session.open_goal, session.preferences])
    words = [word.lower() for word in _WORD_RE.findall(text)]
    tags: list[str] = [source.kind]
    for word, _count in Counter(word for word in words if word not in _STOPWORDS).most_common(18):
        tags.append(word)
    return _unique_strings(tags)[:20]


def _stronger_reliability(left: str, right: str) -> str:
    rank = {"weak": 0, "normal": 1, "verified": 2}
    return right if rank.get(right, 1) > rank.get(left, 1) else left or right or "normal"


def _confidence_for_reliability(reliability: str) -> float:
    normalized = str(reliability or "").strip().lower()
    if normalized == "verified":
        return 0.75
    if normalized == "weak":
        return 0.35
    return 0.55


def _safe_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _stable_digest(text: str) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()


def _clip_text(text: str, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _unique_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in result:
            result.append(item)
    return result
