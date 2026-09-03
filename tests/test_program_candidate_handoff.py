"""Focused contract tests for the result-package -> Challenge Program bridge."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from core.web.services.team_workflow import challenge_question_runs
from core.web.services.team_workflow.research_runtime import (
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


def test_completion_manifest_requires_fresh_approved_program_readback():
    approved = {
        "workflowRunId": "workflow-sci-096",
        "questionId": "SCI-096",
        "recordId": "SCI-096:workflow-sci-096",
        "reviewStatus": "approved",
        "outputSha256": "e" * 64,
        "sourceResultPackageHash": "a" * 64,
        "resultPackage": {"canonicalHash": "c" * 64},
        "officialModelCall": True,
        "receiptStatus": "passed",
        "humanGates": {"allApproved": True, "approvedCount": 4},
    }

    manifest = program_candidate_handoff.stage_one_completion_manifest_from_handoff(
        approved,
        policy_sha256="d" * 64,
    )

    assert manifest["programRecordId"] == approved["recordId"]
    assert manifest["programReviewStatus"] == "approved"
    assert manifest["receiptStatus"] == "passed"
    assert manifest["receiptAuthority"] == "canonical_result_package"
    assert "receiptTraceCount" not in manifest
    assert "receiptTraceDigest" not in manifest
    assert len(manifest["manifestSha256"]) == 64

    pending = deepcopy(approved)
    pending["reviewStatus"] = "review_required"
    pending["humanGates"] = {"allApproved": False, "approvedCount": 0}
    with pytest.raises(
        program_candidate_handoff.ProgramCandidateHandoffContractError,
        match="not approved",
    ):
        program_candidate_handoff.stage_one_completion_manifest_from_handoff(
            pending,
            policy_sha256="d" * 64,
        )


def test_v2_handoff_without_result_package_builds_trace_verified_manifest(
    monkeypatch,
):
    """A v2 run with no canonical package still carries honest receipt proof."""

    _isolate_v2_trace_handoff(monkeypatch)
    monkeypatch.setattr(
        challenge_question_runs,
        "_question_model_invocation_trace_projection",
        lambda _team_id, _record: (
            deepcopy(_TRACE_REFS),
            deepcopy(_TRACE_COVERAGE),
        ),
    )

    result = program_candidate_handoff.handoff_result_package_to_challenge_program(
        team_id="research-team",
        workflow_run_id="workflow-sci-096",
    )

    assert result["receiptStatus"] != "passed"
    assert result["receiptTraceVerified"] is True
    assert result["receiptTraceCount"] == 2
    assert result["receiptTraceDigest"] == _trace_digest(_TRACE_REFS)

    manifest = program_candidate_handoff.stage_one_completion_manifest_from_handoff(
        result,
        policy_sha256="d" * 64,
    )

    assert manifest["receiptStatus"] == "trace_verified"
    assert manifest["receiptAuthority"] == "model_invocation_trace"
    assert manifest["receiptTraceCount"] == 2
    assert manifest["receiptTraceDigest"] == _trace_digest(_TRACE_REFS)
    assert manifest["canonicalPackageHash"] == result["sourceResultPackageHash"]
    assert len(manifest["manifestSha256"]) == 64


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
    with pytest.raises(
        program_candidate_handoff.ProgramCandidateHandoffContractError,
        match="not approved",
    ):
        program_candidate_handoff.stage_one_completion_manifest_from_handoff(
            result,
            policy_sha256="d" * 64,
        )
