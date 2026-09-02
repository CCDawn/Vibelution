"""Source-collection residual helpers still leaving the orchestration facade.

Claim scope: import local sources, search plan, exclusion ledger, work-run
persist, phase gates, agent graph, extraction metadata, prompt-cache policy,
and related SC residual bodies.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import re
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ARXIV_ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
ARXIV_SCHEMA_NAMESPACE = "http://arxiv.org/schemas/atom"


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _append_source_collection_seed(seeds: list[str], value: Any) -> None:
    s = _service()
    text = s._trim_text(value, max_length=220)
    if not text:
        return
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return
    seen = {item.lower() for item in seeds}
    if normalized.lower() not in seen:
        seeds.append(normalized)


def _build_source_collection_search_plan(
    *,
    team_id: str,
    run_id: str,
    payload: dict[str, Any],
    scope: dict[str, Any],
    input_refs: list[str],
    roles: list[str],
    prompt_cache_policy: dict[str, Any],
    plan_id: str = "",
) -> dict[str, Any]:
    s = _service()
    normalized_plan_id = s._trim_text(plan_id, max_length=128) or s._new_record_id("searchplan")
    topic = s._trim_text(scope.get("topic") or payload.get("topic"), max_length=500)
    goal = s._trim_text(scope.get("goal") or payload.get("goal"), max_length=1000)
    query_seeds = s._source_collection_query_seeds(payload, scope, input_refs, topic=topic, goal=goal)
    languages = s._source_collection_search_languages(payload.get("searchLanguages"))
    source_types = s._source_collection_source_types(payload.get("sourceTypes"))
    max_results = s._normalize_int(
        payload.get("maxResultsPerQuery"),
        default=s.SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY,
        minimum=1,
        maximum=100,
    )
    search_roles = [role for role in roles if role in s.SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES]
    role_cycle = search_roles or ["source_finder"]
    queries: list[dict[str, Any]] = []
    for seed in query_seeds:
        for source_type in source_types:
            for language in languages:
                if len(queries) >= s.SOURCE_COLLECTION_MAX_QUERIES:
                    break
                assigned_role = role_cycle[len(queries) % len(role_cycle)]
                query_id = f"{normalized_plan_id}-q{len(queries) + 1:03d}"
                queries.append(
                    {
                        "queryId": query_id,
                        "query": s._source_collection_query_text(seed, source_type=source_type, language=language),
                        "seed": seed,
                        "language": language,
                        "sourceType": source_type,
                        "assignedAgentRole": assigned_role,
                        "maxResults": max_results,
                        "status": "planned",
                        "execution": {
                            "mode": "contract_only",
                            "externalSearchTriggered": False,
                            "conversationTraceRequired": True,
                            "promptCacheRequired": prompt_cache_policy.get("requirement") in s.SOURCE_COLLECTION_PROMPT_CACHE_REQUIRED_MODES,
                            "promptCachePartition": s._source_collection_prompt_cache_partition(
                                team_id,
                                assigned_role,
                                model_id=str(prompt_cache_policy.get("modelId") or ""),
                            ),
                        },
                        "writeback": {
                            "target": "CollectionOutput.records",
                            "recordStatus": "collected",
                            "candidateImportTarget": "source_manifest",
                        },
                    }
                )
            if len(queries) >= s.SOURCE_COLLECTION_MAX_QUERIES:
                break
        if len(queries) >= s.SOURCE_COLLECTION_MAX_QUERIES:
            break
    writeback_contract = s._source_collection_writeback_contract(team_id, run_id)
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "planId": normalized_plan_id,
        "planKind": "source_collection_data_search",
        "status": "planned",
        "teamId": team_id,
        "runId": run_id,
        "topic": topic,
        "goal": goal,
        "querySeeds": query_seeds,
        "queryCount": len(queries),
        "sourceTypes": source_types,
        "searchLanguages": languages,
        "maxResultsPerQuery": max_results,
        "queries": queries,
        "promptCachePolicy": prompt_cache_policy,
        "roleAssignmentInputs": s._source_collection_role_assignment_inputs(queries, roles, payload),
        "resultWritebackContract": writeback_contract,
        "boundaries": {
            "externalSearchTriggered": False,
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesKnowledgeGraph": False,
            "requiresPromptCacheForAgentExecution": prompt_cache_policy.get("requirement") in s.SOURCE_COLLECTION_PROMPT_CACHE_REQUIRED_MODES,
        },
    }


def _clean_source_collection_stage_agent_sessions_for_new_round(
    team_id: str,
    roles: list[str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Compatibility response: project sessions are append-only and never reset."""
    del team_id, roles, payload
    return {
        "status": "not_required",
        "reason": "research_project_agent_sessions_preserved",
        "cleanedCount": 0,
        "items": [],
        "skipped": [],
    }


def _coerce_source_collection_storage_path_soft(
    source_collection_work_run: dict[str, Any],
    *,
    team_id: str,
    run_id: str,
) -> tuple[Path | None, str]:
    s = _service()
    raw_path = str(source_collection_work_run.get("storagePath") or "").strip()
    if not raw_path:
        return None, ""
    try:
        storage_path = Path(raw_path).expanduser()
    except Exception:
        return None, f"source collection storage path 无法解析（runId={run_id}）：{raw_path}"
    try:
        if not storage_path.is_absolute():
            storage_path = s._project_root() / storage_path
        storage_path = storage_path.resolve()
        project_root = s._project_root().resolve()
    except Exception:
        return None, f"source collection storage path 解析失败（runId={run_id}）：{raw_path}"
    if not storage_path.exists():
        return None, f"source collection storage path 不存在（runId={run_id}）：{storage_path}"
    if not storage_path.is_dir():
        return None, f"source collection storage path 不是目录（runId={run_id}）：{storage_path}"
    if storage_path == project_root:
        return None, f"source collection storage path 不可与主项目目录一致（runId={run_id}）。"
    try:
        storage_path.relative_to(project_root)
    except ValueError:
        return None, f"source collection storage path 不在项目目录内（runId={run_id}）：{storage_path}"
    normalized_team_id = s._trim_text(team_id, max_length=96)
    normalized_run_id = s._trim_text(run_id, max_length=96)
    if normalized_team_id and normalized_run_id:
        expected_run_directory = s._source_collection_storage_artifact_paths(
            normalized_team_id,
            normalized_run_id,
        )["runDirectory"]
        try:
            expected_resolved = expected_run_directory.resolve()
        except Exception:
            expected_resolved = expected_run_directory
        if storage_path != expected_resolved:
            return (
                None,
                "source collection storage path 与历史快照中 teamId/runId 的预期路径不一致。"
                f" expected={s._relative_path(expected_resolved)}",
            )
    return storage_path, ""


def _crossref_authors(value: Any) -> list[str]:
    s = _service()
    authors: list[str] = []
    for item in list(value or [])[:8]:
        if not isinstance(item, dict):
            continue
        name = " ".join(
            part
            for part in [
                s._trim_text(item.get("given"), max_length=80),
                s._trim_text(item.get("family"), max_length=120),
            ]
            if part
        ).strip()
        if name:
            authors.append(name)
    return authors


def _crossref_date(value: Any) -> str:
    s = _service()
    if not isinstance(value, dict):
        return ""
    date_parts = value.get("date-parts")
    if not isinstance(date_parts, list) or not date_parts:
        return ""
    first = date_parts[0]
    if not isinstance(first, list) or not first:
        return ""
    parts = [str(part).zfill(2) for part in first[:3] if isinstance(part, int)]
    if not parts:
        return ""
    if parts:
        parts[0] = parts[0].lstrip("0") or "0"
    return "-".join(parts)


def _data_record_evidence_refs(run: dict[str, Any], record: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    refs = s._normalize_ref_list(payload.get("evidenceRefs"), max_items=20)
    refs.append(
        {
            "type": "data_record",
            "id": s._trim_text(record.get("recordId"), max_length=240),
            "label": s._trim_text(record.get("title"), max_length=240) or s._trim_text(record.get("sourceRef"), max_length=240) or "DataRecord",
        }
    )
    run_id = s._trim_text(run.get("runId"), max_length=240)
    if run_id:
        refs.append({"type": "data_processing_run", "id": run_id, "label": s._trim_text(run.get("title"), max_length=240) or run_id})
    return refs[:24]


def _data_record_ref(run: dict[str, Any], record: dict[str, Any]) -> dict[str, str]:
    s = _service()
    return {
        "runId": s._trim_text(run.get("runId"), max_length=128),
        "recordId": s._trim_text(record.get("recordId"), max_length=128),
        "profileId": s._trim_text(run.get("profileId"), max_length=128),
        "sourceType": s._trim_text(record.get("sourceType"), max_length=80),
        "sourceRef": s._trim_text(record.get("sourceRef") or record.get("rawLocation"), max_length=240),
        "title": s._trim_text(record.get("title"), max_length=240),
    }


def _decorate_source_collection_work_run_snapshot(
    source_collection_work_run: dict[str, Any] | None,
    *,
    team_id: str = "",
    run_id: str = "",
    data_run_exists: bool | None = None,
) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(source_collection_work_run, dict):
        return None
    payload = dict(source_collection_work_run)
    normalized_team_id = team_id or s._trim_text(payload.get("teamId"), max_length=96)
    normalized_run_id = run_id or s._trim_text(payload.get("runId"), max_length=96)
    _, reason = s._coerce_source_collection_storage_path_soft(
        payload,
        team_id=normalized_team_id,
        run_id=normalized_run_id,
    )
    if reason:
        payload.pop("storagePath", None)
        existing_reason = str(payload.get("pathValidationError") or "").strip()
        payload["pathValidationError"] = (
            f"{existing_reason}; {reason}" if existing_reason and existing_reason != reason else reason
        )
    if normalized_run_id:
        resolved_data_run_exists = (
            data_run_exists
            if isinstance(data_run_exists, bool)
            else s._source_collection_data_run_exists(normalized_run_id)
        )
        payload["dataRunExists"] = resolved_data_run_exists
        if not resolved_data_run_exists:
            s._mark_source_collection_work_run_stale(payload, "missing_data_processing_run")
    return payload


def _find_source_candidate_by_identity_key(candidate_store: dict[str, Any], source_identity_key: str) -> dict[str, Any] | None:
    s = _service()
    if not source_identity_key:
        return None
    for candidate in list(candidate_store.get("candidates") or []):
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("candidateType") or "") != "source_manifest" or s._candidate_is_archived(candidate):
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        if source_identity_key in {
            s._trim_text(metadata.get("sourceIdentityKey"), max_length=160),
            s._trim_text(imported_from.get("sourceIdentityKey"), max_length=160),
        }:
            return candidate
    return None


def _first_crossref_text(value: Any) -> str:
    s = _service()
    if isinstance(value, list):
        for item in value:
            text = s._trim_text(item, max_length=500)
            if text:
                return html.unescape(text)
        return ""
    return html.unescape(s._trim_text(value, max_length=500))


def _import_source_collection_local_workspace_sources(
    team_id: str,
    run_id: str,
    payload: dict[str, Any],
    *,
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    s = _service()
    scan_scope = payload.get("localScanScope") if isinstance(payload.get("localScanScope"), dict) else {}
    roots = s._normalize_text_list(
        scan_scope.get("roots") or scan_scope.get("rootRefs") or s.SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_ROOTS,
        max_items=8,
        max_length=240,
    ) or list(s.SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_ROOTS)
    max_files = s._normalize_int(
        scan_scope.get("maxFiles"),
        default=s.SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_MAX_FILES,
        minimum=1,
        maximum=s.SOURCE_COLLECTION_LOCAL_SCAN_HARD_MAX_FILES,
    )
    base_root = Path(s.PROJECT_ROOT).resolve()
    candidates: list[Path] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for root_ref in roots:
        root_path = (base_root / root_ref).resolve()
        try:
            root_path.relative_to(base_root)
        except ValueError:
            skipped.append({"root": root_ref, "reason": "outside_project_root"})
            continue
        if not root_path.exists():
            skipped.append({"root": root_ref, "reason": "missing_root"})
            continue
        if root_path.is_file():
            iterable = [root_path]
        else:
            iterable = sorted(path for path in root_path.rglob("*") if path.is_file())
        for file_path in iterable:
            if len(candidates) >= max_files:
                break
            relative_parts = {part.lower() for part in file_path.relative_to(base_root).parts}
            if relative_parts & s.SOURCE_COLLECTION_LOCAL_SCAN_EXCLUDED_PARTS:
                skipped.append({"path": s._relative_path(file_path), "reason": "excluded_path"})
                continue
            if file_path.suffix.lower() not in s.SOURCE_COLLECTION_LOCAL_SCAN_EXTENSIONS:
                skipped.append({"path": s._relative_path(file_path), "reason": "unsupported_extension"})
                continue
            candidates.append(file_path)
        if len(candidates) >= max_files:
            break

    source_assignment = next(
        (
            item for item in assignments
            if isinstance(item, dict)
            and s._trim_text(item.get("agentRole"), max_length=80) in s.SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
        ),
        {},
    )
    record_payloads: list[dict[str, Any]] = []
    for file_path in candidates:
        try:
            file_bytes = file_path.read_bytes()
        except OSError as exc:
            failed.append({"path": s._relative_path(file_path), "reason": "read_failed", "error": str(exc)})
            continue
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        truncated = len(file_bytes) > s.SOURCE_COLLECTION_LOCAL_SCAN_MAX_BYTES
        sample_bytes = file_bytes[:s.SOURCE_COLLECTION_LOCAL_SCAN_MAX_BYTES]
        summary = s._source_collection_local_file_summary(file_path, sample_bytes)
        relative_path = s._relative_path(file_path)
        record_payloads.append(
            {
                "sourceType": "note" if file_path.suffix.lower() in {".md", ".txt"} else "file",
                "sourceRef": relative_path,
                # 旧 localScanScope 入口同样只写稳定非绝对 locator（§2.3/§5.1），
                # 与受管根 managed:// 同风格；仓库相对路径用 "/" 分隔。
                "rawLocation": f"project://{relative_path}",
                "title": s._source_collection_local_file_title(file_path, sample_bytes),
                "summary": summary,
                "metadata": {
                    "sourceCollectionRunId": run_id,
                    "sha256": sha256,
                    "localWorkspaceImport": {
                        "relativePath": relative_path,
                        "extension": file_path.suffix.lower(),
                        "sizeBytes": len(file_bytes),
                        "truncated": truncated,
                    },
                    "allowedForAnalysis": True,
                },
                "qualitySignals": {
                    "localWorkspaceImport": True,
                    "sizeBytes": len(file_bytes),
                    "truncated": truncated,
                },
                "collectionTrace": {
                    "sourceCollectionRunId": run_id,
                    "assignmentId": s._trim_text(source_assignment.get("assignmentId"), max_length=160),
                    "agentRole": s._trim_text(source_assignment.get("agentRole"), max_length=80) or "source_intake",
                    "agentId": s._trim_text(source_assignment.get("agentId"), max_length=160),
                    "collectionMode": "local_workspace",
                },
            }
        )

    imported: list[dict[str, Any]] = []
    created_records: list[dict[str, Any]] = []
    assignment_id = s._trim_text(source_assignment.get("assignmentId"), max_length=160)
    try:
        if assignment_id:
            output = s.data_processing_service.record_collection_output(
                run_id,
                assignment_id,
                {
                    "status": "completed",
                    "records": record_payloads,
                    "notes": f"Imported {len(record_payloads)} local workspace source files.",
                    "qualitySignals": {"localWorkspaceImport": True, "recordCount": len(record_payloads)},
                },
            )
            created_records = [item for item in list(output.get("createdRecords") or []) if isinstance(item, dict)]
        else:
            created_records = [s.data_processing_service.add_record(run_id, item) for item in record_payloads]
    except s.data_processing_service.DataProcessingError as exc:
        failed.append({"reason": "record_create_failed", "error": str(exc)})
        created_records = []

    for record in created_records:
        try:
            import_response = s.import_data_record_as_source_candidate(
                team_id,
                run_id,
                s._trim_text(record.get("recordId"), max_length=160),
                {
                    "sourcePath": s._trim_text((record.get("metadata") or {}).get("localWorkspaceImport", {}).get("relativePath") if isinstance(record.get("metadata"), dict) else "", max_length=2000),
                    "createdByAgent": s._trim_text(source_assignment.get("agentId"), max_length=160) or "source_finder",
                    "tags": ["source_collection", "local_workspace", "knowledge_expansion"],
                    "metadata": {
                        "sourceCollectionRunId": run_id,
                        "sourceCollectionLocalWorkspaceImport": True,
                        "localWorkspaceImport": (
                            record.get("metadata", {}).get("localWorkspaceImport")
                            if isinstance(record.get("metadata"), dict)
                            else {}
                        ),
                    },
                },
            )
        except s.TeamWorkflowOrchestrationError as exc:
            failed.append({"recordId": s._trim_text(record.get("recordId"), max_length=160), "reason": "candidate_import_failed", "error": str(exc)})
            continue
        candidate = import_response.get("candidate") if isinstance(import_response.get("candidate"), dict) else {}
        imported.append(
            {
                "recordId": s._trim_text(record.get("recordId"), max_length=160),
                "candidateId": s._trim_text(candidate.get("candidateId"), max_length=160),
                "created": bool(import_response.get("created")),
                "path": s._trim_text((record.get("metadata") or {}).get("localWorkspaceImport", {}).get("relativePath") if isinstance(record.get("metadata"), dict) else "", max_length=500),
            }
        )

    status = "completed" if imported and not failed else ("partial" if imported else ("failed" if failed else "empty"))
    summary = s._source_collection_local_scan_summary(status=status, imported=imported, skipped=skipped, failed=failed)
    managed_summary = s._import_source_collection_managed_root_sources(
        team_id,
        run_id,
        payload,
        assignments=assignments,
    )
    summary["managedRoots"] = managed_summary
    s._record_workflow_event(
        "source_collection.local_workspace_imported",
        team_id,
        fields={
            "runId": run_id,
            "status": status,
            "importedCount": summary["importedCount"],
            "skippedCount": summary["skippedCount"],
            "failedCount": summary["failedCount"],
        },
        level="warning" if failed else "info",
        outcome="failed" if failed and not imported else "completed",
    )
    return summary


def _load_candidate_store(team_id: str, *, run_id: str = "") -> dict[str, Any]:
    """Load the team candidate store, optionally scoped to a source-collection run.

    With ``run_id`` the owner-project store is authoritative; the active-project
    store is merged in as a read-compat fallback for candidates materialized
    under a pre-fix wrong project (owner entries win, dedup by candidateId).
    Writes stay normalized to the owner-project path.
    """

    s = _service()
    normalized_run_id = s._trim_text(run_id, max_length=160)
    path = s._candidate_store_path(team_id, normalized_run_id)
    legacy_fallback_path = s._candidate_store_path(team_id) if normalized_run_id else None
    if legacy_fallback_path and str(legacy_fallback_path) != str(path):
        merged = s._merge_candidate_store_payloads(path, legacy_fallback_path)
        if merged is not None:
            return merged
        # Neither store exists yet: seed the owner-project store below.
    elif path.exists():
        payload = s._read_json(path)
        if isinstance(payload.get("candidates"), list):
            return payload
    now = s.utc_now_iso()
    payload = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": team_id,
        "storeKind": "team_workflow_candidate_store",
        "candidates": [],
        "createdAt": now,
        "updatedAt": now,
    }
    if normalized_run_id:
        payload["sourceCollectionRunId"] = normalized_run_id
    s._write_json(path, payload)
    return payload


