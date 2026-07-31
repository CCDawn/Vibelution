"""Persistent no-score orchestration for user-approved self-evolution loops."""

from __future__ import annotations

import threading
import uuid
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from core.runtime_manager.work_run_store import WorkRunStore
from core.web.services.runtime_scene_service import record_runtime_scene_event


RUN_KIND = "self_evolution_autonomous_loop"
SCHEMA_VERSION = 1
MAX_ITERATIONS = 20
MAX_GOAL_LENGTH = 4_000
MAX_SUMMARY_LENGTH = 8_000
MAX_CHANGED_FILES = 400
MAX_VERIFICATION_ITEMS = 100
MAX_EVIDENCE_TEXT_LENGTH = 8_000
MAX_EVIDENCE_DEPTH = 6
_SECRET_KEY_MARKERS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
}
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|cookie|credential|password|secret|token)"
    r"(\s*[:=]\s*|\s+)([^\s,;]+)"
)
_LOCK = threading.RLock()


class AutonomousLoopError(ValueError):
    """Base error for self-evolution autonomous-loop requests."""


class AutonomousLoopValidationError(AutonomousLoopError):
    """Raised when a lifecycle payload violates the public contract."""


class AutonomousLoopConflictError(AutonomousLoopError):
    """Raised when the requested transition conflicts with persisted state."""


AutonomousHook = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class AutonomousLoopHooks:
    """Side-effect boundaries owned by the execution and Git adapters."""

    observe: AutonomousHook
    plan: AutonomousHook
    evolve: AutonomousHook
    integrate: AutonomousHook
    cleanup: AutonomousHook


