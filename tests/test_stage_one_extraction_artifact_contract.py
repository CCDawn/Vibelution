"""A valid extraction writeback must remain valid at artifact construction."""

import pytest

from core.web.services.team_workflow.research_runtime.agent_task_artifact_builder import _source_extraction_payload
from core.web.services.team_workflow.research_runtime.source_extraction_evidence_cards import (
    SourceExtractionEvidenceContractError,
)


def _source(**fields):
    return {
        "candidateId": "source-good", "evidenceStatus": "verified_abstract",
        "title": "Accessible paper", "source_type": "peer_reviewed_paper",
        "source_url": "https://example.org/paper", "retrieved_at": "2026-09-08T00:00:00Z",
        "relation": "supports", "verification_status": "metadata_checked", **fields,
    }


def _build(entries):
    return _source_extraction_payload({"result": {"candidateExtractions": entries}})["evidenceCards"]


@pytest.mark.parametrize("skipped", [
    {"decision": "exclude"},
    {"evidenceStatus": "missing_evidence_anchor"},
    {"evidenceStatus": "unverified"},
])
def test_mixed_success_and_honest_skip_builds_only_real_card(skipped):
    good = _source(fact="Measured result", evidenceRef="paragraph-1")
    cards = _build([good, {"candidateId": "unavailable-source", **skipped}])
    assert len(cards) == 1
    assert cards[0]["candidateId"] == "source-good"


def test_claims_and_findings_preserve_each_explicit_fact():
    cards = _build([_source(
        claims=[{"fact": "First result", "quote": "First result", "evidenceRef": "p1"}],
        keyFindings=[{"fact": "Second result", "quote": "Second result", "evidenceRef": "p2"}],
    )])
    assert {card["fact"] for card in cards} == {"First result", "Second result"}


def test_claim_only_source_does_not_need_a_duplicate_parent_fact():
    cards = _build([_source(claims=[{"fact": "Measured result", "quote": "Measured result", "evidenceRef": "p1"}])])
    assert cards[0]["fact"] == "Measured result"


def test_flat_quote_reference_id_is_an_explicit_locator():
    cards = _build([_source(fact="Measured result", evidenceRefs=[
        {"type": "paragraph", "id": "paragraph-1", "quote": "Measured result"},
    ])])
    assert cards[0]["citationLocator"]["evidenceRef"] == "paragraph-1"


def test_all_unavailable_sources_produce_no_cards():
    assert _build([{"candidateId": "missing", "evidenceStatus": "missing_evidence_anchor"}]) == []
    from core.web.services.team_workflow.research_runtime.artifact_quality_gate import (
        ArtifactQualityError, validate_artifact_quality,
    )
    with pytest.raises(ArtifactQualityError, match="every evidence card"):
        validate_artifact_quality(
            {"runId": "run-current"}, node_id="source_extraction",
            manifests=[{"artifactId": "evidence_card_batch:empty"}],
            payloads={"evidence_card_batch:empty": {"evidenceCards": []}},
        )


def test_active_incomplete_source_still_fails_contract():
    with pytest.raises(SourceExtractionEvidenceContractError):
        _build([{"candidateId": "bad", "evidenceStatus": "evidence_ready"}])


def test_writeback_rejects_invalid_shape_before_artifact_construction(monkeypatch):
    from core.web.services.team_workflow.source_collection import stage_writeback
    monkeypatch.setattr(stage_writeback, "_source_collection_stage_writeback_formal_claim_bound", lambda *_: True)
    errors = stage_writeback._source_collection_stage_writeback_extraction_card_contract_errors(
        {"stageId": "extraction"}, "source-run",
        {"candidateExtractions": [_source(keyFindings=["Unstructured finding"])]},
    )
    assert errors and "keyFindings[0] must be an object" in errors[0]
