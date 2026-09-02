"""Real-LLM wiring for the human-click review chain.

The default digest drafter and the four hypothesis review runners are
deterministic DEV fixtures.  This module builds the real model-backed
counterparts from the operator-configured LLM and wires them into the
service-layer defaults:

* ``build_meeting_digest_drafter`` drafts the Coordinator meeting digest
  from the bound room messages.
* ``build_hypothesis_review_runners`` returns the reflection / pairwise /
  Pareto / MetaReview runners consumed by ``execute_hypothesis_review``.

Resolution is lazy and fail-open at *availability* level only: when no model
is configured the callers keep the DEV fixture behaviour, so DEV/CI stays
deterministic.  Every fallback branch announces itself (warning log plus a
quiet ``review_llm.resolve.unavailable`` scene event naming the missing
configuration), so fixture reviews are never silent.  Once a runner runs, it
fails closed — any malformed model
output raises ``ContractValidationError`` before anything is persisted,
mirroring the executor contract.  A failed call (timeout, provider error,
invalid JSON) also persists its raw response — when one was received — under
the system temp directory (24h self-cleaning sweep, no credentials, no
prompts) so malformed provider output can be attributed offline; success
paths never write anything, and a dump failure only logs.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from config import get_config
from core.infrastructure.llm_utils import build_cacheable_system_message
from core.llm import LLMInvocationContext, get_llm_client, invoke_llm
from core.llm.agent_runtime import agent_dialogue_model_id, config_for_agent_llm_model
from core.llm.client import (
    MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY,
    llm_cancel_context,
    model_invocation_receipt_context_scope,
)
from core.llm.invocation import invoke_llm_outcome
from core.llm.semantic_messages import SemanticOutputSchema
from core.llm.types import LLMError
from core.research.competition.question_result_package import (
    REQUIRED_REVIEW_DIMENSIONS,
    REVIEW_DIMENSION_RATINGS,
)
from core.research.workflow.contracts import (
    CORE_HYPOTHESIS_COHERENCE_CHECK_IDS,
    ContractValidationError,
    CoreHypothesisCoherenceResult,
)
from core.research.workflow.contracts.hypothesis_quality import (
    HYPOTHESIS_SCORE_DIMENSIONS,
    canonical_hypothesis_score_rubric,
)
from core.web.services.team.team_constants import CHALLENGE_CUP_RESEARCH_TEAM_ID
from core.web.services.team_workflow.hypothesis_review_executor import (
    ProviderBoundReviewResult,
)

REVIEW_LLM_PROFILE_ID = "primary"
REVIEW_LLM_SURFACE = "team_workflow_review"
REVIEW_LLM_CACHE_SCOPE = "team_workflow_review"

logger = logging.getLogger(__name__)

_MAX_MESSAGES = 40

# Fallback wall-clock budget for one review-profile LLM call (digest draft and
# the four hypothesis review runners).  Live budgets are receipt-derived:
# ``review_llm_call_timeout_seconds`` resolves p95 latency from succeeded
# model invocation receipts via ``derive_per_call_budget``, bounded to the
# governed 300-600s band.  This 450s constant is the audited fallback for a
# malformed env override and mirrors ``DEFAULT_PER_CALL_BUDGET_MS`` in
# challenge_deadline_policy.py: it sits above the global success-receipt p95
# (~360s over 221 receipts), while the slowest observed route
# (``relay_autodl/GLM-5.3-flash``, p95 ~478s, max ~506s) is covered by the
# receipt-derived review budget, not by this fallback.  Without a finite
# budget a wedged provider connection pinned the meeting in ``summarizing``
# for 33+ minutes while holding the per-meeting summary lock with no
# in-product recovery path (SCI-096 P0, validated 2026-08-28).  Budgets of
# 180s and 360s both produced false timeouts on valid low-cost digest
# attempts.
REVIEW_LLM_CALL_TIMEOUT_SECONDS = 450.0
_REVIEW_LLM_CALL_TIMEOUT_ENV = "VIBELUTION_REVIEW_LLM_CALL_TIMEOUT_SECONDS"

# ---------------------------------------------------------------------------
# Per-purpose output-token clamp and structured-output schema
# ---------------------------------------------------------------------------
#
# The operator profile for short structured review calls historically ran with
# the profile-wide ``max_output_tokens`` (32768 on relay_autodl/GLM-5.3-flash)
# while the runtime receipts show review outputs averaging ~2K tokens.  These
# clamps cap each structured call's ``max_tokens`` so a runaway/looping
# generation cannot burn the full profile budget (a malformed call already
# fails closed and is re-burned at full price).  The clamp is an *upper*
# bound: responses stay well under it, leaving ~4x headroom over the observed
# mean.
#
# - ``VIBELUTION_REVIEW_JSON_MAX_OUTPUT_TOKENS``: reflection / pairwise /
#   pareto / metareview JSON review calls (default 8192).
# - ``VIBELUTION_DIGEST_MAX_OUTPUT_TOKENS``: the meeting digest Markdown call
#   (default 8192; medium-length output).
# - The revision runner (long revised candidate prose) and every speaker /
#   chat path are deliberately NOT clamped and keep the profile default.
_REVIEW_JSON_MAX_OUTPUT_TOKENS_ENV = "VIBELUTION_REVIEW_JSON_MAX_OUTPUT_TOKENS"
_DIGEST_MAX_OUTPUT_TOKENS_ENV = "VIBELUTION_DIGEST_MAX_OUTPUT_TOKENS"
_REVIEW_MAX_OUTPUT_TOKENS_DEFAULT = 8192
_REVIEW_MAX_OUTPUT_TOKENS_MIN = 512
_REVIEW_MAX_OUTPUT_TOKENS_MAX = 65536


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def review_json_max_output_tokens() -> int:
    """Per-call ``max_tokens`` clamp for the structured JSON review calls."""

    return _env_int(
        _REVIEW_JSON_MAX_OUTPUT_TOKENS_ENV,
        _REVIEW_MAX_OUTPUT_TOKENS_DEFAULT,
        minimum=_REVIEW_MAX_OUTPUT_TOKENS_MIN,
        maximum=_REVIEW_MAX_OUTPUT_TOKENS_MAX,
    )


def digest_max_output_tokens() -> int:
    """Per-call ``max_tokens`` clamp for the meeting digest draft call."""

    return _env_int(
        _DIGEST_MAX_OUTPUT_TOKENS_ENV,
        _REVIEW_MAX_OUTPUT_TOKENS_DEFAULT,
        minimum=_REVIEW_MAX_OUTPUT_TOKENS_MIN,
        maximum=_REVIEW_MAX_OUTPUT_TOKENS_MAX,
    )


def _purpose_max_output_tokens(purpose: str) -> int | None:
    """Return the per-call output clamp for ``purpose`` (``None`` = profile)."""

    normalized = str(purpose or "").strip()
    if normalized == "meeting_digest":
        return digest_max_output_tokens()
    if normalized in {
        "hypothesis_reflection",
        "hypothesis_pairwise",
        "hypothesis_pareto",
        "hypothesis_metareview",
    }:
        return review_json_max_output_tokens()
    return None


# Strict JSON schemas for the structured review calls.  They only constrain
# generation when the resolved provider capability
# ``supports_strict_json_schema`` is true (the client-side gate in
# ``LLMClient._build_payload`` would otherwise reject the call); the existing
# brace-tolerant parsing plus contract validation below stay authoritative
# either way, so capability=false or an unexpected provider answer keeps the
# previous behavior.  Optional top-level fields (noveltyContrast,
# coreHypothesisCoherence) are intentionally left out of ``required`` because
# the prompts allow omitting them.
_REVIEW_JSON_SCHEMAS: dict[str, dict[str, Any]] = {
    "hypothesis_reflection": {
        "type": "object",
        "properties": {
            "claim": {"type": "string"},
            "rationale": {"type": "string"},
            "differenceFromAlternatives": {"type": "string"},
            "lineageRefs": {"type": "array", "items": {"type": "string"}},
            "scores": {
                "type": "object",
                "properties": {
                    dimension: {"type": "number"}
                    for dimension in HYPOTHESIS_SCORE_DIMENSIONS
                },
                "required": list(HYPOTHESIS_SCORE_DIMENSIONS),
                "additionalProperties": False,
            },
            "reviewedBy": {"type": "string"},
            "status": {"type": "string"},
            "dimensionReviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hypothesis_id": {"type": "string"},
                        "dimension": {"type": "string"},
                        "rating": {"type": "string"},
                        "rationale": {"type": "string"},
                        "reviewer": {"type": "string"},
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "hypothesis_id",
                        "dimension",
                        "rating",
                        "rationale",
                        "reviewer",
                        "evidence_refs",
                    ],
                    "additionalProperties": False,
                },
            },
            "noveltyContrast": {
                "type": "object",
                "properties": {
                    "overlapPapers": {"type": "array", "items": {"type": "string"}},
                    "deltaStatement": {"type": "string"},
                    "basis": {"type": "string"},
                },
                "required": ["overlapPapers", "deltaStatement", "basis"],
                "additionalProperties": False,
            },
            "coreHypothesisCoherence": {
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "reviewer": {"type": "string"},
                    "checks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "checkId": {"type": "string"},
                                "passed": {"type": "boolean"},
                                "rationale": {"type": "string"},
                                "claimRefs": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "evidenceRefs": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": [
                                "checkId",
                                "passed",
                                "rationale",
                                "claimRefs",
                                "evidenceRefs",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["candidateId", "reviewer", "checks"],
                "additionalProperties": False,
            },
        },
        "required": [
            "claim",
            "rationale",
            "differenceFromAlternatives",
            "lineageRefs",
            "scores",
            "reviewedBy",
            "status",
            "dimensionReviews",
        ],
        "additionalProperties": False,
    },
    "hypothesis_pairwise": {
        "type": "object",
        "properties": {
            "outcome": {"type": "string"},
            "justification": {"type": "string"},
        },
        "required": ["outcome", "justification"],
        "additionalProperties": False,
    },
    "hypothesis_pareto": {
        "type": "object",
        "properties": {
            "paretoFrontCandidateIds": {
                "type": "array",
                "items": {"type": "string"},
            },
            "dominatedCandidateIds": {
                "type": "array",
                "items": {"type": "string"},
            },
            "notes": {"type": "string"},
        },
        "required": ["paretoFrontCandidateIds", "dominatedCandidateIds", "notes"],
        "additionalProperties": False,
    },
    "hypothesis_metareview": {
        "type": "object",
        "properties": {
            "recommendationCandidateId": {"type": "string"},
            "rationale": {"type": "string"},
            "riskNotes": {"type": "string"},
            "accepted": {"type": "boolean"},
        },
        "required": [
            "recommendationCandidateId",
            "rationale",
            "riskNotes",
            "accepted",
        ],
        "additionalProperties": False,
    },
}


def _purpose_output_schema(purpose: str, llm: Mapping[str, Any]) -> SemanticOutputSchema | None:
    """Structured-output schema for ``purpose`` when the provider supports it.

    Returns ``None`` — keeping the prompt + brace-tolerant parsing path — for
    text-mode purposes, unstructured purposes (revision), and providers whose
    resolved capability ``supports_strict_json_schema`` is false or missing.
    """

    schema_body = _REVIEW_JSON_SCHEMAS.get(str(purpose or "").strip())
    if schema_body is None:
        return None
    capabilities = getattr(llm.get("client"), "capabilities", None)
    if not bool(getattr(capabilities, "supports_strict_json_schema", False)):
        return None
    return SemanticOutputSchema(name=f"{purpose}_v1", schema=schema_body)


def _record_meeting_digest_scene_event(
    event_code: str,
    *,
    outcome: str,
    fields: Mapping[str, Any],
    level: str = "info",
) -> None:
    """Emit bounded digest diagnostics without affecting model execution."""

    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow",
            "meeting_digest",
            event_code,
            message="Meeting digest LLM stage observed.",
            level=level,
            outcome=outcome,
            fields=dict(fields),
            lifecycle=False,
        )
    except Exception:  # noqa: BLE001 - diagnostics must never fail the LLM call
        # Diagnostics are never allowed to change the digest contract.
        return


def _review_llm_error_category(error: Exception) -> str:
    if isinstance(error, ReviewLLMTimeoutError):
        return "timeout"
    if is_recoverable_review_llm_gate_error(error):
        return "llm_gate_rejected"
    if isinstance(error, ContractValidationError):
        return "contract_validation"
    if isinstance(error, LLMError):
        return "provider_error"
    return "runtime_error"


# Backwards-compatible alias: the category helper predates the review-wide
# failure dump and was originally named for the digest drafter.
_meeting_digest_error_category = _review_llm_error_category


# ---------------------------------------------------------------------------
# Failed-response evidence dump (offline attribution support)
# ---------------------------------------------------------------------------


# A review LLM call that fails (timeout, invalid JSON, provider error) used to
# lose its raw response: only outputChars/errorCategory survived, so malformed
# provider output could not be attributed offline.  Failed raw responses are
# now persisted under the system temp directory only — never the checkout root
# or any product directory.  Retention is self-cleaning: every dump sweeps
# sibling files older than 24 hours, and the timestamped names make manual
# cleanup trivial.  Successful calls never write anything.
_REVIEW_LLM_FAILURE_DUMP_DIRNAME = "vibelution-review-llm-failures"
_REVIEW_LLM_FAILURE_RETENTION_SECONDS = 24 * 3600
_REVIEW_LLM_FAILURE_MAX_CHARS = 1_000_000

# Tests redirect this to a per-test directory; production always resolves the
# system temp directory.
_REVIEW_LLM_FAILURE_DUMP_DIR_OVERRIDE: str | None = None


def _review_llm_failure_dump_dir() -> str:
    if _REVIEW_LLM_FAILURE_DUMP_DIR_OVERRIDE:
        return str(_REVIEW_LLM_FAILURE_DUMP_DIR_OVERRIDE)
    return os.path.join(tempfile.gettempdir(), _REVIEW_LLM_FAILURE_DUMP_DIRNAME)


def _safe_filename_part(value: Any, *, fallback: str, limit: int = 32) -> str:
    part = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in str(value or "").strip()
    )
    return part[:limit].strip("-.") or fallback


def _sweep_expired_failure_dumps(directory: str, *, now_s: float) -> None:
    """Delete dump files older than the retention window (best effort)."""

    for name in os.listdir(directory):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        try:
            if now_s - os.path.getmtime(path) > _REVIEW_LLM_FAILURE_RETENTION_SECONDS:
                os.remove(path)
        except OSError:
            continue


def _dump_failed_review_response(
    *,
    purpose: str,
    failure_category: str,
    error: Exception,
    raw_response: str,
    session_id: str = "",
    meeting_round_id: str = "",
    context_id: str = "",
    run_id: str = "",
    model_ref: str = "",
) -> None:
    """Persist one failed review LLM raw response for offline triage.

    Diagnostics only: this must never change the call's contract, so any
    failure inside is swallowed with one bounded warning log.  The file
    carries the raw model response plus bounded identity fields (purpose,
    failure category, timestamps, run/meeting/session ids) and never
    credentials or prompts.
    """

    try:
        directory = _review_llm_failure_dump_dir()
        now_s = time.time()
        os.makedirs(directory, exist_ok=True)
        _sweep_expired_failure_dumps(directory, now_s=now_s)
        captured_at = datetime.now(timezone.utc)
        safe_response = str(raw_response or "")[:_REVIEW_LLM_FAILURE_MAX_CHARS]
        record = {
            "schemaVersion": 1,
            "purpose": str(purpose),
            "failureCategory": str(failure_category),
            "errorType": type(error).__name__,
            "errorSummary": f"{type(error).__name__}: {error}".replace("\n", " ")[:200],
            "runId": str(run_id or ""),
            "sessionId": str(session_id or ""),
            "meetingRoundId": str(meeting_round_id or ""),
            "contextId": str(context_id or ""),
            "modelRef": str(model_ref or ""),
            "capturedAt": captured_at.isoformat(),
            "responseChars": len(safe_response),
            "rawResponse": safe_response,
        }
        filename = "-".join(
            (
                captured_at.strftime("%Y%m%dT%H%M%S"),
                uuid.uuid4().hex[:8],
                _safe_filename_part(purpose, fallback="purpose"),
                _safe_filename_part(failure_category, fallback="failure"),
                _safe_filename_part(session_id or run_id, fallback="session"),
            )
        )
        path = os.path.join(directory, f"{filename}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001 - diagnostics must never fail the call
        logger.warning(
            "review LLM failure dump was not written (%s/%s): %s: %s",
            purpose,
            failure_category,
            type(exc).__name__,
            exc,
        )


def _user_payload_context_id(user_payload: Mapping[str, Any]) -> str:
    context = user_payload.get("context")
    if isinstance(context, Mapping):
        return str(context.get("contextId") or "").strip()
    return ""


def _response_usage_fields(response: Any) -> dict[str, Any]:
    metadata = getattr(response, "response_metadata", None)
    metadata = metadata if isinstance(metadata, Mapping) else {}
    usage = metadata.get("usage_observation")
    usage = usage if isinstance(usage, Mapping) else {}

    def nonnegative_int(key: str) -> int:
        value = usage.get(key)
        if isinstance(value, bool):
            return 0
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    finish_reason = str(
        metadata.get("finish_reason") or metadata.get("finishReason") or ""
    ).strip()
    additional_kwargs = getattr(response, "additional_kwargs", None)
    additional_kwargs = (
        additional_kwargs if isinstance(additional_kwargs, Mapping) else {}
    )
    outcome = additional_kwargs.get("turn_outcome")
    outcome_kind = str(getattr(outcome, "kind", "") or "").strip()
    terminal_event = next(
        (
            event
            for event in reversed(tuple(getattr(outcome, "events", ()) or ()))
            if bool(getattr(event, "terminal", False))
        ),
        None,
    )
    provider_terminal = str(
        getattr(terminal_event, "provider_event_type", "") or ""
    ).strip()
    if not finish_reason and provider_terminal.startswith("chat.finish."):
        finish_reason = provider_terminal.removeprefix("chat.finish.")
    elif not finish_reason and provider_terminal:
        finish_reason = provider_terminal
    return {
        "inputTokens": nonnegative_int("input_tokens"),
        "outputTokens": nonnegative_int("output_tokens"),
        "reasoningOutputTokens": nonnegative_int("reasoning_output_tokens"),
        "totalTokens": nonnegative_int("total_tokens"),
        "finishReason": finish_reason,
        "outcomeKind": outcome_kind,
        "usageObserved": bool(usage),
    }


def review_llm_call_timeout_seconds(*, model_ref: str = "") -> float:
    """Return the receipt-derived review-call budget.

    The historical seconds override remains accepted only inside the governed
    300-600 second range.  New deployments should use the shared millisecond
    Challenge policy override so its source is persisted in the meeting.
    """

    raw = str(os.environ.get(_REVIEW_LLM_CALL_TIMEOUT_ENV) or "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return REVIEW_LLM_CALL_TIMEOUT_SECONDS
        if 300.0 <= value <= 600.0:
            return value
    from core.web.services.team_workflow.challenge_deadline_policy import (
        derive_per_call_budget,
    )

    return float(
        derive_per_call_budget(
            CHALLENGE_CUP_RESEARCH_TEAM_ID,
            model_refs=[model_ref] if model_ref else [],
            purpose="team_workflow_review",
        )["perCallBudgetMs"]
    ) / 1000.0


class ReviewLLMTimeoutError(LLMError):
    """One review-profile LLM call exceeded the configured wall-clock budget.

    Classified as non-retryable cancellation because the absolute Challenge
    fence has already elapsed.  Retrying inside the same meeting would only
    create a duplicate late provider call.
    """

    def __init__(self, *, purpose: str, timeout_seconds: float) -> None:
        super().__init__(
            "cancelled",
            f"review step `{purpose}` did not return within {timeout_seconds:g}s",
            retryable=False,
        )
        self.purpose = str(purpose)
        self.timeout_seconds = float(timeout_seconds)


# ---------------------------------------------------------------------------
# Global LLM concurrency gate (Challenge 10-way parallel review guard)
# ---------------------------------------------------------------------------

# Every review wave opens one ThreadPoolExecutor per question with
# ``MAX_CONCURRENT_REVIEW_CALLS`` workers, so N concurrent questions multiply
# into N x 4 in-flight provider calls with no process-wide ceiling (the
# 10-question Challenge wave therefore fires up to 40 simultaneous LLM
# calls).  This gate adds the missing process-level ceiling around the single
# funnel every review call passes through (`_invoke_review_llm` ->
# `_invoke_llm_with_timeout`), so the gated in-flight count measures real
# provider requests, not merely pooled worker threads.
#
# Sizing follows Little's law against the provider's sustained capacity:
#
#     max_concurrent ~= provider_calls_per_minute * avg_call_wall_clock_s / 60
#
# e.g. a provider sustaining 80 calls/min at a 7.5s average wall clock
# supports ~10 concurrent calls.  Tune ``VIBELUTION_LLM_MAX_CONCURRENT`` to
# the provider's real concurrency budget; the default 10 keeps one full
# 10-question wave flowing without multiplicative fan-out.
_LLM_GATE_MAX_CONCURRENT_ENV = "VIBELUTION_LLM_MAX_CONCURRENT"
_LLM_GATE_MAX_CONCURRENT_DEFAULT = 10
_LLM_GATE_MAX_CONCURRENT_LIMIT = 256

# Waiting on the gate must never become unbounded silent queueing: a caller
# that cannot obtain a slot within this budget fails fast into the existing
# recoverable review-failure path (structured exception -> failure
# classification -> retry/requeue) instead of pinning its worker thread.
_LLM_GATE_ACQUIRE_TIMEOUT_ENV = "VIBELUTION_LLM_GATE_ACQUIRE_TIMEOUT_SECONDS"
_LLM_GATE_ACQUIRE_TIMEOUT_DEFAULT = 120.0

# After a provider 429 (transport category ``rate_limit_error``) the model
# cools down for this long: further attempts for the same model fail fast
# before acquiring a slot, so no request is sent and no worker is pinned.
# The transport-level retry policy inside ``core/llm/client.py`` stays
# authoritative for per-call retries with backoff; this window only stops
# *new* calls from piling onto an already throttled model.
_LLM_RATE_LIMIT_COOLDOWN_ENV = "VIBELUTION_LLM_RATE_LIMIT_COOLDOWN_SECONDS"
_LLM_RATE_LIMIT_COOLDOWN_DEFAULT = 60.0

_gate_state_lock = threading.Lock()
_gate_semaphore: threading.BoundedSemaphore | None = None
_gate_semaphore_size = 0
_rate_limit_cooldown_until: dict[str, float] = {}


class ReviewLLMGateTimeoutError(LLMError):
    """No global LLM concurrency slot was freed within the acquire budget.

    Classified as a recoverable gate rejection (``retryable``): the call
    never reached the provider, so a later retry or requeue loses nothing.
    """

    def __init__(
        self,
        *,
        purpose: str,
        model_ref: str = "",
        wait_seconds: float,
    ) -> None:
        super().__init__(
            "gate_timeout",
            (
                f"review step `{purpose}` waited {wait_seconds:g}s for a "
                "global LLM concurrency slot and was rejected before "
                f"reaching the provider (model={model_ref or 'unresolved'})"
            ),
            retryable=True,
        )
        self.purpose = str(purpose)
        self.model_ref = str(model_ref)
        self.wait_seconds = float(wait_seconds)


class ReviewLLMRateLimitCooldownError(LLMError):
    """The target model is inside a provider rate-limit cooldown window."""

    def __init__(
        self,
        *,
        purpose: str,
        model_ref: str = "",
        cooldown_remaining_seconds: float,
    ) -> None:
        super().__init__(
            "rate_limit_cooldown",
            (
                f"review step `{purpose}` was rejected while model "
                f"{model_ref or 'unresolved'} cools down a provider 429 for "
                f"another {cooldown_remaining_seconds:g}s"
            ),
            retryable=True,
        )
        self.purpose = str(purpose)
        self.model_ref = str(model_ref)
        self.cooldown_remaining_seconds = float(cooldown_remaining_seconds)


def is_recoverable_review_llm_gate_error(error: Exception) -> bool:
    """True for gate rejections the retry/requeue path can absorb."""

    return isinstance(
        error, (ReviewLLMGateTimeoutError, ReviewLLMRateLimitCooldownError)
    )


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def llm_gate_max_concurrent() -> int:
    """Process-wide LLM call ceiling (``VIBELUTION_LLM_MAX_CONCURRENT``)."""

    return int(
        _env_float(
            _LLM_GATE_MAX_CONCURRENT_ENV,
            _LLM_GATE_MAX_CONCURRENT_DEFAULT,
            minimum=1.0,
            maximum=float(_LLM_GATE_MAX_CONCURRENT_LIMIT),
        )
    )


def llm_gate_acquire_timeout_seconds() -> float:
    """Max wait for one global slot before failing fast."""

    return _env_float(
        _LLM_GATE_ACQUIRE_TIMEOUT_ENV,
        _LLM_GATE_ACQUIRE_TIMEOUT_DEFAULT,
        minimum=0.05,
        maximum=600.0,
    )


def llm_rate_limit_cooldown_seconds() -> float:
    """Model-level 429 cooldown window."""

    return _env_float(
        _LLM_RATE_LIMIT_COOLDOWN_ENV,
        _LLM_RATE_LIMIT_COOLDOWN_DEFAULT,
        minimum=0.0,
        maximum=600.0,
    )


def _llm_gate() -> threading.BoundedSemaphore:
    global _gate_semaphore, _gate_semaphore_size
    size = llm_gate_max_concurrent()
    with _gate_state_lock:
        if _gate_semaphore is None or _gate_semaphore_size != size:
            # Rebuild only when the configured size changed (env edits are a
            # test/ops action, never a mid-flight product event, so holders
            # of the previous semaphore have released by then).
            _gate_semaphore = threading.BoundedSemaphore(size)
            _gate_semaphore_size = size
        return _gate_semaphore


def reset_llm_gate_for_tests(*, max_concurrent: int | None = None) -> None:
    """Reset the process-wide gate state (tests only)."""

    global _gate_semaphore, _gate_semaphore_size
    with _gate_state_lock:
        if max_concurrent is not None:
            size = max(1, int(max_concurrent))
            _gate_semaphore = threading.BoundedSemaphore(size)
            _gate_semaphore_size = size
        else:
            _gate_semaphore = None
            _gate_semaphore_size = 0
        _rate_limit_cooldown_until.clear()


def _llm_gate_model_key(model_ref: str) -> str:
    return str(model_ref or "").strip().lower()


def _record_model_rate_limit(model_ref: str, *, now_s: float | None = None) -> None:
    key = _llm_gate_model_key(model_ref)
    if not key:
        return
    moment = time.time() if now_s is None else now_s
    deadline = moment + llm_rate_limit_cooldown_seconds()
    with _gate_state_lock:
        _rate_limit_cooldown_until[key] = max(
            deadline, _rate_limit_cooldown_until.get(key, 0.0)
        )


def _maybe_record_provider_rate_limit(error: Exception, *, model_ref: str) -> None:
    """Track a real provider 429 (transport category ``rate_limit_error``).

    The gate's own fast-fail exceptions carry different categories, so a
    storm of gate rejections can never extend the cooldown window.
    """

    if isinstance(error, LLMError) and str(error.category) == "rate_limit_error":
        _record_model_rate_limit(model_ref)


def _raise_if_model_cooling_down(*, purpose: str, model_ref: str) -> None:
    key = _llm_gate_model_key(model_ref)
    if not key:
        return
    with _gate_state_lock:
        deadline = _rate_limit_cooldown_until.get(key, 0.0)
    remaining = deadline - time.time()
    if remaining > 0:
        raise ReviewLLMRateLimitCooldownError(
            purpose=purpose,
            model_ref=model_ref,
            cooldown_remaining_seconds=remaining,
        )


@contextlib.contextmanager
def _llm_gate_slot(*, purpose: str, model_ref: str):
    """Hold one global LLM slot around a real provider call.

    Fast-fails before queueing when the model is in a 429 cooldown, then
    bounds the wait for a slot by the configured acquire timeout.  Release is
    guaranteed on every path (success, provider error, cancellation) via
    try/finally, so an exception can never leak a slot.
    """

    _raise_if_model_cooling_down(purpose=purpose, model_ref=model_ref)
    semaphore = _llm_gate()
    wait_seconds = llm_gate_acquire_timeout_seconds()
    if not semaphore.acquire(timeout=wait_seconds):
        raise ReviewLLMGateTimeoutError(
            purpose=purpose,
            model_ref=model_ref,
            wait_seconds=wait_seconds,
        )
    try:
        # Re-check after the wait: a sibling call may have observed a 429 for
        # this model while this call was queued on the gate.
        _raise_if_model_cooling_down(purpose=purpose, model_ref=model_ref)
        yield
    finally:
        semaphore.release()


def _invoke_llm_with_timeout(
    invoke: Callable[[], Any],
    *,
    purpose: str,
    timeout_seconds: float,
    deadline_at_ms: int | None = None,
    model_ref: str = "",
) -> Any:
    """Run one review call through the existing abortable provider transport."""

    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        current_challenge_task_deadline_at_ms,
    )

    now_ms = int(time.time() * 1000)
    candidates = [now_ms + max(1, int(timeout_seconds * 1000))]
    for value in (deadline_at_ms, current_challenge_task_deadline_at_ms()):
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            candidates.append(value)
    effective_deadline_at_ms = min(candidates)

    def interrupt_checker() -> str:
        return (
            "challenge_review_deadline_exceeded"
            if int(time.time() * 1000) >= effective_deadline_at_ms
            else ""
        )

    if interrupt_checker():
        raise ReviewLLMTimeoutError(
            purpose=purpose,
            timeout_seconds=max(0.001, (effective_deadline_at_ms - now_ms) / 1000),
        )
    try:
        with llm_cancel_context(interrupt_checker, enable_chat_provider_abort=True):
            # Global gate (B5): the in-flight count covers the real provider
            # request only, so queueing on the gate does not consume the
            # per-call budget; the absolute challenge deadline above still
            # fences the whole call, including the gate wait.
            with _llm_gate_slot(purpose=purpose, model_ref=model_ref):
                value = invoke()
    except LLMError as exc:
        if exc.category == "cancelled" and interrupt_checker():
            raise ReviewLLMTimeoutError(
                purpose=purpose,
                timeout_seconds=timeout_seconds,
            ) from exc
        raise
    if interrupt_checker():
        raise ReviewLLMTimeoutError(
            purpose=purpose,
            timeout_seconds=timeout_seconds,
        )
    return value


def _record_review_llm_unavailable(reason: str, *, detail: str = "") -> None:
    """Explain one DEV fixture fallback of the review LLM resolution.

    The fail-open fallback at the fixture boundary is intentional (DEV/CI
    stays deterministic without a configured model), but it must never be
    silent: every unreachable branch emits one bounded warning log plus one
    quiet scene event naming the missing configuration.  Details are
    truncated and never include credentials or prompts.
    """

    safe_detail = str(detail or "").strip().replace("\n", " ")[:200]
    logger.warning(
        "review LLM unavailable; keeping deterministic DEV fixtures (%s)%s",
        reason,
        f": {safe_detail}" if safe_detail else "",
    )
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow",
            "review_llm",
            "review_llm.resolve.unavailable",
            message="Review LLM unavailable; deterministic DEV fixtures stay in charge.",
            level="warning",
            outcome="fallback_dev_fixture",
            fields={
                "reason": str(reason),
                **({"detail": safe_detail} if safe_detail else {}),
            },
            lifecycle=False,
        )
    except Exception:  # noqa: BLE001 - diagnostics must never fail resolution
        return


def resolve_review_llm() -> dict[str, Any] | None:
    """Resolve the Challenge Cup team LLM for review calls.

    Review and digest generation are executed by the Team's evaluator Agent.
    The Team owns only ``role -> agentId`` membership; model selection comes
    from that AgentInstance's ``llmBindings``. The selected Agent model is
    projected onto an isolated runtime config; no operator config is mutated.

    A provider without usable credentials is treated as unavailable and the
    deterministic DEV fixtures stay in charge.  The fallback itself is
    fail-open at availability level only, but never silent: every branch
    records why via :func:`_record_review_llm_unavailable`.
    """

    try:
        from core.web.services import agent_directory_service, team_service

        team = team_service.get_team_light(CHALLENGE_CUP_RESEARCH_TEAM_ID)
        evaluator_agent_id = next(
            (
                str(member.get("agentId") or "").strip()
                for member in list(team.get("members") or [])
                if isinstance(member, dict)
                and str(member.get("role") or "").strip()
                == "challenge_cup_evaluator"
                and str(member.get("agentId") or "").strip()
            ),
            "",
        )
        evaluator = (
            agent_directory_service.get_agent(
                evaluator_agent_id,
                include_archived=False,
            )
            if evaluator_agent_id
            else None
        )
        model_ref = agent_dialogue_model_id(evaluator)
    except Exception as exc:  # noqa: BLE001 - availability probe must stay fail-open
        _record_review_llm_unavailable(
            "resolve_error",
            detail=f"{type(exc).__name__}: {exc}",
        )
        return None
    if not evaluator:
        _record_review_llm_unavailable(
            "evaluator_agent_missing",
            detail=(
                f"agent={evaluator_agent_id} is missing or archived"
                if evaluator_agent_id
                else "no Challenge Cup team member carries the "
                "challenge_cup_evaluator role"
            ),
        )
        return None
    if not model_ref:
        _record_review_llm_unavailable(
            "evaluator_model_unbound",
            detail=f"agent={evaluator_agent_id} has no dialogue llmBindings.modelId",
        )
        return None
    try:
        runtime_config = config_for_agent_llm_model(
            get_config(),
            model_id=model_ref,
            runtime_profile_id=REVIEW_LLM_PROFILE_ID,
            slot="dialogue",
        )
        client = get_llm_client(
            profile_id=REVIEW_LLM_PROFILE_ID,
            config=runtime_config,
        )
        model_id = str(getattr(getattr(client, "profile", None), "model", "") or "").strip()
        provider = getattr(client, "provider", None)
        api_key = str(getattr(provider, "api_key", "") or "").strip()
        api_key_env = str(getattr(provider, "api_key_env", "") or "").strip()
        requires_api_key = bool(getattr(provider, "requires_api_key", True))
    except Exception as exc:  # noqa: BLE001 - availability probe must stay fail-open
        _record_review_llm_unavailable(
            "client_build_error",
            detail=f"model_ref={model_ref} {type(exc).__name__}: {exc}",
        )
        return None
    if not model_id:
        _record_review_llm_unavailable(
            "model_unresolved",
            detail=f"model_ref={model_ref} resolved to an empty profile model",
        )
        return None
    if requires_api_key and not api_key and not (api_key_env and os.environ.get(api_key_env)):
        _record_review_llm_unavailable(
            "provider_credentials_missing",
            detail=(
                f"provider={getattr(provider, 'provider_id', '') or ''} "
                "requires an api key but none is configured or present in the "
                "environment"
            ),
        )
        return None
    return {
        "client": client,
        "profileId": REVIEW_LLM_PROFILE_ID,
        "modelId": model_id,
        "providerId": str(getattr(provider, "provider_id", "") or "").strip(),
        "agentId": evaluator_agent_id,
        "modelRef": (
            f"{str(getattr(provider, 'provider_id', '') or '').strip()}/{model_id}"
        ),
    }


def _parse_json_object(text: str, *, what: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ContractValidationError(f"{what} did not return valid JSON")
        try:
            payload = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            raise ContractValidationError(f"{what} did not return valid JSON") from None
    if not isinstance(payload, dict):
        raise ContractValidationError(f"{what} must return a JSON object")
    return payload


def _invoke_review_llm(
    llm: Mapping[str, Any],
    *,
    agent_id: str,
    purpose: str,
    system_prompt: str,
    user_payload: Mapping[str, Any],
    session_id: str,
    receipt_context: Mapping[str, Any] | None = None,
    require_provider_receipt: bool = False,
    deadline_at_ms: int | None = None,
    response_mode: str = "json_object",
) -> dict[str, Any] | str | ProviderBoundReviewResult:
    """Run one review model call and return its requested response form."""

    # Gate/cooldown attribution key: provider-qualified modelRef when present,
    # falling back to the bare model id.
    model_gate_ref = str(llm.get("modelRef") or llm.get("modelId") or "")
    user_content = json.dumps(dict(user_payload), ensure_ascii=False)
    messages: list[Any] = [
        build_cacheable_system_message(system_prompt),
        {
            "role": "user",
            "content": user_content,
        },
    ]
    receipt_binding = (
        receipt_context.get("questionStageBinding")
        if isinstance(receipt_context, Mapping)
        and isinstance(receipt_context.get("questionStageBinding"), Mapping)
        else {}
    )
    receipt_session_id = str(receipt_binding.get("sessionId") or "").strip()
    turn_id = str(receipt_binding.get("turnId") or "").strip()
    invocation_id = str(
        receipt_context.get("invocationId") if isinstance(receipt_context, Mapping) else ""
    ).strip()
    if require_provider_receipt and (
        not isinstance(receipt_context, Mapping)
        or not receipt_session_id
        or not turn_id
        or not invocation_id
    ):
        raise ContractValidationError(
            f"review step `{purpose}` requires server-owned provider receipt authority"
        )
    invocation_context = LLMInvocationContext(
        surface=REVIEW_LLM_SURFACE,
        run_kind="team_workflow_review",
        run_id=invocation_id if require_provider_receipt else "",
        session_id=receipt_session_id if require_provider_receipt else session_id,
        agent_id=agent_id,
        llm_slot="dialogue",
        cache_scope=REVIEW_LLM_CACHE_SCOPE,
        cache_partition=f"{session_id}:{purpose}",
        prompt_purpose=purpose,
        conversation_bound=False,
        metadata={
            "purpose": purpose,
            "reviewProfileId": llm["profileId"],
            **(
                {"turnId": turn_id, "invocationId": invocation_id}
                if require_provider_receipt
                else {}
            ),
        },
    )
    if not require_provider_receipt:
        timeout_seconds = review_llm_call_timeout_seconds(
            model_ref=str(llm.get("modelRef") or "")
        )
        # Per-call output clamp (structured review/digest) and optional strict
        # JSON schema (capability-gated); both stay None/unset for purposes
        # that keep the profile default (revision) or text-unstructured paths.
        max_output_tokens = _purpose_max_output_tokens(purpose)
        output_schema = _purpose_output_schema(purpose, llm)
        override_metadata = (
            {MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY: max_output_tokens}
            if max_output_tokens
            else None
        )
        digest_observation = purpose == "meeting_digest"
        started_at = time.monotonic()
        base_fields = {
            "teamId": session_id,
            "meetingRoundId": str(user_payload.get("meetingRoundId") or ""),
            "purpose": purpose,
            "providerId": str(llm.get("providerId") or ""),
            "modelId": str(llm.get("modelId") or ""),
            "modelRef": str(llm.get("modelRef") or ""),
            "profileId": str(llm.get("profileId") or ""),
            "responseMode": response_mode,
            "messageCount": len(messages),
            "inputChars": len(system_prompt) + len(user_content),
            "timeoutMs": max(0, int(timeout_seconds * 1000)),
            "deadlinePresent": bool(deadline_at_ms),
            "deadlineRemainingMs": max(0, int(deadline_at_ms - time.time() * 1000))
            if deadline_at_ms
            else 0,
        }
        if digest_observation:
            _record_meeting_digest_scene_event(
                "meeting_digest.llm.started",
                outcome="started",
                fields=base_fields,
            )
        response: Any = None
        content = ""
        try:
            response = _invoke_llm_with_timeout(
                lambda: invoke_llm(
                    llm["client"],
                    messages,
                    context=invocation_context,
                    metadata=override_metadata,
                    output_schema=output_schema,
                ),
                purpose=purpose,
                timeout_seconds=timeout_seconds,
                deadline_at_ms=deadline_at_ms,
                model_ref=model_gate_ref,
            )
            content = str(getattr(response, "content", "") or "")
            if response_mode == "text":
                normalized = content.strip()
                if normalized.startswith("```markdown") and normalized.endswith("```"):
                    normalized = normalized[len("```markdown") : -len("```")].strip()
                elif normalized.startswith("```") and normalized.endswith("```"):
                    normalized = normalized[len("```") : -len("```")].strip()
                if not normalized:
                    raise ContractValidationError(
                        f"review step `{purpose}` returned empty text"
                    )
                produced: dict[str, Any] | str = normalized
            else:
                if response_mode != "json_object":
                    raise ValueError(
                        f"unsupported review response mode: {response_mode}"
                    )
                produced = _parse_json_object(content, what=f"review step `{purpose}`")
        except Exception as exc:  # noqa: BLE001 - classify, record, and re-raise unchanged
            # A real provider 429 opens the model-level cooldown window so
            # later calls fast-fail instead of piling onto the same throttle.
            _maybe_record_provider_rate_limit(exc, model_ref=model_gate_ref)
            if digest_observation:
                _record_meeting_digest_scene_event(
                    "meeting_digest.llm.failed",
                    outcome="failed",
                    level="error",
                    fields={
                        **base_fields,
                        **_response_usage_fields(response),
                        "latencyMs": max(
                            0, int((time.monotonic() - started_at) * 1000)
                        ),
                        "outputChars": len(content),
                        "errorCategory": _review_llm_error_category(exc),
                        "errorType": type(exc).__name__,
                        "llmErrorCategory": (
                            str(exc.category) if isinstance(exc, LLMError) else ""
                        ),
                    },
                )
            # Offline attribution evidence: the raw (possibly malformed)
            # response survives on disk even though the call itself fails
            # closed.  Best-effort; never changes the raised error.
            _dump_failed_review_response(
                purpose=purpose,
                failure_category=_review_llm_error_category(exc),
                error=exc,
                raw_response=content,
                session_id=session_id,
                meeting_round_id=str(user_payload.get("meetingRoundId") or ""),
                context_id=_user_payload_context_id(user_payload),
                model_ref=str(llm.get("modelRef") or ""),
            )
            raise
        if digest_observation:
            _record_meeting_digest_scene_event(
                "meeting_digest.llm.completed",
                outcome="succeeded",
                fields={
                    **base_fields,
                    **_response_usage_fields(response),
                    "latencyMs": max(0, int((time.monotonic() - started_at) * 1000)),
                    "outputChars": len(content),
                },
            )
        return produced

    if response_mode != "json_object":
        raise ValueError("provider-bound review results require JSON object output")

    def _invoke_bound_outcome() -> Any:
        # The receipt scope is a ContextVar: it must wrap the invocation
        # inside the timeout worker so the nested client call still sees it.
        bound_max_output_tokens = _purpose_max_output_tokens(purpose)
        bound_override_metadata = (
            {MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY: bound_max_output_tokens}
            if bound_max_output_tokens
            else None
        )
        with model_invocation_receipt_context_scope(receipt_context):
            return invoke_llm_outcome(
                llm["client"],
                messages,
                context=invocation_context,
                metadata=bound_override_metadata,
                output_schema=_purpose_output_schema(purpose, llm),
            )

    final_text = ""
    try:
        outcome = _invoke_llm_with_timeout(
            _invoke_bound_outcome,
            purpose=purpose,
            timeout_seconds=review_llm_call_timeout_seconds(
                model_ref=str(llm.get("modelRef") or "")
            ),
            deadline_at_ms=deadline_at_ms,
            model_ref=model_gate_ref,
        )
        final_text = str(getattr(outcome, "final_text", "") or "")
        identity = getattr(outcome, "identity", None)
        if (
            str(getattr(outcome, "kind", "") or "") != "final_answer"
            or str(getattr(identity, "session_id", "") or "") != receipt_session_id
            or str(getattr(identity, "turn_id", "") or "") != turn_id
            or str(getattr(identity, "invocation_id", "") or "") != invocation_id
        ):
            raise ContractValidationError(
                f"review step `{purpose}` did not return the bound final provider outcome"
            )
        raw_receipt = getattr(outcome, "model_invocation_receipt", None)
        if not isinstance(raw_receipt, Mapping) or not raw_receipt:
            raise ContractValidationError(
                f"review step `{purpose}` completed without a provider receipt"
            )
        payload = _parse_json_object(
            final_text,
            what=f"review step `{purpose}`",
        )
    except Exception as exc:  # noqa: BLE001 - dump raw evidence, re-raise unchanged
        # A real provider 429 opens the model-level cooldown window (same
        # contract as the non-receipt branch above).
        _maybe_record_provider_rate_limit(exc, model_ref=model_gate_ref)
        _dump_failed_review_response(
            purpose=purpose,
            failure_category=_review_llm_error_category(exc),
            error=exc,
            raw_response=final_text,
            session_id=receipt_session_id,
            context_id=_user_payload_context_id(user_payload),
            run_id=invocation_id,
            model_ref=str(llm.get("modelRef") or ""),
        )
        raise
    return ProviderBoundReviewResult(
        payload=payload,
        model_invocation_receipt=dict(raw_receipt),
    )


# ---------------------------------------------------------------------------
# Coordinator digest drafter
# ---------------------------------------------------------------------------


def _meeting_transcript(
    source_messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    transcript: list[dict[str, Any]] = []
    for message in source_messages:
        if str(message.get("status") or "").strip().lower() != "completed":
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        speaker = (
            str(message.get("speakerTitle") or "").strip()
            or str(message.get("participantId") or "").strip()
            or "participant"
        )
        transcript.append(
            {
                "speaker": speaker,
                "content": content,
            }
        )
        if len(transcript) >= _MAX_MESSAGES:
            break
    return transcript


_DIGEST_SYSTEM_PROMPT = """你是科研团队的 Coordinator，负责把团队会议发言整理为人类可审阅的会议纪要文档。

