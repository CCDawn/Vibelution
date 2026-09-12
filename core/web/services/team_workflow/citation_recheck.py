"""Structured heartbeat, resume ledger and RetryPolicy for citation recheck.

SCI-049 follow-up: the Challenge Cup "重核引用文献" repair used to verify the
whole evidence set in one silent HTTP request (minutes for large evidence
lists) with no progress and no checkpoint — a mid-run failure restarted from
zero.  This module gives that recheck loop the two Temporal-style primitives
the platform already trusts elsewhere (``hypothesis_command_attempts`` uses
the same delivery-shape):

1. **Structured heartbeat.**  After every evidence URL is processed the loop
   appends one heartbeat record to an append-only JSONL ledger next to the
   run artifact.  The payload contract (stable, reusable by future side-flow
   nodes — adopt these constants instead of inventing a second shape)::

       HEARTBEAT_STAGE    = "citation_recheck"
       HEARTBEAT_CONTRACT = "citation-recheck-heartbeat/v1"
       RECORD_KIND        = "citation_recheck_event"

       heartbeat record = {
         "schemaVersion": 1,
         "recordKind": "citation_recheck_event",
         "kind": "heartbeat",
         "stage": "citation_recheck",
         "attemptId": "citrecheck-<hex>",
         "teamId": str, "questionId": str, "runId": str,
         "done": int,            # evidence rows processed so far (1-based)
         "total": int,           # evidence rows in this recheck
         "etaSeconds": float,    # naive linear estimate for the remainder
         "at": "<iso8601 Z>", "atMs": int,
       }

   ``url_result`` records persist the per-URL verification outcome as it
   happens (the resume authority); ``attempt`` records bracket one recheck
   invocation (``running`` / ``finished``).  The ledger is progress metadata,
   never gate evidence: writes are best-effort and a lost record can only
   cause a safe re-verification, never a wrong pass.

2. **RetryPolicy** (Temporal Activity retry semantics): per-URL retries of
   transient verification failures with exponential backoff, plus a
   non-retryable class that fails the URL immediately and moves on.  Defaults
   and their env overrides::

       CITATION_RECHECK_RETRY_INITIAL_SECONDS       = 2.0
         VIBELUTION_CITATION_RECHECK_RETRY_INITIAL_SECONDS
       CITATION_RECHECK_RETRY_BACKOFF_COEFFICIENT   = 2.0
         VIBELUTION_CITATION_RECHECK_RETRY_BACKOFF_COEFFICIENT
       CITATION_RECHECK_RETRY_MAX_INTERVAL_SECONDS  = 60.0
         VIBELUTION_CITATION_RECHECK_RETRY_MAX_INTERVAL_SECONDS
       CITATION_RECHECK_RETRY_MAX_ATTEMPTS          = 5
         VIBELUTION_CITATION_RECHECK_RETRY_MAX_ATTEMPTS

   Non-retryable: the URL carries no DOI authority at all (deterministic —
   retrying can never help) and definitive registry rejections
   (``DefinitiveDoiRejection`` / ``NonRetryableReceiptError``, e.g. a 4xx
   that is not 408/429).  Everything else — timeouts, connection errors,
   5xx, unparseable bodies (verifier ``None`` or raised exception) — is
   retried with backoff until ``maximum_attempts``, then recorded failed.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 1
HEARTBEAT_STAGE = "citation_recheck"
HEARTBEAT_CONTRACT = "citation-recheck-heartbeat/v1"
RECORD_KIND = "citation_recheck_event"

KIND_HEARTBEAT = "heartbeat"
KIND_URL_RESULT = "url_result"
KIND_ATTEMPT = "attempt"

OUTCOME_VERIFIED = "verified"
OUTCOME_FAILED = "failed"
OUTCOME_NO_DOI_AUTHORITY = "no_doi_authority"

ATTEMPT_RUNNING = "running"
ATTEMPT_FINISHED = "finished"

# Reasons recorded on url_result failures (stable for UI/audit surfacing).
REASON_ATTEMPTS_EXHAUSTED = "attempts_exhausted"
REASON_NON_RETRYABLE = "non_retryable"
REASON_NO_DOI_AUTHORITY = OUTCOME_NO_DOI_AUTHORITY

_LEDGER_SUFFIX = ".citation-recheck.jsonl"

# ---------------------------------------------------------------------------
# RetryPolicy (Temporal-style)
# ---------------------------------------------------------------------------


class NonRetryableReceiptError(RuntimeError):
    """A receipt verification failed in a way retries can never fix.

    Raised by verifiers (or classifiers) for validation-class rejections —
    e.g. an explicitly refused DOI lookup.  The loop records the failure and
    continues with the next URL instead of burning the backoff budget.
    """

    def __init__(self, message: str, *, reason: str = REASON_NON_RETRYABLE) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class RetryPolicy:
    """Temporal Activity retry semantics for one URL's verification calls.

    ``backoff_seconds(failed_attempts)`` returns the sleep before the next
    attempt: ``initial * coefficient ** (failed_attempts - 1)``, capped at
    ``maximum_interval_seconds``.
    """

    initial_interval_seconds: float = 2.0
    backoff_coefficient: float = 2.0
    maximum_interval_seconds: float = 60.0
    maximum_attempts: int = 5

    def backoff_seconds(self, failed_attempts: int) -> float:
        if failed_attempts <= 0:
            return self.initial_interval_seconds
        raw = self.initial_interval_seconds * (
            self.backoff_coefficient ** (failed_attempts - 1)
        )
        return min(self.maximum_interval_seconds, raw)


_RETRY_ENV_INITIAL = "VIBELUTION_CITATION_RECHECK_RETRY_INITIAL_SECONDS"
_RETRY_ENV_BACKOFF = "VIBELUTION_CITATION_RECHECK_RETRY_BACKOFF_COEFFICIENT"
_RETRY_ENV_MAX_INTERVAL = "VIBELUTION_CITATION_RECHECK_RETRY_MAX_INTERVAL_SECONDS"
_RETRY_ENV_MAX_ATTEMPTS = "VIBELUTION_CITATION_RECHECK_RETRY_MAX_ATTEMPTS"


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(float(raw))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def load_retry_policy_from_env() -> RetryPolicy:
    """RetryPolicy with the documented env overrides applied (clamped)."""

    initial = _env_float(_RETRY_ENV_INITIAL, 2.0, minimum=0.0)
    backoff = _env_float(_RETRY_ENV_BACKOFF, 2.0, minimum=1.0)
    maximum_interval = _env_float(_RETRY_ENV_MAX_INTERVAL, 60.0, minimum=initial)
    maximum_attempts = _env_int(_RETRY_ENV_MAX_ATTEMPTS, 5, minimum=1, maximum=20)
    return RetryPolicy(
        initial_interval_seconds=initial,
        backoff_coefficient=backoff,
        maximum_interval_seconds=maximum_interval,
        maximum_attempts=maximum_attempts,
    )


# ---------------------------------------------------------------------------
# Ledger plumbing (mirrors hypothesis_command_attempts: append-only JSONL,
# latest-wins reads, brief per-file OS lock — never a long module lock).
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def recheck_ledger_path(team_id: str, question_id: str, run_id: str) -> Path:
    """Ledger path next to the run artifact under the team program root.

    ``<program-root>/challenge_program/question_runs/<question>/<run>.citation-recheck.jsonl``
    """

    from core.web.services.team_workflow.research_projects import (
        resolve_team_program_root,
    )

    normalized_question = str(question_id or "").strip().upper()
    normalized_run = str(run_id or "").strip()
    return (
        resolve_team_program_root(team_id)
        / "challenge_program"
        / "question_runs"
        / normalized_question
        / f"{normalized_run}{_LEDGER_SUFFIX}"
    )


def append_recheck_event(path: Path, record: dict[str, Any]) -> None:
    from core.web.services.team_workflow.storage_durability import append_jsonl_locked

    append_jsonl_locked(path, record)


def read_recheck_events(path: Path) -> list[dict[str, Any]]:
    from core.web.services.team_workflow.storage_durability import read_jsonl_tolerant

    return [
        record
        for record in read_jsonl_tolerant(path)
        if str(record.get("recordKind") or "") == RECORD_KIND
    ]


def read_resume_verified(path: Path) -> dict[str, bool]:
    """Latest-wins resume cache: source URLs verified by an earlier pass.

    Only ``verified`` outcomes survive; a later failure for the same URL
    removes it so the next recheck re-attempts it.
    """

    resume: dict[str, bool] = {}
    for record in read_recheck_events(path):
        if str(record.get("kind") or "") != KIND_URL_RESULT:
            continue
        source_url = str(record.get("sourceUrl") or "").strip()
        if not source_url:
            continue
        if str(record.get("outcome") or "") == OUTCOME_VERIFIED:
            resume[source_url] = True
        else:
            resume.pop(source_url, None)
    return resume


def read_failed_receipts(path: Path) -> list[dict[str, Any]]:
    """Latest-wins per-URL failure entries from the ledger."""

    latest: dict[str, dict[str, Any]] = {}
    for record in read_recheck_events(path):
        if str(record.get("kind") or "") != KIND_URL_RESULT:
            continue
        source_url = str(record.get("sourceUrl") or "").strip()
        if not source_url:
            continue
        latest[source_url] = record
    return [
        {
            "sourceUrl": source_url,
            "outcome": str(record.get("outcome") or ""),
            "reason": str(record.get("reason") or ""),
            "attempts": int(record.get("attempts") or 0),
            "at": str(record.get("at") or ""),
        }
        for source_url, record in sorted(latest.items())
        if str(record.get("outcome") or "") != OUTCOME_VERIFIED
    ]


def read_latest_heartbeat(path: Path) -> dict[str, Any] | None:
    for record in reversed(read_recheck_events(path)):
        if str(record.get("kind") or "") == KIND_HEARTBEAT:
            return record
    return None


def read_latest_attempt(path: Path) -> dict[str, Any] | None:
    for record in reversed(read_recheck_events(path)):
        if str(record.get("kind") or "") == KIND_ATTEMPT:
            return record
    return None


def progress_report(path: Path, *, team_id: str, question_id: str, run_id: str) -> dict[str, Any]:
    """Read-only projection of one run's recheck progress (no store locks)."""

    heartbeat = read_latest_heartbeat(path)
    attempt = read_latest_attempt(path)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "contract": HEARTBEAT_CONTRACT,
        "stage": HEARTBEAT_STAGE,
        "teamId": str(team_id or "").strip(),
        "questionId": str(question_id or "").strip().upper(),
        "runId": str(run_id or "").strip(),
        "heartbeat": {
            "attemptId": str(heartbeat.get("attemptId") or ""),
            "done": int(heartbeat.get("done") or 0),
            "total": int(heartbeat.get("total") or 0),
            "etaSeconds": float(heartbeat.get("etaSeconds") or 0.0),
            "at": str(heartbeat.get("at") or ""),
        }
        if heartbeat
        else None,
        "attempt": {
            "attemptId": str(attempt.get("attemptId") or ""),
            "status": str(attempt.get("status") or ""),
            "total": int(attempt.get("total") or 0),
            "forceFull": bool(attempt.get("forceFull") or False),
            "outcome": str(attempt.get("outcome") or ""),
            "at": str(attempt.get("at") or ""),
        }
        if attempt
        else None,
        "verifiedSourceUrls": sorted(read_resume_verified(path)),
        "failedSourceUrls": read_failed_receipts(path),
        "eventCount": len(read_recheck_events(path)),
    }


