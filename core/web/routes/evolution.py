"""Evolution workbench routes."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, status
from starlette.responses import StreamingResponse

from core.web.routes.evolution_models import (
    ChatReviewActionPayload,
    ChatReviewBulkDeletePayload,
    EvolutionChatReviewCandidateResponse,
    EvolutionChatReviewQueueResponse,
    EvolutionCommandStatusResponse,
    EvolutionDeletedResponse,
    EvolutionJsonResponse,
    EvolutionLibraryResponse,
    EvolutionOverviewResponse,
    EvolutionProposalResponse,
    EvolutionRunResponse,
    EvolutionSelfWorkspaceSnapshotResponse,
    EvolutionWorkspaceSnapshotResponse,
    ProposalBulkDeletePayload,
    ProposalUpdatePayload,
    SelfEvolutionAutonomousRunActionPayload,
    SelfEvolutionAutonomousRunStartPayload,
    SelfEvolutionHistoryDeletePayload,
    SelfEvolutionWorktreeRunStartPayload,
    SelfObservationRunActionPayload,
    SelfObservationRunStartPayload,
    SupervisedRunActionPayload,
    SupervisedRunStartPayload,
    SupervisedWorktreeRunActionPayload,
    SupervisedWorktreeRunStartPayload,
)

from core.web.services.chat_review_service import (
    ChatReviewCandidateNotFoundError,
    ChatReviewCandidateStateError,
    ChatReviewDecisionValidationError,
    approve_chat_review_candidate,
    bulk_discard_chat_review_candidates,
    get_chat_review_candidate,
    get_chat_review_queue,
    reject_chat_review_candidate,
    submit_chat_review_decision,
)
from core.web.services.evolution_service import (
    EvolutionProposalDeleteBlockedError,
    EvolutionProposalEditBlockedError,
    EvolutionProposalNotFoundError,
    EvolutionProposalValidationError,
    get_evolution_overview,
    get_evolution_workspace_dashboard,
    get_proposal_detail,
    get_self_evolution_candidate_review_queue,
    list_library_items,
    list_pending_library_items,
    list_runs,
    record_evolution_workspace_snapshot_perf,
    delete_proposal,
    bulk_delete_proposals,
    update_proposal,
)
from core.web.services.evolution_runtime_projection_service import build_workspace_runtime_projection
from core.web.services.self_evolution_service import (
    SelfEvolutionHistoryDeleteError,
    delete_self_evolution_history_groups,
    get_self_evolution_light_overview,
    get_self_evolution_overview,
    list_self_evolution_audit_events,
    list_self_evolution_transactions,
    record_self_evolution_workspace_snapshot_perf,
)
from core.web.services.self_evolution_control_service import (
    SelfEvolutionRunBusyError,
    SelfEvolutionRunNotFoundError,
    SelfEvolutionRunValidationError,
    execute_self_observation_action,
    get_active_self_observation_run,
    get_self_observation_run_snapshot,
    start_self_evolution_worktree_run,
    start_self_observation_run,
    stream_self_observation_run_events,
)
from core.web.services.self_evolution_autonomous_loop_orchestrator import (
    approve_autonomous_self_evolution,
    get_active_autonomous_self_evolution_run,
    get_autonomous_self_evolution_run,
    get_latest_autonomous_self_evolution_run,
    reject_autonomous_self_evolution,
    retry_autonomous_self_evolution_cleanup,
    start_autonomous_self_evolution,
)
from core.web.services.self_evolution_autonomous_loop_service import (
    AutonomousLoopConflictError,
    AutonomousLoopValidationError,
)
from core.web.services.supervised_control_service import (
    SupervisedRunDeleteError,
    SupervisedRunActionError,
    SupervisedRunBusyError,
    SupervisedRunNotFoundError,
    SupervisedRunStateError,
    SupervisedRunValidationError,
    delete_supervised_run_snapshot,
    execute_supervised_action,
    build_supervised_closed_loop_record,
    get_active_supervised_run,
    get_latest_supervised_run,
    get_supervised_runtime_manager_command_status,
    get_supervised_workbench,
    request_pause_supervised_run,
    retry_supervised_run,
    request_resume_supervised_run,
    request_stop_supervised_run,
    start_supervised_run,
    stream_active_supervised_run_events,
)
from core.web.services.supervised_agent_service import (
    SupervisedAgentBindingError,
    current_supervised_agent_bindings_snapshot,
)
from core.web.services.supervised_worktree_evolution_service import (
    SupervisedWorktreeRunActionError,
    SupervisedWorktreeRunBusyError,
    SupervisedWorktreeRunNotFoundError,
    SupervisedWorktreeRunValidationError,
    execute_supervised_worktree_action,
    get_active_supervised_worktree_run,
    get_supervised_worktree_run,
    list_supervised_worktree_runs,
    start_supervised_worktree_run,
    stream_supervised_worktree_run_events,
)


router = APIRouter(tags=["evolution"])


def _is_self_evolution_worktree_run(run: dict | None) -> bool:
    if not isinstance(run, dict):
        return False
    origin = run.get("selfEvolutionOrigin") if isinstance(run.get("selfEvolutionOrigin"), dict) else {}
    if str(origin.get("sourceTrack") or "").strip() == "self_evolution":
        return True
    start_request = run.get("startRequest") if isinstance(run.get("startRequest"), dict) else {}
    return (
        str(start_request.get("requestSource") or "").strip() == "api:evolution.self.worktree-runs"
        or str(start_request.get("initiator") or "").strip() == "self_evolution_risky_write"
    )


@router.get(
    "/evolution/overview",
    response_model=EvolutionOverviewResponse,
    response_model_exclude_unset=True,
)
def evolution_overview() -> dict:
    return get_evolution_overview()


@router.get(
    "/evolution/workspace-snapshot",
    response_model=EvolutionWorkspaceSnapshotResponse,
    response_model_exclude_unset=True,
)
def evolution_workspace_snapshot(includeSelf: bool = False) -> dict:
    started_at = time.perf_counter()
    timings: dict[str, float] = {}

    def timed(name: str, loader):
        stage_started = time.perf_counter()
        value = loader()
        timings[name] = (time.perf_counter() - stage_started) * 1000
        return value

    dashboard = timed("dashboard", get_evolution_workspace_dashboard)
    active_run = timed("active_run", get_active_supervised_run)
    workbench = timed(
        "workbench",
        lambda: get_supervised_workbench(
            active_run=active_run,
            active_run_loaded=True,
            include_catalog=False,
            saved_state=dashboard.get("overview", {}).get("workbench") if isinstance(dashboard.get("overview"), dict) else None,
        ),
    )
    active_run = workbench.get("activeRun") if isinstance(workbench, dict) else None
    latest_run = timed("latest_run", lambda: get_latest_supervised_run(active_run=active_run, active_run_loaded=True))
    latest_closed_loop_record = timed(
        "latest_closed_loop_record",
        lambda: _reviewable_supervised_closed_loop_record(latest_run),
    )
    current_agent_bindings = timed("current_agent_bindings", current_supervised_agent_bindings_snapshot)
    if isinstance(current_agent_bindings, dict):
        current_agent_binding_payload = current_agent_bindings.get("agentBindings") or {}
        current_agent_binding_source = current_agent_bindings.get("bindingSource") or ""
        current_agent_binding_status = current_agent_bindings.get("status") or "error"
        current_agent_binding_issues = current_agent_bindings.get("issues") or []
    else:
        current_agent_binding_payload = {}
        current_agent_binding_source = ""
        current_agent_binding_status = "error"
        current_agent_binding_issues = []
    self_overview = timed(
        "self_overview",
        get_self_evolution_overview if includeSelf else get_self_evolution_light_overview,
    )
    self_transactions = timed(
        "self_transactions",
        list_self_evolution_transactions if includeSelf else (lambda: []),
    )
    worktree_active_run = timed("worktree_active_run", get_active_supervised_worktree_run)
    worktree_runs = timed("worktree_runs", list_supervised_worktree_runs)
    self_worktree_runs = [item for item in worktree_runs if _is_self_evolution_worktree_run(item)]
    self_worktree_active_run = worktree_active_run if _is_self_evolution_worktree_run(worktree_active_run) else None
    self_observation_active_run = timed(
        "self_observation_active_run",
        get_active_self_observation_run if includeSelf else (lambda: None),
    )
    self_autonomous_active_run = timed(
        "self_autonomous_active_run",
        get_active_autonomous_self_evolution_run if includeSelf else (lambda: None),
    )
    self_autonomous_latest_run = timed(
        "self_autonomous_latest_run",
        get_latest_autonomous_self_evolution_run if includeSelf else (lambda: None),
    )
    supervised_runtime_active_run = (
        worktree_active_run
        if isinstance(worktree_active_run, dict) and not _is_self_evolution_worktree_run(worktree_active_run)
        else active_run
    )
    evolution_runtime = build_workspace_runtime_projection(
        supervised_active_run=supervised_runtime_active_run,
        self_worktree_active_run=self_worktree_active_run,
        self_observation_active_run=self_observation_active_run,
    )
    payload = {
        "overview": dashboard["overview"],
        "runs": dashboard["runs"],
        "library": dashboard["library"],
        "workbench": workbench,
        "activeRun": active_run,
        "latestRun": latest_run,
        "latestClosedLoopRecord": latest_closed_loop_record,
        "currentAgentBindings": current_agent_binding_payload,
        "currentAgentBindingSource": current_agent_binding_source,
        "currentAgentBindingStatus": current_agent_binding_status,
        "currentAgentBindingIssues": current_agent_binding_issues,
        "worktreeActiveRun": worktree_active_run,
        "worktreeRuns": worktree_runs,
        "evolutionRuntime": evolution_runtime,
        "selfOverview": self_overview,
        "selfWorktreeActiveRun": self_worktree_active_run,
        "selfWorktreeRuns": self_worktree_runs if includeSelf else [],
        "selfObservationActiveRun": self_observation_active_run,
        "selfAutonomousActiveRun": self_autonomous_active_run,
        "selfAutonomousLatestRun": self_autonomous_latest_run,
        "selfTransactions": self_transactions,
    }
    duration_ms = (time.perf_counter() - started_at) * 1000
    timings["total"] = duration_ms
    record_evolution_workspace_snapshot_perf(
        duration_ms=duration_ms,
        timings_ms=timings,
        payload=payload,
        include_self=includeSelf,
    )
    return payload


@router.get(
    "/evolution/self/workspace-snapshot",
    response_model=EvolutionSelfWorkspaceSnapshotResponse,
    response_model_exclude_unset=True,
)
def self_evolution_workspace_snapshot() -> dict:
    """Return only the self-evolution data needed for the self workbench first paint."""

    started_at = time.perf_counter()
    timings: dict[str, float] = {}

    def timed(name: str, loader):
        stage_started = time.perf_counter()
        value = loader()
        timings[name] = (time.perf_counter() - stage_started) * 1000
        return value

    overview = timed("overview", get_self_evolution_overview)
    transactions = timed("transactions", list_self_evolution_transactions)
    active_worktree_run = timed("worktree_active_run", get_active_supervised_worktree_run)
    self_worktree_active_run = (
        active_worktree_run
        if _is_self_evolution_worktree_run(active_worktree_run)
        else None
    )
    observation_active_run = timed("observation_active_run", get_active_self_observation_run)
    autonomous_active_run = timed("autonomous_active_run", get_active_autonomous_self_evolution_run)
    autonomous_latest_run = timed("autonomous_latest_run", get_latest_autonomous_self_evolution_run)
    payload = {
        "overview": overview,
        "transactions": transactions,
        "worktreeActiveRun": self_worktree_active_run,
        "observationActiveRun": observation_active_run,
        "autonomousActiveRun": autonomous_active_run,
        "autonomousLatestRun": autonomous_latest_run,
    }
    timings["total"] = (time.perf_counter() - started_at) * 1000
    record_self_evolution_workspace_snapshot_perf(
        duration_ms=timings["total"],
        timings_ms=timings,
        self_transaction_count=len(transactions),
    )
    return payload


def _reviewable_supervised_closed_loop_record(latest_run: dict | None) -> dict | None:
    if not isinstance(latest_run, dict):
        return None
    record = (
        latest_run.get("closedLoopRecord")
        if isinstance(latest_run.get("closedLoopRecord"), dict)
        else build_supervised_closed_loop_record(latest_run)
    )
    if not isinstance(record, dict):
        return None
    if str(record.get("recordStatus") or "").strip().lower() == "incomplete":
        return None
    return record


@router.get(
    "/evolution/runs",
    response_model=list[EvolutionRunResponse],
    response_model_exclude_unset=True,
)
def evolution_runs() -> list[dict]:
    return list_runs()


@router.get(
    "/evolution/library",
    response_model=EvolutionLibraryResponse,
    response_model_exclude_unset=True,
)
def evolution_library() -> dict:
    return {
        "items": list_library_items(),
        "pending": list_pending_library_items(),
    }


@router.get(
    "/evolution/proposals/{session_id}",
    response_model=EvolutionProposalResponse,
    response_model_exclude_unset=True,
)
def evolution_proposal_detail(session_id: str) -> dict:
    try:
        return get_proposal_detail(session_id)
    except EvolutionProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch(
    "/evolution/proposals/{session_id}",
    response_model=EvolutionProposalResponse,
    response_model_exclude_unset=True,
)
def evolution_update_proposal(session_id: str, payload: ProposalUpdatePayload) -> dict:
    updates = {}
    if payload.improvementType is not None:
        updates["improvement_type"] = payload.improvementType
    if payload.expectedEffect is not None:
        updates["expected_effect"] = payload.expectedEffect
    if payload.summary is not None:
        updates["summary"] = payload.summary
    if payload.candidatePrompt is not None:
        updates["candidate_prompt"] = payload.candidatePrompt
    if payload.baselinePrompt is not None:
        updates["baseline_prompt"] = payload.baselinePrompt
    try:
        return update_proposal(
            session_id,
            updates,
            edit_note=payload.editNote or "",
        )
    except EvolutionProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvolutionProposalEditBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EvolutionProposalValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/evolution/proposals/{session_id}",
    response_model=EvolutionProposalResponse,
    response_model_exclude_unset=True,
)
def evolution_delete_proposal(session_id: str) -> dict:
    try:
        return delete_proposal(session_id)
    except EvolutionProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvolutionProposalDeleteBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EvolutionProposalValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/evolution/proposals/delete",
    response_model=EvolutionDeletedResponse,
    response_model_exclude_unset=True,
)
def evolution_bulk_delete_proposals(payload: ProposalBulkDeletePayload) -> dict:
    return bulk_delete_proposals(payload.sessionIds)


@router.get(
    "/evolution/workbench",
    response_model=EvolutionJsonResponse,
    response_model_exclude_unset=True,
)
def evolution_workbench() -> dict:
    return get_supervised_workbench()


@router.get(
    "/evolution/chat-review",
    response_model=EvolutionChatReviewQueueResponse,
    response_model_exclude_unset=True,
)
def evolution_chat_review(includeDetails: bool = False) -> dict:
    return get_chat_review_queue(include_details=includeDetails)


@router.get(
    "/evolution/chat-review/{candidate_id}",
    response_model=EvolutionChatReviewCandidateResponse,
    response_model_exclude_unset=True,
)
def evolution_chat_review_candidate(candidate_id: str) -> dict:
    try:
        return get_chat_review_candidate(candidate_id)
    except ChatReviewCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/evolution/self/candidates",
    response_model=EvolutionChatReviewQueueResponse,
    response_model_exclude_unset=True,
)
def evolution_self_candidates() -> dict:
    return get_self_evolution_candidate_review_queue()


@router.post(
    "/evolution/chat-review/delete",
    response_model=EvolutionDeletedResponse,
    response_model_exclude_unset=True,
)
def evolution_chat_review_bulk_delete(payload: ChatReviewBulkDeletePayload) -> dict:
    return bulk_discard_chat_review_candidates(
        payload.candidateIds,
        reviewer_note=payload.reviewerNote,
    )


@router.post(
    "/evolution/chat-review/{candidate_id}/approve",
    response_model=EvolutionChatReviewCandidateResponse,
    response_model_exclude_unset=True,
)
def evolution_chat_review_approve(candidate_id: str, payload: ChatReviewActionPayload) -> dict:
    try:
        return approve_chat_review_candidate(candidate_id, reviewer_note=payload.reviewerNote)
    except ChatReviewCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatReviewCandidateStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/evolution/chat-review/{candidate_id}/reject",
    response_model=EvolutionChatReviewCandidateResponse,
    response_model_exclude_unset=True,
)
def evolution_chat_review_reject(candidate_id: str, payload: ChatReviewActionPayload) -> dict:
    try:
        return reject_chat_review_candidate(candidate_id, reviewer_note=payload.reviewerNote)
    except ChatReviewCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatReviewCandidateStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/evolution/chat-review/{candidate_id}/decision",
    response_model=EvolutionChatReviewCandidateResponse,
    response_model_exclude_unset=True,
)
def evolution_chat_review_decision(candidate_id: str, payload: ChatReviewActionPayload) -> dict:
    try:
        return submit_chat_review_decision(
            candidate_id,
            decision=payload.decision,
            reviewer_note=payload.reviewerNote,
            reason_code=payload.reasonCode,
            error_type=payload.errorType,
            correct_principle=payload.correctPrinciple,
            ideal_behavior=payload.idealBehavior,
        )
    except ChatReviewCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatReviewCandidateStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChatReviewDecisionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/evolution/active-run",
    response_model=EvolutionRunResponse | None,
    response_model_exclude_unset=True,
)
def evolution_active_run() -> dict | None:
    return get_active_supervised_run()


@router.get(
    "/evolution/latest-run",
    response_model=EvolutionRunResponse | None,
    response_model_exclude_unset=True,
)
def evolution_latest_run() -> dict | None:
    return get_latest_supervised_run()


@router.get(
    "/evolution/active-run/events",
    response_class=StreamingResponse,
)
def evolution_active_run_events() -> StreamingResponse:
    snapshot = get_active_supervised_run()
    return StreamingResponse(
        stream_active_supervised_run_events(initial_snapshot=snapshot) if snapshot is not None else iter(()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/evolution/runs/commands/{command_id}",
    response_model=EvolutionCommandStatusResponse,
    response_model_exclude_unset=True,
)
def evolution_run_command_status(command_id: str) -> dict:
    try:
        return get_supervised_runtime_manager_command_status(command_id)
    except SupervisedRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/evolution/worktree-runs",
    response_model=list[EvolutionRunResponse],
    response_model_exclude_unset=True,
)
def evolution_worktree_runs() -> list[dict]:
    return list_supervised_worktree_runs()


@router.get(
    "/evolution/worktree-runs/active",
    response_model=EvolutionRunResponse | None,
    response_model_exclude_unset=True,
)
def evolution_worktree_active_run() -> dict | None:
    return get_active_supervised_worktree_run()


@router.post(
    "/evolution/worktree-runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def evolution_start_worktree_run(payload: SupervisedWorktreeRunStartPayload) -> dict:
    try:
        data = payload.model_dump()
        data["requestSource"] = "api:evolution.worktree-runs"
        data["initiator"] = "user"
        return start_supervised_worktree_run(data)
    except SupervisedWorktreeRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedWorktreeRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/evolution/self/worktree-runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def self_evolution_start_worktree_run(payload: SelfEvolutionWorktreeRunStartPayload) -> dict:
    try:
        return start_self_evolution_worktree_run(payload.model_dump())
    except (SelfEvolutionRunBusyError, SupervisedWorktreeRunBusyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (SelfEvolutionRunValidationError, SupervisedWorktreeRunValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/evolution/self/observation-runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def self_observation_start_run(payload: SelfObservationRunStartPayload) -> dict:
    try:
        return start_self_observation_run(payload.model_dump())
    except SelfEvolutionRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SelfEvolutionRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/evolution/self/observation-runs/{run_id}",
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def self_observation_run(run_id: str) -> dict:
    snapshot = get_self_observation_run_snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Self observation run not found")
    return snapshot


@router.get(
    "/evolution/self/observation-runs/{run_id}/events",
    response_class=StreamingResponse,
)
def self_observation_run_events(run_id: str) -> StreamingResponse:
    snapshot = get_self_observation_run_snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Self observation run not found")
    return StreamingResponse(
        stream_self_observation_run_events(run_id, initial_snapshot=snapshot),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/evolution/self/observation-runs/{run_id}/actions",
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def self_observation_run_action(run_id: str, payload: SelfObservationRunActionPayload) -> dict:
    try:
        return execute_self_observation_action(run_id, payload.action)
    except SelfEvolutionRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SelfEvolutionRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SelfEvolutionRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/evolution/self/autonomous-runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def self_evolution_start_autonomous_run(
    payload: SelfEvolutionAutonomousRunStartPayload,
) -> dict:
    try:
        return start_autonomous_self_evolution(payload.model_dump())
    except AutonomousLoopConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AutonomousLoopValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/evolution/self/autonomous-runs/active",
    response_model=EvolutionRunResponse | None,
    response_model_exclude_unset=True,
)
def self_evolution_active_autonomous_run() -> dict | None:
    return get_active_autonomous_self_evolution_run()


@router.get(
    "/evolution/self/autonomous-runs/latest",
    response_model=EvolutionRunResponse | None,
    response_model_exclude_unset=True,
)
def self_evolution_latest_autonomous_run() -> dict | None:
    return get_latest_autonomous_self_evolution_run()


@router.get(
    "/evolution/self/autonomous-runs/{run_id}",
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def self_evolution_autonomous_run(run_id: str) -> dict:
    try:
        return get_autonomous_self_evolution_run(run_id)
    except AutonomousLoopValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/evolution/self/autonomous-runs/{run_id}/actions",
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def self_evolution_autonomous_run_action(
    run_id: str,
    payload: SelfEvolutionAutonomousRunActionPayload,
) -> dict:
    action = str(payload.action or "").strip().lower()
    decision = {
        "actorType": "user",
        "actorId": "local-user",
        "comment": payload.comment,
    }
    try:
        if action == "approve":
            return approve_autonomous_self_evolution(
                run_id,
                decision=decision,
            )
        if action == "reject":
            return reject_autonomous_self_evolution(
                run_id,
                decision=decision,
            )
        if action == "retry_cleanup":
            return retry_autonomous_self_evolution_cleanup(run_id)
        raise AutonomousLoopValidationError(
            "Autonomous-loop action must be approve, reject, or retry_cleanup."
        )
    except AutonomousLoopConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AutonomousLoopValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/evolution/worktree-runs/{run_id}",
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def evolution_worktree_run(run_id: str) -> dict:
    snapshot = get_supervised_worktree_run(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Supervised worktree run not found")
    return snapshot


@router.get(
    "/evolution/worktree-runs/{run_id}/events",
    response_class=StreamingResponse,
)
def evolution_worktree_run_events(run_id: str) -> StreamingResponse:
    snapshot = get_supervised_worktree_run(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Supervised worktree run not found")
    return StreamingResponse(
        stream_supervised_worktree_run_events(run_id, initial_snapshot=snapshot),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/evolution/worktree-runs/{run_id}/actions",
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def evolution_worktree_run_action(run_id: str, payload: SupervisedWorktreeRunActionPayload) -> dict:
    try:
        return execute_supervised_worktree_action(
            run_id,
            payload.action,
            force=payload.force,
            reviewer_note=payload.reviewerNote,
        )
    except SupervisedWorktreeRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisedWorktreeRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SupervisedWorktreeRunActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/evolution/runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def evolution_start_run(payload: SupervisedRunStartPayload) -> dict:
    try:
        return start_supervised_run(payload.model_dump())
    except SupervisedRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedAgentBindingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SupervisedRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/evolution/runs/{run_id}/pause",
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def evolution_pause_run(run_id: str) -> dict:
    try:
        return request_pause_supervised_run(run_id)
    except SupervisedRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisedRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/evolution/runs/{run_id}/resume",
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def evolution_resume_run(run_id: str) -> dict:
    try:
        return request_resume_supervised_run(run_id)
    except SupervisedRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisedRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/evolution/runs/{run_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def evolution_retry_run(run_id: str) -> dict:
    try:
        return retry_supervised_run(run_id)
    except SupervisedRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisedRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/evolution/runs/{run_id}/terminate",
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def evolution_terminate_run(run_id: str) -> dict:
    try:
        return request_stop_supervised_run(run_id)
    except SupervisedRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisedRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/evolution/runs/{run_id}",
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def evolution_delete_run(run_id: str) -> dict:
    try:
        return delete_supervised_run_snapshot(run_id)
    except SupervisedRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisedRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SupervisedRunDeleteError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/evolution/runs/{session_id}/actions",
    response_model=EvolutionRunResponse,
    response_model_exclude_unset=True,
)
def evolution_run_action(session_id: str, payload: SupervisedRunActionPayload) -> dict:
    try:
        return execute_supervised_action(session_id, payload.action)
    except SupervisedRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisedRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisedRunActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/evolution/self/overview",
    response_model=EvolutionOverviewResponse,
    response_model_exclude_unset=True,
)
def self_evolution_overview() -> dict:
    return get_self_evolution_overview()


@router.get(
    "/evolution/self/transactions",
    response_model=list[EvolutionRunResponse],
    response_model_exclude_unset=True,
)
def self_evolution_transactions() -> list[dict]:
    return list_self_evolution_transactions()


@router.post(
    "/evolution/self/history/delete",
    response_model=EvolutionDeletedResponse,
    response_model_exclude_unset=True,
)
def self_evolution_delete_history(payload: SelfEvolutionHistoryDeletePayload) -> dict:
    try:
        return delete_self_evolution_history_groups(payload.txnIds)
    except SelfEvolutionHistoryDeleteError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/evolution/self/audit",
    response_model=list[EvolutionRunResponse],
    response_model_exclude_unset=True,
)
def self_evolution_audit() -> list[dict]:
    return list_self_evolution_audit_events()