要求：
- 只依据给出的会议发言，不得编造发言人或结论。
- 第一行必须是 `# ` 开头的会议标题。
- 必须包含 `## 会议结论`，用一到三段中文概括本次会议形成的判断。
- 其余二级章节由你根据实际会议内容自行选择；不要为了填固定栏目重复同一信息。
- 重要结论、取舍和未解决问题应保留发言中的限定条件，不把提议写成已经达成的决定。
- `DISAGREE:`、`RISK:`、`ACTION:`、`CANDIDATE:` 和 `EVIDENCE_REQUEST:` 属于系统独立保存的协议事实；你可以在自然语言中解释其意义，但不要承担协议字段复制或重组职责。
- 输出只包含最终 Markdown 文档，不要输出 JSON、代码围栏、前言或解释。
"""


def _summary_from_digest_markdown(markdown: str) -> str:
    """Project the first conclusion paragraph into the legacy summary field."""

    lines = [line.strip() for line in str(markdown or "").splitlines()]
    first_content = next((line for line in lines if line), "")
    if not first_content.startswith("# "):
        raise ContractValidationError("meeting digest markdown requires an H1 title")
    conclusion_index = next(
        (index for index, line in enumerate(lines) if line == "## 会议结论"),
        -1,
    )
    if conclusion_index < 0:
        raise ContractValidationError(
            "meeting digest markdown requires a `## 会议结论` section"
        )
    candidates = lines[conclusion_index + 1 :]
    paragraph: list[str] = []
    for line in candidates:
        if line.startswith("#"):
            if paragraph:
                break
            continue
        if not line:
            if paragraph:
                break
            continue
        paragraph.append(line.removeprefix("- ").strip())
    summary = " ".join(item for item in paragraph if item).strip()
    if not summary:
        raise ContractValidationError("meeting digest markdown requires narrative content")
    return summary


def _digest_markdown_contract_fields(markdown: str) -> dict[str, Any]:
    lines = [line.strip() for line in str(markdown or "").splitlines()]
    first_content = next((line for line in lines if line), "")
    return {
        "hasH1": first_content.startswith("# "),
        "hasConclusionSection": "## 会议结论" in lines,
        "sectionCount": sum(1 for line in lines if line.startswith("## ")),
        "documentChars": len(str(markdown or "")),
    }


def build_meeting_digest_drafter(llm: Mapping[str, Any] | None = None):
    """Return the real-LLM Coordinator digest drafter, or ``None`` if unavailable."""

    resolved = dict(llm) if isinstance(llm, Mapping) and llm else resolve_review_llm()
    if not resolved:
        return None

    def drafter(
        meeting_round: dict[str, Any], source_messages: list[dict[str, Any]]
    ) -> Mapping[str, Any]:
        from core.web.services.team_workflow import meeting_rounds

        meeting_type = str(meeting_round.get("meetingType") or "").strip()
        transcript = _meeting_transcript(source_messages)
        if not transcript:
            raise ContractValidationError(
                "digest drafter requires completed source messages"
            )
        produced = _invoke_review_llm(
            resolved,
            agent_id=str(resolved.get("agentId") or "challenge_cup_evaluator"),
            purpose="meeting_digest",
            system_prompt=_DIGEST_SYSTEM_PROMPT,
            user_payload={
                "meetingType": meeting_type,
                "meetingRoundId": str(meeting_round.get("meetingRoundId") or ""),
                "agenda": list(meeting_round.get("agenda") or []),
                "participants": list(meeting_round.get("participants") or []),
                "messages": transcript,
            },
            session_id=str(meeting_round.get("teamId") or "") or "team",
            deadline_at_ms=int(meeting_round.get("challengeDeadlineAtMs") or 0)
            or None,
            response_mode="text",
        )
        if not isinstance(produced, str):
            raise ContractValidationError("digest drafter requires Markdown text")
        contract_fields = {
            "teamId": str(meeting_round.get("teamId") or ""),
            "meetingRoundId": str(meeting_round.get("meetingRoundId") or ""),
            **_digest_markdown_contract_fields(produced),
        }
        try:
            summary = _summary_from_digest_markdown(produced)
        except ContractValidationError as exc:
            _record_meeting_digest_scene_event(
                "meeting_digest.contract.validated",
                outcome="failed",
                level="error",
                fields={
                    **contract_fields,
                    "errorCategory": "contract_validation",
                    "errorType": type(exc).__name__,
                },
            )
            raise
        _record_meeting_digest_scene_event(
            "meeting_digest.contract.validated",
            outcome="succeeded",
            fields=contract_fields,
        )
        # Server-owned fields: source refs are computed from the bound
        # messages, never delegated to the model.
        source_refs = [
            meeting_rounds.message_source_ref(message)
            for message in source_messages
            if str(message.get("status") or "").strip().lower() == "completed"
            and not meeting_rounds.is_pass_message(message)
        ]
        agenda = [
            str(item).strip()
            for item in list(meeting_round.get("agenda") or [])
            if str(item).strip()
        ]
        return {
            "summary": summary,
            "agendaSummary": "；".join(agenda),
            "discussionTopics": agenda,
            "documentMarkdown": produced,
            "documentTemplateId": "open_sections_v1",
            "sourceMessageRefs": source_refs,
        }

    return drafter


# ---------------------------------------------------------------------------
# Hypothesis review runners
# ---------------------------------------------------------------------------


def _rubric_block() -> str:
    return json.dumps(canonical_hypothesis_score_rubric(), ensure_ascii=False)


_REFLECTION_SYSTEM_PROMPT = f"""你是科研假说评审员（独立评分步骤）。按官方五维 rubric 对单个假说候选独立评分。

