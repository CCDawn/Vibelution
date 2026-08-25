from __future__ import annotations

import json
from copy import deepcopy

import pytest

from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
)
from core.web.services.team_workflow import challenge_question_runs
from core.web.services.team_workflow.research_runtime import (
    model_invocation_receipt_registry as registry,
)


def _receipt(kind: str) -> dict:
    receipt_id = f"receipt-{kind}"
    node_run_id = f"node-run-{kind}"
    model_policy_sha256 = "a" * 64
    scope = {
        "questionId": "SCI-096",
        "workflowRunId": "run-096",
        "sessionId": f"session-{kind}",
        "taskId": f"task-{kind}",
        "turnId": f"turn-{kind}",
        "formalNodeId": f"node-{kind}",
        "formalNodeRunId": node_run_id,
        "modelPolicySha256": model_policy_sha256,
    }
    return ModelInvocationReceipt.from_invocation(
        receipt_id=receipt_id,
        run_id="run-096",
        node_run_id=node_run_id,
        scope=scope,
        provider="dashscope",
        model="qwen3.6-plus",
        requested_model="qwen3.6-plus",
        request_content={"kind": kind, "input": "bounded"},
        response_content={"kind": kind, "output": "bounded"},
        started_at_ms=100,
        finished_at_ms=120,
        token_usage={"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
        metadata={"outcomeKinds": [kind]},
        evidence_locator={
            **scope,
            "kind": "turn_journal",
            "outputRef": f"session:{scope['sessionId']}/turn:{scope['turnId']}",
            "outputSha256": "b" * 64,
            "receiptId": receipt_id,
            "invocationId": f"invocation-{kind}",
            "attempt": 1,
        },
    ).to_dict()


def test_receipt_store_survives_windows_max_path_overflow(tmp_path, monkeypatch) -> None:
    # Real deployments nest the store under a long AppData workspace root; the
    # final `<sha256>/<sha256>.json` file then crosses the legacy MAX_PATH
    # boundary and os.replace fails with WinError 3 unless the path is
    # normalized to the extended-length form.
    deep_root = tmp_path
    for index in range(4):
        deep_root = deep_root / (f"very-long-team-segment-{index}-" + "x" * 40)
    monkeypatch.setattr(registry, "resolve_team_program_root", lambda _team_id: deep_root)
    receipts = [_receipt(kind) for kind in ("candidate", "review")]

    refs = registry.register_question_model_invocation_receipts(
        "research-team",
        question_id="SCI-096",
        workflow_run_id="run-096",
        receipts=receipts,
    )
    replayed = registry.register_question_model_invocation_receipts(
        "research-team",
        question_id="SCI-096",
        workflow_run_id="run-096",
        receipts=receipts,
    )

    assert replayed == refs
    store_path = registry._io_path(registry._path("research-team", "SCI-096", "run-096"))
    assert len(str(store_path)) > 260 or store_path.exists()
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    assert [item["receiptId"] for item in payload["receipts"]] == [
        "receipt-candidate",
        "receipt-review",
    ]


def test_full_trace_is_idempotent_and_immutable_projection_detects_tamper(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(registry, "resolve_team_program_root", lambda _team_id: tmp_path)
    receipts = [
        _receipt(kind)
        for kind in ("candidate", "review", "revision", "plan", "final_output")
    ]

    refs = registry.register_question_model_invocation_receipts(
        "research-team",
        question_id="SCI-096",
        workflow_run_id="run-096",
        receipts=receipts,
    )
    replayed = registry.register_question_model_invocation_receipts(
        "research-team",
        question_id="SCI-096",
        workflow_run_id="run-096",
        receipts=receipts,
    )

    assert replayed == refs
    assert registry.model_invocation_receipt_coverage(refs) == {
        "status": "passed",
        "coveredKinds": ["candidate", "final_output", "plan", "review", "revision"],
        "missingKinds": [],
        "receiptCount": 5,
    }
    assert all(ref["evidenceLocatorSha256"] for ref in refs)
    assert all(ref["receiptSha256"] for ref in refs)

    record = {"questionId": "SCI-096", "runId": "run-096"}
    assert challenge_question_runs._apply_question_model_invocation_trace_projection(
        "research-team", record
    ) is True
    assert record["modelInvocationReceiptTraceRefs"] == refs
    assert record["modelInvocationReceiptCoverage"]["status"] == "passed"

    path = registry._path("research-team", "SCI-096", "run-096")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["receipts"][0]["responseSummaryHash"] = "f" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    verified_refs, coverage = (
        challenge_question_runs._question_model_invocation_trace_projection(
            "research-team", record
        )
    )
    assert verified_refs == []
    assert coverage["status"] == "failed"
    assert coverage["integrityIssue"] == "stored_projection_mismatch"


def test_receipt_replay_conflict_and_missing_outcome_fail_closed(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(registry, "resolve_team_program_root", lambda _team_id: tmp_path)
    candidate = _receipt("candidate")
    registry.register_question_model_invocation_receipts(
        "research-team",
        question_id="SCI-096",
        workflow_run_id="run-096",
        receipts=[candidate],
    )

    conflict = deepcopy(candidate)
    conflict["responseSummaryHash"] = "e" * 64
    with pytest.raises(ValueError, match="replay conflict"):
        registry.register_question_model_invocation_receipts(
            "research-team",
            question_id="SCI-096",
            workflow_run_id="run-096",
            receipts=[conflict],
        )

    refs = registry.question_model_invocation_receipt_refs(
        "research-team",
        question_id="SCI-096",
        workflow_run_id="run-096",
    )
    coverage = registry.model_invocation_receipt_coverage(refs)
    assert coverage["status"] == "failed"
    assert coverage["missingKinds"] == ["final_output", "plan", "review", "revision"]


def test_source_evidence_is_allowed_but_does_not_satisfy_required_coverage(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(registry, "resolve_team_program_root", lambda _team_id: tmp_path)

    refs = registry.register_question_model_invocation_receipts(
        "research-team",
        question_id="SCI-096",
        workflow_run_id="run-096",
        receipts=[_receipt("source_evidence")],
    )

    assert refs[0]["outcomeKinds"] == ["source_evidence"]
    assert registry.model_invocation_receipt_coverage(refs)["status"] == "failed"
    assert "source_evidence" not in registry.model_invocation_receipt_coverage(refs)[
        "coveredKinds"
    ]


def test_path_components_are_hashed_and_corrupt_store_cannot_be_overwritten(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(registry, "resolve_team_program_root", lambda _team_id: tmp_path)

    hostile_path = registry._path("research-team", "..", "../../escape")
    store_root = tmp_path / "challenge_program" / "model_invocation_receipts"
    assert hostile_path.is_relative_to(store_root)
    assert ".." not in hostile_path.parts
    assert "/" not in hostile_path.name
    assert hostile_path.name.endswith(".json")

    valid_path = registry._path("research-team", "SCI-096", "run-096")
    valid_path.parent.mkdir(parents=True, exist_ok=True)
    valid_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt"):
        registry.register_question_model_invocation_receipts(
            "research-team",
            question_id="SCI-096",
            workflow_run_id="run-096",
            receipts=[_receipt("candidate")],
        )
    assert valid_path.read_text(encoding="utf-8") == "{broken"
    assert registry.question_model_invocation_receipt_refs(
        "research-team",
        question_id="SCI-096",
        workflow_run_id="run-096",
    ) == []


def _mutate_node_run(value: dict) -> None:
    value["nodeRunId"] = "other-node"


def _mutate_policy(value: dict) -> None:
    value["scope"].update({"modelPolicySha256": "A" * 64})


def _mutate_invocation(value: dict) -> None:
    value["evidenceLocator"].pop("invocationId")


def _mutate_attempt(value: dict) -> None:
    value["evidenceLocator"].update({"attempt": 2})


@pytest.mark.parametrize(
    "mutate",
    (_mutate_node_run, _mutate_policy, _mutate_invocation, _mutate_attempt),
)
def test_receipt_scope_and_locator_contract_is_strict(tmp_path, monkeypatch, mutate) -> None:
    monkeypatch.setattr(registry, "resolve_team_program_root", lambda _team_id: tmp_path)
    invalid = _receipt("candidate")
    mutate(invalid)

    with pytest.raises(ValueError):
        registry.register_question_model_invocation_receipts(
            "research-team",
            question_id="SCI-096",
            workflow_run_id="run-096",
            receipts=[invalid],
        )
