"""D04 agent-private memory isolation with explicit cross-theme classification."""

from __future__ import annotations

import pytest

from core.web.services import team_service
from core.web.services.team_workflow import personal_memory_candidates as service


def _team(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    return team_service.create_team(name="private memory team")["teamId"]


def _scope(theme="cc-gpu-operator-001", campaign="cc-campaign-gpu-operator-001"):
    return {
        "program": "XH-202619",
        "theme": theme,
        "campaign": campaign,
        "question": "SCI-091",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-coordinator",
        "mode": "formal",
    }


def test_personal_memory_is_physically_agent_private_and_theme_classified(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    result = service.record_personal_memory_candidates(
        team_id,
        scope_payload=_scope(),
        target_scope_payload=_scope(
            theme="cc-neural-mechanism-001",
            campaign="cc-campaign-neural-mechanism-001",
        ),
        agents=["agent/a", "agent_a"],
        source_refs=["meeting_digest:digest-1"],
        memory_class="lesson",
        summaries={
            "agent/a": "Operator evidence may inform neural efficiency questions.",
            "agent_a": "Neural priors remain advisory for operator hypotheses.",
        },
        evidence_status="reported",
    )
    first, second = result["candidates"]

    assert result["storagePathsByAgent"]["agent/a"] != result["storagePathsByAgent"]["agent_a"]
    assert first["theme"] == "cc-gpu-operator-001"
    assert first["targetTheme"] == "cc-neural-mechanism-001"
    assert first["advisoryOnly"] is True
    assert first["needsRevalidation"] is True

    source_view = service.list_personal_memory_candidates(
        team_id, agent_id="agent/a", theme="cc-gpu-operator-001"
    )
    target_view = service.list_personal_memory_candidates(
        team_id, agent_id="agent/a", theme="cc-neural-mechanism-001"
    )
    other_view = service.list_personal_memory_candidates(
        team_id, agent_id="agent_a", theme="cc-neural-mechanism-001"
    )
    assert source_view["candidateCount"] == 1
    assert target_view["candidateCount"] == 1
    assert other_view["candidateCount"] == 1

    with pytest.raises(service.PersonalMemoryCandidateNotFoundError):
        service.get_personal_memory_candidate(
            team_id,
            second["memoryCandidateId"],
            agent_id="agent/a",
        )


def test_unaccepted_memory_never_injects_and_cross_theme_gate_survives_acceptance(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    candidate = service.record_personal_memory_candidates(
        team_id,
        scope_payload=_scope(),
        target_scope_payload=_scope(
            theme="cc-neural-mechanism-001",
            campaign="cc-campaign-neural-mechanism-001",
        ),
        agents=["agent-alpha"],
        source_refs=["meeting_digest:digest-2"],
        summaries={"agent-alpha": "Cross-theme note that must be revalidated."},
    )["candidates"][0]

    with pytest.raises(service.PersonalMemoryCandidateNotAcceptedError):
        service.inject_personal_memory_candidate(
            team_id,
            candidate["memoryCandidateId"],
            agent_id="agent-alpha",
            injected_by="agent-alpha",
        )

    accepted = service.accept_personal_memory_candidate(
        team_id,
        candidate["memoryCandidateId"],
        agent_id="agent-alpha",
        accepted_by="agent-alpha",
    )["candidate"]
    injected = service.inject_personal_memory_candidate(
        team_id,
        candidate["memoryCandidateId"],
        agent_id="agent-alpha",
        injected_by="agent-alpha",
    )["candidate"]

    assert accepted["advisoryOnly"] is True
    assert accepted["needsRevalidation"] is True
    assert injected["accepted"] is True
    assert injected["injected"] is True


def test_private_memory_access_requires_an_agent_identity(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    with pytest.raises(service.PersonalMemoryCandidateError, match="Agent id"):
        service.list_personal_memory_candidates(team_id, agent_id="")
