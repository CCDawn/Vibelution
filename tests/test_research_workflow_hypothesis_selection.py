"""HF-1 hypothesis selection record contract and append-only service tests."""

from __future__ import annotations

import json

import pytest

from core.research.workflow.contracts import (
    MAX_SELECTED_CANDIDATES,
    ContractValidationError,
    HypothesisSelectionRecord,
    scope_hash_for,
)
from core.web.services import team_service
from core.web.services.team_workflow import hypothesis_selection as selections
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain,
    question_launch,
)

_APPROVED_GATE_KEYS = (
    "H1_problem_understanding",
    "H2_hypothesis_selection",
    "H3_research_plan",
    "H4_external_output",
)


def _team(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(selections, "PROJECT_ROOT", tmp_path)
    return team_service.create_team(name="selection team")["teamId"]


def _approved_detail(question_id: str, candidate_ids: tuple[str, ...]) -> dict:
    record = {
        "questionId": question_id,
        "runId": f"stage1-{question_id.lower()}-v1",
        "schemaVersion": 2,
        "submissionEligible": True,
        "status": "approved",
        "humanGates": {
            "allApproved": True,
            "decisions": {key: "approved" for key in _APPROVED_GATE_KEYS},
        },
        "validation": {
            "schemaValidation": "passed",
            "citationValidation": "passed",
            "officialModelCall": True,
        },
    }
    output = {
        "schema_version": 2,
        "identity": {
            "catalog_id": "science-125-questions-2021",
            "question_id": question_id,
            "question_en": "Fixture question",
        },
        "hypotheses": [
            {"hypothesis_id": candidate_id, "statement": f"candidate {candidate_id}"}
            for candidate_id in candidate_ids
        ],
        "selection": {"selected_hypothesis_id": candidate_ids[0]},
        "review": {"human_review_status": "passed"},
        "submission": {"eligible": True},
    }
    return {
        "teamId": "selection team",
        "questionId": question_id,
        "selectedRunId": record["runId"],
        "record": record,
        "output": output,
        "artifact": {"sha256": "b" * 64, "immutable": True},
    }


def _patch_approved_question(
    monkeypatch: pytest.MonkeyPatch,
    *,
    question_id: str = "SCI-096",
    candidate_ids: tuple[str, ...] = ("hyp-a", "hyp-b", "hyp-c"),
) -> None:
    detail = _approved_detail(question_id, candidate_ids)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {
            "completedQuestionIds": [question_id],
            "completedQuestionResults": [dict(detail["record"])],
        },
    )
    monkeypatch.setattr(
        question_launch,
        "get_challenge_question_run_detail",
        lambda _team_id, requested, *, run_id="": detail,
    )


def _scope(**overrides):
    payload = {
        "program": "XH-202619",
        "theme": "cc-gpu-operator-001",
        "campaign": "cc-campaign-gpu-operator-001",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-coordinator",
        "mode": "formal",
    }
    payload.update(overrides)
    return payload


def _selection(**overrides):
    payload = {
        **_scope(),
        "questionId": "SCI-096",
        "selectedCandidateIds": ["hyp-a"],
        "decidedBy": "operator",
    }
    payload.update(overrides)
    return payload


def _read_scope(**overrides):
    scope = _scope(**overrides)
    scope["scopeHash"] = scope_hash_for(
        program=scope["program"],
        theme=scope["theme"],
        campaign=scope["campaign"],
        question=scope["question"],
        branch=scope["branch"],
        workflow=scope["workflow"],
        agent_id=scope["agentId"],
        mode=scope["mode"],
    )
    return scope