def _merge_candidate_store_payloads(primary_path: Path, fallback_path: Path) -> dict[str, Any] | None:
    """Owner-first merged candidate store read (compat for misplaced stores)."""

    s = _service()
    primary_payload = s._read_json(primary_path) if primary_path.exists() else {}
    fallback_payload = s._read_json(fallback_path) if fallback_path.exists() else {}
    primary_candidates = (
        list(primary_payload.get("candidates"))
        if isinstance(primary_payload.get("candidates"), list)
        else None
    )
    fallback_candidates = (
        list(fallback_payload.get("candidates"))
        if isinstance(fallback_payload.get("candidates"), list)
        else None
    )
    if primary_candidates is None and fallback_candidates is None:
        return None
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (primary_candidates or [], fallback_candidates or []):
        for item in source:
            if not isinstance(item, dict):
                continue
            candidate_id = s._trim_text(item.get("candidateId"), max_length=160)
            if candidate_id and candidate_id in seen:
                continue
            if candidate_id:
                seen.add(candidate_id)
            merged.append(item)
    payload = dict(primary_payload if primary_candidates is not None else fallback_payload)
    payload["candidates"] = merged
    return payload


def _normalize_managed_root_request(payload: dict[str, Any]) -> dict[str, Any]:
    """解析 run payload 中的受管根选择：managedSourceRoots / managedSourceRootIds。"""

    s = _service()
    selection: list[str] = []
    select_all = False
    raw = payload.get("managedSourceRoots")
    if isinstance(raw, bool):
        select_all = bool(raw)
    elif isinstance(raw, list):
        for item in raw[:32]:
            if isinstance(item, str) and s._trim_text(item, max_length=64):
                selection.append(s._trim_text(item, max_length=64).lower())
            elif isinstance(item, dict) and s._trim_text(item.get("rootId"), max_length=64):
                selection.append(s._trim_text(item.get("rootId"), max_length=64).lower())
    elif isinstance(raw, dict):
        select_all = raw.get("all") is True or raw.get("enabled") is True
        ids = raw.get("rootIds")
        if isinstance(ids, list):
            for item in ids[:32]:
                if isinstance(item, str) and s._trim_text(item, max_length=64):
                    selection.append(s._trim_text(item, max_length=64).lower())
    ids_field = payload.get("managedSourceRootIds")
    if isinstance(ids_field, list):
        for item in ids_field[:32]:
            if isinstance(item, str) and s._trim_text(item, max_length=64):
                selection.append(s._trim_text(item, max_length=64).lower())
    deduped: list[str] = []
    for root_id in selection:
        if root_id not in deduped:
            deduped.append(root_id)
    return {
        "configured": select_all or bool(deduped),
        "selectAll": select_all,
        "rootIds": deduped,
    }


