from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.web.services.session.worker import (
    _research_task_structured_output_contract,
)
from core.web.services.team_workflow import research_project_agent_tasks


def _context() -> dict:
    return {
        "message_metadata": {
            "kind": "research_project_agent_task",
            "taskId": "task-1",
            "teamId": "team-1",
            "researchProjectId": "project-1",
            "taskKind": "hypothesis_design",
        }
    }


def _task() -> dict:
    return {
        "taskId": "task-1",
        "taskKind": "hypothesis_design",
        "researchProjectId": "project-1",
        "sessionId": "session-1",
        "turn": {"turnId": "turn-1"},
    }


def test_formal_research_task_binds_server_owned_strict_output(monkeypatch):
    monkeypatch.setattr(
        research_project_agent_tasks,
        "_read_research_project_agent_task_record",
        lambda *_args: _task(),
    )

    contract = _research_task_structured_output_contract(
        _context(),
        session_id="session-1",
        turn_id="turn-1",
    )

    assert contract.name == "research_hypothesis_design_v1"
    assert contract.strict is True
    contract.validator(
        {
            "schemaVersion": 1,
            "taskKind": "hypothesis_design",
            "status": "needs_more_evidence",
            "reasoning": "Evidence is incomplete.",
            "evidenceRefs": [],
            "maxEvolutionRounds": 3,
            "currentEvolutionRound": 1,
            "candidates": [],
        }
    )
    with pytest.raises(ValidationError):
        contract.validator({"taskKind": "hypothesis_design"})


def test_formal_research_task_fails_closed_for_unbound_session(monkeypatch):
    monkeypatch.setattr(
        research_project_agent_tasks,
        "_read_research_project_agent_task_record",
        lambda *_args: _task(),
    )

    with pytest.raises(RuntimeError, match="does not match"):
        _research_task_structured_output_contract(
            _context(),
            session_id="session-other",
            turn_id="turn-1",
        )