def test_record_single_selection_persists_append_only_record(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)

    created = selections.record_hypothesis_selection(team_id, _selection())

    assert created["status"] == "created"
    record = created["selection"]
    assert record["selectionId"].startswith("hsel-")
    assert record["questionId"] == "SCI-096"
    assert record["selectedCandidateIds"] == ["hyp-a"]
    assert record["previousSelectionId"] == ""
    assert record["decidedBy"] == "operator"
    assert record["scopeHash"] == scope_hash_for(
        program="XH-202619",
        theme="cc-gpu-operator-001",
        campaign="cc-campaign-gpu-operator-001",
        question="SCI-096",
        branch="main",
        workflow="hypothesis_and_plan",
        agent_id="agent-coordinator",
        mode="formal",
    )
    HypothesisSelectionRecord.from_dict(record)

    listed = selections.list_hypothesis_selections(team_id)
    assert listed["selectionCount"] == 1
    fetched = selections.get_hypothesis_selection(team_id, record["selectionId"])
    assert fetched["selection"]["selectionId"] == record["selectionId"]
    latest = selections.get_latest_hypothesis_selection(
        team_id, "SCI-096", scope=_read_scope()
    )
    assert latest["selection"]["selectedCandidateIds"] == ["hyp-a"]


def test_record_multi_selection_preserves_candidate_order(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)

    created = selections.record_hypothesis_selection(
        team_id,
        _selection(selectedCandidateIds=["hyp-c", "hyp-a", "hyp-b"]),
    )

    assert created["status"] == "created"
    assert created["selection"]["selectedCandidateIds"] == ["hyp-c", "hyp-a", "hyp-b"]


def test_record_selection_rejects_candidates_missing_from_approved_artifact(
    tmp_path, monkeypatch
):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)

    with pytest.raises(ContractValidationError, match="approved question artifact"):
        selections.record_hypothesis_selection(
            team_id,
            _selection(selectedCandidateIds=["hyp-a", "hyp-unknown"]),
        )

    assert selections.list_hypothesis_selections(team_id)["selectionCount"] == 0


def test_record_selection_rejects_empty_and_oversized_candidate_lists(
    tmp_path, monkeypatch
):
    team_id = _team(tmp_path, monkeypatch)
    many_candidates = tuple(f"hyp-{index:02d}" for index in range(20))
    _patch_approved_question(monkeypatch, candidate_ids=many_candidates)

    with pytest.raises(ContractValidationError, match="non-empty list"):
        selections.record_hypothesis_selection(team_id, _selection(selectedCandidateIds=[]))
    with pytest.raises(ContractValidationError, match="non-empty list"):
        selections.record_hypothesis_selection(team_id, _selection(selectedCandidateIds="hyp-a"))
    with pytest.raises(ContractValidationError, match="empty entries"):
        selections.record_hypothesis_selection(
            team_id, _selection(selectedCandidateIds=["hyp-00", "  "])
        )
    with pytest.raises(ContractValidationError, match="must be unique"):
        selections.record_hypothesis_selection(
            team_id, _selection(selectedCandidateIds=["hyp-00", "hyp-00"])
        )
    with pytest.raises(ContractValidationError, match=f"at most {MAX_SELECTED_CANDIDATES}"):
        selections.record_hypothesis_selection(
            team_id,
            _selection(selectedCandidateIds=list(many_candidates[:17])),
        )

    boundary = selections.record_hypothesis_selection(
        team_id,
        _selection(selectedCandidateIds=list(many_candidates[:16])),
    )
    assert boundary["status"] == "created"
    assert len(boundary["selection"]["selectedCandidateIds"]) == MAX_SELECTED_CANDIDATES


def test_record_selection_rejects_out_of_scope_payloads(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)

    with pytest.raises(ContractValidationError, match="scope requires a non-empty 'theme'"):
        selections.record_hypothesis_selection(team_id, _selection(theme=""))
    with pytest.raises(ContractValidationError, match="non-empty agentId"):
        selections.record_hypothesis_selection(team_id, _selection(agentId=""))
    with pytest.raises(ContractValidationError, match="unsupported scope mode"):
        selections.record_hypothesis_selection(team_id, _selection(mode="sandbox"))
    with pytest.raises(ContractValidationError, match="questionId"):
        selections.record_hypothesis_selection(team_id, _selection(questionId=""))
    with pytest.raises(ContractValidationError, match="decidedBy"):
        selections.record_hypothesis_selection(team_id, _selection(decidedBy=""))

    record = selections.record_hypothesis_selection(team_id, _selection())["selection"]
    tampered = {**record, "scopeHash": "0" * 64}
    with pytest.raises(ContractValidationError, match="scopeHash does not match"):
        HypothesisSelectionRecord.from_dict(tampered)


