"""Unified runtime projections for evolution workspace surfaces."""

from __future__ import annotations

from typing import Any


RUNTIME_KINDS = {"supervised", "self_worktree", "self_observation"}
ACTIVE_STATUSES = {"queued", "running", "paused", "stopping"}


def build_workspace_runtime_projection(
    *,
    supervised_active_run: dict[str, Any] | None = None,
    self_worktree_active_run: dict[str, Any] | None = None,
    self_observation_active_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project all currently loaded evolution runtimes into one stable shape."""

    active_runs: list[dict[str, Any]] = []
    by_kind: dict[str, dict[str, Any]] = {}
    for kind, snapshot in (
        ("supervised", supervised_active_run),
        ("self_worktree", self_worktree_active_run),
        ("self_observation", self_observation_active_run),
    ):
        projection = build_runtime_projection(snapshot, kind=kind)
        if not projection:
            continue
        active_runs.append(projection)
        by_kind[kind] = projection

    active = _choose_active_projection(active_runs)
    return {
        "active": active,
        "activeRuns": active_runs,
        "byKind": by_kind,
    }


def build_runtime_projection(snapshot: dict[str, Any] | None, *, kind: str) -> dict[str, Any] | None:
    """Return a compact runtime projection without mutating the source snapshot."""

    if not isinstance(snapshot, dict):
        return None
    normalized_kind = str(kind or "").strip()
    if normalized_kind not in RUNTIME_KINDS:
        raise ValueError(f"Unsupported evolution runtime kind: {kind}")

    if normalized_kind == "self_observation":
        workflow_steps = _observation_workflow_steps(snapshot)
    else:
        workflow_steps = _normalize_workflow_steps(snapshot.get("workflowSteps"))

    current_step_id = _current_step_id(workflow_steps, snapshot=snapshot, kind=normalized_kind)
    primary_session_id = _primary_conversation_session_id(workflow_steps, snapshot=snapshot)
    action_states = snapshot.get("actionStates") if isinstance(snapshot.get("actionStates"), dict) else {}

    return {
        "runId": _text(snapshot.get("runId")),
        "kind": normalized_kind,
        "status": _text(snapshot.get("status")),
        "phase": _text(snapshot.get("phase") or snapshot.get("currentPhase") or snapshot.get("runtimeStatus")),
        "currentStepId": current_step_id,
        "workflowSteps": workflow_steps,
        "trajectoryPreview": _trajectory_preview(snapshot, workflow_steps),
        "governanceActions": _governance_actions(action_states),
        "primaryConversationSessionId": primary_session_id,
        "chatRoute": _chat_route(primary_session_id),
        "approvalEvidence": _approval_evidence(snapshot),
    }


def _choose_active_projection(active_runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not active_runs:
        return None
    for kind in ("self_observation", "self_worktree", "supervised"):
        for item in active_runs:
            if item.get("kind") == kind and str(item.get("status") or "").strip().lower() in ACTIVE_STATUSES:
                return item
    return active_runs[-1]


def _normalize_workflow_steps(raw_steps: Any) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for raw in list(raw_steps or []):
        if not isinstance(raw, dict):
            continue
        session_id = _text(raw.get("conversationSessionId"))
        step = {
            "id": _text(raw.get("id")),
            "label": _text(raw.get("label")),
            "ownerKind": _text(raw.get("ownerKind")),
            "role": raw.get("role") if raw.get("role") is None else _text(raw.get("role")),
            "status": _text(raw.get("status")),
            "current": bool(raw.get("current")),
            "summary": _bounded(raw.get("summary")),
            "livePreview": _bounded(raw.get("livePreview")),
            "metrics": raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {},
            "conversationSessionId": session_id,
            "conversationTurnId": _text(raw.get("conversationTurnId")),
            "chatRoute": _text(raw.get("chatRoute")) or _chat_route(session_id),
            "conversationMessages": list(raw.get("conversationMessages") or []),
        }
        if step["id"]:
            steps.append(step)
    return steps


def _observation_workflow_steps(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    status = _text(snapshot.get("status"))
    latest = _bounded(snapshot.get("latestMessage") or snapshot.get("report") or snapshot.get("goal"))
    session_id = _text(snapshot.get("conversationSessionId"))
    return [
        {
            "id": "self_observation",
            "label": "自主观察",
            "ownerKind": "agent",
            "role": "observer",
            "status": status or "pending",
            "current": status.strip().lower() in ACTIVE_STATUSES,
            "summary": _bounded(snapshot.get("goal") or "等待自主观察。"),
            "livePreview": latest,
            "metrics": {
                "durationSeconds": snapshot.get("durationSeconds"),
                "toolCount": len(list(snapshot.get("allowedTools") or [])),
                "messageCount": len(list(snapshot.get("messages") or [])),
            },
            "conversationSessionId": session_id,
            "conversationTurnId": "",
            "chatRoute": _chat_route(session_id),
            "conversationMessages": [],
        }
    ]


def _current_step_id(steps: list[dict[str, Any]], *, snapshot: dict[str, Any], kind: str) -> str:
    for step in steps:
        if bool(step.get("current")):
            return _text(step.get("id"))
    for step in steps:
        if _text(step.get("status")).strip().lower() in {"running", "queued", "paused"}:
            return _text(step.get("id"))
    if steps:
        return _text(steps[-1 if _text(snapshot.get("status")).strip().lower() not in ACTIVE_STATUSES else 0].get("id"))
    if kind == "self_observation":
        return "self_observation"
    return ""


def _primary_conversation_session_id(steps: list[dict[str, Any]], *, snapshot: dict[str, Any]) -> str:
    for step in steps:
        if bool(step.get("current")) and _text(step.get("conversationSessionId")):
            return _text(step.get("conversationSessionId"))
    for step in steps:
        if _text(step.get("conversationSessionId")):
            return _text(step.get("conversationSessionId"))
    return _text(snapshot.get("conversationSessionId") or snapshot.get("candidateConversationSessionId"))


def _trajectory_preview(snapshot: dict[str, Any], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    run_id = _text(snapshot.get("runId"))
    for step in steps:
        summary = _bounded(step.get("livePreview") or step.get("summary"))
        if not summary:
            continue
        preview.append(
            {
                "id": f"{_text(step.get('id'))}:preview",
                "runId": run_id,
                "sessionId": _text(step.get("conversationSessionId")),
                "actor": _text(step.get("role") or step.get("ownerKind")),
                "phase": _text(step.get("id")),
                "kind": "message",
                "summary": summary,
                "outcome": _text(step.get("status")),
                "timestamp": _text(snapshot.get("updatedAt") or snapshot.get("startedAt")),
            }
        )

    for index, message in enumerate(list(snapshot.get("messages") or [])[-3:]):
        summary = _bounded(message)
        if not summary:
            continue
        preview.append(
            {
                "id": f"message:{index}",
                "runId": run_id,
                "sessionId": _text(snapshot.get("conversationSessionId")),
                "actor": "agent",
                "phase": _text(snapshot.get("phase") or snapshot.get("status")),
                "kind": "message",
                "summary": summary,
                "outcome": _text(snapshot.get("status")),
                "timestamp": _text(snapshot.get("updatedAt") or snapshot.get("startedAt")),
            }
        )
    return preview[-6:]


def _governance_actions(action_states: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for action_id, raw_state in action_states.items():
        state = raw_state if isinstance(raw_state, dict) else {}
        normalized_id = _normalize_action_id(action_id)
        actions.append(
            {
                "id": normalized_id,
                "label": _text(state.get("label")) or _default_action_label(normalized_id),
                "enabled": bool(state.get("enabled")),
                "reason": _text(state.get("reason")),
                "risk": _action_risk(normalized_id),
            }
        )
    return actions


def _approval_evidence(snapshot: dict[str, Any]) -> dict[str, Any]:
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    merge_analysis = snapshot.get("mergeAnalysis") if isinstance(snapshot.get("mergeAnalysis"), dict) else {}
    review_gate = snapshot.get("reviewGate") if isinstance(snapshot.get("reviewGate"), dict) else {}
    worktree = snapshot.get("candidateWorktree") if isinstance(snapshot.get("candidateWorktree"), dict) else {}
    return {
        "decision": decision,
        "mergeAnalysis": merge_analysis,
        "reviewGate": review_gate,
        "changedFiles": list(worktree.get("changedFiles") or merge_analysis.get("changedFiles") or []),
        "summary": _bounded(merge_analysis.get("reason") or decision.get("reason") or snapshot.get("latestMessage")),
    }


def _normalize_action_id(value: Any) -> str:
    text = _text(value)
    if text == "approveReview":
        return "approve_review"
    if text == "analyzeMerge":
        return "analyze_merge"
    return text


def _default_action_label(action_id: str) -> str:
    return {
        "terminate": "终止",
        "preserve": "保留",
        "discard": "丢弃",
        "analyze_merge": "检查合并",
        "approve_review": "批准评审",
        "merge": "合并",
        "rollback": "回滚",
    }.get(action_id, action_id)


def _action_risk(action_id: str) -> str:
    if action_id in {"merge", "rollback", "discard"}:
        return "high"
    if action_id in {"approve_review", "analyze_merge", "preserve"}:
        return "medium"
    return "low"


def _chat_route(session_id: str) -> str:
    normalized = _text(session_id)
    return f"/chat?session={normalized}" if normalized else ""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bounded(value: Any, *, limit: int = 280) -> str:
    text = _text(value).replace("\r", " ").replace("\n", " ")
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}…"
