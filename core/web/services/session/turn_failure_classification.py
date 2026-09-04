"""Turn terminal-failure classification: the single owner that maps the
centralized LLM error classifier (``core/llm/error_classification.py``) onto
the session turn terminal-status vocabulary.

Before this module the ``failed`` vs ``failed_provider`` split was guessed by
the ``_PROVIDER_ERROR_PATTERN`` regex on raw error text. The classifier now
decides, but it answers "what kind of LLM error is this" -- not "which
existing terminal value should this turn carry". This module is that mapping:

- ``provider_family`` selects the existing ``failed_provider`` value; anything
  else keeps the plain ``failed``/``failed_runtime`` values. No new terminal
  status or problem-code enums are invented here, so journal projection, UI
  and diagnosis consumers stay compatible (additive diagnosis fields only).
- ``disposition`` mirrors the classifier's three-value view
  (``transient_retryable`` / ``permanent`` / ``budget_or_context``).
- ``problem_code`` reuses the established ``context_budget_exhausted`` code
  for the budget family so downstream loop detection
  (``stage_session_replay._CONTEXT_BUDGET_LOOP_MARKERS``) can see it.

Workflow-orchestration semantics borrowed for the family rule (recorded as
EXTERNAL reuse evidence):

- Prefect separates ``failed`` (re-runnable work failure) from ``crashed``
  (worker/process death). ``worker_gone`` / cancellation markers are process
  lifecycle events: they must never be classified into the provider family,
  even when the surrounding text mentions provider error tokens.
- Temporal separates retryable transport failures from non-retryable
  ``ApplicationError``. Unknown errors stay fail-closed: non-provider family,
  ``permanent`` disposition, never widened.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from core.llm.error_classification import (
    BUDGET_OR_CONTEXT,
    PERMANENT,
    TRANSIENT_RETRYABLE,
    classify_error,
)
from core.llm.types import LLMError

__all__ = [
    "BUDGET_EXHAUSTED_PROBLEM_CODE",
    "TERMINAL_STATUS_FAILURE_DISPOSITION",
    "TurnFailureClassification",
    "classify_turn_failure",
    "derive_failure_disposition",
    "normalize_disposition",
    "resolve_failure_disposition",
]

# Established problem code (agent_turn_completion continuation chain and
# stage_session_replay loop markers already speak it) reused for budget-family
# turn failures so the poisoned-session replay loop keeps detecting them.
BUDGET_EXHAUSTED_PROBLEM_CODE = "context_budget_exhausted"

# Classifier categories that describe the provider transport/protocol domain.
# Kept explicit instead of "everything not X" so a future classifier category
# fails closed to the non-provider family rather than silently widening
# ``failed_provider``.
_PROVIDER_FAMILY_CATEGORIES = frozenset(
    {
        "network_error",
        "server_error",
        "timeout",
        "rate_limit",
        "auth_error",
        "payload_protocol_error",
        "tool_protocol_error",
        "empty_content_error",
        "capability_error",
    }
)

# Categories that are LLM-stack outcomes but never provider failures.
_NON_PROVIDER_LLM_CATEGORIES = frozenset(
    {
        "context_length_error",
        "quota_error",
        "output_truncated",
        "user_interrupt",
    }
)

# ``classify_exception``'s catch-all reuses "provider_protocol_error" for
# unknown errors; only explicit bad-request/400 evidence is a genuine provider
# protocol rejection. Mirrors the classifier's own keyword set so the two stay
# consistent without modifying the frozen classifier.
_GENUINE_PROVIDER_PROTOCOL_PATTERN = re.compile(
    r"bad_request|bad request|invalid params|400",
    re.IGNORECASE,
)

# Prefect failed-vs-crashed semantics: worker death and cancellation are
# process lifecycle events, never provider business failures.
_WORKER_LIFECYCLE_PATTERN = re.compile(
    r"worker[_ ]?gone|worker (?:process )?(?:exited|died|terminated)"
    r"|(?:task|run|node) (?:was |is )?cancell?ed|cancell?ed by(?: the)? (?:user|operator)"
    r"|keyboardinterrupt",
    re.IGNORECASE,
)

# Read-only mapping: terminal status -> failureDisposition for failure
# terminals. Values align with the frozen retry taxonomy
# (``core/research/workflow/contracts/retry_taxonomy.py``):
# - ``transient``          ~ classifier ``transient_retryable`` ~
#   ``retryable_infra`` (same-request replay may succeed; free recovery)
# - ``permanent``          ~ classifier ``permanent`` ~ ``terminal`` /
#   charged ``business_retry`` (fail-closed: unknown failures never widen)
# - ``budget_or_context``  ~ classifier ``budget_or_context`` ~ the
#   ``human_required`` budget family (recovery = compression / limit adjust)
TERMINAL_STATUS_FAILURE_DISPOSITION: Mapping[str, str] = {
    "failed": "permanent",
    "failed_provider": "transient",
    "failed_runtime": "permanent",
    "error": "permanent",
    "cancelled": "permanent",
    "canceled": "permanent",
    "stopped": "permanent",
    "stopped_by_user": "permanent",
    "superseded": "permanent",
    # parked awaiting the explicit continue protocol step: never auto-resumed
    # (charged business per taxonomy), so the fail-closed value is permanent
    "needs_continue": "permanent",
    # parked by the token limit: recovery is compression / limit adjustment
    "paused_limit": "budget_or_context",
}

# Dispositions accepted from persisted evidence (classifier value domain).
_KNOWN_DISPOSITIONS = frozenset({TRANSIENT_RETRYABLE, PERMANENT, BUDGET_OR_CONTEXT})

# Snapshot-facing short aliases (transient) for the classifier value
# (transient_retryable) so downstream payloads stay compact. The mapping above
# already speaks the short form.
_ALIAS_TO_SHORT = {TRANSIENT_RETRYABLE: "transient", PERMANENT: "permanent", BUDGET_OR_CONTEXT: "budget_or_context"}


@dataclass(frozen=True)
class TurnFailureClassification:
    """Classifier verdict projected onto the turn terminal-status vocabulary."""

    category: str
    disposition: str
    provider_family: bool
    problem_code: str


def _is_provider_family(exc: Exception, category: str, raw_error: str) -> bool:
    """Decide the existing ``failed_provider`` vs ``failed`` family.

    Explicit categories decide; the classifier's catch-all reuse of
    ``provider_protocol_error`` only counts as provider when the raw text
    carries genuine bad-request/400 evidence. LLMError instances are trusted
    as provider verdicts (the LLM stack raised them deliberately), except the
    budget/interrupt family which is never provider.
    """

    if category in _NON_PROVIDER_LLM_CATEGORIES:
        return False
    if isinstance(exc, LLMError):
        return True
    if _WORKER_LIFECYCLE_PATTERN.search(raw_error):
        # Prefect crashed-semantics: process lifecycle event, not provider.
        return False
    if category in _PROVIDER_FAMILY_CATEGORIES:
        return True
    if category == "provider_protocol_error":
        return bool(_GENUINE_PROVIDER_PROTOCOL_PATTERN.search(raw_error))
    return False


def classify_turn_failure(raw_error: Any, *, exc: Exception | None = None) -> TurnFailureClassification:
    """Classify a turn failure into family + disposition + problem code.

    Fail-closed: if the classifier itself raises, the failure lands in the
    non-provider family with a ``permanent`` disposition.
    """

    text = str(raw_error or "").strip()
    try:
        classification = classify_error(exc if exc is not None else RuntimeError(text or "unknown turn failure"))
        category = str(classification.category or "").strip()
        disposition = str(classification.disposition or "").strip()
    except Exception:
        category, disposition = "runtime_error", PERMANENT
    provider_family = _is_provider_family(
        exc if exc is not None else RuntimeError(text),
        category,
        text,
    )
    problem_code = BUDGET_EXHAUSTED_PROBLEM_CODE if disposition == BUDGET_OR_CONTEXT else ""
    return TurnFailureClassification(
        category=category,
        disposition=disposition,
        provider_family=provider_family,
        problem_code=problem_code,
    )


def normalize_disposition(value: Any) -> str:
    """Canonical short disposition (``transient``/``permanent``/
    ``budget_or_context``) from either the short form or the classifier's
    ``transient_retryable`` alias; unknown values pass through untouched so
    evidence is never silently dropped.
    """

    text = str(value or "").strip()
    if not text:
        return ""
    return _ALIAS_TO_SHORT.get(text, text)


def derive_failure_disposition(*, problem_code: Any = "", terminal_status: Any = "") -> str:
    """Best-effort disposition from persisted turn diagnostics.

    Budget problem codes win (they are explicit family evidence); otherwise
    the read-only status table answers; unknown/non-failure statuses return
    "" so callers can omit the field instead of inventing a disposition.
    """

    normalized_code = str(problem_code or "").strip().lower()
    if normalized_code == BUDGET_EXHAUSTED_PROBLEM_CODE:
        return _ALIAS_TO_SHORT[BUDGET_OR_CONTEXT]
    normalized_status = str(terminal_status or "").strip().lower()
    return TERMINAL_STATUS_FAILURE_DISPOSITION.get(normalized_status, "")


def resolve_failure_disposition(snapshot: Mapping[str, Any], terminal_status: Any = "") -> str:
    """Pick the failure disposition for a failure propagation detail payload.

    Persisted snapshot evidence (``failureDisposition``) wins; the read-only
    status table is the fallback; a truly unknown status fails closed to
    ``permanent`` (never widened to retryable).
    """

    explicit = str(snapshot.get("failureDisposition") or "").strip()
    if explicit in _KNOWN_DISPOSITIONS:
        return _ALIAS_TO_SHORT.get(explicit, explicit)
    if explicit:
        return explicit
    derived = derive_failure_disposition(
        problem_code=snapshot.get("terminalProblemCode") or snapshot.get("terminalReason"),
        terminal_status=terminal_status,
    )
    return derived or "permanent"
