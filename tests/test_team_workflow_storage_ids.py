from __future__ import annotations

import pytest

from core.web.services.team_workflow import challenge_question_runs
from core.web.services.team_workflow.storage_ids import (
    safe_storage_component,
    validate_artifact_component,
)

EVIL_RUN_ID = ".." + chr(92) + ".." + chr(92) + ".." + chr(92) + "config" + chr(92) + "evil"


def test_safe_storage_component_blocks_dot_components() -> None:
    assert safe_storage_component("..", fallback="team") == "_"
    assert safe_storage_component(".", fallback="team") == "_"
    assert safe_storage_component("...hidden", fallback="team") == "_hidden"
    assert safe_storage_component("a/../../b", fallback="team") == "a_.._.._b"
    assert safe_storage_component("research-team", fallback="team") == "research-team"
    assert safe_storage_component("", fallback="team") == "team"


def test_validate_artifact_component_rejects_path_shapes() -> None:
    assert validate_artifact_component("run-0bce801238e1", field="run_id") == "run-0bce801238e1"
    assert validate_artifact_component("SCI-001", field="question_id") == "SCI-001"
    for evil in (
        EVIL_RUN_ID,
        "../../etc/passwd",
        "..",
        "a/b",
        "a" + chr(92) + "b",
        "",
        "x" * 65,
        "run id with spaces",
    ):
        with pytest.raises(ValueError, match="must match"):
            validate_artifact_component(evil, field="run_id")


def test_register_output_rejects_path_shaped_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "output": {
            "schema_version": 2,
            "identity": {"question_id": "SCI-001"},
            "run": {"run_id": EVIL_RUN_ID},
        },
    }
    monkeypatch.setattr(
        challenge_question_runs.team_service,
        "get_team",
        lambda _team_id: {"teamId": "research-team"},
    )
    with pytest.raises(ValueError, match="output.run.run_id"):
        challenge_question_runs.register_challenge_question_output("research-team", payload)

    payload["output"]["run"]["run_id"] = "run-ok"
    payload["output"]["identity"]["question_id"] = "../../escape"
    with pytest.raises(ValueError, match="output.identity.question_id"):
        challenge_question_runs.register_challenge_question_output("research-team", payload)


def test_get_api_requires_control_token_except_exemptions() -> None:
    from fastapi.testclient import TestClient

    from core.web.app import create_app
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

    client = TestClient(create_app())
    # Bootstrap endpoints stay open.
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/control-token").status_code == 200
    # Any other guarded GET without a token is refused…
    unguarded = client.get("/api/agents")
    assert unguarded.status_code == 403
    assert "control token" in unguarded.json()["detail"].lower()
    # …and passes with the token.
    authorized = TestClient(
        create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()}
    )
    assert authorized.get("/api/agents").status_code != 403


def test_evidence_request_marker_size_is_bounded() -> None:
    from core.web.services.team_workflow.meeting_rounds import extract_discussion_markers

    huge = "EVIDENCE_REQUEST: " + '{"pad": "' + "x" * 70000 + '"}'
    extracted = extract_discussion_markers([{"content": huge, "status": "completed"}])
    assert extracted["evidenceRequests"] == []
    assert extracted["evidenceRequestErrors"]
    assert extracted["evidenceRequestErrors"][0]["code"] == "evidence_request_too_large"
