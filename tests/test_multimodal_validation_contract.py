"""MultimodalValidationReport contract tests: modality coverage, parsability,
citation locating, supports/refutes verdicts, failure reasons and fail-closed
rejection of invalid/over-limit/missing-citation inputs."""

from __future__ import annotations

import pytest

from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.multimodal_validation import (
    CitationLocator,
    ClaimVerdict,
    Modality,
    MultimodalValidationReport,
    ValidationFailure,
    ValidationFailureCode,
    Verdict,
)

SCOPE = {
    "teamId": "research-team",
    "runId": "run-sci-096",
    "nodeRunId": "nr-sci-096-a5",
    "nodeId": "source_extraction",
}

CITATION = CitationLocator(
    citation_id="cite-1",
    modality=Modality.TEXT,
    offset=120,
    length=64,
    source_ref="source-package:abc",
    snippet_hash="a" * 64,
)


def _report(**overrides):
    defaults = {
        "input_types": (Modality.TEXT, Modality.IMAGE),
        "parsed": True,
        "parse_error": "",
        "input_byte_size": 4096,
        "input_max_bytes": 8192,
        "citations": (CITATION,),
        "verdicts": (
            ClaimVerdict(
                claim_ref="claim-1",
                verdict=Verdict.SUPPORTS,
                evidence_refs=("source-package:abc",),
                rationale="图示与文本一致。",
            ),
        ),
        "failures": (),
        "verdict": Verdict.SUPPORTS,
        "valid": True,
    }
    defaults.update(overrides)
    return MultimodalValidationReport(
        report_id="mm-1",
        run_id="run-sci-096",
        node_run_id="nr-sci-096-a5",
        scope=SCOPE,
        created_at_ms=1_750_000_000_000,
        **defaults,
    )


def test_valid_report_roundtrip() -> None:
    report = _report()
    decoded = MultimodalValidationReport.from_dict(report.to_dict())
    assert decoded == report
    payload = report.to_dict()
    assert payload["inputTypes"] == ["text", "image"]
    assert payload["parsed"] is True
    assert payload["valid"] is True
    assert payload["verdict"] == "supports"
    assert payload["citations"][0]["sourceRef"] == "source-package:abc"


def test_unknown_modality_is_fail_closed() -> None:
    failure = ValidationFailure(ValidationFailureCode.INVALID_MODALITY, "不支持的模态")
    report = _report(
        input_types=(Modality.TEXT, Modality.UNKNOWN),
        verdicts=(),
        citations=(),
        failures=(failure,),
        verdict=Verdict.REJECTED,
        valid=False,
    )
    payload = report.to_dict()
    assert payload["valid"] is False
    assert payload["verdict"] == "rejected"
    assert [f["code"] for f in payload["failures"]] == ["invalid_modality"]
    decoded = MultimodalValidationReport.from_dict(payload)
    assert decoded == report
    with pytest.raises(ContractValidationError, match="invalid_modality"):
        _report(
            input_types=(Modality.TEXT, Modality.UNKNOWN),
            verdicts=(),
            citations=(),
            failures=(),
            verdict=Verdict.REJECTED,
            valid=False,
        )


def test_over_limit_is_fail_closed() -> None:
    with pytest.raises(ContractValidationError, match="over_limit"):
        _report(
            input_byte_size=20_000,
            input_max_bytes=8_192,
            failures=(),
            verdict=Verdict.REJECTED,
            valid=False,
        )
    report = _report(
        input_byte_size=20_000,
        input_max_bytes=8_192,
        verdicts=(),
        citations=(),
        failures=(ValidationFailure(ValidationFailureCode.OVER_LIMIT, "输入超限"),),
        verdict=Verdict.REJECTED,
        valid=False,
    )
    assert report.valid is False
    assert report.verdict is Verdict.REJECTED


def test_unparsable_is_fail_closed() -> None:
    with pytest.raises(ContractValidationError, match="unparsable"):
        _report(
            parsed=False,
            parse_error="image bytes 不可解码",
            failures=(),
            verdict=Verdict.REJECTED,
            valid=False,
        )
    report = _report(
        parsed=False,
        parse_error="image bytes 不可解码",
        verdicts=(),
        citations=(),
        failures=(
            ValidationFailure(ValidationFailureCode.UNPARSABLE, "image bytes 不可解码"),
        ),
        verdict=Verdict.REJECTED,
        valid=False,
    )
    assert report.valid is False
    assert report.parse_error == "image bytes 不可解码"


def test_missing_citation_is_fail_closed() -> None:
    with pytest.raises(ContractValidationError, match="missing_citation"):
        _report(
            verdicts=(ClaimVerdict("claim-1", Verdict.SUPPORTS, (), "无引用"),),
        )
    with pytest.raises(ContractValidationError, match="missing_citation"):
        _report(citations=(), verdicts=())


def test_verdicts_support_and_refute_with_evidence() -> None:
    report = _report(
        verdicts=(
            ClaimVerdict(
                "claim-1", Verdict.SUPPORTS, ("source-package:abc",), "支持"
            ),
            ClaimVerdict(
                "claim-2", Verdict.REFUTES, ("counter-evidence:def",), "反驳"
            ),
        ),
        verdict=Verdict.NEUTRAL,
    )
    payload = report.to_dict()
    assert len(payload["verdicts"]) == 2
    assert payload["verdicts"][1]["verdict"] == "refutes"
    decoded = MultimodalValidationReport.from_dict(payload)
    assert decoded == report


def test_from_dict_rejects_unknown_modality_and_verdict() -> None:
    payload = _report().to_dict()
    payload["inputTypes"] = ["text", "hologram"]
    with pytest.raises(ContractValidationError, match="modality"):
        MultimodalValidationReport.from_dict(payload)
    payload = _report().to_dict()
    payload["verdict"] = "unknown"
    with pytest.raises(ContractValidationError, match="verdict"):
        MultimodalValidationReport.from_dict(payload)


def test_citation_locator_validation() -> None:
    with pytest.raises(ContractValidationError, match="snippetHash"):
        CitationLocator("cite-1", Modality.TEXT, 0, 4, "ref-1", "not-a-hash")
    with pytest.raises(ContractValidationError, match="offset"):
        CitationLocator("cite-1", Modality.TEXT, -1, 4, "ref-1", "a" * 64)