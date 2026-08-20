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