Rubric（分数 0.0-1.0，两位小数，按分档描述对号入座）：
{_rubric_block()}

要求：
- scores 必须恰好包含五个维度：{list(HYPOTHESIS_SCORE_DIMENSIONS)}。
- claim 沿用候选自己的 claim 原文；rationale 用中文说明打分依据；differenceFromAlternatives 说明相对其他候选的差异。
- lineageRefs 沿用候选携带的来源引用，没有就给空数组，不得编造。
- dimensionReviews 是与 5+2 完全独立的结果包审计七维，每个维度恰好一行，维度只能为 {list(REQUIRED_REVIEW_DIMENSIONS)}。不得把 5+2 评分字段映射、改名或复制成审计七维。
- 每行 {{"hypothesis_id","dimension","rating","rationale","reviewer","evidence_refs"}}；rating 只能取 {list(REVIEW_DIMENSION_RATINGS)}；rationale 必须针对该审计维度给出非空正文；evidence_refs 只能从输入 refsWhitelist 中选择，白名单为空则给空数组。文献对照论文（literatureContrast.papers）没有 canonical ref，禁止写入 evidence_refs。
- novelty 维度必须有文献对照支撑：输入 literatureContrast.papers 是评审前检索到的开放文献（title/year/venue/abstract）。novelty rationale 必须逐条对照检索文献：哪些论文已覆盖候选的哪些部分（引用具体 title），真正的增量（delta）是什么；若检索结果中未发现显著重叠，必须明确写「检索结果中未发现显著重叠工作」；禁止无文献证据的空泛「novelty 不足/充足」。语气从严：只有当增量足以构成新贡献时 novelty 才算充足。
- 若 literatureContrast.degraded=true 或缺失，必须写明「未能获取文献对照，基于评审自身知识判断」，并说明结论存在「基于可检索文献（open-access 盲区）」的局限；此时 noveltyContrast.basis 必须为 "degraded"。
- 输出可选顶层 noveltyContrast 对象 {{"overlapPapers": [str], "deltaStatement": str, "basis": "retrieved" | "degraded"}}：overlapPapers 列出确实覆盖候选内容的具体论文 title（无重叠则为空数组），deltaStatement 一句话说明相对已检索文献的真正增量，basis 按实际检索情况取值。确实无法给出时可省略该对象，省略不影响其余输出的有效性。
- reviewedBy 固定为 "llm"，status 固定为 "reviewed"。
- 若输入 requireCoreHypothesisCoherence=true，必须在同一次 Reflection 输出 coreHypothesisCoherence，不得新增模型调用。它必须恰好按顺序覆盖 {list(CORE_HYPOTHESIS_COHERENCE_CHECK_IDS)}；每项包含 checkId、passed、非空 rationale、claimRefs、evidenceRefs。evidenceRefs 只能来自 refsWhitelist；五项分别审查因果链、prediction 是否由 mechanism 推导、falsifier 是否命中机制、population/boundary 是否冲突、候选边界是否与替代方案可区分。
- 严格输出单个 JSON 对象。