def test_record_selection_rejects_unapproved_question(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)

    with pytest.raises(
        selections.ResearchHypothesisSelectionError,
        match="not an approved formal v2 question artifact",
    ):
        selections.record_hypothesis_selection(team_id, _selection(questionId="NOPE-001"))


def test_record_selection_catalog_cold_start_uses_ledger_candidates(tmp_path, monkeypatch):
    """Catalog question without an approved artifact selects from ledger candidates."""
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "_catalog_question",
        lambda question_id: {"id": question_id} if question_id == "SCI-097" else None,
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "list_hypothesis_candidates",
        lambda team_id, question_id="": {
            "schemaVersion": 1,
            "teamId": team_id,
            "candidates": [
                {"candidateId": "cand-1", "statement": "s", "rationale": "r"},
            ],
        },
    )

    created = selections.record_hypothesis_selection(
        team_id,
        _selection(questionId="SCI-097", selectedCandidateIds=["cand-1"]),
    )
    assert created["status"] == "created"
    assert created["selection"]["selectedCandidateIds"] == ["cand-1"]

    with pytest.raises(ContractValidationError, match="must exist in the approved"):
        selections.record_hypothesis_selection(
            team_id,
            _selection(questionId="SCI-097", selectedCandidateIds=["hyp-a"]),
        )


