from __future__ import annotations

import copy

import pytest

from core.web.services.agent_perception.policy import (
    AgentPerceptionPolicyError,
    agent_perception_policy_fingerprint,
    decide_agent_perception,
    default_agent_perception_policy,
    normalize_agent_perception_policy,
)


def _enabled_policy(source: str, *, mode: str = "auto") -> dict:
    policy = default_agent_perception_policy()
    policy["enabled"] = True
    policy["sources"][source]["mode"] = mode
    return policy


def test_unconfigured_policy_preserves_legacy_behavior_but_explicit_off_closes_gate():
    unconfigured = decide_agent_perception(
        None,
        source="personal",
        trigger="task",
        requested_by_user=True,
    )
    assert unconfigured == {
        "enforced": False,
        "allowed": None,
        "reason": "policy_not_configured",
        "source": "personal",
        "trigger": "task",
        "mode": None,
        "scope": None,
    }

    explicit_default = decide_agent_perception(
        default_agent_perception_policy(),
        source="personal",
        trigger="task",
        requested_by_user=True,
    )
    assert explicit_default["enforced"] is True
    assert explicit_default["allowed"] is False
    assert explicit_default["reason"] == "perception_disabled"


def test_normalization_sorts_deduplicates_and_fingerprints_equivalent_selections():
    left = _enabled_policy("team")
    left["sources"]["team"].update(
        {"mode": "auto", "teamIds": ["team-b", "team-a", "team-b"]}
    )
    right = copy.deepcopy(left)
    right["sources"]["team"]["teamIds"] = ["team-a", "team-b"]

    normalized = normalize_agent_perception_policy(left)
    assert normalized["sources"]["team"]["teamIds"] == ["team-a", "team-b"]
    assert agent_perception_policy_fingerprint(left) == agent_perception_policy_fingerprint(right)

    normalized["sources"]["team"]["teamIds"].append("team-c")
    assert normalize_agent_perception_policy(left)["sources"]["team"]["teamIds"] == [
        "team-a",
        "team-b",
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"unexpected": True}),
        lambda value: value.update({"schemaVersion": 2}),
        lambda value: value.update({"enabled": 1}),
        lambda value: value["sources"]["personal"].update({"mode": "AUTO"}),
        lambda value: value["sources"]["personal"]["triggers"].update({"task": "yes"}),
        lambda value: value["sources"]["team"].update({"teamIds": ["team/other"]}),
        lambda value: value["sources"]["knowledge"].update({"all": True}),
    ],
)
def test_normalization_rejects_unknown_or_malformed_policy_values(mutate):
    policy = default_agent_perception_policy()
    mutate(policy)

    with pytest.raises(AgentPerceptionPolicyError):
        normalize_agent_perception_policy(policy)


def test_knowledge_scope_is_explicit_and_all_authorized_cannot_mix_selected_ids():
    policy = _enabled_policy("knowledge")
    knowledge = policy["sources"]["knowledge"]
    knowledge.update(
        {
            "mode": "auto",
            "scope": "all_authorized",
            "knowledgeBaseIds": ["team:team-a:kb-one"],
        }
    )

    with pytest.raises(AgentPerceptionPolicyError, match="must be empty"):
        normalize_agent_perception_policy(policy)


@pytest.mark.parametrize(
    ("scope", "field", "ids"),
    [
        ("selected", "knowledgeBaseIds", ["kb-one"]),
        ("all_authorized", "excludedKnowledgeBaseIds", ["kb-secret"]),
        ("selected", "knowledgeBaseIds", ["user:user-a:kb-one"]),
        ("selected", "knowledgeBaseIds", ["team:team:a:kb-one"]),
    ],
)
def test_knowledge_selections_and_exclusions_require_owner_scoped_ids(scope, field, ids):
    policy = _enabled_policy("knowledge")
    knowledge = policy["sources"]["knowledge"]
    knowledge["scope"] = scope
    knowledge[field] = ids

    with pytest.raises(AgentPerceptionPolicyError, match="owner-scoped"):
        normalize_agent_perception_policy(policy)