def _source_collection_managed_scan_summary(
    *,
    status: str,
    roots: list[dict[str, Any]] | None = None,
    imported: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
    blocked: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    imported_items = list(imported or [])
    skipped_items = list(skipped or [])
    failed_items = list(failed or [])
    blocked_items = list(blocked or [])
    return {
        "status": status,
        "rootCount": len(list(roots or [])),
        "roots": list(roots or [])[:16],
        "importedCount": len(imported_items),
        "skippedCount": len(skipped_items),
        "failedCount": len(failed_items),
        "blockedCount": len(blocked_items),
        "imported": imported_items[:40],
        "skipped": skipped_items[:40],
        "failed": failed_items[:40],
        "blocked": blocked_items[:40],
    }


def _managed_root_title_from_parse(parse_result: dict[str, Any], display_relative: str) -> str:
    s = _service()
    for block in list(parse_result.get("blocks") or []):
        locator = str(block.get("locator") or "")
        if locator.startswith("heading:") or locator == "title" or locator.startswith("slide:1:"):
            text = s._trim_text(block.get("text"), max_length=240)
            if text:
                return text
    return s._trim_text(Path(display_relative).stem.replace("_", " "), max_length=240) or Path(display_relative).name


def _source_collection_managed_root_record_payload(
    *,
    run_id: str,
    source_assignment: dict[str, Any],
    root_entry: dict[str, Any],
    category: str,
    locator: str,
    display_relative: str,
    sha256: str,
    size_bytes: int,
    parse_result: dict[str, Any],
    zip_lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """受管根文件 → DataRecord payload；rawLocation 只写 managed:// locator。"""

    s = _service()
    from core.web.services.team_workflow.source_collection import managed_roots

    meta = parse_result.get("meta") if isinstance(parse_result.get("meta"), dict) else {}
    suffix = s._trim_text(meta.get("suffix"), max_length=24)
    allowed_evidence = managed_roots.category_allows_evidence(category)
    locations = s._normalize_text_list(
        [block.get("locator") for block in list(parse_result.get("blocks") or []) if isinstance(block, dict)],
        max_items=200,
        max_length=160,
    )
    warnings = s._normalize_text_list(parse_result.get("warnings"), max_items=16, max_length=120)
    metadata: dict[str, Any] = {
        "sourceCollectionRunId": run_id,
        "sha256": s._trim_text(sha256, max_length=128),
        "managedSourceRoot": {
            "rootId": s._trim_text(root_entry.get("rootId"), max_length=64),
            "displayName": s._trim_text(root_entry.get("displayName"), max_length=120),
            "trustClass": s._trim_text(root_entry.get("trustClass"), max_length=40),
        },
        "managedRootImport": {
            "locator": s._trim_text(locator, max_length=1000),
            "relativePath": s._trim_text(display_relative, max_length=900),
            "extension": suffix,
            "category": s._trim_text(category, max_length=60),
            "allowedForEvidence": allowed_evidence,
            "candidateOnly": not allowed_evidence,
        },
        "mimeType": s._trim_text(meta.get("magicKind"), max_length=40),
        "parserVersion": s._trim_text(meta.get("parserVersion"), max_length=60),
        "structuredLocations": locations,
        "warnings": warnings,
        "allowedForAnalysis": allowed_evidence,
    }
    if zip_lineage:
        metadata["zipLineage"] = {
            "parentSha256": s._trim_text(zip_lineage.get("parentSha256"), max_length=128),
            "parentLocator": s._trim_text(zip_lineage.get("parentLocator"), max_length=1000),
            "entryName": s._trim_text(zip_lineage.get("entryName"), max_length=400),
        }
    # 受管根内稳定身份键（不含绝对路径），让候选桥在跨 run 重复导入时去重。
    metadata["sourceIdentityKey"] = s._trim_text(
        f"managed:{root_entry.get('rootId')}:{display_relative}",
        max_length=160,
    )
    return {
        "sourceType": "note" if suffix in {".md", ".txt"} else "file",
        "sourceRef": s._trim_text(locator, max_length=1000),
        "rawLocation": s._trim_text(locator, max_length=1000),
        "title": s._managed_root_title_from_parse(parse_result, display_relative),
        "summary": s._trim_text(parse_result.get("summaryText"), max_length=4000),
        "metadata": metadata,
        "qualitySignals": {
            "managedRootImport": True,
            "sizeBytes": int(size_bytes or 0),
            "truncated": bool(meta.get("truncated")),
            "warningCount": len(warnings),
            "allowedForEvidence": allowed_evidence,
        },
        "collectionTrace": {
            "sourceCollectionRunId": run_id,
            "assignmentId": s._trim_text(source_assignment.get("assignmentId"), max_length=160),
            "agentRole": s._trim_text(source_assignment.get("agentRole"), max_length=80) or "source_intake",
            "agentId": s._trim_text(source_assignment.get("agentId"), max_length=160),
            "collectionMode": "local_workspace",
            "managedRootId": s._trim_text(root_entry.get("rootId"), max_length=64),
        },
    }


def _import_source_collection_managed_root_sources(
    team_id: str,
    run_id: str,
    payload: dict[str, Any],
    *,
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    """受管桌面资料根导入旁路（手动刷新语义，无任何后台监听）。

    - 根必须先在 managed_roots registry 登记；localPath 只存在于 registry。
    - DataRecord/候选/manifest 侧只允许 ``managed://<rootId>/<relative>`` locator。
    - blocked 文件进入结构化审计（reason+detail），绝不静默截断。
    - allowedForEvidence=false 类别产物带 candidate-only 标记（allowedForAnalysis=False）。
    """

    s = _service()
    from core.web.services.team_workflow.source_collection import local_parsing, managed_roots

    request = s._normalize_managed_root_request(payload)
    if not request["configured"]:
        return s._source_collection_managed_scan_summary(status="not_configured")

    if request["selectAll"]:
        root_ids = [
            str(entry.get("rootId") or "")
            for entry in list(managed_roots.list_managed_source_roots().get("roots") or [])
            if bool(entry.get("enabled", True))
        ]
    else:
        root_ids = request["rootIds"]

    source_assignment = next(
        (
            item for item in assignments
            if isinstance(item, dict)
            and s._trim_text(item.get("agentRole"), max_length=80) in s.SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
        ),
        {},
    )
    all_imported: list[dict[str, Any]] = []
    all_skipped: list[dict[str, Any]] = []
    all_failed: list[dict[str, Any]] = []
    all_blocked: list[dict[str, Any]] = []
    root_summaries: list[dict[str, Any]] = []

    for root_ref in root_ids[:16]:
        root_id = s._trim_text(root_ref, max_length=64).lower()
        entry = managed_roots.get_managed_source_root(root_id)
        if entry is None:
            all_skipped.append({"rootId": root_id, "reason": "root_not_registered"})
            continue
        if not bool(entry.get("enabled", True)):
            all_skipped.append({"rootId": root_id, "reason": "root_disabled"})
            continue
        try:
            root_path = Path(str(entry.get("localPath") or "")).resolve()
        except (OSError, ValueError):
            all_skipped.append({"rootId": root_id, "reason": "root_path_invalid"})
            continue
        if not root_path.is_dir():
            all_skipped.append({"rootId": root_id, "reason": "root_path_missing"})
            continue
        root_outcome = s._scan_managed_root_for_import(
            team_id,
            run_id,
            root_id=root_id,
            entry=entry,
            root_path=root_path,
            source_assignment=source_assignment,
        )
        all_imported.extend(root_outcome["imported"])
        all_skipped.extend(root_outcome["skipped"])
        all_failed.extend(root_outcome["failed"])
        all_blocked.extend(root_outcome["blocked"])
        root_summaries.append(root_outcome["summary"])
        managed_roots.mark_managed_root_scanned(root_id)

    if root_summaries:
        status = (
            "completed" if all_imported and not (all_failed or all_blocked)
            else ("partial" if all_imported else ("failed" if (all_failed or all_blocked) else "empty"))
        )
    else:
        status = "empty"
    summary = s._source_collection_managed_scan_summary(
        status=status,
        roots=root_summaries,
        imported=all_imported,
        skipped=all_skipped,
        failed=all_failed,
        blocked=all_blocked,
    )
    s._record_workflow_event(
        "source_collection.managed_root_imported",
        team_id,
        fields={
            "runId": run_id,
            "status": status,
            "rootCount": len(root_summaries),
            "importedCount": summary["importedCount"],
            "skippedCount": summary["skippedCount"],
            "failedCount": summary["failedCount"],
            "blockedCount": summary["blockedCount"],
        },
        level="warning" if all_failed or all_blocked else "info",
        outcome="failed" if (all_failed or all_blocked) and not all_imported else "completed",
    )
    return summary


def _scan_managed_root_for_import(
    team_id: str,
    run_id: str,
    *,
    root_id: str,
    entry: dict[str, Any],
    root_path: Path,
    source_assignment: dict[str, Any],
) -> dict[str, Any]:
    """扫描单个受管根：预算 → 分类 → 解析链 → DataRecord → 候选桥。"""

    s = _service()
    from core.web.services.team_workflow.source_collection import local_parsing, managed_roots

    budget = entry.get("scanBudget") if isinstance(entry.get("scanBudget"), dict) else {}
    max_files = s._normalize_int(
        budget.get("maxFiles"),
        default=managed_roots.MANAGED_SCAN_BUDGET_DEFAULTS["maxFiles"],
        minimum=1,
        maximum=managed_roots.MANAGED_SCAN_BUDGET_LIMITS["maxFiles"][1],
    )
    max_total_bytes = s._normalize_int(
        budget.get("maxTotalBytes"),
        default=managed_roots.MANAGED_SCAN_BUDGET_DEFAULTS["maxTotalBytes"],
        minimum=1,
        maximum=managed_roots.MANAGED_SCAN_BUDGET_LIMITS["maxTotalBytes"][1],
    )
    max_file_bytes = s._normalize_int(
        budget.get("maxFileBytes"),
        default=managed_roots.MANAGED_SCAN_BUDGET_DEFAULTS["maxFileBytes"],
        minimum=1,
        maximum=managed_roots.MANAGED_SCAN_BUDGET_LIMITS["maxFileBytes"][1],
    )
    allowed_types = set(entry.get("allowedTypes") or managed_roots.MANAGED_SOURCE_ROOT_ALLOWED_EXTENSIONS)

    skipped: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    selected: list[tuple[Path, str, int]] = []
    total_bytes = 0
    budget_exhausted = False
    budget_reason = ""
    try:
        iterable = sorted(path for path in root_path.rglob("*") if path.is_file())
    except OSError:
        return {
            "imported": [],
            "skipped": [{"rootId": root_id, "reason": "root_unreadable"}],
            "failed": [],
            "blocked": [],
            "summary": {"rootId": root_id, "status": "failed", "importedCount": 0, "skippedCount": 1, "failedCount": 0, "blockedCount": 0, "budgetTruncated": False, "budgetReason": ""},
        }
    for file_path in iterable:
        relative_parts = {part.lower() for part in file_path.relative_to(root_path).parts}
        if relative_parts & s.SOURCE_COLLECTION_LOCAL_SCAN_EXCLUDED_PARTS:
            continue
        relative_path = file_path.relative_to(root_path).as_posix()
        try:
            size_bytes = file_path.stat().st_size
        except OSError:
            skipped.append({"rootId": root_id, "path": relative_path, "reason": "stat_failed"})
            continue
        if budget_exhausted:
            skipped.append({"rootId": root_id, "path": relative_path, "reason": budget_reason})
            continue
        if len(selected) >= max_files:
            budget_exhausted = True
            budget_reason = "budget_max_files_exceeded"
            skipped.append({"rootId": root_id, "path": relative_path, "reason": budget_reason})
            continue
        if total_bytes + size_bytes > max_total_bytes:
            budget_exhausted = True
            budget_reason = "budget_max_total_bytes_exceeded"
            skipped.append({"rootId": root_id, "path": relative_path, "reason": budget_reason})
            continue
        if size_bytes > max_file_bytes:
            skipped.append({"rootId": root_id, "path": relative_path, "reason": "file_too_large", "sizeBytes": size_bytes})
            continue
        suffix = file_path.suffix.lower()
        if suffix not in allowed_types:
            skipped.append({"rootId": root_id, "path": relative_path, "reason": "unsupported_extension"})
            continue
        category = managed_roots.derive_managed_category(relative_path, entry.get("categoryPolicy"))
        if not managed_roots.category_enabled_by_default(category) and not s._managed_category_policy_enabled(entry, category):
            skipped.append({"rootId": root_id, "path": relative_path, "reason": "category_disabled", "category": category})
            continue
        selected.append((file_path, relative_path, size_bytes))
        total_bytes += size_bytes

    record_payloads: list[dict[str, Any]] = []
    imported: list[dict[str, Any]] = []
    for file_path, relative_path, size_bytes in selected:
        suffix = file_path.suffix.lower()
        try:
            file_bytes = file_path.read_bytes()
        except OSError as exc:
            failed.append({"rootId": root_id, "path": relative_path, "reason": "read_failed", "error": str(exc)[:200]})
            continue
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        parse_result = local_parsing.parse_local_file(file_path, suffix=suffix, allowed_extensions=allowed_types)
        if parse_result.get("status") != "parsed":
            blocked.append(
                {
                    "rootId": root_id,
                    "path": relative_path,
                    "reason": s._trim_text(parse_result.get("blockedReason"), max_length=120) or "blocked",
                    "detail": s._trim_text(parse_result.get("blockedDetail"), max_length=300),
                }
            )
            continue
        category = managed_roots.derive_managed_category(relative_path, entry.get("categoryPolicy"))
        locator = managed_roots.build_managed_locator(root_id, relative_path)
        record_payloads.append(
            s._source_collection_managed_root_record_payload(
                run_id=run_id,
                source_assignment=source_assignment,
                root_entry=entry,
                category=category,
                locator=locator,
                display_relative=relative_path,
                sha256=sha256,
                size_bytes=size_bytes,
                parse_result=parse_result,
            )
        )
        imported.append({"rootId": root_id, "path": relative_path, "locator": locator, "category": category})
        if parse_result.get("kind") == "zip":
            extracted_results = [
                item for item in list(parse_result.get("extracted") or [])
                if isinstance(item, dict) and item.get("status") == "parsed" and isinstance(item.get("parse"), dict)
            ]
            for extracted in extracted_results[:64]:
                entry_name = s._trim_text(extracted.get("entryName"), max_length=400)
                entry_locator = managed_roots.build_zip_entry_locator(root_id, relative_path, entry_name)
                record_payloads.append(
                    s._source_collection_managed_root_record_payload(
                        run_id=run_id,
                        source_assignment=source_assignment,
                        root_entry=entry,
                        category=category,
                        locator=entry_locator,
                        display_relative=f"{relative_path}!/{entry_name}",
                        sha256=s._trim_text(extracted.get("sha256"), max_length=128),
                        size_bytes=int(extracted.get("sizeBytes") or 0),
                        parse_result=extracted["parse"],
                        zip_lineage={
                            "parentSha256": sha256,
                            "parentLocator": locator,
                            "entryName": entry_name,
                        },
                    )
                )
                imported.append({"rootId": root_id, "path": f"{relative_path}!/{entry_name}", "locator": entry_locator, "category": category})

    created_records = s._create_managed_root_records(team_id, run_id, source_assignment, record_payloads)
    candidate_errors = s._bridge_managed_root_records_to_candidates(
        team_id,
        run_id,
        created_records,
        source_assignment=source_assignment,
    )
    failed.extend(candidate_errors)

    imported_count = len(imported)
    root_status = (
        "completed" if imported_count and not (failed or blocked)
        else ("partial" if imported_count else ("failed" if (failed or blocked) else "empty"))
    )
    summary = {
        "rootId": root_id,
        "displayName": s._trim_text(entry.get("displayName"), max_length=120),
        "status": root_status,
        "importedCount": imported_count,
        "skippedCount": len(skipped),
        "failedCount": len(failed),
        "blockedCount": len(blocked),
        "budgetTruncated": bool(budget_exhausted),
        "budgetReason": budget_reason,
        "scannedBytes": total_bytes,
    }
    return {"imported": imported, "skipped": skipped, "failed": failed, "blocked": blocked, "summary": summary}


def _managed_category_policy_enabled(entry: dict[str, Any], category: str) -> bool:
    """categoryPolicy 覆盖默认关闭类别的开关（enableCategories 列表）。"""

    policy = entry.get("categoryPolicy") if isinstance(entry.get("categoryPolicy"), dict) else {}
    enabled_categories = policy.get("enableCategories") if isinstance(policy.get("enableCategories"), list) else []
    return category in {str(item).strip() for item in enabled_categories}


def _create_managed_root_records(
    team_id: str,
    run_id: str,
    source_assignment: dict[str, Any],
    record_payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """分批写入 DataRecord（record_collection_output 单批上限 200）。"""

    s = _service()
    created_records: list[dict[str, Any]] = []
    assignment_id = s._trim_text(source_assignment.get("assignmentId"), max_length=160)
    batches = [record_payloads[index : index + 200] for index in range(0, len(record_payloads), 200)] or [[]]
    for batch in batches:
        try:
            if assignment_id:
                output = s.data_processing_service.record_collection_output(
                    run_id,
                    assignment_id,
                    {
                        "status": "completed",
                        "records": batch,
                        "notes": f"Imported {len(batch)} managed source root files.",
                        "qualitySignals": {"managedRootImport": True, "recordCount": len(batch)},
                    },
                )
                created_records.extend(item for item in list(output.get("createdRecords") or []) if isinstance(item, dict))
            else:
                created_records.extend(s.data_processing_service.add_record(run_id, item) for item in batch)
        except s.data_processing_service.DataProcessingError as exc:
            s._record_workflow_event(
                "source_collection.managed_root_records_failed",
                team_id,
                fields={"runId": run_id, "error": str(exc)[:200]},
                level="warning",
                outcome="failed",
            )
    return created_records


def _bridge_managed_root_records_to_candidates(
    team_id: str,
    run_id: str,
    created_records: list[dict[str, Any]],
    *,
    source_assignment: dict[str, Any],
) -> list[dict[str, Any]]:
    """受管根 DataRecord → source_manifest 候选；candidate-only 类别带标记。"""

    s = _service()
    failures: list[dict[str, Any]] = []
    for record in created_records:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        managed_import = metadata.get("managedRootImport") if isinstance(metadata.get("managedRootImport"), dict) else {}
        root_ref = metadata.get("managedSourceRoot") if isinstance(metadata.get("managedSourceRoot"), dict) else {}
        allowed_evidence = bool(managed_import.get("allowedForEvidence", True))
        locator = s._trim_text(managed_import.get("locator"), max_length=1000)
        try:
            s.import_data_record_as_source_candidate(
                team_id,
                run_id,
                s._trim_text(record.get("recordId"), max_length=160),
                {
                    "sourcePath": locator,
                    "allowedForAnalysis": allowed_evidence,
                    "createdByAgent": s._trim_text(source_assignment.get("agentId"), max_length=160) or "source_finder",
                    "tags": ["source_collection", "managed_root", "knowledge_expansion"],
                    "metadata": {
                        "sourceCollectionRunId": run_id,
                        "sourceCollectionManagedRootImport": True,
                        "managedRootImport": managed_import,
                        "candidateOnly": not allowed_evidence,
                    },
                },
            )
        except s.TeamWorkflowOrchestrationError as exc:
            failures.append(
                {
                    "rootId": s._trim_text(root_ref.get("rootId"), max_length=64),
                    "recordId": s._trim_text(record.get("recordId"), max_length=160),
                    "reason": "candidate_import_failed",
                    "error": str(exc)[:200],
                }
            )
    return failures


def _load_source_collection_exclusion_store(team_id: str) -> dict[str, Any]:
    s = _service()
    store = s._read_json(s._source_collection_exclusion_store_path(team_id))
    if not store:
        return s._source_collection_exclusion_store_default(team_id)
    entries = [item for item in list(store.get("entries") or []) if isinstance(item, dict)]
    store["schemaVersion"] = s._source_collection_count(store.get("schemaVersion")) or s.SCHEMA_VERSION
    store["teamId"] = s._trim_text(store.get("teamId"), max_length=160) or team_id
    store["entries"] = entries
    return store


def _load_stage_round_store(team_id: str) -> dict[str, Any]:
    s = _service()
    path = s._stage_round_store_path(team_id)
    if path.exists():
        payload = s._read_json(path)
        if isinstance(payload.get("rounds"), list):
            return payload
    now = s.utc_now_iso()
    payload = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": team_id,
        "storeKind": "research_stage_round_store",
        "rounds": [],
        "createdAt": now,
        "updatedAt": now,
    }
    s._write_json(path, payload)
    return payload


def _mark_source_collection_work_run_stale(payload: dict[str, Any], reason: str) -> None:
    s = _service()
    normalized_reason = s._trim_text(reason, max_length=160)
    if not normalized_reason:
        return
    reasons = [
        s._trim_text(item, max_length=160)
        for item in list(payload.get("staleReasons") or [])
        if s._trim_text(item, max_length=160)
    ]
    if normalized_reason not in reasons:
        reasons.append(normalized_reason)
    payload["staleReasons"] = reasons
    payload["staleReason"] = reasons[0]


def _new_record_id(prefix: str) -> str:
    s = _service()
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _normalize_source_collection_exclusion_reason(value: Any) -> str:
    s = _service()
    normalized = re.sub(r"[^a-z0-9]+", "_", s._trim_text(value, max_length=120).lower()).strip("_")
    aliases = {
        "no_content": "no_effective_content",
        "empty": "no_effective_content",
        "invalid": "no_effective_content",
        "exclude": "no_effective_content",
        "excluded": "no_effective_content",
        "discard": "no_effective_content",
        "discarded": "no_effective_content",
        "irrelevant": "out_of_scope",
        "topic_mismatch": "out_of_scope",
        "not_relevant": "out_of_scope",
        "not_obtainable": "unobtainable",
        "not_accessible": "unobtainable",
        "cannot_access": "unobtainable",
        "unavailable": "unobtainable",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in s.SOURCE_COLLECTION_EXCLUSION_REASONS else ""


def _normalize_source_collection_prompt_cache_requirement(raw_policy: dict[str, Any], payload: dict[str, Any]) -> str:
    s = _service()
    raw = (
        s._trim_text(raw_policy.get("requirement"), max_length=80)
        or s._trim_text(raw_policy.get("mode"), max_length=80)
        or s._trim_text(payload.get("promptCacheRequirement"), max_length=80)
        or "required_for_llm_execution"
    ).lower()
    if raw in s.SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES:
        return "disabled"
    if raw in {"advisory", "optional", "warn", "warning"}:
        return "advisory"
    return "required_for_llm_execution"


def _normalize_source_collection_roles(value: Any) -> list[str]:
    s = _service()
    raw_roles = value if isinstance(value, list) else list(s.SOURCE_COLLECTION_DEFAULT_AGENT_ROLES)
    roles: list[str] = []
    for item in raw_roles[:8]:
        role = s._normalize_source_collection_agent_role(item)
        if role in s.SOURCE_COLLECTION_AGENT_ROLES and role not in roles:
            roles.append(role)
    return roles or list(s.SOURCE_COLLECTION_DEFAULT_AGENT_ROLES)


def _persist_source_collection_work_run(
    team_id: str,
    run_id: str,
    *,
    status: str,
    current_phase: str,
    run: dict[str, Any],
    team: dict[str, Any],
    assignments: list[dict[str, Any]],
    records: list[dict[str, Any]],
    summary: str,
    active: bool,
    error: str = "",
    error_type: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    now = s.utc_now_iso()
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    assignment_summary = s._source_collection_assignment_stage_summary(assignments)
    search_plan_ref = run_scope.get("dataSearchPlanRef") if isinstance(run_scope.get("dataSearchPlanRef"), dict) else {}
    query_count = s._normalize_int(
        run_metadata.get("queryCount") or search_plan_ref.get("queryCount"),
        default=0,
        minimum=0,
        maximum=s.SOURCE_COLLECTION_MAX_QUERIES * 4,
    )
    snapshot: dict[str, Any] = {
        "runId": run_id,
        "runKind": s.SOURCE_COLLECTION_WORK_RUN_KIND,
        "kind": s.SOURCE_COLLECTION_WORK_RUN_KIND,
        "status": status,
        "currentPhase": current_phase,
        "stageType": "knowledge_collection",
        "teamId": team_id,
        "teamName": s._trim_text(team.get("name"), max_length=160) or team_id,
        "title": s._trim_text(run.get("title"), max_length=180) or "知识搜集批次",
        "topic": s._trim_text(run_scope.get("topic"), max_length=500),
        "summary": s._trim_text(summary, max_length=500),
        "currentTask": s._trim_text(summary, max_length=500),
        "assignmentCount": len(assignments),
        "openAssignmentCount": assignment_summary["openAssignmentCount"],
        "searchAssignmentCount": assignment_summary["searchAssignmentCount"],
        "searchOpenAssignmentCount": assignment_summary["searchOpenAssignmentCount"],
        "collectionAssignmentCount": assignment_summary["collectionAssignmentCount"],
        "collectionOpenAssignmentCount": assignment_summary["collectionOpenAssignmentCount"],
        "downstreamAssignmentCount": assignment_summary["downstreamAssignmentCount"],
        "downstreamOpenAssignmentCount": assignment_summary["downstreamOpenAssignmentCount"],
        "recordCount": len(records),
        "queryCount": query_count,
        "storagePath": s._source_collection_storage_artifacts(team_id, run_id)["runDirectory"],
        "updatedAt": now,
        "sourceCollection": {
            "teamId": team_id,
            "stageType": "knowledge_collection",
            "openAssignmentCount": assignment_summary["openAssignmentCount"],
            "searchAssignmentCount": assignment_summary["searchAssignmentCount"],
            "searchOpenAssignmentCount": assignment_summary["searchOpenAssignmentCount"],
            "collectionAssignmentCount": assignment_summary["collectionAssignmentCount"],
            "collectionOpenAssignmentCount": assignment_summary["collectionOpenAssignmentCount"],
            "downstreamAssignmentCount": assignment_summary["downstreamAssignmentCount"],
            "downstreamOpenAssignmentCount": assignment_summary["downstreamOpenAssignmentCount"],
            "recordCount": len(records),
            "queryCount": query_count,
        },
    }
    started_at = s._trim_text(run.get("createdAt"), max_length=80) or s._trim_text(run.get("startedAt"), max_length=80)
    if started_at:
        snapshot["startedAt"] = started_at
    if not active:
        snapshot["finishedAt"] = now
    if error:
        snapshot["error"] = s._trim_text(error, max_length=500)
    if error_type:
        snapshot["errorType"] = s._trim_text(error_type, max_length=120)
    if extra:
        snapshot.update(extra)
        source_collection = snapshot.get("sourceCollection") if isinstance(snapshot.get("sourceCollection"), dict) else {}
        source_collection.update({key: value for key, value in extra.items() if key.endswith("Count")})
        snapshot["sourceCollection"] = source_collection
    return s._source_collection_work_run_store().persist_snapshot(
        s.SOURCE_COLLECTION_WORK_RUN_KIND,
        snapshot,
        active_run_id=run_id if active else "",
    )


def _record_source_collection_exclusion(
    team_id: str,
    run: dict[str, Any],
    record: dict[str, Any],
    *,
    reason: str,
    evidence: list[str] | None = None,
    task_id: str = "",
    agent_id: str = "",
    stage_id: str = "",
    source: str = "stage_writeback",
) -> dict[str, Any]:
    s = _service()
    source_identity_key = s._source_collection_record_identity_or_record_key(record)
    if not source_identity_key:
        return {}
    normalized_reason = s._normalize_source_collection_exclusion_reason(reason) or "no_effective_content"
    now = s.utc_now_iso()
    scope = s._source_collection_exclusion_scope(run)
    record_id = s._trim_text(record.get("recordId"), max_length=160)
    run_id = s._trim_text(run.get("runId"), max_length=160)
    evidence_items = s._normalize_text_list(evidence or [], max_items=8, max_length=500)
    with s._WORKFLOW_LOCK:
        store = s._load_source_collection_exclusion_store(team_id)
        entries = [item for item in list(store.get("entries") or []) if isinstance(item, dict)]
        matched: dict[str, Any] | None = None
        for entry in entries:
            if (
                s._trim_text(entry.get("sourceIdentityKey"), max_length=240) == source_identity_key
                and s._trim_text(entry.get("scopeKey"), max_length=120) == scope["scopeKey"]
            ):
                matched = entry
                break
        if matched is None:
            matched = {
                "exclusionId": s._new_record_id("srcexcl"),
                "sourceIdentityKey": source_identity_key,
                "scope": scope["scope"],
                "scopeKey": scope["scopeKey"],
                "topic": scope["topic"],
                "reason": normalized_reason,
                "evidence": evidence_items,
                "sourceSnapshot": s._source_collection_record_source_snapshot(record),
                "firstSeenAt": now,
                "lastSeenAt": now,
                "updatedAt": now,
                "hitCount": 1,
                "createdByTaskId": s._trim_text(task_id, max_length=160),
                "createdByAgent": s._trim_text(agent_id, max_length=160),
                "stageId": s._trim_text(stage_id, max_length=80),
                "source": s._trim_text(source, max_length=80),
                "runIds": [run_id] if run_id else [],
                "recordIds": [record_id] if record_id else [],
                "restoreAllowed": True,
            }
            entries.append(matched)
        else:
            matched["reason"] = normalized_reason or s._trim_text(matched.get("reason"), max_length=120)
            if evidence_items:
                previous_evidence = s._normalize_text_list(matched.get("evidence"), max_items=8, max_length=500)
                matched["evidence"] = s._normalize_text_list([*previous_evidence, *evidence_items], max_items=8, max_length=500)
            matched["sourceSnapshot"] = s._source_collection_record_source_snapshot(record)
            matched["lastSeenAt"] = now
            matched["updatedAt"] = now
            matched["hitCount"] = max(1, s._source_collection_count(matched.get("hitCount")))
            run_ids = s._normalize_text_list(matched.get("runIds"), max_items=40, max_length=160)
            if run_id and run_id not in run_ids:
                run_ids.append(run_id)
            matched["runIds"] = run_ids[:40]
            record_ids = s._normalize_text_list(matched.get("recordIds"), max_items=80, max_length=160)
            if record_id and record_id not in record_ids:
                record_ids.append(record_id)
            matched["recordIds"] = record_ids[:80]
        store["entries"] = entries
        s._write_source_collection_exclusion_store(team_id, store)
        stored = dict(matched)
    s._record_workflow_event(
        "source_collection.source_excluded",
        team_id,
        fields={
            "runId": run_id,
            "recordId": record_id,
            "taskId": s._trim_text(task_id, max_length=160),
            "stageId": s._trim_text(stage_id, max_length=80),
            "sourceIdentityKey": source_identity_key,
            "reason": normalized_reason,
            "scopeKey": scope["scopeKey"],
        },
        level="warning",
        outcome="completed",
    )
    return stored


def _record_source_collection_summary_timing(
    team_id: str,
    run_id: str,
    payload: dict[str, Any],
    started_at: float,
) -> None:
    s = _service()
    # Prefer facade.time so tests can monkeypatch team_workflow_orchestration_service.time.
    clock = getattr(s, "time", time)
    duration_ms = int(round((clock.perf_counter() - started_at) * 1000))
    if duration_ms < s.SOURCE_COLLECTION_SUMMARY_SLOW_EVENT_MS:
        return
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    phase_close_gate = payload.get("phaseCloseGate") if isinstance(payload.get("phaseCloseGate"), dict) else {}
    s._record_workflow_event(
        "source_collection.summary.slow",
        team_id,
        level="warning",
        outcome="degraded",
        fields={
            "runId": s._trim_text(run_id, max_length=160),
            "durationMs": duration_ms,
            "recordCount": s._source_collection_count(summary.get("recordCount")),
            "sourceCandidateCount": s._source_collection_count(summary.get("sourceCandidateCount")),
            "stageCardCount": len(list(payload.get("stageCards") or [])),
            "phaseCloseGateStatus": s._trim_text(phase_close_gate.get("status"), max_length=80),
            "phaseCloseGatePassed": bool(phase_close_gate.get("passed")),
            "activeWorkRun": bool(payload.get("activeWorkRun")),
        },
    )


def _record_workflow_event(
    event_code: str,
    team_id: str,
    *,
    fields: dict[str, Any],
    level: str = "info",
    outcome: str = "observed",
    child_log_path: str = "",
    child_log_payload: dict[str, Any] | None = None,
    lifecycle: bool = False,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "team_workflow_orchestration",
            "workflow",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={"teamId": team_id, **fields},
            child_log_path=child_log_path,
            child_log_payload=child_log_payload,
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _resolve_source_collection_record_id(raw_record_id: str, records: list[dict[str, Any]]) -> tuple[str, str]:
    s = _service()
    candidate = s._trim_text(raw_record_id, max_length=160)
    if not candidate:
        return "", "missing_record_id"
    record_ids = {
        s._trim_text(record.get("recordId"), max_length=160)
        for record in records
        if s._trim_text(record.get("recordId"), max_length=160)
    }
    if candidate in record_ids:
        return candidate, ""
    suffix_lookup = s._source_collection_record_id_suffix_lookup(records)
    matched = suffix_lookup.get(candidate)
    if matched:
        return matched, "record_id_suffix_matched"
    return "", "record_not_in_source_collection_run"


def _source_candidate_payload_from_data_record(run: dict[str, Any], record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    source_type = s._trim_text(record.get("sourceType"), max_length=80) or "unknown"
    source_ref = s._trim_text(record.get("sourceRef"), max_length=2000)
    raw_location = s._trim_text(record.get("rawLocation"), max_length=2000)
    source_kind = s._trim_text(payload.get("sourceKind"), max_length=80) or s._source_kind_from_data_record(source_type, source_ref, raw_location)
    source_url = s._trim_text(payload.get("sourceUrl"), max_length=2000)
    source_path = s._trim_text(payload.get("sourcePath"), max_length=2000)
    if not source_url and s._looks_like_url(source_ref):
        source_url = source_ref
    if not source_path and not source_url:
        source_path = raw_location or (source_ref if source_type in {"file", "paper", "dataset"} else "")
    title = s._trim_text(payload.get("title"), max_length=240) or s._trim_text(record.get("title"), max_length=240) or source_ref or raw_location
    if not title and not source_url and not source_path:
        raise s.TeamWorkflowOrchestrationError("Data processing record cannot be imported without title, sourceRef, or rawLocation.")
    metadata = s._normalize_metadata(payload.get("metadata"))
    record_metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    quality_signals = record.get("qualitySignals") if isinstance(record.get("qualitySignals"), dict) else {}
    collection_trace = record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {}
    source_trace = record_metadata.get("sourceCollectionTrace") if isinstance(record_metadata.get("sourceCollectionTrace"), dict) else collection_trace
    source_category = s._source_collection_source_category(
        source_kind=source_kind,
        source_ref=source_ref,
        raw_location=raw_location,
        source_url=source_url,
        source_path=source_path,
    )
    doi = s._source_collection_extract_doi(source_ref, source_url, raw_location, record_metadata.get("doi"))
    imported_from = s._data_record_ref(run, record)
    metadata.update(
        {
            "importedFromDataRecord": imported_from,
            "dataProcessingQualitySignals": s._normalize_metadata(quality_signals),
            "dataProcessingCollectionTrace": s._normalize_metadata(collection_trace),
            "dataProcessingRecordMetadata": s._normalize_metadata(record_metadata),
            "sourceCollectionTrace": s._normalize_metadata(source_trace),
            "sourceRunId": imported_from["runId"],
            "sourceRecordId": imported_from["recordId"],
            # 定界标记（readiness scoped 过滤的命中键）：SC run、工作流 run 与
            # 研究项目三者取 run 记录权威（任务可得时 workflowRunId 以任务为准）。
            "sourceCollectionRunId": imported_from["runId"],
            "workflowRunId": s._trim_text(
                metadata.get("workflowRunId")
                or run_scope.get("workflowRunId")
                or run_metadata.get("workflowRunId"),
                max_length=160,
            ),
            "researchProjectId": s._trim_text(
                run_scope.get("researchProjectId") or run_metadata.get("researchProjectId"),
                max_length=160,
            ),
            "sourceCategory": source_category,
            "sourceRef": source_ref or raw_location,
            "sourceUrl": source_url,
            "sourcePath": source_path,
            "assignmentId": s._trim_text(source_trace.get("assignmentId"), max_length=128),
            "agentRole": s._trim_text(source_trace.get("agentRole"), max_length=80),
            "queryId": s._trim_text(source_trace.get("queryId"), max_length=160),
            "query": s._trim_text(source_trace.get("query"), max_length=1000),
            "searchProvider": s._trim_text(source_trace.get("searchProvider") or record_metadata.get("searchProvider"), max_length=80),
            "searchUrl": s._trim_text(source_trace.get("searchUrl") or record_metadata.get("searchUrl"), max_length=1000),
        }
    )
    if doi:
        metadata["doi"] = doi
        metadata["importedFromDataRecord"]["doi"] = doi
    source_identity_key = s._source_collection_record_identity_key(record)
    if source_identity_key:
        metadata["sourceIdentityKey"] = source_identity_key
        metadata["importedFromDataRecord"]["sourceIdentityKey"] = source_identity_key
    return {
        "candidateType": "source_manifest",
        "title": title,
        "sourceUrl": source_url,
        "sourcePath": source_path,
        "sourceKind": source_kind,
        "sha256": s._trim_text(payload.get("sha256") or record_metadata.get("sha256"), max_length=128),
        "allowedForAnalysis": s._normalize_optional_bool(payload.get("allowedForAnalysis")) if "allowedForAnalysis" in payload else s._normalize_optional_bool(record_metadata.get("allowedForAnalysis")),
        "pageScope": s._trim_text(payload.get("pageScope") or record_metadata.get("pageScope"), max_length=160),
        "summary": s._trim_text(payload.get("summary"), max_length=4000) or s._trim_text(record.get("summary"), max_length=4000),
        "tags": s._normalize_text_list(payload.get("tags"), max_items=24, max_length=80),
        "evidenceRefs": s._data_record_evidence_refs(run, record, payload),
        "metadata": metadata,
        "createdByAgent": s._trim_text(payload.get("createdByAgent"), max_length=160) or "data_intake_coordinator",
    }


def _source_collection_agent_context_next_actions(stage_id: str, record_count: int, candidate_count: int, open_assignment_count: int) -> list[str]:
    s = _service()
    if stage_id == "finding":
        if record_count <= 0:
            return ["继续等待或执行资料搜索，先形成 DataRecord。"]
        return ["检查 DataRecord 覆盖面，必要时补充查询词或来源类型。"]
    if stage_id == "extraction":
        if candidate_count <= 0:
            return ["从 DataRecord 提炼 source_manifest 候选。"]
        return ["完成候选内容提炼，并对相关性、可靠性、可访问性和入库价值给出审查结论。"]
    if stage_id == "relations":
        return ["基于已通过质量评估的候选构建候选关系图。"]
    if stage_id == "ingestion":
        return ["审核通过候选入库包；正式知识写入仍受审核门禁控制。"]
    if open_assignment_count:
        return ["继续处理未完成的本角色分派任务。"]
    return []


def _source_collection_agent_graph_edges(agent_graph: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()

    def canonical_edge(
        source_id: str,
        target_id: str,
        relation: str,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        edge: dict[str, Any] = s._candidate_graph_edge(
            source_id,
            target_id,
            relation,
        )
        evidence_refs = s._normalize_text_list(
            item.get("evidenceRefs")
            or item.get("evidence_refs")
            or item.get("evidenceRef"),
            max_items=64,
            max_length=320,
        )
        if evidence_refs:
            edge["evidenceRefs"] = evidence_refs
        return edge

    node_aliases: dict[str, str] = {}
    for item in list(agent_graph.get("nodes") or []):
        if not isinstance(item, dict):
            continue
        candidate_id = s._trim_text(item.get("candidateId") or item.get("candidate_id"), max_length=160)
        if not candidate_id:
            continue
        for raw_alias in (candidate_id, item.get("nodeId"), item.get("node_id"), item.get("id")):
            alias = s._trim_text(raw_alias, max_length=160)
            if alias:
                node_aliases.setdefault(alias, candidate_id)
    edges: list[dict[str, Any]] = []
    for item in list(agent_graph.get("edges") or []):
        if not isinstance(item, dict):
            continue
        source_token = s._trim_text(item.get("sourceCandidateId") or item.get("source") or item.get("from"), max_length=160)
        target_token = s._trim_text(item.get("targetCandidateId") or item.get("target") or item.get("to"), max_length=160)
        source_id = node_aliases.get(source_token, source_token)
        target_id = node_aliases.get(target_token, target_token)
        relation = s._trim_text(
            item.get("relation")
            or item.get("relationType")
            or item.get("predicate")
            or item.get("type"),
            max_length=160,
        )
        if source_id and target_id and relation:
            edges.append(canonical_edge(source_id, target_id, relation, item))
    for item in list(agent_graph.get("sourceThemeEdges") or []):
        if not isinstance(item, dict):
            continue
        source_token = s._trim_text(
            item.get("candidateId") or item.get("candidate_id") or item.get("sourceCandidateId") or item.get("source_candidate_id"),
            max_length=160,
        )
        source_id = node_aliases.get(source_token, source_token)
        theme_id = s._source_collection_agent_graph_theme_id(item)
        relation = s._trim_text(item.get("relation") or item.get("relationType") or item.get("relation_type"), max_length=160) or "source_supports_theme"
        if source_id and theme_id:
            edges.append(
                canonical_edge(
                    source_id,
                    s._source_collection_agent_graph_theme_node_id(theme_id),
                    relation,
                    item,
                )
            )
    for item in list(agent_graph.get("topicRelations") or []):
        if not isinstance(item, dict):
            continue
        source_theme_id = s._trim_text(
            item.get("from")
            or item.get("fromThemeId")
            or item.get("from_theme_id")
            or item.get("sourceThemeId")
            or item.get("source_theme_id"),
            max_length=160,
        )
        target_theme_id = s._trim_text(
            item.get("to")
            or item.get("toThemeId")
            or item.get("to_theme_id")
            or item.get("targetThemeId")
            or item.get("target_theme_id"),
            max_length=160,
        )
        relation = s._trim_text(item.get("relation") or item.get("relationType") or item.get("relation_type"), max_length=160)
        if source_theme_id and target_theme_id and relation:
            edges.append(
                canonical_edge(
                    s._source_collection_agent_graph_theme_node_id(source_theme_id),
                    s._source_collection_agent_graph_theme_node_id(target_theme_id),
                    relation,
                    item,
                )
            )
    # ``candidateRelations[]`` is the relations prompt contract's canonical
    # output shape (writeback prompt contracts mandate it). Classify each
    # relation the same way the payload normalizer does: theme endpoints map
    # to ``source-theme:`` node ids, everything else stays a candidate edge.
    # Endpoints that resolve nowhere keep the merge's fail-closed dangling
    # semantics; the caller dedupes by (source, target, relation).
    theme_ids: set[str] = set()
    for item in list(agent_graph.get("themeNodes") or []):
        if not isinstance(item, dict):
            continue
        theme_id = s._source_collection_agent_graph_theme_id(item)
        if theme_id:
            theme_ids.add(theme_id)

    def _theme_endpoint(token: str) -> str:
        bare = token.split(":", 1)[1] if token.startswith("source-theme:") else token
        return s._source_collection_agent_graph_theme_node_id(bare) if bare in theme_ids else ""

    for item in list(agent_graph.get("candidateRelations") or []):
        if not isinstance(item, dict):
            continue
        source_token = s._trim_text(
            item.get("from")
            or item.get("source")
            or item.get("sourceCandidateId")
            or item.get("candidateId"),
            max_length=160,
        )
        target_token = s._trim_text(
            item.get("to")
            or item.get("target")
            or item.get("targetCandidateId")
            or item.get("themeId"),
            max_length=160,
        )
        relation = s._trim_text(
            item.get("relation") or item.get("relationType") or item.get("relation_type") or item.get("type"),
            max_length=160,
        )
        if not source_token or not target_token or not relation:
            continue
        source_id = node_aliases.get(source_token, source_token)
        target_id = node_aliases.get(target_token, target_token)
        source_id = _theme_endpoint(source_id) or source_id
        target_id = _theme_endpoint(target_id) or target_id
        edges.append(canonical_edge(source_id, target_id, relation, item))
    return edges


def _source_collection_agent_graph_nodes(agent_graph: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    nodes: list[dict[str, Any]] = []
    for item in list(agent_graph.get("nodes") or []):
        if not isinstance(item, dict):
            continue
        node_id = s._trim_text(item.get("candidateId") or item.get("id"), max_length=160)
        if not node_id:
            continue
        nodes.append(
            {
                "candidateId": node_id,
                "candidateType": s._trim_text(item.get("candidateType") or item.get("type"), max_length=80) or "agent_relation_node",
                "title": s._trim_text(item.get("title") or item.get("label") or node_id, max_length=240),
                "currentWorkflowNode": s._trim_text(item.get("currentWorkflowNode"), max_length=120) or "candidate_graph",
                "currentState": s._trim_text(item.get("currentState"), max_length=120) or "candidate_graph_visible",
                "qualityStatus": s._trim_text(item.get("qualityStatus"), max_length=120) or "preview_ready",
                "valid": bool(item.get("valid", True)),
                "requiresReview": bool(item.get("requiresReview", False)),
                "officialState": s._trim_text(item.get("officialState"), max_length=80) or "candidate_only",
            }
        )
    for item in list(agent_graph.get("themeNodes") or []):
        if not isinstance(item, dict):
            continue
        theme_id = s._source_collection_agent_graph_theme_id(item)
        if not theme_id:
            continue
        nodes.append(
            {
                "candidateId": s._source_collection_agent_graph_theme_node_id(theme_id),
                "candidateType": "source_topic",
                "title": s._trim_text(item.get("label") or item.get("title") or theme_id, max_length=240),
                "currentWorkflowNode": "candidate_graph",
                "currentState": "candidate_graph_visible",
                "qualityStatus": "preview_ready",
                "valid": True,
                "requiresReview": False,
                "officialState": "candidate_only",
            }
        )
    return nodes


def _source_collection_agent_graph_theme_id(item: dict[str, Any]) -> str:
    s = _service()
    return s._trim_text(
        item.get("themeId") or item.get("theme_id") or item.get("topicId") or item.get("topic_id") or item.get("id"),
        max_length=160,
    )


def _source_collection_agent_graph_theme_node_id(theme_id: str) -> str:
    s = _service()
    normalized = s._trim_text(theme_id, max_length=160)
    return f"source-theme:{normalized}" if normalized and not normalized.startswith("source-theme:") else normalized


def _source_collection_agent_id(role: str, payload: dict[str, Any]) -> str:
    s = _service()
    agent_ids = payload.get("agentIds") if isinstance(payload.get("agentIds"), dict) else {}
    explicit = s._trim_text(agent_ids.get(role), max_length=160)
    return explicit or role


def _source_collection_agent_role_for_id(assignments: list[dict[str, Any]], agent_id: str, stage_id: str) -> str:
    s = _service()
    normalized_agent_id = s._trim_text(agent_id, max_length=160)
    allowed_roles = s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES.get(stage_id, ())
    for assignment in assignments:
        if s._trim_text(assignment.get("agentId"), max_length=160) != normalized_agent_id:
            continue
        role = s._trim_text(assignment.get("agentRole"), max_length=80)
        if role in allowed_roles:
            return role
    for assignment in assignments:
        role = s._trim_text(assignment.get("agentRole"), max_length=80)
        if role in allowed_roles:
            return role
    return allowed_roles[0] if allowed_roles else ""


def _source_collection_assignment_scope(role: str, base_scope: dict[str, Any], *, search_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    role_purposes = {
        "data_intake_coordinator": "Coordinate source collection and handoff to source_manifest import.",
        "source_finder": "Find, fetch, download, and register traceable source records for the run.",
        "source_extractor": "Extract useful source content and make source-quality decisions in one pass.",
        "source_relation_mapper": "Build candidate-only topic, source, and evidence relationships.",
        "source_ingestor": "Perform governed final ingestion into formal team knowledge.",
    }
    scope = {
        **base_scope,
        "agentRole": role,
        "rolePurpose": role_purposes.get(role, "Collect data records for downstream processing."),
    }
    if isinstance(search_plan, dict):
        assigned_queries = s._source_collection_queries_for_role(search_plan, role)
        prompt_cache_policy = search_plan.get("promptCachePolicy") if isinstance(search_plan.get("promptCachePolicy"), dict) else {}
        scope["dataSearchPlanRef"] = s._source_collection_search_plan_ref(search_plan)
        scope["assignedQueries"] = assigned_queries
        scope["queryCount"] = len(assigned_queries)
        scope["resultWritebackContract"] = search_plan.get("resultWritebackContract", {})
        scope["promptCachePolicyRef"] = s._source_collection_prompt_cache_policy_ref(prompt_cache_policy)
        scope["promptCachePartition"] = s._source_collection_prompt_cache_partition(
            str(base_scope.get("teamId") or search_plan.get("teamId") or ""),
            role,
            model_id=str(prompt_cache_policy.get("modelId") or ""),
        )
        scope["conversationTraceRequired"] = bool((prompt_cache_policy.get("dynamicDeltaContract") or {}).get("conversationTraceRequired", True))
    return scope


def _source_collection_assignment_stage_summary(assignments: list[dict[str, Any]]) -> dict[str, int]:
    s = _service()
    open_assignments = s._source_collection_open_assignments(assignments)
    search_assignments = [
        item for item in assignments
        if s._normalize_source_collection_agent_role(item.get("agentRole")) in s.SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
    ]
    search_open_assignments = [
        item for item in open_assignments
        if s._normalize_source_collection_agent_role(item.get("agentRole")) in s.SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
    ]
    collection_assignments = [
        item for item in assignments
        if s._normalize_source_collection_agent_role(item.get("agentRole")) in s.SOURCE_COLLECTION_COLLECTION_STAGE_AGENT_ROLES
    ]
    collection_open_assignments = [
        item for item in open_assignments
        if s._normalize_source_collection_agent_role(item.get("agentRole")) in s.SOURCE_COLLECTION_COLLECTION_STAGE_AGENT_ROLES
    ]
    downstream_assignments = [
        item for item in assignments
        if s._normalize_source_collection_agent_role(item.get("agentRole")) not in s.SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
    ]
    downstream_open_assignments = [
        item for item in open_assignments
        if s._normalize_source_collection_agent_role(item.get("agentRole")) not in s.SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
    ]
    return {
        "assignmentCount": len(assignments),
        "openAssignmentCount": len(open_assignments),
        "searchAssignmentCount": len(search_assignments),
        "searchOpenAssignmentCount": len(search_open_assignments),
        "collectionAssignmentCount": len(collection_assignments),
        "collectionOpenAssignmentCount": len(collection_open_assignments),
        "downstreamAssignmentCount": len(downstream_assignments),
        "downstreamOpenAssignmentCount": len(downstream_open_assignments),
    }


def _source_collection_background_snapshot_is_active(snapshot: dict[str, Any] | None, team_id: str, run_id: str) -> bool:
    s = _service()
    if not isinstance(snapshot, dict):
        return False
    if s._source_collection_work_run_snapshot_is_stale(snapshot):
        return False
    if s._trim_text(snapshot.get("runId"), max_length=160) != run_id:
        return False
    if s._trim_text(snapshot.get("teamId"), max_length=160) != team_id:
        return False
    status = s._trim_text(snapshot.get("status"), max_length=80).lower()
    current_phase = s._trim_text(snapshot.get("currentPhase"), max_length=80).lower()
    return status in {"queued", "running"} or current_phase in {"queued", "running"}


def _source_collection_candidate_count_for_run(candidate_store: dict[str, Any], run_id: str) -> int:
    s = _service()
    count = 0
    for candidate in list(candidate_store.get("candidates") or []):
        if not isinstance(candidate, dict) or s._candidate_is_archived(candidate):
            continue
        if str(candidate.get("candidateType") or "") != "source_manifest":
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        if str(imported_from.get("runId") or "") == run_id:
            count += 1
    return count


def _source_collection_candidates_for_run(team_id: str, run_id: str) -> list[dict[str, Any]]:
    s = _service()
    normalized_run_id = s._trim_text(run_id, max_length=128)
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(team_id, run_id=normalized_run_id)
    candidates: list[dict[str, Any]] = []
    for item in list(candidate_store.get("candidates") or []):
        if not isinstance(item, dict) or item.get("candidateType") != "source_manifest":
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        candidate_run_id = (
            s._trim_text(imported_from.get("runId"), max_length=128)
            or s._trim_text(metadata.get("sourceCollectionRunId"), max_length=128)
        )
        if candidate_run_id == normalized_run_id:
            candidates.append(item)
    return candidates


def _source_collection_collection_mode(value: Any) -> str:
    s = _service()
    normalized = s._safe_token(value, default="web_search", max_length=80)
    return normalized if normalized in s.SOURCE_COLLECTION_COLLECTION_MODES else "web_search"


def _source_collection_completion_superseded_stage_cutoffs(team_id: str, run_id: str) -> dict[str, str]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._trim_text(run_id, max_length=160)
    if not normalized_run_id:
        return {}
    try:
        snapshot = s._decorate_knowledge_ingestion_work_run_snapshot(
            s._knowledge_ingestion_work_run_store().load_latest_snapshot(s.KNOWLEDGE_INGESTION_WORK_RUN_KIND)
        )
    except Exception:
        return {}
    if not isinstance(snapshot, dict):
        return {}
    if s._trim_text(snapshot.get("teamId"), max_length=160) != normalized_team_id:
        return {}
    if s._trim_text(snapshot.get("sourceRunId"), max_length=160) != normalized_run_id:
        return {}
    if s._knowledge_collection_flow_step_status(snapshot.get("status")) == "failed":
        return {}
    flow = snapshot.get("flowVisualization") if isinstance(snapshot.get("flowVisualization"), dict) else {}
    nodes = [item for item in list(flow.get("nodes") or []) if isinstance(item, dict)]
    updated_at = s._trim_text(snapshot.get("finishedAt") or snapshot.get("updatedAt"), max_length=120)
    if not nodes or not updated_at:
        return {}
    cutoffs: dict[str, str] = {}
    for node in nodes:
        stage_id = s._normalize_source_collection_stage_id(node.get("stageId"), default="")
        if stage_id not in s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
            continue
        raw_status = s._trim_text(node.get("status"), max_length=120).lower()
        normalized_status = s._knowledge_collection_flow_step_status(raw_status)
        if raw_status == "executed" or normalized_status in {"completed", "skipped"}:
            cutoffs[stage_id] = updated_at
    return cutoffs


def _source_collection_count(value: Any) -> int:
    s = _service()
    return s._normalize_int(value, default=0, minimum=0, maximum=100_000)


def _source_collection_current_stage_agent_ids(team_id: str, stage_id: str) -> set[str]:
    s = _service()
    return s._source_collection_current_stage_agent_ids_by_stage(team_id, [stage_id]).get(stage_id, set())


def _source_collection_current_stage_agent_ids_by_stage(team_id: str, stage_ids: Iterable[str]) -> dict[str, set[str]]:
    s = _service()
    normalized_stage_ids = [
        s._normalize_source_collection_stage_id(stage_id, default="")
        for stage_id in stage_ids
        if s._normalize_source_collection_stage_id(stage_id, default="") in s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES
    ]
    result = {stage_id: set() for stage_id in normalized_stage_ids}
    if not result:
        return result
    role_to_stage_ids: dict[str, list[str]] = {}
    for stage_id in result:
        for role in s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES.get(stage_id, ()):
            role_to_stage_ids.setdefault(role, []).append(stage_id)
    for member in s._source_collection_team_member_snapshot(team_id):
        member_role = s._normalize_source_collection_agent_role(member.get("role") or member.get("agentRole"))
        member_agent_id = s._trim_text(member.get("agentId"), max_length=160)
        if not member_agent_id:
            continue
        for stage_id in role_to_stage_ids.get(member_role, ()):
            result[stage_id].add(member_agent_id)
    return result


def _source_collection_data_processing_source_type(value: Any) -> str:
    s = _service()
    source_type = s._trim_text(value, max_length=80).lower()
    if source_type in s.data_processing_service.SOURCE_TYPES:
        return source_type
    if source_type in {"review", "preprint", "journal-article", "proceedings-article", "book-chapter"}:
        return "paper"
    if source_type in {"posted-content"}:
        return "paper"
    if source_type in {"dataset", "data"}:
        return "dataset"
    return "url"


def _source_collection_data_run_exists(run_id: str) -> bool:
    s = _service()
    normalized_run_id = s._trim_text(run_id, max_length=160)
    if not normalized_run_id:
        return False
    try:
        s.data_processing_service.get_processing_run(normalized_run_id)
    except s.data_processing_service.DataProcessingError:
        return False
    return True


def _source_collection_default_stage_agent(stage_id: str, *, agent_role: str = "") -> dict[str, Any] | None:
    s = _service()
    return None


def _source_collection_dynamic_delta_contract() -> dict[str, Any]:
    s = _service()
    return {
        "allowedFields": [
            "queryId",
            "query",
            "sourceRef",
            "rawLocation",
            "resultSummary",
            "recordId",
            "collectionTrace",
            "cacheObservation",
        ],
        "maxRawContentPolicy": "Do not replay full pages; store artifacts as DataRecord/source refs and pass excerpts or summaries only.",
        "conversationTraceRequired": True,
    }


def _source_collection_exclusion_scope(run: dict[str, Any]) -> dict[str, str]:
    s = _service()
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    topic = s._trim_text(
        scope.get("topic")
        or metadata.get("topic")
        or run.get("title")
        or scope.get("goal")
        or metadata.get("title"),
        max_length=500,
    )
    normalized = re.sub(r"\s+", " ", topic.lower()).strip()
    scope_key = f"topic:{hashlib.sha256(normalized.encode('utf-8', errors='replace')).hexdigest()[:24]}" if normalized else "team"
    return {
        "scope": "team_topic" if normalized else "team",
        "scopeKey": scope_key,
        "topic": topic,
    }


def _source_collection_exclusion_store_default(team_id: str) -> dict[str, Any]:
    s = _service()
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": team_id,
        "entries": [],
        "updatedAt": "",
    }


def _source_collection_exclusion_store_path(team_id: str) -> Path:
    s = _service()
    return s._team_workflow_root(team_id) / "source_collection_exclusions" / "index.json"


def _source_collection_existing_query_ids(records: list[dict[str, Any]]) -> set[str]:
    s = _service()
    query_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        traces = [
            record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {},
            metadata.get("sourceCollectionTrace") if isinstance(metadata.get("sourceCollectionTrace"), dict) else {},
        ]
        for trace in traces:
            query_id = s._trim_text(trace.get("queryId"), max_length=160)
            if query_id:
                query_ids.add(query_id)
    return query_ids


def _source_collection_expected_action(role: str) -> str:
    s = _service()
    actions = {
        "data_intake_coordinator": "Coordinate planned query execution and ensure outputs follow the writeback contract.",
        "source_finder": "Find, fetch, download, and register traceable DataRecord sources.",
        "source_extractor": "Extract useful content and review source quality with per-source decisions.",
        "source_relation_mapper": "Organize approved sources into candidate-only topic and evidence relationships.",
        "source_ingestor": "Review approved candidates and write governed formal Team Knowledge.",
    }
    return actions.get(role, "Collect data records under the source-collection run contract.")


def _source_collection_extract_doi(*values: Any) -> str:
    s = _service()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
        match = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", text, flags=re.IGNORECASE)
        if match:
            return match.group(0).rstrip(").,;")
    return ""


def _source_collection_extraction_citation_items(value: Any) -> list[dict[str, str]]:
    s = _service()
    if not isinstance(value, list):
        return []
    citations: list[dict[str, str]] = []
    for item in value[:24]:
        if isinstance(item, dict):
            normalized = {
                "sourceRef": s._trim_text(item.get("sourceRef") or item.get("sourceRefId") or item.get("sourceId"), max_length=240),
                "page": s._trim_text(item.get("page") or item.get("pageAnchor") or item.get("pageRange"), max_length=120),
                "citation": s._trim_text(item.get("citation") or item.get("citationAnchor") or item.get("text"), max_length=300),
                "evidenceRef": s._trim_text(item.get("evidenceRef") or item.get("evidenceRefId"), max_length=240),
            }
        else:
            normalized = {
                "sourceRef": "",
                "page": "",
                "citation": s._trim_text(item, max_length=300),
                "evidenceRef": "",
            }
        compact = {key: item_value for key, item_value in normalized.items() if item_value}
        if compact:
            citations.append(compact)
    return citations


def _source_collection_extraction_claim_items(value: Any) -> list[dict[str, str]]:
    s = _service()
    if not isinstance(value, list):
        return []
    claims: list[dict[str, str]] = []
    for item in value[:24]:
        if isinstance(item, dict):
            claim = s._trim_text(item.get("claim") or item.get("finding") or item.get("summary") or item.get("text"), max_length=600)
            normalized = {
                "claim": claim,
                "sourceRef": s._trim_text(item.get("sourceRef") or item.get("sourceRefId") or item.get("sourceId"), max_length=240),
                "page": s._trim_text(item.get("page") or item.get("pageAnchor") or item.get("pageRange"), max_length=120),
                "citation": s._trim_text(item.get("citation") or item.get("citationAnchor"), max_length=300),
                "evidenceRef": s._trim_text(item.get("evidenceRef") or item.get("evidenceRefId"), max_length=240),
                "supportLevel": s._trim_text(item.get("supportLevel") or item.get("support") or item.get("confidence"), max_length=80),
            }
        else:
            normalized = {
                "claim": s._trim_text(item, max_length=600),
                "sourceRef": "",
                "page": "",
                "citation": "",
                "evidenceRef": "",
                "supportLevel": "",
            }
        compact = {key: item_value for key, item_value in normalized.items() if item_value}
        if compact:
            claims.append(compact)
    return claims


def _source_collection_extraction_evidence_ledger(
    extraction: dict[str, Any],
    *,
    fallback_evidence_refs: Any = None,
) -> dict[str, Any]:
    s = _service()
    key_findings_value = extraction.get("keyFindings") or extraction.get("key_findings") or extraction.get("findings")
    evidence_refs = s._normalize_ref_list(
        extraction.get("evidenceRefs") or extraction.get("evidence_refs") or fallback_evidence_refs,
        max_items=24,
    )
    ledger = {
        "sourceRefs": s._normalize_ref_list(extraction.get("sourceRefs") or extraction.get("source_refs"), max_items=24),
        "evidenceRefs": evidence_refs,
        "claims": s._source_collection_extraction_claim_items(extraction.get("claims")),
        "keyFindings": s._source_collection_extraction_key_finding_items(key_findings_value),
        "citations": s._source_collection_extraction_citation_items(extraction.get("citations")),
        "limitations": s._normalize_text_list(
            extraction.get("limitations") or extraction.get("defects"),
            max_items=12,
            max_length=240,
        ),
        "uncertainty": s._normalize_text_list(extraction.get("uncertainty"), max_items=12, max_length=240),
        "riskFlags": s._normalize_text_list(
            extraction.get("riskFlags") or extraction.get("risk_flags") or extraction.get("risks"),
            max_items=12,
            max_length=120,
        ),
        "supportLevel": s._trim_text(extraction.get("supportLevel") or extraction.get("support") or extraction.get("confidence"), max_length=80),
        "nextAction": s._trim_text(extraction.get("nextAction") or extraction.get("next_action") or extraction.get("followUpSuggestion"), max_length=240),
    }
    compact = {key: value for key, value in ledger.items() if value not in ("", [], {})}
    if not compact:
        return {}
    compact["status"] = "evidence_ready" if s._source_collection_extraction_has_evidence_anchor(compact) else "missing_evidence_anchor"
    return compact


def _source_collection_evidence_ref_has_anchor(value: dict[str, Any]) -> bool:
    s = _service()
    ref_type = s._trim_text(value.get("type"), max_length=80).lower().replace("-", "_")
    ref_id = s._trim_text(value.get("id"), max_length=240)
    if not ref_type or not ref_id:
        return False
    if ref_type in {"doi", "url", "uri", "paper", "source", "data_record", "candidate", "record", "text"}:
        return False
    return (
        ref_type in {
            "page",
            "pdf_page",
            "page_anchor",
            "record_anchor",
            "section",
            "paragraph",
            "html_paragraph",
            "quote",
            "citation",
            "excerpt",
            "abstract",
            "sentence",
            "line",
            "table",
            "figure",
            "timestamp",
        }
        or "anchor" in ref_type
        or ref_type.endswith("_page")
    )


def _source_collection_extraction_has_evidence_anchor(ledger: dict[str, Any]) -> bool:
    s = _service()
    if any(
        _source_collection_evidence_ref_has_anchor(item)
        for item in s._normalize_ref_list(ledger.get("evidenceRefs"), max_items=24)
    ):
        return True
    for key in ("claims", "keyFindings", "citations"):
        for item in list(ledger.get(key) or []):
            if isinstance(item, dict) and s._has_citation_anchor(item):
                return True
    return False


def _source_collection_extraction_key_finding_items(value: Any) -> list[dict[str, str]]:
    s = _service()
    if not isinstance(value, list):
        return []
    findings: list[dict[str, str]] = []
    for item in value[:24]:
        if isinstance(item, dict):
            finding = s._trim_text(item.get("finding") or item.get("claim") or item.get("summary") or item.get("text"), max_length=600)
            normalized = {
                "finding": finding,
                "sourceRef": s._trim_text(item.get("sourceRef") or item.get("sourceRefId") or item.get("sourceId"), max_length=240),
                "page": s._trim_text(item.get("page") or item.get("pageAnchor") or item.get("pageRange"), max_length=120),
                "citation": s._trim_text(item.get("citation") or item.get("citationAnchor"), max_length=300),
                "evidenceRef": s._trim_text(item.get("evidenceRef") or item.get("evidenceRefId"), max_length=240),
                "supportLevel": s._trim_text(item.get("supportLevel") or item.get("support") or item.get("confidence"), max_length=80),
            }
        else:
            normalized = {
                "finding": s._trim_text(item, max_length=600),
                "sourceRef": "",
                "page": "",
                "citation": "",
                "evidenceRef": "",
                "supportLevel": "",
            }
        compact = {key: item_value for key, item_value in normalized.items() if item_value}
        if compact:
            findings.append(compact)
    return findings


def _source_collection_extraction_key_finding_texts(extraction: dict[str, Any]) -> list[str]:
    s = _service()
    raw_findings = extraction.get("keyFindings") or extraction.get("key_findings") or extraction.get("findings")
    if not isinstance(raw_findings, list):
        return []
    findings: list[str] = []
    for item in raw_findings[:12]:
        if isinstance(item, dict):
            text = s._trim_text(
                item.get("finding")
                or item.get("claim")
                or item.get("summary")
                or item.get("text"),
                max_length=240,
            )
        else:
            text = s._trim_text(item, max_length=240)
        if text and text not in findings:
            findings.append(text)
    return findings


def _source_collection_filter_active_records(
    team_id: str,
    run: dict[str, Any],
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    s = _service()
    active_records: list[dict[str, Any]] = []
    excluded_refs: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        excluded = s._source_collection_record_is_excluded(team_id, run, record)
        if excluded:
            excluded_refs.append(
                {
                    "recordId": s._trim_text(record.get("recordId"), max_length=160),
                    "sourceIdentityKey": s._trim_text(excluded.get("sourceIdentityKey"), max_length=240),
                    "reason": s._trim_text(excluded.get("reason"), max_length=120),
                    "title": s._trim_text(record.get("title") or (excluded.get("sourceSnapshot") or {}).get("title"), max_length=240),
                }
            )
            continue
        active_records.append(record)
    return active_records, {
        "excludedCount": len(excluded_refs),
        "activeRecordCount": len(active_records),
        "rawRecordCount": len([item for item in records if isinstance(item, dict)]),
        "excluded": excluded_refs[:40],
    }


def _source_collection_identity_key(
    *,
    source_ref: Any,
    raw_location: Any,
    doi: Any = "",
    url: Any = "",
    title: Any,
    container: Any = "",
    published: Any = "",
) -> str:
    s = _service()
    for value in (doi, source_ref, raw_location):
        doi = s._source_collection_normalized_doi(value)
        if doi:
            return f"doi:{doi}"
    for value in (url, source_ref, raw_location):
        url_key = s._source_collection_normalized_url(value)
        if url_key:
            return f"url:{url_key}"
    normalized_title = re.sub(r"\s+", " ", s._trim_text(title, max_length=260).lower()).strip()
    if len(normalized_title) < 16:
        return ""
    normalized_container = re.sub(r"\s+", " ", s._trim_text(container, max_length=160).lower()).strip()
    year_match = re.search(r"(19|20)\d{2}", s._trim_text(published, max_length=80))
    if not normalized_container and not year_match:
        return ""
    fingerprint_source = "|".join([normalized_title, normalized_container, year_match.group(0) if year_match else ""])
    return f"title:{hashlib.sha256(fingerprint_source.encode('utf-8')).hexdigest()[:24]}"


def _source_collection_is_text_model(model_id: str, model_entry: dict[str, Any]) -> bool:
    s = _service()
    descriptor = " ".join(
        [
            str(model_id or ""),
            str(model_entry.get("model") or ""),
            str(model_entry.get("label") or ""),
            str(model_entry.get("transport") or ""),
        ]
    ).lower()
    if "image2" in descriptor or "image" in descriptor:
        return False
    return True


def _source_collection_local_file_summary(file_path: Path, sample_bytes: bytes) -> str:
    s = _service()
    if file_path.suffix.lower() == ".pdf":
        return "Local PDF source; metadata imported for downstream extraction."
    text = s._decode_local_workspace_sample(sample_bytes)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return s._trim_text(" ".join(lines[:12]), max_length=1200)


def _source_collection_local_file_title(file_path: Path, sample_bytes: bytes) -> str:
    s = _service()
    text = s._decode_local_workspace_sample(sample_bytes)
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return s._trim_text(stripped, max_length=240)
    return s._trim_text(file_path.stem.replace("_", " "), max_length=240) or file_path.name


def _source_collection_local_scan_summary(
    *,
    status: str,
    imported: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    imported_items = list(imported or [])
    skipped_items = list(skipped or [])
    failed_items = list(failed or [])
    return {
        "status": status,
        "importedCount": len(imported_items),
        "skippedCount": len(skipped_items),
        "failedCount": len(failed_items),
        "imported": imported_items[:40],
        "skipped": skipped_items[:40],
        "failed": failed_items[:40],
    }


def _source_collection_matching_assignments(
    assignments: list[dict[str, Any]],
    *,
    agent_id: str,
    agent_role: str,
) -> list[dict[str, Any]]:
    s = _service()
    return [
        item
        for item in assignments
        if (
            (agent_role and s._trim_text(item.get("agentRole"), max_length=80) == agent_role)
            or s._trim_text(item.get("agentId"), max_length=160) == agent_id
        )
    ]


def _source_collection_model_library() -> dict[str, Any]:
    s = _service()
    try:
        public_config = s.load_public_config()
    except Exception:
        public_config = {}
    llm = public_config.get("llm") if isinstance(public_config, dict) else {}
    if isinstance(llm, dict) and int(llm.get("schema_version") or 2) == 2:
        try:
            from config.llm_projection import project_v2_llm_for_runtime

            public_config = project_v2_llm_for_runtime(public_config)
        except (TypeError, ValueError):
            return {}
    llm = public_config.get("llm") if isinstance(public_config, dict) else {}
    model_library = llm.get("model_library") if isinstance(llm, dict) else {}
    return dict(model_library) if isinstance(model_library, dict) else {}


def _source_collection_normalized_doi(value: Any) -> str:
    s = _service()
    text = s._trim_text(value, max_length=1000).strip()
    if not text:
        return ""
    match = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(0).rstrip(".,;)").lower()


def _source_collection_normalized_url(value: Any) -> str:
    s = _service()
    text = s._trim_text(value, max_length=1000).strip()
    if not s._looks_like_url(text):
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return ""
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if not netloc:
        return ""
    query_pairs = sorted(
        [
        (key, val)
        for key, val in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid"}
        ]
    )
    query = urllib.parse.urlencode(query_pairs, doseq=True)
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def _source_collection_open_assignments(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
    return [
        item for item in assignments
        if str(item.get("status") or "").strip().lower() in {"open", "in_progress", "returned"}
    ]


def _source_collection_output_query_ids(outputs: list[dict[str, Any]]) -> set[str]:
    s = _service()
    query_ids: set[str] = set()
    for output in outputs:
        if not isinstance(output, dict):
            continue
        quality_signals = output.get("qualitySignals") if isinstance(output.get("qualitySignals"), dict) else {}
        query_id = s._trim_text(quality_signals.get("queryId"), max_length=160)
        if query_id:
            query_ids.add(query_id)
    return query_ids


def _source_collection_owner_agent_id(team: dict[str, Any], payload: dict[str, Any]) -> str:
    s = _service()
    explicit = s._trim_text(payload.get("ownerAgentId"), max_length=160)
    if explicit:
        return explicit
    canvas = team.get("canvas") if isinstance(team.get("canvas"), dict) else {}
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    preferred_roles = ("research_coordination", "data_intake_coordinator", "ceo", "organization_coordinator")
    for preferred_role in preferred_roles:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            role = s._trim_text(node.get("role"), max_length=80)
            agent_id = s._trim_text(node.get("agentId"), max_length=160)
            if role == preferred_role and agent_id:
                return agent_id
    return s.DEFAULT_OWNER_AGENT_ID


def _source_collection_phase_close_gate(
    run_id: str,
    *,
    projection: dict[str, Any],
    stage_round_ref: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    normalized_run_id = s._trim_text(run_id, max_length=160)
    cards_by_stage = {
        s._normalize_source_collection_stage_id(item.get("stageId"), default=""): item
        for item in list(projection.get("cards") or [])
        if isinstance(item, dict) and s._normalize_source_collection_stage_id(item.get("stageId"), default="")
    }
    stages: list[dict[str, Any]] = []
    blocking_reasons: list[str] = []
    for stage_id in s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
        card = cards_by_stage.get(stage_id, {})
        passed = bool(card.get("isClosedLoop"))
        card_reasons = [
            s._trim_text(item, max_length=500)
            for item in list(card.get("blockingReasons") or [])
            if s._trim_text(item, max_length=500)
        ]
        if not passed and not card_reasons:
            card_reasons = [f"{stage_id} 阶段尚未形成闭环。"]
        blocking_reasons.extend(card_reasons)
        stages.append(
            {
                "stageId": stage_id,
                "status": s._trim_text(card.get("status"), max_length=80) or "not_started",
                "passed": passed,
                "artifactStatus": s._trim_text(card.get("artifactStatus"), max_length=80),
                "agentTaskStatus": s._trim_text(card.get("agentTaskStatus"), max_length=80) or "not_started",
                "currentCoverageSummary": card.get("currentCoverageSummary")
                if isinstance(card.get("currentCoverageSummary"), dict)
                else {},
                "blockingReasons": card_reasons,
            }
        )
    stage_count = len(stages)
    closed_loop_count = sum(1 for stage in stages if stage["passed"])
    stage_gate_passed = (
        bool(normalized_run_id)
        and stage_count == len(s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES)
        and closed_loop_count == stage_count
    )
    stage_round_status = s._trim_text(stage_round_ref.get("status"), max_length=80).lower()
    state_reconciliation_required = stage_gate_passed and stage_round_status not in {"completed", "closed_loop"}
    if not normalized_run_id:
        gate_status = "idle"
        blocking_reasons = ["尚未选择资料搜集运行批次。"]
    elif not stage_gate_passed:
        gate_status = "needs_continue"
    elif state_reconciliation_required:
        gate_status = "ready_to_close"
        blocking_reasons.append("四个阶段产物已齐备，等待阶段轮次状态收口。")
    else:
        gate_status = "closed_loop"
    return {
        "runId": normalized_run_id,
        "stageRoundId": s._trim_text(stage_round_ref.get("stageRoundId"), max_length=160),
        "stageRoundStatus": stage_round_status,
        "status": gate_status,
        "passed": gate_status == "closed_loop",
        "stageGatePassed": stage_gate_passed,
        "stateReconciliationRequired": state_reconciliation_required,
        "stageCount": stage_count,
        "closedLoopCount": closed_loop_count,
        "stages": stages,
        "blockingReasons": list(dict.fromkeys(blocking_reasons)),
    }


def _source_collection_prompt_cache_mode(model_entry: dict[str, Any]) -> str:
    s = _service()
    prompt_cache = model_entry.get("prompt_cache") if isinstance(model_entry.get("prompt_cache"), dict) else {}
    return s._trim_text(prompt_cache.get("mode"), max_length=80).lower() or "disabled"


def _source_collection_prompt_cache_model_score(model_id: str, model_entry: dict[str, Any]) -> tuple[int, str]:
    s = _service()
    descriptor = " ".join(
        [
            str(model_id or ""),
            str(model_entry.get("model") or ""),
            str(model_entry.get("label") or ""),
            str((model_entry.get("provider") or {}).get("kind") if isinstance(model_entry.get("provider"), dict) else model_entry.get("provider") or ""),
        ]
    ).lower()
    score = 0
    if s._source_collection_is_text_model(model_id, model_entry):
        score += 100
    if "qwen" in descriptor or "local" in descriptor:
        score += 30
    if "relay" in descriptor or "openai" in descriptor or "gpt" in descriptor:
        score += 20
    return (-score, str(model_id or ""))


def _source_collection_prompt_cache_policy(team_id: str, payload: dict[str, Any], roles: list[str]) -> dict[str, Any]:
    s = _service()
    raw_policy = payload.get("promptCachePolicy") if isinstance(payload.get("promptCachePolicy"), dict) else {}
    requirement = s._normalize_source_collection_prompt_cache_requirement(raw_policy, payload)
    requested_model_id = (
        s._trim_text(raw_policy.get("modelId"), max_length=160)
        or s._trim_text(payload.get("modelId"), max_length=160)
    )
    model_id, model_entry, model_resolution = s._source_collection_resolve_prompt_cache_model(requested_model_id)
    prompt_cache_mode = s._source_collection_prompt_cache_mode(model_entry)
    model_name = s._trim_text(model_entry.get("model") or model_entry.get("label"), max_length=240) or model_id
    provider_id = s._trim_text(model_entry.get("provider_id") or model_entry.get("provider"), max_length=160)
    hard_block = requirement in s.SOURCE_COLLECTION_PROMPT_CACHE_REQUIRED_MODES
    gate_status = "disabled" if requirement in s.SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES else "satisfied"
    gate_reason = ""
    if requirement not in s.SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES and not model_entry:
        gate_status = "blocked" if hard_block else "warning"
        requested_for_message = s._trim_text(model_resolution.get("requestedModelId"), max_length=160)
        gate_reason = (
            f"Prompt cache model is not configured: {requested_for_message}"
            if requested_for_message
            else "No prompt-cache-capable model is configured for knowledge collection."
        )
    elif hard_block and prompt_cache_mode not in s.SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES:
        gate_status = "blocked"
        gate_reason = (
            "Knowledge collection requires prompt cache/KV reuse, but "
            f"model `{model_id}` has prompt_cache.mode `{prompt_cache_mode}`."
        )
    elif requirement not in s.SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES and prompt_cache_mode not in s.SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES:
        gate_status = "warning"
        gate_reason = f"Prompt cache is not guaranteed for model `{model_id}`."
    role_partitions = [
        {
            "agentRole": role,
            "agentId": s._source_collection_agent_id(role, payload),
            "promptCachePartition": s._source_collection_prompt_cache_partition(team_id, role, model_id=model_id),
        }
        for role in roles
    ]
    policy = {
        "schemaVersion": s.SCHEMA_VERSION,
        "policyId": s._new_record_id("cachepolicy"),
        "policyKind": "source_collection_prompt_cache_policy",
        "scope": s.SOURCE_COLLECTION_PROMPT_CACHE_SCOPE,
        "requirement": requirement,
        "modelId": model_id,
        "modelName": model_name,
        "providerId": provider_id,
        "promptCacheMode": prompt_cache_mode,
        "modelResolution": model_resolution,
        "supportedPromptCacheModes": sorted(s.SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES),
        "partitionTemplate": "research-team:{teamId}:knowledge_collection:{agentRole}:{modelId}",
        "rolePartitions": role_partitions,
        "stablePrefixContract": s._source_collection_stable_prefix_contract(),
        "dynamicDeltaContract": s._source_collection_dynamic_delta_contract(),
        "gate": {
            "status": gate_status,
            "passed": gate_status in {"satisfied", "disabled", "warning"},
            "hardBlock": hard_block,
            "reason": gate_reason,
            "checkedAt": s.utc_now_iso(),
        },
    }
    if gate_status == "blocked":
        s._record_workflow_event(
            "source_collection.prompt_cache_blocked",
            team_id,
            fields={
                "policyId": policy["policyId"],
                "requirement": requirement,
                "modelId": model_id,
                "requestedModelId": model_resolution.get("requestedModelId", ""),
                "modelResolutionStatus": model_resolution.get("status", ""),
                "promptCacheMode": prompt_cache_mode,
                "outcome": "blocked",
                "reason": gate_reason,
            },
        )
        raise s.TeamWorkflowOrchestrationError(
            f"{gate_reason} Knowledge collection requires prompt cache/KV reuse. "
            "Set prompt_cache.mode to automatic or explicit_cache_control before starting knowledge collection."
        )
    return policy


def _source_collection_prompt_cache_policy_ref(policy: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    gate = policy.get("gate") if isinstance(policy.get("gate"), dict) else {}
    return {
        "policyId": s._trim_text(policy.get("policyId"), max_length=160),
        "scope": s._trim_text(policy.get("scope"), max_length=120),
        "requirement": s._trim_text(policy.get("requirement"), max_length=80),
        "modelId": s._trim_text(policy.get("modelId"), max_length=160),
        "promptCacheMode": s._trim_text(policy.get("promptCacheMode"), max_length=80),
        "gateStatus": s._trim_text(gate.get("status"), max_length=80),
    }


def _source_collection_queries_for_role(search_plan: dict[str, Any], role: str) -> list[dict[str, Any]]:
    s = _service()
    queries = search_plan.get("queries")
    if not isinstance(queries, list):
        return []
    return [item for item in queries if isinstance(item, dict) and item.get("assignedAgentRole") == role]


def _source_collection_query_seeds(payload: dict[str, Any], scope: dict[str, Any], input_refs: list[str], *, topic: str, goal: str) -> list[str]:
    s = _service()
    seeds: list[str] = []
    for value in s._normalize_text_list(payload.get("querySeeds"), max_items=40, max_length=220):
        s._append_source_collection_seed(seeds, value)
    s._append_source_collection_seed(seeds, topic)
    for key in ("researchQuestion", "domain", "dataset", "benchmark", "organism", "method"):
        s._append_source_collection_seed(seeds, scope.get(key))
    for value in s._metadata_text_values(scope.get("keywords")):
        s._append_source_collection_seed(seeds, value)
    for value in s._metadata_text_values(scope.get("seedQueries")):
        s._append_source_collection_seed(seeds, value)
    for ref in input_refs:
        s._append_source_collection_seed(seeds, s._source_collection_seed_from_input_ref(ref))
    if not seeds:
        s._append_source_collection_seed(seeds, goal)
    if not seeds:
        s._append_source_collection_seed(seeds, "challenge cup research source collection")
    return seeds[:12]


def _source_collection_query_text(seed: str, *, source_type: str, language: str) -> str:
    s = _service()
    normalized_seed = s._trim_text(seed, max_length=220)
    normalized_source_type = s._trim_text(source_type, max_length=40).lower()
    normalized_language = s._trim_text(language, max_length=16).lower()
    if normalized_language.startswith("zh") or normalized_language in {"cn", "chinese"}:
        suffixes = {
            "paper": "论文",
            "review": "综述",
            "dataset": "数据集",
            "preprint": "预印本",
        }
        suffix = suffixes.get(normalized_source_type, normalized_source_type or "资料")
        return s._trim_text(f"{normalized_seed} {suffix}", max_length=260)
    suffixes = {
        "paper": "peer reviewed paper",
        "review": "review",
        "dataset": "dataset",
        "preprint": "preprint",
    }
    suffix = suffixes.get(normalized_source_type, normalized_source_type or "source")
    return s._trim_text(f"{normalized_seed} {suffix}", max_length=260)


def _source_collection_record_extraction_effective_texts(extraction: dict[str, Any], record: dict[str, Any]) -> list[str]:
    s = _service()
    texts: list[str] = []
    for key in (
        "valueSummary",
        "value_summary",
        "summary",
        "finding",
        "notes",
        "abstract",
        "usableContent",
        "usable_content",
    ):
        text = s._trim_text(extraction.get(key), max_length=2000)
        if text:
            texts.append(text)
    for key in ("keyFindings", "key_findings", "findings"):
        for item in s._normalize_text_list(extraction.get(key), max_items=12, max_length=300):
            if item:
                texts.append(item)
    record_summary = s._trim_text(record.get("summary"), max_length=2000)
    if record_summary:
        texts.append(record_summary)
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    for key in ("abstract", "description"):
        text = s._trim_text(metadata.get(key), max_length=2000)
        if text:
            texts.append(text)
    return texts


def _source_collection_record_extraction_has_effective_content(extraction: dict[str, Any], record: dict[str, Any]) -> bool:
    s = _service()
    negative_fragments = (
        "no abstract",
        "no summary",
        "no usable",
        "placeholder",
        "landing page",
        "没有摘要",
        "没有正文",
        "无有效内容",
        "无法验证",
        "仅有占位",
    )
    for text in s._source_collection_record_extraction_effective_texts(extraction, record):
        normalized = re.sub(r"\s+", " ", text.lower()).strip()
        if len(normalized) < 24:
            continue
        if any(fragment in normalized for fragment in negative_fragments):
            continue
        return True
    return False


def _source_collection_record_extraction_kept_status(extraction: dict[str, Any]) -> str:
    s = _service()
    decision = s._source_collection_stage_writeback_record_extraction_decision(extraction)
    has_defects = bool(
        s._normalize_text_list(
            extraction.get("defects")
            or extraction.get("limitations")
            or extraction.get("riskFlags")
            or extraction.get("risk_flags"),
            max_items=12,
            max_length=180,
        )
        or s._trim_text(extraction.get("followUpSuggestion") or extraction.get("follow_up_suggestion"), max_length=500)
    )
    if decision in s.SOURCE_COLLECTION_KEEP_WITH_NOTES_DECISIONS or has_defects:
        return "kept_with_notes"
    return "kept"


def _source_collection_record_extraction_metadata(
    extraction: dict[str, Any],
    *,
    record_id: str,
    task_id: str,
    run_id: str,
    stage_id: str,
    recorded_by_agent: str,
) -> dict[str, Any]:
    s = _service()
    value_summary = s._trim_text(extraction.get("valueSummary") or extraction.get("value_summary"), max_length=2000)
    defects = s._normalize_text_list(
        extraction.get("defects")
        or extraction.get("limitations")
        or extraction.get("riskFlags")
        or extraction.get("risk_flags"),
        max_items=12,
        max_length=180,
    )
    follow_up = s._trim_text(
        extraction.get("followUpSuggestion")
        or extraction.get("follow_up_suggestion")
        or extraction.get("nextStep")
        or extraction.get("next_step"),
        max_length=600,
    )
    decision = s._source_collection_stage_writeback_record_extraction_decision(extraction)
    content_extraction = {
        "status": s._source_collection_record_extraction_kept_status(extraction),
        "decision": decision,
        "valueSummary": value_summary,
        "defects": defects,
        "followUpSuggestion": follow_up,
        "summary": s._trim_text(
            value_summary
            or extraction.get("summary")
            or extraction.get("finding")
            or extraction.get("notes")
            or extraction.get("reason"),
            max_length=2000,
        ),
        "keyFindings": s._source_collection_extraction_key_finding_texts(extraction)
        or s._normalize_text_list(
            extraction.get("keyFindings") or extraction.get("key_findings") or extraction.get("findings"),
            max_items=12,
            max_length=240,
        ),
        "riskFlags": s._normalize_text_list(
            extraction.get("riskFlags") or extraction.get("risk_flags") or extraction.get("risks"),
            max_items=12,
            max_length=120,
        ),
        "evidenceRefs": s._normalize_ref_list(
            extraction.get("evidenceRefs") or extraction.get("evidence_refs"),
            max_items=24,
        ),
        "sourceRecordId": record_id,
        "taskId": task_id,
        "runId": s._trim_text(run_id, max_length=160),
        "stageId": stage_id,
        "recordedByAgent": recorded_by_agent,
        "recordedAt": s.utc_now_iso(),
    }
    evidence_ledger = s._source_collection_extraction_evidence_ledger(extraction)
    if evidence_ledger:
        content_extraction["evidenceLedger"] = evidence_ledger
        content_extraction["evidenceStatus"] = evidence_ledger["status"]
    return content_extraction


def _source_collection_record_id_suffix_lookup(records: list[dict[str, Any]]) -> dict[str, str]:
    s = _service()
    buckets: dict[str, set[str]] = {}
    for record in records:
        record_id = s._trim_text(record.get("recordId"), max_length=160)
        if not record_id:
            continue
        suffixes = {record_id}
        if "-" in record_id:
            suffixes.add(record_id.rsplit("-", 1)[-1])
        if len(record_id) >= 8:
            suffixes.add(record_id[-8:])
        for suffix in suffixes:
            if suffix:
                buckets.setdefault(suffix, set()).add(record_id)
    return {suffix: next(iter(values)) for suffix, values in buckets.items() if len(values) == 1}


def _source_collection_record_identity_or_record_key(record: dict[str, Any]) -> str:
    s = _service()
    identity_key = s._source_collection_record_identity_key(record)
    if identity_key:
        return identity_key
    record_id = s._trim_text(record.get("recordId"), max_length=160)
    return f"record:{record_id}" if record_id else ""


def _source_collection_record_is_excluded(team_id: str, run: dict[str, Any], record: dict[str, Any]) -> dict[str, Any] | None:
    s = _service()
    return s._source_collection_exclusion_match(
        team_id,
        run,
        s._source_collection_record_identity_or_record_key(record),
    )


def _source_collection_record_source_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    trace = record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {}
    return {
        "recordId": s._trim_text(record.get("recordId"), max_length=160),
        "title": s._trim_text(record.get("title"), max_length=260),
        "sourceType": s._trim_text(record.get("sourceType"), max_length=80),
        "sourceRef": s._trim_text(record.get("sourceRef"), max_length=500),
        "rawLocation": s._trim_text(record.get("rawLocation"), max_length=1000),
        "doi": s._source_collection_extract_doi(record.get("sourceRef"), record.get("rawLocation"), metadata.get("doi")),
        "containerTitle": s._trim_text(metadata.get("containerTitle") or metadata.get("container"), max_length=240),
        "queryId": s._trim_text(trace.get("queryId") or metadata.get("queryId"), max_length=160),
        "query": s._trim_text(trace.get("query") or metadata.get("query"), max_length=500),
    }


def _source_collection_resolve_prompt_cache_model(requested_model_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    s = _service()
    model_library = s._source_collection_model_library()
    requested_entry = model_library.get(requested_model_id) if requested_model_id else {}
    if isinstance(requested_entry, dict) and s._source_collection_prompt_cache_mode(requested_entry) in s.SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES:
        return requested_model_id, dict(requested_entry), {
            "status": "requested",
            "requestedModelId": requested_model_id,
            "reason": "",
        }

    candidates: list[tuple[tuple[int, str], str, dict[str, Any]]] = []
    for candidate_id, candidate_entry in model_library.items():
        if not isinstance(candidate_entry, dict):
            continue
        if s._source_collection_prompt_cache_mode(candidate_entry) not in s.SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES:
            continue
        if not s._source_collection_is_text_model(str(candidate_id), candidate_entry):
            continue
        candidates.append((s._source_collection_prompt_cache_model_score(str(candidate_id), candidate_entry), str(candidate_id), dict(candidate_entry)))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        resolved_id = candidates[0][1]
        resolved_entry = candidates[0][2]
        return resolved_id, resolved_entry, {
            "status": "fallback" if requested_model_id and resolved_id != requested_model_id else "auto",
            "requestedModelId": requested_model_id,
            "reason": "requested_model_unavailable" if requested_model_id and not requested_entry else "requested_model_prompt_cache_unsupported" if requested_model_id else "auto_selected",
        }

    if isinstance(requested_entry, dict) and requested_entry:
        return requested_model_id, dict(requested_entry), {
            "status": "unavailable",
            "requestedModelId": requested_model_id,
            "reason": "requested_model_prompt_cache_unsupported",
        }
    return requested_model_id, {}, {
        "status": "unavailable",
        "requestedModelId": requested_model_id,
        "reason": "requested_model_not_configured" if requested_model_id else "no_prompt_cache_model_configured",
    }


def _source_collection_result_from_crossref_item(item: dict[str, Any], *, fallback_source_type: str) -> dict[str, Any]:
    s = _service()
    doi = s._trim_text(item.get("DOI"), max_length=500)
    source_ref = f"https://doi.org/{doi}" if doi else s._trim_text(item.get("URL"), max_length=1000)
    title = s._first_crossref_text(item.get("title")) or doi or source_ref
    container_title = s._first_crossref_text(item.get("container-title"))
    issued = s._crossref_date(item.get("published-print")) or s._crossref_date(item.get("published-online")) or s._crossref_date(item.get("issued"))
    abstract = s._strip_html(s._trim_text(item.get("abstract"), max_length=5000))
    authors = s._crossref_authors(item.get("author"))
    crossref_type = s._trim_text(item.get("type"), max_length=80)
    source_type = s._source_collection_data_processing_source_type(fallback_source_type or crossref_type)
    summary_parts = [
        f"Container: {container_title}" if container_title else "",
        f"Published: {issued}" if issued else "",
        abstract,
    ]
    return {
        "title": title,
        "sourceRef": source_ref,
        "rawLocation": s._trim_text(item.get("URL"), max_length=1000) or source_ref,
        "summary": s._trim_text(" ".join(part for part in summary_parts if part), max_length=1600),
        "sourceType": source_type,
        "providerType": crossref_type,
        "metadata": {
            "doi": doi,
            "containerTitle": container_title,
            "issued": issued,
            "authors": authors,
            "crossrefType": crossref_type,
        },
        "qualitySignals": {
            "providerScore": item.get("score"),
            "hasDoi": bool(doi),
            "hasAbstract": bool(abstract),
        },
    }


def _source_collection_arxiv_atom_entries(payload: bytes | str) -> list[ET.Element]:
    """Parse an arXiv Atom feed body into its ``<entry>`` elements."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8", errors="replace")
    root = ET.fromstring(payload)
    return list(root.findall(f"{{{ARXIV_ATOM_NAMESPACE}}}entry"))


def _source_collection_result_from_arxiv_entry(entry: ET.Element, *, fallback_source_type: str) -> dict[str, Any]:
    """Map one arXiv Atom ``<entry>`` into the shared search-result shape.

    The abstract must land in ``summary``: downstream extraction produces the
    verbatim quotes from that field, so a title+URL-only result would starve
    the evidence pipeline.
    """
    s = _service()
    atom = f"{{{ARXIV_ATOM_NAMESPACE}}}"
    schema = f"{{{ARXIV_SCHEMA_NAMESPACE}}}"

    def _element_text(tag: str) -> str:
        raw = entry.findtext(tag) or ""
        return re.sub(r"\s+", " ", raw).strip()

    entry_id = s._trim_text(_element_text(f"{atom}id"), max_length=500)
    source_ref = entry_id or s._trim_text(_element_text(f"{atom}sourceRef"), max_length=1000)
    title = _element_text(f"{atom}title") or source_ref
    abstract = s._strip_html(_element_text(f"{atom}summary"))
    published = s._trim_text(_element_text(f"{atom}published"), max_length=80)
    updated = s._trim_text(_element_text(f"{atom}updated"), max_length=80)
    authors = [
        s._trim_text(re.sub(r"\s+", " ", author.findtext(f"{atom}name") or ""), max_length=200)
        for author in entry.findall(f"{atom}author")
    ]
    authors = [author for author in authors if author]
    doi = s._trim_text(_element_text(f"{schema}doi"), max_length=500)
    primary_category = ""
    primary_category_node = entry.find(f"{atom}category[@primary='true']")
    if primary_category_node is None:
        primary_category_node = entry.find(f"{atom}category")
    if primary_category_node is not None:
        primary_category = s._trim_text(primary_category_node.get("term"), max_length=120)
    source_type = s._source_collection_data_processing_source_type(fallback_source_type or "preprint")
    arxiv_id = ""
    if "/abs/" in entry_id:
        arxiv_id = s._trim_text(entry_id.rsplit("/abs/", 1)[-1], max_length=120)
    return {
        "title": title,
        "sourceRef": source_ref,
        "rawLocation": source_ref,
        "summary": s._trim_text(abstract, max_length=1600),
        "sourceType": source_type,
        "providerType": "arxiv_preprint",
        "metadata": {
            "arxivId": arxiv_id,
            "doi": doi,
            "published": published,
            "updated": updated,
            "authors": authors,
            "primaryCategory": primary_category,
        },
        "qualitySignals": {
            "hasDoi": bool(doi),
            "hasAbstract": bool(abstract),
        },
    }


def _source_collection_openalex_abstract(abstract_inverted_index: Any) -> str:
    """Rebuild abstract text from OpenAlex's ``abstract_inverted_index``.

    OpenAlex stores abstracts as a ``{word: [position, ...]}`` inverted index;
    the words are placed at their positions and joined in order to recover the
    original text.  The rebuilt abstract is the verbatim material downstream
    extraction quotes from, so this rebuild is load-bearing for the evidence
    pipeline.
    """
    if not isinstance(abstract_inverted_index, dict) or not abstract_inverted_index:
        return ""
    placements: list[tuple[int, str]] = []
    for word, positions in abstract_inverted_index.items():
        if not isinstance(positions, (list, tuple)):
            continue
        for position in positions:
            if isinstance(position, int) and not isinstance(position, bool):
                placements.append((int(position), str(word)))
    if not placements:
        return ""
    placements.sort(key=lambda pair: pair[0])
    return " ".join(word for _position, word in placements)


def _source_collection_result_from_openalex_work(work: dict[str, Any], *, fallback_source_type: str) -> dict[str, Any]:
    """Map one OpenAlex ``work`` object into the shared search-result shape.

    The rebuilt abstract must land in ``summary`` (with a ``hasAbstract``
    quality signal): downstream extraction produces the verbatim quotes from
    that field, so a title+URL-only result would starve the evidence pipeline.
    """
    s = _service()
    if not isinstance(work, dict):
        work = {}
    openalex_id = s._trim_text(work.get("id"), max_length=500)
    doi_url = s._trim_text(work.get("doi"), max_length=500)
    doi = s._source_collection_normalized_doi(doi_url)
    primary_location = work.get("primary_location") if isinstance(work.get("primary_location"), dict) else {}
    landing_page_url = s._trim_text(primary_location.get("landing_page_url"), max_length=1000)
    location_source = primary_location.get("source") if isinstance(primary_location.get("source"), dict) else {}
    venue = s._trim_text(location_source.get("display_name"), max_length=260)
    source_ref = doi_url or landing_page_url or openalex_id
    title = s._trim_text(work.get("title"), max_length=260) or source_ref
    abstract = s._strip_html(s._source_collection_openalex_abstract(work.get("abstract_inverted_index")))
    publication_date = s._trim_text(work.get("publication_date"), max_length=80)
    publication_year = work.get("publication_year") if isinstance(work.get("publication_year"), int) else ""
    authors: list[str] = []
    authorships = work.get("authorships") if isinstance(work.get("authorships"), list) else []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") if isinstance(authorship.get("author"), dict) else {}
        display_name = s._trim_text(author.get("display_name"), max_length=200)
        if display_name:
            authors.append(display_name)
    openalex_type = s._trim_text(work.get("type"), max_length=80)
    # OpenAlex calls journal articles just "article"; alias it onto the
    # Crossref-style vocabulary the shared source-type normalizer understands.
    if openalex_type == "article":
        openalex_type = "journal-article"
    source_type = s._source_collection_data_processing_source_type(fallback_source_type or openalex_type)
    return {
        "title": title,
        "sourceRef": source_ref,
        "rawLocation": landing_page_url or source_ref,
        "summary": s._trim_text(abstract, max_length=1600),
        "sourceType": source_type,
        "providerType": openalex_type,
        "metadata": {
            "openalexId": openalex_id,
            "doi": doi,
            "publicationDate": publication_date,
            "publicationYear": publication_year,
            "authors": authors,
            "venue": venue,
            "openalexType": openalex_type,
        },
        "qualitySignals": {
            "hasDoi": bool(doi),
            "hasAbstract": bool(abstract),
        },
    }


def _source_collection_result_identity_key(result: dict[str, Any]) -> str:
    s = _service()
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    quality_signals = result.get("qualitySignals") if isinstance(result.get("qualitySignals"), dict) else {}
    return s._source_collection_identity_key(
        source_ref=result.get("sourceRef"),
        raw_location=result.get("rawLocation"),
        doi=metadata.get("doi") or result.get("doi") or quality_signals.get("doi"),
        url=metadata.get("url") or result.get("url") or quality_signals.get("url"),
        title=result.get("title"),
        container=result.get("container") or metadata.get("containerTitle") or metadata.get("container") or quality_signals.get("containerTitle") or quality_signals.get("container"),
        published=result.get("published") or metadata.get("issued") or metadata.get("published") or quality_signals.get("issued") or quality_signals.get("published"),
    )


def _source_collection_role_assignment_inputs(queries: list[dict[str, Any]], roles: list[str], payload: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    assignments: list[dict[str, Any]] = []
    for role in roles:
        role_queries = s._source_collection_queries_for_role({"queries": queries}, role)
        prompt_cache_partition = ""
        for query in role_queries:
            execution = query.get("execution") if isinstance(query.get("execution"), dict) else {}
            prompt_cache_partition = s._trim_text(execution.get("promptCachePartition"), max_length=160)
            if prompt_cache_partition:
                break
        assignments.append(
            {
                "agentRole": role,
                "agentId": s._source_collection_agent_id(role, payload),
                "queryIds": [item["queryId"] for item in role_queries],
                "queryCount": len(role_queries),
                "promptCachePartition": prompt_cache_partition,
                "conversationTraceRequired": True,
                "expectedAction": s._source_collection_expected_action(role),
            }
        )
    return assignments


def _source_collection_run_belongs_to_team(run: dict[str, Any], team_id: str) -> bool:
    s = _service()
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    run_team_id = s._trim_text(scope.get("teamId") or metadata.get("teamId"), max_length=160)
    started_from = s._trim_text(metadata.get("startedFrom"), max_length=160)
    workflow_stage = s._trim_text(scope.get("workflowStage"), max_length=120)
    return run_team_id == team_id and (
        started_from == "team_workflow_source_collection"
        or workflow_stage == "knowledge_collection"
    )


def _source_collection_run_belongs_to_research_project(run: dict[str, Any], research_project_id: str) -> bool:
    """Keep source rounds inside their active research-project boundary.

    Legacy rounds predate research-project isolation. They remain visible only
    while the legacy project itself is active; an isolated project must never
    adopt a legacy or another project's usable historical round as its default.
    """

    s = _service()
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    run_project_id = s._trim_text(
        scope.get("researchProjectId") or metadata.get("researchProjectId"),
        max_length=160,
    )
    if run_project_id:
        return run_project_id == research_project_id
    return research_project_id == s.LEGACY_PROJECT_ID


def _source_collection_run_context_bundle(team_id: str, run_id: str) -> dict[str, Any]:
    s = _service()
    try:
        run = s.data_processing_service.get_processing_run(run_id)
        assignments_payload = s.data_processing_service.list_collection_assignments(run_id)
        records_payload = s.data_processing_service.list_records(run_id)
        run_status = s.data_processing_service.get_processing_status(run_id)
    except s.data_processing_service.DataProcessingError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = s._trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != team_id:
        raise s.TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")
    assignments = [item for item in list(assignments_payload.get("assignments") or []) if isinstance(item, dict)]
    all_records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    records, excluded_source_summary = s._source_collection_filter_active_records(team_id, run, all_records)
    source_candidates = s._source_collection_candidates_for_run(team_id, run_id)
    active_snapshot = s._source_collection_work_run_store().load_active_snapshot_for_run(
        s.SOURCE_COLLECTION_WORK_RUN_KIND,
        run_id,
    )
    active_snapshot = s._decorate_source_collection_work_run_snapshot(
        active_snapshot,
        team_id=team_id,
        run_id=run_id,
    )
    active_work_run = (
        active_snapshot
        if s._source_collection_background_snapshot_is_active(active_snapshot, team_id, run_id)
        else {}
    )
    return {
        "run": run,
        "assignments": assignments,
        "records": records,
        "allRecords": all_records,
        "excludedSourceSummary": excluded_source_summary,
        "runStatus": run_status,
        "sourceCandidates": source_candidates,
        "activeWorkRun": active_work_run,
    }


def _source_collection_run_has_usable_outputs(run: dict[str, Any]) -> bool:
    s = _service()
    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    processing_status = run.get("processingStatus") if isinstance(run.get("processingStatus"), dict) else {}
    processing_summary = processing_status.get("summary") if isinstance(processing_status.get("summary"), dict) else {}
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    for source in (summary, processing_summary, scope.get("sourceCollectionSummary"), metadata.get("sourceCollectionSummary"), scope, metadata):
        if not isinstance(source, dict):
            continue
        if any(
            s._source_collection_count(source.get(key)) > 0
            for key in ("recordCount", "rawRecordCount", "createdUniqueRecordCount", "sourceCandidateCount", "candidateCount", "importedCount")
        ):
            return True
    return False


def _source_collection_search_languages(value: Any) -> list[str]:
    s = _service()
    languages = s._normalize_text_list(value, max_items=8, max_length=16)
    return languages or list(s.SOURCE_COLLECTION_DEFAULT_SEARCH_LANGUAGES)


def _source_collection_search_plan_ref(search_plan: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    prompt_cache_policy = search_plan.get("promptCachePolicy") if isinstance(search_plan.get("promptCachePolicy"), dict) else {}
    return {
        "planId": s._trim_text(search_plan.get("planId"), max_length=128),
        "planKind": s._trim_text(search_plan.get("planKind"), max_length=120) or "source_collection_data_search",
        "status": s._trim_text(search_plan.get("status"), max_length=80) or "planned",
        "queryCount": s._normalize_int(search_plan.get("queryCount"), default=0, minimum=0, maximum=s.SOURCE_COLLECTION_MAX_QUERIES),
        "externalSearchTriggered": False,
        "promptCachePolicyId": s._trim_text(prompt_cache_policy.get("policyId"), max_length=160),
        "promptCacheRequirement": s._trim_text(prompt_cache_policy.get("requirement"), max_length=80),
        "promptCacheGateStatus": s._trim_text((prompt_cache_policy.get("gate") or {}).get("status") if isinstance(prompt_cache_policy.get("gate"), dict) else "", max_length=80),
    }


def _source_collection_seed_from_input_ref(value: Any) -> str:
    s = _service()
    text = s._trim_text(value, max_length=220)
    lowered = text.lower()
    for prefix in ("seed-query:", "query:", "keyword:", "topic:"):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def _source_collection_source_category(
    *,
    source_kind: str,
    source_ref: str,
    raw_location: str,
    source_url: str,
    source_path: str,
) -> str:
    s = _service()
    normalized = str(source_kind or "").strip().lower()
    refs = " ".join([source_ref, raw_location, source_url, source_path]).lower()
    if "dataset" in normalized:
        return "dataset"
    if ".pdf" in refs or "application/pdf" in refs:
        return "pdf"
    if source_path and not s._looks_like_url(source_path):
        return "local_file"
    if normalized in {"file", "manual", "note"}:
        return "local_file"
    if s._source_collection_extract_doi(source_ref, source_url, raw_location) or s._looks_like_url(source_ref) or s._looks_like_url(source_url):
        return "paper_web"
    return "missing"


def _source_collection_source_types(value: Any) -> list[str]:
    s = _service()
    source_types = s._normalize_text_list(value, max_items=16, max_length=40)
    return source_types or list(s.SOURCE_COLLECTION_DEFAULT_SOURCE_TYPES)


def _source_collection_stable_prefix_contract() -> dict[str, Any]:
    s = _service()
    return {
        "cacheableBlocks": [
            "ai科学研究团队身份与知识搜集阶段规则",
            "source collection assignment/output/DataRecord/source_manifest schema",
            "禁止直接写正式 Team Knowledge/RAG/official graph 的边界",
            "功能 Agent 职责、回写合同和质量审查规则",
        ],
        "forbiddenDynamicFields": [
            "currentQuery",
            "currentUrl",
            "downloadedText",
            "rawPageContent",
            "latestToolResult",
            "fullConversationHistory",
        ],
        "expectedUsage": "Stable prefix is cacheable; each step sends only the current query/result refs as dynamic delta.",
    }


def _source_collection_stage_id_for_agent_role(agent_role: str) -> str:
    s = _service()
    normalized_role = s._normalize_source_collection_agent_role(agent_role)
    for stage_id, roles in s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES.items():
        if normalized_role in roles:
            return stage_id
    return "finding"


def _source_collection_stage_invalid_source_record(source: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    doi = s._source_collection_extract_doi(
        source.get("doi"),
        source.get("DOI"),
        source.get("locator"),
        source.get("sourceRef"),
        source.get("sourceUrl"),
        source.get("url"),
    )
    source_ref = s._trim_text(
        source.get("sourceRef")
        or source.get("source_ref")
        or source.get("sourceUrl")
        or source.get("url")
        or source.get("locator"),
        max_length=2000,
    )
    if doi and not source_ref:
        source_ref = f"https://doi.org/{doi}"
    raw_location = s._trim_text(source.get("rawLocation") or source.get("raw_location") or source.get("url"), max_length=2000)
    metadata = s._normalize_metadata(source.get("metadata"))
    if doi:
        metadata["doi"] = doi
    container = s._trim_text(source.get("container") or source.get("venue") or source.get("journal"), max_length=240)
    if container:
        metadata["containerTitle"] = container
    published = s._trim_text(source.get("published") or source.get("year"), max_length=80)
    if published:
        metadata["published"] = published
    return {
        "recordId": s._trim_text(source.get("recordId") or source.get("record_id"), max_length=160),
        "title": s._trim_text(source.get("title"), max_length=260),
        "sourceType": s._trim_text(source.get("sourceType") or source.get("type") or "invalid_source", max_length=80),
        "sourceRef": source_ref,
        "rawLocation": raw_location or source_ref,
        "metadata": metadata,
    }


def _source_collection_stage_quality_materialization_child_summary(summary: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    return {
        "status": s._trim_text(summary.get("status"), max_length=80),
        "assessedCandidateCount": s._source_collection_count(summary.get("assessedCandidateCount")),
        "approvedCandidateCount": s._source_collection_count(summary.get("approvedCandidateCount")),
        "needsRevisionCandidateCount": s._source_collection_count(summary.get("needsRevisionCandidateCount")),
        "rejectedCandidateCount": s._source_collection_count(summary.get("rejectedCandidateCount")),
        "skippedCandidateCount": s._source_collection_count(summary.get("skippedCandidateCount")),
        "failedCandidateCount": s._source_collection_count(summary.get("failedCandidateCount")),
        "assessedCandidates": s._bounded_log_items(summary.get("assessedCandidates"), ("candidateId", "decision", "assessmentId"), max_items=40),
        "skippedCandidates": s._bounded_log_items(summary.get("skippedCandidates"), ("candidateId", "reason"), max_items=40),
        "failedCandidates": s._bounded_log_items(summary.get("failedCandidates"), ("candidateId", "reason", "errorType", "error"), max_items=24),
    }


def _source_collection_stage_records_for_run(run_id: str) -> list[dict[str, Any]]:
    s = _service()
    try:
        payload = s.data_processing_service.list_records(run_id)
    except s.data_processing_service.DataProcessingError:
        return []
    return [item for item in list(payload.get("records") or []) if isinstance(item, dict)]


def _source_collection_stage_retry_ancestor_results(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
) -> list[dict[str, Any]]:
    s = _service()
    task_id = s._trim_text(task.get("taskId"), max_length=160)
    parent_task_id = s._trim_text(task.get("retrySourceTaskId"), max_length=160)
    seen = {task_id} if task_id else set()
    results: list[dict[str, Any]] = []
    while parent_task_id and parent_task_id not in seen and len(results) < 24:
        seen.add(parent_task_id)
        parent_task, parent_run_id = s._find_source_collection_stage_session_task_by_id(team_id, parent_task_id)
        if parent_task is None or parent_run_id != run_id:
            break
        parent_writeback = parent_task.get("writeback") if isinstance(parent_task.get("writeback"), dict) else {}
        parent_result = parent_writeback.get("result") if isinstance(parent_writeback.get("result"), dict) else {}
        if not parent_result and isinstance(parent_task.get("result"), dict):
            parent_result = parent_task["result"]
        if parent_result:
            results.append(parent_result)
        parent_task_id = s._trim_text(parent_task.get("retrySourceTaskId"), max_length=160)
    return list(reversed(results))


def _source_collection_stage_round_ref_for_run(team_id: str, run_id: str) -> dict[str, Any]:
    s = _service()
    normalized_run_id = s._trim_text(run_id, max_length=160)
    if not normalized_run_id:
        return {}
    with s._WORKFLOW_LOCK:
        store = s._load_stage_round_store(team_id)
    rounds = [
        item for item in s._stage_rounds(store)
        if isinstance(item, dict)
        and str(item.get("stageType") or "") == "knowledge_collection"
        and normalized_run_id in {str(source_run_id) for source_run_id in list(item.get("sourceRunIds") or [])}
    ]
    latest_round = s._latest_stage_round(rounds)
    if not latest_round:
        return {}
    return {
        "stageRoundId": s._trim_text(latest_round.get("stageRoundId"), max_length=160),
        "stageType": "knowledge_collection",
        "roundNumber": s._source_collection_count(latest_round.get("roundNumber")),
        "status": s._trim_text(latest_round.get("status"), max_length=80),
        "sourceRunIds": [str(item) for item in list(latest_round.get("sourceRunIds") or []) if str(item or "").strip()],
        "updatedAt": s._trim_text(latest_round.get("updatedAt"), max_length=120),
    }


def _source_collection_stage_task_has_evidence_gaps(task: dict[str, Any] | None) -> bool:
    s = _service()
    if not isinstance(task, dict) or not task:
        return False
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    materialized = (
        writeback.get("materializedContentExtraction")
        if isinstance(writeback.get("materializedContentExtraction"), dict)
        else {}
    )
    if s._source_collection_count(materialized.get("missingEvidenceAnchorCount")) > 0:
        return True
    coverage = s._source_collection_stage_task_coverage_summary(task)
    return bool(
        isinstance(coverage, dict)
        and bool(coverage.get("applicable"))
        and bool(coverage.get("complete"))
        and coverage.get("blockedCandidateIds")
    )


def _source_collection_run_owner_research_project_id(team_id: str, run_id: str) -> str:
    """Resolve the owning research project of a source-collection run.

    Authority: the data_processing run record (scope/metadata.researchProjectId)
    frozen at run start. Returns "" when the run record is unavailable so
    callers keep the historical active-project behavior.
    """

    s = _service()
    normalized_run_id = s._trim_text(run_id, max_length=160)
    if not normalized_run_id:
        return ""
    try:
        # 轻量读取 run.json 的 scope/metadata，不触发 records/status 重算。
        run_identity = s.data_processing_service.get_processing_run_scope(normalized_run_id)
    except Exception:  # noqa: BLE001 - missing/unreadable run keeps active-project behavior
        return ""
    scope = run_identity.get("scope") if isinstance(run_identity.get("scope"), dict) else {}
    metadata = run_identity.get("metadata") if isinstance(run_identity.get("metadata"), dict) else {}
    return s._trim_text(
        scope.get("researchProjectId") or metadata.get("researchProjectId"),
        max_length=160,
    )


def _resolve_candidate_store_write_run(team_id: str, run_id: str) -> str:
    """Resolve the candidate-store write scope for a caller-supplied authority run.

    Workflow candidates created while processing a source-collection run must
    land in the run owner project's store (SCI-091 steward-pack incident: the
    pack materialized into whichever project happened to be active). Returns
    the normalized run id once the owner project resolves so callers use the
    owner-scoped store. Returns "" when no run context was supplied (the
    historical active-store behavior) — and also when a supplied run cannot be
    resolved to an owner project (legacy/deleted run record): the historical
    active-store target is kept, but a warning event records the explicit
    reason so the drift is never silent. No new fallback path is introduced.
    """

    s = _service()
    normalized_run_id = s._trim_text(run_id, max_length=160)
    if not normalized_run_id:
        return ""
    owner_project_id = s._source_collection_run_owner_research_project_id(team_id, normalized_run_id)
    if not owner_project_id:
        s._record_workflow_event(
            "candidate.store_owner_project_unresolved",
            team_id,
            fields={
                "runId": normalized_run_id,
                "reason": "authority_run_has_no_resolvable_owner_research_project",
                "storeTarget": "active_project",
            },
            level="warning",
            outcome="degraded",
        )
        return ""
    return normalized_run_id


def _source_collection_run_workflow_root(team_id: str, run_id: str) -> Path:
    """Workflow root resolved by the run owner project (fallback: active project).

    Stage task ledgers, candidate stores, and run artifact directories must all
    live under the run owner project; the team's *active* project drifts when
    another experiment is activated while an older run is still being written.
    """

    s = _service()
    owner_project_id = s._source_collection_run_owner_research_project_id(team_id, run_id)
    if owner_project_id:
        try:
            from core.web.services.team_workflow.research_projects import (
                resolve_research_project_workspace_root,
            )

            return resolve_research_project_workspace_root(team_id, owner_project_id)
        except Exception:  # noqa: BLE001 - unknown project id falls back to active root
            pass
    return s._team_workflow_root(team_id)


def _source_collection_task_store_search_roots(team_id: str) -> list[Path]:
    """All plausible ``source_collection_runs`` roots for cross-run lookups.

    Covers the active project root (historical default), every isolated
    research-project root, and the legacy base root, so tasks stored under a
    pre-fix wrong project stay discoverable.
    """

    s = _service()
    roots: list[Path] = [s._team_workflow_root(team_id) / "source_collection_runs"]
    try:
        from core.web.services.team_workflow.research_projects import (
            formal_team_workspace_root,
        )

        base_root = formal_team_workspace_root(team_id)
    except Exception:  # noqa: BLE001 - unknown team keeps the active root only
        return roots
    candidates = [
        base_root / "source_collection_runs",
        *sorted(
            (child / "workspace" / "source_collection_runs")
            for child in (base_root / "research_projects").glob("*")
            if (child / "workspace" / "source_collection_runs").is_dir()
        ),
    ]
    for candidate in candidates:
        if candidate not in roots:
            roots.append(candidate)
    return roots


def _source_collection_storage_artifact_paths(team_id: str, run_id: str) -> dict[str, Path]:
    s = _service()
    normalized_team_id = s._safe_token(team_id, default="team", max_length=96)
    normalized_run_id = s._safe_token(run_id, default="run", max_length=96)
    run_directory = (
        s._source_collection_run_workflow_root(team_id, run_id)
        / "source_collection_runs"
        / normalized_run_id
    )
    data_processing_directory = s.developer_sandbox.seeded_sandbox_workspace_path(
        s._project_root(),
        "data_processing",
        "runs",
        normalized_run_id,
    )
    return {
        "runDirectory": run_directory,
        "artifactsDirectory": run_directory / "artifacts",
        "searchPlanPath": run_directory / "search_plan.json",
        "searchEventsPath": run_directory / "search_events.jsonl",
        "recordsPath": run_directory / "records.jsonl",
        "candidatesPath": run_directory / "candidates.jsonl",
        "candidateStorePath": s._candidate_store_path(team_id, run_id),
        "dataProcessingRunPath": data_processing_directory / "run.json",
        "dataProcessingRecordsPath": data_processing_directory / "records.jsonl",
    }


def _source_collection_storage_artifacts(team_id: str, run_id: str) -> dict[str, str]:
    s = _service()
    return {
        key: s._relative_path(path)
        for key, path in s._source_collection_storage_artifact_paths(team_id, run_id).items()
    }


def _source_collection_storage_refs(run: dict[str, Any]) -> list[str]:
    s = _service()
    storage = run.get("storage") if isinstance(run.get("storage"), dict) else {}
    return [
        s._trim_text(storage.get("recordsPath"), max_length=240),
        s._trim_text(storage.get("collectionOutputsPath"), max_length=240),
    ]


def _source_collection_storage_target_path(team_id: str, run_id: str, target: str) -> Path:
    s = _service()
    paths = s._source_collection_storage_artifact_paths(team_id, run_id)
    target_to_path = {
        "run_directory": paths["runDirectory"],
        "artifacts_directory": paths["artifactsDirectory"],
        "search_plan": paths["searchPlanPath"],
        "search_events": paths["searchEventsPath"],
        "records": paths["recordsPath"],
        "candidates": paths["candidatesPath"],
        "candidate_store": paths["candidateStorePath"],
        "data_processing_run": paths["dataProcessingRunPath"],
        "data_processing_records": paths["dataProcessingRecordsPath"],
    }
    path = target_to_path.get(target)
    if path is None:
        raise s.TeamWorkflowOrchestrationError(f"Unsupported source collection storage target: {target or '<empty>'}")
    return s._ensure_project_child(path)


def _source_collection_team_identity_snapshot(team_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    try:
        with s.team_service._TEAM_LOCK:  # type: ignore[attr-defined]
            state = s.team_service._load_index()  # type: ignore[attr-defined]
            team = s.team_service._find_team(state, normalized_team_id)  # type: ignore[attr-defined]
    except Exception:
        team = None
    if isinstance(team, dict):
        return {
            "teamId": normalized_team_id,
            "name": s._trim_text(team.get("name"), max_length=160),
            "linkedChatRoomId": s._trim_text(team.get("linkedChatRoomId"), max_length=160),
        }
    s.team_service.assert_team_exists(normalized_team_id)
    return {"teamId": normalized_team_id, "name": "", "linkedChatRoomId": ""}


def _source_collection_team_member_snapshot(team_id: str) -> list[dict[str, Any]]:
    s = _service()
    try:
        with s.team_service._TEAM_LOCK:  # type: ignore[attr-defined]
            state = s.team_service._load_index()  # type: ignore[attr-defined]
            team = s.team_service._find_team(state, team_id)  # type: ignore[attr-defined]
    except Exception:
        try:
            team = s.team_service.get_team(team_id)
        except Exception:
            team = {}
    return [
        dict(member)
        for member in list((team or {}).get("members") or [])
        if isinstance(member, dict)
    ]


def _source_collection_work_run_snapshot_is_stale(snapshot: dict[str, Any] | None) -> bool:
    s = _service()
    if not isinstance(snapshot, dict):
        return False
    if snapshot.get("dataRunExists") is False:
        return True
    return bool([item for item in list(snapshot.get("staleReasons") or []) if s._trim_text(item, max_length=160)])


def _source_collection_work_run_store() -> Any:
    s = _service()
    return s.work_run_store.WorkRunStore(root=s.work_run_store.WORK_RUNS_DIR)


def _source_collection_work_run_terminal_phase(result: dict[str, Any]) -> str:
    s = _service()
    status = s._source_collection_work_run_terminal_status(result)
    if status == "failed":
        return "failed"
    if status == "cancelled":
        return "cancelled"
    if status == "needs_continue":
        return "waiting_for_next_batch"
    return "completed"


def _source_collection_work_run_terminal_status(result: dict[str, Any]) -> str:
    s = _service()
    if str(result.get("status") or "").strip().lower() == "cancelled":
        return "cancelled"
    if str(result.get("status") or "") == "duplicates_skipped":
        return "completed"
    if s._source_collection_count(result.get("failedQueryCount")) and not s._source_collection_count(result.get("executedQueryCount")):
        return "failed"
    if bool(result.get("hasMore")) or s._source_collection_count(result.get("remainingQueryCount")):
        return "needs_continue"
    source_collection_summary = result.get("sourceCollectionSummary") if isinstance(result.get("sourceCollectionSummary"), dict) else {}
    if s._source_collection_count(source_collection_summary.get("searchOpenAssignmentCount")):
        return "needs_continue"
    return "completed"


def _source_collection_work_run_terminal_summary(result: dict[str, Any]) -> str:
    s = _service()
    if s._source_collection_work_run_terminal_status(result) == "cancelled":
        return "资料搜索已由操作员停止。"
    if s._source_collection_work_run_terminal_status(result) == "failed":
        return "资料搜索执行失败，等待检查搜索错误。"
    record_count = s._source_collection_count(result.get("recordCount"))
    imported_count = s._source_collection_count(result.get("importedCount"))
    skipped_duplicate_count = s._source_collection_count(result.get("skippedDuplicateCount"))
    if str(result.get("status") or "") == "duplicates_skipped":
        return f"本轮资料搜索完成，跳过 {skipped_duplicate_count} 条重复资料，未新增资料。"
    if s._source_collection_work_run_terminal_status(result) == "needs_continue":
        return f"本轮已写入 {record_count} 条资料、导入 {imported_count} 个候选、跳过 {skipped_duplicate_count} 条重复资料，仍有任务可继续。"
    return f"本轮资料搜索完成，写入 {record_count} 条资料、导入 {imported_count} 个候选、跳过 {skipped_duplicate_count} 条重复资料。"


def _source_collection_workflow_kind(payload: dict[str, Any], team: dict[str, Any]) -> str:
    s = _service()
    raw = s._safe_token(
        payload.get("workflowKind") or payload.get("workflowPurpose") or team.get("teamKind") or "",
        default=s.WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH,
        max_length=80,
    )
    if raw == "knowledge_expansion":
        return s.WORKFLOW_KIND_KNOWLEDGE_EXPANSION
    return s.WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH


def _source_collection_writeback_contract(team_id: str, run_id: str) -> dict[str, Any]:
    s = _service()
    run_ref = s._trim_text(run_id, max_length=128) or "{runId}"
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "target": "data_processing.collection_output.records",
        "recordContract": {
            "requiredAnyOf": ["sourceRef", "rawLocation", "title"],
            "recordFields": ["sourceType", "sourceRef", "rawLocation", "title", "summary", "metadata", "qualitySignals", "collectionTrace"],
            "collectionTraceFields": ["planId", "queryId", "assignmentId", "agentRole"],
        },
        "candidateImport": {
            "targetCandidateType": "source_manifest",
            "route": f"/api/teams/{team_id}/workflow-orchestration/data-processing/runs/{run_ref}/records/{{recordId}}/source-candidate",
            "idempotencyKey": "metadata.importedFromDataRecord.recordId",
        },
        "formalKnowledgeWrites": False,
        "ragWrites": False,
        "officialGraphWrites": False,
    }


def _source_kind_from_data_record(source_type: str, source_ref: str, raw_location: str) -> str:
    s = _service()
    if source_type in {"paper", "dataset", "file", "url", "api", "note", "manual"}:
        return source_type
    if s._looks_like_url(source_ref):
        return "url"
    if raw_location or source_ref:
        return "file"
    return "unknown"


def _stage_rounds(store: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    return [item for item in list(store.get("rounds") or []) if isinstance(item, dict)]


def _stage_source_collection_payload(stage_round: dict[str, Any], payload: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    scope = s._normalize_metadata(payload.get("scope"))
    scope.update(
        {
            "workflowStage": "knowledge_collection",
            "researchStageRoundId": stage_round["stageRoundId"],
            "researchStageRoundNumber": stage_round["roundNumber"],
            "uiEntry": s._trim_text(scope.get("uiEntry"), max_length=120) or "teams_research_stage_launcher",
            "upstreamRoundIds": list(stage_round.get("upstreamRoundIds") or []),
        }
    )
    roles = s._normalize_source_collection_roles(payload.get("agentRoles"))
    return {
        "title": stage_round["title"],
        "topic": stage_round["topic"],
        "goal": stage_round["goal"],
        "ownerAgentId": stage_round["ownerAgentId"],
        "requestedByAgent": stage_round["requestedByAgent"],
        "agentRoles": payload.get("agentRoles") or list(s.SOURCE_COLLECTION_DEFAULT_AGENT_ROLES),
        "agentIds": payload.get("agentIds") if isinstance(payload.get("agentIds"), dict) else s._source_collection_team_agent_ids(team, roles, payload),
        "inputRefs": list(stage_round.get("inputRefs") or []),
        "querySeeds": list(stage_round.get("querySeeds") or []),
        "searchLanguages": list(stage_round.get("searchLanguages") or []),
        "sourceTypes": list(stage_round.get("sourceTypes") or []),
        "maxResultsPerQuery": int(stage_round.get("maxResultsPerQuery") or s.SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY),
        "promptCachePolicy": payload.get("promptCachePolicy") if isinstance(payload.get("promptCachePolicy"), dict) else {},
        "scope": scope,
    }


def _sync_source_collection_stage_round_from_latest_work_run(team_id: str, run_id: str) -> dict[str, Any] | None:
    s = _service()
    latest = s.load_source_collection_work_run_summary().get("latest")
    if not isinstance(latest, dict) or str(latest.get("runId") or "") != run_id:
        return None
    latest_status = str(latest.get("status") or "").lower()
    if latest_status in {"queued", "running"}:
        return None
    result = {
        "status": latest_status,
        "provider": s.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
        "executedQueryCount": s._source_collection_count(latest.get("executedQueryCount")),
        "failedQueryCount": s._source_collection_count(latest.get("failedQueryCount")),
        "recordCount": s._source_collection_count(latest.get("recordCount")),
        "importedCount": s._source_collection_count(latest.get("importedCount")),
        "skippedDuplicateCount": s._source_collection_count(latest.get("skippedDuplicateCount")),
        "remainingQueryCount": s._source_collection_count(latest.get("searchOpenAssignmentCount")),
        "hasMore": latest_status == "needs_continue",
        "sourceCollectionSummary": latest.get("sourceCollection") if isinstance(latest.get("sourceCollection"), dict) else {},
    }
    synced = s._sync_source_collection_stage_round_after_search(
        team_id,
        run_id,
        result,
        terminal_status=latest_status or "completed",
        terminal_summary=s._trim_text(latest.get("summary"), max_length=500) or "资料搜索已结束。",
    )
    if synced is not None:
        s._record_workflow_event(
            "research_stage_round.source_collection_search_recovered_from_work_run",
            team_id,
            fields={
                "runId": run_id,
                "stageRoundId": synced.get("stageRoundId", ""),
                "status": synced.get("status", ""),
                "searchStatus": latest_status or "completed",
                "recordCount": s._source_collection_count(latest.get("recordCount")),
                "importedCount": s._source_collection_count(latest.get("importedCount")),
                "remainingQueryCount": s._source_collection_count(latest.get("searchOpenAssignmentCount")),
            },
        )
    return synced


def _update_source_candidate_content_extraction(
    team_id: str,
    candidate_id: str,
    content_extraction: dict[str, Any],
    *,
    run_id: str = "",
) -> None:
    s = _service()
    normalized_candidate_id = s._trim_text(candidate_id, max_length=160)
    if not normalized_candidate_id:
        return
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(team_id, run_id=run_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
        changed = False
        for candidate in candidates:
            if s._trim_text(candidate.get("candidateId"), max_length=160) != normalized_candidate_id:
                continue
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            metadata["contentExtraction"] = s._normalize_metadata(content_extraction)
            candidate["metadata"] = metadata
            candidate["updatedAt"] = s.utc_now_iso()
            changed = True
            break
        if changed:
            candidate_store["updatedAt"] = s.utc_now_iso()
            s._write_json(s._candidate_store_path(team_id, run_id), candidate_store)


def _validate_source_manifest(candidate: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    issues: list[dict[str, str]] = []
    source_kind = s._trim_text(candidate.get("sourceKind"), max_length=80)
    source_url = s._trim_text(candidate.get("sourceUrl"), max_length=2000)
    source_path = s._trim_text(candidate.get("sourcePath"), max_length=2000)
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    metadata_path = s._trim_text(metadata.get("path") or metadata.get("sourcePath"), max_length=2000)
    metadata_sha = s._trim_text(metadata.get("sha256") or metadata.get("hash"), max_length=128)
    sha256 = s._trim_text(candidate.get("sha256"), max_length=128) or metadata_sha
    allowed = candidate.get("allowedForAnalysis")
    if allowed is None and "allowedForAnalysis" in metadata:
        allowed = s._normalize_optional_bool(metadata.get("allowedForAnalysis"))
    page_scope = s._trim_text(candidate.get("pageScope") or metadata.get("pageScope"), max_length=160)
    if not source_kind or source_kind == "unknown":
        issues.append({"severity": "warning", "code": "unknown_source_kind", "message": "sourceKind should identify pdf, paper, note, or competition_doc."})
    if not (source_url or source_path or metadata_path):
        issues.append({"severity": "error", "code": "missing_source_location", "message": "source_manifest requires sourceUrl, sourcePath, or metadata.path."})
    is_pdf = source_kind == "pdf" or source_path.lower().endswith(".pdf") or metadata_path.lower().endswith(".pdf")
    if is_pdf:
        if not (source_path or metadata_path):
            issues.append({"severity": "error", "code": "missing_pdf_path", "message": "PDF source_manifest requires sourcePath or metadata.path."})
        if not sha256:
            issues.append({"severity": "error", "code": "missing_sha256", "message": "PDF source_manifest requires sha256 before screening."})
        if allowed is not True:
            issues.append({"severity": "error", "code": "analysis_not_allowed", "message": "PDF source_manifest requires allowedForAnalysis=true."})
        if not page_scope:
            issues.append({"severity": "warning", "code": "missing_page_scope", "message": "PDF source_manifest should include pageScope for later citation anchors."})
        extraction = metadata.get("sourceExtraction") if isinstance(metadata.get("sourceExtraction"), dict) else {}
        if extraction:
            extraction_status = s._trim_text(extraction.get("status"), max_length=80)
            if extraction_status == "failed":
                issues.append({"severity": "error", "code": "source_extraction_failed", "message": "PDF source_manifest extraction failed and needs confirmation before screening."})
            elif extraction_status == "extracted" and not isinstance(extraction.get("pageAnchors"), list):
                issues.append({"severity": "error", "code": "missing_page_anchors", "message": "PDF source_manifest extraction must include pageAnchors."})
    return issues


def _write_source_collection_exclusion_store(team_id: str, store: dict[str, Any]) -> None:
    s = _service()
    payload = dict(store)
    payload["schemaVersion"] = s._source_collection_count(payload.get("schemaVersion")) or s.SCHEMA_VERSION
    payload["teamId"] = team_id
    payload["entries"] = [item for item in list(payload.get("entries") or []) if isinstance(item, dict)]
    payload["updatedAt"] = s.utc_now_iso()
    s._write_json(s._source_collection_exclusion_store_path(team_id), payload)


def _write_source_collection_search_plan(team_id: str, run_id: str, search_plan: dict[str, Any]) -> None:
    s = _service()
    paths = s._source_collection_storage_artifact_paths(team_id, run_id)
    paths["runDirectory"].mkdir(parents=True, exist_ok=True)
    paths["artifactsDirectory"].mkdir(parents=True, exist_ok=True)
    s._write_json(paths["searchPlanPath"], search_plan)
    for path_key in ("searchEventsPath", "recordsPath", "candidatesPath"):
        paths[path_key].touch(exist_ok=True)


def get_source_collection_exclusion_ledger(team_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.assert_team_exists(normalized_team_id)
    with s._WORKFLOW_LOCK:
        store = s._load_source_collection_exclusion_store(normalized_team_id)
    entries = [dict(item) for item in list(store.get("entries") or []) if isinstance(item, dict)]
    entries.sort(key=lambda item: str(item.get("updatedAt") or item.get("lastSeenAt") or ""), reverse=True)
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "excludedCount": len(entries),
        "entries": entries,
        "storagePath": s._relative_path(s._source_collection_exclusion_store_path(normalized_team_id)),
        "updatedAt": s._trim_text(store.get("updatedAt"), max_length=120),
    }
