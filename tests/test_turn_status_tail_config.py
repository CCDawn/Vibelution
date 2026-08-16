"""Turn Status Bar session-level tail composition."""

from __future__ import annotations

from core.orchestration.turn_status_bar import (
    TURN_STATUS_BAR_HEADER,
    build_turn_status_bar_message,
    collect_turn_status_snapshot,
    format_turn_status_bar,
    is_turn_status_bar_message,
    upsert_turn_status_bar_message,
)
from core.orchestration.turn_status_tail_config import (
    BLOCK_BUDGET,
    BLOCK_CLOCK,
    BLOCK_GIT_BRIEF,
    BLOCK_GIT_PATHS,
    block_enabled,
    default_turn_status_tail_config,
    normalize_turn_status_tail_config,
)
from langchain_core.messages import HumanMessage, SystemMessage


def test_default_lean_blocks():
    cfg = default_turn_status_tail_config()
    assert cfg["enabled"] is True
    assert cfg["blocks"][BLOCK_BUDGET] is True
    assert cfg["blocks"][BLOCK_CLOCK] is True
    assert cfg["blocks"][BLOCK_GIT_BRIEF] is False
    assert cfg["blocks"][BLOCK_GIT_PATHS] is False
    assert cfg["limits"]["gitPathsMax"] == 12
    assert cfg["limits"]["maxTailChars"] == 2500


def test_normalize_clamps_limits_and_bools():
    cfg = normalize_turn_status_tail_config(
        {
            "enabled": "on",
            "blocks": {"git_brief": True, "budget": 0},
            "limits": {"gitPathsMax": 999, "maxTailChars": 10},
        }
    )
    assert cfg["enabled"] is True
    assert cfg["blocks"]["git_brief"] is True
    assert cfg["blocks"]["budget"] is False
    assert cfg["limits"]["gitPathsMax"] == 40
    assert cfg["limits"]["maxTailChars"] == 400


def test_normalize_accepts_bytes_false_and_json_payload():
    cfg = normalize_turn_status_tail_config({"enabled": b"false"})
    assert cfg["enabled"] is False
    cfg = normalize_turn_status_tail_config(
        '{"enabled": false, "blocks": {"git_brief": true}, "limits": {"gitPathsMax": "8"}}'
    )
    assert cfg["enabled"] is False
    assert cfg["blocks"]["git_brief"] is True
    assert cfg["limits"]["gitPathsMax"] == 8
    assert block_enabled({"enabled": True, "blocks": {"git_brief": True}}, b"git_brief") is True
    assert block_enabled({"enabled": "off"}, "budget") is False



def test_format_default_includes_budget_and_clock_not_git():
    snapshot = collect_turn_status_snapshot(
        iteration=1,
        model="deepseek-chat",
        tool_policy={"maxCallsPerTurn": 16},
    )
    text = format_turn_status_bar(snapshot)
    assert text.startswith(TURN_STATUS_BAR_HEADER)
    assert "### budget" in text
    assert "### clock" in text
    assert "### git_brief" not in text
    assert "placement: tail-only" in text


def test_format_git_sections_when_enabled():
    snapshot = collect_turn_status_snapshot(iteration=2, model="deepseek-chat")
    cfg = normalize_turn_status_tail_config(
        {
            "blocks": {
                "budget": True,
                "clock": False,
                "git_brief": True,
                "git_paths": True,
            },
            "limits": {"gitPathsMax": 2},
        }
    )
    extras = {
        "git": {
            "available": True,
            "branch": "feat/x",
            "dirty": True,
            "headRevShort": "abc1234",
            "summary": "3 files dirty",
            "upstream": {"ahead": 1, "behind": 0},
            "files": [
                {"path": "a.py", "status": "M"},
                {"path": "b.py", "status": "A"},
                {"path": "c.py", "status": "D"},
            ],
            "totalFiles": 3,
        }
    }
    text = format_turn_status_bar(snapshot, config=cfg, extras=extras)
    assert "### git_brief" in text
    assert "branch: feat/x" in text
    assert "### git_paths" in text
    assert "- M a.py" in text
    assert "- A b.py" in text
    assert "c.py" not in text  # capped at 2
    assert "truncated: showing 2/3" in text
    assert "### clock" not in text


def test_max_tail_chars_truncates():
    snapshot = collect_turn_status_snapshot(iteration=1, model="x")
    cfg = normalize_turn_status_tail_config(
        {
            "blocks": {"budget": True, "clock": True, "identity": True},
            "limits": {"maxTailChars": 400},
        }
    )
    extras = {
        "identity": {
            "sessionId": "session-" + ("z" * 80),
            "agentId": "agent-" + ("a" * 40),
            "worktree": "/tmp/" + ("w" * 200),
        }
    }
    text = format_turn_status_bar(snapshot, config=cfg, extras=extras)
    assert len(text) <= 400 + 5
    assert "truncated: maxTailChars reached" in text


def test_upsert_still_appends_tail_with_sections():
    snapshot = collect_turn_status_snapshot(iteration=1, model="deepseek-chat")
    bar = build_turn_status_bar_message(
        snapshot,
        config=normalize_turn_status_tail_config({"blocks": {"budget": True, "clock": True}}),
    )
    messages = [SystemMessage(content="stable"), HumanMessage(content="hi")]
    updated = upsert_turn_status_bar_message(messages, bar)
    assert is_turn_status_bar_message(updated[-1])
    assert not is_turn_status_bar_message(updated[0])
    assert updated[1].content == "hi"
