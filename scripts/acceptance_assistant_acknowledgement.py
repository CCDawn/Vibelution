"""Retry only the real lost-acknowledgement scene without repeating long tests."""
from __future__ import annotations

import time

from scripts.acceptance_assistant_recovery import _run_lost_ack
from scripts.assistant_acceptance_support import AssistantAcceptanceFixture


def run_case(fixture: AssistantAcceptanceFixture, evidence: dict, timeout: float = 1200) -> None:
    fixture.start_backend()
    agent_id = fixture.create_agent("Acknowledgement acceptance ordinary target")
    fixture.start_host()
    fixture.assert_no_approvals()
    evidence["lostAcknowledgement"] = {"status": "not_tested"}
    _run_lost_ack(fixture, evidence["lostAcknowledgement"], time.monotonic() + timeout, agent_id, set())
