# -*- coding: utf-8 -*-
"""Supervised Judge rubric version store (append-only lineage).

评估器版本化 + shadow 晋升的地基：监督进化的 Judge 每轮「生成并冻结
rubric」，但 rubric 跨轮没有谱系，无法回答「评估器变好了吗」。本模块以
append-only JSONL 台账表达状态迁移：``shadow`` 记录 → 晋升（追加
``active`` 行并指向前任）→ 退役（追加 ``retired`` 行）。历史永不改写，
晋升必须携带证据（分数、kappa 等），供统计治理门消费。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_ALLOWED_STATUSES = frozenset({"shadow", "active", "retired"})


class RubricVersionStoreError(ValueError):
    """Raised for invalid rubric-version store operations."""


def _ledger_path() -> Path:
    return developer_sandbox.sandboxed_workspace_path(
        _PROJECT_ROOT, "evaluation", "rubric_versions", "ledger.jsonl"
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def record_rubric_version(
    rubric: dict[str, Any],
    *,
    source: str,
    rubric_hash: str,
    status: str = "shadow",
) -> dict[str, Any]:
    """Append one rubric version record; idempotent on (rubric_hash, status)."""
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in _ALLOWED_STATUSES:
        raise RubricVersionStoreError(
            f"invalid rubric version status {status!r}; expected one of "
            f"{sorted(_ALLOWED_STATUSES)}"
        )
    if not str(rubric_hash or "").strip():
        raise RubricVersionStoreError("rubric_hash is required")
    existing = _find_same_content(rubric_hash, normalized_status)
    if existing is not None:
        return existing
    body = {
        "schemaVersion": 1,
        "rubricVersionId": f"rv-{uuid.uuid4().hex[:12]}",
        "source": str(source or "").strip(),
        "rubricHash": str(rubric_hash).strip(),
        "rubric": rubric,
        "status": normalized_status,
        "supersedesVersionId": "",
        "evidence": {},
        "createdAt": _now_iso(),
    }
    record = {**body, "contentSha256": _fingerprint(body)}
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return record


def _read_records(limit: int = 0) -> list[dict[str, Any]]:
    path = _ledger_path()
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").strip().splitlines():
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records if limit <= 0 else records[-limit:]


def list_rubric_versions(limit: int = 100) -> list[dict[str, Any]]:
    """Read the ledger (corrupt lines skipped), newest last, bounded by limit."""
    return _read_records(limit=limit)


def latest_active_version() -> dict[str, Any] | None:
    """The most recent ``active`` record, or None before the first promotion."""
    for record in reversed(_read_records()):
        if str(record.get("status") or "") == "active":
            return record
    return None


def promote_rubric_version(version_id: str, *, evidence: dict[str, Any]) -> dict[str, Any]:
    """Promote one version to ``active``; the previous active is retired.

    状态迁移全部通过追加新行表达：晋升行（``active``、指向前任）+ 退役行
    （``retired``、指向被替换者）。evidence 必填（分数/kappa 等治理证据）。
    """
    normalized_id = str(version_id or "").strip()
    if not normalized_id:
        raise RubricVersionStoreError("version_id is required")
    if not isinstance(evidence, dict) or not evidence:
        raise RubricVersionStoreError("promotion evidence must be a non-empty dict")
    records = _read_records()
    target = next(
        (r for r in records if str(r.get("rubricVersionId") or "") == normalized_id),
        None,
    )
    if target is None:
        raise RubricVersionStoreError(f"rubric version not found: {normalized_id}")
    if str(target.get("status") or "") != "shadow":
        raise RubricVersionStoreError(
            f"only shadow versions can be promoted; {normalized_id} is "
            f"{target.get('status')!r}"
        )
    already_promoted = any(
        str(record.get("promotedFromVersionId") or "") == normalized_id
        for record in records
    )
    if already_promoted:
        raise RubricVersionStoreError(
            f"rubric version {normalized_id} has already been promoted once"
        )
    previous_active = latest_active_version()
    promoted_body = {
        "schemaVersion": 1,
        "rubricVersionId": f"rv-{uuid.uuid4().hex[:12]}",
        "source": str(target.get("source") or ""),
        "rubricHash": str(target.get("rubricHash") or ""),
        "rubric": target.get("rubric") or {},
        "status": "active",
        "supersedesVersionId": str(previous_active.get("rubricVersionId") or "")
        if previous_active
        else "",
        "promotedFromVersionId": normalized_id,
        "evidence": evidence,
        "createdAt": _now_iso(),
    }
    retired_body = None
    if previous_active is not None:
        retired_body = {
            "schemaVersion": 1,
            "rubricVersionId": f"rv-{uuid.uuid4().hex[:12]}",
            "source": str(previous_active.get("source") or ""),
            "rubricHash": str(previous_active.get("rubricHash") or ""),
            "rubric": previous_active.get("rubric") or {},
            "status": "retired",
            "supersedesVersionId": str(previous_active.get("rubricVersionId") or ""),
            "evidence": {"retiredBy": promoted_body["rubricVersionId"]},
            "createdAt": _now_iso(),
        }
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {**promoted_body, "contentSha256": _fingerprint(promoted_body)},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    ]
    if retired_body is not None:
        lines.append(
            json.dumps(
                {**retired_body, "contentSha256": _fingerprint(retired_body)},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        )
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(line + "\n")
    return {**promoted_body, "contentSha256": _fingerprint(promoted_body)}


def _find_same_content(rubric_hash: str, status: str) -> dict[str, Any] | None:
    for record in reversed(_read_records()):
        if (
            str(record.get("rubricHash") or "") == str(rubric_hash)
            and str(record.get("status") or "") == status
        ):
            return record
    return None


__all__ = [
    "RubricVersionStoreError",
    "latest_active_version",
    "list_rubric_versions",
    "promote_rubric_version",
    "record_rubric_version",
]
