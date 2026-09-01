"""Close one hypothesis candidate subtask and deterministically fan in the set."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .hypothesis_artifact_writer import record_hypothesis_set_from_fragments
from .hypothesis_fragment_writer import record_hypothesis_fragment
from .store import WorkflowRunStore
from .task_bundle_lifecycle import (
    complete_agent_task_bundle_subtask,
    complete_task_bundle_records,
)
from .workflow_artifact_store import list_workflow_artifacts, put_workflow_artifact


def _text(value: Any) -> str:
    return str(value or "").strip()


def _task(task_context: Mapping[str, Any]) -> dict[str, Any]:
    value = task_context.get("task")
    return dict(value) if isinstance(value, Mapping) else {}


def load_hypothesis_fan_out_input(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze the current ordered selection and canonical candidate snapshots."""
    input_snapshot = record.get("inputSnapshot")
    input_snapshot = input_snapshot if isinstance(input_snapshot, Mapping) else {}
    question_id = _text(input_snapshot.get("questionId"))
    if not question_id:
        raise ValueError("candidate fan-out requires inputSnapshot.questionId")
    from core.web.services.team_workflow import challenge_question_runs, hypothesis_selection
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
    )

    team_id = _text(record.get("teamId"))
    workflow_run_id = _text(
        record.get("runId")
        or record.get("workflowRunId")
        or input_snapshot.get("workflowRunId")
    )
    if not workflow_run_id:
        raise ValueError("candidate fan-out requires a workflow run id")
    chain = hypothesis_first_chain.chain_state(
        team_id,
        question_id,
        workflow_run_id=workflow_run_id,
    )
    selection_id = _text(chain.get("selectionId"))
    if not selection_id:
        raise ValueError("hypothesis_design requires a current hypothesis selection")
    selection = hypothesis_selection.get_hypothesis_selection(
        team_id, selection_id
    ).get("selection") or {}
    if _text(selection.get("questionId")).upper() != question_id.upper():
        raise ValueError("current hypothesis selection belongs to another question")
    if _text(selection.get("workflowRunId")) != workflow_run_id:
        raise ValueError("current hypothesis selection belongs to another workflow run")
    selected_candidate_ids = [
        _text(item)
        for item in list(selection.get("selectedCandidateIds") or [])
        if _text(item)
    ]
    if not selected_candidate_ids:
        raise ValueError("current hypothesis selection has no candidates")

    candidate_records = hypothesis_first_chain.list_hypothesis_candidates(
        team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
    ).get("candidates") or []
    by_id: dict[str, dict[str, Any]] = {
        _text(item.get("candidateId")): dict(item)
        for item in candidate_records
        if isinstance(item, dict) and _text(item.get("candidateId"))
    }
    # An approved v2 run can provide the selected hypotheses without a
    # candidate-generation meeting. Hydrate only that same run's persisted
    # output; a team/question-wide approved-details fallback could leak a
    # sibling run's candidates into this fan-out.
    try:
        detail = challenge_question_runs.get_challenge_question_run_detail(
            team_id,
            question_id,
            run_id=workflow_run_id,
        )
    except ValueError as exc:
        if not str(exc).startswith("challenge_question_run_not_found"):
            raise
        detail = {}
    output = detail.get("output") if isinstance(detail, Mapping) else {}
    hypotheses = (
        output.get("hypotheses")
        if isinstance(output, Mapping) and isinstance(output.get("hypotheses"), list)
        else []
    )
    for item in hypotheses:
        if not isinstance(item, Mapping):
            continue
        candidate_id = _text(item.get("hypothesis_id") or item.get("candidateId"))
        if candidate_id:
            by_id.setdefault(candidate_id, dict(item))
    snapshots: list[dict[str, Any]] = []
    for index, candidate_id in enumerate(selected_candidate_ids):
        source = by_id.get(candidate_id) or {}
        statement = _text(
            source.get("statement")
            or source.get("claim")
            or source.get("hypothesis")
        )
        if not statement:
            raise ValueError(
                f"selected candidate {candidate_id} has no canonical statement"
            )
        snapshots.append(
            {
                "candidateId": candidate_id,
                "selectionId": selection_id,
                "candidateOrder": index,
                "statement": statement,
                "mechanism": _text(
                    source.get("mechanism") or source.get("rationale")
                ),
                "predictions": list(source.get("predictions") or []),
            }
        )
    return {
        "selection": dict(selection),
        "selectionId": selection_id,
        "selectedCandidateIds": selected_candidate_ids,
        "candidateSnapshots": snapshots,
    }