def test_background_schedule_and_topic_limits_are_strict_and_bounded():
    policy = default_agent_perception_policy()
    policy["background"].update(
        {
            "enabled": True,
            "intervalMinutes": 15,
            "dailyMaxRuns": 96,
            "maxCallsPerRun": 32,
            "maxInputTokensPerRun": 131_072,
            "maxConcurrent": 1,
            "maxResultChars": 50_000,
            "topics": ["  quarterly\tSEC\n filing ", "quarterly SEC filing"],
        }
    )

    normalized = normalize_agent_perception_policy(policy)
    assert normalized["background"]["topics"] == ["quarterly SEC filing"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("intervalMinutes", 14),
        ("intervalMinutes", 10_081),
        ("dailyMaxRuns", 97),
        ("maxCallsPerRun", 33),
        ("maxInputTokensPerRun", 131_073),
        ("maxConcurrent", 2),
        ("maxResultChars", 50_001),
        ("maxCallsPerRun", True),
    ],
)
def test_background_budgets_reject_values_outside_their_bounds(field, value):
    policy = default_agent_perception_policy()
    policy["background"][field] = value

    with pytest.raises(AgentPerceptionPolicyError):
        normalize_agent_perception_policy(policy)


def test_background_requires_a_bounded_user_topic_and_rejects_controls():
    policy = default_agent_perception_policy()
    policy["background"].update({"enabled": True, "topics": []})
    with pytest.raises(AgentPerceptionPolicyError, match="topic"):
        normalize_agent_perception_policy(policy)

    policy["background"].update({"enabled": False, "topics": ["bad\u0000topic"]})
    with pytest.raises(AgentPerceptionPolicyError, match="control"):
        normalize_agent_perception_policy(policy)

    policy["background"]["topics"] = ["x" * 201]
    with pytest.raises(AgentPerceptionPolicyError, match="200 characters"):
        normalize_agent_perception_policy(policy)

    policy["background"]["topics"] = [f"topic-{index}" for index in range(9)]
    with pytest.raises(AgentPerceptionPolicyError, match="at most 8"):
        normalize_agent_perception_policy(policy)


def test_auto_sources_need_enabled_triggers_but_keep_direct_user_queries_available():
    policy = _enabled_policy("personal")
    policy["sources"]["personal"]["mode"] = "auto"

    automatic = decide_agent_perception(
        policy,
        source="personal",
        trigger="task",
        requested_by_user=False,
    )
    assert automatic["allowed"] is False
    assert automatic["reason"] == "trigger_disabled"

    explicit = decide_agent_perception(
        policy,
        source="personal",
        trigger="task",
        requested_by_user=True,
    )
    assert explicit["allowed"] is True
    assert explicit["scope"] == {"kind": "personal"}


def test_manual_mode_requires_a_user_task_request_and_never_starts_background_work():
    policy = _enabled_policy("projects", mode="manual")

    implicit = decide_agent_perception(
        policy,
        source="projects",
        trigger="task",
        requested_by_user=False,
    )
    assert implicit["reason"] == "user_request_required"

    direct = decide_agent_perception(
        policy,
        source="projects",
        trigger="task",
        requested_by_user=True,
    )
    assert direct["allowed"] is True
    assert direct["scope"] == {"kind": "project_index"}

    background = decide_agent_perception(
        policy,
        source="projects",
        trigger="background",
        requested_by_user=True,
    )
    assert background["allowed"] is False
    assert background["reason"] == "manual_only"


def test_team_scope_denies_empty_selection_and_agent_cannot_expand_it():
    empty = _enabled_policy("team")
    empty["sources"]["team"]["mode"] = "auto"
    empty["sources"]["team"]["triggers"]["task"] = True
    denied = decide_agent_perception(empty, source="team", trigger="task")
    assert denied["reason"] == "empty_scope"

    policy = _enabled_policy("team")
    policy["sources"]["team"].update(
        {"mode": "auto", "teamIds": ["team-a", "team-b"]}
    )
    policy["sources"]["team"]["triggers"]["task"] = True

    subset = decide_agent_perception(
        policy,
        source="team",
        trigger="task",
        requested_scope_ids=["team-b"],
    )
    assert subset["allowed"] is True
    assert subset["scope"] == {"kind": "selected", "ids": ["team-b"]}

    expanded = decide_agent_perception(
        policy,
        source="team",
        trigger="task",
        requested_scope_ids=["team-other"],
    )
    assert expanded["allowed"] is False
    assert expanded["reason"] == "scope_outside_policy"


def test_selected_knowledge_scope_applies_exclusions_and_blocks_scope_expansion():
    policy = _enabled_policy("knowledge")
    policy["sources"]["knowledge"].update(
        {
            "mode": "auto",
            "scope": "selected",
            "knowledgeBaseIds": [
                "team:team-a:kb-a",
                "team:team-a:kb-b",
                "team:team-a:kb-c",
            ],
            "excludedKnowledgeBaseIds": ["team:team-a:kb-b"],
        }
    )
    policy["sources"]["knowledge"]["triggers"]["task"] = True

    full = decide_agent_perception(
        policy,
        source="knowledge",
        trigger="task",
    )
    assert full["scope"] == {
        "kind": "selected",
        "ids": ["team:team-a:kb-a", "team:team-a:kb-c"],
    }

    excluded = decide_agent_perception(
        policy,
        source="knowledge",
        trigger="task",
        requested_scope_ids=["team:team-a:kb-b"],
    )
    assert excluded["reason"] == "scope_outside_policy"