输出 JSON 结构：
{{"claim": str, "rationale": str, "differenceFromAlternatives": str, "lineageRefs": [str], "scores": {{{", ".join(f'"{d}": float' for d in HYPOTHESIS_SCORE_DIMENSIONS)}}}, "reviewedBy": "llm", "status": "reviewed", "dimensionReviews": [dict], "noveltyContrast": {{"overlapPapers": [str], "deltaStatement": str, "basis": "retrieved" | "degraded"}}, "coreHypothesisCoherence": {{"candidateId": str, "reviewer": str, "checks": [{{"checkId": str, "passed": bool, "rationale": str, "claimRefs": [str], "evidenceRefs": [str]}}]}}}}
"""

_PAIRWISE_SYSTEM_PROMPT = """你是科研假说评审员（两两比较步骤）。对给出的左右两个候选做一次比较。

要求：
- outcome 只能是 "left_wins"、"right_wins" 或 "tie"；只依据候选内容与评审上下文判断。
- justification 用中文说明胜负依据，必须非空。
- 严格输出单个 JSON 对象。

输出 JSON 结构：
{"outcome": "left_wins" | "right_wins" | "tie", "justification": str}
"""

_PARETO_SYSTEM_PROMPT = """你是科研假说评审员（Pareto 分类步骤）。基于五维评分把所有候选划分为 Pareto 前沿与被支配两类。

