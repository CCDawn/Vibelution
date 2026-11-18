# -*- coding: utf-8 -*-
"""Extra tool policy package merge: additive union with blocked names winning."""

from __future__ import annotations

import pytest

from core.web.services.agent_directory import policies


class _StubLogger:
    def warning(self, *args, **kwargs):  # noqa: D102 - test double
        return None


class _StubFacade:
    """Minimal facade surface used by ``_with_extra_tool_policies``."""

    _debug_logger = _StubLogger()

    def __init__(self, catalog):
        self._catalog = catalog

    def _tool_name_list(self, values):
        return [str(item) for item in list(values or []) if str(item or "").strip()]

    def load_state(self):
        return {"toolPolicies": self._catalog}

    def _tool_policies(self, state):
        return dict(state["toolPolicies"])


@pytest.fixture
def facade(monkeypatch):
    catalog = {
        "tool-base": {"allowedTools": ["read_file_tool"], "blockedTools": []},
        "tool-extra": {
            "allowedTools": ["write_file_tool", "grep_search_tool"],
            "blockedTools": [],
        },
        "tool-extra-blocked": {
            "allowedTools": ["write_file_tool", "danger_tool"],
            "blockedTools": ["danger_tool"],
        },
    }
    stub = _StubFacade(catalog)

    def _service():
        return stub

    monkeypatch.setattr(policies, "_service", _service)
    return stub


def test_empty_extra_ids_returns_same_policy(facade):
    policy = {"allowedTools": ["read_file_tool"], "blockedTools": []}
    assert policies._with_extra_tool_policies(policy, []) is policy
    assert policies._with_extra_tool_policies(policy, None) is policy


def test_empty_base_allow_list_stays_empty(facade):
    policy = {"allowedTools": [], "blockedTools": []}
    assert policies._with_extra_tool_policies(policy, ["tool-extra"]) is policy


def test_extra_package_union_and_record(facade):
    policy = {"allowedTools": ["read_file_tool"], "blockedTools": []}
    merged = policies._with_extra_tool_policies(policy, ["tool-extra"])
    assert merged["allowedTools"] == [
        "read_file_tool",
        "write_file_tool",
        "grep_search_tool",
    ]
    assert merged["temporaryAllowedTools"] == ["write_file_tool", "grep_search_tool"]
    # The persisted policy copy passed in stays untouched.
    assert policy["allowedTools"] == ["read_file_tool"]


def test_extra_blocked_tool_never_added(facade):
    policy = {"allowedTools": ["read_file_tool"], "blockedTools": []}
    merged = policies._with_extra_tool_policies(policy, ["tool-extra-blocked"])
    assert merged["allowedTools"] == ["read_file_tool", "write_file_tool"]
    assert "danger_tool" not in merged["allowedTools"]


def test_base_blocked_still_wins(facade):
    policy = {"allowedTools": ["read_file_tool"], "blockedTools": ["write_file_tool"]}
    merged = policies._with_extra_tool_policies(policy, ["tool-extra"])
    assert merged["allowedTools"] == ["read_file_tool", "grep_search_tool"]


def test_base_grant_survives_extra_block(facade):
    policy = {"allowedTools": ["read_file_tool", "write_file_tool"], "blockedTools": []}
    merged = policies._with_extra_tool_policies(policy, ["tool-extra-blocked"])
    # Additive only: an extra package may not silently remove a base grant.
    assert "write_file_tool" in merged["allowedTools"]
    assert "danger_tool" not in merged["allowedTools"]


def test_unknown_policy_id_is_ignored(facade):
    policy = {"allowedTools": ["read_file_tool"], "blockedTools": []}
    assert policies._with_extra_tool_policies(policy, ["tool-missing"]) is policy


def test_duplicate_tools_are_not_repeated(facade):
    policy = {"allowedTools": ["read_file_tool", "write_file_tool"], "blockedTools": []}
    merged = policies._with_extra_tool_policies(policy, ["tool-extra"])
    assert merged["allowedTools"] == [
        "read_file_tool",
        "write_file_tool",
        "grep_search_tool",
    ]
    assert merged["temporaryAllowedTools"] == ["grep_search_tool"]