def test_reselection_requires_resolvable_previous_selection(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    first = selections.record_hypothesis_selection(team_id, _selection())

    with pytest.raises(
        selections.ResearchHypothesisSelectionError,
        match="requires previousSelectionId",
    ):
        selections.record_hypothesis_selection(
            team_id, _selection(selectedCandidateIds=["hyp-b"])
        )
    with pytest.raises(
        selections.ResearchHypothesisSelectionError,
        match="does not resolve",
    ):
        selections.record_hypothesis_selection(
            team_id,
            _selection(
                selectedCandidateIds=["hyp-b"],
                previousSelectionId="hsel-nonexistent",
            ),
        )

    other_scope = selections.record_hypothesis_selection(
        team_id,
        _selection(branch="experiment", selectedCandidateIds=["hyp-b"]),
    )
    assert other_scope["status"] == "created"
    with pytest.raises(
        selections.ResearchHypothesisSelectionError,
        match="does not resolve",
    ):
        selections.record_hypothesis_selection(
            team_id,
            _selection(
                selectedCandidateIds=["hyp-c"],
                previousSelectionId=other_scope["selection"]["selectionId"],
            ),
        )

    assert first["status"] == "created"
    assert selections.list_hypothesis_selections(team_id)["selectionCount"] == 2


def test_identical_selection_requests_are_idempotent(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    request = _selection(selectedCandidateIds=["hyp-a", "hyp-b"])

    first = selections.record_hypothesis_selection(team_id, request)
    repeated = selections.record_hypothesis_selection(team_id, request)

    assert first["status"] == "created"
    assert repeated["status"] == "reused"
    assert repeated["selection"]["selectionId"] == first["selection"]["selectionId"]
    assert selections.list_hypothesis_selections(team_id)["selectionCount"] == 1

    reselected = selections.record_hypothesis_selection(
        team_id,
        _selection(
            selectedCandidateIds=["hyp-c"],
            previousSelectionId=first["selection"]["selectionId"],
        ),
    )
    assert reselected["status"] == "created"
    repeated_reselection = selections.record_hypothesis_selection(
        team_id,
        _selection(
            selectedCandidateIds=["hyp-c"],
            previousSelectionId=first["selection"]["selectionId"],
        ),
    )
    assert repeated_reselection["status"] == "reused"
    repeated_first = selections.record_hypothesis_selection(team_id, request)
    assert repeated_first["status"] == "reused"
    assert selections.list_hypothesis_selections(team_id)["selectionCount"] == 2


def test_reselection_chains_and_latest_tracks_newest(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    first = selections.record_hypothesis_selection(team_id, _selection())["selection"]

    second = selections.record_hypothesis_selection(
        team_id,
        _selection(
            selectedCandidateIds=["hyp-b", "hyp-c"],
            previousSelectionId=first["selectionId"],
        ),
    )["selection"]

    assert first["previousSelectionId"] == ""
    assert second["previousSelectionId"] == first["selectionId"]
    latest = selections.get_latest_hypothesis_selection(
        team_id, "SCI-096", scope=_read_scope()
    )
    assert latest["selection"]["selectionId"] == second["selectionId"]
    assert latest["selection"]["selectedCandidateIds"] == ["hyp-b", "hyp-c"]

    storage_path = selections.list_hypothesis_selections(team_id)["storagePath"]
    with open(storage_path, encoding="utf-8") as handle:
        lines = [line for line in handle if line.strip()]
    assert len(lines) == 2
    persisted = [json.loads(line) for line in lines]
    assert [item["selectionId"] for item in persisted] == [
        first["selectionId"],
        second["selectionId"],
    ]


def test_selection_id_conflict_with_different_content_is_rejected(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    selections.record_hypothesis_selection(
        team_id, _selection(selectionId="hsel-fixed")
    )

    with pytest.raises(
        selections.ResearchHypothesisSelectionError,
        match="already bound to different content",
    ):
        selections.record_hypothesis_selection(
            team_id,
            _selection(selectionId="hsel-fixed", selectedCandidateIds=["hyp-b"]),
        )


def test_contract_round_trip_and_defaults():
    scope = _scope()
    payload = {
        "selectionId": "hsel-demo",
        **scope,
        "scopeHash": scope_hash_for(
            program=scope["program"],
            theme=scope["theme"],
            campaign=scope["campaign"],
            question=scope["question"],
            branch=scope["branch"],
            workflow=scope["workflow"],
            agent_id=scope["agentId"],
            mode=scope["mode"],
        ),
        "questionId": "SCI-096",
        "selectedCandidateIds": ["hyp-a"],
        "decidedBy": "operator",
        "createdAt": "2026-08-18T00:00:00Z",
    }

    parsed = HypothesisSelectionRecord.from_dict(payload)

    assert parsed.previousSelectionId == ""
    assert parsed.selectedCandidateIds == ("hyp-a",)
    assert HypothesisSelectionRecord.from_dict(parsed.to_dict()) == parsed


def test_latest_selection_requires_a_complete_scope_and_verified_scope_hash(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    selections.record_hypothesis_selection(team_id, _selection())

    with pytest.raises(ContractValidationError, match="scope"):
        selections.get_latest_hypothesis_selection(team_id, "SCI-096")

    bad_scope = _read_scope()
    bad_scope["scopeHash"] = "0" * 64
    with pytest.raises(ContractValidationError, match="scopeHash"):
        selections.get_latest_hypothesis_selection(
            team_id, "SCI-096", scope=bad_scope
        )


def test_latest_selection_isolated_when_scopes_are_interleaved(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    scope_a = _scope(branch="branch-a", agentId="agent-a")
    scope_b = _scope(branch="branch-b", agentId="agent-b")
    selections.record_hypothesis_selection(
        team_id,
        _selection(**scope_a, selectedCandidateIds=["hyp-a"]),
    )
    selections.record_hypothesis_selection(
        team_id,
        _selection(**scope_b, selectedCandidateIds=["hyp-b"]),
    )
    selections.record_hypothesis_selection(
        team_id,
        _selection(
            **scope_a,
            selectedCandidateIds=["hyp-c"],
            previousSelectionId=selections.get_latest_hypothesis_selection(
                team_id, "SCI-096", scope=_read_scope(**scope_a)
            )["selection"]["selectionId"],
        ),
    )

    latest_a = selections.get_latest_hypothesis_selection(
        team_id, "SCI-096", scope=_read_scope(**scope_a)
    )
    latest_b = selections.get_latest_hypothesis_selection(
        team_id, "SCI-096", scope=_read_scope(**scope_b)
    )
    assert latest_a["selection"]["selectedCandidateIds"] == ["hyp-c"]
    assert latest_b["selection"]["selectedCandidateIds"] == ["hyp-b"]
