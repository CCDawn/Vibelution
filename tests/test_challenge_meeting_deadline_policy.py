from __future__ import annotations

import json

import pytest

from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
)
from core.web.services.team_workflow import challenge_deadline_policy as policy
from core.web.services.team_workflow.research_runtime import (
    model_invocation_receipt_registry as receipt_registry,
)


def test_binding_p95_derives_bounded_call_budget(monkeypatch):
    samples = [
        {
            "provider": "relay_autodl",
            "model": "GLM-5.3-flash",
            "purpose": "meeting_speaker",
            "latencyMs": 470_000 + index * 1_000,
        }
        for index in range(20)
    ]
    monkeypatch.delenv(policy._PER_CALL_OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(policy, "_receipt_latency_samples", lambda _team: samples)

    result = policy.derive_per_call_budget(
        "research-team",
        model_refs=["relay_autodl/GLM-5.3-flash"],
        purpose="meeting_speaker",
    )

    assert result["sampleSource"] == "provider_model_purpose_p95"
    assert result["sampleCount"] == 20
    assert result["latencyP95Ms"] == 488_000
    assert result["perCallBudgetMs"] == 600_000


def test_sparse_samples_use_audited_default(monkeypatch):
    monkeypatch.delenv(policy._PER_CALL_OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(
        policy,
        "_receipt_latency_samples",
        lambda _team: [{"provider": "p", "model": "m", "latencyMs": 10_000}],
    )

    result = policy.derive_per_call_budget(
        "research-team", model_refs=["p/m"], purpose="meeting_speaker"
    )

    assert result["sampleSource"] == "audited_default"
    assert result["perCallBudgetMs"] == 450_000


def test_operator_override_is_bounded(monkeypatch):
    monkeypatch.setenv(policy._PER_CALL_OVERRIDE_ENV, "299999")
    with pytest.raises(policy.ChallengeMeetingDeadlinePolicyError):
        policy.derive_per_call_budget("research-team")

    monkeypatch.setenv(policy._PER_CALL_OVERRIDE_ENV, "360000")
    assert policy.derive_per_call_budget("research-team") == {
        "perCallBudgetMs": 360_000,
        "latencyP95Ms": 0,
        "sampleCount": 0,
        "sampleSource": "operator_env",
        "overrideEnv": policy._PER_CALL_OVERRIDE_ENV,
    }


def test_meeting_budget_sums_serial_speakers_and_digest(monkeypatch):
    monkeypatch.setattr(policy, "_participant_model_refs", lambda _ids: ["p/m"])
    monkeypatch.setattr(
        policy,
        "derive_per_call_budget",
        lambda *_args, **_kwargs: {
            "perCallBudgetMs": 300_000,
            "latencyP95Ms": 100_000,
            "sampleCount": 24,
            "sampleSource": "provider_model_purpose_p95",
            "overrideEnv": "",
        },
    )

    result = policy.derive_meeting_deadline_policy(
        "research-team",
        {"participants": ["a", "b", "c", "d"], "rounds": 2},
        server_created_at_ms=1_000_000,
    )

    assert result["plannedSerialCallCount"] == 9
    assert result["meetingBudgetMs"] == 2_700_000
    assert result["meetingDeadlineAtMs"] == 3_700_000
    assert result["challengeDeadlineAtMs"] == 3_700_000
    assert len(result["deadlinePolicyHash"]) == 64

    insufficient = policy.derive_meeting_deadline_policy(
        "research-team",
        {"participants": ["a", "b", "c", "d"], "rounds": 2},
        server_created_at_ms=1_000_000,
        outer_deadline_at_ms=2_000_000,
    )
    assert insufficient["challengeDeadlineAtMs"] == 2_000_000
    assert insufficient["deadlineBudgetSufficient"] is False
    assert insufficient["deadlineProblem"] == {
        "code": "deadline_budget_insufficient",
        "availableMs": 1_000_000,
        "requiredMs": 2_700_000,
        "outerDeadlineAtMs": 2_000_000,
        "meetingDeadlineAtMs": 3_700_000,
    }


def test_effective_call_deadline_uses_earliest_clock():
    assert policy.effective_call_deadline_at_ms(
        call_started_at_ms=1_000_000,
        per_call_budget_ms=300_000,
        meeting_deadline_at_ms=1_500_000,
        outer_deadline_at_ms=1_200_000,
    ) == 1_200_000


def test_latency_projection_reads_receipt_facts_without_excerpts(tmp_path, monkeypatch):
    root = tmp_path / "receipts"
    path = root / "question" / "run.json"
    path.parent.mkdir(parents=True)
    scope = {
        "questionId": "SCI-091",
        "workflowRunId": "run-1",
        "sessionId": "session-1",
        "taskId": "task-1",
        "turnId": "turn-1",
        "formalNodeId": "node-1",
        "formalNodeRunId": "node-run-1",
        "modelPolicySha256": "a" * 64,
    }
    locator = {
        **scope,
        "kind": "turn_journal",
        "outputRef": "session:session-1/turn:turn-1",
        "outputSha256": "b" * 64,
        "receiptId": "receipt-1",
        "invocationId": "invocation-1",
        "attempt": 1,
    }
    receipt = ModelInvocationReceipt.from_invocation(
        receipt_id="receipt-1",
        run_id="run-1",
        node_run_id="node-run-1",
        scope=scope,
        provider="relay_autodl",
        model="GLM-5.3-flash",
        request_content="secret request",
        response_content="secret response",
        started_at_ms=1_000,
        finished_at_ms=121_000,
        metadata={"outcomeKinds": ["candidate"], "purpose": "meeting_speaker"},
        evidence_locator=locator,
    )
    path.write_text(
        json.dumps(
            {
                "schemaVersion": receipt_registry.STORE_SCHEMA_VERSION,
                "storeKind": receipt_registry.STORE_KIND,
                "teamId": "research-team",
                "questionId": "SCI-091",
                "workflowRunId": "run-1",
                "receipts": [receipt.to_dict()],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(receipt_registry, "_receipt_store_root", lambda _team: root)

    rows = receipt_registry.list_team_model_invocation_latency_samples(
        "research-team"
    )

    assert rows == [
        {
            "provider": "relay_autodl",
            "model": "GLM-5.3-flash",
            "latencyMs": 120_000,
            "finishedAtMs": 121_000,
            "purpose": "meeting_speaker",
        }
    ]
    assert "secret" not in str(rows)