def test_all_authorized_knowledge_returns_an_acl_deferred_scope_with_exclusions():
    policy = _enabled_policy("knowledge")
    policy["sources"]["knowledge"].update(
        {
            "mode": "manual",
            "scope": "all_authorized",
            "excludedKnowledgeBaseIds": ["team:team-a:kb-secret"],
        }
    )

    all_scope = decide_agent_perception(
        policy,
        source="knowledge",
        trigger="task",
        requested_by_user=True,
    )
    assert all_scope["allowed"] is True
    assert all_scope["scope"] == {
        "kind": "all_authorized",
        "excludedIds": ["team:team-a:kb-secret"],
    }

    narrower = decide_agent_perception(
        policy,
        source="knowledge",
        trigger="task",
        requested_by_user=True,
        requested_scope_ids=["team:team-a:kb-public"],
    )
    assert narrower["scope"] == {
        "kind": "selected",
        "ids": ["team:team-a:kb-public"],
    }


def test_all_authorized_policy_rejects_raw_exclusion_instead_of_silently_ignoring_it():
    policy = _enabled_policy("knowledge")
    policy["sources"]["knowledge"].update(
        {
            "mode": "auto",
            "scope": "all_authorized",
            "excludedKnowledgeBaseIds": ["private-notes"],
        }
    )

    with pytest.raises(AgentPerceptionPolicyError, match="owner-scoped"):
        normalize_agent_perception_policy(policy)


def test_requested_knowledge_scope_must_also_be_owner_scoped():
    policy = _enabled_policy("knowledge", mode="manual")
    policy["sources"]["knowledge"]["scope"] = "all_authorized"

    with pytest.raises(AgentPerceptionPolicyError, match="owner-scoped"):
        decide_agent_perception(
            policy,
            source="knowledge",
            trigger="task",
            requested_by_user=True,
            requested_scope_ids=["kb-public"],
        )


def test_scoped_knowledge_id_limits_each_segment_instead_of_the_combined_id():
    scoped_id = f"team:{'o' * 128}:{'b' * 128}"
    assert len(scoped_id) > 128

    policy = _enabled_policy("knowledge")
    policy["sources"]["knowledge"].update(
        {"scope": "selected", "knowledgeBaseIds": [scoped_id]}
    )
    normalized = normalize_agent_perception_policy(policy)
    assert normalized["sources"]["knowledge"]["knowledgeBaseIds"] == [scoped_id]

    policy["sources"]["knowledge"].update(
        {"mode": "manual", "scope": "all_authorized", "knowledgeBaseIds": []}
    )
    requested = decide_agent_perception(
        policy,
        source="knowledge",
        trigger="task",
        requested_by_user=True,
        requested_scope_ids=[scoped_id],
    )
    assert requested["scope"] == {"kind": "selected", "ids": [scoped_id]}


def test_background_trigger_reports_disabled_and_zero_run_budget_gates():
    policy = _enabled_policy("projects")
    policy["sources"]["projects"]["triggers"]["background"] = True
    policy["sources"]["projects"]["mode"] = "auto"

    disabled = decide_agent_perception(
        policy,
        source="projects",
        trigger="background",
    )
    assert disabled["reason"] == "background_disabled"

    policy["background"].update(
        {"enabled": True, "dailyMaxRuns": 0, "topics": ["User topic"]}
    )
    no_budget = decide_agent_perception(
        policy,
        source="projects",
        trigger="background",
    )
    assert no_budget["reason"] == "daily_run_budget_zero"

    policy["background"]["dailyMaxRuns"] = 1
    allowed = decide_agent_perception(policy, source="projects", trigger="background")
    assert allowed["allowed"] is True


def test_requested_scope_arguments_are_validated_before_a_decision():
    with pytest.raises(AgentPerceptionPolicyError, match="unknown source"):
        decide_agent_perception(None, source="unknown", trigger="task")
    with pytest.raises(AgentPerceptionPolicyError, match="unknown trigger"):
        decide_agent_perception(None, source="personal", trigger="poll")
    with pytest.raises(AgentPerceptionPolicyError, match="boolean"):
        decide_agent_perception(
            None,
            source="personal",
            trigger="task",
            requested_by_user=1,
        )
    with pytest.raises(AgentPerceptionPolicyError, match="ASCII ID"):
        decide_agent_perception(
            None,
            source="team",
            trigger="task",
            requested_scope_ids=["team/one"],
        )