class SelfEvolutionAutonomousLoopService:
    """Drive observation through user-approved integration without a Judge."""

    def __init__(
        self,
        *,
        store: WorkRunStore,
        hooks: AutonomousLoopHooks,
        run_id_factory: Callable[[], str] | None = None,
        now: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._hooks = hooks
        self._run_id_factory = run_id_factory or (lambda: f"self-loop-{uuid.uuid4().hex[:12]}")
        self._now = now or (lambda: datetime.now(timezone.utc).isoformat())

    def start(self, request: dict[str, Any]) -> dict[str, Any]:
        """Run observe, plan, and evolve phases, then stop for user review."""

        normalized_request = _normalize_request(request)
        with _LOCK:
            active = self._store.load_active_snapshot(RUN_KIND)
            if active is not None:
                raise AutonomousLoopConflictError(
                    "An active self-evolution autonomous loop already exists."
                )
            run_id = str(self._run_id_factory() or "").strip()
            if not run_id:
                raise AutonomousLoopValidationError("run_id_factory returned an empty run id.")
            now = self._now()
            snapshot = {
                "schemaVersion": SCHEMA_VERSION,
                "runKind": RUN_KIND,
                "runId": run_id,
                "status": "running",
                "phase": "observing",
                "request": normalized_request,
                "reviewGate": {
                    "status": "not_ready",
                    "requiredActorType": "user",
                },
                "createdAt": now,
                "startedAt": now,
                "updatedAt": now,
            }
            snapshot = self._persist(snapshot, active=True)

        try:
            observation = _normalize_observation(
                self._hooks.observe(_phase_context(snapshot))
            )
            snapshot = self._advance(
                snapshot,
                phase="planning",
                updates={"observation": observation},
            )
            plan = _normalize_plan(self._hooks.plan(_phase_context(snapshot)))
            snapshot = self._advance(
                snapshot,
                phase="evolving",
                updates={"plan": plan},
            )
            candidate = _normalize_candidate(
                self._hooks.evolve(_phase_context(snapshot))
            )
            return self._advance(
                snapshot,
                status="awaiting_user_approval",
                phase="reporting",
                updates={
                    "candidate": candidate,
                    "resultReport": _result_report(candidate),
                    "reviewGate": {
                        "status": "pending",
                        "requiredActorType": "user",
                    },
                },
            )
        except Exception as exc:
            return self._fail(snapshot, phase=f"{snapshot['phase']}_failed", exc=exc)

    def approve(self, run_id: str, *, decision: dict[str, Any]) -> dict[str, Any]:
        """Apply explicit user approval, integrate, and clean local candidate state."""

        approval = _normalize_user_decision(decision, expected="approve")
        with _LOCK:
            snapshot = self._load_required(run_id)
            _require_phase(snapshot, "reporting", status="awaiting_user_approval")
            snapshot = self._advance(
                snapshot,
                status="running",
                phase="integrating",
                updates={
                    "approval": approval,
                    "reviewGate": {
                        "status": "approved",
                        "requiredActorType": "user",
                        "decision": approval,
                    }
                },
            )

        try:
            integration = _normalize_integration(
                self._hooks.integrate(_phase_context(snapshot)),
                candidate=snapshot["candidate"],
            )
            snapshot = self._advance(
                snapshot,
                phase="cleanup_pending",
                updates={"integration": integration},
            )
        except Exception as exc:
            return self._fail(snapshot, phase="integration_failed", exc=exc)

        return self._run_cleanup(snapshot)

    def reject(self, run_id: str, *, decision: dict[str, Any]) -> dict[str, Any]:
        """Record a user rejection while preserving the candidate for follow-up."""

        rejection = _normalize_user_decision(decision, expected="reject")
        with _LOCK:
            snapshot = self._load_required(run_id)
            _require_phase(snapshot, "reporting", status="awaiting_user_approval")
            return self._advance(
                snapshot,
                status="rejected",
                phase="rejected",
                terminal=True,
                updates={
                    "reviewGate": {
                        "status": "rejected",
                        "requiredActorType": "user",
                        "decision": rejection,
                    }
                },
            )

    def retry_cleanup(self, run_id: str) -> dict[str, Any]:
        """Retry cleanup only after a persisted successful merge."""

        with _LOCK:
            snapshot = self._load_required(run_id)
            _require_phase(snapshot, "cleanup_failed", status="partial")
            if str((snapshot.get("integration") or {}).get("status") or "") != "merged":
                raise AutonomousLoopConflictError(
                    "Cleanup retry requires a persisted merged integration."
                )
            snapshot = deepcopy(snapshot)
            snapshot.pop("error", None)
            snapshot.pop("finishedAt", None)
            snapshot = self._advance(
                snapshot,
                status="running",
                phase="cleanup_pending",
            )
        return self._run_cleanup(snapshot)

    def load(self, run_id: str) -> dict[str, Any]:
        return self._load_required(run_id)

    def _run_cleanup(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        try:
            cleanup = _normalize_cleanup(
                self._hooks.cleanup(_phase_context(snapshot))
            )
            return self._advance(
                snapshot,
                status="completed",
                phase="completed",
                terminal=True,
                updates={"cleanup": cleanup},
            )
        except Exception as exc:
            return self._fail(
                snapshot,
                phase="cleanup_failed",
                exc=exc,
                status="partial",
            )

    def _load_required(self, run_id: str) -> dict[str, Any]:
        snapshot = self._store.load_snapshot(RUN_KIND, str(run_id or "").strip())
        if snapshot is None:
            raise AutonomousLoopValidationError(
                f"Unknown self-evolution autonomous loop: {run_id}"
            )
        return snapshot

    def _advance(
        self,
        snapshot: dict[str, Any],
        *,
        phase: str,
        status: str | None = None,
        updates: dict[str, Any] | None = None,
        terminal: bool = False,
    ) -> dict[str, Any]:
        next_snapshot = deepcopy(snapshot)
        next_snapshot["phase"] = phase
        next_snapshot["status"] = status or str(snapshot.get("status") or "running")
        next_snapshot["updatedAt"] = self._now()
        if updates:
            next_snapshot.update(deepcopy(updates))
        if terminal:
            next_snapshot["finishedAt"] = self._now()
        return self._persist(next_snapshot, active=not terminal)

    def _fail(
        self,
        snapshot: dict[str, Any],
        *,
        phase: str,
        exc: Exception,
        status: str = "failed",
    ) -> dict[str, Any]:
        return self._advance(
            snapshot,
            status=status,
            phase=phase,
            terminal=True,
            updates={
                "error": {
                    "type": type(exc).__name__,
                    "message": _redact_text(
                        _trim_text(str(exc), MAX_SUMMARY_LENGTH)
                    ),
                }
            },
        )

    def _persist(self, snapshot: dict[str, Any], *, active: bool) -> dict[str, Any]:
        persisted = self._store.persist_snapshot(
            RUN_KIND,
            snapshot,
            active_run_id=str(snapshot.get("runId") or "") if active else "",
        )
        _record_lifecycle_event(persisted)
        return persisted


def _normalize_request(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise AutonomousLoopValidationError("Autonomous-loop request must be an object.")
    goal = _trim_text(request.get("goal"), MAX_GOAL_LENGTH)
    if not goal:
        raise AutonomousLoopValidationError("Autonomous-loop goal is required.")
    try:
        max_iterations = int(request.get("maxIterations") or 1)
    except (TypeError, ValueError) as exc:
        raise AutonomousLoopValidationError("maxIterations must be an integer.") from exc
    if not 1 <= max_iterations <= MAX_ITERATIONS:
        raise AutonomousLoopValidationError(
            f"maxIterations must be between 1 and {MAX_ITERATIONS}."
        )
    return {
        "goal": goal,
        "maxIterations": max_iterations,
    }


def _normalize_observation(payload: dict[str, Any]) -> dict[str, Any]:
    item = _require_object(payload, "Observation")
    summary = _required_text(item.get("summary"), "Observation summary")
    evidence = item.get("evidence")
    if not isinstance(evidence, list):
        raise AutonomousLoopValidationError("Observation evidence must be a list.")
    normalized = {
        "summary": summary,
        "evidence": [
            _sanitize_evidence(item)
            for item in evidence[:MAX_VERIFICATION_ITEMS]
        ],
    }
    _copy_optional_text(
        item,
        normalized,
        "conversationSessionId",
        max_length=300,
    )
    return normalized


def _normalize_plan(payload: dict[str, Any]) -> dict[str, Any]:
    item = _require_object(payload, "Plan")
    summary = _required_text(item.get("summary"), "Plan summary")
    steps = item.get("steps")
    if not isinstance(steps, list) or not steps:
        raise AutonomousLoopValidationError("Plan steps must be a non-empty list.")
    normalized = {
        "summary": summary,
        "steps": [
            _sanitize_evidence(item)
            for item in steps[:MAX_VERIFICATION_ITEMS]
        ],
    }
    _copy_optional_text(
        item,
        normalized,
        "conversationSessionId",
        max_length=300,
    )
    return normalized


def _normalize_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    item = _require_object(payload, "Candidate")
    candidate = {
        "summary": _required_text(item.get("summary"), "Candidate summary"),
        "branch": _required_text(item.get("branch"), "Candidate branch"),
        "worktreePath": _required_text(
            item.get("worktreePath"),
            "Candidate worktreePath",
        ),
        "baseCommit": _required_text(item.get("baseCommit"), "Candidate baseCommit"),
        "headCommit": _required_text(item.get("headCommit"), "Candidate headCommit"),
        "changedFiles": _bounded_string_list(
            item.get("changedFiles"),
            "Candidate changedFiles",
            limit=MAX_CHANGED_FILES,
        ),
        "verification": _bounded_object_list(
            item.get("verification"),
            "Candidate verification",
            limit=MAX_VERIFICATION_ITEMS,
        ),
    }
    if candidate["branch"] in {"main", "master"}:
        raise AutonomousLoopValidationError(
            "Candidate branch must be an isolated task branch."
        )
    if candidate["baseCommit"] == candidate["headCommit"]:
        raise AutonomousLoopValidationError(
            "Candidate headCommit must differ from baseCommit."
        )
    _copy_optional_text(
        item,
        candidate,
        "conversationSessionId",
        max_length=300,
    )
    _copy_optional_text(item, candidate, "variantId", max_length=300)
    return candidate


def _normalize_user_decision(
    payload: dict[str, Any],
    *,
    expected: str,
) -> dict[str, str]:
    item = _require_object(payload, "User decision")
    if str(item.get("actorType") or "").strip().lower() != "user":
        raise AutonomousLoopValidationError(
            "Explicit user approval or rejection is required; actorType must be user."
        )
    actor_id = _required_text(item.get("actorId"), "User decision actorId")
    return {
        "decision": expected,
        "actorType": "user",
        "actorId": actor_id,
        "comment": _trim_text(item.get("comment"), MAX_SUMMARY_LENGTH),
    }


def _normalize_integration(
    payload: dict[str, Any],
    *,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    item = _require_object(payload, "Integration result")
    if str(item.get("status") or "").strip() != "merged":
        raise AutonomousLoopValidationError(
            "Integration result must confirm status=merged."
        )
    candidate_head = _required_text(
        item.get("candidateHead"),
        "Integration candidateHead",
    )
    if candidate_head != str(candidate.get("headCommit") or ""):
        raise AutonomousLoopValidationError(
            "Integration candidateHead does not match the approved candidate."
        )
    return {
        "status": "merged",
        "targetBranch": _required_text(
            item.get("targetBranch"),
            "Integration targetBranch",
        ),
        "previousHead": _required_text(
            item.get("previousHead"),
            "Integration previousHead",
        ),
        "mergedHead": _required_text(item.get("mergedHead"), "Integration mergedHead"),
        "candidateHead": candidate_head,
    }


def _normalize_cleanup(payload: dict[str, Any]) -> dict[str, Any]:
    item = _require_object(payload, "Cleanup result")
    if str(item.get("status") or "").strip() != "cleaned":
        raise AutonomousLoopValidationError(
            "Cleanup result must confirm status=cleaned."
        )
    if item.get("worktreeRemoved") is not True:
        raise AutonomousLoopValidationError(
            "Cleanup must confirm worktreeRemoved=true."
        )
    if item.get("localBranchDeleted") is not True:
        raise AutonomousLoopValidationError(
            "Cleanup must confirm localBranchDeleted=true."
        )
    return {
        "status": "cleaned",
        "worktreeRemoved": True,
        "localBranchDeleted": True,
    }


def _result_report(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": candidate["summary"],
        "changedFiles": deepcopy(candidate["changedFiles"]),
        "verification": deepcopy(candidate["verification"]),
        "candidateHead": candidate["headCommit"],
    }


def _phase_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(snapshot)


def _require_phase(
    snapshot: dict[str, Any],
    phase: str,
    *,
    status: str,
) -> None:
    if (
        str(snapshot.get("phase") or "") != phase
        or str(snapshot.get("status") or "") != status
    ):
        raise AutonomousLoopConflictError(
            f"Run must be {status}/{phase}; "
            f"got {snapshot.get('status')}/{snapshot.get('phase')}."
        )


def _require_object(payload: Any, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AutonomousLoopValidationError(f"{label} must be an object.")
    return payload


def _required_text(value: Any, label: str) -> str:
    text = _trim_text(value, MAX_SUMMARY_LENGTH)
    if not text:
        raise AutonomousLoopValidationError(f"{label} is required.")
    return text


def _bounded_string_list(value: Any, label: str, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        raise AutonomousLoopValidationError(f"{label} must be a list.")
    result = [
        _trim_text(item, MAX_SUMMARY_LENGTH)
        for item in value[:limit]
        if _trim_text(item, MAX_SUMMARY_LENGTH)
    ]
    if not result:
        raise AutonomousLoopValidationError(f"{label} must not be empty.")
    return result


def _bounded_object_list(value: Any, label: str, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise AutonomousLoopValidationError(f"{label} must be a list.")
    result = [deepcopy(item) for item in value[:limit] if isinstance(item, dict)]
    if not result:
        raise AutonomousLoopValidationError(f"{label} must not be empty.")
    return [_sanitize_evidence(item) for item in result]


def _trim_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _copy_optional_text(
    source: dict[str, Any],
    target: dict[str, Any],
    key: str,
    *,
    max_length: int,
) -> None:
    value = _trim_text(source.get(key), max_length)
    if value:
        target[key] = value


def _sanitize_evidence(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_EVIDENCE_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:MAX_VERIFICATION_ITEMS]:
            key = _trim_text(raw_key, 200)
            normalized_key = key.lower().replace("-", "_")
            if any(marker in normalized_key for marker in _SECRET_KEY_MARKERS):
                result[key] = "[REDACTED]"
            else:
                result[key] = _sanitize_evidence(raw_value, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [
            _sanitize_evidence(item, depth=depth + 1)
            for item in value[:MAX_VERIFICATION_ITEMS]
        ]
    if isinstance(value, str):
        return _redact_text(value[:MAX_EVIDENCE_TEXT_LENGTH])
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value)[:MAX_EVIDENCE_TEXT_LENGTH])


def _redact_text(value: str) -> str:
    return _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        str(value or ""),
    )


def _record_lifecycle_event(snapshot: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "work_run",
            "state",
            "self_evolution.autonomous_loop.transitioned",
            message="Self-evolution autonomous loop transitioned.",
            outcome="observed",
            fields={
                "runKind": RUN_KIND,
                "runId": str(snapshot.get("runId") or ""),
                "status": str(snapshot.get("status") or ""),
                "phase": str(snapshot.get("phase") or ""),
                "reviewStatus": str(
                    (snapshot.get("reviewGate") or {}).get("status") or ""
                ),
            },
            lifecycle=True,
        )
    except Exception:
        return
