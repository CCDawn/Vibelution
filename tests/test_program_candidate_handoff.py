"""Focused contract tests for the result-package -> Challenge Program bridge."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from core.research.competition.question_result_package import canonical_model_policy
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
)
from core.web.services.team_workflow import challenge_question_runs
from core.web.services.team_workflow.research_runtime import (
    model_invocation_receipt_registry as receipt_registry,
    program_candidate_handoff,
)
from tests.test_challenge_question_runs import _citation_checks, _isolate_store, _output


def _package(*, output: dict, package_hash: str = "a" * 64) -> dict:
    return {
        "teamId": "research-team",
        "workflowRunId": "workflow-sci-096",
        "sourceCollectionRunId": "workflow-sci-096",
        "package": {
            "runId": "workflow-sci-096",
            "questionId": "SCI-096",
            "contentHash": package_hash,
        },
        "challengeQuestionOutput": output,
        "citationChecks": _citation_checks(output),
    }


def _trace_ref(receipt_id: str, receipt_sha256: str) -> dict:
    return {
        "receiptId": receipt_id,
        "receiptSha256": receipt_sha256,
        "nodeRunId": f"nr-{receipt_id}",
        "sessionId": "session-sci-096",
        "turnId": "turn-sci-096",
        "outcomeKinds": [],
        "evidenceLocator": {
            "kind": "workflow-ledger",
            "ref": f"receipt://{receipt_id}",
        },
        "evidenceLocatorSha256": "8" * 64,
    }


_TRACE_REFS = [
    _trace_ref("receipt-generation", "1" * 64),
    _trace_ref("receipt-review", "2" * 64),
]
_TRACE_COVERAGE = {
    "status": "failed",
    "coveredKinds": [],
    "missingKinds": ["candidate"],
    "receiptCount": 2,
}


def _isolate_v2_trace_handoff(monkeypatch, *, stored_trace_refs: bool = True) -> None:
    """Stage a complete v2 handoff whose record carries registry trace refs.

    The trace projection is patched by the caller, so no real receipt-registry
    or Challenge Program store is touched.
    """

    output = _output()
    output["run"]["run_id"] = "workflow-sci-096"
    artifact = _package(output=output)
    monkeypatch.setattr(
        program_candidate_handoff,
        "load_scoped_artifact_payload",
        lambda *args, **kwargs: {
            "teamId": "research-team",
            "workflowRunId": "workflow-sci-096",
            "sourceCollectionRunId": "workflow-sci-096",
            "payload": artifact,
        },
    )
    record = {
        "recordId": "SCI-096:workflow-sci-096",
        "questionId": "SCI-096",
        "runId": "workflow-sci-096",
        "status": "approved",
        "outputSha256": "e" * 64,
        "humanGates": {"allApproved": True, "approvedCount": 4},
        "validation": {
            "officialModelCall": True,
            "modelInvocationReceipts": "pending",
        },
    }
    if stored_trace_refs:
        record["modelInvocationReceiptTraceRefs"] = deepcopy(_TRACE_REFS)
        record["modelInvocationReceiptCoverage"] = deepcopy(_TRACE_COVERAGE)
    monkeypatch.setattr(
        challenge_question_runs,
        "register_challenge_question_output",
        lambda *args, **kwargs: {"idempotent": True, "record": deepcopy(record)},
    )


def _trace_digest(refs: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(
            sorted(item["receiptSha256"] for item in refs),
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_missing_v2_authority_returns_needs_context_without_registering(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        program_candidate_handoff,
        "load_scoped_artifact_payload",
        lambda *args, **kwargs: {
            "teamId": "research-team",
            "workflowRunId": "workflow-sci-096",
            "sourceCollectionRunId": "workflow-sci-096",
            "payload": {
                "package": {
                    "runId": "workflow-sci-096",
                    "questionId": "SCI-096",
                    "contentHash": "a" * 64,
                }
            },
        },
    )
    monkeypatch.setattr(
        challenge_question_runs,
        "register_challenge_question_output",
        lambda *args, **kwargs: calls.append(kwargs) or {},
    )

    result = program_candidate_handoff.handoff_result_package_to_challenge_program(
        team_id="research-team",
        workflow_run_id="workflow-sci-096",
    )

    assert result["status"] == program_candidate_handoff.NEEDS_CONTEXT
    assert "canonical_challenge_question_output.v2" in result["missingAuthorities"]
    assert "package.challengeQuestionOutput" in result["missingFields"]
    assert calls == []


def test_complete_v2_authority_registers_review_required_and_replays_idempotently(
    tmp_path, monkeypatch
):
    _isolate_store(tmp_path, monkeypatch)
    output = _output()
    output["run"]["run_id"] = "workflow-sci-096"
    artifact = _package(output=output)
    monkeypatch.setattr(
        program_candidate_handoff,
        "load_scoped_artifact_payload",
        lambda *args, **kwargs: {
            "teamId": "research-team",
            "workflowRunId": "workflow-sci-096",
            "sourceCollectionRunId": "workflow-sci-096",
            "payload": artifact,
        },
    )

    first = program_candidate_handoff.handoff_result_package_to_challenge_program(
        team_id="research-team",
        workflow_run_id="workflow-sci-096",
    )
    replay = program_candidate_handoff.handoff_result_package_to_challenge_program(
        team_id="research-team",
        workflow_run_id="workflow-sci-096",
    )

    assert first["status"] == "registered"
    assert first["reviewStatus"] == "review_required"
    assert replay["status"] == "idempotent"
    assert replay["sourceResultPackageHash"] == "a" * 64
    records = challenge_question_runs._load_store("research-team")["records"]
    assert len(records) == 1
    assert records[0]["sourceResultPackageHash"] == "a" * 64

    changed = deepcopy(artifact)
    changed["package"]["contentHash"] = "b" * 64
    monkeypatch.setattr(
        program_candidate_handoff,
        "load_scoped_artifact_payload",
        lambda *args, **kwargs: {
            "teamId": "research-team",
            "workflowRunId": "workflow-sci-096",
            "sourceCollectionRunId": "workflow-sci-096",
            "payload": changed,
        },
    )
    with pytest.raises(
        program_candidate_handoff.ProgramCandidateHandoffContractError,
        match="source result package binding",
    ):
        program_candidate_handoff.handoff_result_package_to_challenge_program(
            team_id="research-team",
            workflow_run_id="workflow-sci-096",
        )


def test_handoff_forwards_canonical_package_and_receipt_authority(
    tmp_path, monkeypatch
):
    _isolate_store(tmp_path, monkeypatch)
    output = _output()
    output["run"]["run_id"] = "workflow-sci-096"
    canonical_package = {
        "schema_version": 2,
        "package_id": "qrp-v2-workflow-sci-096",
        "canonical_sha256": "c" * 64,
        "model_policy": {"policySha256": "d" * 64},
        "model_invocation_receipts": {
            "generation": {"receiptId": "receipt-generation"},
            "review": {"receiptId": "receipt-review"},
            "revision": {"receiptId": "receipt-revision"},
        },
    }
    artifact = _package(output=output)
    artifact["package"]["resultPackage"] = canonical_package
    artifact["package"]["officialModelCall"] = True
    artifact["package"]["modelInvocationReceipts"] = list(
        canonical_package["model_invocation_receipts"].values()
    )
    artifact["package"]["authorizedModelPolicySha256"] = "d" * 64
    monkeypatch.setattr(
        program_candidate_handoff,
        "load_scoped_artifact_payload",
        lambda *args, **kwargs: {
            "teamId": "research-team",
            "workflowRunId": "workflow-sci-096",
            "sourceCollectionRunId": "workflow-sci-096",
            "payload": artifact,
        },
    )
    captured: dict = {}

    def _register(_team_id, payload):
        captured.update(deepcopy(payload))
        return {
            "idempotent": False,
            "record": {
                "recordId": "SCI-096:workflow-sci-096",
                "status": "review_required",
                "outputSha256": "e" * 64,
                "humanGates": {},
                "validation": {
                    "officialModelCall": True,
                    "modelInvocationReceipts": "passed",
                },
                "resultPackage": {
                    "canonicalHash": "c" * 64,
                    "idempotencyKey": "qrp-key",
                },
            },
        }

    monkeypatch.setattr(
        challenge_question_runs, "register_challenge_question_output", _register
    )

    result = program_candidate_handoff.handoff_result_package_to_challenge_program(
        team_id="research-team",
        workflow_run_id="workflow-sci-096",
    )

    assert captured["resultPackage"] == canonical_package
    assert captured["modelInvocationReceipts"] == list(
        canonical_package["model_invocation_receipts"].values()
    )
    assert captured["authorizedModelPolicySha256"] == "d" * 64
    assert result["resultPackage"]["canonicalHash"] == "c" * 64
    assert result["officialModelCall"] is True
    assert result["receiptStatus"] == "passed"


def test_v2_handoff_trace_projection_mismatch_fails_closed(monkeypatch):
    """A registry/stored trace mismatch fails closed without raising."""

    _isolate_v2_trace_handoff(monkeypatch)
    monkeypatch.setattr(
        challenge_question_runs,
        "_question_model_invocation_trace_projection",
        lambda _team_id, _record: (
            [],
            {
                "status": "failed",
                "coveredKinds": [],
                "missingKinds": ["candidate"],
                "receiptCount": 0,
                "integrityIssue": "stored_projection_mismatch",
            },
        ),
    )

    result = program_candidate_handoff.handoff_result_package_to_challenge_program(
        team_id="research-team",
        workflow_run_id="workflow-sci-096",
    )

    assert result["receiptTraceVerified"] is False
    assert result["receiptTraceCount"] == 0
    assert result["receiptTraceDigest"] == ""


# ---------------------- stage-one registry authority end-to-end registration


def _stage_one_frozen_policy() -> dict:
    return canonical_model_policy(
        {
            "family": "qwen",
            "providerIds": ["dashscope_main"],
            "modelIds": ["qwen3.6-plus"],
            "requireOfficialProvider": True,
        }
    )


def _registered_stage_one_receipt(
    stage: str, run_id: str, policy_sha256: str
) -> dict:
    """A registry-valid stage-one receipt, minted the way sessions mint them."""

    receipt_id = f"receipt-{stage}"
    node_run_id = f"node-run-{stage}"
    scope = {
        "questionId": "SCI-096",
        "workflowRunId": run_id,
        "sessionId": f"session-{stage}",
        "taskId": f"task-{stage}",
        "turnId": f"turn-{stage}",
        "formalNodeId": f"node-{stage}",
        "formalNodeRunId": node_run_id,
        "stageId": stage,
        "modelPolicySha256": policy_sha256,
    }
    return ModelInvocationReceipt.from_invocation(
        receipt_id=receipt_id,
        run_id=run_id,
        node_run_id=node_run_id,
        scope=scope,
        provider="dashscope_main",
        model="qwen3.6-plus",
        requested_model="qwen3.6-plus",
        request_content={"kind": stage, "input": "bounded"},
        response_content={"kind": stage, "output": "bounded"},
        started_at_ms=100,
        finished_at_ms=120,
        token_usage={"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
        metadata={
            "outcomeKinds": ["candidate" if stage == "generation" else stage]
        },
        evidence_locator={
            **scope,
            "kind": "turn_journal",
            "outputRef": f"session:{scope['sessionId']}/turn:{scope['turnId']}",
            "outputSha256": "b" * 64,
            "receiptId": receipt_id,
            "invocationId": f"invocation-{stage}",
            "attempt": 1,
        },
    ).to_dict()


def _seed_stage_one_registry(run_id: str) -> dict[str, dict]:
    policy = _stage_one_frozen_policy()
    receipts = {
        stage: _registered_stage_one_receipt(
            stage, run_id, policy["policySha256"]
        )
        for stage in ("generation", "review", "revision")
    }
    receipt_registry.register_question_model_invocation_receipts(
        "research-team",
        question_id="SCI-096",
        workflow_run_id=run_id,
        receipts=[deepcopy(receipts[stage]) for stage in receipts],
    )
    return receipts


def _stage_one_v2_artifact(
    output: dict, receipts: dict[str, dict], *, with_authority: bool
) -> dict:
    """The research_result_package payload the v2 producer now commits."""

    package: dict = {
        "runId": "run-sci-096",
        "questionId": "SCI-096",
        "contentHash": "a" * 64,
        "challengeQuestionOutput": output,
        "citationChecks": _citation_checks(output),
    }
    if with_authority:
        policy = _stage_one_frozen_policy()
        package.update(
            {
                "modelInvocationReceipts": deepcopy(receipts),
                "modelPolicy": deepcopy(policy),
                "authorizedModelPolicySha256": policy["policySha256"],
                "inputSnapshotSha256": "c" * 64,
            }
        )
    return {
        "teamId": "research-team",
        "workflowRunId": "run-sci-096",
        "sourceCollectionRunId": "run-sci-096",
        "package": package,
    }


def _patch_stage_one_v2_artifact(
    monkeypatch, artifact: dict
) -> None:
    monkeypatch.setattr(
        program_candidate_handoff,
        "load_scoped_artifact_payload",
        lambda *args, **kwargs: {
            "teamId": "research-team",
            "workflowRunId": "run-sci-096",
            "sourceCollectionRunId": "run-sci-096",
            "payload": artifact,
        },
    )


def test_stage_one_v2_handoff_registers_canonical_package_end_to_end(
    tmp_path, monkeypatch
):
    _isolate_store(tmp_path, monkeypatch)
    output = _output()
    output["run"]["run_id"] = "run-sci-096"
    # The legacy evidence-id proxy must not satisfy the official gate; only
    # the canonical package path may flip officialModelCall.
    # A non-empty schema-required ref list whose ids match no official
    # evidence row, so only the canonical package path can flip the gate.
    output["run"]["invocation_evidence_refs"] = [
        "model-invocation-receipt:unregistered-receipt"
    ]
    receipts = _seed_stage_one_registry("run-sci-096")
    _patch_stage_one_v2_artifact(
        monkeypatch,
        _stage_one_v2_artifact(output, receipts, with_authority=True),
    )

    result = program_candidate_handoff.handoff_result_package_to_challenge_program(
        team_id="research-team",
        workflow_run_id="run-sci-096",
    )

    assert result["status"] == "registered"
    assert result["officialModelCall"] is True
    package_metadata = result["resultPackage"]
    assert isinstance(package_metadata, dict)
    assert package_metadata["locator"]
    assert Path(package_metadata["locator"]).is_file()

    store = json.loads(
        challenge_question_runs._store_path("research-team").read_text(
            encoding="utf-8"
        )
    )
    record = store["records"][0]
    assert record["validation"]["officialModelCall"] is True
    assert record["validation"]["modelInvocationReceipts"] == "passed"
    assert "modelInvocationReceiptIssue" not in record["validation"]
    assert set(record["modelInvocationReceiptRefs"]) == {
        "generation",
        "review",
        "revision",
    }
    assert record["resultPackage"]["canonicalHash"] == (
        package_metadata["canonicalHash"]
    )

    replay = (
        program_candidate_handoff.handoff_result_package_to_challenge_program(
            team_id="research-team",
            workflow_run_id="run-sci-096",
        )
    )
    assert replay["status"] == "idempotent"
    assert replay["officialModelCall"] is True


def test_stage_one_v2_handoff_without_receipt_authority_keeps_legacy_degradation(
    tmp_path, monkeypatch
):
    _isolate_store(tmp_path, monkeypatch)
    output = _output()
    output["run"]["run_id"] = "run-sci-096"
    # A non-empty schema-required ref list whose ids match no official
    # evidence row, so only the canonical package path can flip the gate.
    output["run"]["invocation_evidence_refs"] = [
        "model-invocation-receipt:unregistered-receipt"
    ]
    # A package built while the receipt registry was incomplete carries no
    # canonical-package evidence keys, so the bridge must register exactly as
    # it did before this fix (fail closed, officialModelCall false).
    _patch_stage_one_v2_artifact(
        monkeypatch,
        _stage_one_v2_artifact(output, receipts={}, with_authority=False),
    )

    result = program_candidate_handoff.handoff_result_package_to_challenge_program(
        team_id="research-team",
        workflow_run_id="run-sci-096",
    )

    assert result["status"] == "registered"
    assert result["officialModelCall"] is False
    assert result["receiptStatus"] == "failed"
    store = json.loads(
        challenge_question_runs._store_path("research-team").read_text(
            encoding="utf-8"
        )
    )
    record = store["records"][0]
    assert record["validation"]["officialModelCall"] is False
    assert record["validation"]["modelInvocationReceiptIssue"] == (
        "canonical_result_package_missing"
    )
    assert "resultPackage" not in record
