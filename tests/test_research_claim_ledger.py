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


def _ledger_lines(team_id):
    path = service._store_path(team_id)
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_propose_replay_merges_new_evidence_refs_idempotently(tmp_path, monkeypatch):
    """首提无 refs → 重放带 refs → 合并追加且幂等（SCI-085 修复语义）。

    A claim id proposed ref-less (selection-time binding) must accept
    evidence refs collected later on replay: new refs attach by
    ``claimEvidenceId`` dedupe, a fully-known replay appends nothing, and the
    attachment is auditable on the appended ledger record.
    """
    team_id = _team(tmp_path, monkeypatch)
    first = service.propose_claim(team_id, _claim())["claim"]
    scope_hash = first["scopeHash"]
    ref_one = _evidence(scope_hash, review="pending", evidence_id="evidence-1")
    ref_two = _evidence(scope_hash, review="pending", evidence_id="evidence-2")

    attached = service.propose_claim(team_id, _claim(evidenceRefs=[ref_one]))
    assert attached["status"] == "reused"
    assert attached["attachedRefs"] == 1
    assert [ref["claimEvidenceId"] for ref in attached["claim"]["evidenceRefs"]] == [
        "evidence-1"
    ]
    assert attached["claim"]["attachedEvidenceRefs"] == [ref_one]
    assert attached["claim"]["evidenceRefsAttachedAt"]
    # Identity fields stay untouched by the attachment.
    assert attached["claim"]["claim"] == first["claim"]
    assert attached["claim"]["status"] == "proposed"
    assert attached["claim"]["createdAt"] == first["createdAt"]
    assert len(_ledger_lines(team_id)) == 2  # created + one attach record

    # Idempotent: the same replay attaches nothing and writes nothing.
    replayed = service.propose_claim(team_id, _claim(evidenceRefs=[ref_one]))
    assert replayed["status"] == "reused"
    assert replayed["attachedRefs"] == 0
    assert len(_ledger_lines(team_id)) == 2

    # Partial overlap: only the genuinely new id attaches, order preserved.
    merged = service.propose_claim(
        team_id, _claim(evidenceRefs=[ref_one, ref_two])
    )
    assert merged["attachedRefs"] == 1
    assert [ref["claimEvidenceId"] for ref in merged["claim"]["evidenceRefs"]] == [
        "evidence-1",
        "evidence-2",
    ]
    assert len(_ledger_lines(team_id)) == 3

    # The latest row is what readers (the belief gate) see.
    rows = [
        item
        for item in service.list_claims(team_id)["claims"]
        if item["claimId"] == first["claimId"]
    ]
    assert len(rows) == 1
    assert len(rows[0]["evidenceRefs"]) == 2


def test_propose_replay_never_rewrites_existing_refs(tmp_path, monkeypatch):
    """重放不允许改写既有 refs：同 id 不同快照（pending→accepted/contradicts）
    的 incoming ref 被忽略，行上保持原快照。"""
    team_id = _team(tmp_path, monkeypatch)
    first = service.propose_claim(team_id, _claim())["claim"]
    original = _evidence(first["scopeHash"], review="pending", evidence_id="evidence-1")
    service.propose_claim(team_id, _claim(evidenceRefs=[original]))

    drifted = _evidence(
        first["scopeHash"],
        review="accepted",
        support="contradicts",
        evidence_id="evidence-1",
    )
    replay = service.propose_claim(team_id, _claim(evidenceRefs=[drifted]))
    assert replay["status"] == "reused"
    assert replay["attachedRefs"] == 0
    assert replay["claim"]["evidenceRefs"] == [original]
    assert len(_ledger_lines(team_id)) == 2  # no rewrite record appended


def test_propose_replay_still_binds_identity_and_frozen_rows(tmp_path, monkeypatch):
    """内容绑定不放松：非 refs 字段漂移仍拒绝；supported 行冻结，重放
    pending refs 不允许挂上（fail-closed，合同要求 accepted-only refs）。"""
    team_id = _team(tmp_path, monkeypatch)
    proposed = service.propose_claim(team_id, _claim())["claim"]
    scope_hash = proposed["scopeHash"]

    with pytest.raises(service.ClaimLedgerError, match="different content"):
        service.propose_claim(team_id, _claim(claim="Drifted claim text."))
    with pytest.raises(service.ClaimLedgerError, match="different content"):
        service.propose_claim(team_id, _claim(createdBy="someone-else"))

    service.support_claim(
        team_id,
        proposed["claimId"],
        {
            "evidenceRefs": [_evidence(scope_hash, evidence_id="evidence-support")],
            "supportedBy": "agent-evaluator",
        },
    )
    with pytest.raises(service.ClaimLedgerError, match="different content"):
        service.propose_claim(
            team_id,
            _claim(
                evidenceRefs=[
                    _evidence(scope_hash, review="pending", evidence_id="evidence-late")
                ]
            ),
        )
