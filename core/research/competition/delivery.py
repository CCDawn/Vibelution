"""Challenge Cup delivery-pack control flow.

Formal packs are refused until 125/125, R0/R1, no pending claims and a frozen
submission projection exist. Preview packs never claim to be final.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.research.competition.resources import (
    CATALOG_QUESTION_COUNT,
    CORE_BEHAVIOR_HASH,
    CORE_POLICY_HASH,
)

DEFAULT_PDF_LIMIT_BYTES = 20 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def formal_blockers(payload: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    approved = int(payload.get("approvedQuestionCount") or 0)
    if approved != CATALOG_QUESTION_COUNT:
        blockers.append("catalog_incomplete")
    if str(payload.get("r0") or "") != "PASS":
        blockers.append("r0_not_pass")
    if str(payload.get("r1") or "") != "PASS":
        blockers.append("r1_not_pass")
    if str(payload.get("r2") or "pending") not in {"PASS", "not_required_for_preview"}:
        blockers.append("r2_not_pass")
    if str(payload.get("r3") or "pending") not in {"PASS", "not_required_for_preview"}:
        blockers.append("r3_not_pass")
    if int(payload.get("pendingClaimCount") or 0) > 0:
        blockers.append("pending_claims")
    if payload.get("submissionProjectionFrozen") is not True:
        blockers.append("submission_projection_unfrozen")
    return blockers


def export_results(payload: dict[str, Any], *, mode: str) -> dict[str, Any]:
    requested = str(mode or "preview").strip().lower()
    if requested not in {"preview", "formal"}:
        raise ValueError(f"unsupported export mode: {mode}")
    blockers = formal_blockers(payload) if requested == "formal" else []
    status = "refused" if blockers else ("final" if requested == "formal" else "preview")
    return {
        "schemaVersion": 1,
        "packKind": "challenge_cup_result_pack",
        "mode": requested,
        "status": status,
        "blockers": blockers,
        "programContract": {
            "version": "2.2.0",
            "coreBehaviorHash": CORE_BEHAVIOR_HASH,
        },
        "catalogPolicy": {
            "version": "1.2.0",
            "corePolicyHash": CORE_POLICY_HASH,
        },
        "approvedQuestionCount": int(payload.get("approvedQuestionCount") or 0),
        "requiredQuestionCount": CATALOG_QUESTION_COUNT,
        "evidenceIndex": list(payload.get("evidenceIndex") or []),
        "generatedAt": _now(),
        "final": status == "final",
    }


def validate_submission_projection(payload: dict[str, Any]) -> dict[str, Any]:
    frozen = payload.get("submissionProjectionFrozen") is True
    captured = payload.get("captured") is True
    return {
        "frozen": frozen,
        "captured": captured,
        "blocksFormalPack": not frozen,
        "allowedPackMode": "preview" if not frozen else "formal",
        "officialPageObservedState": str(payload.get("officialPageObservedState") or "unknown"),
    }


def build_evidence_index(entries: list[dict[str, Any]]) -> dict[str, Any]:
    index = []
    for item in entries:
        path = str(item.get("path") or "").replace("\\", "/")
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"unsafe evidence path: {path}")
        index.append(
            {
                "path": path,
                "kind": str(item.get("kind") or "artifact"),
                "sha256": str(item.get("sha256") or ""),
                "scope": dict(item.get("scope") or {}),
            }
        )
    return {
        "schemaVersion": 1,
        "entryCount": len(index),
        "entries": index,
        "generatedAt": _now(),
    }


def check_pdf_limit(size_bytes: int, *, limit_bytes: int = DEFAULT_PDF_LIMIT_BYTES) -> dict[str, Any]:
    if size_bytes < 0:
        raise ValueError("size_bytes must be non-negative")
    return {
        "sizeBytes": int(size_bytes),
        "limitBytes": int(limit_bytes),
        "withinLimit": int(size_bytes) <= int(limit_bytes),
        "generatedContent": False,
    }