要求：
- paretoFrontCandidateIds 与 dominatedCandidateIds 的并集必须恰好覆盖全部候选 id，且两集合不相交。
- 前沿集合不能为空；notes 用中文说明划分依据。
- 严格输出单个 JSON 对象。

输出 JSON 结构：
{"paretoFrontCandidateIds": [str], "dominatedCandidateIds": [str], "notes": str}
"""

_METAREVIEW_SYSTEM_PROMPT = """你是科研团队 Coordinator（MetaReview 步骤）。综合独立评分、两两比较与 Pareto 分类，给出最终推荐。

要求：
- recommendationCandidateId 必须从给出的候选 id 中选择。
- rationale 用中文说明推荐依据；riskNotes 汇总未解决风险。
- accepted 表示本轮评审结论是否可接受（推荐候选质量足以进入下一轮修订或第一阶段研究计划设计）；不得据此声称实验已设计或执行。
- 严格输出单个 JSON 对象。

输出 JSON 结构：
{"recommendationCandidateId": str, "rationale": str, "riskNotes": str, "accepted": bool}
"""

_REVISION_SYSTEM_PROMPT = """你是科研假说修订员。根据 MetaReview 的明确反馈，真正改写被推荐的 R1 假说，产出 R2；你不是复述评分或推荐理由。

