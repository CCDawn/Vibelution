"""DashScope explicit prompt-cache keepalive probes for active meetings.

DashScope explicit ``cache_control`` entries live ~5 minutes and every hit
re-arms the TTL.  Challenge review/generation rounds are typically spaced
6-15 minutes apart (measured round gaps run 18-92 minutes), so the marked
shared prefixes — every review step's system prompt — reliably expire between
rounds and each next-round call pays the full uncached input price.

After a meeting round closes, the meeting discussion driver schedules delayed
minimal probes (default ~4 minutes, before the TTL expires) through this
module.  One probe fans out over EVERY review step's system prompt
(reflection / pairwise / pareto / metareview / revision, via
``llm_review_runners.review_step_system_prompts``): the historical
single-prompt probe kept only the heaviest reflection prefix warm while the
other steps' shorter prompts never got probed and always started cold.  Each
probe re-sends a ``cache_control``-marked shared prefix with a tiny output
budget via the normal review LLM channel, so the provider re-arms that
prefix's TTL for the next round.

TTL-aware chaining: one probe only re-arms the TTL for roughly the next five
minutes, far shorter than measured round gaps, so each fired probe chains a
bounded number of follow-up probes (``VIBELUTION_MEETING_CACHE_KEEPALIVE_CHAIN_MAX_PROBES``)
spaced one keepalive delay apart.  Chaining stops as soon as the meeting round
closes or becomes unreadable — no active review wave means no probing, so idle
meetings never burn tokens.

Review-wave gap probes (``ReviewWaveGapKeepalive``): the review itself runs
after the meeting round closed, and its reflection→pairwise gap measured
~323 s — past the TTL — so the pairwise wave started cold even with the
round-gap probes above.  The hypothesis review executor arms one wave handle
when the reflection wave starts and cancels it when that wave completes; the
handle fires a probe (pairwise prompt = shared head + pairwise tail) every
keepalive delay only while the wave is still running, so short waves never
probe and long waves keep the next wave's prefix warm.  Same probe path, same
guards, wave-scoped liveness instead of the meeting-round one.

Hard guards (keepalive is a pure optimization and must never affect the main
chain or its accounting):

- ``VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS=0`` disables the feature;
- ``VIBELUTION_MEETING_CACHE_KEEPALIVE_CHAIN_MAX_PROBES`` bounds the per-prompt
  probe chain (default 6 probes ≈ one 24-minute gap at the default delay);
- at most one scheduled probe chain per (meeting, closed round, prompt) per
  process;
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

# TTL-aware probe chain: DashScope cache entries expire ~5 minutes after the
# last hit, so probes spaced one keepalive delay apart (default 4 minutes)
# keep a prefix continuously warm for ``chain_max_probes * delay``.  The
# default 6 probes covers the short end of the measured 18-92 minute round
# gaps; longer gaps trade a cold first call for bounded idle burn.
_KEEPALIVE_CHAIN_MAX_PROBES_ENV = "VIBELUTION_MEETING_CACHE_KEEPALIVE_CHAIN_MAX_PROBES"
_KEEPALIVE_CHAIN_MAX_PROBES_DEFAULT = 6
_KEEPALIVE_CHAIN_MAX_PROBES_MIN = 1
_KEEPALIVE_CHAIN_MAX_PROBES_MAX = 48

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

_scheduled_keys: set[tuple[str, str, str, str]] = set()
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


def keepalive_chain_max_probes() -> int:
    """Bounded probe chain length per (round, prompt); every hit re-arms the TTL."""

    return _env_int(
        _KEEPALIVE_CHAIN_MAX_PROBES_ENV,
        _KEEPALIVE_CHAIN_MAX_PROBES_DEFAULT,
        minimum=_KEEPALIVE_CHAIN_MAX_PROBES_MIN,
        maximum=_KEEPALIVE_CHAIN_MAX_PROBES_MAX,
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


def _schedule_keepalive_timer(
    team_id: str,
    meeting_round_id: str,
    *,
    system_prompt: str,
    prompt_tag: str,
    chain_index: int,
    resolve: Callable[[], dict[str, Any] | None] | None,
) -> None:
    """Start one daemon fire-and-forget probe timer and register it."""

    timer = threading.Timer(
        meeting_cache_keepalive_delay_ms() / 1000.0,
        _run_probe,
        args=(team_id, meeting_round_id),
        kwargs={
            "system_prompt": system_prompt,
            "prompt_tag": prompt_tag,
            "chain_index": chain_index,
            "resolve": resolve,
        },
    )
    timer.daemon = True
    with _pending_timers_lock:
        _pending_timers.append(timer)
    timer.start()


def _maybe_chain_next_probe(
    team_id: str,
    meeting_round_id: str,
    *,
    system_prompt: str,
    prompt_tag: str,
    chain_index: int,
    resolve: Callable[[], dict[str, Any] | None] | None,
) -> None:
    """Re-arm this prompt's prefix before the TTL expires again.

    Chained from a *fired* probe only, bounded by the chain budget, and only
    while the meeting round is still active — a closed or unreadable round
    means no review wave is anticipated, so the chain stops here.
    """

    next_index = chain_index + 1
    if chain_index < 1 or next_index > keepalive_chain_max_probes():
        return
    if meeting_cache_keepalive_delay_ms() <= 0:
        return
    if not _meeting_round_is_active(team_id, meeting_round_id):
        return
    _schedule_keepalive_timer(
        team_id,
        meeting_round_id,
        system_prompt=system_prompt,
        prompt_tag=prompt_tag,
        chain_index=next_index,
        resolve=resolve,
    )
    _record_keepalive_scene_event(
        "review_cache_keepalive.chained",
        outcome="started",
        fields={
            "teamId": str(team_id),
            "meetingRoundId": str(meeting_round_id),
            "promptTag": str(prompt_tag),
            "chainIndex": int(next_index),
            "delayMs": meeting_cache_keepalive_delay_ms(),
        },
    )


def _run_probe(
    team_id: str,
    meeting_round_id: str,
    *,
    system_prompt: str,
    prompt_tag: str = "custom",
    chain_index: int = 0,
    resolve: Callable[[], dict[str, Any] | None] | None = None,
    is_active: Callable[[], bool] | None = None,
) -> None:
    """Fire one keepalive probe; every failure path stays quiet and bounded.

    ``is_active`` lets a caller swap the default "meeting round still open"
    liveness gate (round-gap probes between discussion rounds) for its own
    wave-scoped predicate (the review wave probes below, which run while the
    meeting round is already closed).
    """

    from core.web.services.team_workflow.llm_review_runners import (
        _response_usage_fields,
    )

    base_fields = {
        "teamId": str(team_id),
        "meetingRoundId": str(meeting_round_id),
        "promptTag": str(prompt_tag),
        "chainIndex": int(chain_index),
    }
    active_check = is_active or (
        lambda: _meeting_round_is_active(team_id, meeting_round_id)
    )
    if not active_check():
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
            # Byte-identical construction to the review calls: the provider
            # can only hit the cache entry when the marked prefix matches
            # exactly, so the probe goes through the same shared-head builder
            # (head block + step tail block) the review calls use.
            llm_review_runners.build_review_system_message(system_prompt),
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
    # TTL-aware chaining: only a probe that actually fired may extend the
    # chain; skip paths (closed meeting, busy slot) never do.
    _maybe_chain_next_probe(
        team_id,
        meeting_round_id,
        system_prompt=system_prompt,
        prompt_tag=prompt_tag,
        chain_index=chain_index,
        resolve=resolve,
    )


class ReviewWaveGapKeepalive:
    """Re-arm the next review wave's cacheable prefix while one wave runs.

    Measured review waves gap longer than the ~5 minute DashScope explicit-cache
    TTL: the last reflection call warms the shared prefix, then the pairwise
    wave's first dispatch lands ~5.5 minutes later and pays full price.  The
    executor arms this handle when the reflection wave starts; a timer fires
    one minimal probe every keepalive delay (default 4 minutes) *only while
    the wave is still running* — cancelling the handle (reflection wave done,
    pairwise wave follows immediately) leaves short waves completely
    probe-free, so the probe is scheduled exactly when the reflection→pairwise
    gap is predicted to cross the TTL.  Probes ride ``_run_probe`` unchanged
    (same LLM gate, budget, metering, quiet diagnostics) with a wave-scoped
    liveness predicate instead of the meeting-round one: the review runs after
    the meeting round already closed.

    Re-arms are bounded by ``keepalive_chain_max_probes()`` and everything is
    fire-and-forget: ``cancel()`` is idempotent and never raises.
    """

    def __init__(
        self,
        *,
        team_id: str,
        meeting_round_id: str,
        system_prompt: str,
        prompt_tag: str,
        resolve: Callable[[], dict[str, Any] | None] | None,
    ) -> None:
        self._team_id = str(team_id)
        self._meeting_round_id = str(meeting_round_id)
        self._system_prompt = str(system_prompt)
        self._prompt_tag = str(prompt_tag)
        self._resolve = resolve
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._probes_armed = 0

    def start(self) -> "ReviewWaveGapKeepalive | None":
        """Arm the first delayed probe; ``None``-equivalent when disabled."""

        if meeting_cache_keepalive_delay_ms() <= 0:
            self._cancelled.set()
            return None
        self._schedule_timer()
        return self

    def _schedule_timer(self) -> None:
        timer = threading.Timer(
            meeting_cache_keepalive_delay_ms() / 1000.0,
            self._fire,
        )
        timer.daemon = True
        with self._lock:
            if self._cancelled.is_set():
                return
            self._timer = timer
            self._probes_armed += 1
        # Register with the module registry so test resets cancel wave timers
        # the same way they cancel round-gap probe timers.
        with _pending_timers_lock:
            _pending_timers.append(timer)
        timer.start()

    def _fire(self) -> None:
        if self._cancelled.is_set():
            return
        with self._lock:
            self._timer = None
            chain_index = self._probes_armed
        _run_probe(
            self._team_id,
            self._meeting_round_id,
            system_prompt=self._system_prompt,
            prompt_tag=self._prompt_tag,
            chain_index=chain_index,
            resolve=self._resolve,
            is_active=lambda: not self._cancelled.is_set(),
        )
        # Re-arm for waves that outlive one probe interval, bounded by the
        # same chain budget as the round-gap probes.
        if (
            not self._cancelled.is_set()
            and chain_index < keepalive_chain_max_probes()
            and meeting_cache_keepalive_delay_ms() > 0
        ):
            self._schedule_timer()

    def cancel(self) -> None:
        """Stop the chain; the wave ended, so no further probe may fire."""

        self._cancelled.set()
        with self._lock:
            timer = self._timer
            self._timer = None
        if timer is not None:
            timer.cancel()


def review_wave_gap_probe_prompt() -> tuple[str, str]:
    """Return ``(promptTag, systemPrompt)`` the wave-gap probe should send.

    The pairwise prompt is the highest-value target: its marked blocks are
    (a) the shared system head every next wave reuses and (b) the pairwise
    step tail itself.  Falls back to the raw reflection prompt if the step
    list ever changes shape.
    """

    from core.web.services.team_workflow.llm_review_runners import (
        review_step_system_prompts,
    )

    prompts = dict(review_step_system_prompts())
    return "pairwise", prompts.get("pairwise") or prompts.get("reflection", "")


def schedule_review_wave_gap_keepalive(
    team_id: str,
    meeting_round_id: str,
    *,
    resolve: Callable[[], dict[str, Any] | None] | None = None,
) -> ReviewWaveGapKeepalive | None:
    """Arm the reflection→pairwise gap keepalive for one review execution.

    Fire-and-forget: returns the handle the executor cancels when the
    reflection wave completes, or ``None`` when the feature is disabled
    (keepalive delay 0) or the scope is unusable.  Never raises.
    """

    normalized_team_id = str(team_id or "").strip()
    normalized_round_id = str(meeting_round_id or "").strip()
    if (
        not normalized_team_id
        or not normalized_round_id
        or meeting_cache_keepalive_delay_ms() <= 0
    ):
        return None
    try:
        prompt_tag, system_prompt = review_wave_gap_probe_prompt()
        if not system_prompt:
            return None
        return ReviewWaveGapKeepalive(
            team_id=normalized_team_id,
            meeting_round_id=normalized_round_id,
            system_prompt=system_prompt,
            prompt_tag=prompt_tag,
            resolve=resolve,
        ).start()
    except Exception:  # noqa: BLE001 - keepalive scheduling never blocks reviews
        return None


def schedule_meeting_cache_keepalive(
    team_id: str,
    meeting_round_id: str,
    *,
    dedupe_key: str = "",
    system_prompt: str | None = None,
    resolve: Callable[[], dict[str, Any] | None] | None = None,
) -> dict[str, str]:
    """Schedule delayed cache keepalive probes for a closed meeting round.

    Fire-and-forget: callers (the discussion driver) must never observe a
    failure from scheduling.  ``dedupe_key`` should identify the round that
    just closed so each round interval schedules at most one probe chain per
    prompt.  Without an explicit ``system_prompt``, one probe is scheduled for
    EVERY review step's shared system prompt — keeping only the heaviest
    reflection prefix warm left the other steps' prompts permanently cold.
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
    if system_prompt is None:
        # One probe per review step system prompt, imported lazily to keep
        # module import weight low.
        from core.web.services.team_workflow.llm_review_runners import (
            review_step_system_prompts,
        )

        targets: tuple[tuple[str, str], ...] = review_step_system_prompts()
    else:
        targets = (("custom", str(system_prompt)),)
    scheduled_any = False
    scheduled_tags: list[str] = []
    for prompt_tag, prompt in targets:
        dedupe = (
            normalized_team_id,
            normalized_round_id,
            normalized_dedupe_key,
            str(prompt_tag),
        )
        with _scheduled_keys_lock:
            if dedupe in _scheduled_keys:
                continue
            _scheduled_keys.add(dedupe)
        _schedule_keepalive_timer(
            normalized_team_id,
            normalized_round_id,
            system_prompt=prompt,
            prompt_tag=str(prompt_tag),
            chain_index=1,
            resolve=resolve,
        )
        scheduled_any = True
        scheduled_tags.append(str(prompt_tag))
    if not scheduled_any:
        return {"status": "duplicate", "delayMs": str(delay_ms)}
    _record_keepalive_scene_event(
        "review_cache_keepalive.scheduled",
        outcome="started",
        fields={**base_fields, "promptTags": scheduled_tags},
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
