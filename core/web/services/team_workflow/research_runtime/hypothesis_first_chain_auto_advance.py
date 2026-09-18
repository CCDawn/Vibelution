"""Auto-advance entry points for the hypothesis-first chain.

Functions here execute with ``hypothesis_first_chain`` globals so tests that
patch the facade still apply. Command and meeting orchestration stay on
``hypothesis_first_chain``.
"""

from __future__ import annotations

import types
from collections.abc import Mapping, Sequence
from typing import Any

# Names are resolved on the chain facade at call time. See bind_to_chain.
# ruff: noqa: F821


def bind_to_chain(chain_globals: dict[str, Any]) -> None:
    """Rebind auto-advance callables so LOAD_GLOBAL uses the chain facade."""

    for name in _EXPORTS:
        fn = globals()[name]
        if fn.__globals__ is chain_globals:
            chain_globals.setdefault(name, fn)
            continue
        rebound = types.FunctionType(
            fn.__code__,
            chain_globals,
            fn.__name__,
            fn.__defaults__,
            fn.__closure__,
        )
        rebound.__kwdefaults__ = fn.__kwdefaults__
        rebound.__annotations__ = dict(fn.__annotations__)
        rebound.__doc__ = fn.__doc__
        rebound.__module__ = __name__
        rebound.__qualname__ = fn.__qualname__
        rebound.__dict__.update(fn.__dict__)
        globals()[name] = rebound
        chain_globals[name] = rebound


# ---------------------------------------------------------------------------
# automation policy active execution hooks (gated, audited, quiet)
#
# The executor only ever presses the chain's own idempotent buttons after its
# full safety ladder (kill switch, activation credential, calibration gate,
# drain mode, capability switch) passes; with no active policy configured
# every hook below is a no-op before any I/O, so these calls stay
# behavior-identical to the pre-executor chain.


def _auto_advance_selection_tick(
    team_id: str,
    meeting_round: Mapping[str, Any],
    candidates: list[dict[str, Any]],
) -> None:
    """Try autoSelectCandidates right after generation candidates register."""

    if (
        meeting_round.get("candidateAuthority") == FORMAL_GROUNDED_CANDIDATE_AUTHORITY
        and _meeting_workflow_run_id(meeting_round)
    ):
        return

    from core.web.services.team_workflow.research_runtime import (
        automation_policy_executor,
    )

    question_id = str(meeting_round.get("question") or "").strip()
    candidate_ids = [
        str(item.get("hypothesisId") or item.get("candidateId") or "").strip()
        for item in candidates
        if isinstance(item, Mapping)
    ]
    automation_policy_executor.attempt_capability_quietly(
        decision_point="candidate_selection",
        team_id=team_id,
        question_id=question_id,
        candidate_ids=candidate_ids,
        selection_scope=_question_scope_envelope(team_id, question_id),
    )



def _auto_advance_converge_tick(team_id: str, question_id: str) -> None:
    """Try autoConvergeQuestion after a review closure settles."""

    from core.web.services.team_workflow.research_runtime import (
        automation_policy_executor,
    )

    automation_policy_executor.attempt_capability_quietly(
        decision_point="converge_question",
        team_id=team_id,
        question_id=str(question_id or "").strip(),
    )



def _auto_advance_meeting_close_tick(team_id: str, meeting_round_id: str) -> None:
    """Try autoCloseMeetingRound after a summary draft lands (awaiting_approval)."""

    from core.web.services.team_workflow.research_runtime import (
        automation_policy_executor,
    )

    automation_policy_executor.attempt_capability_quietly(
        decision_point="meeting_close",
        team_id=team_id,
        meeting_round_id=str(meeting_round_id or "").strip(),
    )



def _auto_redispatch_superseded_reviews(
    team_id: str,
    *,
    selection_id: str,
    candidate_ids: Sequence[str],
) -> dict[str, Any]:
    """Re-dispatch superseded digest-less review identities (bounded).

    A superseded closing (``discussion_has_no_completed_messages``) has no
    open meeting to close, so a fan-in that keeps waiting on it can only make
    progress by dispatching the candidate's review again (SCI-117 waited
    eight days for a "last sibling close" that could never happen).  Bound:
    each (selection, candidate, current round) identity is re-dispatched
    automatically at most ``AUTO_REDISPATCH_SUPERSEDED_LIMIT`` times, counted
    from the durable dispatch-attempt ledger.  Every attempt that actually
    dispatched (``superseded`` or ``succeeded``) consumes budget: a meeting
    that opened but produced no closure comes back through this sweep as
    another ``waiting_for_sibling_reviews`` pass, so counting only
    ``superseded`` outcomes let a chain re-open the same review meeting
    forever (the SCI-117 loop).  Afterwards the structured wait stays with
    the explicit operator hint.  Best-effort: nothing raises.
    """

    normalized_selection_id = str(selection_id or "").strip()
    requested = [
        str(item or "").strip()
        for item in candidate_ids
        if str(item or "").strip()
    ]
    summary: dict[str, Any] = {
        "requested": len(requested),
        "redispatched": 0,
        "exhausted": 0,
        "failed": 0,
    }
    if not normalized_selection_id or not requested:
        return summary
    try:
        records = _read_jsonl(_storage_path(team_id))
    except Exception as exc:  # noqa: BLE001 - best-effort recovery
        summary["failed"] = len(requested)
        summary["error"] = str(exc)[:200]
        return summary

    def auto_dispatch_attempt_count(candidate_id: str) -> int:
        identity = [
            item
            for item in _review_dispatch_attempts(
                records, selection_id=normalized_selection_id
            )
            if str(item.get("candidateId") or "").strip() == candidate_id
        ]
        if not identity:
            return 0
        newest = max(
            identity,
            key=lambda item: (
                int(item.get("attemptNumber") or 0),
                str(item.get("updatedAt") or item.get("createdAt") or ""),
            ),
        )
        newest_round = int(newest.get("roundIndex") or 1)
        return sum(
            1
            for item in identity
            if int(item.get("roundIndex") or 1) == newest_round
            and str(item.get("outcome") or "") in AUTO_REDISPATCH_CONSUMING_OUTCOMES
        )

    eligible: list[str] = []
    for candidate_id in requested:
        if auto_dispatch_attempt_count(candidate_id) >= AUTO_REDISPATCH_SUPERSEDED_LIMIT:
            summary["exhausted"] += 1
            continue
        eligible.append(candidate_id)
    if not eligible:
        return summary
    try:
        retry_review_dispatch(
            team_id, normalized_selection_id, eligible
        )
        summary["redispatched"] = len(eligible)
    except Exception as exc:  # noqa: BLE001 - best-effort recovery
        summary["failed"] = len(eligible)
        summary["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return summary



def _auto_adjudication_idempotency_key(round_id: str) -> str:
    return f"hf2:auto-adjudication:{str(round_id or '').strip()}"



def _auto_adjudication_rejected_key(round_id: str) -> str:
    """Distinct key for the auto-recorded rejected (gate-blocked) outcome."""
    return f"hf2:auto-adjudication-rejected:{str(round_id or '').strip()}"



def auto_adjudicate_exhausted_round(team_id: str, *, question_id: str) -> dict[str, Any]:
    """Serialize automatic read/check/write with frontend adjudication commands."""
    try:
        with hypothesis_first_scope_lock(team_id, question_id):
            return _auto_adjudicate_exhausted_round_locked(team_id, question_id=question_id)
    except Exception as exc:
        return {"status": "failed", "reason": type(exc).__name__, "detail": str(exc)[:200]}



def _auto_adjudicate_exhausted_round_locked(
    team_id: str,
    *,
    question_id: str,
) -> dict[str, Any]:
    """Close an accepted review early, or adjudicate an exhausted review round.

    Fires when the latest closed HypothesisRound has an accepted meta-review
    and passed quality checks, or its review-round budget has been spent,
    no adjudication exists for it yet, and no collection request is still
    pending (the same pending-collection clause that blocks an accepted
    adjudication in the convergence read model).  The appended record is the
    ordinary convergence authority: deterministic rationale (no timestamps),
    idempotency key ``hf2:auto-adjudication:<roundId>`` and
    a system actor identifying accepted-review or budget closeout keep replays returning
    ``reused`` forever.  A pre-existing human (or foreign-policy) adjudication
    is never overwritten — ``skipped``.  A legacy auto adjudication for the
    exact round may receive one append-only run-binding amendment when every
    round meeting resolves to the same workflow run.

    Claim-belief hard gate: the gate keeps its fail-closed semantics (blocked
    never reaches the formal path), but per the challenge-cup retention policy
    the chain must still land in a terminal state with a formal result record.
    A blocked gate therefore auto-records a REJECTED adjudication
    (``hf2:auto-adjudication-rejected:<roundId>``,
    ``system:auto-advance:gate-blocked`` — rejecting is never gated, so this
    cannot self-lock) and returns ``rejected``; the projection flips to
    completed/rejected/terminal and the exhausted anomaly item disappears,
    while the re-selection unlock stays the existing human path.  Only the
    gate-blocked failure records an outcome — transient errors (storage etc.)
    return ``failed`` with no record so the sweep can retry.  No exception
    ever escapes this helper.
    """
    from core.web.services import team_service

    round_id = ""
    round_index = 0
    accepted_review_closeout = False
    normalized_team_id = team_id
    normalized_question_id = str(question_id or "").strip().upper()
    try:
        normalized_team_id = team_service.assert_team_exists(team_id)
        latest_round = _latest_closed_exhausted_round(
            normalized_team_id, normalized_question_id
        )
        if latest_round is None:
            return {"status": "skipped", "reason": "round_not_exhausted"}
        round_id = str(latest_round.get("roundId") or "").strip()
        try:
            round_index = int(latest_round.get("roundIndex") or 0)
        except (TypeError, ValueError):
            round_index = 0
        accepted_review_closeout = round_index < HARD_ROUND_LIMIT
        idempotency_key = _auto_adjudication_idempotency_key(round_id)
        existing = _latest_round_adjudication(
            _records(normalized_team_id),
            question_id=normalized_question_id,
            round_id=round_id,
        )
        # Resolve the immutable run from every meeting ref before inspecting
        # an existing auto decision.  This lets the maintenance sweep append
        # an audit-preserving binding amendment for records written before
        # workflowRunId existed; no in-place data mutation is performed.
        adjudication_workflow_run_id = _adjudication_workflow_run_id(
            normalized_team_id,
            latest_round,
            workflow_run_id="",
        )
        if existing is not None and adjudication_workflow_run_id:
            repaired = _repair_auto_adjudication_workflow_run_binding(
                normalized_team_id,
                question_id=normalized_question_id,
                round_record=latest_round,
                adjudication=existing,
                workflow_run_id=adjudication_workflow_run_id,
            )
            if repaired is not None:
                if (
                    str(repaired.get("workflowRunId") or "").strip()
                    == adjudication_workflow_run_id
                    and not str(existing.get("workflowRunId") or "").strip()
                ):
                    _record_scene_event(
                        "hypothesis_first.auto_adjudication_binding_repaired",
                        outcome="applied",
                        fields={
                            "teamId": normalized_team_id,
                            "questionId": normalized_question_id,
                            "roundId": round_id,
                            "workflowRunId": adjudication_workflow_run_id,
                            "adjudicationId": str(
                                repaired.get("adjudicationId") or ""
                            ),
                        },
                    )
                existing = repaired
        if existing is not None:
            existing_key = str(existing.get("idempotencyKey") or "")
            if existing_key == _auto_adjudication_rejected_key(round_id):
                # Our rejected outcome is already the recorded terminal
                # result; replays report reused and never flip it to accepted
                # (a repaired claim re-opens through the human selection
                # path, not by overwriting this verdict).
                return {
                    "status": "reused",
                    "reason": "claim_belief_gate_blocked",
                    "roundId": round_id,
                    "decision": "rejected",
                }
            if existing_key != idempotency_key:
                return {
                    "status": "skipped",
                    "reason": "adjudication_exists",
                    "roundId": round_id,
                    "decision": str(existing.get("decision") or ""),
                }
        if _pending_handoff_count(normalized_team_id, normalized_question_id):
            return {
                "status": "skipped",
                "reason": "pending_collection",
                "roundId": round_id,
            }
        result = record_human_adjudication(
            normalized_team_id,
            question_id=normalized_question_id,
            hypothesis_round_id=round_id,
            decision="accepted",
            rationale=(
                "auto-advance: accepted meta-review and passed quality checks; "
                "all evidence handoffs completed"
                if accepted_review_closeout
                else
                "auto-advance: review round budget exhausted "
                f"({round_index}/{HARD_ROUND_LIMIT}); auto-advanced per "
                "budget-exhaustion policy"
            ),
            idempotency_key=idempotency_key,
            workflow_run_id=adjudication_workflow_run_id,
            decided_by=(
                "system:auto-advance:meta-review-accepted"
                if accepted_review_closeout
                else "system:auto-advance:budget-exhausted"
            ),
        )
        status = str(result.get("status") or "")
        adjudication = result.get("adjudication")
        _record_scene_event(
            "hypothesis_first.auto_adjudication",
            outcome=status,
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "roundId": round_id,
                "roundIndex": round_index,
                "adjudicationId": str(
                    (adjudication or {}).get("adjudicationId") or ""
                )
                if isinstance(adjudication, Mapping)
                else "",
            },
        )
        return {
            "status": status,
            "roundId": round_id,
            "decision": "accepted",
            "adjudicationId": str(
                (adjudication or {}).get("adjudicationId") or ""
            )
            if isinstance(adjudication, Mapping)
            else "",
        }
    except ClaimBeliefGateBlockedError as exc:
        # Fail-closed hard gate: the recommended candidate must not reach the
        # formal path.  The gate verdict is final for this chain, so the
        # formal failure outcome is recorded right here (challenge-cup
        # retention policy: even a rejected convergence must leave a
        # queryable result, not a dangling human wait).
        gate_reason = _claim_gate_block_reason(exc)
        _record_scene_event(
            "hypothesis_first.auto_adjudication",
            outcome="blocked_by_claim_gate",
            level="warning",
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "roundId": round_id,
                "candidateId": str(getattr(exc, "candidate_id", "") or ""),
                "reason": "claim_belief_gate_blocked",
                "gateReason": gate_reason,
                "error": str(exc)[:400],
            },
        )
        try:
            result = record_human_adjudication(
                normalized_team_id,
                question_id=normalized_question_id,
                hypothesis_round_id=round_id,
                decision="rejected",
                rationale=(
                    "auto-advance: claim belief gate blocked "
                    f"({gate_reason}); "
                    + (
                        "accepted meta-review could not pass the claim gate; "
                        if accepted_review_closeout else
                        f"review round budget exhausted ({round_index}/{HARD_ROUND_LIMIT}); "
                    )
                    + "unconverged outcome "
                    "recorded per challenge-cup retention policy"
                ),
                idempotency_key=_auto_adjudication_rejected_key(round_id),
                workflow_run_id=adjudication_workflow_run_id,
                decided_by="system:auto-advance:gate-blocked",
            )
        except Exception as record_exc:  # noqa: BLE001 - stay retryable
            # Even the outcome record failed (transient): leave nothing
            # behind so the sweep can retry the whole advance.
            _record_scene_event(
                "hypothesis_first.auto_adjudication",
                outcome="failed",
                level="warning",
                fields={
                    "teamId": normalized_team_id,
                    "questionId": normalized_question_id,
                    "roundId": round_id,
                    "reason": "claim_belief_gate_blocked",
                    "rejectedRecordError": str(record_exc)[:400],
                },
            )
            return {
                "status": "failed",
                "reason": "claim_belief_gate_blocked",
                "detail": str(record_exc)[:200],
            }
        rejected_status = str(result.get("status") or "")
        adjudication = result.get("adjudication")
        _record_scene_event(
            "hypothesis_first.auto_adjudication",
            outcome=rejected_status,
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "roundId": round_id,
                "roundIndex": round_index,
                "decision": "rejected",
                "gateReason": gate_reason,
            },
        )
        return {
            # A fresh rejected outcome reads as "rejected"; replays read as
            # the ordinary idempotent "reused".
            "status": "rejected" if rejected_status == "created" else rejected_status,
            "reason": "claim_belief_gate_blocked",
            "roundId": round_id,
            "decision": "rejected",
            "adjudicationId": str(
                (adjudication or {}).get("adjudicationId") or ""
            )
            if isinstance(adjudication, Mapping)
            else "",
        }
    except Exception as exc:  # noqa: BLE001 - auto-advance is best-effort
        _record_scene_event(
            "hypothesis_first.auto_adjudication",
            outcome="failed",
            level="warning",
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "roundId": round_id,
                "reason": type(exc).__name__,
                "error": str(exc)[:400],
            },
        )
        return {
            "status": "failed",
            "reason": type(exc).__name__,
            "detail": str(exc)[:200],
        }



