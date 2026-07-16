from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import research_evidence_service, team_service


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _payload():
    return {
        "claimId": "claim-1",
        "candidateId": "candidate-1",
        "sourceId": "pmid:27917138",
        "sourceRevision": "sha256:" + "a" * 64,
        "locator": {"kind": "pdf_page", "page": 4},
        "quote": "A bounded source excerpt.",
        "evidenceKind": "review_summary",
        "reasoningRole": "fact",
        "supportLevel": "supports",
        "extractionMethod": "manual",
        "extractorAgentId": "agent-source-extractor",
    }


def test_research_evidence_routes_register_review_and_report_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_evidence_service, "PROJECT_ROOT", tmp_path)
    client = _client()
    team = client.post("/api/teams", json={"name": "科研证据团队"}).json()
    team_id = team["teamId"]

    created = client.post(f"/api/teams/{team_id}/research-evidence/claims", json=_payload())
    evidence_id = created.json()["evidence"]["claimEvidenceId"]
    reviewed = client.post(
        f"/api/teams/{team_id}/research-evidence/claims/{evidence_id}/review",
        json={
            "decision": "accepted",
            "reviewedBy": "agent-research-reviewer",
            "note": "Checked against the source.",
        },
    )
    listed = client.get(f"/api/teams/{team_id}/research-evidence/claims?candidateId=candidate-1")
    coverage = client.get(f"/api/teams/{team_id}/research-evidence/coverage?candidateId=candidate-1")

    assert created.status_code == 201, created.text
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["evidence"]["reviewStatus"] == "accepted"
    assert listed.status_code == 200, listed.text
    assert listed.json()["summary"]["count"] == 1
    assert coverage.status_code == 200, coverage.text
    assert coverage.json()["evidenceGatePassed"] is True
    assert coverage.json()["formalKnowledgeWriteAllowed"] is False


def test_research_evidence_routes_keep_legacy_projection_shadow_only(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_evidence_service, "PROJECT_ROOT", tmp_path)
    client = _client()
    team = client.post("/api/teams", json={"name": "科研证据团队"}).json()
    team_id = team["teamId"]

    projected = client.post(
        f"/api/teams/{team_id}/research-evidence/legacy-projection",
        json={
            "candidateId": "candidate-legacy",
            "legacyEntries": [{"claim": "Legacy claim", "citation": "PMID:1", "excerpt": "Abstract only"}],
        },
    )
    listed = client.get(f"/api/teams/{team_id}/research-evidence/claims")

    assert projected.status_code == 200, projected.text
    assert projected.json()["evidence"][0]["shadowOnly"] is True
    assert projected.json()["boundaries"]["persistsCanonicalEvidence"] is False
    assert listed.json()["summary"]["count"] == 0


def test_research_evidence_routes_reject_invalid_or_missing_team(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_evidence_service, "PROJECT_ROOT", tmp_path)
    client = _client()

    missing = client.post("/api/teams/missing/research-evidence/claims", json=_payload())
    team = client.post("/api/teams", json={"name": "科研证据团队"}).json()
    invalid_payload = _payload()
    invalid_payload["sourceRevision"] = "unknown"
    invalid = client.post(f"/api/teams/{team['teamId']}/research-evidence/claims", json=invalid_payload)

    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert "sourceRevision" in invalid.text
