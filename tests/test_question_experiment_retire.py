"""Question-scoped experiment retire: store composition and hard guards.

The retire is the cleanup widening of the built-in hypothesis-first question
reset: it must remove exactly one question's registered runs, workflow
artifacts, receipts and research project while leaving approved experiments,
other questions and the team knowledge base untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services import data_processing_service, team_service
from core.web.services.team_workflow import (
    challenge_question_retire,
    challenge_question_runs,
    research_projects,
)
from core.web.services.team_workflow import hypothesis_rounds as hrounds
from core.web.services.team_workflow import hypothesis_selection as selections
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import (
    model_invocation_receipt_registry as receipts,
)
from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from tests._support.team_workflow.helpers import _use_tmp_project_root

_TARGET = "SCI-001"
_KEEP = "SCI-002"


def _retire_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    _use_tmp_project_root(tmp_path, monkeypatch)
    return team_service.create_team(
        name="Retire 验收团队",
        purpose="challenge-workflow-retire",
    )["teamId"]


def _seed_chain_artifacts(team_id: str, question_id: str) -> dict[str, str]:
    suffix = question_id.lower()
    meeting_id = f"meeting-{suffix}"
    selection_id = f"selection-{suffix}"
    candidate_id = f"candidate-{suffix}"
    round_id = f"round-{suffix}"
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.CANDIDATE_KIND,
            "candidateId": candidate_id,
            "questionId": question_id,
            "statement": f"{question_id} candidate",
            "meetingRoundId": meeting_id,
        },
    )
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.COLLECTION_REQUEST_KIND,
            "requestId": f"request-{suffix}",
            "questionId": question_id,
            "meetingRoundId": meeting_id,
            "status": "completed",
        },
    )
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.REVIEW_ROUND_LINK_KIND,
            "linkId": f"link-{suffix}",
            "questionId": question_id,
            "meetingRoundId": meeting_id,
            "selectionId": selection_id,
            "roundIndex": 1,
        },
    )
    selections._append_jsonl(
        selections._storage_path(team_id),
        {"schemaVersion": 1, "selectionId": selection_id, "questionId": question_id},
    )
    meetings._append_jsonl(
        meetings._rounds_path(team_id),
        {
            "schemaVersion": 2,
            "meetingRoundId": meeting_id,
            "question": question_id,
            "meetingType": "hypothesis_review",
            "status": "closed",
        },
    )
    meetings._append_jsonl(
        meetings._digests_path(team_id),
        {"schemaVersion": 2, "digestId": f"digest-{suffix}", "meetingRoundId": meeting_id},
    )
    meetings._append_jsonl(
        meetings._decisions_path(team_id),
        {"schemaVersion": 2, "decisionId": f"decision-{suffix}", "meetingRoundId": meeting_id},
    )
    hrounds._append_jsonl(
        hrounds._storage_path(team_id),
        {
            "schemaVersion": 1,
            "roundId": round_id,
            "status": "closed",
            "meetingRefs": [{"kind": "meeting_round", "id": meeting_id}],
        },
    )
    return {"candidateId": candidate_id, "roundId": round_id}


def _seed_run_record(
    team_id: str, question_id: str, run_id: str, *, status: str
) -> None:
    store_path = challenge_question_runs._store_path(team_id)
    store = challenge_question_runs._read_json(store_path)
    if not store:
        store = {
            "schemaVersion": challenge_question_runs.STORE_SCHEMA_VERSION,
            "storeKind": challenge_question_runs.STORE_KIND,
            "teamId": team_id,
            "records": [],
            "updatedAt": "",
        }
    store.setdefault("records", []).append(
        {
            "recordId": f"record-{run_id}",
            "questionId": question_id,
            "runId": run_id,
            "status": status,
        }
    )
    challenge_question_runs._write_json(store_path, store)
    artifact = challenge_question_runs._artifact_path(team_id, question_id, run_id)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps({"questionId": question_id, "runId": run_id}), encoding="utf-8"
    )
    challenge_question_runs._result_package_artifact_path(
        team_id, question_id, run_id
    ).write_text("{}", encoding="utf-8")


def _seed_receipt(team_id: str, question_id: str, run_id: str) -> Path:
    path = receipts._path(team_id, question_id, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"teamId": team_id, "questionId": question_id, "workflowRunId": run_id}
        ),
        encoding="utf-8",
    )
    return path


def _seed_project(team_id: str, question_id: str) -> dict[str, object]:
    project = research_projects.ensure_challenge_question_project(
        team_id,
        question_id=question_id,
        title=f"{question_id} title",
        topic="retire fixture",
    )["project"]
    workspace = research_projects.resolve_research_project_workspace_root(
        team_id, str(project["projectId"])
    )
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "noise.txt").write_text("noise", encoding="utf-8")
    return {"project": project, "workspace": workspace}


def test_retire_removes_question_scoped_stores_and_keeps_approved_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id = _retire_env(tmp_path, monkeypatch)
    keep = _seed_project(team_id, _KEEP)
    target = _seed_project(team_id, _TARGET)
    keep_chain = _seed_chain_artifacts(team_id, _KEEP)
    target_chain = _seed_chain_artifacts(team_id, _TARGET)
    _seed_run_record(team_id, _KEEP, "run-keep", status="approved")
    _seed_run_record(team_id, _TARGET, "run-target", status="needs_revision")
    workflow_artifact_store.put_workflow_artifact(
        team_id,
        kind="run_artifacts",
        workflow_run_id="run-keep",
        source_collection_run_id="sc-keep",
        payload={"questionId": _KEEP},
    )
    workflow_artifact_store.put_workflow_artifact(
        team_id,
        kind="run_artifacts",
        workflow_run_id="run-target",
        source_collection_run_id="sc-target",
        payload={"questionId": _TARGET},
    )
    keep_receipt = _seed_receipt(team_id, _KEEP, "run-keep")
    target_receipt = _seed_receipt(team_id, _TARGET, "run-target")
    # The question's receipts are removed even when their run id is not part
    # of the registered/formal run set collected for lineage scoping.
    unregistered_receipt = _seed_receipt(team_id, _TARGET, "run-unregistered")

    preview = challenge_question_retire.preview_question_retire(team_id, _TARGET)

    assert preview["canRetire"] is True
    assert preview["blockingReason"] == ""
    assert preview["questionRuns"]["recordCount"] == 1
    assert preview["questionRuns"]["runIds"] == ["run-target"]
    assert preview["workflowArtifacts"]["removedCount"] == 1
    assert preview["modelInvocationReceipts"]["removedCount"] == 2
    assert preview["project"]["found"] is True

    result = challenge_question_retire.retire_question_experiment(
        team_id,
        _TARGET,
        confirmation_question_id=_TARGET,
    )

    assert result["errors"] == []
    assert result["questionRuns"]["removedRunIds"] == ["run-target"]
    assert result["workflowArtifacts"]["removedCount"] == 1
    assert result["modelInvocationReceipts"]["removedCount"] == 2
    assert result["project"]["removed"] is True

    assert (
        challenge_question_runs.list_challenge_question_run_records(
            team_id, question_id=_TARGET
        )
        == []
    )
    kept_records = challenge_question_runs.list_challenge_question_run_records(
        team_id, question_id=_KEEP
    )
    assert [record["runId"] for record in kept_records] == ["run-keep"]
    assert not challenge_question_runs._artifact_path(
        team_id, _TARGET, "run-target"
    ).exists()
    assert challenge_question_runs._artifact_path(
        team_id, _KEEP, "run-keep"
    ).is_file()
    kept_artifacts = workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="run_artifacts"
    )
    assert {row["workflowRunId"] for row in kept_artifacts} == {"run-keep"}
    assert not target_receipt.exists()
    assert not unregistered_receipt.exists()
    assert keep_receipt.is_file()
    assert (
        research_projects.get_research_project_for_question(team_id, _TARGET) is None
    )
    assert (
        research_projects.get_research_project_for_question(team_id, _KEEP) is not None
    )
    store = research_projects.list_research_projects(team_id)
    assert store["activeProjectId"] == research_projects.LEGACY_PROJECT_ID
    assert not Path(str(target["workspace"])).exists()
    assert Path(str(keep["workspace"])).is_dir()

    assert chain.list_hypothesis_candidates(team_id, question_id=_TARGET)["candidates"] == []
    kept_candidates = chain.list_hypothesis_candidates(team_id, question_id=_KEEP)[
        "candidates"
    ]
    assert [item["candidateId"] for item in kept_candidates] == [
        keep_chain["candidateId"]
    ]
    assert [item["roundId"] for item in hrounds.list_hypothesis_rounds(team_id)["rounds"]] == [
        keep_chain["roundId"]
    ]
    assert target_chain["candidateId"] != keep_chain["candidateId"]


def test_retire_refuses_approved_run_without_touching_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id = _retire_env(tmp_path, monkeypatch)
    _seed_project(team_id, _TARGET)
    _seed_run_record(team_id, _TARGET, "run-approved", status="approved")
    receipt = _seed_receipt(team_id, _TARGET, "run-approved")

    preview = challenge_question_retire.preview_question_retire(team_id, _TARGET)

    assert preview["canRetire"] is False
    assert "通过验收" in preview["blockingReason"]
    with pytest.raises(challenge_question_retire.ChallengeQuestionRetireBlockedError):
        challenge_question_retire.retire_question_experiment(
            team_id,
            _TARGET,
            confirmation_question_id=_TARGET,
        )
    assert (
        len(
            challenge_question_runs.list_challenge_question_run_records(
                team_id, question_id=_TARGET
            )
        )
        == 1
    )
    assert receipt.is_file()
    assert research_projects.get_research_project_for_question(team_id, _TARGET) is not None


def test_retire_refuses_golden_sample_and_wrong_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id = _retire_env(tmp_path, monkeypatch)

    golden = challenge_question_retire.preview_question_retire(team_id, "SCI-096")

    assert golden["canRetire"] is False
    assert "深度实验题" in golden["blockingReason"]
    with pytest.raises(challenge_question_retire.ChallengeQuestionRetireBlockedError):
        challenge_question_retire.retire_question_experiment(
            team_id, "SCI-096", confirmation_question_id="SCI-096"
        )

    with pytest.raises(challenge_question_retire.ChallengeQuestionRetireError):
        challenge_question_retire.retire_question_experiment(
            team_id,
            _TARGET,
            confirmation_question_id="SCI-999",
        )


def test_retire_survives_source_runs_owned_by_already_retired_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reset must finish when its source runs' owner project was retired first.

    Live data can reference a run whose owner project no longer exists (the
    earlier cleanup retired that project).  The run directory is gone with the
    owner workspace, but the processing-run authority still needs removal.
    """

    team_id = _retire_env(tmp_path, monkeypatch)
    owner = _seed_project(team_id, _KEEP)["project"]
    _seed_project(team_id, _TARGET)
    orphan_run = data_processing_service.create_processing_run(
        title="orphaned owner run",
        scope={
            "teamId": team_id,
            "questionId": _TARGET,
            "researchProjectId": str(owner["projectId"]),
            "workflowStage": "knowledge_collection",
        },
        metadata={"startedFrom": "team_workflow_source_collection", "teamId": team_id},
    )
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.COLLECTION_REQUEST_KIND,
            "requestId": "request-orphan",
            "questionId": _TARGET,
            "meetingRoundId": "meeting-orphan",
            "status": "completed",
            "collectionRunId": orphan_run["runId"],
        },
    )

    research_projects.remove_challenge_question_project(
        team_id,
        question_id=_KEEP,
        expected_project_id=str(owner["projectId"]),
    )

    result = challenge_question_retire.retire_question_experiment(
        team_id,
        _TARGET,
        confirmation_question_id=_TARGET,
    )

    assert result["errors"] == []
    with pytest.raises(data_processing_service.DataProcessingNotFoundError):
        data_processing_service.get_processing_run(orphan_run["runId"])
