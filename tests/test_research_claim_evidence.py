import json

import pytest

from core.research.evidence import ClaimEvidenceError, ClaimEvidenceStore
from core.research.third_party import research_component_catalog


def _payload(**overrides):
    payload = {
        "claimId": "claim-predictive-coding-1",
        "candidateId": "candidate-paper-1",
        "sourceId": "pmid:27917138",
        "sourceRevision": "sha256:" + "a" * 64,
        "locator": {"kind": "pdf_page", "page": 7, "section": "3.2"},
        "quote": "Prediction errors are propagated through the hierarchy.",
        "evidenceKind": "review_summary",
        "reasoningRole": "fact",
        "supportLevel": "supports",
        "extractionMethod": "paperqa2",
        "extractorAgentId": "agent-source-extractor",
        "modelRef": "ai-pixel/gpt-5.6-terra",
    }
    payload.update(overrides)
    return payload


def test_third_party_catalog_pins_reusable_research_components():
    catalog = research_component_catalog()

    assert catalog["schemaVersion"] == 1
    assert {item["componentId"] for item in catalog["components"]} >= {
        "paperqa2",
        "agent-skills-reference",
    }
    for item in catalog["components"]:
        assert item["license"] in {"Apache-2.0", "MIT"}
        assert item["sourceUrl"].startswith("https://github.com/")
        assert item["pin"]
        assert item["integrationMode"] in {"dependency", "component", "managed_skill"}
        assert item["writesCanonicalResearchState"] is False
        assert item["featureFlagDefault"] is False


def test_claim_evidence_requires_revision_locator_and_fact_inference_boundary(tmp_path):
    store = ClaimEvidenceStore(tmp_path)

    with pytest.raises(ClaimEvidenceError, match="sourceRevision"):
        store.register("research-team", _payload(sourceRevision=""))
    with pytest.raises(ClaimEvidenceError, match="locator"):
        store.register("research-team", _payload(locator={}))
    with pytest.raises(ClaimEvidenceError, match="quote"):
        store.register("research-team", _payload(quote=""))
    with pytest.raises(ClaimEvidenceError, match="reasoningRole"):
        store.register("research-team", _payload(reasoningRole="proved_by_paper"))


def test_claim_evidence_is_idempotent_and_marks_changed_source_stale(tmp_path):
    store = ClaimEvidenceStore(tmp_path)

    first = store.register("research-team", _payload())
    duplicate = store.register("research-team", _payload())

    assert duplicate["claimEvidenceId"] == first["claimEvidenceId"]
    assert duplicate["quoteHash"].startswith("sha256:")
    assert len(store.list("research-team")) == 1

    refreshed = store.reconcile_source_revision(
        "research-team",
        source_id="pmid:27917138",
        current_revision="sha256:" + "b" * 64,
    )

    assert refreshed["staleCount"] == 1
    assert store.list("research-team")[0]["reviewStatus"] == "stale"
    assert store.list("research-team")[0]["staleReason"] == "source_revision_changed"


def test_legacy_evidence_projects_as_unverified_without_writing(tmp_path):
    store = ClaimEvidenceStore(tmp_path)
    legacy = [
        {
            "claim": "The cortex uses hierarchical prediction errors.",
            "citation": "PMID:27917138",
            "excerpt": "Abstract-level summary only.",
        }
    ]

    projected = store.project_legacy(
        "research-team",
        candidate_id="candidate-paper-1",
        legacy_entries=legacy,
    )

    assert projected[0]["evidenceKind"] == "legacy_unverified"
    assert projected[0]["reasoningRole"] == "inference"
    assert projected[0]["supportLevel"] == "unverified"
    assert projected[0]["reviewStatus"] == "pending"
    assert projected[0]["shadowOnly"] is True
    assert store.list("research-team") == []
    assert not (tmp_path / "workspace" / "teams" / "research-team" / "claim_evidence" / "index.jsonl").exists()


def test_claim_evidence_storage_is_append_safe_jsonl(tmp_path):
    store = ClaimEvidenceStore(tmp_path)
    record = store.register("research-team", _payload())
    path = tmp_path / "workspace" / "teams" / "research-team" / "claim_evidence" / "index.jsonl"

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert rows == [record]
    assert record["schemaVersion"] == 1
    assert record["reviewStatus"] == "pending"
    assert record["formalKnowledgeWriteAllowed"] is False


def test_claim_evidence_review_and_coverage_preserve_counter_evidence(tmp_path):
    store = ClaimEvidenceStore(tmp_path)
    supporting = store.register("research-team", _payload())
    counter = store.register(
        "research-team",
        _payload(
            claimId="claim-predictive-coding-2",
            quote="The reported evidence does not establish the proposed implementation.",
            evidenceKind="counter_evidence",
            supportLevel="contradicts",
        ),
    )

    accepted = store.review(
        "research-team",
        supporting["claimEvidenceId"],
        decision="accepted",
        reviewed_by="agent-research-reviewer",
        note="Locator and wording checked against the source.",
    )
    store.review(
        "research-team",
        counter["claimEvidenceId"],
        decision="accepted",
        reviewed_by="agent-research-reviewer",
        note="Counter-evidence must remain visible.",
    )
    coverage = store.coverage("research-team", candidate_id="candidate-paper-1")

    assert accepted["reviewStatus"] == "accepted"
    assert accepted["formalKnowledgeWriteAllowed"] is False
    assert coverage["summary"] == {
        "total": 2,
        "accepted": 2,
        "pending": 0,
        "rejected": 0,
        "stale": 0,
        "supports": 1,
        "contradicts": 1,
        "unverified": 0,
    }
    assert coverage["evidenceGatePassed"] is True
    assert coverage["counterEvidencePresent"] is True


def test_model_extracted_evidence_requires_model_identity(tmp_path):
    store = ClaimEvidenceStore(tmp_path)

    with pytest.raises(ClaimEvidenceError, match="modelRef"):
        store.register(
            "research-team",
            _payload(extractionMethod="model", modelRef=""),
        )
