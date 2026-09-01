"""Ledger-side helpers for hypothesis candidate fan-out.

This module contains only the narrow authority bridges needed by
``RealDomainPorts``.  It never reads the legacy ``WorkflowRunStore`` and never
looks at a session transcript: candidate selection comes from the frozen run
input or the hypothesis-first authority, while candidate output comes from the
canonical ``hypothesis_fragment`` artifact store.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from core.research.workflow.contracts import PendingAction
from core.web.services.team_workflow.research_runtime.domain_ports import (
    ScopedAgentTaskHandle,
)


class HypothesisAuthorityUnavailable(RuntimeError):
    """The formal hypothesis/task authority could not be read safely.

    A missing row is a valid empty result.  An error while reading the
    authority is different: treating it as absence would allow a retry to
    create a new task/session and silently fork the formal lineage.
    """


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _selection_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = (
        snapshot.get("hypothesisSelection")
        or snapshot.get("hypothesis_selection")
        or snapshot.get("selection")
    )
    selection = _mapping(raw)
    nested = _mapping(selection.get("selection"))
    if nested:
        selection = nested
    selection_id = _text(
        selection.get("selectionId")
        or snapshot.get("hypothesisSelectionId")
        or snapshot.get("selectionId")
    )
    selected_raw = (
        selection.get("selectedCandidateIds")
        or selection.get("candidateIds")
        or snapshot.get("selectedCandidateIds")
    )
    selected = [_text(item) for item in list(selected_raw or []) if _text(item)]
    if not selection_id or not selected:
        return None
    if len(set(selected)) != len(selected):
        raise RuntimeError("hypothesis selection contains duplicate candidate IDs")
    candidates = selection.get("candidateSnapshots") or selection.get("candidates")
    if not isinstance(candidates, list):
        candidates = snapshot.get("hypothesisCandidates")
    snapshots: list[dict[str, Any]] = []
    for item in list(candidates or []):
        if not isinstance(item, Mapping):
            continue
        candidate_id = _text(item.get("candidateId") or item.get("hypothesis_id"))
        if not candidate_id or candidate_id not in selected:
            continue
        snapshots.append(dict(item))
    return {
        **selection,
        "selectionId": selection_id,
        "selectedCandidateIds": selected,
        "candidateSnapshots": snapshots,
    }


def _selection_from_authority(
    snapshot: Mapping[str, Any], *, bound_selection_id: str = ""
) -> dict[str, Any] | None:
    team_id = _text(snapshot.get("teamId"))
    question_id = _text(snapshot.get("questionId"))
    workflow_run_id = _text(snapshot.get("workflowRunId"))
    if not team_id or not question_id:
        return None
    try:
        from core.web.services.team_workflow import hypothesis_selection
        from core.web.services.team_workflow.research_runtime import (
            hypothesis_first_chain,
        )

        selection_id = _text(bound_selection_id)
        if not selection_id:
            chain = hypothesis_first_chain.chain_state(
                team_id,
                question_id,
                **({"workflow_run_id": workflow_run_id} if workflow_run_id else {}),
            )
            selection_id = _text(chain.get("selectionId"))
        if not selection_id:
            return None
        response = hypothesis_selection.get_hypothesis_selection(team_id, selection_id)
        selection = _mapping(response.get("selection"))
        if not selection:
            return None
        selection_run_id = _text(selection.get("workflowRunId"))
        if workflow_run_id and selection_run_id != workflow_run_id:
            raise RuntimeError(
                "current hypothesis selection belongs to another workflow run"
            )
        selected = [_text(item) for item in list(selection.get("selectedCandidateIds") or [])]
        selected = [item for item in selected if item]
        if not selected or len(set(selected)) != len(selected):
            raise RuntimeError("current hypothesis selection is invalid")
        records = hypothesis_first_chain.list_hypothesis_candidates(
            team_id,
            question_id=question_id,
            **({"workflow_run_id": workflow_run_id} if workflow_run_id else {}),
        ).get("candidates") or []
        by_id = {
            _text(item.get("candidateId")): dict(item)
            for item in records
            if isinstance(item, Mapping) and _text(item.get("candidateId"))
        }
        snapshots = [by_id[candidate_id] for candidate_id in selected if candidate_id in by_id]
        if workflow_run_id and len(snapshots) != len(selected):
            raise RuntimeError(
                "current hypothesis selection contains a candidate outside its workflow run"
            )
        return {
            **selection,
            "selectionId": selection_id,
            "workflowRunId": selection_run_id or workflow_run_id,
            "selectedCandidateIds": selected,
            "candidateSnapshots": snapshots,
        }
    except RuntimeError:
        raise
    except Exception as exc:  # authority unavailable is a hard execution blocker
        raise HypothesisAuthorityUnavailable(
            f"current hypothesis selection authority is unavailable: {exc}"
        ) from exc


def formal_hypothesis_fan_out_input(
    *,
    action: PendingAction,
    snapshot: Mapping[str, Any],
    bound_selection_id: str = "",
) -> dict[str, Any] | None:
    """Resolve the frozen/authoritative selection for a formal node action."""

    if action.node_id != "hypothesis_design":
        return None
    # The graph action is the authoritative run fence.  Do not let a stale
    # snapshot field (or a question-only fallback) select another run's chain.
    scoped_snapshot = dict(snapshot)
    workflow_run_id = _text(action.run_id)
    if workflow_run_id:
        scoped_snapshot["workflowRunId"] = workflow_run_id
    selection = _selection_from_snapshot(scoped_snapshot)
    if selection is None:
        selection = _selection_from_authority(
            scoped_snapshot,
            bound_selection_id=bound_selection_id,
        )
    if selection is None:
        raise RuntimeError("hypothesis_design requires a current hypothesis selection")
    selected = list(selection.get("selectedCandidateIds") or [])
    if not selected:
        raise RuntimeError("hypothesis_design selection has no candidates")
    selection_run_id = _text(selection.get("workflowRunId"))
    if workflow_run_id and selection_run_id and selection_run_id != workflow_run_id:
        raise RuntimeError(
            "hypothesis selection belongs to another workflow run"
        )
    for candidate in list(selection.get("candidateSnapshots") or []):
        if not isinstance(candidate, Mapping):
            continue
        candidate_run_id = _text(candidate.get("workflowRunId"))
        if workflow_run_id and candidate_run_id and candidate_run_id != workflow_run_id:
            raise RuntimeError(
                "hypothesis candidate belongs to another workflow run"
            )
    return {
        "selection": {
            **selection,
            **({"workflowRunId": selection_run_id or workflow_run_id} if workflow_run_id else {}),
        },
        "selectionId": _text(selection.get("selectionId")),
        "selectedCandidateIds": selected,
        "candidateSnapshots": list(selection.get("candidateSnapshots") or []),
    }


def hypothesis_max_parallel(snapshot: Mapping[str, Any], count: int) -> int:
    """Return the frozen parallelism limit; absence means the selection size."""

    policy = _mapping(snapshot.get("budgetPolicy"))
    raw = (
        policy.get("maxParallelTasks")
        if "maxParallelTasks" in policy
        else snapshot.get("maxConcurrency")
    )
    if raw is None:
        raw = _mapping(snapshot.get("hypothesisFanOut")).get("maxConcurrency")
    if raw is None:
        return max(1, int(count))
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise RuntimeError("hypothesis fan-out maxConcurrency must be a positive integer")
    return int(raw)


def resolve_formal_node_root_session(
    *,
    team_id: str,
    project_id: str,
    agent_id: str,
    role_key: str,
    workflow_run_id: str,
    workflow_node_id: str,
    created_from_task_id: str,
) -> dict[str, Any]:
    try:
        from core.web.services.team_workflow.research_project_agent_sessions import (
            resolve_research_project_agent_session,
        )

        return resolve_research_project_agent_session(
            team_id,
            research_project_id=project_id,
            agent_id=agent_id,
            role_key=role_key,
            created_from_task_id=created_from_task_id,
            workflow_run_id=workflow_run_id,
            workflow_node_id=workflow_node_id,
        )
    except HypothesisAuthorityUnavailable:
        raise
    except Exception as exc:
        raise HypothesisAuthorityUnavailable(
            f"hypothesis root session authority is unavailable: {exc}"
        ) from exc


def previous_hypothesis_anchor(store: Any, action: PendingAction) -> dict[str, Any]:
    """Load only a prior formal Ledger anchor for retry reuse."""

    try:
        attempts = list(store.list_attempts(action.run_id) or [])
    except Exception as exc:
        raise HypothesisAuthorityUnavailable(
            f"hypothesis attempt authority is unavailable: {exc}"
        ) from exc
    prior = [
        item
        for item in attempts
        if str(getattr(item, "node_id", "") or "") == action.node_id
        and str(getattr(item, "node_run_id", "") or "") != action.node_run_id
        and int(getattr(item, "attempt", 0) or 0) < int(action.attempt or 0)
    ]
    if not prior:
        return {}
    prior_attempt = max(prior, key=lambda item: int(getattr(item, "attempt", 0) or 0))
    prior_node_run_id = _text(getattr(prior_attempt, "node_run_id", ""))
    if not prior_node_run_id:
        return {}
    try:
        row = store.read(lambda repo: repo.get_anchor_by_node_run(prior_node_run_id))
    except Exception as exc:
        raise HypothesisAuthorityUnavailable(
            f"hypothesis anchor authority is unavailable: {exc}"
        ) from exc
    if row is None:
        return {}
    try:
        raw = row[13] if row is not None and len(row) > 13 else ""
        payload = json.loads(raw or "{}")
    except Exception as exc:
        raise HypothesisAuthorityUnavailable(
            f"hypothesis anchor authority is invalid: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise HypothesisAuthorityUnavailable(
            "hypothesis anchor authority returned a non-object payload"
        )
    return payload


def _task_from_status(
    *,
    team_id: str,
    project_id: str,
    workflow_run_id: str,
    workflow_node_id: str,
    selection_id: str,
    candidate_id: str,
) -> dict[str, Any] | None:
    try:
        from core.web.services.team_workflow.research_project_agent_tasks import (
            get_research_project_agent_task_status,
        )

        response = get_research_project_agent_task_status(team_id, project_id)
    except Exception as exc:
        raise HypothesisAuthorityUnavailable(
            f"hypothesis task authority is unavailable: {exc}"
        ) from exc
    if not isinstance(response, Mapping):
        raise HypothesisAuthorityUnavailable(
            "hypothesis task authority returned an invalid response"
        )
    raw_tasks = response.get("tasks")
    if raw_tasks is not None and not isinstance(raw_tasks, (list, tuple)):
        raise HypothesisAuthorityUnavailable(
            "hypothesis task authority returned invalid tasks"
        )
    matches = [
        dict(item)
        for item in list(raw_tasks or [])
        if isinstance(item, Mapping)
        and _text(item.get("workflowRunId")) == workflow_run_id
        and _text(item.get("workflowNodeId")) == workflow_node_id
        and _text(item.get("selectionId")) == selection_id
        and _text(item.get("candidateId")) == candidate_id
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: (_text(item.get("updatedAt")), _text(item.get("taskId"))))


def _started_from_task(task: Mapping[str, Any]) -> dict[str, Any] | None:
    nested_turn = _mapping(task.get("turn"))
    turn_id = _text(
        nested_turn.get("turnId")
        or task.get("startedTurnId")
        or task.get("turnId")
    )
    session_id = _text(task.get("sessionId"))
    task_id = _text(task.get("taskId"))
    if not session_id or not task_id or not turn_id:
        return None
    return {
        "task": dict(task),
        "taskId": task_id,
        "sessionId": session_id,
        "sessionAttempt": int(task.get("sessionAttempt") or 1),
        "startedTurnId": turn_id,
        "turn": {"turnId": turn_id},
    }


def _started_from_anchor(anchor: Mapping[str, Any]) -> dict[str, Any] | None:
    return _started_from_task(anchor)


def _require_formal_task_authority(
    *,
    action: PendingAction,
    agent_id: str,
    challenge_task_contract: Mapping[str, Any],
    model_invocation_receipt_binding: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reject a candidate start without a scoped server-owned authority pair."""

    contract = _mapping(challenge_task_contract)
    receipt = _mapping(model_invocation_receipt_binding)
    run_id = _text(action.run_id)
    node_id = _text(action.node_id)
    node_run_id = _text(action.node_run_id)
    agent = _text(agent_id)
    try:
        attempt = int(action.attempt or 0)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("formal candidate task authority has an invalid attempt") from exc
    if not run_id or not node_id or not node_run_id or not agent or attempt <= 0:
        raise RuntimeError("formal candidate task authority is incomplete")
    if (
        not _text(contract.get("questionId"))
        or not _text(contract.get("workflowId"))
        or not _text(contract.get("workflowVersionId"))
        or _text(contract.get("workflowRunId")) != run_id
        or _text(contract.get("workflowNodeId")) != node_id
        or _text(contract.get("nodeRunId")) != node_run_id
        or _text(contract.get("agentId")) != agent
        or int(contract.get("nodeAttempt") or 0) != attempt
        or len(_text(contract.get("modelPolicySha256"))) != 64
        or not isinstance(contract.get("requiredModelPolicy"), Mapping)
    ):
        raise RuntimeError("formal candidate task contract scope is invalid")
    expected_outcomes: tuple[str, ...]
    expected_stage: str
    try:
        from .agent_node_execution import (
            _MODEL_INVOCATION_OUTCOME_KINDS,
            _MODEL_INVOCATION_STAGES,
        )

        expected_outcomes = _MODEL_INVOCATION_OUTCOME_KINDS.get(node_id, ())
        expected_stage = _MODEL_INVOCATION_STAGES.get(node_id, "")
    except Exception as exc:
        raise RuntimeError("formal candidate task model authority is unavailable") from exc
    receipt_outcomes = tuple(
        _text(item) for item in list(receipt.get("outcomeKinds") or []) if _text(item)
    )
    if (
        not _text(receipt.get("questionId"))
        or _text(receipt.get("workflowId")) != _text(contract.get("workflowId"))
        or _text(receipt.get("workflowVersionId"))
        != _text(contract.get("workflowVersionId"))
        or _text(receipt.get("questionId")).upper()
        != _text(contract.get("questionId")).upper()
        or _text(receipt.get("questionRunId")) != run_id
        or _text(receipt.get("workflowRunId")) != run_id
        or _text(receipt.get("formalNodeId")) != node_id
        or _text(receipt.get("formalNodeRunId")) != node_run_id
        or int(receipt.get("formalNodeAttempt") or 0) != attempt
        or _text(receipt.get("questionStage")) != expected_stage
        or tuple(expected_outcomes) != receipt_outcomes
        or _text(receipt.get("modelPolicySha256")).lower()
        != _text(contract.get("modelPolicySha256")).lower()
    ):
        raise RuntimeError("formal candidate receipt binding scope is invalid")
    return contract, receipt


