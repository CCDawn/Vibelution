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
    scope = {
        "questionId": "SCI-096",
        "workflowRunId": "run-096",
        "sessionId": f"session-{kind}",
        "taskId": f"task-{kind}",
        "turnId": f"turn-{kind}",
        "formalNodeId": f"node-{kind}",
        "formalNodeRunId": node_run_id,
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
            "receiptId": receipt_id,
            "invocationId": f"invocation-{kind}",
        },
    ).to_dict()


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
