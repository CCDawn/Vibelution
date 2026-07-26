# -*- coding: utf-8 -*-
"""Append-only, proposal-only candidate archive with deterministic Pareto ranking."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .optimization_models import EvolutionCandidate


@dataclass(frozen=True)
class ObjectiveVector:
    success: float = 0.0
    quality: float = 0.0
    validation: float = 0.0
    cost: float = 0.0
    latency: float = 0.0
    tool_errors: float = 0.0
    regression_risk: float = 0.0
    safety_risk: float = 0.0


@dataclass
class CandidateArchiveRecord:
    candidate_id: str
    fingerprint: str
    objective: ObjectiveVector
    status: str = "evaluated"
    blockers: list[str] = field(default_factory=list)
    candidate: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "fingerprint": self.fingerprint,
            "objective": asdict(self.objective),
            "status": self.status,
            "blockers": list(self.blockers),
            "candidate": self.candidate,
        }


class CandidateArchive:
    """Rebuildable local archive; a hard blocker can never enter the frontier."""

    def __init__(self, ledger_path: Path) -> None:
        self.ledger_path = Path(ledger_path)
        self._records: dict[str, CandidateArchiveRecord] = {}
        self._load()
        self._refresh_statuses(persist=False)

    def append(
        self,
        candidate: EvolutionCandidate,
        objective: ObjectiveVector,
        *,
        evidence_complete: bool = True,
        foundation_ok: bool = True,
    ) -> CandidateArchiveRecord:
        if not isinstance(candidate, EvolutionCandidate):
            raise TypeError("Candidate archive requires EvolutionCandidate")
        if not isinstance(objective, ObjectiveVector):
            raise TypeError("Candidate archive requires ObjectiveVector")
        fingerprint = candidate.artifact_fingerprint
        existing = self._records.get(fingerprint)
        if existing is not None:
            return existing
        blockers = _hard_blockers(objective, evidence_complete=evidence_complete, foundation_ok=foundation_ok)
        record = CandidateArchiveRecord(
            candidate_id=candidate.candidate_id,
            fingerprint=fingerprint,
            objective=objective,
            status="blocked" if blockers else "evaluated",
            blockers=blockers,
            candidate=candidate.to_dict(),
        )
        self._records[fingerprint] = record
        self._append_event({"kind": "record", "record": record.to_dict()})
        self._refresh_statuses(persist=True)
        return record

    def frontier(self) -> list[CandidateArchiveRecord]:
        self._refresh_statuses(persist=False)
        return sorted((record for record in self._records.values() if record.status == "pareto"), key=lambda item: item.candidate_id)

    def records(self) -> list[CandidateArchiveRecord]:
        return sorted(self._records.values(), key=lambda item: item.candidate_id)

    def _refresh_statuses(self, *, persist: bool) -> None:
        eligible = [record for record in self._records.values() if not record.blockers]
        for record in eligible:
            next_status = "dominated" if any(_dominates(other.objective, record.objective) for other in eligible if other is not record) else "pareto"
            if record.status != next_status:
                record.status = next_status
                if persist:
                    self._append_event({"kind": "status", "fingerprint": record.fingerprint, "status": next_status})

    def _load(self) -> None:
        if not self.ledger_path.exists():
            return
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("kind") == "record":
                payload = event["record"]
                self._records[payload["fingerprint"]] = CandidateArchiveRecord(
                    candidate_id=payload["candidate_id"],
                    fingerprint=payload["fingerprint"],
                    objective=ObjectiveVector(**payload["objective"]),
                    status=payload.get("status", "evaluated"),
                    blockers=list(payload.get("blockers") or []),
                    candidate=dict(payload.get("candidate") or {}),
                )
            elif event.get("kind") == "status" and event.get("fingerprint") in self._records:
                self._records[event["fingerprint"]].status = str(event["status"])

    def _append_event(self, event: dict[str, Any]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _hard_blockers(objective: ObjectiveVector, *, evidence_complete: bool, foundation_ok: bool) -> list[str]:
    blockers: list[str] = []
    if not evidence_complete:
        blockers.append("incomplete_evidence")
    if not foundation_ok:
        blockers.append("foundation_regression")
    if objective.safety_risk > 0:
        blockers.append("safety_risk")
    if objective.regression_risk > 0:
        blockers.append("regression_risk")
    return blockers


def _dominates(left: ObjectiveVector, right: ObjectiveVector) -> bool:
    maximize = ("success", "quality", "validation")
    minimize = ("cost", "latency", "tool_errors", "regression_risk", "safety_risk")
    no_worse = all(getattr(left, field) >= getattr(right, field) for field in maximize) and all(
        getattr(left, field) <= getattr(right, field) for field in minimize
    )
    strictly_better = any(getattr(left, field) > getattr(right, field) for field in maximize) or any(
        getattr(left, field) < getattr(right, field) for field in minimize
    )
    return no_worse and strictly_better


__all__ = ["CandidateArchive", "CandidateArchiveRecord", "ObjectiveVector"]