def _current_selection(
    team_id: str,
    question_id: str,
    selection_id: str,
    workflow_run_id: str = "",
) -> dict[str, Any]:
    from core.web.services.team_workflow import hypothesis_selection
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

    state = hypothesis_first_chain.chain_state(
        team_id,
        question_id,
        **({"workflow_run_id": workflow_run_id} if workflow_run_id else {}),
    )
    if _text(state.get("selectionId")) != selection_id:
        raise ValueError(
            "The bound hypothesis selection is no longer current; restart the node for the new selection."
        )
    selection = hypothesis_selection.get_hypothesis_selection(
        team_id, selection_id
    ).get("selection")
    if not isinstance(selection, dict):
        raise ValueError("The bound hypothesis selection cannot be read.")
    if workflow_run_id and _text(selection.get("workflowRunId")) != workflow_run_id:
        raise ValueError("The bound hypothesis selection belongs to another workflow run.")
    return selection


def _candidate_bindings(bundle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    bindings: dict[str, dict[str, Any]] = {}
    for subtask in bundle.get("subtasks") or []:
        if not isinstance(subtask, Mapping):
            continue
        scope = subtask.get("scope") if isinstance(subtask.get("scope"), Mapping) else {}
        candidate_id = _text(scope.get("candidateId"))
        if not candidate_id:
            continue
        bindings[candidate_id] = {
            "candidateId": candidate_id,
            "selectionId": _text(scope.get("selectionId")),
            "taskId": _text(subtask.get("taskId")),
            "sessionId": _text(subtask.get("sessionId")),
            "sessionAttempt": int(subtask.get("attempt") or 1),
        }
    return bindings


def record_candidate_fragment_and_maybe_aggregate(
    *,
    team_id: str,
    task_context: Mapping[str, Any],
    payload: Mapping[str, Any],
    store: WorkflowRunStore | None = None,
) -> dict[str, Any]:
    """Persist one fragment, close only its subtask, and fan in when complete."""
    task = _task(task_context)
    required = (
        "researchProjectId",
        "workflowRunId",
        "workflowNodeId",
        "nodeRunId",
        "selectionId",
        "candidateId",
        "subtaskId",
    )
    missing = [field for field in required if not _text(task.get(field))]
    if missing:
        raise ValueError(
            "Candidate hypothesis task is missing scope: " + ", ".join(missing)
        )
    if _text(task.get("workflowNodeId")) != "hypothesis_design":
        raise ValueError("Candidate fragment writeback requires hypothesis_design.")

    run_store = store or WorkflowRunStore()
    run = run_store.get_run(_text(task["workflowRunId"]))
    if not isinstance(run, dict):
        raise ValueError("The bound workflow run cannot be read.")
    question_id = _text((run.get("inputSnapshot") or {}).get("questionId"))
    selection = _current_selection(
        team_id,
        question_id,
        _text(task["selectionId"]),
        _text(task["workflowRunId"]),
    )

    fragment_result = record_hypothesis_fragment(
        team_id=team_id,
        task_context=task_context,
        payload=payload,
        persist=True,
        artifact_sink=put_workflow_artifact,
    )
    fragment_ref = _text((fragment_result.get("artifact") or {}).get("recordId"))
    bundle = complete_agent_task_bundle_subtask(
        run_store,
        run_id=_text(task["workflowRunId"]),
        node_run_id=_text(task["nodeRunId"]),
        subtask_id=_text(task["subtaskId"]),
        output_artifact_refs=[fragment_ref],
        attempt=int(task.get("sessionAttempt") or 1),
    )
    response: dict[str, Any] = {
        "status": "fragment_recorded",
        "fragment": fragment_result,
        "taskBundle": bundle,
        "aggregation": None,
    }
    if bundle.get("status") != "succeeded":
        return response

    bindings = _candidate_bindings(bundle)
    bound_task_ids = {item["taskId"] for item in bindings.values() if item["taskId"]}
    fragments = [
        dict(row.get("payload") or {})
        for row in list_workflow_artifacts(
            team_id,
            kind="hypothesis_fragment",
            workflow_run_id=_text(task["workflowRunId"]),
        )
        if isinstance(row.get("payload"), dict)
        and _text(row["payload"].get("selectionId")) == _text(task["selectionId"])
        and _text(row["payload"].get("nodeRunId")) == _text(task["nodeRunId"])
        and _text(row["payload"].get("taskId")) in bound_task_ids
    ]
    aggregation = record_hypothesis_set_from_fragments(
        team_id=team_id,
        task_context=dict(task_context),
        selection=selection,
        fragments=fragments,
        scope={
            "workflowRunId": _text(task["workflowRunId"]),
            "workflowNodeId": _text(task["workflowNodeId"]),
            "nodeRunId": _text(task["nodeRunId"]),
            "selectionId": _text(task["selectionId"]),
            "candidateScopes": bindings,
        },
        artifact_identity=(
            f"hypothesis_set:{_text(task['selectionId'])}:"
            f"{_text(task['nodeRunId'])}:v1"
        ),
    )
    aggregation_artifact = aggregation.get("artifact") or {}
    hypothesis_set_ref = _text(aggregation_artifact.get("recordId"))
    if not hypothesis_set_ref:
        raise ValueError("Hypothesis aggregation did not persist a canonical artifact.")

    def attach_aggregation_ref(current: dict[str, Any]) -> dict[str, Any]:
        return {
            **current,
            "taskBundles": complete_task_bundle_records(
                current,
                node_run_id=_text(task["nodeRunId"]),
                output_artifact_refs=[hypothesis_set_ref],
                completed_at=_text(aggregation_artifact.get("updatedAt")),
            ),
        }

    persisted = run_store.mutate_run(
        _text(task["workflowRunId"]),
        attach_aggregation_ref,
    )
    bundle = next(
        dict(item)
        for item in persisted.get("taskBundles") or []
        if _text(item.get("parentNodeRunId")) == _text(task["nodeRunId"])
    )

    from core.web.services.team_workflow.research_project_agent_tasks import (
        TERMINAL_STATUSES,
        get_research_project_agent_task_status,
        update_research_project_agent_task_status,
    )

    # Fan-in must not rewind siblings that already reached a terminal status
    # (completed/failed/...): only still-active candidates are held at
    # "running" until their own completion writeback lands.
    status_by_task = {
        _text(item.get("taskId")): _text(item.get("status"))
        for item in (
            get_research_project_agent_task_status(
                team_id,
                _text(task["researchProjectId"]),
            ).get("tasks")
            or []
        )
    }

    for candidate_binding in bindings.values():
        task_id = _text(candidate_binding.get("taskId"))
        if not task_id:
            continue
        if status_by_task.get(task_id, "") in TERMINAL_STATUSES:
            continue
        own_fragment_ref = next(
            (
                _text(item.get("recordId"))
                for item in list_workflow_artifacts(
                    team_id,
                    kind="hypothesis_fragment",
                    workflow_run_id=_text(task["workflowRunId"]),
                )
                if isinstance(item.get("payload"), dict)
                and _text(item["payload"].get("taskId")) == task_id
            ),
            "",
        )
        update_research_project_agent_task_status(
            team_id,
            _text(task["researchProjectId"]),
            task_id,
            status="running",
            result_refs=[ref for ref in (own_fragment_ref, hypothesis_set_ref) if ref],
        )
    response.update(
        {
            "status": "aggregated",
            "aggregation": aggregation,
            "hypothesisSetRef": hypothesis_set_ref,
            "taskBundle": bundle,
        }
    )
    return response


__all__ = [
    "load_hypothesis_fan_out_input",
    "record_candidate_fragment_and_maybe_aggregate",
]
