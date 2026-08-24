"""Static/fake-port checks for the read-only Challenge Cup inventory adapter.

These tests never bind the default live ports and never touch the operator data
home.  The parent task owns the final focused test run.
"""

from __future__ import annotations

import json
from typing import Any

from core.web.services.team_workflow.challenge_cup_reset_live_adapter import (
    ChallengeCupInventoryPorts,
    LiveChallengeCupInventoryReader,
)
from core.web.services.team_workflow.challenge_cup_reset_service import (
    RETAINED_AGENT_ROLE_KEYS,
    ChallengeCupResetService,
)


def _ports(*, missing_checkpoints: bool = False) -> ChallengeCupInventoryPorts:
    agents = [
        {
            "agentId": f"agent-{role}",
            "teamId": "research-team",
            "roleKey": role,
            "prompt": "must never cross the adapter boundary",
        }
        for role in RETAINED_AGENT_ROLE_KEYS
    ]
    teams = {
        "teams": [
            {
                "teamId": "research-team",
                "members": [{"agentId": item["agentId"]} for item in agents],
            },
            {"teamId": "other-team", "members": []},
        ]
    }

    def list_sessions() -> list[dict[str, Any]]:
        return [
            {
                "id": "legacy-session",
                "sessionId": "legacy-session",
                "teamId": "research-team",
                "agentId": agents[0]["agentId"],
                "sessionKind": "child",
                "transcript": "must never cross the adapter boundary",
            },
            {"id": "other-session", "teamId": "other-team", "status": "idle"},
        ]

    def list_rooms() -> list[dict[str, Any]]:
        return [
            {
                "roomId": "legacy-room",
                "config": {"teamId": "research-team"},
                "status": "idle",
                "participants": [
                    {
                        "participantId": "participant-1",
                        "agentId": agents[0]["agentId"],
                        "sessionId": "legacy-session",
                    }
                ],
                "rounds": [{"roundId": "legacy-round", "status": "closed", "messages": ["secret"]}],
            },
            {
                "roomId": "other-room",
                "config": {"teamId": "other-team"},
                "status": "idle",
                "participants": [],
                "rounds": [],
            },
        ]

    def list_artifacts(team_id: str, kind: str) -> list[dict[str, Any]]:
        if team_id == "research-team" and kind == "research_plan":
            return [{"recordId": "legacy-plan", "teamId": team_id, "payload": {"prompt": "secret"}}]
        return []

    return ChallengeCupInventoryPorts(
        list_teams=lambda: teams,
        list_agents=lambda: agents,
        list_sessions=list_sessions,
        list_rooms=list_rooms,
        list_meeting_rounds=lambda team_id: {"meetings": []},
        list_workflow_runs=lambda team_id: {"runs": []},
        list_artifacts=list_artifacts,
        list_checkpoints=None if missing_checkpoints else (lambda team_id: []),
        list_receipts=lambda team_id: [],
        list_active_session_work=lambda: [],
        load_catalog=lambda: {"catalog_id": "science-125-questions-2021", "question_count": 125, "sha256": "catalog-hash"},
        load_program=lambda: {"contractVersion": "2.2.0", "coreBehaviorHash": "program-hash"},
        load_policy=lambda: {"version": "1.2.0", "corePolicyHash": "policy-hash"},
    )


def test_live_adapter_returns_bounded_identity_only_and_preview_can_consume_it() -> None:
    reader = LiveChallengeCupInventoryReader(_ports())

    inventory = reader.read_inventory("research-team")
    encoded = json.dumps(inventory, ensure_ascii=False)

    assert "prompt" not in encoded
    assert "transcript" not in encoded
    assert "messages" not in encoded
    assert inventory["activeWork"] == {
        "authorityPresent": True,
        "activeCount": 0,
        "items": [],
        "statuses": {},
    }
    assert inventory["otherTeamProtection"]["authorityPresent"] is True
    assert any(item["id"] == "legacy-plan" for item in inventory["objects"]["plans"])
    assert any(item["id"] == "legacy-room:participant-1" for item in inventory["objects"]["legacyParticipantBindings"])

    preview = ChallengeCupResetService(inventory_reader=reader).preview().to_dict()
    assert preview["safeToConfirm"] is True
    assert preview["deleteSet"]["sessions"] == ["legacy-session"]
    assert preview["deleteSet"]["rooms"] == ["legacy-room"]


def test_active_work_is_derived_from_managed_snapshots() -> None:
    ports = _ports()
    ports = ChallengeCupInventoryPorts(
        **{
            **ports.__dict__,
            "list_active_session_work": lambda: [
                {"runId": "turn-1", "sessionId": "legacy-session", "runKind": "chat_turn", "status": "running"}
            ],
        }
    )
    reader = LiveChallengeCupInventoryReader(ports)

    active = reader.read_inventory("research-team")["activeWork"]

    assert active["authorityPresent"] is True
    assert active["activeCount"] == 1
    assert active["items"] == [{"id": "turn-1", "kind": "chat_turn", "status": "running"}]


def test_unrelated_unscoped_sessions_are_protected_outside_reset_inventory() -> None:
    ports = _ports()
    original_list_sessions = ports.list_sessions

    def list_sessions() -> list[dict[str, Any]]:
        return [
            *list(original_list_sessions()),
            {
                "id": "personal-session",
                "agentId": "agent-not-in-any-team",
                "status": "idle",
            },
        ]

    reader = LiveChallengeCupInventoryReader(
        ChallengeCupInventoryPorts(**{**ports.__dict__, "list_sessions": list_sessions})
    )

    preview = ChallengeCupResetService(inventory_reader=reader).preview().to_dict()

    assert preview["safeToConfirm"] is True
    assert preview["deleteSet"]["sessions"] == ["legacy-session"]
    assert all(item.get("id") != "personal-session" for item in reader.read_inventory("research-team")["objects"]["sessions"])


def test_missing_checkpoint_authority_is_fail_closed_without_sqlite_scan() -> None:
    reader = LiveChallengeCupInventoryReader(_ports(missing_checkpoints=True))

    inventory = reader.read_inventory("research-team")
    authority = reader.read_authority()
    preview = ChallengeCupResetService(inventory_reader=reader).preview().to_dict()

    assert inventory["objects"]["checkpoints"][0]["id"] == ""
    assert authority["families"]["checkpoints"] is False
    assert preview["safeToConfirm"] is False
    assert any(item["code"] == "object_id_missing" for item in preview["blockers"])
