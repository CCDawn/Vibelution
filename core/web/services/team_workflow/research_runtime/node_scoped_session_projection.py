"""Read-only projection for node-root and candidate-scoped sessions.

The workflow ledger owns task and attempt state.  The Chat session service is
the only authority for parent/root lineage, so this module never derives
those IDs from a task bundle or from a sibling candidate.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable, Mapping
from typing import Any

from core.research.workflow.contracts.session_scope import (
    ContractValidationError,
    WorkflowSessionScopeV3,
)

from .node_execution_support import NodeExecutionError, latest_node_run
from .session_binding_bridge import chat_deep_link

SessionDetailReader = Callable[[str], Mapping[str, Any] | None]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    normalized = _text(value)
    return normalized or None


def _session_kind(detail: Mapping[str, Any]) -> str:
    return _text(detail.get("sessionKind") or detail.get("session_kind")).lower()


def _canonical_root_detail_matches(
    detail: Mapping[str, Any] | None,
    *,
    session_id: str | None,
) -> bool:
    """Accept only a canonical root, while tolerating old v2 root metadata."""

    expected_id = _optional_text(session_id)
    if not isinstance(detail, Mapping) or not expected_id:
        return False
    kind = _session_kind(detail)
    if kind and kind != "main":
        return False
    if _optional_text(detail.get("parentSessionId") or detail.get("parent_session_id")):
        return False
    canonical_root_id = _optional_text(
        detail.get("rootSessionId") or detail.get("root_session_id")
    )
    return not canonical_root_id or canonical_root_id == expected_id


def _canonical_child_detail_matches(
    detail: Mapping[str, Any] | None,
    *,
    session_id: str | None,
    root_session_id: str | None,
    research_project_id: str | None,
    team_id: str,
    run_id: str,
    node_id: str,
    selection_id: str,
    candidate_id: str,
) -> bool:
    """Require canonical hidden-child lineage and the complete v3 scope binding."""

    if not isinstance(detail, Mapping) or not _optional_text(session_id):
        return False
    if _session_kind(detail) != "child":
        return False
    if not (
        detail.get("hiddenFromIndex") is True
        or detail.get("hidden_from_index") is True
    ):
        return False
    expected_root_id = _optional_text(root_session_id)
    parent_id = _optional_text(
        detail.get("parentSessionId") or detail.get("parent_session_id")
    )
    canonical_root_id = _optional_text(
        detail.get("rootSessionId") or detail.get("root_session_id")
    )
    if not expected_root_id or parent_id != expected_root_id or canonical_root_id != expected_root_id:
        return False

    binding = detail.get("experimentBinding") or detail.get("experiment_binding")
    if not isinstance(binding, Mapping):
        return False
    if (
        _optional_text(binding.get("teamId") or binding.get("team_id")) != _optional_text(team_id)
        or _optional_text(binding.get("workflowRunId") or binding.get("workflow_run_id"))
        != _optional_text(run_id)
        or _optional_text(binding.get("workflowNodeId") or binding.get("workflow_node_id"))
        != _optional_text(node_id)
        or _optional_text(binding.get("selectionId") or binding.get("selection_id"))
        != _optional_text(selection_id)
        or _optional_text(binding.get("candidateId") or binding.get("candidate_id"))
        != _optional_text(candidate_id)
    ):
        return False
    detail_agent_id = _optional_text(detail.get("agentId") or detail.get("agent_id"))
    binding_agent_id = _optional_text(binding.get("agentId") or binding.get("agent_id"))
    if (
        not detail_agent_id
        or not binding_agent_id
        or detail_agent_id != binding_agent_id
    ):
        return False
    raw_scope = binding.get("scope")
    if not isinstance(raw_scope, Mapping):
        return False
    try:
        scope = WorkflowSessionScopeV3.from_mapping(raw_scope)
    except ContractValidationError:
        return False
    if (
        scope.kind != "workflow_candidate"
        or scope.teamId != _text(team_id)
        or scope.workflowRunId != _text(run_id)
        or scope.workflowNodeId != _text(node_id)
        or scope.selectionId != _text(selection_id)
        or scope.candidateId != _text(candidate_id)
    ):
        return False
    if detail_agent_id and scope.agentId != detail_agent_id:
        return False
    if binding_agent_id and scope.agentId != binding_agent_id:
        return False
    binding_project_id = _optional_text(
        binding.get("researchProjectId") or binding.get("research_project_id")
    )
    if not binding_project_id or scope.researchProjectId != binding_project_id:
        return False
    expected_project_id = _optional_text(research_project_id)
    return not expected_project_id or binding_project_id == expected_project_id


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _positive_int(value: Any, *, fallback: int | None = None) -> int | None:
    if isinstance(value, bool):
        return fallback
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return fallback
    return normalized if normalized > 0 else fallback


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_text(item) for item in value if _text(item)]


def _fragment_refs(subtask: Mapping[str, Any]) -> list[str]:
    refs = _string_list(subtask.get("fragmentRefs"))
    if not refs:
        refs = _string_list(subtask.get("outputArtifactRefs"))
    singular = _optional_text(subtask.get("fragmentRef"))
    if singular and singular not in refs:
        refs.append(singular)
    return refs


def _root_chat_route(
    *,
    session_id: str | None,
    team_id: str,
    run_id: str,
    node_id: str,
) -> str | None:
    """Open the canonical root container without inventing a task/turn anchor."""

    if not session_id:
        return None
    return_to = "/teams?" + urllib.parse.urlencode(
        {
            "teamId": team_id,
            "researchView": "workflow",
            "runId": run_id,
            "node": node_id,
            "panel": "node",
        }
    )
    return "/chat?" + urllib.parse.urlencode(
        {
            "session": session_id,
            "returnTo": return_to,
            "returnLabel": "workflow",
        }
    )


def _default_session_detail_reader(session_id: str) -> Mapping[str, Any] | None:
    """Read one session from the canonical Chat authority, without transcript."""

    from core.web.services import session_service

    try:
        detail = session_service.get_session_detail(
            session_id,
            message_limit=0,
            transcript_scope="none",
        )
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return None
    return detail if isinstance(detail, Mapping) else None


def _canonical_detail(
    session_id: str | None,
    *,
    reader: SessionDetailReader,
) -> dict[str, Any] | None:
    if not session_id:
        return None
    try:
        raw = reader(session_id)
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return None
    if not isinstance(raw, Mapping):
        return None
    detail = dict(raw)
    detail_id = _optional_text(detail.get("id"))
    if detail_id and detail_id != session_id:
        return None
    return detail


def _bundle_for_node_run(
    record: Mapping[str, Any],
    node_run_id: str,
) -> dict[str, Any]:
    matches = [
        dict(item)
        for item in record.get("taskBundles") or []
        if isinstance(item, Mapping)
        and _text(item.get("parentNodeRunId")) == node_run_id
    ]
    return matches[-1] if matches else {}


def _root_anchor_source(
    node_run: Mapping[str, Any],
    session_binding: Mapping[str, Any] | None,
) -> tuple[str | None, str | None, str | None]:
    """Prefer the NodeRun as a whole; use the old binding only if it has no ID."""

    node_session_id = _optional_text(node_run.get("sessionId"))
    if node_session_id:
        return (
            node_session_id,
            _optional_text(node_run.get("taskId")),
            _optional_text(node_run.get("turnId")),
        )
    binding = _mapping(session_binding)
    return (
        _optional_text(binding.get("sessionId")),
        _optional_text(binding.get("taskId")),
        _optional_text(binding.get("turnId")),
    )


def _root_session(
    *,
    record: Mapping[str, Any],
    node_id: str,
    node_run: Mapping[str, Any],
    bundle: Mapping[str, Any],
    session_binding: Mapping[str, Any] | None,
    reader: SessionDetailReader,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    raw_session_id, task_id, turn_id = _root_anchor_source(
        node_run,
        session_binding,
    )
    raw_detail = _canonical_detail(raw_session_id, reader=reader)
    canonical_root_id = _optional_text(
        (raw_detail or {}).get("rootSessionId")
        or (raw_detail or {}).get("root_session_id")
    )
    canonical_parent_id = _optional_text(
        (raw_detail or {}).get("parentSessionId")
        or (raw_detail or {}).get("parent_session_id")
    )
    raw_root_is_canonical = _canonical_root_detail_matches(
        raw_detail,
        session_id=raw_session_id,
    )

    # A candidate fan-out may leave the legacy NodeRun anchor pointing at the
    # first child.  The canonical child row is allowed to reveal the actual
    # root ID, but never supplies that root's task/turn anchor.
    root_session_id = raw_session_id
    if not raw_root_is_canonical and canonical_root_id and canonical_root_id != raw_session_id:
        root_session_id = canonical_root_id
        task_id = None
        turn_id = None
    elif not raw_root_is_canonical and canonical_parent_id and canonical_parent_id != raw_session_id:
        root_session_id = canonical_parent_id
        task_id = None
        turn_id = None

    root_detail = raw_detail
    if root_session_id and root_session_id != raw_session_id:
        root_detail = _canonical_detail(root_session_id, reader=reader)

    root_canonical_id = _optional_text(
        (root_detail or {}).get("rootSessionId")
        or (root_detail or {}).get("root_session_id")
    )
    parent_session_id = _optional_text(
        (root_detail or {}).get("parentSessionId")
        or (root_detail or {}).get("parent_session_id")
    )
    root_is_canonical = _canonical_root_detail_matches(
        root_detail,
        session_id=root_session_id,
    )
    root_healthy = bool(root_session_id and root_detail and root_is_canonical)
    fragment_refs = _string_list(bundle.get("aggregationArtifactRefs"))
    if not fragment_refs:
        fragment_refs = _string_list(node_run.get("artifactRefs"))
    link = None
    if root_healthy:
        link = chat_deep_link(
            session_id=root_session_id or "",
            task_id=task_id or "",
            turn_id=turn_id or "",
            team_id=_text(record.get("teamId")),
            run_id=_text(record.get("runId")),
            node_id=node_id,
        )
        if link is None:
            link = _root_chat_route(
                session_id=root_session_id,
                team_id=_text(record.get("teamId")),
                run_id=_text(record.get("runId")),
                node_id=node_id,
            )
    if root_healthy:
        degraded_reason = None
    elif not root_session_id:
        degraded_reason = "session_not_started"
    elif root_detail is None:
        degraded_reason = "session_not_found"
    else:
        degraded_reason = "root_lineage_mismatch"
    attempt = _positive_int(
        node_run.get("attempt"),
        fallback=_positive_int(_mapping(session_binding).get("nodeAttempt")),
    )
    anchor = {
        "scopeKind": "workflow_node_root",
        "nodeId": node_id,
        "nodeRunId": _optional_text(node_run.get("nodeRunId")),
        "sessionId": root_session_id,
        "taskId": task_id if root_healthy else None,
        "turnId": turn_id if root_healthy else None,
        "attempt": attempt,
        "sessionAttempt": attempt,
        "status": _optional_text(node_run.get("status"))
        or _optional_text(record.get("status")),
        "parentSessionId": parent_session_id,
        "rootSessionId": root_canonical_id or (root_session_id if root_healthy else None),
        "chatDeepLink": link,
        "chatRoute": link,
        "fragmentRefs": fragment_refs,
        "fragmentRef": fragment_refs[0] if fragment_refs else None,
        "sessionAnchorDegraded": not root_healthy,
        "sessionAnchorDegradedReason": degraded_reason,
    }
    return (anchor if root_session_id else None), raw_detail


def _scoped_session_anchor(
    *,
    record: Mapping[str, Any],
    node_id: str,
    node_run_id: str,
    root_session_id: str | None,
    research_project_id: str | None,
    selection_id: str,
    subtask: Mapping[str, Any],
    reader: SessionDetailReader,
) -> dict[str, Any]:
    scope = _mapping(subtask.get("scope"))
    candidate_id = _optional_text(scope.get("candidateId") or subtask.get("candidateId"))
    session_id = _optional_text(subtask.get("sessionId"))
    task_id = _optional_text(subtask.get("taskId"))
    turn_id = _optional_text(subtask.get("turnId"))
    detail = _canonical_detail(session_id, reader=reader)
    parent_session_id = _optional_text(
        (detail or {}).get("parentSessionId")
        or (detail or {}).get("parent_session_id")
    )
    canonical_root_id = _optional_text(
        (detail or {}).get("rootSessionId")
        or (detail or {}).get("root_session_id")
    )
    canonical_child = _canonical_child_detail_matches(
        detail,
        session_id=session_id,
        root_session_id=root_session_id,
        research_project_id=research_project_id,
        team_id=_text(record.get("teamId")),
        run_id=_text(record.get("runId")),
        node_id=node_id,
        selection_id=selection_id,
        candidate_id=candidate_id or "",
    )
    anchor_complete = bool(session_id and task_id and turn_id)
    degraded = not (anchor_complete and canonical_child)
    if not root_session_id:
        degraded_reason = "root_session_degraded"
    elif not session_id:
        degraded_reason = "session_not_started"
    elif detail is None:
        degraded_reason = "session_not_found"
    elif not canonical_child:
        degraded_reason = "candidate_scope_mismatch"
    elif not anchor_complete:
        degraded_reason = "task_turn_anchor_incomplete"
    else:
        degraded_reason = None
    link = None
    if not degraded:
        link = chat_deep_link(
            session_id=session_id or "",
            task_id=task_id or "",
            turn_id=turn_id or "",
            team_id=_text(record.get("teamId")),
            run_id=_text(record.get("runId")),
            node_id=node_id,
        )
    refs = _fragment_refs(subtask)
    attempt = _positive_int(subtask.get("attempt"))
    return {
        "scopeKind": "workflow_candidate",
        "nodeId": node_id,
        "nodeRunId": node_run_id,
        "selectionId": selection_id or _optional_text(scope.get("selectionId")),
        "candidateId": candidate_id,
        "subtaskId": _optional_text(subtask.get("subtaskId")),
        "sessionId": session_id,
        "taskId": task_id,
        "turnId": turn_id,
        "attempt": attempt,
        "sessionAttempt": attempt,
        "status": _optional_text(subtask.get("status")),
        "parentSessionId": parent_session_id,
        "rootSessionId": canonical_root_id,
        "chatDeepLink": link,
        "chatRoute": link,
        "fragmentRefs": refs,
        "fragmentRef": refs[0] if refs else None,
        "outputArtifactRefs": refs,
        "sessionAnchorDegraded": degraded,
        "sessionAnchorDegradedReason": degraded_reason,
    }


def project_node_scoped_sessions(
    record: Mapping[str, Any],
    node_id: str,
    *,
    session_binding: Mapping[str, Any] | None = None,
    session_detail_reader: SessionDetailReader | None = None,
) -> dict[str, Any]:
    """Project the latest node root and its ordered candidate child sessions."""

    reader = session_detail_reader or _default_session_detail_reader
    try:
        node_run = latest_node_run(dict(record), node_id)
    except NodeExecutionError:
        return {"rootSession": None, "scopedSessions": []}

    bundle = _bundle_for_node_run(record, _text(node_run.get("nodeRunId")))
    root, _raw_root_detail = _root_session(
        record=record,
        node_id=node_id,
        node_run=node_run,
        bundle=bundle,
        session_binding=session_binding,
        reader=reader,
    )
    root_session_id = (
        _optional_text(root.get("sessionId"))
        if root and not root.get("sessionAnchorDegraded")
        else None
    )
    research_project_id = _optional_text(
        record.get("researchProjectId") or record.get("projectId")
    )
    subtasks = [
        dict(item)
        for item in bundle.get("subtasks") or []
        if isinstance(item, Mapping)
    ]
    selection_id = _optional_text(bundle.get("selectionId"))
    selection = _mapping(bundle.get("selection"))
    selection_id = selection_id or _optional_text(selection.get("selectionId"))
    if not selection_id:
        for subtask in subtasks:
            scope = _mapping(subtask.get("scope"))
            selection_id = _optional_text(scope.get("selectionId"))
            if selection_id:
                break

    scoped_sessions: list[dict[str, Any]] = []
    for subtask in subtasks:
        scope = _mapping(subtask.get("scope"))
        subtask_selection_id = _optional_text(
            scope.get("selectionId") or subtask.get("selectionId")
        )
        candidate_id = _optional_text(
            scope.get("candidateId") or subtask.get("candidateId")
        )
        if not candidate_id or not subtask_selection_id:
            continue
        if selection_id and subtask_selection_id != selection_id:
            continue
        scoped_sessions.append(
            _scoped_session_anchor(
                record=record,
                node_id=node_id,
                node_run_id=_text(node_run.get("nodeRunId")),
                root_session_id=root_session_id,
                research_project_id=research_project_id,
                selection_id=subtask_selection_id,
                subtask=subtask,
                reader=reader,
            )
        )
    return {"rootSession": root, "scopedSessions": scoped_sessions}


def _ledger_anchor_payload(anchor: tuple[Any, ...] | None) -> dict[str, Any]:
    if anchor is None or len(anchor) <= 13:
        return {}
    try:
        payload = json.loads(anchor[13] or "{}")
    except (TypeError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _ledger_root_session(
    raw: Mapping[str, Any],
    *,
    team_id: str,
    run_id: str,
    node_id: str,
    node_run_id: str | None,
    node_status: str | None,
    reader: SessionDetailReader,
) -> dict[str, Any] | None:
    session_id = _optional_text(raw.get("sessionId"))
    if not session_id:
        return None
    detail = _canonical_detail(session_id, reader=reader)
    canonical_root_id = _optional_text(
        (detail or {}).get("rootSessionId")
        or (detail or {}).get("root_session_id")
    )
    parent_session_id = _optional_text(
        (detail or {}).get("parentSessionId")
        or (detail or {}).get("parent_session_id")
    )
    canonical_root = _canonical_root_detail_matches(
        detail,
        session_id=session_id,
    )
    if detail is None:
        degraded_reason = "session_not_found"
    elif not canonical_root:
        degraded_reason = "root_lineage_mismatch"
    else:
        degraded_reason = None
    link = (
        _root_chat_route(
            session_id=session_id,
            team_id=team_id,
            run_id=run_id,
            node_id=node_id,
        )
        if canonical_root
        else None
    )
    return {
        "scopeKind": "workflow_node_root",
        "nodeId": node_id,
        "nodeRunId": node_run_id,
        "sessionId": session_id,
        "taskId": _optional_text(raw.get("taskId")) if canonical_root else None,
        "turnId": _optional_text(raw.get("turnId")) if canonical_root else None,
        "attempt": _positive_int(raw.get("attempt") or raw.get("sessionAttempt")),
        "sessionAttempt": _positive_int(
            raw.get("sessionAttempt") or raw.get("attempt")
        ),
        "status": _optional_text(raw.get("status")) or node_status,
        "parentSessionId": parent_session_id,
        "rootSessionId": canonical_root_id or (session_id if canonical_root else None),
        "chatDeepLink": link,
        "chatRoute": link,
        "fragmentRef": _optional_text(raw.get("fragmentRef")),
        "fragmentRefs": _string_list(raw.get("fragmentRefs")),
        "sessionAnchorDegraded": not canonical_root,
        "sessionAnchorDegradedReason": degraded_reason,
    }


def _ledger_candidate_session(
    raw: Mapping[str, Any],
    *,
    root_session_id: str | None,
    team_id: str,
    run_id: str,
    node_id: str,
    node_run_id: str | None,
    reader: SessionDetailReader,
) -> dict[str, Any] | None:
    candidate_id = _optional_text(raw.get("candidateId"))
    selection_id = _optional_text(raw.get("selectionId"))
    session_id = _optional_text(raw.get("sessionId"))
    if not candidate_id or not selection_id:
        return None
    task_id = _optional_text(raw.get("taskId"))
    turn_id = _optional_text(raw.get("turnId"))
    detail = _canonical_detail(session_id, reader=reader)
    parent_session_id = _optional_text(
        (detail or {}).get("parentSessionId")
        or (detail or {}).get("parent_session_id")
    )
    canonical_root_id = _optional_text(
        (detail or {}).get("rootSessionId")
        or (detail or {}).get("root_session_id")
    )
    binding_scope = _mapping(detail.get("experimentBinding")) if detail else {}
    scope = binding_scope.get("scope")
    expected_project_id = _optional_text(
        scope.get("researchProjectId")
        if isinstance(scope, Mapping)
        else None
    )
    canonical_child = _canonical_child_detail_matches(
        detail,
        session_id=session_id,
        root_session_id=root_session_id,
        research_project_id=expected_project_id,
        team_id=team_id,
        run_id=run_id,
        node_id=node_id,
        selection_id=selection_id,
        candidate_id=candidate_id,
    )
    lineage_ok = bool(detail and task_id and turn_id and canonical_child)
    if not session_id:
        degraded_reason = "session_not_started"
    elif not root_session_id:
        degraded_reason = "root_session_degraded"
    elif detail is None:
        degraded_reason = "session_not_found"
    elif not task_id or not turn_id:
        degraded_reason = "task_turn_anchor_incomplete"
    elif not canonical_child:
        degraded_reason = "candidate_scope_mismatch"
    elif not lineage_ok:
        degraded_reason = "candidate_lineage_mismatch"
    else:
        degraded_reason = None
    link = (
        chat_deep_link(
            session_id=session_id,
            task_id=task_id or "",
            turn_id=turn_id or "",
            team_id=team_id,
            run_id=run_id,
            node_id=node_id,
        )
        if lineage_ok
        else None
    )
    refs = _fragment_refs(raw)
    attempt = _positive_int(raw.get("sessionAttempt") or raw.get("attempt"))
    return {
        "scopeKind": "workflow_candidate",
        "nodeId": node_id,
        "nodeRunId": node_run_id,
        "selectionId": selection_id,
        "candidateId": candidate_id,
        "subtaskId": _optional_text(raw.get("subtaskId")),
        "sessionId": session_id,
        "taskId": task_id,
        "turnId": turn_id,
        "attempt": attempt,
        "sessionAttempt": attempt,
        "status": _optional_text(raw.get("status")),
        "parentSessionId": parent_session_id,
        "rootSessionId": canonical_root_id,
        "chatDeepLink": link,
        "chatRoute": link,
        "fragmentRef": refs[0] if refs else None,
        "fragmentRefs": refs,
        "outputArtifactRefs": refs,
        "sessionAnchorDegraded": not lineage_ok,
        "sessionAnchorDegradedReason": degraded_reason,
    }


def project_ledger_scoped_sessions(
    anchor: tuple[Any, ...] | None,
    *,
    team_id: str,
    run_id: str,
    node_id: str,
    node_run_id: str | None,
    node_status: str | None,
    session_detail_reader: SessionDetailReader | None = None,
) -> dict[str, Any]:
    """Project formal root/child anchors exclusively from one Ledger row."""

    payload = _ledger_anchor_payload(anchor)
    raw_root = payload.get("rootSession")
    raw_scoped = payload.get("scopedSessions")
    formal_projection = "rootSession" in payload or "scopedSessions" in payload
    if not formal_projection:
        return {
            "rootSession": None,
            "scopedSessions": [],
            "_formalProjection": False,
        }
    reader = session_detail_reader or _default_session_detail_reader
    root = _ledger_root_session(
        dict(raw_root) if isinstance(raw_root, Mapping) else {},
        team_id=team_id,
        run_id=run_id,
        node_id=node_id,
        node_run_id=node_run_id,
        node_status=node_status,
        reader=reader,
    )
    root_session_id = (
        _optional_text((root or {}).get("sessionId"))
        if root and not root.get("sessionAnchorDegraded")
        else None
    )
    scoped: list[dict[str, Any]] = []
    for item in raw_scoped or []:
        if not isinstance(item, Mapping):
            continue
        projected = _ledger_candidate_session(
            item,
            root_session_id=root_session_id,
            team_id=team_id,
            run_id=run_id,
            node_id=node_id,
            node_run_id=node_run_id,
            reader=reader,
        )
        if projected is not None:
            scoped.append(projected)
    return {
        "rootSession": root,
        "scopedSessions": scoped,
        "_formalProjection": True,
    }


__all__ = ["project_ledger_scoped_sessions", "project_node_scoped_sessions"]