def auto_create_formal_run_after_convergence(
    team_id: str,
    *,
    question_id: str,
) -> dict[str, Any]:
    """Create + auto-start the formal run behind a converged review chain.

    Budget-exhaustion auto-advance, step two (safe to call standalone).  The
    guard mirrors the v2 ``create_formal_run`` offer projection exactly: the
    latest round holds an accepted adjudication, no collection request is
    pending, the claim-belief hard gate allows the confirmed candidate, the
    question owns no live formal run yet, and the recommended candidate id is
    present.  The action reuses the exact ``create_formal_run`` command
    channel — ``create_question_run`` plus ``_auto_start_created_formal_run``
    (the start rides its own offer gate; readiness is never bypassed) — with
    the canonical V2 offer and idempotency key shared with the frontend.
    Stage-one policy-covered
    questions carry the durable CatalogRunAuthorization like the
    ``_create_stage_one_question_run`` precedent; a missing authorization or
    an authorization replay mismatch is a structured ``failed`` plus scene
    event, never a raise.
    """
    from core.web.services import team_service

    from .service import ResearchWorkflowError

    try:
        normalized_team_id = team_service.assert_team_exists(team_id)
        normalized_question_id = str(question_id or "").strip().upper()
        rounds = _question_hypothesis_rounds(
            normalized_team_id, normalized_question_id
        )
        latest_round = rounds[-1] if rounds else None
        round_id = str((latest_round or {}).get("roundId") or "").strip()
        if (
            not round_id
            or str((latest_round or {}).get("status") or "").strip().lower()
            != "closed"
        ):
            return {"status": "skipped", "reason": "no_closed_round"}
        adjudication = _latest_round_adjudication(
            _records(normalized_team_id),
            question_id=normalized_question_id,
            round_id=round_id,
        )
        if (
            adjudication is None
            or str(adjudication.get("decision") or "").strip().lower()
            != "accepted"
        ):
            return {"status": "skipped", "reason": "no_accepted_adjudication"}
        if _pending_handoff_count(normalized_team_id, normalized_question_id):
            return {
                "status": "skipped",
                "reason": "pending_collection",
                "roundId": round_id,
            }
        meta_review = (
            latest_round.get("metaReview")
            if isinstance(latest_round.get("metaReview"), Mapping)
            else {}
        )
        confirmed_candidate_id = str(
            meta_review.get("recommendationCandidateId") or ""
        ).strip()
        if not confirmed_candidate_id:
            return {
                "status": "skipped",
                "reason": "confirmed_candidate_missing",
                "roundId": round_id,
            }
        gate_verdict = evaluate_claim_belief_gate(
            normalized_team_id,
            normalized_question_id,
            [confirmed_candidate_id],
        ).get(confirmed_candidate_id) or _blocked_gate_verdict(
            confirmed_candidate_id, "claim_belief_evaluation_failed"
        )
        if str(gate_verdict.get("status") or "") != "allowed":
            return {
                "status": "skipped",
                "reason": "claim_belief_gate_not_allowed",
                "roundId": round_id,
                "gateReason": str(gate_verdict.get("reason") or ""),
            }
        formal_run_exists = _question_non_archived_formal_run_exists(
            normalized_team_id, normalized_question_id
        )
        if formal_run_exists is None:
            return {"status": "skipped", "reason": "formal_runtime_unavailable"}
        if formal_run_exists:
            return {
                "status": "skipped",
                "reason": "formal_run_exists",
                "roundId": round_id,
            }
        from .hypothesis_first_state_v2 import project_hypothesis_first_state_v2

        state = project_hypothesis_first_state_v2(normalized_team_id, normalized_question_id)
        offer = next((item for item in state.get("allowedActions") or []
                      if item.get("kind") == "command"
                      and item.get("command") == "create_formal_run"
                      and item.get("enabled") is True), None)
        if offer is None:
            return {"status": "skipped", "reason": "formal_creation_not_offered", "roundId": round_id}
        executed = execute_v2_command(
            normalized_team_id,
            {**offer, "expectedStateVersion": state["stateVersion"]},
            question_id=normalized_question_id,
            _actor="system:auto-advance:formal-creation",
        )
        result = executed.get("result") or {}
        run_id = str(result.get("runId") or "").strip()
        _record_scene_event(
            "hypothesis_first.auto_formal_run",
            outcome="created",
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "roundId": round_id,
                "runId": run_id,
            },
        )
        return {"status": "created", "roundId": round_id, "runId": run_id}
    except Exception as exc:  # noqa: BLE001 - auto-advance is best-effort
        # Run-creation contract errors (catalog_run_authorization_required /
        # catalog_run_authorization_replay_mismatch / idempotency_conflict)
        # and the real-batch authorization lookup keep their stable codes;
        # everything else degrades to the exception type name.
        from core.web.services.team_workflow.challenge_cup_real_batch import (
            ChallengeCupRealBatchError,
        )

        reason = (
            str(getattr(exc, "code", "") or "")
            if isinstance(exc, (ResearchWorkflowError, ChallengeCupRealBatchError))
            else type(exc).__name__
        )
        _record_scene_event(
            "hypothesis_first.auto_formal_run",
            outcome="failed",
            level="warning",
            fields={
                "teamId": team_id,
                "questionId": str(question_id or "").strip().upper(),
                "reason": reason or type(exc).__name__,
                "error": str(exc)[:400],
            },
        )
        return {
            "status": "failed",
            "reason": reason or type(exc).__name__,
            "detail": str(exc)[:200],
        }



