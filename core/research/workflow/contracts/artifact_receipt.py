"""ArtifactReceipt / BudgetReceipt: verified domain materialization receipts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactReceipt:
    receipt_id: str
    team_id: str
    run_id: str
    node_run_id: str
    artifact_type: str
    canonical_ref: str
    version: str
    sha256: str
    domain_revision: str
    materialized: bool
    verified_at_ms: int
    verifier: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "receiptId": self.receipt_id,
            "teamId": self.team_id,
            "runId": self.run_id,
            "nodeRunId": self.node_run_id,
            "artifactType": self.artifact_type,
            "canonicalRef": self.canonical_ref,
            "version": self.version,
            "sha256": self.sha256,
            "domainRevision": self.domain_revision,
            "materialized": self.materialized,
            "verifiedAtMs": self.verified_at_ms,
            "verifier": self.verifier,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ArtifactReceipt:
        return cls(
            receipt_id=str(payload.get("receiptId") or ""),
            team_id=str(payload.get("teamId") or ""),
            run_id=str(payload.get("runId") or ""),
            node_run_id=str(payload.get("nodeRunId") or ""),
            artifact_type=str(payload.get("artifactType") or ""),
            canonical_ref=str(payload.get("canonicalRef") or ""),
            version=str(payload.get("version") or ""),
            sha256=str(payload.get("sha256") or ""),
            domain_revision=str(payload.get("domainRevision") or ""),
            materialized=bool(payload.get("materialized")),
            verified_at_ms=int(payload.get("verifiedAtMs") or 0),
            verifier=str(payload.get("verifier") or ""),
        )


@dataclass(frozen=True, slots=True)
class BudgetReceipt:
    receipt_id: str
    run_id: str
    node_run_id: str
    reservation_id: str
    stage_id: str
    policy_hash: str
    reserved: dict[str, Any]
    settled: dict[str, Any] | None
    status: str
    created_at_ms: int
    updated_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "receiptId": self.receipt_id,
            "runId": self.run_id,
            "nodeRunId": self.node_run_id,
            "reservationId": self.reservation_id,
            "stageId": self.stage_id,
            "policyHash": self.policy_hash,
            "reserved": dict(self.reserved),
            "status": self.status,
            "createdAtMs": self.created_at_ms,
            "updatedAtMs": self.updated_at_ms,
        }
        if self.settled is not None:
            payload["settled"] = dict(self.settled)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BudgetReceipt:
        settled = payload.get("settled")
        return cls(
            receipt_id=str(payload.get("receiptId") or ""),
            run_id=str(payload.get("runId") or ""),
            node_run_id=str(payload.get("nodeRunId") or ""),
            reservation_id=str(payload.get("reservationId") or ""),
            stage_id=str(payload.get("stageId") or ""),
            policy_hash=str(payload.get("policyHash") or ""),
            reserved=dict(payload.get("reserved") or {}),
            settled=dict(settled) if settled else None,
            status=str(payload.get("status") or ""),
            created_at_ms=int(payload.get("createdAtMs") or 0),
            updated_at_ms=int(payload.get("updatedAtMs") or 0),
        )
