import json

from tools.personal_assistant_rescue_tools import (
    personal_assistant_git_tool,
    personal_assistant_startup_diagnosis_tool,
)


def _payload(raw: str) -> dict:
    return json.loads(raw)


def test_git_status_and_log_are_structured() -> None:
    status = _payload(personal_assistant_git_tool("status"))
    assert status["ok"] is True
    assert status["action"] == "status"
    assert "## " in status["stdout"]

    log = _payload(personal_assistant_git_tool("log", '{"limit": 2}'))
    assert log["ok"] is True
    assert log["action"] == "log"
    assert log["stdout"].strip()


def test_git_forbidden_and_invalid_actions_are_blocked() -> None:
    assert _payload(personal_assistant_git_tool("push"))["status"] == "blocked"
    assert (
        _payload(
            personal_assistant_git_tool("reset_to_commit", '{"mode": "hard"}')
        )["status"]
        == "blocked"
    )
    assert _payload(personal_assistant_git_tool("commit", "{}"))["status"] == "blocked"
    assert _payload(personal_assistant_git_tool("show", "{}"))["status"] == "blocked"
    assert (
        _payload(personal_assistant_git_tool("commit", "not-json"))["status"]
        == "blocked"
    )


def test_git_paths_must_stay_inside_checkout() -> None:
    outside = _payload(
        personal_assistant_git_tool("checkout_path", '{"paths": ["../outside"]}')
    )
    assert outside["status"] == "blocked"

    git_dir = _payload(
        personal_assistant_git_tool("checkout_path", '{"paths": [".git/config"]}')
    )
    assert git_dir["status"] == "blocked"


def test_startup_diagnosis_is_bounded_json() -> None:
    payload = _payload(personal_assistant_startup_diagnosis_tool(1))
    assert "ok" in payload
    if payload["ok"]:
        assert payload["status"] == "ready"
        assert "git" in payload
        assert "launcher" in payload
        assert "frontendBuild" in payload
        assert "agentLog" in payload
        assert len(json.dumps(payload, ensure_ascii=False)) < 12000
    else:
        assert payload["code"] == "DIAGNOSIS_UNAVAILABLE"