要求：
- revisedCandidate.candidateId 必须与 parentCandidate.candidateId 完全一致，但 claim 必须是实质修订后的新文本，不能复制原文。
- 保留并完善可检验预测、机制靶向 falsifier、差异说明与 axisProfile；lineageRefs 只能从 refsWhitelist 选择，不得编造引用。
- changes 必须逐条说明实际改动；unresolvedIssues 必须逐条保留仍未解决的边界或风险，两者都不能为空。
- 不得把 MetaReview rationale、riskNotes、分数或收据本身冒充 revisedCandidate。
- 严格输出单个 JSON 对象。

输出 JSON 结构：
{"revisedCandidate": {"candidateId": str, "claim": str, "rationale": str, "differenceFromAlternatives": str, "lineageRefs": [str], "testablePrediction": str, "falsifier": str, "axisProfile": dict}, "changes": [str], "unresolvedIssues": [str]}
"""


def _validated_dimension_review_rows(
    rows: Any,
    *,
    candidate_id: str,
    reviewer: str,
    refs_whitelist: Sequence[str],
) -> list[dict[str, Any]]:
    """Bind one real reflection output to the independent audit authority."""

    if not isinstance(rows, list):
        raise ContractValidationError(
            "reflection dimensionReviews must be a list covering all audit dimensions"
        )
    allowed_dimensions = set(REQUIRED_REVIEW_DIMENSIONS)
    allowed_ratings = set(REVIEW_DIMENSION_RATINGS)
    allowed_refs = {str(item) for item in refs_whitelist if str(item or "").strip()}
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ContractValidationError("reflection dimensionReviews rows must be objects")
        dimension = str(raw.get("dimension") or "").strip()
        if dimension not in allowed_dimensions or dimension in seen:
            raise ContractValidationError(
                "reflection dimensionReviews must cover exactly the seven audit dimensions"
            )
        rating = str(raw.get("rating") or "").strip().lower()
        rationale = str(raw.get("rationale") or "").strip()
        evidence_refs = raw.get("evidence_refs", raw.get("evidenceRefs", []))
        if rating not in allowed_ratings or not rationale:
            raise ContractValidationError(
                f"reflection audit dimension {dimension} requires a valid rating and rationale"
            )
        if not isinstance(evidence_refs, list):
            raise ContractValidationError(
                f"reflection audit dimension {dimension} evidence_refs must be a list"
            )
        normalized_refs = [
            str(item).strip() for item in evidence_refs if str(item or "").strip()
        ]
        if any(ref not in allowed_refs for ref in normalized_refs):
            raise ContractValidationError(
                f"reflection audit dimension {dimension} contains an unbound evidence ref"
            )
        seen.add(dimension)
        normalized.append(
            {
                "hypothesis_id": candidate_id,
                "dimension": dimension,
                "rating": rating,
                "rationale": rationale,
                "reviewer": reviewer,
                "evidence_refs": list(dict.fromkeys(normalized_refs)),
            }
        )
    if seen != allowed_dimensions:
        raise ContractValidationError(
            "reflection dimensionReviews must cover exactly the seven audit dimensions"
        )
    return normalized


def _candidate_refs(candidate: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("lineageRefs", "evidenceRefs", "refs"):
        value = candidate.get(key)
        if isinstance(value, (list, tuple)):
            refs.extend(str(item) for item in value if str(item or "").strip())
    return refs


def _context_digest_refs(context: Mapping[str, Any]) -> list[str]:
    digest = context.get("digest") if isinstance(context.get("digest"), Mapping) else {}
    refs: list[str] = []
    for key in ("sourceMessageRefs", "discussionItemRefs"):
        value = digest.get(key) or context.get(key)
        if isinstance(value, (list, tuple)):
            refs.extend(str(item) for item in value if str(item or "").strip())
    return refs


def _literature_contrast_payload(context: Mapping[str, Any]) -> dict[str, Any]:
    """Project the executor-injected literature contrast onto the payload shape.

    Absent or malformed input degrades to an empty, ``degraded`` contrast so
    the reflection payload contract stays stable and the reviewer always knows
    whether retrieved literature is available.
    """

    raw = context.get("literatureContrast")
    if isinstance(raw, Mapping) and raw:
        papers = [
            dict(item)
            for item in list(raw.get("papers") or [])
            if isinstance(item, Mapping)
        ]
        meta = raw.get("retrievalMeta")
        return {
            "papers": papers,
            "degraded": bool(raw.get("degraded")) or not papers,
            "retrievalMeta": dict(meta) if isinstance(meta, Mapping) else {},
        }
    return {"papers": [], "degraded": True, "retrievalMeta": {}}


def _normalized_novelty_contrast(
    raw: Any,
    *,
    literature: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Leniently normalize the optional ``noveltyContrast`` reflection output.

    Malformed or missing output returns ``None`` and never fails the review.
    ``basis`` is forced to match retrieval reality: a claimed ``retrieved``
    basis without papers cannot exist.
    """

    if not isinstance(raw, Mapping):
        return None
    overlap: list[str] = []
    for item in list(raw.get("overlapPapers") or []):
        text = str(item or "").strip()[:260]
        if text:
            overlap.append(text)
        if len(overlap) >= 10:
            break
    delta = str(raw.get("deltaStatement") or "").strip()[:2000]
    basis = str(raw.get("basis") or "").strip().lower()
    if basis not in {"retrieved", "degraded"}:
        basis = "retrieved"
    if not list(literature.get("papers") or []):
        basis = "degraded"
    return {
        "overlapPapers": overlap,
        "deltaStatement": delta,
        "basis": basis,
    }