def resolve_formal_candidate_task(
    *,
    team_id: str,
    project_id: str,
    action: PendingAction,
    agent_id: str,
    source_collection_run_id: str,
    selection_id: str,
    candidate_id: str,
    selected_candidate_ids: list[str],
    candidate_context: dict[str, Any],
    subtask_id: str,
    previous: Mapping[str, Any],
    challenge_task_contract: Mapping[str, Any],
    model_invocation_receipt_binding: Mapping[str, Any],
    hypothesis_input_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Reuse only a sibling that consumed the same composite snapshot."""

    binding = _mapping(hypothesis_input_binding)
    knowledge_snapshot = _mapping(binding.get("knowledgeSnapshot"))
    snapshot_hash = _text(knowledge_snapshot.get("snapshotHash")).lower()
    if (
        binding.get("status") != "ready"
        or len(snapshot_hash) != 64
        or _text(binding.get("workflowRunId")) != action.run_id
        or _text(binding.get("sourceCollectionRunId"))
        != source_collection_run_id
    ):
        raise RuntimeError("formal candidate hypothesis input binding is invalid")

    existing = _task_from_status(
        team_id=team_id,
        project_id=project_id,
        workflow_run_id=action.run_id,
        workflow_node_id=action.node_id,
        selection_id=selection_id,
        candidate_id=candidate_id,
    )
    if existing is not None:
        status = _text(existing.get("status")).lower()
        existing_snapshot_hash = _text(
            existing.get("consumedKnowledgeSnapshotHash")
        ).lower()
        if (
            existing_snapshot_hash == snapshot_hash
            and status
            in {"queued", "running", "completed", "complete", "succeeded"}
        ):
            started = _started_from_task(existing)
            if started is not None:
                return started
        retry_task_id = _text(existing.get("taskId"))
    else:
        retry_task_id = _text(previous.get("taskId"))

    if (
        existing is None
        and _text(previous.get("consumedKnowledgeSnapshotHash")).lower()
        == snapshot_hash
        and _text(previous.get("status")).lower()
        in {"queued", "running", "completed", "complete", "succeeded"}
    ):
        started = _started_from_anchor(previous)
        if started is not None:
            return started

    contract, receipt_binding = _require_formal_task_authority(
        action=action,
        agent_id=agent_id,
        challenge_task_contract=challenge_task_contract,
        model_invocation_receipt_binding=model_invocation_receipt_binding,
    )

    # Failed prior work receives a formal retry. Successful siblings return
    # their canonical Session/Task/Turn and replay only their structured
    # fragment provenance into the new NodeRun.
    formal_retry = bool(retry_task_id)
    idempotency_key = (
        f"agent-task:{action.node_run_id}:hypothesis:{selection_id}:"
        f"{candidate_id}:{snapshot_hash[:16]}"
    )
    from core.web.services.team_workflow.research_project_agent_tasks import (
        start_research_project_agent_task,
    )

    try:
        started = start_research_project_agent_task(
            team_id,
            project_id,
            {
                "taskKind": "hypothesis_design",
                "agentId": agent_id,
                "idempotencyKey": idempotency_key,
                "targetRef": f"hypothesis:{selection_id}:{candidate_id}",
                "workflowRunId": action.run_id,
                "workflowNodeId": action.node_id,
                "nodeRunId": action.node_run_id,
                "selectionId": selection_id,
                "candidateId": candidate_id,
                "selectedCandidateIds": list(selected_candidate_ids),
                "candidateContext": dict(candidate_context),
                "subtaskId": subtask_id,
                "sourceCollectionRunId": source_collection_run_id,
                "formalRetry": formal_retry,
                "retryTaskId": retry_task_id if formal_retry else "",
            },
            _challenge_task_contract=contract,
            _model_invocation_receipt_binding=receipt_binding,
            _hypothesis_input_binding=binding,
        )
    except HypothesisAuthorityUnavailable:
        raise
    except Exception as exc:
        raise HypothesisAuthorityUnavailable(
            f"hypothesis task authority is unavailable: {exc}"
        ) from exc
    return started


def scoped_handle_from_started(
    started: Mapping[str, Any],
    *,
    selection_id: str,
    candidate_id: str,
    subtask_id: str,
    expected_root_session_id: str = "",
    expected_agent_id: str = "",
) -> ScopedAgentTaskHandle:
    task = _mapping(started.get("task"))
    task.update({key: value for key, value in started.items() if key != "task"})
    turn = _mapping(task.get("turn"))
    turn_id = _text(
        turn.get("turnId")
        or task.get("startedTurnId")
        or started.get("startedTurnId")
    )
    session_id = _text(started.get("sessionId") or task.get("sessionId"))
    task_id = _text(started.get("taskId") or task.get("taskId"))
    if not session_id or not task_id or not turn_id:
        raise RuntimeError(f"candidate {candidate_id} returned an incomplete Session/Task/Turn")
    from core.web.services import session_service

    try:
        session_detail = session_service.get_session_detail(
            session_id,
            message_limit=0,
            transcript_scope="none",
        )
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"candidate {candidate_id} canonical Session lineage is unavailable"
        ) from exc
    if not isinstance(session_detail, Mapping):
        raise TypeError(
            f"candidate {candidate_id} canonical Session lineage is unavailable"
        )
    parent_session_id = _text(session_detail.get("parentSessionId"))
    root_session_id = _text(session_detail.get("rootSessionId"))
    canonical_session_id = _text(session_detail.get("id"))
    canonical_agent_id = _text(session_detail.get("agentId"))
    if (
        canonical_session_id != session_id
        or not expected_root_session_id
        or parent_session_id != expected_root_session_id
        or root_session_id != expected_root_session_id
        or (
            expected_agent_id
            and canonical_agent_id
            and canonical_agent_id != expected_agent_id
        )
    ):
        raise RuntimeError(
            f"candidate {candidate_id} canonical Session lineage does not match the node root"
        )
    return ScopedAgentTaskHandle(
        candidate_id=candidate_id,
        selection_id=selection_id,
        session_id=session_id,
        session_attempt=int(started.get("sessionAttempt") or task.get("sessionAttempt") or 1),
        task_id=task_id,
        turn_id=turn_id,
        subtask_id=subtask_id,
        status=_text(task.get("status") or started.get("status")) or "running",
        parent_session_id=parent_session_id,
        root_session_id=root_session_id,
    )


def load_formal_hypothesis_fragment(
    rows: list[dict[str, Any]],
    *,
    node_run_id: str,
    selection_id: str,
    candidate_id: str,
    session_id: str,
    task_id: str,
    session_attempt: int,
) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload") if isinstance(row, Mapping) else None
        if not isinstance(payload, dict):
            continue
        if (
            _text(payload.get("kind")) == "hypothesis_fragment"
            and _text(payload.get("workflowRunId"))
            and _text(payload.get("nodeRunId")) == node_run_id
            and _text(payload.get("selectionId")) == selection_id
            and _text(payload.get("candidateId")) == candidate_id
            and _text(payload.get("sessionId")) == session_id
            and _text(payload.get("taskId")) == task_id
            and int(payload.get("sessionAttempt") or 0) == int(session_attempt)
        ):
            matches.append(dict(payload))
    if len(matches) > 1:
        raise RuntimeError(f"duplicate hypothesis fragments for candidate {candidate_id}")
    return matches[0] if matches else None


def load_reusable_formal_hypothesis_fragment(
    rows: list[dict[str, Any]],
    *,
    workflow_run_id: str,
    selection_id: str,
    candidate_id: str,
    session_id: str,
    task_id: str,
    session_attempt: int,
    preferred_fragment_refs: str | tuple[str, ...] | list[str] | None = (),
) -> dict[str, Any] | None:
    """Load one successful sibling fragment without weakening its scope."""

    matches: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload") if isinstance(row, Mapping) else None
        if not isinstance(payload, dict):
            continue
        if (
            _text(payload.get("kind")) == "hypothesis_fragment"
            and _text(payload.get("workflowRunId")) == workflow_run_id
            and _text(payload.get("selectionId")) == selection_id
            and _text(payload.get("candidateId")) == candidate_id
            and _text(payload.get("sessionId")) == session_id
            and _text(payload.get("taskId")) == task_id
            and int(payload.get("sessionAttempt") or 0) == int(session_attempt)
        ):
            matches.append(dict(payload))
    if isinstance(preferred_fragment_refs, str):
        preferred = [preferred_fragment_refs]
    else:
        preferred = [
            str(item).strip()
            for item in (preferred_fragment_refs or ())
            if str(item).strip()
        ]
    if preferred:
        preferred_matches = [
            item
            for item in matches
            if str(item.get("recordId") or "").strip() in preferred
            or str(item.get("artifactRef") or "").strip() in preferred
            or (
                item.get("_recordId") is not None
                and str(item.get("_recordId") or "").strip() in preferred
            )
        ]
        if len(preferred_matches) == 1:
            return preferred_matches[0]
        # The rows passed by the canonical artifact store carry recordId on
        # the envelope rather than in payload.  Preserve it while matching
        # the prior anchor lineage.
        for row in rows:
            payload = row.get("payload") if isinstance(row, Mapping) else None
            if not isinstance(payload, dict) or payload not in matches:
                continue
            record_id = str(row.get("recordId") or "").strip()
            if record_id in preferred:
                preferred_matches.append(payload)
        unique_preferred = {id(item): item for item in preferred_matches}
        if len(unique_preferred) == 1:
            return next(iter(unique_preferred.values()))
        if not preferred_matches:
            return None
        raise RuntimeError(
            f"duplicate preferred reusable hypothesis fragments for candidate {candidate_id}"
        )
    if len(matches) > 1:
        raise RuntimeError(
            f"duplicate reusable hypothesis fragments for candidate {candidate_id}"
        )
    return matches[0] if matches else None


def candidate_hypothesis_task_context(
    *,
    team_id: str,
    project_id: str,
    action: PendingAction,
    child: ScopedAgentTaskHandle,
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Read the accepted knowledge-package context from task authority."""

    try:
        from core.web.services.team_workflow.research_project_agent_tasks import (
            get_research_project_agent_task_context,
        )

        context = get_research_project_agent_task_context(
            team_id,
            project_id,
            child.task_id,
            require_active=False,
        )
    except Exception as exc:
        raise HypothesisAuthorityUnavailable(
            "hypothesis candidate task context authority is unavailable"
        ) from exc
    if not isinstance(context, Mapping):
        raise HypothesisAuthorityUnavailable(
            "hypothesis candidate task context authority returned an invalid response"
        )
    task = _mapping(context.get("task"))
    hypothesis_input = _mapping(context.get("hypothesisInput"))
    if hypothesis_input.get("status") != "ready":
        raise RuntimeError("accepted knowledge package is not ready for hypothesis fan-in")
    # Rebind identity fields from the formal Ledger action; the task authority
    # remains the source of allowedEvidenceRefs and never the run snapshot.
    task.update(
        {
            "workflowRunId": action.run_id,
            "workflowNodeId": action.node_id,
            "nodeRunId": action.node_run_id,
            "selectionId": child.selection_id,
            "candidateId": child.candidate_id,
            "sessionId": child.session_id,
            "sessionAttempt": child.session_attempt,
            "taskId": child.task_id,
        }
    )
    return {"task": task, "hypothesisInput": hypothesis_input}


def root_hypothesis_task_context(
    *,
    team_id: str,
    action: PendingAction,
    root_session_id: str,
    source_collection_run_id: str,
    child_task_context: Mapping[str, Any],
) -> dict[str, Any]:
    task = {
        "taskId": f"workflow-node:{action.node_run_id}",
        "taskKind": "hypothesis_design",
        "teamId": team_id,
        "workflowRunId": action.run_id,
        "workflowNodeId": action.node_id,
        "nodeRunId": action.node_run_id,
        "sourceCollectionRunId": source_collection_run_id,
        "sessionId": root_session_id,
        "sessionAttempt": 1,
    }
    return {
        "teamId": team_id,
        "task": task,
        "hypothesisInput": _mapping(child_task_context.get("hypothesisInput")),
    }


def mark_candidate_task_completed(
    *,
    team_id: str,
    project_id: str,
    task_id: str,
    completion: Mapping[str, Any],
    result_ref: str = "",
) -> None:
    if not _text(result_ref):
        raise RuntimeError(f"hypothesis candidate {task_id} has no fragment artifact ref")
    from core.web.services.team_workflow.research_project_agent_tasks import (
        update_research_project_agent_task_status,
    )

    try:
        update_research_project_agent_task_status(
            team_id,
            project_id,
            task_id,
            status="completed",
            result_refs=[_text(result_ref)],
        )
    except Exception as exc:
        raise HypothesisAuthorityUnavailable(
            f"hypothesis candidate task authority is unavailable: {exc}"
        ) from exc
    _ = completion


__all__ = [
    "HypothesisAuthorityUnavailable",
    "candidate_hypothesis_task_context",
    "formal_hypothesis_fan_out_input",
    "hypothesis_max_parallel",
    "load_formal_hypothesis_fragment",
    "load_reusable_formal_hypothesis_fragment",
    "mark_candidate_task_completed",
    "previous_hypothesis_anchor",
    "resolve_formal_candidate_task",
    "resolve_formal_node_root_session",
    "root_hypothesis_task_context",
    "scoped_handle_from_started",
]
