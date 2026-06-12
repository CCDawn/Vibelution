"""Clean legacy memory knowledge records that bypass central source governance.

The script defaults to dry-run. Pass --apply to rewrite JSONL files and remove
stale vector-index records. Reports intentionally include only ids, paths, and
reasons; they do not copy knowledge bodies or original source content.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


JSONL_FILES = {
    "sourceArtifacts": "source_artifacts.jsonl",
    "proposals": "refinement_proposals.jsonl",
    "batches": "batches.jsonl",
    "items": "items.jsonl",
    "ratingSuggestions": "rating_suggestions.jsonl",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean legacy memory source-governance records.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--apply", action="store_true", help="Apply cleanup. Without this flag the script only reports.")
    parser.add_argument(
        "--report-dir",
        default="workspace/knowledge/cleanup_reports",
        help="Directory for the cleanup report, relative to root unless absolute.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    report_dir = Path(args.report_dir)
    if not report_dir.is_absolute():
        report_dir = root / report_dir
    report_dir = report_dir.resolve()
    _ensure_under_root(root, report_dir)

    report = clean(root, apply=args.apply)
    report["reportPath"] = _relative_path(root, _write_report(root, report_dir, report, apply=args.apply))
    print(json.dumps(_summary(report), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def clean(root: Path, *, apply: bool) -> dict[str, Any]:
    central_source_ids = _load_central_source_ids(root)
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "mode": "apply" if apply else "dry-run",
        "generatedAt": _utc_now_iso(),
        "root": str(root),
        "centralSourceCount": len(central_source_ids),
        "owners": [],
        "vectorIndex": {
            "removedRecordCount": 0,
            "keptRecordCount": 0,
            "records": [],
        },
        "summary": {},
    }
    valid_item_record_ids: set[str] = set()

    for owner in _iter_owner_roots(root):
        owner_report, owner_valid_items = _clean_owner(root, owner, central_source_ids, apply=apply)
        if owner_report["changed"]:
            report["owners"].append(owner_report)
        valid_item_record_ids.update(owner_valid_items)

    report["vectorIndex"] = _clean_vector_index(root, central_source_ids, valid_item_record_ids, apply=apply)
    report["summary"] = _build_summary(report)
    return report


def _clean_owner(
    root: Path,
    owner: dict[str, Any],
    central_source_ids: set[str],
    *,
    apply: bool,
) -> tuple[dict[str, Any], set[str]]:
    owner_root = Path(owner["root"])
    loaded = {
        key: _read_jsonl(owner_root / filename)
        for key, filename in JSONL_FILES.items()
    }
    owner_report: dict[str, Any] = {
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "root": _relative_path(root, owner_root),
        "changed": False,
        "files": {},
    }

    source_rows, source_removed, valid_sources = _filter_sources(
        loaded["sourceArtifacts"]["records"],
        central_source_ids,
    )
    source_removed.extend(loaded["sourceArtifacts"]["invalid"])
    _record_file_report(owner_report, "sourceArtifacts", owner_root / JSONL_FILES["sourceArtifacts"], len(loaded["sourceArtifacts"]["records"]), source_removed)

    proposal_rows, proposal_removed, valid_proposals = _filter_proposals(
        loaded["proposals"]["records"],
        central_source_ids,
        valid_sources,
    )
    proposal_removed.extend(loaded["proposals"]["invalid"])
    _record_file_report(owner_report, "proposals", owner_root / JSONL_FILES["proposals"], len(loaded["proposals"]["records"]), proposal_removed)

    batch_rows, batch_removed, valid_batches = _filter_batches(
        loaded["batches"]["records"],
        central_source_ids,
        valid_sources,
        valid_proposals,
    )
    batch_removed.extend(loaded["batches"]["invalid"])
    _record_file_report(owner_report, "batches", owner_root / JSONL_FILES["batches"], len(loaded["batches"]["records"]), batch_removed)

    item_rows, item_removed, valid_items = _filter_items(
        loaded["items"]["records"],
        central_source_ids,
        valid_sources,
        valid_batches,
        owner,
    )
    item_removed.extend(loaded["items"]["invalid"])
    _record_file_report(owner_report, "items", owner_root / JSONL_FILES["items"], len(loaded["items"]["records"]), item_removed)

    suggestion_rows, suggestion_removed = _filter_rating_suggestions(
        loaded["ratingSuggestions"]["records"],
        valid_proposals,
        valid_items,
    )
    suggestion_removed.extend(loaded["ratingSuggestions"]["invalid"])
    _record_file_report(
        owner_report,
        "ratingSuggestions",
        owner_root / JSONL_FILES["ratingSuggestions"],
        len(loaded["ratingSuggestions"]["records"]),
        suggestion_removed,
    )

    if apply:
        _rewrite_if_changed(root, owner_root / JSONL_FILES["sourceArtifacts"], source_rows, source_removed)
        _rewrite_if_changed(root, owner_root / JSONL_FILES["proposals"], proposal_rows, proposal_removed)
        _rewrite_if_changed(root, owner_root / JSONL_FILES["batches"], batch_rows, batch_removed)
        _rewrite_if_changed(root, owner_root / JSONL_FILES["items"], item_rows, item_removed)
        _rewrite_if_changed(root, owner_root / JSONL_FILES["ratingSuggestions"], suggestion_rows, suggestion_removed)

    owner_report["changed"] = any(file_report["removedCount"] for file_report in owner_report["files"].values())
    return owner_report, {_record_id_for_item(item) for item in valid_items.values()}


def _filter_sources(records: list[dict[str, Any]], central_source_ids: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    valid: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = _string(record.get("sourceArtifactId"))
        central_source_id = _string(record.get("centralSourceId"))
        reason = ""
        if not record_id:
            reason = "missing_sourceArtifactId"
        elif not central_source_id:
            reason = "missing_centralSourceId"
        elif central_source_id not in central_source_ids:
            reason = "unknown_centralSourceId"
        if reason:
            removed.append(_removed(record_id, reason, centralSourceId=central_source_id))
            continue
        kept.append(record)
        valid[record_id] = record
    return kept, removed, valid


def _filter_proposals(
    records: list[dict[str, Any]],
    central_source_ids: set[str],
    valid_sources: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    valid: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = _string(record.get("proposalId"))
        source_ids = _string_list(record.get("sourceArtifactIds"))
        central_ids = _string_list(record.get("centralSourceIds"))
        source_central_ids = [_string((valid_sources.get(source_id) or {}).get("centralSourceId")) for source_id in source_ids]
        reason = ""
        if not record_id:
            reason = "missing_proposalId"
        elif not source_ids:
            reason = "missing_sourceArtifactIds"
        elif not central_ids:
            reason = "missing_centralSourceIds"
        elif any(source_id not in valid_sources for source_id in source_ids):
            reason = "references_removed_or_unknown_sourceArtifact"
        elif any(central_id not in central_source_ids for central_id in central_ids):
            reason = "unknown_centralSourceId"
        elif any(central_id and central_id not in central_ids for central_id in source_central_ids):
            reason = "sourceArtifact_centralSourceId_not_declared"
        if reason:
            removed.append(_removed(record_id, reason, sourceArtifactIds=source_ids, centralSourceIds=central_ids))
            continue
        kept.append(record)
        valid[record_id] = record
    return kept, removed, valid


def _filter_batches(
    records: list[dict[str, Any]],
    central_source_ids: set[str],
    valid_sources: dict[str, dict[str, Any]],
    valid_proposals: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    valid: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = _string(record.get("batchId"))
        proposal_ids = _string_list(record.get("proposalIds"))
        source_ids = _string_list(record.get("sourceArtifactIds"))
        central_ids = _string_list(record.get("centralSourceIds"))
        reason = ""
        if not record_id:
            reason = "missing_batchId"
        elif not proposal_ids:
            reason = "missing_proposalIds"
        elif any(proposal_id not in valid_proposals for proposal_id in proposal_ids):
            reason = "references_removed_or_unknown_proposal"
        elif not source_ids or any(source_id not in valid_sources for source_id in source_ids):
            reason = "references_removed_or_unknown_sourceArtifact"
        elif not central_ids or any(central_id not in central_source_ids for central_id in central_ids):
            reason = "missing_or_unknown_centralSourceIds"
        if reason:
            removed.append(_removed(record_id, reason, proposalIds=proposal_ids, sourceArtifactIds=source_ids, centralSourceIds=central_ids))
            continue
        kept.append(record)
        valid[record_id] = record
    return kept, removed, valid


def _filter_items(
    records: list[dict[str, Any]],
    central_source_ids: set[str],
    valid_sources: dict[str, dict[str, Any]],
    valid_batches: dict[str, dict[str, Any]],
    owner: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    valid: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = _string(record.get("knowledgeItemId"))
        source_ids = _string_list(record.get("sourceArtifactIds"))
        central_ids = _string_list(record.get("centralSourceIds"))
        batch_id = _string(record.get("batchId"))
        reason = ""
        if not record_id:
            reason = "missing_knowledgeItemId"
        elif not batch_id or batch_id not in valid_batches:
            reason = "references_removed_or_unknown_batch"
        elif not source_ids or any(source_id not in valid_sources for source_id in source_ids):
            reason = "references_removed_or_unknown_sourceArtifact"
        elif not central_ids or any(central_id not in central_source_ids for central_id in central_ids):
            reason = "missing_or_unknown_centralSourceIds"
        if reason:
            removed.append(_removed(record_id, reason, batchId=batch_id, sourceArtifactIds=source_ids, centralSourceIds=central_ids))
            continue
        normalized = dict(record)
        normalized.setdefault("ownerType", owner["ownerType"])
        normalized.setdefault("ownerId", owner["ownerId"])
        kept.append(normalized)
        valid[record_id] = normalized
    return kept, removed, valid


def _filter_rating_suggestions(
    records: list[dict[str, Any]],
    valid_proposals: dict[str, dict[str, Any]],
    valid_items: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for record in records:
        record_id = _string(record.get("suggestionId"))
        target_type = _string(record.get("targetType"))
        proposal_id = _string(record.get("proposalId"))
        item_id = _string(record.get("knowledgeItemId"))
        reason = ""
        if not record_id:
            reason = "missing_suggestionId"
        elif target_type == "proposal" and (not proposal_id or proposal_id not in valid_proposals):
            reason = "references_removed_or_unknown_proposal"
        elif target_type == "knowledge_item" and (not item_id or item_id not in valid_items):
            reason = "references_removed_or_unknown_knowledgeItem"
        elif target_type not in {"proposal", "knowledge_item"}:
            reason = "unsupported_targetType"
        if reason:
            removed.append(_removed(record_id, reason, targetType=target_type, proposalId=proposal_id, knowledgeItemId=item_id))
            continue
        kept.append(record)
    return kept, removed


def _clean_vector_index(
    root: Path,
    central_source_ids: set[str],
    valid_item_record_ids: set[str],
    *,
    apply: bool,
) -> dict[str, Any]:
    items_dir = root / "workspace" / "knowledge" / "vector_index" / "items"
    vector_report = {"removedRecordCount": 0, "keptRecordCount": 0, "records": []}
    kept_records: list[dict[str, Any]] = []
    if not items_dir.exists():
        return vector_report
    _ensure_under_root(root, items_dir.resolve())
    for path in sorted(items_dir.glob("*.json")):
        record = _read_json(path)
        if not isinstance(record, dict):
            _remove_vector_record(root, path, "invalid_json", vector_report, apply=apply)
            continue
        record_id = _string(record.get("recordId"))
        expected_record_id = _record_id_for_record(record)
        expected_name = f"{_safe_record_filename(expected_record_id)}.json"
        central_ids = _string_list(record.get("centralSourceIds"))
        reason = ""
        if not record_id:
            reason = "missing_recordId"
        elif record_id != expected_record_id:
            reason = "recordId_owner_scope_mismatch"
        elif path.name != expected_name:
            reason = "legacy_vector_record_filename"
        elif record_id not in valid_item_record_ids:
            reason = "references_removed_or_unknown_knowledgeItem"
        elif not central_ids or any(central_id not in central_source_ids for central_id in central_ids):
            reason = "missing_or_unknown_centralSourceIds"
        if reason:
            _remove_vector_record(root, path, reason, vector_report, apply=apply, record=record)
            continue
        kept_records.append(record)
        vector_report["keptRecordCount"] += 1
    if apply:
        _write_vector_index_summary(root, kept_records)
    return vector_report


def _load_central_source_ids(root: Path) -> set[str]:
    registry_path = root / "workspace" / "knowledge" / "sources" / "registry" / "source_registry.jsonl"
    records = _read_jsonl(registry_path)["records"]
    return {_string(record.get("centralSourceId")) for record in records if _string(record.get("centralSourceId"))}


def _iter_owner_roots(root: Path) -> list[dict[str, Any]]:
    owners: list[dict[str, Any]] = []
    for owner_type, base in (("team", root / "workspace" / "teams"), ("agent", root / "workspace" / "agents")):
        if not base.exists():
            continue
        for owner_dir in sorted(path for path in base.iterdir() if path.is_dir()):
            knowledge_root = owner_dir / "knowledge"
            if knowledge_root.exists():
                owners.append({"ownerType": owner_type, "ownerId": owner_dir.name, "root": knowledge_root.resolve()})
    return owners


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl(path: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    if not path.exists():
        return {"records": records, "invalid": invalid}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        invalid.append(_removed("", "unreadable_file"))
        return {"records": records, "invalid": invalid}
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid.append(_removed("", "invalid_json_line", line=index))
            continue
        if not isinstance(payload, dict):
            invalid.append(_removed("", "jsonl_record_not_object", line=index))
            continue
        records.append(payload)
    return {"records": records, "invalid": invalid}


def _rewrite_if_changed(root: Path, path: Path, rows: list[dict[str, Any]], removed: list[dict[str, Any]]) -> None:
    if not removed or not path.exists():
        return
    resolved = path.resolve()
    _ensure_under_root(root, resolved)
    tmp_path = resolved.with_suffix(resolved.suffix + ".tmp")
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    tmp_path.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp_path, resolved)


def _remove_vector_record(
    root: Path,
    path: Path,
    reason: str,
    report: dict[str, Any],
    *,
    apply: bool,
    record: dict[str, Any] | None = None,
) -> None:
    report["removedRecordCount"] += 1
    report["records"].append(
        {
            "path": _relative_path(root, path),
            "recordId": _string((record or {}).get("recordId")),
            "knowledgeItemId": _string((record or {}).get("knowledgeItemId")),
            "reason": reason,
        }
    )
    if apply:
        resolved = path.resolve()
        _ensure_under_root(root, resolved)
        resolved.unlink(missing_ok=True)


def _write_vector_index_summary(root: Path, records: list[dict[str, Any]]) -> None:
    index_path = root / "workspace" / "knowledge" / "vector_index" / "index.json"
    _ensure_under_root(root, index_path.resolve())
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "updatedAt": _utc_now_iso(),
        "recordCount": len(records),
        "records": [
            {
                "knowledgeItemId": _string(record.get("knowledgeItemId")),
                "recordId": _string(record.get("recordId")),
                "knowledgeBaseId": _string(record.get("knowledgeBaseId")),
                "ownerType": _string(record.get("ownerType")) or "team",
                "ownerId": _string(record.get("ownerId") or record.get("teamId") or record.get("agentId")),
                "teamId": _string(record.get("teamId")),
                "agentId": _string(record.get("agentId")),
                "centralSourceIds": _string_list(record.get("centralSourceIds")),
                "contentHash": _string(record.get("contentHash")),
                "status": _string(record.get("status")),
                "indexedAt": _string(record.get("indexedAt")),
            }
            for record in records
        ],
    }
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _record_file_report(owner_report: dict[str, Any], key: str, path: Path, original_count: int, removed: list[dict[str, Any]]) -> None:
    if not removed:
        return
    owner_report["files"][key] = {
        "path": str(Path(owner_report["root"]) / path.name),
        "originalCount": original_count,
        "removedCount": len(removed),
        "records": removed,
    }


def _removed(record_id: str, reason: str, **fields: Any) -> dict[str, Any]:
    payload = {"id": record_id, "reason": reason}
    for key, value in fields.items():
        if value not in ("", [], {}, None):
            payload[key] = value
    return payload


def _record_id_for_item(item: dict[str, Any]) -> str:
    return _owner_scoped_item_record_id(
        owner_type=_string(item.get("ownerType")) or "team",
        owner_id=_string(item.get("ownerId") or item.get("teamId") or item.get("agentId")),
        knowledge_item_id=_string(item.get("knowledgeItemId")),
    )


def _record_id_for_record(record: dict[str, Any]) -> str:
    return _owner_scoped_item_record_id(
        owner_type=_string(record.get("ownerType")) or "team",
        owner_id=_string(record.get("ownerId") or record.get("teamId") or record.get("agentId")),
        knowledge_item_id=_string(record.get("knowledgeItemId")),
    )


def _owner_scoped_item_record_id(*, owner_type: str, owner_id: str, knowledge_item_id: str) -> str:
    safe_owner_type = _safe_record_fragment(owner_type or "team")
    safe_owner_id = _safe_record_fragment(owner_id)
    safe_item_id = _safe_record_fragment(knowledge_item_id)
    if safe_owner_type and safe_owner_id and safe_item_id:
        return f"{safe_owner_type}:{safe_owner_id}:{safe_item_id}"
    return safe_item_id


def _safe_record_fragment(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in str(value or "").strip()).strip(".-_")


def _safe_record_filename(value: str) -> str:
    return _safe_record_fragment(value) or "item"


def _string(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for text in (_string(item) for item in value) if text]


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _ensure_under_root(root: Path, path: Path) -> None:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    try:
        path_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise RuntimeError(f"Refusing to modify path outside root: {path_resolved}") from exc


def _write_report(root: Path, report_dir: Path, report: dict[str, Any], *, apply: bool) -> Path:
    _ensure_under_root(root, report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mode = "apply" if apply else "dry_run"
    path = report_dir / f"legacy_memory_source_cleanup_{mode}_{timestamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _build_summary(report: dict[str, Any]) -> dict[str, int]:
    owner_count = len(report.get("owners") or [])
    removed_by_kind: dict[str, int] = {}
    for owner in report.get("owners") or []:
        for key, file_report in (owner.get("files") or {}).items():
            removed_by_kind[key] = removed_by_kind.get(key, 0) + int(file_report.get("removedCount") or 0)
    removed_by_kind["vectorIndexRecords"] = int((report.get("vectorIndex") or {}).get("removedRecordCount") or 0)
    return {"changedOwnerCount": owner_count, **removed_by_kind}


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": report["mode"],
        "generatedAt": report["generatedAt"],
        "reportPath": report.get("reportPath", ""),
        "centralSourceCount": report["centralSourceCount"],
        "summary": report["summary"],
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
