"""Question-scoped experiment retire built on the hypothesis-first reset.

The built-in ``reset_question_chain`` clears a question's hypothesis-first
working artifacts but deliberately leaves four team-level stores behind:
registered Challenge Cup runs, workflow artifacts, model-invocation receipts
and the question's research-project identity.  This module composes that reset
with a narrow, question-scoped removal of those stores, so an old experiment
can be retired without touching approved experiments, the golden sample or the
team knowledge base.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.web.services import team_service
from core.web.services.runtime_scene_service import record_runtime_scene_event
from core.web.services.team_workflow import challenge_question_runs, research_projects
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain,
    workflow_artifact_store,
)
from core.web.services.team_workflow.research_runtime import (
    model_invocation_receipt_registry as receipt_registry,
)

SCHEMA_VERSION = 1


class ChallengeQuestionRetireError(RuntimeError):
    """Base error for question-scoped experiment retire."""


class ChallengeQuestionRetireBlockedError(ChallengeQuestionRetireError):
    """A hard guard (protected question, approved run) blocked the retire."""

    code = "challenge_question_retire_blocked"


class ChallengeQuestionRetirePartialError(ChallengeQuestionRetireError):
    """The chain reset committed but one or more follow-up removals failed."""

    code = "challenge_question_retire_partial"

    def __init__(self, message: str, result: dict[str, Any]) -> None:
        super().__init__(message)
        self.result = result


def _collect_retire_targets(team_id: str, question_id: str) -> dict[str, Any]:
    """Read every run identity owned by one question before the reset writes."""

    records = challenge_question_runs.list_challenge_question_run_records(
        team_id, question_id=question_id
    )
    question_run_ids = {
        str(record.get("runId") or "").strip()
        for record in records
        if str(record.get("runId") or "").strip()
    }
    chain_targets = hypothesis_first_chain.question_reset_targets(team_id, question_id)
    normalized_question = str(question_id or "").strip().upper()
    formal_run_ids: set[str] = set()
    formal_runtime_available = False
    payload: dict[str, Any] = {}
    try:
        from core.web.services.team_workflow.research_runtime.formal_read_runtime import (
            get_query_service,
        )

        payload = get_query_service().list_runs(
            team_id=team_id,
            workflow_id=hypothesis_first_chain.CHALLENGE_CUP_WORKFLOW_ID,
        )
        formal_runtime_available = True
    except Exception:  # noqa: BLE001 - formal runtime absent (command line)
        payload = {}
    for run in list((payload or {}).get("runs") or []):
        if not isinstance(run, Mapping):
            continue
        if str(run.get("questionId") or "").strip().upper() != normalized_question:
            continue
        run_id = str(run.get("runId") or "").strip()
        if run_id:
            formal_run_ids.add(run_id)
    live_formal_run_ids = {
        str(value or "").strip()
        for value in chain_targets.get("liveFormalRunIds") or []
        if str(value or "").strip()
    }
    project = research_projects.get_research_project_for_question(
        team_id, normalized_question
    )
    return {
        "questionId": normalized_question,
        "records": records,
        "questionRunIds": sorted(question_run_ids),
        "formalRunIds": sorted(formal_run_ids),
        "liveFormalRunIds": sorted(live_formal_run_ids),
        "collectionRunIds": [
            str(value) for value in chain_targets.get("collectionRunIds") or [] if value
        ],
        "formalRuntimeAvailable": formal_runtime_available,
        "project": dict(project) if project else {},
        "receiptRunIds": sorted(
            question_run_ids | formal_run_ids | live_formal_run_ids
        ),
    }


def _assert_retire_allowed(
    question_id: str, records: list[dict[str, Any]]
) -> None:
    """Refuse to retire the golden sample, deep-experiment or approved work."""

    from core.web.services.team_workflow.challenge_cup_reset_service import (
        GOLDEN_SAMPLE_QUESTION_ID,
    )

    protected_ids = challenge_question_runs.required_deep_experiment_question_ids() | {
        str(GOLDEN_SAMPLE_QUESTION_ID).strip().upper()
    }
    if question_id in protected_ids:
        raise ChallengeQuestionRetireBlockedError(
            f"{question_id} 是竞赛计划保留的深度实验题（含金样例），不允许退役。"
        )
    if any(str(record.get("status") or "") == "approved" for record in records):
        raise ChallengeQuestionRetireBlockedError(
            "本题已有通过验收的正式运行，按保留策略不允许退役。"
        )


def preview_question_retire(team_id: str, question_id: str) -> dict[str, Any]:
    """Non-mutating retire preview: guards, scope counts and store impact."""

    normalized_team = team_service.assert_team_exists(team_id)
    normalized_question = str(question_id or "").strip().upper()
    if not normalized_question:
        raise ChallengeQuestionRetireError("Question id is required.")
    reset_preview = hypothesis_first_chain.preview_question_reset(
        normalized_team, normalized_question
    )
    targets = _collect_retire_targets(normalized_team, normalized_question)
    blocking_reason = ""
    try:
        _assert_retire_allowed(normalized_question, targets["records"])
    except ChallengeQuestionRetireBlockedError as exc:
        blocking_reason = str(exc)
    if not blocking_reason and not reset_preview.get("canReset"):
        blocking_reason = str(
            reset_preview.get("blockingReason") or "本题当前不能重置。"
        )
    artifact_preview = workflow_artifact_store.remove_workflow_artifacts_for_runs(
        normalized_team,
        workflow_run_ids=targets["receiptRunIds"],
        source_collection_run_ids=targets["collectionRunIds"],
        dry_run=True,
    )
    receipt_preview = receipt_registry.preview_question_model_invocation_receipts(
        normalized_team,
        question_id=normalized_question,
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team,
        "questionId": normalized_question,
        "canRetire": not blocking_reason,
        "blockingReason": blocking_reason,
        "chainReset": reset_preview,
        "project": {
            "found": bool(targets["project"]),
            "projectId": str(targets["project"].get("projectId") or ""),
            "name": str(targets["project"].get("name") or ""),
        },
        "questionRuns": {
            "recordCount": len(targets["records"]),
            "runIds": targets["questionRunIds"],
            "statuses": [
                str(record.get("status") or "") for record in targets["records"]
            ],
        },
        "formalRuns": {
            "runtimeAvailable": targets["formalRuntimeAvailable"],
            "runIds": targets["formalRunIds"],
            "liveRunIds": targets["liveFormalRunIds"],
        },
        "collectionRunIds": targets["collectionRunIds"],
        "workflowArtifacts": {
            "removedCount": artifact_preview["removedCount"],
            "removedByKind": artifact_preview["removedByKind"],
        },
        "modelInvocationReceipts": {
            "removedCount": receipt_preview["receiptCount"],
        },
    }


def retire_question_experiment(
    team_id: str,
    question_id: str,
    *,
    confirmation_question_id: str,
) -> dict[str, Any]:
    """Retire one question's experiment across every question-owned store.

    Step order: collect the question's run identities, run the built-in
    question reset (which also cancels and archives live formal runs), then
    remove the registered runs, workflow artifacts, receipts and the research
    project.  A follow-up failure is reported per step as a partial retire
    instead of pretending the whole operation rolled back.
    """

    normalized_team = team_service.assert_team_exists(team_id)
    normalized_question = str(question_id or "").strip().upper()
    if not normalized_question:
        raise ChallengeQuestionRetireError("Question id is required.")
    if str(confirmation_question_id or "").strip().upper() != normalized_question:
        raise ChallengeQuestionRetireError("请输入当前题号后再确认退役。")
    targets = _collect_retire_targets(normalized_team, normalized_question)
    _assert_retire_allowed(normalized_question, targets["records"])
    reset_result = hypothesis_first_chain.reset_question_chain(
        normalized_team,
        normalized_question,
        confirmation_question_id=normalized_question,
    )
    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team,
        "questionId": normalized_question,
        "chainReset": reset_result,
        "questionRuns": {
            "removedRunIds": [],
            "removedFileCount": 0,
            "failedPaths": [],
        },
        "workflowArtifacts": {"removedCount": 0, "removedByKind": {}},
        "modelInvocationReceipts": {"removedCount": 0, "failedFiles": []},
        "project": {},
        "errors": [],
    }
    if targets["questionRunIds"]:
        try:
            result["questionRuns"] = (
                challenge_question_runs.retire_challenge_question_runs(
                    normalized_team,
                    question_id=normalized_question,
                    run_ids=targets["questionRunIds"],
                )
            )
        except Exception as exc:  # noqa: BLE001 - continue and report per step
            result["errors"].append(f"question runs: {exc}")
    try:
        result["workflowArtifacts"] = (
            workflow_artifact_store.remove_workflow_artifacts_for_runs(
                normalized_team,
                workflow_run_ids=targets["receiptRunIds"],
                source_collection_run_ids=targets["collectionRunIds"],
            )
        )
    except Exception as exc:  # noqa: BLE001 - continue and report per step
        result["errors"].append(f"workflow artifacts: {exc}")
    try:
        result["modelInvocationReceipts"] = (
            receipt_registry.retire_question_model_invocation_receipts(
                normalized_team,
                question_id=normalized_question,
            )
        )
    except Exception as exc:  # noqa: BLE001 - continue and report per step
        result["errors"].append(f"model invocation receipts: {exc}")
    try:
        result["project"] = research_projects.remove_challenge_question_project(
            normalized_team,
            question_id=normalized_question,
            expected_project_id=str(targets["project"].get("projectId") or ""),
        )
    except Exception as exc:  # noqa: BLE001 - continue and report per step
        result["errors"].append(f"research project: {exc}")
    record_runtime_scene_event(
        "team_workflow_orchestration",
        "challenge_question_run",
        "challenge_question_run.retired",
        outcome="succeeded" if not result["errors"] else "partial_failed",
        fields={
            "teamId": normalized_team[:160],
            "questionId": normalized_question[:160],
            "errorCount": len(result["errors"]),
            "removedRunCount": len(
                result["questionRuns"].get("removedRunIds") or []
            ),
            "removedArtifactCount": int(
                result["workflowArtifacts"].get("removedCount") or 0
            ),
            "removedReceiptCount": int(
                result["modelInvocationReceipts"].get("removedCount") or 0
            ),
        },
    )
    if result["errors"]:
        raise ChallengeQuestionRetirePartialError(
            "题目重置已完成，但部分后继清理失败：" + "；".join(result["errors"]),
            result,
        )
    return result


__all__ = [
    "SCHEMA_VERSION",
    "ChallengeQuestionRetireBlockedError",
    "ChallengeQuestionRetireError",
    "ChallengeQuestionRetirePartialError",
    "preview_question_retire",
    "retire_question_experiment",
]
