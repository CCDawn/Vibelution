"""HF-1 hypothesis selection record contract and append-only service tests."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest

from core.research.workflow.contracts import (
    MAX_SELECTED_CANDIDATES,
    ContractValidationError,
    HypothesisSelectionRecord,
    scope_hash_for,
)
from core.web.services import team_service
from core.web.services.team_workflow import (
    hypothesis_selection as selections,
)
from core.web.services.team_workflow import (
    jsonl_quarantine,
)
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain,
    question_launch,
)

_QUARANTINE_LOGGER = "core.web.services.team_workflow.jsonl_quarantine"

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
        "_approved_details",
        lambda _team_id: {question_id.upper(): detail},
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
        "selectedCandidateIds": ["hyp-a", "hyp-b"],
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
    assert record["selectedCandidateIds"] == ["hyp-a", "hyp-b"]
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
    assert listed["corruptQuarantinedLineCount"] == 0
    fetched = selections.get_hypothesis_selection(team_id, record["selectionId"])
    assert fetched["selection"]["selectionId"] == record["selectionId"]
    latest = selections.get_latest_hypothesis_selection(
        team_id, "SCI-096", scope=_read_scope()
    )
    assert latest["selection"]["selectedCandidateIds"] == ["hyp-a", "hyp-b"]


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
    with pytest.raises(ContractValidationError, match="at least two candidates"):
        selections.record_hypothesis_selection(
            team_id, _selection(selectedCandidateIds=["hyp-00"])
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
                {"candidateId": "cand-2", "statement": "s2", "rationale": "r2"},
            ],
        },
    )

    created = selections.record_hypothesis_selection(
        team_id,
        _selection(questionId="SCI-097", selectedCandidateIds=["cand-1", "cand-2"]),
    )
    assert created["status"] == "created"
    assert created["selection"]["selectedCandidateIds"] == ["cand-1", "cand-2"]

    with pytest.raises(ContractValidationError, match="must exist in the approved"):
        selections.record_hypothesis_selection(
            team_id,
            _selection(questionId="SCI-097", selectedCandidateIds=["hyp-a", "hyp-b"]),
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
            team_id, _selection(selectedCandidateIds=["hyp-b", "hyp-c"])
        )
    with pytest.raises(
        selections.ResearchHypothesisSelectionError,
        match="does not resolve",
    ):
        selections.record_hypothesis_selection(
            team_id,
            _selection(
                selectedCandidateIds=["hyp-b", "hyp-c"],
                previousSelectionId="hsel-nonexistent",
            ),
        )

    other_scope = selections.record_hypothesis_selection(
        team_id,
        _selection(branch="experiment", selectedCandidateIds=["hyp-b", "hyp-c"]),
    )
    assert other_scope["status"] == "created"
    with pytest.raises(
        selections.ResearchHypothesisSelectionError,
        match="does not resolve",
    ):
        selections.record_hypothesis_selection(
            team_id,
            _selection(
                selectedCandidateIds=["hyp-c", "hyp-a"],
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
            selectedCandidateIds=["hyp-c", "hyp-a"],
            previousSelectionId=first["selection"]["selectionId"],
        ),
    )
    assert reselected["status"] == "created"
    repeated_reselection = selections.record_hypothesis_selection(
        team_id,
        _selection(
            selectedCandidateIds=["hyp-c", "hyp-a"],
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
            _selection(selectionId="hsel-fixed", selectedCandidateIds=["hyp-b", "hyp-c"]),
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
        _selection(**scope_a, selectedCandidateIds=["hyp-a", "hyp-b"]),
    )
    selections.record_hypothesis_selection(
        team_id,
        _selection(**scope_b, selectedCandidateIds=["hyp-b", "hyp-c"]),
    )
    selections.record_hypothesis_selection(
        team_id,
        _selection(
            **scope_a,
            selectedCandidateIds=["hyp-c", "hyp-a"],
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
    assert latest_a["selection"]["selectedCandidateIds"] == ["hyp-c", "hyp-a"]
    assert latest_b["selection"]["selectedCandidateIds"] == ["hyp-b", "hyp-c"]


def _append_raw_lines(storage_path: Path, texts: list[str]) -> None:
    with open(storage_path, "a", encoding="utf-8") as handle:
        handle.write("".join(text + "\n" for text in texts))


def _sidecar_rows(storage_path: Path) -> list[dict]:
    sidecar = storage_path.with_name(storage_path.name + ".corrupt.jsonl")
    return [
        json.loads(line)
        for line in sidecar.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_corrupt_selection_lines_are_quarantined_instead_of_raising(
    tmp_path, monkeypatch, caplog
):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    created = selections.record_hypothesis_selection(team_id, _selection())
    selection_id = created["selection"]["selectionId"]
    storage_path = Path(
        selections.list_hypothesis_selections(team_id)["storagePath"]
    )
    corrupt_texts = ["{torn-write-not-json", json.dumps(["wrong", "shape"])]
    _append_raw_lines(storage_path, corrupt_texts)
    original_bytes = storage_path.read_bytes()

    with caplog.at_level(logging.WARNING, logger=_QUARANTINE_LOGGER):
        listed = selections.list_hypothesis_selections(team_id)
        fetched = selections.get_hypothesis_selection(team_id, selection_id)
        latest = selections.get_latest_hypothesis_selection(
            team_id, "SCI-096", scope=_read_scope()
        )

    assert [item["selectionId"] for item in listed["selections"]] == [selection_id]
    assert listed["selectionCount"] == 1
    assert listed["corruptQuarantinedLineCount"] == 2
    assert fetched["corruptQuarantinedLineCount"] == 2
    assert fetched["selection"]["selectionId"] == selection_id
    assert latest["corruptQuarantinedLineCount"] == 2
    assert latest["selection"]["selectedCandidateIds"] == ["hyp-a", "hyp-b"]

    # The ledger stays byte-identical; only the sidecar gains evidence.
    assert storage_path.read_bytes() == original_bytes
    rows = _sidecar_rows(storage_path)
    assert len(rows) == 2
    assert [row["lineHash"] for row in rows] == [
        hashlib.sha256(text.encode("utf-8")).hexdigest() for text in corrupt_texts
    ]
    assert [row["lineNumber"] for row in rows] == [2, 3]
    for row in rows:
        assert set(row) == {"lineHash", "lineNumber", "quarantinedAt"}

    count_warnings = [
        record
        for record in caplog.records
        if record.name == _QUARANTINE_LOGGER and len(record.args) >= 2
    ]
    assert any(
        str(storage_path) in record.getMessage() and record.args[1] == 2
        for record in count_warnings
    )
    logged_text = "".join(record.getMessage() for record in caplog.records)
    assert all(text not in logged_text for text in corrupt_texts)


def test_selection_reads_do_not_grow_the_sidecar_on_repeat(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    selections.record_hypothesis_selection(team_id, _selection())
    storage_path = Path(
        selections.list_hypothesis_selections(team_id)["storagePath"]
    )
    _append_raw_lines(storage_path, ["{torn-write-not-json"])
    first = selections.list_hypothesis_selections(team_id)
    assert first["corruptQuarantinedLineCount"] == 1
    sidecar = storage_path.with_name(storage_path.name + ".corrupt.jsonl")
    sidecar_after_first = sidecar.read_bytes()

    repeated_list = selections.list_hypothesis_selections(team_id)
    repeated_get = selections.get_hypothesis_selection(
        team_id, first["selections"][0]["selectionId"]
    )
    repeated_latest = selections.get_latest_hypothesis_selection(
        team_id, "SCI-096", scope=_read_scope()
    )

    assert repeated_list["corruptQuarantinedLineCount"] == 1
    assert repeated_get["corruptQuarantinedLineCount"] == 1
    assert repeated_latest["corruptQuarantinedLineCount"] == 1
    assert sidecar.read_bytes() == sidecar_after_first


def test_clean_selection_ledger_reports_zero_quarantined_lines(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    created = selections.record_hypothesis_selection(team_id, _selection())

    listed = selections.list_hypothesis_selections(team_id)
    fetched = selections.get_hypothesis_selection(
        team_id, created["selection"]["selectionId"]
    )
    latest = selections.get_latest_hypothesis_selection(
        team_id, "SCI-096", scope=_read_scope()
    )
    storage_path = Path(listed["storagePath"])

    assert listed["corruptQuarantinedLineCount"] == 0
    assert fetched["corruptQuarantinedLineCount"] == 0
    assert latest["corruptQuarantinedLineCount"] == 0
    assert not storage_path.with_name(storage_path.name + ".corrupt.jsonl").exists()


def test_jsonl_quarantine_helper_dedupes_and_ignores_a_broken_sidecar(tmp_path):
    store = tmp_path / "ledger.jsonl"
    sidecar = tmp_path / (store.name + ".corrupt.jsonl")
    corrupt_a = "{broken-a"
    keep = {"id": "keep"}
    store.write_text(json.dumps(keep) + "\n" + corrupt_a + "\n", encoding="utf-8")
    seeded_entry = {
        "lineHash": hashlib.sha256(corrupt_a.encode("utf-8")).hexdigest(),
        "lineNumber": 9,
        "quarantinedAt": "2026-08-01T00:00:00Z",
    }
    seeded_row = json.dumps(seeded_entry, sort_keys=True)
    sidecar.write_text("junk-not-json\n" + seeded_row + "\n", encoding="utf-8")

    records, corrupt_count = jsonl_quarantine.read_jsonl_with_quarantine(store)

    assert corrupt_count == 1
    assert records == [keep]
    # Junk rows are ignored and the known hash suppresses a duplicate append.
    assert sidecar.read_text(encoding="utf-8").splitlines() == [
        "junk-not-json",
        seeded_row,
    ]

    repeat_count = jsonl_quarantine.read_jsonl_with_quarantine(store)[1]
    assert repeat_count == 1

    corrupt_b = "{broken-b"
    store.write_text(
        json.dumps(keep) + "\n" + corrupt_a + "\n" + corrupt_b + "\n", encoding="utf-8"
    )
    records_again, count_again = jsonl_quarantine.read_jsonl_with_quarantine(store)

    assert count_again == 2
    assert records_again == [keep]
    rows = [
        json.loads(row)
        for row in sidecar.read_text(encoding="utf-8").splitlines()
        if row.startswith("{")
    ]
    assert len(rows) == 2
    assert rows[-1]["lineHash"] == hashlib.sha256(corrupt_b.encode("utf-8")).hexdigest()


def test_jsonl_quarantine_helper_preserves_strict_io_behavior(tmp_path):
    missing = tmp_path / "missing.jsonl"

    assert jsonl_quarantine.read_jsonl_with_quarantine(missing) == ([], 0)
    assert not missing.with_name(missing.name + ".corrupt.jsonl").exists()

    class _UnreadableStore:
        def exists(self) -> bool:
            return True

        def read_text(self, encoding: str) -> str:
            raise PermissionError(13, "simulated unreadable store")

    with pytest.raises(PermissionError):
        jsonl_quarantine.read_jsonl_with_quarantine(_UnreadableStore())  # type: ignore[arg-type]