# ---------------------------------------------------------------------------
# The recheck loop
# ---------------------------------------------------------------------------


def verify_receipts_with_heartbeat(
    checks: Sequence[Mapping[str, Any]],
    *,
    team_id: str,
    question_id: str,
    run_id: str,
    ledger_path: Path,
    verifier: Callable[[str], Mapping[str, Any] | None] | None = None,
    timeout_seconds: float | None = None,
    max_verifications: int = 0,
    force_full: bool = False,
    resume_verified: Mapping[str, bool] | None = None,
    retry_policy: RetryPolicy | None = None,
    sleeper: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Verify failing citation receipts with heartbeat, resume and retries.

    Report shape is a superset of
    :func:`doi_metadata_verification.verify_failed_receipt_dois` — its keys
    keep their semantics (``attemptedCount`` counts URLs that entered
    network verification; retries within one URL do not increment it) —
    plus the resume/failure extras ``resumedSourceUrls``,
    ``failedSourceUrls`` and ``ledgerWriteFailures``.

    ``KeyboardInterrupt``/``SystemExit`` are never retried or swallowed:
    they propagate after the already-processed URLs are persisted, which is
    exactly the interrupted-run resume case.
    """

    from core.web.services.team_workflow.doi_metadata_verification import (
        DEFAULT_TIMEOUT_SECONDS,
        DefinitiveDoiRejection,
        extract_doi,
        fetch_doi_metadata,
    )

    policy = retry_policy or load_retry_policy_from_env()
    sleep = sleeper if sleeper is not None else time.sleep
    # Resume defaults to the run's own ledger; explicit injection (tests,
    # pre-warmed caches) wins, ``force_full`` disables resuming entirely.
    if resume_verified is not None:
        resume = {} if force_full else dict(resume_verified)
    else:
        resume = {} if force_full else read_resume_verified(ledger_path)
    total = len(checks)
    attempt_id = f"citrecheck-{uuid4().hex[:20]}"

    write_failures = 0

    def _append(record: dict[str, Any]) -> bool:
        # Best-effort: the ledger is progress metadata, not gate evidence.
        # A lost heartbeat can only cause a safe re-verification later.
        try:
            append_recheck_event(ledger_path, record)
            return True
        except Exception:  # noqa: BLE001 - progress must never kill the recheck
            return False

    def _event(kind: str, **fields: Any) -> bool:
        record: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "recordKind": RECORD_KIND,
            "kind": kind,
            "stage": HEARTBEAT_STAGE,
            "attemptId": attempt_id,
            "teamId": str(team_id or "").strip(),
            "questionId": str(question_id or "").strip().upper(),
            "runId": str(run_id or "").strip(),
            "at": _utc_now(),
            "atMs": int(time.time() * 1000),
            **fields,
        }
        return _append(record)

    done = 0

    def _beat(*, resumed: bool = False) -> None:
        # Heartbeat after every processed evidence row (the SCI-049 payload
        # contract): naive linear ETA over the observed pace.
        nonlocal write_failures
        elapsed = max(0.0, monotonic() - started)
        remaining = max(0, total - done)
        eta = round((elapsed / done) * remaining, 1) if done > 0 else 0.0
        fields: dict[str, Any] = {"done": done, "total": total, "etaSeconds": eta}
        if resumed:
            fields["resumed"] = True
        if not _event(KIND_HEARTBEAT, **fields):
            write_failures += 1

    def _url_result(*, source_url: str, outcome: str, reason: str, attempts: int) -> None:
        nonlocal write_failures
        if not _event(
            KIND_URL_RESULT,
            sourceUrl=source_url,
            outcome=outcome,
            reason=reason,
            attempts=int(attempts),
        ):
            write_failures += 1

    if not _event(
        KIND_ATTEMPT,
        status=ATTEMPT_RUNNING,
        total=total,
        forceFull=bool(force_full),
    ):
        write_failures += 1
    started = monotonic()
    outcome = "completed"
    try:
        verified: dict[str, bool] = {}
        unresolved: list[str] = []
        failures: list[dict[str, Any]] = []
        attempted = 0
        for item in checks:
            if not isinstance(item, Mapping):
                continue
            source_url = str(item.get("sourceUrl") or item.get("source_url") or "").strip()
            if not source_url or source_url in verified:
                # Empty/duplicate row: count it so done always converges on total.
                done += 1
                _beat()
                continue
            if str(item.get("status") or "").lower() == "passed":
                # Already passing without the DOI fallback: counted so the
                # progress covers the whole evidence set, no network spent.
                done += 1
                _beat()
                continue
            if source_url in resume:
                # Resume: a previous pass already verified this URL; keep the
                # verified receipt without another network attempt.
                verified[source_url] = True
                done += 1
                _beat(resumed=True)
                continue
            doi = extract_doi(source_url, item.get("doi"))
            if not doi:
                # No DOI authority: deterministic, non-retryable, and — as
                # before — not even counted as a network attempt.
                failures.append(
                    {
                        "sourceUrl": source_url,
                        "reason": REASON_NO_DOI_AUTHORITY,
                        "attempts": 0,
                    }
                )
                _url_result(
                    source_url=source_url,
                    outcome=OUTCOME_NO_DOI_AUTHORITY,
                    reason=REASON_NO_DOI_AUTHORITY,
                    attempts=0,
                )
                done += 1
                _beat()
                continue
            if max_verifications and attempted >= max_verifications:
                break
            attempted += 1
            attempts = 0
            failure_reason = ""
            while attempts < policy.maximum_attempts:
                attempts += 1
                metadata: Mapping[str, Any] | None = None
                failure_reason = ""
                try:
                    if verifier is not None:
                        metadata = verifier(doi)
                    else:
                        effective_timeout = (
                            DEFAULT_TIMEOUT_SECONDS
                            if timeout_seconds is None
                            else max(0.5, float(timeout_seconds))
                        )
                        # Definitive registry rejections (4xx except 408/429)
                        # surface as DefinitiveDoiRejection so the retry
                        # policy can short-circuit them; package builders
                        # keep the old swallow-to-None default.
                        metadata = fetch_doi_metadata(
                            doi,
                            timeout_seconds=effective_timeout,
                            raise_definitive_rejections=True,
                        )
                except (KeyboardInterrupt, SystemExit):
                    raise
                except NonRetryableReceiptError as exc:
                    failure_reason = str(exc.reason or REASON_NON_RETRYABLE)
                except DefinitiveDoiRejection as exc:
                    status_code = getattr(exc, "status_code", None)
                    failure_reason = (
                        f"doi_definitive_rejection:{status_code}"
                        if status_code
                        else "doi_definitive_rejection"
                    )
                except Exception:  # noqa: BLE001 - transient trouble is retryable
                    failure_reason = ""
                if metadata is not None:
                    verified[source_url] = True
                    break
                if failure_reason:
                    break  # non-retryable: record and move on
                if attempts >= policy.maximum_attempts:
                    break
                sleep(policy.backoff_seconds(attempts))
            if source_url in verified:
                _url_result(
                    source_url=source_url,
                    outcome=OUTCOME_VERIFIED,
                    reason="",
                    attempts=attempts,
                )
                done += 1
                _beat()
                continue
            reason = failure_reason or REASON_ATTEMPTS_EXHAUSTED
            unresolved.append(source_url)
            failures.append({"sourceUrl": source_url, "reason": reason, "attempts": attempts})
            _url_result(
                source_url=source_url,
                outcome=OUTCOME_FAILED,
                reason=reason,
                attempts=attempts,
            )
            done += 1
            _beat()
        return {
            "verifiedSourceUrls": verified,
            "attemptedCount": attempted,
            "verifiedCount": len(verified),
            "unresolvedSourceUrls": unresolved,
            "resumedSourceUrls": sorted(resume),
            "failedSourceUrls": failures,
            "ledgerWriteFailures": write_failures,
        }
    except (KeyboardInterrupt, SystemExit):
        outcome = "interrupted"
        raise
    finally:
        _event(
            KIND_ATTEMPT,
            status=ATTEMPT_FINISHED,
            total=total,
            forceFull=bool(force_full),
            outcome=outcome,
        )


__all__ = [
    "ATTEMPT_FINISHED",
    "ATTEMPT_RUNNING",
    "HEARTBEAT_CONTRACT",
    "HEARTBEAT_STAGE",
    "KIND_ATTEMPT",
    "KIND_HEARTBEAT",
    "KIND_URL_RESULT",
    "OUTCOME_FAILED",
    "OUTCOME_NO_DOI_AUTHORITY",
    "OUTCOME_VERIFIED",
    "REASON_ATTEMPTS_EXHAUSTED",
    "REASON_NON_RETRYABLE",
    "RECORD_KIND",
    "SCHEMA_VERSION",
    "NonRetryableReceiptError",
    "RetryPolicy",
    "append_recheck_event",
    "load_retry_policy_from_env",
    "progress_report",
    "read_failed_receipts",
    "read_latest_attempt",
    "read_latest_heartbeat",
    "read_recheck_events",
    "read_resume_verified",
    "recheck_ledger_path",
    "verify_receipts_with_heartbeat",
]