def auto_retry_blocked_formal_nodes(
    team_id: str,
    *,
    question_id: str,
) -> dict[str, Any]:
    """Auto-retry formal nodes blocked on the transient auto-advance gate.

    Budget-exhaustion auto-advance, step three.  A formal run that auto-starts
    one instant before the hypothesis review meeting closes lands blocked with
    ``auto_advance_not_ready`` — a condition the auto-advance loop itself
    resolves moments later, so the run must not wait for a human retry click.
    This helper enumerates the question's blocked formal runs (same
    ``list_runs`` read as ``_question_non_archived_formal_run_exists``), keeps
    only runs whose latest blocked ledger attempt carries exactly this
    transient code, and submits the retry through the identical offer-gated
    channel as the manual ``retry_formal_node`` action
    (``_submit_formal_v2_command``): the offer projection is re-read at submit
    time and its own ``offer:{runId}:{nodeId}:retry_node:...`` idempotency key
    is reused, so an offer that readiness still blocks (or a stale run
    version) ends as a structured wait and the next maintenance tick retries —
    readiness is never bypassed.  Best-effort: nothing raises; every outcome
    is counted and recorded as a scene event.
    """
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "blockedRuns": 0,
        "retried": 0,
        "skipped": 0,
        "ineligible": 0,
        "failed": 0,
    }
    try:
        from .formal_read_runtime import get_query_service

        payload = get_query_service().list_runs(
            team_id=team_id, workflow_id=CHALLENGE_CUP_WORKFLOW_ID
        )
    except Exception:  # noqa: BLE001 - formal runtime absent (command line)
        return summary
    from .runtime_factory import production_workflow_runtime

    runtime = production_workflow_runtime()
    if runtime is None:
        return summary
    blocked_runs = [
        run
        for run in list((payload or {}).get("runs") or [])
        if isinstance(run, Mapping)
        and str(run.get("questionId") or "").strip().upper()
        == normalized_question_id
        and str(run.get("status") or "").strip().lower() == "blocked"
    ]
    for run in blocked_runs:
        summary["blockedRuns"] += 1
        run_id = str(run.get("runId") or "").strip()
        if not run_id:
            continue
        try:
            target = _latest_auto_advance_blocked_attempt(runtime.store, run_id)
            if target is None:
                # Blocked on a real readiness gap or a human problem: the
                # auto-retry never touches this run.
                summary["ineligible"] += 1
                continue
            node_id, _problem = target
            _submit_formal_v2_command(
                team_id,
                run_id=run_id,
                node_id=node_id,
                command="retry_node",
                # Retry offers carry their own idempotency key and
                # _submit_formal_v2_command always submits with it; this
                # deterministic value only satisfies the signature.
                idempotency_key=f"hf2:auto-retry:{run_id}:{node_id}",
            )
        except HypothesisFirstChainError as exc:
            # The offer gate kept the retry out: readiness still blocks the
            # offer or the run version moved on.  Wait for the next tick.
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_formal_node",
                outcome="waited_for_offer",
                fields={
                    "teamId": team_id,
                    "questionId": normalized_question_id,
                    "runId": run_id,
                    "reason": str(exc)[:200],
                },
            )
        except Exception as exc:  # noqa: BLE001 - one broken run is isolated
            summary["failed"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_formal_node",
                outcome="failed",
                level="warning",
                fields={
                    "teamId": team_id,
                    "questionId": normalized_question_id,
                    "runId": run_id,
                    "reason": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
        else:
            summary["retried"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_formal_node",
                outcome="submitted",
                fields={
                    "teamId": team_id,
                    "questionId": normalized_question_id,
                    "runId": run_id,
                    "nodeId": node_id,
                },
            )
    return summary



def auto_extend_budget_blocked_nodes(
    team_id: str,
    *,
    question_id: str,
) -> dict[str, Any]:
    """Auto-recover budget-precheck blocks: extend_budget then retry_node.

    Budget-precheck auto-recovery, step two-six (before the transient
    ``auto_advance_not_ready`` retry).  A blocked run whose latest node
    attempt carries the structured ``budget_precheck_insufficient`` problem
    is machine-recoverable when a positive ``suggestedExtensionTokens``
    exists: this helper extends the stage limit by exactly the stored
    suggestion (same overrun-aware baseline ``max(stageLimitTokens,
    stageConsumedTokens) + suggested`` as the operator's one-click inbox CTA)
    and then submits the retry through the same command service the manual
    clicks reach — never a second write path, never an invented amount.

    Bounded and idempotent: at most
    ``auto_budget_recovery_max_extensions()`` automated extensions per
    blocked node (counted from the ``recovery_records`` audit trail this
    step writes, so the cap survives restarts); a manual extension is
    detected from ``safety_limits_json`` and the step then only retries;
    deterministic idempotency keys make replays converge; once the cap is
    spent the existing human-visible stop is left intact and a decline
    ``recovery_record`` states why (never an ``open`` record — those are
    readiness blockers).  Both formal runs and knowledge sideflow child runs
    are covered (the stalled run was a child).  Best-effort: nothing raises;
    every outcome is counted and, when it acts, recorded as a scene event.
    """

    from .budget_stage_admission import (
        auto_budget_recovery_enabled,
        auto_budget_recovery_max_extensions,
    )

    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "blockedRuns": 0,
        "extended": 0,
        "retried": 0,
        "declined": 0,
        "skipped": 0,
        "ineligible": 0,
        "failed": 0,
    }
    if not auto_budget_recovery_enabled():
        return summary
    if not normalized_question_id:
        return summary
    try:
        from .formal_read_runtime import get_query_service

        blocked_runs: list[dict[str, Any]] = []
        seen_run_ids: set[str] = set()
        for workflow_id in (CHALLENGE_CUP_WORKFLOW_ID, KNOWLEDGE_SIDEFLOW_WORKFLOW_ID):
            payload = get_query_service().list_runs(
                team_id=team_id, workflow_id=workflow_id
            )
            for run in list((payload or {}).get("runs") or []):
                if not isinstance(run, Mapping):
                    continue
                if (
                    str(run.get("questionId") or "").strip().upper()
                    != normalized_question_id
                    or str(run.get("status") or "").strip().lower() != "blocked"
                ):
                    continue
                run_id = str(run.get("runId") or "").strip()
                if run_id and run_id not in seen_run_ids:
                    seen_run_ids.add(run_id)
                    blocked_runs.append(dict(run))
    except Exception:  # noqa: BLE001 - formal runtime absent (command line)
        return summary
    from .runtime_factory import production_workflow_runtime

    runtime = production_workflow_runtime()
    if runtime is None:
        return summary

    from core.research.workflow.contracts import WorkflowCommandKind

    now_ms = int(time.time() * 1000)
    for run in blocked_runs:
        summary["blockedRuns"] += 1
        run_id = str(run.get("runId") or "").strip()
        if not run_id:
            continue
        try:
            target = _latest_budget_precheck_blocked_attempt(runtime.store, run_id)
            if target is None:
                summary["ineligible"] += 1
                continue
            node_id, attempt_no, problem = target
            stage_id = str(problem.get("stageId") or "").strip()
            stage_limit = int(problem.get("stageLimitTokens") or 0)
            consumed = int(problem.get("stageConsumedTokens") or 0)
            suggested = int(problem.get("suggestedExtensionTokens") or 0)
            current_run = runtime.store.get_run(run_id)
            if current_run is None:
                summary["ineligible"] += 1
                continue
            current_stage_limit = _run_stage_limit_override(current_run, stage_id)
            baseline = max(stage_limit, consumed if consumed > 0 else 0)
            new_stage_tokens = baseline + suggested
            extend_key = (
                f"auto-budget-recovery:{run_id}:{stage_id}"
                f":extend:{new_stage_tokens}"
            )
            retry_key = (
                f"auto-budget-recovery:{run_id}:{node_id}"
                f":retry_node:a{attempt_no}"
            )
            if current_stage_limit < new_stage_tokens:
                applied = _count_auto_budget_extensions(
                    runtime.store, run_id=run_id, node_id=node_id
                )
                cap = auto_budget_recovery_max_extensions()
                if applied >= cap:
                    # Cap spent: leave the human-visible stop intact and only
                    # record WHY the auto actor declines (deterministic id —
                    # one entry per blocked attempt, never a loop).
                    _record_auto_budget_recovery(
                        runtime.store,
                        run_id=run_id,
                        node_id=node_id,
                        attempt_no=attempt_no,
                        action="declined",
                        resolution={
                            "reason": "auto_extension_cap_exhausted",
                            "autoExtensionsApplied": applied,
                            "maxAutoExtensions": cap,
                            "suggestedExtensionTokens": suggested,
                            "newStageTokens": new_stage_tokens,
                            "recovery": "manual extend_budget + retry_node",
                        },
                        now_ms=now_ms,
                    )
                    summary["declined"] += 1
                    _record_scene_event(
                        "hypothesis_first.auto_budget_recovery",
                        outcome="declined",
                        fields={
                            "teamId": team_id,
                            "questionId": normalized_question_id,
                            "runId": run_id,
                            "nodeId": node_id,
                            "reason": "auto_extension_cap_exhausted",
                        },
                    )
                    continue
                outcome, reason = _submit_auto_budget_command(
                    runtime,
                    team_id=team_id,
                    run_id=run_id,
                    kind=WorkflowCommandKind.EXTEND_BUDGET,
                    node_id=None,
                    payload={
                        "limits": {"stageTokens": {stage_id: new_stage_tokens}},
                        "recovery": {
                            "command": "extend_budget",
                            "then": "retry_node",
                            "actor": AUTO_BUDGET_RECOVERY_ACTOR_ID,
                        },
                    },
                    idempotency_key=extend_key,
                )
                if outcome != "accepted":
                    summary["skipped" if outcome == "skipped" else "failed"] += 1
                    if outcome == "failed":
                        _record_scene_event(
                            "hypothesis_first.auto_budget_recovery",
                            outcome="failed",
                            level="warning",
                            fields={
                                "teamId": team_id,
                                "runId": run_id,
                                "nodeId": node_id,
                                "error": reason[:200],
                            },
                        )
                    continue
                summary["extended"] += 1
                _record_auto_budget_recovery(
                    runtime.store,
                    run_id=run_id,
                    node_id=node_id,
                    attempt_no=attempt_no,
                    action="auto_extend",
                    resolution={
                        "stageId": stage_id,
                        "newStageTokens": new_stage_tokens,
                        "suggestedExtensionTokens": suggested,
                        "idempotencyKey": extend_key,
                    },
                    now_ms=now_ms,
                )
                _record_scene_event(
                    "hypothesis_first.auto_budget_recovery",
                    outcome="extended",
                    fields={
                        "teamId": team_id,
                        "questionId": normalized_question_id,
                        "runId": run_id,
                        "nodeId": node_id,
                        "stageId": stage_id,
                        "newStageTokens": new_stage_tokens,
                        "suggestedExtensionTokens": suggested,
                    },
                )
            # Extension already in place (manual click, or this step's earlier
            # hop): only the retry remains.  Deterministic per-attempt key —
            # a replayed submit is an idempotent replay, and once the retry
            # lands the blocked attempt goes stale so the key never fires
            # twice for the same attempt.
            outcome, _reason = _submit_auto_budget_command(
                runtime,
                team_id=team_id,
                run_id=run_id,
                kind=WorkflowCommandKind.RETRY_NODE,
                node_id=node_id,
                payload={},
                idempotency_key=retry_key,
            )
            if outcome == "accepted":
                summary["retried"] += 1
                _record_scene_event(
                    "hypothesis_first.auto_budget_recovery",
                    outcome="retried",
                    fields={
                        "teamId": team_id,
                        "questionId": normalized_question_id,
                        "runId": run_id,
                        "nodeId": node_id,
                    },
                )
            elif outcome == "skipped":
                summary["skipped"] += 1
            else:
                summary["failed"] += 1
        except Exception:  # noqa: BLE001 - one broken run is isolated
            summary["failed"] += 1
    return summary



def _auto_advance_sweep_budget_ms() -> int:
    """Configured wall-clock budget in ms for one sweep pass.

    A nonpositive or unparseable override falls back to the default, matching
    the digest-TTL env style. The budget bounds one pass without changing any
    per-question decision.
    """

    raw = str(os.environ.get(_AUTO_ADVANCE_SWEEP_BUDGET_ENV) or "").strip()
    if not raw:
        return DEFAULT_AUTO_ADVANCE_SWEEP_BUDGET_MS
    try:
        normalized = int(raw)
    except ValueError:
        return DEFAULT_AUTO_ADVANCE_SWEEP_BUDGET_MS
    if normalized <= 0:
        return DEFAULT_AUTO_ADVANCE_SWEEP_BUDGET_MS
    return normalized



def auto_redrive_fenced_review_meeting(
    team_id: str,
    *,
    question_id: str,
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Auto-execute the retry-review-dispatch recovery for one fenced review.

    Auto-advance step four.  A Challenge fence closes a review meeting whose
    discussion really produced citable speech (deadline cut, restart orphan);
    the V2 projection correctly offers ``retry_review_dispatch`` for that
    shape, but nothing executed the offer automatically, so the candidate
    waited for a human sweep.  This helper finds the question's fenced review
    meetings whose last bound round is still speech-bearing, resolves the
    dispatch identity, and re-dispatches through the exact same
    :func:`retry_review_dispatch` entry the manual command branch reaches —
    the attempt ledger supersedes the fenced attempt and a fresh meeting
    opens without burning the round budget.  Idempotent: a fenced meeting
    whose dispatch identity already has a newer attempt is never re-driven,
    and the queued attempt append is the single attempt authority.  Bounded:
    at most one meeting per call (one hop per sweep per question), capped by
    ``HARD_ROUND_LIMIT`` attempts per identity.  Best-effort: nothing raises;
    every outcome lands as a ``hypothesis_first.auto_redrive_fenced_review``
    scene event.  ``records`` optionally carries the ledger snapshot taken
    once per sweep pass so plan construction for many fenced meetings does
    not re-parse the whole chain file per meeting; the dispatch itself keeps
    reading fresh state.
    """

    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "fenced": 0,
        "redriven": 0,
        "skipped": 0,
        "failed": 0,
        "status": "skipped",
        "reason": "",
    }
    if not normalized_team_id or not normalized_question_id:
        summary["reason"] = "missing_identity"
        return summary
    meetings = [
        meeting
        for meeting in _question_meetings(normalized_team_id, normalized_question_id)
        if str(meeting.get("status") or "").strip().lower() == "closed"
        and _is_auto_recoverable_execution_stop(meeting)
    ]
    for meeting_index, meeting in enumerate(meetings):
        if meeting_index:
            time.sleep(_SWEEP_ITERATION_YIELD_SECONDS)
        summary["fenced"] += 1
        meeting_round_id = str(meeting.get("meetingRoundId") or "").strip()
        inflight_key = (normalized_team_id, meeting_round_id)
        inflight_token: object = object()
        if _FENCED_REVIEW_REDRIVE_INFLIGHT.setdefault(
            inflight_key, inflight_token
        ) is not inflight_token:
            summary["skipped"] += 1
            continue
        try:
            plan = _fenced_review_redrive_plan(
                normalized_team_id, meeting, records=records
            )
            if plan is None:
                summary["skipped"] += 1
                continue
            retry_review_dispatch(
                normalized_team_id,
                str(plan["selectionId"]),
                [str(item) for item in plan["candidateIds"]],
            )
        except HypothesisFirstChainError as exc:
            # Domain rejection (the meeting/selection moved between the read
            # and the dispatch): a structured wait, never an error.
            summary["skipped"] += 1
            summary["status"] = "skipped"
            summary["reason"] = str(exc)[:200]
            _record_scene_event(
                "hypothesis_first.auto_redrive_fenced_review",
                outcome="skipped",
                fields={
                    "teamId": normalized_team_id,
                    "questionId": normalized_question_id,
                    "meetingRoundId": meeting_round_id,
                    "reason": str(exc)[:200],
                },
            )
            continue
        except Exception as exc:  # noqa: BLE001 - one broken meeting is isolated
            summary["failed"] += 1
            summary["status"] = "failed"
            _record_scene_event(
                "hypothesis_first.auto_redrive_fenced_review",
                outcome="failed",
                level="warning",
                fields={
                    "teamId": normalized_team_id,
                    "questionId": normalized_question_id,
                    "meetingRoundId": meeting_round_id,
                    "reason": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
            continue
        else:
            summary["redriven"] += 1
            summary["status"] = "redriven"
            _record_scene_event(
                "hypothesis_first.auto_redrive_fenced_review",
                outcome="submitted",
                fields={
                    "teamId": normalized_team_id,
                    "questionId": normalized_question_id,
                    "meetingRoundId": meeting_round_id,
                    "selectionId": str(plan["selectionId"]),
                    "candidateIds": [str(item) for item in plan["candidateIds"]],
                    "roundIndex": int(plan["roundIndex"]),
                },
            )
            # One hop per sweep per question: the remaining fenced meetings
            # (if any) wait for the next tick.
            return summary
        finally:
            _FENCED_REVIEW_REDRIVE_INFLIGHT.pop(inflight_key, None)
    return summary



def auto_retry_fenced_generation_attempt(
    team_id: str,
    *,
    question_id: str,
) -> dict[str, Any]:
    """Auto-supersede and retry a fenced, digest-less generation attempt.

    Auto-advance step five.  A fenced candidate-generation meeting that
    produced no digest leaves the R1 chain with no candidates and no live
    attempt; the ``retry_generation`` offer exists but had no automatic
    executor.  This helper finds the question's fenced generation meetings
    with no digest artifact, then walks the exact internal path the
    ``retry_generation`` command branch reaches —
    :func:`resolve_stage_one_generation_launch` +
    :func:`open_candidate_generation_meeting` — so the owning service
    supersedes the terminal attempt and opens the fresh per-attempt meeting
    unchanged.  Idempotent: only the question's newest attempt is eligible,
    the attempt count is capped at ``HARD_ROUND_LIMIT``, and a meeting that
    already produced a digest is never touched.  At most one retry per call.
    Best-effort: nothing raises; every outcome lands as a
    ``hypothesis_first.auto_retry_closed_generation`` scene event.
    """

    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "fenced": 0,
        "retried": 0,
        "skipped": 0,
        "failed": 0,
        "status": "skipped",
        "reason": "",
    }
    if not normalized_team_id or not normalized_question_id:
        summary["reason"] = "missing_identity"
        return summary
    meetings = [
        meeting
        for meeting in _question_generation_meetings(
            normalized_team_id, normalized_question_id
        )
        if str(meeting.get("status") or "").strip().lower() == "closed"
        and _is_auto_recoverable_execution_stop(meeting)
    ]
    for meeting_index, meeting in enumerate(meetings):
        if meeting_index:
            time.sleep(_SWEEP_ITERATION_YIELD_SECONDS)
        summary["fenced"] += 1
        meeting_round_id = str(meeting.get("meetingRoundId") or "").strip()
        inflight_key = (normalized_team_id, meeting_round_id)
        inflight_token: object = object()
        if _CLOSED_GENERATION_RETRY_INFLIGHT.setdefault(
            inflight_key, inflight_token
        ) is not inflight_token:
            summary["skipped"] += 1
            continue
        try:
            if not _fenced_generation_retry_plan(
                normalized_team_id, meeting, question_id=normalized_question_id
            ):
                summary["skipped"] += 1
                continue
            launch = resolve_stage_one_generation_launch(
                normalized_team_id,
                normalized_question_id,
                _meeting_workflow_run_id(meeting),
            )
            open_candidate_generation_meeting(
                normalized_team_id,
                normalized_question_id,
                _model_invocation_receipt_authority=launch.get("receipt_authority"),
                _discussion_scope=launch.get("discussion_scope"),
                _candidate_authority=str(launch.get("candidate_authority") or ""),
                _generation_context=launch.get("generation_context"),
            )
        except HypothesisFirstChainError as exc:
            # Domain rejection (context blocked, scope moved): a structured
            # wait for the next tick, never an error.
            summary["skipped"] += 1
            summary["status"] = "skipped"
            summary["reason"] = str(exc)[:200]
            _record_scene_event(
                "hypothesis_first.auto_retry_closed_generation",
                outcome="skipped",
                fields={
                    "teamId": normalized_team_id,
                    "questionId": normalized_question_id,
                    "meetingRoundId": meeting_round_id,
                    "reason": str(exc)[:200],
                },
            )
            continue
        except Exception as exc:  # noqa: BLE001 - one broken meeting is isolated
            summary["failed"] += 1
            summary["status"] = "failed"
            _record_scene_event(
                "hypothesis_first.auto_retry_closed_generation",
                outcome="failed",
                level="warning",
                fields={
                    "teamId": normalized_team_id,
                    "questionId": normalized_question_id,
                    "meetingRoundId": meeting_round_id,
                    "reason": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
            continue
        else:
            summary["retried"] += 1
            summary["status"] = "retried"
            _record_scene_event(
                "hypothesis_first.auto_retry_closed_generation",
                outcome="submitted",
                fields={
                    "teamId": normalized_team_id,
                    "questionId": normalized_question_id,
                    "meetingRoundId": meeting_round_id,
                },
            )
            # One retry per sweep per question.
            return summary
        finally:
            _CLOSED_GENERATION_RETRY_INFLIGHT.pop(inflight_key, None)
    return summary



def _auto_approve_digest_ttl_ms() -> int:
    """Configured digest auto-approve wait in ms.

    ``0`` (the default) means no human window: the next sweep tick approves
    a landed digest immediately.  A positive env override is a manual wait
    and is clamped up to ``AUTO_APPROVE_DIGEST_TTL_MIN_MS`` so it stays an
    operationally meaningful window; a negative or unparseable override
    falls back to the default.
    """

    raw = str(os.environ.get(_AUTO_APPROVE_DIGEST_TTL_OVERRIDE_ENV) or "").strip()
    if not raw:
        return DEFAULT_AUTO_APPROVE_DIGEST_TTL_MS
    try:
        normalized = int(raw)
    except ValueError:
        return DEFAULT_AUTO_APPROVE_DIGEST_TTL_MS
    if normalized < 0:
        return DEFAULT_AUTO_APPROVE_DIGEST_TTL_MS
    if normalized == 0:
        # Explicit "no human window" — legal and identical to the default.
        return 0
    return max(normalized, AUTO_APPROVE_DIGEST_TTL_MIN_MS)



def _auto_regen_round_grace_ms() -> int:
    """Configured missing-round grace; the env override is clamped to >=0."""

    raw = str(os.environ.get(_AUTO_REGEN_ROUND_GRACE_OVERRIDE_ENV) or "").strip()
    if raw:
        try:
            normalized = int(raw)
        except ValueError:
            normalized = -1
        if normalized >= 0:
            return normalized
    return DEFAULT_AUTO_REGEN_ROUND_GRACE_MS



def _auto_retry_handoff_grace_ms() -> int:
    """Configured zombie-handoff grace; the env override is clamped to >=10s."""

    raw = str(os.environ.get(_AUTO_RETRY_HANDOFF_GRACE_OVERRIDE_ENV) or "").strip()
    if raw:
        try:
            normalized = int(raw)
        except ValueError:
            normalized = 0
        if normalized > 0:
            return max(normalized, AUTO_RETRY_HANDOFF_GRACE_MIN_MS)
    return DEFAULT_AUTO_RETRY_HANDOFF_GRACE_MS



def auto_approve_awaiting_review_digests(
    team_id: str,
    *,
    question_id: str,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Auto-approve stale meeting digests (auto-advance step zero).

    The digest approval is the last per-round human gate of the
    hypothesis-first chain: every round parks at ``awaiting_approval`` once
    the digest draft lands and waits for the ``approve_summary`` command.
    This helper removes that wait by resolving it exactly the way the manual
    command resolves it — it calls the same ``approve_meeting_digest`` domain
    implementation the ``approve_summary`` command branch reaches (review
    rounds close through the review closure chain, candidate-generation
    rounds through the generation closure chain), with a type-specific
    system identity as ``closed_by`` so the persisted decisions carry
    ``decidedBy=system:auto-approve:review-digest`` /
    ``decidedBy=system:auto-approve:generation-digest`` and every standard
    closure effect (request_new_evidence collection, fan-in round, deferred
    next review, candidate registration) runs unchanged through the owning
    services.

    Eligibility is strict, per meeting: one of the digest-carrying types
    (``AUTO_APPROVE_DIGEST_MEETING_TYPES``), status ``awaiting_approval``
    for this question, a real digest draft (a non-empty
    ``summaryDraftError`` or a missing draft is a failure state that
    belongs to the stuck-digest recovery, never to an approval), and an
    ``updatedAt`` at least as old as the configured TTL — which is 0 by
    default (no human window: the landed digest is approved on this very
    sweep pass).  A candidate-generation digest additionally must pass a
    quality gate before the automatic approval: zero ``validationErrors``
    and at least one proposed candidate.  A generation draft that fails
    the gate keeps its human gate and emits a reminder scene event
    instead of being silently skipped.  No offer/idempotency layer is
    re-invented: the closure is idempotent on its closure hash and a
    meeting that closed in the
    meantime is rejected by the domain status assertion, so a replay can
    never approve twice.

    Best-effort like every auto-advance helper: nothing raises, each meeting
    is isolated, and every outcome lands as a
    ``hypothesis_first.auto_approve_review_digest`` scene event.
    """
    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "awaitingApproval": 0,
        "approved": 0,
        "reused": 0,
        "skipped": 0,
        "failed": 0,
    }
    if not normalized_team_id or not normalized_question_id:
        return summary
    try:
        from core.web.services.team_workflow import meeting_rounds

        meetings = list(
            meeting_rounds.list_meeting_rounds(
                normalized_team_id, status="awaiting_approval", read_only=True
            )["meetings"]
        )
    except Exception:  # noqa: BLE001 - enumeration outages stay invisible
        return summary
    now_value = int(now_ms if now_ms is not None else time.time() * 1000)
    ttl_ms = _auto_approve_digest_ttl_ms()
    for meeting in meetings:
        if not isinstance(meeting, Mapping):
            continue
        meeting_type = str(meeting.get("meetingType") or "").strip().lower()
        if meeting_type not in AUTO_APPROVE_DIGEST_MEETING_TYPES:
            # Only the two digest-carrying round types own the digest
            # approval gate; other meeting types keep their own lifecycle
            # owners.
            continue
        if (
            str(meeting.get("question") or "").strip().upper()
            != normalized_question_id
        ):
            continue
        summary["awaitingApproval"] += 1
        meeting_round_id = str(meeting.get("meetingRoundId") or "").strip()
        closed_by = (
            AUTO_APPROVE_GENERATION_DIGEST_CLOSED_BY
            if meeting_type == CANDIDATE_GENERATION_MEETING_TYPE
            else AUTO_APPROVE_REVIEW_DIGEST_CLOSED_BY
        )
        fields = {
            "teamId": normalized_team_id,
            "questionId": normalized_question_id,
            "meetingRoundId": meeting_round_id,
            "ttlMs": ttl_ms,
        }
        draft = (
            dict(meeting.get("digestDraft"))
            if isinstance(meeting.get("digestDraft"), Mapping)
            else {}
        )
        content_hash = str(draft.get("contentHash") or "").strip()
        block_reason = _digest_auto_approval_block_reason(meeting)
        if block_reason:
            # The shared quality gate refused the digest: the human gate
            # stays (the awaiting-approval reaper owns escalation for the
            # stuck shape), and a reminder event keeps the wait auditable.
            summary["skipped"] += 1
            extra_fields: dict[str, Any] = {}
            event_level = "info"
            if block_reason.startswith("candgen_digest_"):
                validation_errors = [
                    item
                    for item in list(draft.get("validationErrors") or [])
                    if isinstance(item, Mapping)
                ]
                proposals = [
                    item
                    for item in list(draft.get("proposedCandidates") or [])
                    if isinstance(item, Mapping)
                ]
                extra_fields = {
                    "validationErrorCount": len(validation_errors),
                    "proposedCandidateCount": len(proposals),
                    "reminder": (
                        "candgen digest awaits manual approval: the "
                        "auto-approve quality gate did not pass"
                    ),
                }
                event_level = "warning"
            _record_scene_event(
                "hypothesis_first.auto_approve_review_digest",
                outcome="skipped",
                level=event_level,
                fields={**fields, "reason": block_reason, **extra_fields},
            )
            continue
        updated_at_ms = _iso_timestamp_ms(meeting.get("updatedAt"))
        if updated_at_ms is None:
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_approve_review_digest",
                outcome="skipped",
                fields={**fields, "reason": "unreadable_updated_at"},
            )
            continue
        digest_age_ms = max(now_value - updated_at_ms, 0)
        if digest_age_ms < ttl_ms:
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_approve_review_digest",
                outcome="skipped",
                fields={
                    **fields,
                    "digestAgeMs": digest_age_ms,
                    "reason": "within_ttl",
                },
            )
            continue
        try:
            result = approve_meeting_digest(
                normalized_team_id,
                meeting_round_id,
                closed_by=closed_by,
                expected_digest_content_hash=content_hash,
            )
        except HypothesisFirstChainError as exc:
            # The domain gate kept the approval out (status moved on, digest
            # regenerated between the read and the approve): a structured
            # wait, never an error — the next tick re-reads fresh state.
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_approve_review_digest",
                outcome="skipped",
                fields={
                    **fields,
                    "digestAgeMs": digest_age_ms,
                    "reason": str(exc)[:200],
                },
            )
        except Exception as exc:  # noqa: BLE001 - one broken meeting is isolated
            summary["failed"] += 1
            _record_scene_event(
                "hypothesis_first.auto_approve_review_digest",
                outcome="failed",
                level="warning",
                fields={
                    **fields,
                    "digestAgeMs": digest_age_ms,
                    "reason": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
        else:
            status = str(result.get("status") or "")
            if status == "awaiting_approval":
                # Every drafted evidence request failed validation, so the
                # digest cannot close as-is: regenerate/human owns it now.
                summary["skipped"] += 1
                _record_scene_event(
                    "hypothesis_first.auto_approve_review_digest",
                    outcome="skipped",
                    fields={
                        **fields,
                        "digestAgeMs": digest_age_ms,
                        "reason": "digest_requests_invalid",
                    },
                )
            elif status in {"created", "reused"}:
                summary["approved" if status == "created" else "reused"] += 1
                _record_scene_event(
                    "hypothesis_first.auto_approve_review_digest",
                    outcome="approved" if status == "created" else "reused",
                    fields={
                        **fields,
                        "digestAgeMs": digest_age_ms,
                        "closedBy": closed_by,
                        "meetingType": meeting_type,
                        # Deterministic identity of the automatic approval
                        # (no timestamps): meetingRoundId + TTL semantics.
                        "rationale": (
                            "auto-approve: digest awaited beyond ttl "
                            f"({ttl_ms} ms, type {meeting_type}); meeting "
                            f"{meeting_round_id} approved with the standard "
                            "closure chain per auto-advance policy"
                        ),
                    },
                )
            else:
                summary["skipped"] += 1
                _record_scene_event(
                    "hypothesis_first.auto_approve_review_digest",
                    outcome="skipped",
                    fields={
                        **fields,
                        "digestAgeMs": digest_age_ms,
                        "reason": "unexpected_status",
                    },
                )
    return summary



def _auto_regenerate_failure_budget_exhausted(
    team_id: str,
    *,
    selection_id: str,
    round_index: int | None,
) -> bool:
    """True when the automatic regeneration budget for one failure is spent.

    The synchronous close-time generation and the auto-advance sweep share
    one failing identity; without this bound the sweep re-attempted the same
    deterministic failure every pass (SCI-024: 255 identical "requires a
    non-empty claim" traces over 15 hours).  Failures recorded with
    ``trigger=auto_advance`` count against ``AUTO_REGENERATE_FAILURE_RETRY_
    BUDGET``; the operator command path never counts and always stays open.
    Unreadable ledgers resolve to False: the sweep keeps its previous
    behavior instead of losing recovery over a read hiccup.
    """

    normalized_selection_id = str(selection_id or "").strip()
    if not normalized_selection_id:
        return False
    try:
        from core.web.services.team_workflow import hypothesis_rounds

        listing = hypothesis_rounds.list_hypothesis_round_failures(
            team_id, unresolved_only=True
        )
    except Exception:  # noqa: BLE001 - a read hiccup never blocks recovery
        return False
    count = 0
    for record in list(listing.get("failures") or []):
        if not isinstance(record, Mapping):
            continue
        if str(record.get("status") or "") != "failed":
            continue
        if str(record.get("trigger") or "") != "auto_advance":
            continue
        if (
            str(record.get("selectionId") or "").strip()
            != normalized_selection_id
        ):
            continue
        if round_index is not None and record.get("roundIndex") is not None:
            try:
                if int(record.get("roundIndex")) != int(round_index):
                    continue
            except (TypeError, ValueError):
                continue
        count += 1
    return count >= AUTO_REGENERATE_FAILURE_RETRY_BUDGET



def auto_regenerate_missing_hypothesis_round(
    team_id: str,
    *,
    question_id: str,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Regenerate a HypothesisRound the closure fan-in never landed.

    Auto-advance step between digest approval and adjudication.  The live
    break this closes: :func:`close_review_meeting` persists the meeting
    ``closed`` and only then runs the selection-level round generation
    synchronously through the review LLMs; when that call times out, the
    closure artifacts stand but the round never lands — and with no round,
    no adjudication or convergence gate can ever fire, so the chain
    dead-waits forever.  Detection and action per selection chain: see
    :func:`_missing_round_plans_for_question`; the action reuses the
    existing :func:`regenerate_hypothesis_round` command path unchanged
    (all of its domain assertions and runner resolution stay authoritative),
    so a fan-in that judges siblings unready and an already-stored round are
    domain rejections, not errors.

    Result semantics: ``created`` (a round landed), ``skipped`` (guarded or
    domain-rejected; ``reason`` says which), ``failed`` (generation failed —
    automatically re-attempted up to ``AUTO_REGENERATE_FAILURE_RETRY_BUDGET``
    times, then left to the operator command).  Best-effort like every
    auto-advance helper: nothing raises and every outcome lands as a
    ``hypothesis_first.auto_regenerate_round`` scene event.  An in-process
    inflight marker keyed by ``(teamId, questionId)`` keeps a slow
    regeneration (the review-LLM budget is minutes against a 30s sweep
    interval) from being double-triggered for the same question.
    """
    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "status": "skipped",
        "reason": "",
        "created": 0,
        "skipped": 0,
        "failed": 0,
    }
    if not normalized_team_id or not normalized_question_id:
        summary["reason"] = "missing_identity"
        return summary
    inflight_key = (normalized_team_id, normalized_question_id)
    inflight_token: object = object()
    if _ROUND_REGEN_INFLIGHT.setdefault(inflight_key, inflight_token) is not (
        inflight_token
    ):
        return {
            "status": "skipped",
            "reason": "already_in_flight",
            "created": 0,
            "skipped": 0,
            "failed": 0,
        }
    try:
        now_value = int(now_ms if now_ms is not None else time.time() * 1000)
        grace_ms = _auto_regen_round_grace_ms()
        try:
            plans = _missing_round_plans_for_question(
                normalized_team_id,
                question_id=normalized_question_id,
                now_ms=now_value,
                grace_ms=grace_ms,
            )
        except Exception as exc:  # noqa: BLE001 - detection stays best-effort
            summary["status"] = "failed"
            summary["reason"] = "detection_failed"
            summary["error"] = str(exc)[:400]
            _record_scene_event(
                "hypothesis_first.auto_regenerate_round",
                outcome="failed",
                level="warning",
                fields={
                    "teamId": normalized_team_id,
                    "questionId": normalized_question_id,
                    "reason": "detection_failed",
                    "errorType": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
            return summary
        decisive: dict[str, Any] | None = None
        for plan in plans:
            fields = {
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "selectionId": str(plan.get("selectionId") or ""),
                "roundIndex": plan.get("roundIndex"),
                "graceMs": grace_ms,
            }
            if str(plan.get("status") or "") != "planned":
                summary["skipped"] += 1
                if decisive is None or decisive.get("status") == "skipped":
                    decisive = {
                        "status": "skipped",
                        "reason": str(plan.get("reason") or "unknown"),
                    }
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="skipped",
                    fields={**fields, "reason": str(plan.get("reason") or "")},
                )
                continue
            trigger_meeting_id = str(plan.get("triggerMeetingRoundId") or "").strip()
            plan_fields = {
                **fields,
                "meetingRoundId": trigger_meeting_id,
                "meetingRoundIds": list(plan.get("meetingRoundIds") or []),
            }
            if _auto_regenerate_failure_budget_exhausted(
                normalized_team_id,
                selection_id=str(plan.get("selectionId") or ""),
                round_index=plan.get("roundIndex"),
            ):
                summary["skipped"] += 1
                if decisive is None or decisive.get("status") == "skipped":
                    decisive = {
                        "status": "skipped",
                        "reason": "auto_retry_budget_exhausted",
                    }
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="skipped",
                    fields={
                        **plan_fields,
                        "reason": "auto_retry_budget_exhausted",
                    },
                )
                continue
            try:
                result = regenerate_hypothesis_round(
                    normalized_team_id,
                    trigger_meeting_id,
                    trigger="auto_advance",
                )
            except HypothesisFirstChainError as exc:
                # Domain rejection (the meeting moved, the closure state
                # disagrees): a structured wait, never an error.
                summary["skipped"] += 1
                if decisive is None:
                    decisive = {"status": "skipped", "reason": str(exc)[:200]}
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="skipped",
                    fields={**plan_fields, "reason": str(exc)[:200]},
                )
                continue
            except Exception as exc:  # noqa: BLE001 - one plan is isolated
                summary["failed"] += 1
                if decisive is None or decisive.get("status") != "created":
                    decisive = {
                        "status": "failed",
                        "reason": type(exc).__name__,
                        "error": str(exc)[:400],
                    }
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="failed",
                    level="warning",
                    fields={
                        **plan_fields,
                        "reason": type(exc).__name__,
                        "error": str(exc)[:400],
                    },
                )
                continue
            result_status = str(result.get("status") or "")
            if result_status == "created":
                round_record = (
                    result.get("round")
                    if isinstance(result.get("round"), Mapping)
                    else {}
                )
                summary["created"] += 1
                decisive = {
                    "status": "created",
                    "reason": "round_generated",
                    "roundId": str(round_record.get("roundId") or ""),
                }
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="created",
                    fields={
                        **plan_fields,
                        "roundId": str(round_record.get("roundId") or ""),
                    },
                )
            elif result_status == "reused":
                # The stored round predated detection (or a concurrent winner
                # landed it): the chain has its round either way.
                summary["skipped"] += 1
                decisive = {"status": "skipped", "reason": "round_reused"}
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="skipped",
                    fields={**plan_fields, "reason": "round_reused"},
                )
            elif result_status in {
                "waiting_for_sibling_reviews",
                "generation_in_progress",
            }:
                # Fan-in authority says siblings are not ready, or another
                # trigger is generating the same round: wait for the next pass.
                summary["skipped"] += 1
                decisive = {"status": "skipped", "reason": result_status}
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="skipped",
                    fields={**plan_fields, "reason": result_status},
                )
                superseded_ids = list(result.get("supersededCandidateIds") or [])
                if result_status == "waiting_for_sibling_reviews" and superseded_ids:
                    # A superseded digest-less closing has no open meeting to
                    # close: the wait can only end by dispatching the review
                    # again, so recover it here (bounded) instead of waiting
                    # for a sibling close that can never happen.
                    redispatch = _auto_redispatch_superseded_reviews(
                        normalized_team_id,
                        selection_id=str(result.get("selectionId") or ""),
                        candidate_ids=superseded_ids,
                    )
                    summary["autoRedispatch"] = redispatch
                    _record_scene_event(
                        "hypothesis_first.auto_redispatch_superseded",
                        outcome=(
                            "redispatched"
                            if redispatch.get("redispatched")
                            else (
                                "failed"
                                if redispatch.get("failed")
                                else "exhausted"
                            )
                        ),
                        level=(
                            "warning"
                            if redispatch.get("failed")
                            else "info"
                        ),
                        fields={
                            **plan_fields,
                            "selectionId": str(result.get("selectionId") or ""),
                            "supersededCandidateIds": superseded_ids,
                            **redispatch,
                        },
                    )
            elif result_status == "failed":
                # The generation failure trace is already durable (the
                # hypothesis_round_failures ledger); the sweep re-attempts up
                # to AUTO_REGENERATE_FAILURE_RETRY_BUDGET times (checked at
                # the call site) and then keeps the operator hint.
                summary["failed"] += 1
                decisive = {
                    "status": "failed",
                    "reason": "generation_failed",
                    "error": str(result.get("error") or "")[:400],
                }
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="failed",
                    level="warning",
                    fields={
                        **plan_fields,
                        "reason": "generation_failed",
                        "errorType": str(result.get("errorType") or ""),
                        "error": str(result.get("error") or "")[:400],
                    },
                )
            else:
                summary["skipped"] += 1
                decisive = {
                    "status": "skipped",
                    "reason": f"unexpected_status:{result_status}",
                }
                _record_scene_event(
                    "hypothesis_first.auto_regenerate_round",
                    outcome="skipped",
                    fields={**plan_fields, "reason": "unexpected_status"},
                )
        if decisive is not None:
            summary.update(decisive)
        elif not plans:
            summary["reason"] = "no_review_links"
        return summary
    finally:
        if _ROUND_REGEN_INFLIGHT.get(inflight_key) is inflight_token:
            _ROUND_REGEN_INFLIGHT.pop(inflight_key, None)



def auto_backfill_missing_round_authorities(
    team_id: str,
    *,
    question_id: str,
) -> dict[str, Any]:
    """Re-materialize round authorities a first-write failure left behind.

    Auto-advance step between round regeneration and handoff retry.  The live
    break this closes: the closure path materializes ``dimension_reviews``
    (plus its sibling round authorities) exactly once per generated round, so
    a first-write failure — or a round generated by an older build — leaves a
    closed round with no canonical ``dimension_reviews`` authority forever.
    The stage-one ``result_package`` readiness gate then reports the generic
    ``result_package_incomplete`` while every retry is rejected as
    ``node_not_ready``: the round exists (the regen step's ``round_exists``
    guard skips it) and nothing ever re-ran the writer.  Detection is per
    stored round: a reusable (``reviewed``/``closed``) round whose scoped
    ``dimension_reviews`` artifact is absent.

    The action reuses :func:`regenerate_hypothesis_round` in ``replay_only``
    mode: review runners are never resolved (the reuse dedup cannot reach the
    executor, so a missing evaluator configuration can no longer reject the
    replay the way the formal runner fence did for live closed rounds), and a
    derived round id that no longer addresses a stored round surfaces as a
    structured ``replay_miss`` skip instead of ever degrading into a fresh
    budget-spending generation.  The full sibling authority batch (dimension
    reviews, review independence, feedback iterations, stage-one plan +
    competition alignment) re-runs through the production binding code.  A
    replay is only attempted when the trigger meeting's current fan-in group
    still equals the round's bound meeting set — a moved group would compute
    a different round id, which the replay-only guard then refuses anyway.
    A still-failing materialization stays fail-closed: the blocked authority
    is reported (never faked) and the next sweep pass retries naturally.
    Nothing here raises: one broken round is isolated and counted, and each
    non-trivial outcome lands as a
    ``hypothesis_first.auto_backfill_round_authorities`` scene event plus a
    ``logger.warning`` — the runtime scene sink is best-effort in production,
    so the log line is the durable observability trail for stuck rounds.
    """

    from core.web.services.team_workflow import hypothesis_rounds as _hypothesis_rounds

    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip()
    summary: dict[str, Any] = {
        "status": "skipped",
        "reason": "",
        "backfilled": 0,
        "skipped": 0,
        "failed": 0,
    }
    if not normalized_team_id or not normalized_question_id:
        summary["reason"] = "missing_identity"
        return summary
    try:
        rounds = [
            dict(item)
            for item in _question_hypothesis_rounds(
                normalized_team_id, normalized_question_id
            )
            if isinstance(item, Mapping)
        ]
    except Exception as exc:  # noqa: BLE001 - detection stays best-effort
        summary["reason"] = "detection_failed"
        summary["error"] = str(exc)[:400]
        return summary
    if not rounds:
        summary["reason"] = "no_rounds"
        return summary
    decisive: dict[str, Any] | None = None
    for round_record in rounds:
        round_id = str(round_record.get("roundId") or "").strip()
        round_status = str(round_record.get("status") or "").strip().lower()
        fields = {
            "teamId": normalized_team_id,
            "questionId": normalized_question_id,
            "roundId": round_id,
            "roundStatus": round_status,
        }
        if not round_id or round_status not in _hypothesis_rounds.REUSABLE_ROUND_STATUSES:
            summary["skipped"] += 1
            continue
        run_ids, bound_meetings = _round_authority_binding(
            normalized_team_id, round_record
        )
        if not bound_meetings:
            summary["skipped"] += 1
            if decisive is None:
                decisive = {"status": "skipped", "reason": "round_meetings_unreadable"}
            continue
        missing = not _round_has_dimension_reviews_authority(
            normalized_team_id, round_id, run_ids
        )
        if not missing:
            summary["skipped"] += 1
            continue
        closed_meetings = [
            meeting
            for meeting in bound_meetings
            if str(meeting.get("status") or "").strip().lower() == "closed"
            and str(meeting.get("meetingType") or "")
            == HYPOTHESIS_REVIEW_MEETING_TYPE
        ]
        if not closed_meetings:
            summary["skipped"] += 1
            if decisive is None:
                decisive = {"status": "skipped", "reason": "round_meetings_not_closed"}
            continue
        trigger = closed_meetings[-1]
        trigger_id = str(trigger.get("meetingRoundId") or "").strip()
        plan_fields = {**fields, "meetingRoundId": trigger_id}
        # Group-identity guard: replay only when the trigger meeting's current
        # fan-in group still resolves to exactly the round's bound meeting
        # set.  A moved group would address a different round id and fall
        # through the reuse dedup into a fresh (budget-spending) generation.
        try:
            fan_in = _review_meeting_fan_in_group(normalized_team_id, trigger)
        except Exception as exc:  # noqa: BLE001 - domain rejection stays a skip
            summary["skipped"] += 1
            if decisive is None:
                decisive = {"status": "skipped", "reason": "fan_in_unreadable"}
            logger.warning(
                "hypothesis_first.auto_backfill_round_authorities skipped "
                "(fan_in_unreadable): team=%s question=%s round=%s trigger=%s "
                "error=%s",
                normalized_team_id,
                normalized_question_id,
                round_id,
                str(trigger.get("meetingRoundId") or ""),
                str(exc)[:200],
            )
            _record_scene_event(
                "hypothesis_first.auto_backfill_round_authorities",
                outcome="skipped",
                fields={**plan_fields, "reason": str(exc)[:200]},
            )
            continue
        fan_in_meeting_ids = {
            str(item.get("meetingRoundId") or "").strip()
            for item in list(fan_in.get("meetings") or [])
            if isinstance(item, Mapping)
        }
        if str(fan_in.get("status") or "") != "ready" or fan_in_meeting_ids != set(
            _round_refs_meeting_ids(round_record)
        ):
            summary["skipped"] += 1
            if decisive is None:
                decisive = {"status": "skipped", "reason": "fan_in_group_moved"}
            logger.warning(
                "hypothesis_first.auto_backfill_round_authorities skipped "
                "(fan_in_group_moved): team=%s question=%s round=%s trigger=%s",
                normalized_team_id,
                normalized_question_id,
                round_id,
                trigger_id,
            )
            _record_scene_event(
                "hypothesis_first.auto_backfill_round_authorities",
                outcome="skipped",
                fields={**plan_fields, "reason": "fan_in_group_moved"},
            )
            continue
        try:
            result = regenerate_hypothesis_round(
                normalized_team_id, trigger_id, replay_only=True
            )
        except HypothesisFirstChainError as exc:
            summary["skipped"] += 1
            if decisive is None:
                decisive = {"status": "skipped", "reason": str(exc)[:200]}
            logger.warning(
                "hypothesis_first.auto_backfill_round_authorities skipped "
                "(domain rejection): team=%s question=%s round=%s trigger=%s "
                "reason=%s",
                normalized_team_id,
                normalized_question_id,
                round_id,
                trigger_id,
                str(exc)[:200],
            )
            _record_scene_event(
                "hypothesis_first.auto_backfill_round_authorities",
                outcome="skipped",
                fields={**plan_fields, "reason": str(exc)[:200]},
            )
            continue
        except Exception as exc:  # noqa: BLE001 - one round is isolated
            summary["failed"] += 1
            decisive = {
                "status": "failed",
                "reason": type(exc).__name__,
                "error": str(exc)[:400],
            }
            logger.warning(
                "hypothesis_first.auto_backfill_round_authorities failed "
                "(%s): team=%s question=%s round=%s trigger=%s error=%s",
                type(exc).__name__,
                normalized_team_id,
                normalized_question_id,
                round_id,
                trigger_id,
                str(exc)[:400],
            )
            _record_scene_event(
                "hypothesis_first.auto_backfill_round_authorities",
                outcome="failed",
                level="warning",
                fields={**plan_fields, "reason": type(exc).__name__},
            )
            continue
        result_status = str(result.get("status") or "")
        if result_status not in {"created", "reused"}:
            summary["skipped"] += 1
            if decisive is None:
                decisive = {
                    "status": "skipped",
                    "reason": result_status or "unexpected_status",
                }
            if result_status == "replay_miss":
                # The stored round is no longer addressable from this
                # meeting's current fan-in identity; the replay-only guard
                # refused before any executor work (zero review budget).
                logger.warning(
                    "hypothesis_first.auto_backfill_round_authorities skipped "
                    "(replay_miss): team=%s question=%s round=%s trigger=%s "
                    "derivedRoundId=%s",
                    normalized_team_id,
                    normalized_question_id,
                    round_id,
                    trigger_id,
                    str(result.get("roundId") or ""),
                )
            _record_scene_event(
                "hypothesis_first.auto_backfill_round_authorities",
                outcome="skipped",
                fields={**plan_fields, "reason": result_status or "unexpected_status"},
            )
            continue
        dimension_authority = (
            result.get("dimensionReviewsAuthority")
            if isinstance(result.get("dimensionReviewsAuthority"), Mapping)
            else {}
        )
        if str(dimension_authority.get("status") or "") != "written":
            # Fail-closed: the writer refused (or persisted nothing) and the
            # blocked authority must stay visible instead of being faked.
            blocker_codes = list(dimension_authority.get("blockerCodes") or [])
            summary["failed"] += 1
            decisive = {
                "status": "failed",
                "reason": "authority_still_blocked",
                "blockerCodes": blocker_codes,
            }
            logger.warning(
                "hypothesis_first.auto_backfill_round_authorities failed "
                "(authority_still_blocked): team=%s question=%s round=%s "
                "trigger=%s blockers=%s",
                normalized_team_id,
                normalized_question_id,
                round_id,
                trigger_id,
                blocker_codes,
            )
            _record_scene_event(
                "hypothesis_first.auto_backfill_round_authorities",
                outcome="failed",
                level="warning",
                fields={
                    **plan_fields,
                    "reason": "authority_still_blocked",
                    "blockerCodes": blocker_codes,
                },
            )
            continue
        summary["backfilled"] += 1
        decisive = {
            "status": "backfilled",
            "reason": "authority_backfilled",
            "roundId": round_id,
        }
        _record_scene_event(
            "hypothesis_first.auto_backfill_round_authorities",
            outcome="backfilled",
            fields={**plan_fields, "authorityRunIds": list(run_ids)},
        )
    if decisive is not None:
        summary.update(decisive)
    return summary



def auto_backfill_missing_feedback_iterations(
    team_id: str,
    *,
    question_id: str,
) -> dict[str, Any]:
    """Sweep step: backfill feedback-iteration authority for blocked runs.

    Auto-advance step after ``auto_backfill_missing_round_authorities``.  A
    blocked (or failed) formal run whose authority carries zero canonical
    ``feedback_iterations`` artifacts fails result packaging with ``canonical
    feedback_iterations contains no actual revision`` forever, even though the
    question's hypothesis-review round chain holds a complete, truthful
    revision lineage.  Discovery mirrors the blocked-run scan of
    :func:`auto_retry_blocked_formal_nodes`; the authority and the run's
    hypothesis-stage node attempt come straight from the workflow ledger, and
    the write goes through
    :func:`backfill_feedback_iterations_from_round_chain` (fail-closed,
    idempotent — a second pass replays byte-identical evidence and writes
    nothing new).  A blocked outcome is memoized per run against the round
    chain fingerprint for a bounded TTL: the per-second recovery sweep must
    not grind the ledger with identical failed attempts and warning spam.
    Nothing here raises: one broken run is isolated and every
    non-trivial outcome lands as a
    ``hypothesis_first.auto_backfill_feedback_iterations`` scene event plus a
    ``logger.warning``.
    """

    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "status": "skipped",
        "reason": "",
        "written": 0,
        "blocked": 0,
        "skipped": 0,
        "failed": 0,
        "runs": [],
    }
    if not normalized_team_id or not normalized_question_id:
        summary["reason"] = "missing_identity"
        return summary
    try:
        from .formal_read_runtime import get_query_service

        payload = get_query_service().list_runs(
            team_id=normalized_team_id, workflow_id=CHALLENGE_CUP_WORKFLOW_ID
        )
    except Exception:  # noqa: BLE001 - formal runtime absent (command line)
        summary["reason"] = "formal_runtime_unavailable"
        return summary
    target_runs = [
        run
        for run in list((payload or {}).get("runs") or [])
        if isinstance(run, Mapping)
        and str(run.get("questionId") or "").strip().upper()
        == normalized_question_id
        and str(run.get("status") or "").strip().lower()
        in FEEDBACK_ITERATION_BACKFILL_RUN_STATUSES
    ]
    if not target_runs:
        summary["reason"] = "no_target_formal_run"
        return summary
    from .runtime_factory import production_workflow_runtime

    runtime = production_workflow_runtime()
    if runtime is None:
        summary["reason"] = "formal_runtime_unavailable"
        return summary
    try:
        rounds = _question_hypothesis_rounds(
            normalized_team_id, normalized_question_id
        )
    except Exception as exc:  # noqa: BLE001 - one broken question is isolated
        summary["reason"] = "rounds_unreadable"
        summary["error"] = str(exc)[:400]
        return summary
    fingerprint = _feedback_iteration_rounds_fingerprint(rounds)
    store = runtime.store
    for run in target_runs:
        run_id = str(run.get("runId") or "").strip()
        if not run_id:
            summary["skipped"] += 1
            continue
        run_fields = {
            "teamId": normalized_team_id,
            "questionId": normalized_question_id,
            "runId": run_id,
        }
        if _feedback_iteration_backfill_recently_blocked(run_id, fingerprint):
            summary["skipped"] += 1
            summary["runs"].append(
                {
                    "runId": run_id,
                    "status": "skipped",
                    "reason": "blocked_backfill_recently_attempted",
                    "blockerCodes": [],
                    "rounds": 0,
                }
            )
            continue
        try:
            record = store.get_run(run_id)
            snapshot = json.loads(
                str(getattr(record, "input_snapshot_json", "") or "") or "{}"
            )
            source = (
                str(snapshot.get("sourceCollectionRunId") or "").strip()
                if isinstance(snapshot, Mapping)
                else ""
            )
            attempt = store.latest_attempt(run_id, "hypothesis_design")
            node_run_id = str(getattr(attempt, "node_run_id", "") or "").strip()
        except Exception as exc:  # noqa: BLE001 - one broken run is isolated
            summary["failed"] += 1
            summary["status"] = "failed"
            summary["runs"].append(
                {"runId": run_id, "status": "failed", "reason": type(exc).__name__}
            )
            logger.warning(
                "hypothesis_first.auto_backfill_feedback_iterations failed "
                "(run_record_unreadable): team=%s question=%s run=%s error=%s",
                normalized_team_id,
                normalized_question_id,
                run_id,
                str(exc)[:200],
            )
            _record_scene_event(
                "hypothesis_first.auto_backfill_feedback_iterations",
                outcome="failed",
                level="warning",
                fields={**run_fields, "reason": type(exc).__name__},
            )
            continue
        result = backfill_feedback_iterations_from_round_chain(
            team_id=normalized_team_id,
            workflow_run_id=run_id,
            question_id=normalized_question_id,
            source_collection_run_id=source,
            node_run_id=node_run_id,
            rounds=rounds,
        )
        result_status = str(result.get("status") or "")
        outcome: dict[str, Any] = {
            "runId": run_id,
            "status": result_status,
            "reason": str(result.get("reason") or ""),
            "blockerCodes": list(result.get("blockerCodes") or []),
            "rounds": int(result.get("rounds") or 0),
        }
        summary["runs"].append(outcome)
        if result_status == "written":
            _FEEDBACK_ITERATION_BACKFILL_BLOCKED_MEMO.pop(run_id, None)
            summary["written"] += int(result.get("written") or 0)
            summary["status"] = "written"
            _record_scene_event(
                "hypothesis_first.auto_backfill_feedback_iterations",
                outcome="backfilled",
                fields={
                    **run_fields,
                    "rounds": outcome["rounds"],
                    "sourceCollectionRunId": source,
                },
            )
        elif result_status == "blocked":
            _remember_feedback_iteration_backfill_blocked(run_id, fingerprint)
            summary["blocked"] += 1
            if summary["status"] != "written":
                summary["status"] = "blocked"
            summary["reason"] = outcome["reason"]
            logger.warning(
                "hypothesis_first.auto_backfill_feedback_iterations blocked: "
                "team=%s question=%s run=%s reason=%s blockers=%s",
                normalized_team_id,
                normalized_question_id,
                run_id,
                outcome["reason"],
                outcome["blockerCodes"],
            )
            _record_scene_event(
                "hypothesis_first.auto_backfill_feedback_iterations",
                outcome="blocked",
                level="warning",
                fields={
                    **run_fields,
                    "reason": outcome["reason"],
                    "blockerCodes": outcome["blockerCodes"],
                },
            )
        else:
            summary["skipped"] += 1
    return summary



def auto_retry_pending_collection_handoffs(
    team_id: str,
    *,
    question_id: str,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Re-run the idempotent handoff for zombie ``handoff_pending`` requests.

    Auto-advance step between round regeneration and adjudication.  The live
    break this closes: ``notify_collection_run_terminal`` runs the collection
    writeback exactly once when a run completes, and a handoff rejection
    there (historically: a review-round link already bound by a sibling
    request's fan-out) parked the request in ``handoff_pending`` forever —
    the run never completes again and no other path retried it, so the
    pending count blocked budget-exhaustion adjudication permanently.  A
    request is retried only when it is still ``handoff_pending`` AND its
    collection run already reached ``completed`` (a running or failed run
    stays owned by collection recovery) AND the configured grace since its
    last attempt has elapsed, so a persistently failing request is
    throttled by the grace instead of being hammered by every 30s sweep.

    The action reuses :func:`record_collection_handoff` unchanged (idempotent
    ``handed_off``/``reused`` semantics, claim materialization, and the
    newest-round guard that keeps a late handoff from stacking another
    round).  Every request is isolated: a domain rejection stays pending and
    retries on the next pass, nothing here raises, and each outcome lands as
    a ``hypothesis_first.auto_retry_handoff`` scene event.
    """
    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "status": "skipped",
        "reason": "",
        "retried": 0,
        "skipped": 0,
        "failed": 0,
    }
    if not normalized_team_id or not normalized_question_id:
        summary["reason"] = "missing_identity"
        return summary
    now_value = int(now_ms if now_ms is not None else time.time() * 1000)
    grace_ms = _auto_retry_handoff_grace_ms()
    try:
        requests = [
            record
            for record in _collection_requests(_records(normalized_team_id))
            if str(record.get("questionId") or "").strip().upper()
            == normalized_question_id
        ]
    except Exception as exc:  # noqa: BLE001 - detection stays best-effort
        summary["status"] = "failed"
        summary["reason"] = "detection_failed"
        summary["error"] = str(exc)[:400]
        _record_scene_event(
            "hypothesis_first.auto_retry_handoff",
            outcome="failed",
            level="warning",
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "reason": "detection_failed",
                "errorType": type(exc).__name__,
                "error": str(exc)[:400],
            },
        )
        return summary
    for request in requests:
        request_id = str(request.get("requestId") or "").strip()
        if not request_id:
            continue
        fields = {
            "teamId": normalized_team_id,
            "questionId": normalized_question_id,
            "requestId": request_id,
            "collectionRunId": str(request.get("collectionRunId") or ""),
            "graceMs": grace_ms,
        }
        if str(request.get("status") or "") != "handoff_pending":
            continue
        if str(request.get("collectionRunStatus") or "").strip().lower() != (
            "completed"
        ):
            # The run has not finished (or recovery owns a failed run): the
            # writeback will arrive on its own, retrying here would race it.
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_handoff",
                outcome="skipped",
                fields={**fields, "reason": "run_not_completed"},
            )
            continue
        last_attempt_ms = _iso_timestamp_ms(
            request.get("lastAutoRetryAt") or request.get("handedOffAt")
        )
        if last_attempt_ms is not None and (
            now_value - last_attempt_ms
        ) < grace_ms:
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_handoff",
                outcome="skipped",
                fields={**fields, "reason": "within_grace_period"},
            )
            continue
        try:
            # Refresh the attempt timestamp BEFORE the retry so a crashing
            # or hanging handoff still respects the grace on the next pass.
            _update_collection_request(
                normalized_team_id, request_id, lastAutoRetryAt=_utc_now()
            )
            handoff_ref = str(request.get("handoffRef") or "").strip()
            if not handoff_ref:
                run_id = str(request.get("collectionRunId") or "").strip()
                handoff_ref = (
                    f"source_collection_run:{run_id}" if run_id else ""
                )
            result = record_collection_handoff(
                normalized_team_id,
                request_id,
                handoff_ref=handoff_ref,
            )
        except HypothesisFirstChainError as exc:
            # Domain rejection (a guard disagrees): restore the pending
            # state the writeback would have left — the handoff already
            # flipped the record to handed_off before the rejection fired —
            # so the request stays visibly retryable on the next pass.
            summary["failed"] += 1
            try:
                _update_collection_request(
                    normalized_team_id,
                    request_id,
                    status="handoff_pending",
                    handoffError={
                        "code": "handoff_failed",
                        "message": str(exc)[:500],
                    },
                )
            except Exception:  # noqa: BLE001 - never mask the handoff error
                pass
            _record_scene_event(
                "hypothesis_first.auto_retry_handoff",
                outcome="failed",
                fields={
                    **fields,
                    "reason": "domain_rejected",
                    "error": str(exc)[:400],
                },
            )
            continue
        except Exception as exc:  # noqa: BLE001 - one request is isolated
            summary["failed"] += 1
            try:
                _update_collection_request(
                    normalized_team_id,
                    request_id,
                    status="handoff_pending",
                    handoffError={
                        "code": "handoff_failed",
                        "message": str(exc)[:500],
                    },
                )
            except Exception:  # noqa: BLE001 - never mask the retry error
                pass
            _record_scene_event(
                "hypothesis_first.auto_retry_handoff",
                outcome="failed",
                level="warning",
                fields={
                    **fields,
                    "reason": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
            continue
        result_status = str(result.get("status") or "")
        if result_status in {"handed_off", "reused"}:
            summary["retried"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_handoff",
                outcome="retried",
                fields={**fields, "handoffStatus": result_status},
            )
        else:
            summary["skipped"] += 1
            _record_scene_event(
                "hypothesis_first.auto_retry_handoff",
                outcome="skipped",
                fields={
                    **fields,
                    "reason": f"unexpected_status:{result_status}",
                },
            )
    if summary["retried"]:
        summary["status"] = "retried"
    elif summary["failed"]:
        summary["status"] = "failed"
    return summary



def auto_repair_handed_off_claim_refs(
    team_id: str, *, question_id: str
) -> dict[str, Any]:
    """Re-run the chain claim bridge for handed-off requests missing refs.

    Production incident (SCI-085, 2026-09-10): the candidate's core-claim row
    was proposed ref-less at selection time, so the handoff-time Phase 2
    proposal collided with the ledger's claim-id content binding, the whole
    chain materialization failed, and the collected evidence never attached —
    the convergence gate then read ``evidenceRefs=[]`` and the auto-advance
    recorded a rejected adjudication for a candidate the reviewers accepted.
    With ledger-level evidence-ref attachment in place, the idempotent chain
    bridge (:func:`_materialize_request_collection_claims`) heals such ledgers
    on replay.  This sweep step finds ``handed_off`` requests whose served
    hypothesis candidates still have no candidate-dimension evidence record
    for the request's own collection run, re-runs the bridge once for them,
    and marks the request (``claimRefsRepairAt``) so the repair is one-shot
    per request; a failed repair stays unmarked and retries on a later pass.
    Requests already fully covered, and the terminal-event/operator handoff
    replay paths, are untouched.  Nothing here raises.
    """
    normalized_team_id = str(team_id or "").strip()
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "status": "skipped",
        "reason": "",
        "repaired": 0,
        "skipped": 0,
        "failed": 0,
    }
    if not normalized_team_id or not normalized_question_id:
        summary["reason"] = "missing_identity"
        return summary
    try:
        requests = [
            record
            for record in _collection_requests(_records(normalized_team_id))
            if str(record.get("questionId") or "").strip().upper()
            == normalized_question_id
            and str(record.get("status") or "") == "handed_off"
        ]
    except Exception as exc:  # noqa: BLE001 - detection stays best-effort
        summary["status"] = "failed"
        summary["reason"] = "detection_failed"
        summary["error"] = str(exc)[:400]
        _record_scene_event(
            "hypothesis_first.auto_repair_claim_refs",
            outcome="failed",
            level="warning",
            fields={
                "teamId": normalized_team_id,
                "questionId": normalized_question_id,
                "reason": "detection_failed",
                "errorType": type(exc).__name__,
                "error": str(exc)[:400],
            },
        )
        return summary
    try:
        evidence_records = _claim_evidence_records(normalized_team_id)
    except Exception:  # noqa: BLE001 - unreadable store keeps the gate closed
        evidence_records = []
    for request in requests:
        request_id = str(request.get("requestId") or "").strip()
        collection_run_id = str(request.get("collectionRunId") or "").strip()
        served_ids = _normalized_str_list(request.get("hypothesisCandidateIds"))
        fields = {
            "teamId": normalized_team_id,
            "questionId": normalized_question_id,
            "requestId": request_id,
            "collectionRunId": collection_run_id,
        }
        if not request_id or not collection_run_id or not served_ids:
            summary["skipped"] += 1
            continue
        if str(request.get("claimRefsRepairAt") or "").strip():
            # One-shot per request: a completed (or markered) repair must not
            # re-run on every sweep pass even when the run legitimately
            # produced no anchorable evidence.
            summary["skipped"] += 1
            continue
        served = set(served_ids)
        covered = {
            str(record.get("candidateId") or "").strip()
            for record in evidence_records
            if str(record.get("sourceCollectionRunId") or "") == collection_run_id
            and str(record.get("candidateId") or "").strip() in served
        }
        if not (served - covered):
            summary["skipped"] += 1
            continue
        try:
            result = _materialize_request_collection_claims(
                normalized_team_id, request
            )
        except Exception as exc:  # noqa: BLE001 - one request is isolated
            summary["failed"] += 1
            _record_scene_event(
                "hypothesis_first.auto_repair_claim_refs",
                outcome="failed",
                level="warning",
                fields={**fields, "error": str(exc)[:400]},
            )
            continue
        if str(result.get("status") or "") == "failed":
            summary["failed"] += 1
            _record_scene_event(
                "hypothesis_first.auto_repair_claim_refs",
                outcome="failed",
                level="warning",
                fields={**fields, "reason": "materialization_failed"},
            )
            continue
        try:
            _update_collection_request(
                normalized_team_id,
                request_id,
                claimRefsRepairAt=_utc_now(),
            )
        except Exception:  # noqa: BLE001 - the repair itself already landed
            pass
        summary["repaired"] += 1
        _record_scene_event(
            "hypothesis_first.auto_repair_claim_refs",
            outcome="repaired",
            fields={**fields, "materializationStatus": str(result.get("status") or "")},
        )
    if summary["repaired"]:
        summary["status"] = "repaired"
    elif summary["failed"]:
        summary["status"] = "failed"
    return summary



def auto_accept_knowledge_handoffs(
    team_id: str,
    *,
    question_id: str,
) -> dict[str, Any]:
    """Auto-accept pending ``knowledge_handoff`` human gates on formal runs.

    Budget-exhaustion auto-advance, after formal-run creation (safe to call
    standalone).  The knowledge ingestion governance chain (source review
    accepted -> knowledge review approved -> official sync) is itself the
    human decision, so per operator policy the residual ``knowledge_handoff``
    click is accepted automatically instead of dead-waiting on a human.  The
    helper enumerates the question's non-archived main and parallel knowledge
    sideflow runs and, per run,
    resolves every pending ``knowledge_handoff`` human task through the exact
    formal command SSOT the manual accept uses
    (``WorkflowCommandKind.RESOLVE_HUMAN_TASK``, deterministic idempotency key
    ``hf2:auto-knowledge-handoff:<runId>:<taskId>``).

    Fail-closed scoping: only ``nodeId == knowledge_handoff`` tasks are
    touched (task kind and the node attempt must both agree); the inbound
    ``e_ingest_handoff`` handoff must carry a ``knowledge_package_draft``
    artifact reference (proof the governed ingestion completed), otherwise the
    task is skipped unsubmitted; and the command service still re-verifies the
    materialized accepted knowledge package at accept time, so a missing
    package ends as a structured skip, never a blind accept.  Every other
    human gate (protocol_freeze / smoke_gate / candidate_promotion) keeps its
    human decision semantics and is never touched.

    Isolation and idempotency: typed command rejections (already resolved,
    stale run version, forbidden, artifact not materialized) count as
    ``skipped`` for the next tick, unexpected errors count as ``failed``, a
    previous auto-accept replayed from the bounded event window counts as
    ``reused``, and nothing here raises.  Every outcome is recorded as a
    ``hypothesis_first.auto_accept_knowledge_handoff`` scene event.
    """
    normalized_question_id = str(question_id or "").strip().upper()
    summary: dict[str, Any] = {
        "runsScanned": 0,
        "pendingTasks": 0,
        "accepted": 0,
        "reused": 0,
        "skipped": 0,
        "failed": 0,
    }
    try:
        from .formal_read_runtime import get_query_service

        query_service = get_query_service()
        runs_by_id: dict[str, Mapping[str, Any]] = {}
        for workflow_id in (CHALLENGE_CUP_WORKFLOW_ID, KNOWLEDGE_SIDEFLOW_WORKFLOW_ID):
            payload = query_service.list_runs(team_id=team_id, workflow_id=workflow_id)
            for run in list((payload or {}).get("runs") or []):
                if isinstance(run, Mapping) and str(run.get("runId") or "").strip():
                    runs_by_id[str(run["runId"]).strip()] = run
    except Exception:  # noqa: BLE001 - formal runtime absent (command line)
        return summary
    from .runtime_factory import production_workflow_runtime

    runtime = production_workflow_runtime()
    if runtime is None:
        return summary
    runs = [
        run
        for run in runs_by_id.values()
        if isinstance(run, Mapping)
        and str(run.get("questionId") or "").strip().upper()
        == normalized_question_id
        and str(run.get("status") or "").strip().lower() != "archived"
    ]
    for run in runs:
        summary["runsScanned"] += 1
        run_id = str(run.get("runId") or "").strip()
        if not run_id:
            continue
        try:
            scan = runtime.store.read(
                lambda repo: _scan_knowledge_handoff_targets(repo, run_id)
            )
        except Exception as exc:  # noqa: BLE001 - one broken run is isolated
            summary["failed"] += 1
            _record_scene_event(
                "hypothesis_first.auto_accept_knowledge_handoff",
                outcome="failed",
                level="warning",
                fields={
                    "teamId": team_id,
                    "questionId": normalized_question_id,
                    "runId": run_id,
                    "reason": type(exc).__name__,
                    "error": str(exc)[:400],
                },
            )
            continue
        # Replays of this sweep's own earlier accepts (bounded event window,
        # same discipline as the snapshot) are reported as reused — the task
        # is already resolved, so there is nothing pending to resubmit.
        for task_id in sorted(scan.get("autoAcceptedTaskIds") or []):
            summary["reused"] += 1
            _record_scene_event(
                "hypothesis_first.auto_accept_knowledge_handoff",
                outcome="reused",
                fields={
                    "teamId": team_id,
                    "questionId": normalized_question_id,
                    "runId": run_id,
                    "taskId": task_id,
                    "reason": "already_auto_accepted",
                },
            )
        for target in scan.get("pendingTargets") or []:
            task_id = str(target.get("taskId") or "")
            summary["pendingTasks"] += 1
            if not target.get("eligible"):
                # The nodeId could not be double-confirmed from the node
                # attempt: fail closed, never guess.
                reason = str(target.get("reason") or "task_not_eligible")
                summary["skipped"] += 1
                _record_scene_event(
                    "hypothesis_first.auto_accept_knowledge_handoff",
                    outcome="skipped",
                    fields={
                        "teamId": team_id,
                        "questionId": normalized_question_id,
                        "runId": run_id,
                        "taskId": task_id,
                        "reason": reason,
                    },
                )
                continue
            if not target.get("draftRefPresent"):
                # Without a knowledge_package_draft reference on the inbound
                # e_ingest_handoff the governance chain has not demonstrably
                # passed — the auto-accept never fires on a guess.
                summary["skipped"] += 1
                _record_scene_event(
                    "hypothesis_first.auto_accept_knowledge_handoff",
                    outcome="skipped",
                    fields={
                        "teamId": team_id,
                        "questionId": normalized_question_id,
                        "runId": run_id,
                        "taskId": task_id,
                        "reason": "artifact_refs_missing",
                    },
                )
                continue
            outcome, reason = _submit_auto_knowledge_handoff_accept(
                runtime,
                team_id=team_id,
                run_id=run_id,
                task_id=task_id,
            )
            summary[outcome] += 1
            _record_scene_event(
                "hypothesis_first.auto_accept_knowledge_handoff",
                outcome=outcome,
                level="warning" if outcome == "failed" else "info",
                fields={
                    "teamId": team_id,
                    "questionId": normalized_question_id,
                    "runId": run_id,
                    "taskId": task_id,
                    "reason": reason,
                },
            )
    return summary



def auto_advance_stage_one_generation(team_id: str, *, question_id: str) -> dict[str, Any]:
    """Advance single-run generation and screened selection via UI commands.

    A completed exploratory round is not a failed generation to retry. The
    existing projection owns the join with accepted knowledge, and the command
    rechecks that offer under the question lock before opening its idempotent
    meeting. Failed grounded discussions reuse the retry offer, capped by the
    existing round limit within R1. A completed grounded meeting submits its
    complete candidate pool to the existing quality/diversity screening command.
    Single-question review is workflow-owned, independent of batch calibration.
    No R0 replay or experiment action is submitted.
    """
    from .formal_read_runtime import get_query_service
    from .hypothesis_first_state_v2 import (
        _active_stage_one_run, project_hypothesis_first_state_v2,
    )

    summary: dict[str, Any] = {"opened": 0, "failed": 0}
    try:
        catalog = get_query_service().list_runs(
            team_id=team_id, workflow_id=CHALLENGE_CUP_WORKFLOW_ID,
        )
        run = _active_stage_one_run([
            item for item in catalog.get("runs", [])
            if str(item.get("questionId") or "").strip().upper()
            == str(question_id or "").strip().upper()
        ])
        if run is None:
            return summary
        run_id = str(run["runId"])
        snapshot = project_hypothesis_first_state_v2(
            team_id, question_id, workflow_run_id=run_id,
        )
        action = next((
            item for item in snapshot.get("allowedActions", [])
            if item.get("actionId") == "open-stage-one-generation"
            and item.get("command") == "open_generation"
            and item.get("enabled") is True
        ), None)
        generation = snapshot.get("generation") or {}
        if action is None and generation.get("lifecycle") == "failed" and any(
            problem.get("code") in {"discussion_round_failed", "diversity_collapse"}
            for problem in generation.get("problems") or []
        ):
            grounded_meetings = [
                meeting for meeting in _question_generation_meetings(team_id, question_id)
                if _meeting_workflow_run_id(meeting) == run_id
                and meeting.get("candidateAuthority") == FORMAL_GROUNDED_CANDIDATE_AUTHORITY
            ]
            if len(grounded_meetings) < HARD_ROUND_LIMIT and any(
                meeting.get("meetingRoundId") == generation.get("generationMeetingId")
                for meeting in grounded_meetings
            ):
                action = next((
                    item for item in snapshot.get("allowedActions", [])
                    if item.get("actionId") == "retry-generation"
                    and item.get("command") == "retry_generation"
                    and item.get("enabled") is True
                ), None)
        selection_input: dict[str, Any] = {}
        selection = snapshot.get("selection") or {}
        if (
            action is None
            and generation.get("lifecycle") == "completed"
            and selection.get("lifecycle") == "waiting_human"
            and not selection.get("selectionId")
        ):
            owns_grounded_result = any(
                meeting.get("meetingRoundId") == generation.get("generationMeetingId")
                and meeting.get("status") == "closed"
                and _meeting_workflow_run_id(meeting) == run_id
                and meeting.get("candidateAuthority") == FORMAL_GROUNDED_CANDIDATE_AUTHORITY
                for meeting in _question_generation_meetings(team_id, question_id)
            )
            if owns_grounded_result:
                action = next((
                    item for item in snapshot.get("allowedActions", [])
                    if item.get("actionId") == "record-selection"
                    and item.get("command") == "record_selection"
                    and item.get("enabled") is True
                ), None)
                if action is not None:
                    selection_input = {"candidateIds": list(generation.get("candidateIds") or [])}
        if action is None:
            return summary
        request = {**action, "expectedStateVersion": snapshot["stateVersion"]}
        actor_args = {}
        if selection_input:
            request["input"] = selection_input
            actor_args["_actor"] = "system:stage-one-auto-selection"
        execute_v2_command(team_id, request, question_id=question_id,
                           workflow_run_id=run_id, **actor_args)
        summary["selected" if selection_input else "opened"] = 1
    except HypothesisFirstChainError:
        # The package or offer moved after projection; the owning command
        # rejected before launch and the next maintenance pass will re-read.
        return summary
    except Exception as exc:  # noqa: BLE001 - isolate one question
        summary["failed"] = 1
        _record_scene_event(
            "hypothesis_first.auto_advance_stage_one_generation", outcome="failed",
            level="warning", fields={"teamId": team_id, "questionId": question_id,
                                     "errorType": type(exc).__name__},
        )
        return summary
    _record_scene_event(
        "hypothesis_first.auto_advance_stage_one_generation", outcome="selected" if selection_input else "opened",
        fields={"teamId": team_id, "questionId": question_id,
                "runId": run_id},
    )
    return summary



def sweep_auto_advance_closure() -> dict[str, Any]:
    """Maintenance sweep: auto-advance every exhausted hypothesis chain.

    Restart-time recovery for chains stuck at an auto-advance gate (the
    closing tick may be long gone by the time this runs).  Enumerates the
    team ids that own a hypothesis-first chain ledger read-only, then walks
    each question through approve -> regenerate -> backfill-round-authorities
    -> backfill-feedback-iterations -> retry-handoffs -> adjudicate ->
    create -> accept-knowledge-handoffs ->
    retry: review
    digests that waited beyond the TTL
    get approved and closed first (so the fan-in / next-round advance can
    still progress within the same pass), a newest review round whose fan-in
    round generation never landed (the closure LLM died mid-close) gets its
    HypothesisRound regenerated before anything downstream could block on
    it, a closed round whose canonical dimension_reviews authority never
    landed (a first-write persistence failure or an older build) gets its
    authority batch re-materialized by replaying the stored round, zombie
    collection requests parked in ``handoff_pending`` by a
    once-failed writeback get their idempotent handoff retried past the
    grace (unblocking the pending count in the same pass), handed-off
    requests whose served candidates still miss their collected
    candidate-dimension claim evidence (the SCI-085 ref-less-first-proposal
    ledger defect) get the idempotent chain claim bridge re-run once,
    exhausted rounds
    get their accepted adjudication, converged chains get the formal run
    created and started, runs blocked on the stage-boundary budget precheck
    get the extend_budget → retry_node contract driven automatically within
    the per-node extension cap (formal runs and knowledge sideflow children
    alike), and formal nodes blocked on the transient
    ``auto_advance_not_ready`` gate get their offer-gated retry resubmitted.
    Nothing here raises: one broken team or question is isolated and
    counted; questions whose latest round is not an unadjudicated exhausted
    round cost one cheap guard read.
    """
    global _SWEEP_ROUND_ROBIN_CURSOR

    summary: dict[str, Any] = {
        "teams": 0,
        "questions": 0,
        "approved": 0,
        "roundsRegenerated": 0,
        "authoritiesBackfilled": 0,
        "feedbackIterationsBackfilled": 0,
        "handoffsRetried": 0,
        "claimRefsRepaired": 0,
        "adjudicated": 0,
        "rejected": 0,
        "formalRuns": 0,
        "knowledgeHandoffsAccepted": 0,
        "budgetExtends": 0,
        "budgetRetries": 0,
        "budgetDeclined": 0,
        "retried": 0,
        "fencedReviewsRedriven": 0,
        "closedGenerationsRetried": 0,
        "failed": 0,
        "skipped": 0,
        "budgetExhausted": False,
        "questionsDeferred": 0,
    }
    try:
        team_ids = _team_ids_with_chain_storage()
    except Exception:  # noqa: BLE001 - the sweep must never break its host
        _record_scene_event(
            "hypothesis_first.auto_advance_sweep",
            outcome="failed",
            level="warning",
            fields={"reason": "team_enumeration_failed"},
        )
        return summary
    resume_team, resume_question = _SWEEP_ROUND_ROBIN_CURSOR or (0, 0)
    if resume_team >= len(team_ids):
        resume_team, resume_question = 0, 0
    budget_ms = _auto_advance_sweep_budget_ms()
    round_started_at = time.monotonic()
    processed_any = False
    budget_exhausted = False
    for team_offset in range(len(team_ids)):
        team_index = (resume_team + team_offset) % len(team_ids)
        team_id = team_ids[team_index]
        summary["teams"] += 1
        try:
            # One ledger read per team per sweep pass: the redrive plan
            # construction below receives this snapshot instead of re-parsing
            # the whole chain file per meeting/question (defect 18). Mutation
            # steps still read fresh state through the memoized reader.
            team_records = _records(team_id)
            question_ids = question_ids_with_chain_records(
                team_id, records=team_records
            )
        except Exception:  # noqa: BLE001 - one broken team cannot stop the sweep
            summary["skipped"] += 1
            continue
        question_start = resume_question if team_offset == 0 else 0
        if question_start >= len(question_ids):
            question_start = 0
        pending = question_ids[question_start:]
        for pending_index, question_id in enumerate(pending):
            # Budget gate (defect 19): before opening a new question, stop
            # once the pass exceeded its wall-clock budget. The first question
            # always runs so a tiny budget can never stall progress entirely;
            # the stop cursor resumes round-robin on the next pass.
            if processed_any and budget_ms > 0:
                elapsed_ms = (time.monotonic() - round_started_at) * 1000.0
                if elapsed_ms >= budget_ms:
                    budget_exhausted = True
                    summary["questionsDeferred"] += len(pending) - pending_index
                    _SWEEP_ROUND_ROBIN_CURSOR = (
                        team_index,
                        question_start + pending_index,
                    )
                    break
            if pending_index or question_start:
                time.sleep(_SWEEP_ITERATION_YIELD_SECONDS)
            processed_any = True
            summary["questions"] += 1
            try:
                # Step zero, before adjudication: approve landed review and
                # candidate-generation digests once the (default-zero) TTL
                # allows it, so the closure chain (fan-in, next round) can
                # still progress within this same pass.
                approval = auto_approve_awaiting_review_digests(
                    team_id, question_id=question_id
                )
                summary["approved"] += int(approval.get("approved") or 0)
                # Step zero-five, after approval: a newest review round whose
                # fan-in round generation never landed (the closure's
                # synchronous review-LLM call died after the meeting was
                # already closed) is regenerated here — without the round,
                # every downstream gate below would wait forever.
                regeneration = auto_regenerate_missing_hypothesis_round(
                    team_id, question_id=question_id
                )
                if str(regeneration.get("status") or "") == "created":
                    summary["roundsRegenerated"] += 1
                elif str(regeneration.get("status") or "") == "failed":
                    summary["failed"] += 1
                # Step zero-six, after regeneration: a closed round whose
                # canonical dimension_reviews authority never landed (a
                # first-write persistence failure, or a round generated by an
                # older build) gets its authority batch re-materialized by
                # replaying the stored round (zero review calls).  Without
                # this, the stage-one result_package readiness gate blocks on
                # the generic result_package_incomplete forever.
                backfill = auto_backfill_missing_round_authorities(
                    team_id, question_id=question_id
                )
                summary["authoritiesBackfilled"] += int(
                    backfill.get("backfilled") or 0
                )
                if str(backfill.get("status") or "") == "failed":
                    summary["failed"] += 1
                # Step zero-seven, after round-authority backfill: a blocked
                # formal run whose authority carries zero canonical
                # feedback_iterations artifacts gets its closed
                # hypothesis-review round chain replayed as feedback-iteration
                # authority (fail-closed, idempotent).  Without this, result
                # packaging fails with "canonical feedback_iterations contains
                # no actual revision" forever even though every round
                # truthfully revised.
                feedback_backfill = auto_backfill_missing_feedback_iterations(
                    team_id, question_id=question_id
                )
                summary["feedbackIterationsBackfilled"] += int(
                    feedback_backfill.get("written") or 0
                )
                if str(feedback_backfill.get("status") or "") == "failed":
                    summary["failed"] += 1
                # Step zero-eight, after regeneration and before
                # adjudication: a collection request left in handoff_pending
                # by a once-failed writeback (its run already completed) is
                # retried here — past the grace it unblocks the pending
                # count, so a chain rescued in this pass can be adjudicated
                # in the same pass instead of waiting another tick.
                handoff_retry = auto_retry_pending_collection_handoffs(
                    team_id, question_id=question_id
                )
                summary["handoffsRetried"] += int(
                    handoff_retry.get("retried") or 0
                )
                # Step zero-eight-five, after handoff retry and before
                # adjudication: a handed_off request whose served candidates
                # still miss the collected candidate-dimension evidence (the
                # SCI-085 ref-less-first-proposal ledger defect) gets the
                # idempotent chain claim bridge re-run once, so the belief
                # gate reads the collected refs instead of an empty list.
                claim_ref_repair = auto_repair_handed_off_claim_refs(
                    team_id, question_id=question_id
                )
                summary["claimRefsRepaired"] += int(
                    claim_ref_repair.get("repaired") or 0
                )
                if str(claim_ref_repair.get("status") or "") == "failed":
                    summary["failed"] += 1
                adjudication = auto_adjudicate_exhausted_round(
                    team_id, question_id=question_id
                )
                status = str(adjudication.get("status") or "")
                if status == "created":
                    summary["adjudicated"] += 1
                elif status == "rejected":
                    summary["rejected"] += 1
                elif status == "failed":
                    summary["failed"] += 1
                else:
                    summary["skipped"] += 1
                if status in {"created", "reused"}:
                    formal_run = auto_create_formal_run_after_convergence(
                        team_id, question_id=question_id
                    )
                    if str(formal_run.get("status") or "") == "created":
                        summary["formalRuns"] += 1
                    elif str(formal_run.get("status") or "") == "failed":
                        summary["failed"] += 1
                # Step two-five, every question every pass: accept the
                # knowledge_handoff human gate on formal runs whose ingestion
                # governance chain already passed (the operator-automation
                # policy removes the residual click).  Newly created runs have
                # no such task yet; live runs stuck on the gate unblock here.
                handoff_accept = auto_accept_knowledge_handoffs(
                    team_id, question_id=question_id
                )
                summary["knowledgeHandoffsAccepted"] += int(
                    handoff_accept.get("accepted") or 0
                )
                # Step two-six, every question every pass: drive the
                # extend_budget → retry_node recovery contract for runs
                # blocked on the stage-boundary budget precheck (formal runs
                # AND knowledge sideflow child runs), bounded per node and
                # config-gated; read-only unless an eligible block exists.
                budget_recovery = auto_extend_budget_blocked_nodes(
                    team_id, question_id=question_id
                )
                summary["budgetExtends"] += int(
                    budget_recovery.get("extended") or 0
                )
                summary["budgetRetries"] += int(
                    budget_recovery.get("retried") or 0
                )
                summary["budgetDeclined"] += int(
                    budget_recovery.get("declined") or 0
                )
                # Step three, every question every pass: resubmit the
                # offer-gated retry for formal nodes blocked on the transient
                # auto_advance_not_ready verdict (read-only unless an eligible
                # blocked run exists).
                retry_summary = auto_retry_blocked_formal_nodes(
                    team_id, question_id=question_id
                )
                summary["retried"] += int(retry_summary.get("retried") or 0)
                grounded_generation = auto_advance_stage_one_generation(
                    team_id, question_id=question_id
                )
                summary["failed"] += int(grounded_generation.get("failed") or 0)
                # Step four, every question every pass: execute the
                # retry-review-dispatch recovery for a fenced review meeting
                # whose discussion really completed (the offer 068c92ba5 made
                # executable, now driven automatically, one hop per pass).
                fenced_review = auto_redrive_fenced_review_meeting(
                    team_id, question_id=question_id, records=team_records
                )
                summary["fencedReviewsRedriven"] += int(
                    fenced_review.get("redriven") or 0
                )
                # Step five, every question every pass: supersede + retry a
                # fenced, digest-less generation attempt through the
                # retry_generation internal path (one retry per pass).
                fenced_generation = auto_retry_fenced_generation_attempt(
                    team_id, question_id=question_id
                )
                summary["closedGenerationsRetried"] += int(
                    fenced_generation.get("retried") or 0
                )
            except Exception:  # noqa: BLE001 - one broken question is isolated
                summary["failed"] += 1
        if budget_exhausted:
            break
    if not budget_exhausted:
        _SWEEP_ROUND_ROBIN_CURSOR = None
    summary["budgetExhausted"] = budget_exhausted
    _record_scene_event(
        "hypothesis_first.auto_advance_sweep",
        outcome="completed",
        fields={
            "teams": int(summary["teams"]),
            "questions": int(summary["questions"]),
            "approved": int(summary["approved"]),
            "roundsRegenerated": int(summary["roundsRegenerated"]),
            "authoritiesBackfilled": int(summary["authoritiesBackfilled"]),
            "handoffsRetried": int(summary["handoffsRetried"]),
            "claimRefsRepaired": int(summary["claimRefsRepaired"]),
            "adjudicated": int(summary["adjudicated"]),
            "rejected": int(summary["rejected"]),
            "formalRuns": int(summary["formalRuns"]),
            "knowledgeHandoffsAccepted": int(summary["knowledgeHandoffsAccepted"]),
            "budgetExtends": int(summary["budgetExtends"]),
            "budgetRetries": int(summary["budgetRetries"]),
            "budgetDeclined": int(summary["budgetDeclined"]),
            "retried": int(summary["retried"]),
            "fencedReviewsRedriven": int(summary["fencedReviewsRedriven"]),
            "closedGenerationsRetried": int(summary["closedGenerationsRetried"]),
            "failed": int(summary["failed"]),
            "skipped": int(summary["skipped"]),
            "budgetExhausted": bool(summary["budgetExhausted"]),
            "questionsDeferred": int(summary["questionsDeferred"]),
        },
    )
    return summary



def _auto_start_created_formal_run(
    team_id: str,
    *,
    run: Mapping[str, Any],
    idempotency_key: str,
) -> dict[str, Any] | None:
    """Submit the entry-node start_node right after ``create_formal_run``.

    Without this a created formal run waits indefinitely for a manual UI
    start (the graph worker's created-run reconciliation deliberately spares
    hypothesis-first-era runs only).  The start goes through the same offer
    gate as the UI: the offer's own idempotencyKey keeps replays idempotent,
    and an unavailable (readiness-blocked) offer keeps the historical
    behavior — wait for a human start, never bypass readiness.  Best-effort:
    any failure records a scene event and returns None instead of failing
    the create command.
    """
    run_id = str(run.get("runId") or "").strip()
    if not run_id:
        return None
    try:
        entry_node_id = _formal_run_entry_node_id(run)
        if not entry_node_id:
            raise HypothesisFirstChainError(
                "formal run definition has no startable entry node"
            )
        receipt = _submit_formal_v2_command(
            team_id,
            run_id=run_id,
            node_id=entry_node_id,
            command="start_node",
            idempotency_key=idempotency_key,
        )
    except HypothesisFirstChainError as exc:
        # Offer unavailable (readiness gate) or formal runtime absent (e.g.
        # command-line path): keep the historical wait-for-manual-start state.
        _record_scene_event(
            "formal_run_auto_start_waited",
            outcome="waited_for_manual_start",
            fields={
                "runId": run_id,
                "reason": str(exc),
                "errorType": type(exc).__name__,
            },
        )
        return None
    except Exception as exc:  # noqa: BLE001 - auto-start must never fail create
        _record_scene_event(
            "formal_run_auto_start_failed",
            outcome="failed",
            level="warning",
            fields={
                "runId": run_id,
                "reason": str(exc),
                "errorType": type(exc).__name__,
            },
        )
        return None
    _record_scene_event(
        "formal_run_auto_start_submitted",
        outcome="submitted",
        fields={
            "runId": run_id,
            "commandId": str(receipt.get("commandId") or ""),
            "receiptStatus": str(receipt.get("status") or ""),
        },
    )
    return receipt

_EXPORTS = (
    "_auto_advance_selection_tick",
    "_auto_advance_converge_tick",
    "_auto_advance_meeting_close_tick",
    "_auto_redispatch_superseded_reviews",
    "_auto_adjudication_idempotency_key",
    "_auto_adjudication_rejected_key",
    "auto_adjudicate_exhausted_round",
    "_auto_adjudicate_exhausted_round_locked",
    "auto_create_formal_run_after_convergence",
    "auto_retry_blocked_formal_nodes",
    "auto_extend_budget_blocked_nodes",
    "_auto_advance_sweep_budget_ms",
    "auto_redrive_fenced_review_meeting",
    "auto_retry_fenced_generation_attempt",
    "_auto_approve_digest_ttl_ms",
    "_auto_regen_round_grace_ms",
    "_auto_retry_handoff_grace_ms",
    "auto_approve_awaiting_review_digests",
    "_auto_regenerate_failure_budget_exhausted",
    "auto_regenerate_missing_hypothesis_round",
    "auto_backfill_missing_round_authorities",
    "auto_backfill_missing_feedback_iterations",
    "auto_retry_pending_collection_handoffs",
    "auto_repair_handed_off_claim_refs",
    "auto_accept_knowledge_handoffs",
    "auto_advance_stage_one_generation",
    "sweep_auto_advance_closure",
    "_auto_start_created_formal_run",
)
