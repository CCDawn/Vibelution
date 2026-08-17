"""D04 append-only claim ledger and accepted-evidence promotion tests."""

from __future__ import annotations

import pytest

from core.research.workflow.contracts import ContractValidationError
from core.web.services import team_service
from core.web.services.team_workflow import claim_ledger as service


def _team(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    return team_service.create_team(name="claim ledger team")["teamId"]


def _claim(**overrides):
    payload = {
        "program": "XH-202619",
        "theme": "cc-gpu-operator-001",
        "campaign": "cc-campaign-gpu-operator-001",
        "question": "SCI-091",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-evaluator",
        "mode": "formal",
        "claimId": "claim-demo-1",
        "claim": "The bounded operator candidate improves the offline proxy metric.",
        "source": "agent",
        "createdBy": "agent-evaluator",
    }
    payload.update(overrides)
    return payload


def _evidence(scope_hash, *, review="accepted", support="supports", evidence_id="evidence-1"):
    return {
        "claimEvidenceId": evidence_id,
        "scopeHash": scope_hash,
        "reviewStatus": review,
        "supportLevel": support,
        "sourceId": f"artifact:{evidence_id}",
    }


def test_meeting_text_never_promotes_claim_directly(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    proposed = service.propose_claim(
        team_id,
        _claim(source="meeting", evidenceRefs=[]),
    )
    assert proposed["claim"]["status"] == "proposed"
    assert proposed["claim"]["meetingPromotionAllowed"] is False

    with pytest.raises(ContractValidationError, match="never promote"):
        service.propose_claim(
            team_id,
            _claim(
                claimId="claim-meeting-invalid",
                source="meeting",
                evidenceRefs=[_evidence(proposed["claim"]["scopeHash"])],
            ),
        )


def test_claim_id_reuse_is_idempotent_only_for_identical_content(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    first = service.propose_claim(team_id, _claim())
    repeated = service.propose_claim(team_id, _claim())
    assert first["status"] == "created"
    assert repeated["status"] == "reused"

    with pytest.raises(service.ClaimLedgerError, match="different content"):
        service.propose_claim(team_id, _claim(claim="Conflicting claim text."))


def test_support_requires_accepted_scope_consistent_positive_evidence(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    proposed = service.propose_claim(team_id, _claim())["claim"]
    scope_hash = proposed["scopeHash"]

    with pytest.raises(service.ClaimLedgerNotSupportedError, match="accepted"):
        service.support_claim(
            team_id,
            proposed["claimId"],
            {"evidenceRefs": [_evidence(scope_hash, review="pending")]},
        )
    with pytest.raises(service.ClaimLedgerNotSupportedError, match="scope"):
        service.support_claim(
            team_id,
            proposed["claimId"],
            {"evidenceRefs": [_evidence("f" * 64)]},
        )
    with pytest.raises(service.ClaimLedgerNotSupportedError, match="contradictory-only"):
        service.support_claim(
            team_id,
            proposed["claimId"],
            {
                "evidenceRefs": [
                    _evidence(scope_hash, support="contradicts")
                ]
            },
        )

    evidence = [
        _evidence(scope_hash, evidence_id="evidence-support"),
        _evidence(
            scope_hash,
            support="contradicts",
            evidence_id="evidence-counter",
        ),
    ]
    supported = service.support_claim(
        team_id,
        proposed["claimId"],
        {"evidenceRefs": evidence, "supportedBy": "agent-evaluator"},
    )
    repeated = service.support_claim(
        team_id,
        proposed["claimId"],
        {"evidenceRefs": evidence, "supportedBy": "agent-evaluator"},
    )
    assert supported["claim"]["status"] == "supported"
    assert supported["claim"]["counterEvidenceRefs"] == ["evidence-counter"]
    assert repeated["status"] == "reused"


def test_supersede_and_retract_preserve_append_only_history(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    original = service.propose_claim(team_id, _claim())["claim"]
    superseded = service.supersede_claim(
        team_id,
        original["claimId"],
        {
            "claim": "The bounded operator candidate only improves the proxy under low noise.",
            "createdBy": "agent-evaluator",
        },
    )
    assert superseded["supersededClaim"]["status"] == "superseded"
    assert superseded["claim"]["supersedesClaimId"] == original["claimId"]

    retracted = service.retract_claim(
        team_id,
        superseded["claim"]["claimId"],
        {
            "retractedBy": "agent-evaluator",
            "retractionReason": "new counter-evidence",
        },
    )
    assert retracted["claim"]["status"] == "retracted"
    assert service.list_claims(team_id)["claimCount"] == 2
