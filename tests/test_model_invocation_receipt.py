"""ModelInvocationReceipt contract tests: bounded serialization, scrubbing,
stable statuses and no-silent-degradation enforcement."""

from __future__ import annotations

import json

import pytest

from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
    bound_excerpt,
)

SCOPE = {
    "teamId": "research-team",
    "runId": "run-sci-096",
    "nodeRunId": "nr-sci-096-a5",
    "nodeId": "hypothesis_design",
    "attempt": "1",
}


def _receipt(**overrides):
    defaults = {
        "provider": "offline-fake",
        "model": "fake-model-v2",
        "model_version": "2.0",
        "requested_model": "fake-model-v2",
        "status": ModelInvocationStatus.SUCCEEDED,
        "request_content": "ROUND_PROMPT" * 500,
        "response_content": "ROUND_RESPONSE" * 500,
        "started_at_ms": 1_000,
        "finished_at_ms": 1_400,
        "token_usage": {"inputTokens": 100, "outputTokens": 40, "totalTokens": 140},
        "cost": {"currency": "USD", "totalCost": 0.0042},
        "metadata": {"note": "ok"},
        "evidence_locator": {"kind": "runtime_scene", "sceneId": "scene-1"},
    }
    defaults.update(overrides)
    return ModelInvocationReceipt.from_invocation(
        receipt_id="inv-1",
        run_id="run-sci-096",
        node_run_id="nr-sci-096-a5",
        scope=SCOPE,
        **defaults,
    )


def test_from_invocation_bounds_content_and_hashes() -> None:
    receipt = _receipt()
    assert len(receipt.request_excerpt) <= 259
    assert len(receipt.response_excerpt) <= 259
    assert "ROUND_PROMPT" * 500 not in receipt.request_excerpt
    assert "ROUND_RESPONSE" * 500 not in receipt.response_excerpt
    assert len(receipt.request_summary_hash) == 64
    assert len(receipt.response_summary_hash) == 64
    assert receipt.request_summary_hash != receipt.response_summary_hash
    again = _receipt()
    assert again.request_summary_hash == receipt.request_summary_hash


def test_serialization_scrubs_secrets_and_bounds_excerpts() -> None:
    receipt = _receipt(
        request_content=(
            "api-key: sk-live-1234 Authorization: Bearer TOK cookie: c=1 "
        ),
        response_content="secret: hunter2",
        metadata={
            "authHeaders": {"apiKey": "sk-xyz", "ok": True},
            "credentials": {"apiKey": "sk-outer"},
        },
        cost={"apiKey": "sk-cost"},
    )
    payload = receipt.to_dict()
    serialized = json.dumps(payload, ensure_ascii=False)
    for secret in ("sk-live-1234", "Bearer TOK", "hunter2", "sk-xyz", "Bearer abcd", "sk-cost", "sk-outer"):
        assert secret not in serialized
    assert "<redacted>" in payload["requestExcerpt"]
    assert "<redacted>" in payload["responseExcerpt"]
    assert payload["metadata"]["authHeaders"]["apiKey"] == "<redacted>"
    assert payload["metadata"]["authHeaders"]["ok"] is True
    assert payload["metadata"]["credentials"] == "<redacted>"
    assert payload["cost"]["apiKey"] == "<redacted>"
    decoded = ModelInvocationReceipt.from_dict(payload)
    assert "sk-xyz" not in json.dumps(decoded.to_dict(), ensure_ascii=False)


def test_direct_construction_is_bounded_on_serialization() -> None:
    receipt = _receipt(request_content="x" * 5000)
    payload = receipt.to_dict()
    assert len(payload["requestExcerpt"]) <= 259
    assert "x" * 5000 not in payload["requestExcerpt"]


def test_six_statuses_roundtrip() -> None:
    for status in ModelInvocationStatus:
        kwargs = {}
        if status is ModelInvocationStatus.NOT_CONFIGURED:
            kwargs = {
                "provider": "",
                "model": "",
                "requested_model": "",
                "status": status,
                "started_at_ms": 0,
                "finished_at_ms": 0,
                "request_content": None,
                "response_content": None,
            }
        elif status is ModelInvocationStatus.RETRIED:
            kwargs = {"status": status, "attempt": 3, "retry_count": 2}
        elif status is ModelInvocationStatus.MODEL_IDENTITY_DRIFT:
            kwargs = {
                "status": status,
                "requested_model": "fake-model-v1",
                "model": "fallback-model-v2",
                "evidence_locator": {"kind": "runtime_scene", "sceneId": "drift-1"},
            }
        else:
            kwargs = {"status": status}
        receipt = _receipt(**kwargs)
        decoded = ModelInvocationReceipt.from_dict(receipt.to_dict())
        assert decoded == receipt
        assert decoded.status is status


def test_silent_model_degradation_is_rejected() -> None:
    with pytest.raises(ContractValidationError, match="model_identity_drift"):
        _receipt(
            requested_model="fake-model-v2",
            model="fallback-model-v2",
            status=ModelInvocationStatus.SUCCEEDED,
        )


def test_model_identity_drift_requires_evidence() -> None:
    with pytest.raises(ContractValidationError, match="evidence_locator"):
        _receipt(
            requested_model="fake-model-v1",
            model="fallback-model-v2",
            status=ModelInvocationStatus.MODEL_IDENTITY_DRIFT,
            evidence_locator=None,
        )
    ok = _receipt(
        requested_model="fake-model-v1",
        model="fallback-model-v2",
        status=ModelInvocationStatus.MODEL_IDENTITY_DRIFT,
        evidence_locator={"kind": "runtime_scene", "sceneId": "drift-1"},
    )
    assert ok.status is ModelInvocationStatus.MODEL_IDENTITY_DRIFT
    assert ok.evidence_locator["sceneId"] == "drift-1"


def test_not_configured_is_terminated_with_zero_work() -> None:
    with pytest.raises(ContractValidationError, match="latency"):
        _receipt(
            provider="",
            model="",
            status=ModelInvocationStatus.NOT_CONFIGURED,
            started_at_ms=100,
            finished_at_ms=300,
            request_content=None,
            response_content=None,
        )
    with pytest.raises(ContractValidationError, match="retryCount"):
        _receipt(
            provider="",
            model="",
            status=ModelInvocationStatus.NOT_CONFIGURED,
            retry_count=1,
            request_content=None,
            response_content=None,
        )


def test_retried_status_requires_retry_count() -> None:
    with pytest.raises(ContractValidationError, match="retryCount"):
        _receipt(status=ModelInvocationStatus.RETRIED, retry_count=0)


def test_from_dict_rejects_unknown_status() -> None:
    payload = _receipt().to_dict()
    payload["status"] = "hallucinated"
    with pytest.raises(ContractValidationError, match="status"):
        ModelInvocationReceipt.from_dict(payload)


def test_metadata_defaults_to_empty_and_roundtrips() -> None:
    receipt = _receipt(metadata=None, cost=None, evidence_locator=None)
    payload = receipt.to_dict()
    assert payload["metadata"] == {}
    assert payload["cost"] == {}
    assert payload["evidenceLocator"] == {}
    decoded = ModelInvocationReceipt.from_dict(payload)
    assert decoded == receipt


def test_bound_excerpt_redacts_embedded_credentials() -> None:
    excerpt = bound_excerpt("Authorization: Bearer abc DEF api-key sk-x AKIA1234567890ABCDEF ok")
    assert "Bearer" not in excerpt
    assert "sk-x" not in excerpt
    assert "AKIA1234567890ABCDEF" not in excerpt