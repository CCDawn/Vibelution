"""DashScope explicit prompt-cache keepalive probe for active meetings.

DashScope explicit ``cache_control`` entries live ~5 minutes and every hit
re-arms the TTL.  Challenge review/generation rounds are typically spaced
6-15 minutes apart, so the marked shared prefixes (the hypothesis review
rubric prompts, the digest prompt) reliably expire between rounds and every
next-round call pays the full uncached input price.

After a meeting round closes, the meeting discussion driver schedules ONE
delayed minimal probe (default ~4 minutes) through this module.  The probe
re-sends a ``cache_control``-marked shared prefix with a tiny output budget
via the normal review LLM channel, so the provider re-arms the prefix TTL for
the next round.

Hard guards (keepalive is a pure optimization and must never affect the main
chain or its accounting):

- ``VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS=0`` disables the feature;
- at most one scheduled probe per (meeting, closed round) per process;
- at fire time the meeting round must still be open (``status != "closed"``),
  so meetings that already closed never emit a probe;
- global probe concurrency is 1 — a probe arriving while another one runs is
  skipped, never queued;
- probes ride the existing global LLM gate, provider-abort timeout, and
  usage metering (``invoke_llm`` + invocation context, so receipts and the
  client usage ledger attribute the tokens; never a bypass);
- every outcome — including failures — is a quiet, bounded scene event;
  probe failures are never re-raised and never change the meeting contract.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from core.infrastructure.llm_utils import build_cacheable_system_message
from core.llm import LLMInvocationContext, invoke_llm
from core.llm.client import MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY
from core.web.services.team_workflow.llm_review_runners import (
    REVIEW_LLM_CACHE_SCOPE,
    REVIEW_LLM_SURFACE,
    _env_float,
    _env_int,
    _invoke_llm_with_timeout,
)

_KEEPALIVE_DELAY_MS_ENV = "VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS"
_KEEPALIVE_DELAY_MS_DEFAULT = 240_000
_KEEPALIVE_DELAY_MS_MAX = 3_600_000

# The probe discards its output; the smallest bounded budget only exists so
# providers that reject ``max_tokens`` below their floor keep accepting the
# call while the re-armed prefix still dominates the bill.
_KEEPALIVE_MAX_OUTPUT_TOKENS_ENV = (
    "VIBELUTION_MEETING_CACHE_KEEPALIVE_MAX_OUTPUT_TOKENS"
)
_KEEPALIVE_MAX_OUTPUT_TOKENS_DEFAULT = 16
_KEEPALIVE_MAX_OUTPUT_TOKENS_MAX = 256

# Wall-clock fence for one probe call.  Deliberately far below the review
# call budget: a keepalive that cannot finish in about a minute is not worth
# holding a global LLM slot for.
_KEEPALIVE_TIMEOUT_SECONDS_ENV = (
    "VIBELUTION_MEETING_CACHE_KEEPALIVE_TIMEOUT_SECONDS"
)
_KEEPALIVE_TIMEOUT_SECONDS_DEFAULT = 60.0
_KEEPALIVE_TIMEOUT_SECONDS_MIN = 5.0
_KEEPALIVE_TIMEOUT_SECONDS_MAX = 600.0

_PROBE_USER_CONTENT = "."
_PROBE_PURPOSE = "review_cache_keepalive"

_scheduled_keys: set[tuple[str, str, str]] = set()
_scheduled_keys_lock = threading.Lock()
_pending_timers: list[threading.Timer] = []
_pending_timers_lock = threading.Lock()
_probe_slot = threading.Semaphore(1)


def meeting_cache_keepalive_delay_ms() -> int:
    """Delay between a closed round and its keepalive probe; ``0`` disables."""

    return _env_int(
        _KEEPALIVE_DELAY_MS_ENV,
        _KEEPALIVE_DELAY_MS_DEFAULT,
        minimum=0,
        maximum=_KEEPALIVE_DELAY_MS_MAX,
    )


def probe_max_output_tokens() -> int:
    """Minimal output budget for one probe call."""

    return _env_int(
        _KEEPALIVE_MAX_OUTPUT_TOKENS_ENV,
        _KEEPALIVE_MAX_OUTPUT_TOKENS_DEFAULT,
        minimum=1,
        maximum=_KEEPALIVE_MAX_OUTPUT_TOKENS_MAX,
    )


def probe_call_timeout_seconds() -> float:
    """Wall-clock fence for one probe call."""

    return _env_float(
        _KEEPALIVE_TIMEOUT_SECONDS_ENV,
        _KEEPALIVE_TIMEOUT_SECONDS_DEFAULT,
        minimum=_KEEPALIVE_TIMEOUT_SECONDS_MIN,
        maximum=_KEEPALIVE_TIMEOUT_SECONDS_MAX,
    )


def _record_keepalive_scene_event(
    event_code: str,
    *,
    outcome: str,
    fields: dict[str, Any],
    level: str = "info",
) -> None:
    """Emit bounded keepalive diagnostics; never affect any caller."""

    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow",
            "review_cache_keepalive",
            event_code,
            message="Meeting prompt-cache keepalive probe observed.",
            level=level,
            outcome=outcome,
            fields=dict(fields),
            lifecycle=False,
        )
    except Exception:  # noqa: BLE001 - diagnostics must never fail the probe
        return


def _meeting_round_is_active(team_id: str, meeting_round_id: str) -> bool:
    """Return True while the meeting may still run another same-prefix round.

    Any read failure counts as inactive: the probe is optional, so an
    ambiguous meeting state always resolves to "do not fire".
    """

    try:
        from core.web.services.team_workflow import meeting_rounds

        meeting_round = meeting_rounds.get_meeting_round(team_id, meeting_round_id)[
            "meetingRound"
        ]
    except Exception:  # noqa: BLE001 - fail closed for an optional probe
        return False
    return str(meeting_round.get("status") or "").strip().lower() != "closed"


def _run_probe(
    team_id: str,
    meeting_round_id: str,
    *,
    system_prompt: str,
    resolve: Callable[[], dict[str, Any] | None] | None = None,
) -> None:
    """Fire one keepalive probe; every failure path stays quiet and bounded."""

    from core.web.services.team_workflow.llm_review_runners import (
        _response_usage_fields,
    )

    base_fields = {
        "teamId": str(team_id),
        "meetingRoundId": str(meeting_round_id),
    }
    if not _meeting_round_is_active(team_id, meeting_round_id):
        _record_keepalive_scene_event(
            "review_cache_keepalive.probe.skipped",
            outcome="skipped",
            fields={**base_fields, "reason": "meeting_closed_or_unreadable"},
        )
        return
    if not _probe_slot.acquire(blocking=False):
        _record_keepalive_scene_event(
            "review_cache_keepalive.probe.skipped",
            outcome="skipped",
            fields={**base_fields, "reason": "probe_busy"},
        )
        return
    started_at = time.monotonic()
    try:
        # Consulted through the owning module so test-isolation pins (conftest
        # resolves the review LLM to None) also disable probes, and so a
        # caller-injected resolver still wins.
        from core.web.services.team_workflow import llm_review_runners

        resolved = (resolve or llm_review_runners.resolve_review_llm)()
        if not resolved:
            _record_keepalive_scene_event(
                "review_cache_keepalive.probe.failed",
                outcome="failed",
                level="warning",
                fields={**base_fields, "reason": "review_llm_unavailable"},
            )
            return
        model_ref = str(resolved.get("modelRef") or "")
        messages: list[Any] = [
            # Byte-identical construction to the review/digest calls: the
            # provider can only hit the cache entry when the marked prefix
            # matches exactly.
            build_cacheable_system_message(system_prompt),
            {"role": "user", "content": _PROBE_USER_CONTENT},
        ]
        invocation_context = LLMInvocationContext(
            surface=REVIEW_LLM_SURFACE,
            run_kind="team_workflow_review",
            run_id="",
            session_id=str(team_id),
            agent_id=str(resolved.get("agentId") or "challenge_cup_evaluator"),
            llm_slot="dialogue",
            cache_scope=REVIEW_LLM_CACHE_SCOPE,
            cache_partition=f"{team_id}:{_PROBE_PURPOSE}",
            prompt_purpose=_PROBE_PURPOSE,
            conversation_bound=False,
            metadata={
                "purpose": _PROBE_PURPOSE,
                "teamId": str(team_id),
                "meetingRoundId": str(meeting_round_id),
            },
        )
        response = _invoke_llm_with_timeout(
            lambda: invoke_llm(
                resolved["client"],
                messages,
                context=invocation_context,
                metadata={
                    MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY: probe_max_output_tokens()
                },
            ),
            purpose=_PROBE_PURPOSE,
            timeout_seconds=probe_call_timeout_seconds(),
            model_ref=model_ref,
        )
        _record_keepalive_scene_event(
            "review_cache_keepalive.probe.succeeded",
            outcome="succeeded",
            fields={
                **base_fields,
                "modelRef": model_ref,
                "maxOutputTokens": probe_max_output_tokens(),
                "latencyMs": max(0, int((time.monotonic() - started_at) * 1000)),
                **_response_usage_fields(response),
            },
        )
    except Exception as exc:  # noqa: BLE001 - keepalive failures stay quiet
        _record_keepalive_scene_event(
            "review_cache_keepalive.probe.failed",
            outcome="failed",
            level="warning",
            fields={
                **base_fields,
                "errorType": type(exc).__name__,
                "latencyMs": max(0, int((time.monotonic() - started_at) * 1000)),
            },
        )
    finally:
        _probe_slot.release()


def schedule_meeting_cache_keepalive(
    team_id: str,
    meeting_round_id: str,
    *,
    dedupe_key: str = "",
    system_prompt: str | None = None,
    resolve: Callable[[], dict[str, Any] | None] | None = None,
) -> dict[str, str]:
    """Schedule one delayed cache keepalive probe for a closed meeting round.

    Fire-and-forget: callers (the discussion driver) must never observe a
    failure from scheduling.  ``dedupe_key`` should identify the round that
    just closed so each round interval schedules at most one probe.
    """

    normalized_team_id = str(team_id or "").strip()
    normalized_round_id = str(meeting_round_id or "").strip()
    normalized_dedupe_key = str(dedupe_key or "").strip()
    delay_ms = meeting_cache_keepalive_delay_ms()
    base_fields = {
        "teamId": normalized_team_id,
        "meetingRoundId": normalized_round_id,
        "delayMs": delay_ms,
    }
    if not normalized_team_id or not normalized_round_id or delay_ms <= 0:
        return {"status": "disabled", "delayMs": str(delay_ms)}
    dedupe = (normalized_team_id, normalized_round_id, normalized_dedupe_key)
    with _scheduled_keys_lock:
        if dedupe in _scheduled_keys:
            return {"status": "duplicate", "delayMs": str(delay_ms)}
        _scheduled_keys.add(dedupe)
    if system_prompt is None:
        # The reflection prompt is the heaviest prefix every review wave
        # re-sends per question, so keeping it warm benefits the next round
        # the most.  Imported lazily to keep module import weight low.
        from core.web.services.team_workflow.llm_review_runners import (
            _REFLECTION_SYSTEM_PROMPT,
        )

        system_prompt = _REFLECTION_SYSTEM_PROMPT
    timer = threading.Timer(
        delay_ms / 1000.0,
        _run_probe,
        args=(normalized_team_id, normalized_round_id),
        kwargs={
            "system_prompt": system_prompt,
            "resolve": resolve,
        },
    )
    timer.daemon = True
    with _pending_timers_lock:
        _pending_timers.append(timer)
    timer.start()
    _record_keepalive_scene_event(
        "review_cache_keepalive.scheduled",
        outcome="started",
        fields=base_fields,
    )
    return {"status": "scheduled", "delayMs": str(delay_ms)}


def reset_meeting_cache_keepalive_for_tests() -> None:
    """Drop scheduled probes and registry state between tests."""

    global _probe_slot
    with _pending_timers_lock:
        timers = list(_pending_timers)
        _pending_timers.clear()
    for timer in timers:
        timer.cancel()
    with _scheduled_keys_lock:
        _scheduled_keys.clear()
    # A leaked in-flight probe releases its own (old) semaphore, so rebinding
    # a fresh slot guarantees the next test starts uncongested.
    _probe_slot = threading.Semaphore(1)