def build_hypothesis_review_runners(
    llm: Mapping[str, Any] | None = None,
    *,
    require_provider_receipts: bool = False,
) -> dict[str, Any] | None:
    """Return the real-LLM review and revision runners, or ``None``."""

    resolved = dict(llm) if isinstance(llm, Mapping) and llm else resolve_review_llm()
    if not resolved:
        return None
    session_id = "team"

    def _context_session(context: Mapping[str, Any]) -> str:
        return str(context.get("teamId") or "") or session_id

    def _receipt_context(
        context: Mapping[str, Any],
        *,
        review_step: str,
        identity_parts: Sequence[Any],
    ) -> Mapping[str, Any] | None:
        if not require_provider_receipts:
            return None
        from core.web.services.team_workflow.research_runtime.meeting_receipt_authority import (
            MeetingReceiptAuthorityError,
            build_review_step_receipt_context,
        )

        try:
            receipt_context = build_review_step_receipt_context(
                context,
                review_step=review_step,
                identity_parts=identity_parts,
                session_id=_context_session(context),
                expected_model_route={
                    "modelRef": resolved.get("modelRef"),
                    "providerId": resolved.get("providerId"),
                    "modelId": resolved.get("modelId"),
                },
            )
        except MeetingReceiptAuthorityError as exc:
            raise ContractValidationError(str(exc)) from exc
        if receipt_context is None:
            raise ContractValidationError(
                f"formal {review_step} runner requires server-owned receipt authority"
            )
        return receipt_context

    def reflection_runner(candidate: dict[str, Any], context: dict[str, Any]):
        refs_whitelist = [
            * _candidate_refs(candidate),
            * _context_digest_refs(context),
        ]
        produced = _invoke_review_llm(
            resolved,
            agent_id=str(resolved.get("agentId") or "challenge_cup_evaluator"),
            purpose="hypothesis_reflection",
            system_prompt=_REFLECTION_SYSTEM_PROMPT,
            user_payload={
                "candidate": dict(candidate),
                "context": {
                    "contextId": str(context.get("contextId") or ""),
                    "question": str(context.get("question") or ""),
                },
                "requireCoreHypothesisCoherence": bool(
                    context.get("requireCoreHypothesisCoherence")
                )
                or (
                    str(candidate.get("candidateAuthority") or "").strip().lower()
                    == "formal_grounded_candidate"
                ),
                "refsWhitelist": refs_whitelist,
                "scoreDimensions": list(HYPOTHESIS_SCORE_DIMENSIONS),
                "reviewDimensions": list(REQUIRED_REVIEW_DIMENSIONS),
                "allowedRatings": list(REVIEW_DIMENSION_RATINGS),
                "literatureContrast": _literature_contrast_payload(context),
            },
            session_id=_context_session(context),
            receipt_context=_receipt_context(
                context,
                review_step="reflection",
                identity_parts=(str(candidate.get("candidateId") or ""),),
            ),
            require_provider_receipt=require_provider_receipts,
            deadline_at_ms=int(context.get("challengeDeadlineAtMs") or 0) or None,
        )
        provider_receipt = None
        if isinstance(produced, ProviderBoundReviewResult):
            provider_receipt = produced.model_invocation_receipt
            result = dict(produced.payload)
        else:
            result = dict(produced)
        # Optional structured novelty conclusion: lenient normalization, and a
        # malformed or missing object never fails the review.
        novelty = _normalized_novelty_contrast(
            result.pop("noveltyContrast", None),
            literature=_literature_contrast_payload(context),
        )
        if novelty is not None:
            result["noveltyContrast"] = novelty
        result["reviewedBy"] = f"llm:{resolved['modelId']}"
        result["dimensionReviews"] = _validated_dimension_review_rows(
            result.get("dimensionReviews"),
            candidate_id=str(candidate.get("candidateId") or ""),
            reviewer=result["reviewedBy"],
            refs_whitelist=refs_whitelist,
        )
        require_coherence = bool(context.get("requireCoreHypothesisCoherence")) or (
            str(candidate.get("candidateAuthority") or "").strip().lower()
            == "formal_grounded_candidate"
        )
        if require_coherence:
            raw_coherence = result.get("coreHypothesisCoherence")
            if not isinstance(raw_coherence, Mapping):
                raise ContractValidationError(
                    "coherence_failure: reflection output is missing coreHypothesisCoherence"
                )
            coherence = CoreHypothesisCoherenceResult.from_review_payload(
                raw_coherence,
                candidate_id=str(candidate.get("candidateId") or ""),
                reviewer=result["reviewedBy"],
            )
            allowed_refs = set(refs_whitelist)
            if any(
                ref not in allowed_refs
                for check in coherence.checks
                for ref in check.evidenceRefs
            ):
                raise ContractValidationError(
                    "coherence_failure: core coherence contains an unbound evidence ref"
                )
            # The executor adds the provider receipt and canonical artifact
            # hash after it verifies the provider-bound result.
            result["coreHypothesisCoherence"] = {
                "candidateId": coherence.candidateId,
                "reviewer": coherence.reviewer,
                "checks": [item.to_dict() for item in coherence.checks],
            }
        if provider_receipt is not None:
            return ProviderBoundReviewResult(result, provider_receipt)
        return result

    def pairwise_runner(
        left: dict[str, Any], right: dict[str, Any], context: dict[str, Any]
    ):
        return _invoke_review_llm(
            resolved,
            agent_id=str(resolved.get("agentId") or "challenge_cup_evaluator"),
            purpose="hypothesis_pairwise",
            system_prompt=_PAIRWISE_SYSTEM_PROMPT,
            user_payload={
                "left": dict(left),
                "right": dict(right),
                "context": {
                    "contextId": str(context.get("contextId") or ""),
                    "question": str(context.get("question") or ""),
                },
            },
            session_id=_context_session(context),
            receipt_context=_receipt_context(
                context,
                review_step="pairwise",
                identity_parts=(
                    str(left.get("candidateId") or ""),
                    str(right.get("candidateId") or ""),
                ),
            ),
            require_provider_receipt=require_provider_receipts,
            deadline_at_ms=int(context.get("challengeDeadlineAtMs") or 0) or None,
        )

    def pareto_runner(scores_by_candidate: dict[str, dict[str, float]], context: dict[str, Any]):
        return _invoke_review_llm(
            resolved,
            agent_id=str(resolved.get("agentId") or "challenge_cup_evaluator"),
            purpose="hypothesis_pareto",
            system_prompt=_PARETO_SYSTEM_PROMPT,
            user_payload={
                "scoresByCandidate": dict(scores_by_candidate),
                "context": {
                    "contextId": str(context.get("contextId") or ""),
                    "question": str(context.get("question") or ""),
                },
            },
            session_id=_context_session(context),
            receipt_context=_receipt_context(
                context,
                review_step="pareto",
                identity_parts=tuple(sorted(scores_by_candidate)),
            ),
            require_provider_receipt=require_provider_receipts,
            deadline_at_ms=int(context.get("challengeDeadlineAtMs") or 0) or None,
        )

    def metareview_runner(
        context: dict[str, Any],
        candidates: list[dict[str, Any]],
        pairwise: list[dict[str, Any]],
        pareto: dict[str, Any],
    ):
        produced = _invoke_review_llm(
            resolved,
            agent_id=str(resolved.get("agentId") or "challenge_cup_evaluator"),
            purpose="hypothesis_metareview",
            system_prompt=_METAREVIEW_SYSTEM_PROMPT,
            user_payload={
                "context": {
                    "contextId": str(context.get("contextId") or ""),
                    "question": str(context.get("question") or ""),
                },
                "candidates": [dict(item) for item in candidates],
                "pairwiseComparisons": [dict(item) for item in pairwise],
                "pareto": dict(pareto),
            },
            session_id=_context_session(context),
            receipt_context=_receipt_context(
                context,
                review_step="metareview",
                identity_parts=tuple(
                    sorted(str(item.get("candidateId") or "") for item in candidates)
                ),
            ),
            require_provider_receipt=require_provider_receipts,
            deadline_at_ms=int(context.get("challengeDeadlineAtMs") or 0) or None,
        )
        provider_receipt = None
        if isinstance(produced, ProviderBoundReviewResult):
            provider_receipt = produced.model_invocation_receipt
            result = dict(produced.payload)
        else:
            result = dict(produced)
        result["reviewerAgentId"] = f"llm:{resolved['modelId']}"
        if provider_receipt is not None:
            return ProviderBoundReviewResult(result, provider_receipt)
        return result

    def revision_runner(
        context: dict[str, Any],
        parent_candidate: dict[str, Any],
        candidates: list[dict[str, Any]],
        meta_review: dict[str, Any],
    ):
        refs_whitelist = list(
            dict.fromkeys(
                [
                    *_candidate_refs(parent_candidate),
                    *_context_digest_refs(context),
                ]
            )
        )
        produced = _invoke_review_llm(
            resolved,
            agent_id=str(resolved.get("agentId") or "challenge_cup_evaluator"),
            purpose="hypothesis_revision",
            system_prompt=_REVISION_SYSTEM_PROMPT,
            user_payload={
                "context": {
                    "contextId": str(context.get("contextId") or ""),
                    "question": str(context.get("question") or ""),
                },
                "parentCandidate": dict(parent_candidate),
                "candidateSet": [dict(item) for item in candidates],
                "metaReview": dict(meta_review),
                "refsWhitelist": refs_whitelist,
            },
            session_id=_context_session(context),
            receipt_context=_receipt_context(
                context,
                review_step="revision",
                identity_parts=(
                    str(parent_candidate.get("candidateId") or ""),
                    str(meta_review.get("metaReviewId") or ""),
                ),
            ),
            require_provider_receipt=require_provider_receipts,
            deadline_at_ms=int(context.get("challengeDeadlineAtMs") or 0) or None,
        )
        provider_receipt = None
        if isinstance(produced, ProviderBoundReviewResult):
            provider_receipt = produced.model_invocation_receipt
            result = dict(produced.payload)
        else:
            result = dict(produced)
        revised = result.get("revisedCandidate")
        if not isinstance(revised, Mapping):
            raise ContractValidationError(
                "hypothesis revision output is missing revisedCandidate"
            )
        revised_refs = [
            str(item).strip()
            for item in list(revised.get("lineageRefs") or [])
            if str(item or "").strip()
        ]
        if any(ref not in set(refs_whitelist) for ref in revised_refs):
            raise ContractValidationError(
                "hypothesis revision contains an unbound lineage ref"
            )
        if provider_receipt is not None:
            return ProviderBoundReviewResult(result, provider_receipt)
        return result

    return {
        "reflection_runner": reflection_runner,
        "pairwise_runner": pairwise_runner,
        "pareto_runner": pareto_runner,
        "metareview_runner": metareview_runner,
        "revision_runner": revision_runner,
    }
