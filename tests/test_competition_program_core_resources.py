from __future__ import annotations

from copy import deepcopy

import pytest

from core.research.competition.resources import (
    CATALOG_SHA256,
    CORE_BEHAVIOR_HASH,
    CORE_POLICY_HASH,
    CompetitionResourceError,
    load_competition_program_core,
    load_full_catalog_execution_core,
    load_legacy_representative_cases,
    load_science_question_catalog,
    validate_competition_program_core,
    validate_full_catalog_execution_core,
    validate_question_catalog,
)


def test_tracked_competition_resources_match_the_frozen_contract() -> None:
    program = load_competition_program_core()
    policy = load_full_catalog_execution_core()
    catalog = load_science_question_catalog()
    cases = load_legacy_representative_cases()

    assert program["contractVersion"] == "2.3.0"
    assert program["freezeLayers"]["programCore"]["coreBehaviorHash"] == CORE_BEHAVIOR_HASH
    assert program["program"]["directionExecutionMode"] == "a_then_b"
    assert program["program"]["dimensions"] == [
        "A. 科学假设生成与研究计划设计",
        "B. 科学实验任务规划与反馈迭代",
    ]
    phases = program["executionPhases"]
    assert phases["mode"] == "a_then_b" and phases["activePhase"] == 1
    assert [item["phase"] for item in phases["phases"]] == [1, 2]
    assert phases["phases"][0]["completionRule"] == "full_catalog_result_set_approved"
    assert phases["phases"][1]["activationGate"] == "full_catalog_result_set_approved"
    assert [item["questionId"] for item in program["requiredDeepExperiments"]] == ["SCI-091", "SCI-096"]
    assert all(
        item["executionPhase"] == 2 and item["activationGate"] == "full_catalog_result_set_approved"
        for item in program["requiredDeepExperiments"]
    )
    assert program["completionContract"]["programRule"] == (
        "full_catalog_result_set_approved AND all_required_deep_experiments_approved"
    )
    assert program["completionContract"]["phaseCompletionRules"]["phase1"] == "full_catalog_result_set_approved"
    assert policy["version"] == "1.2.0"
    assert policy["freezeLayers"]["programAndQuestionCore"]["corePolicyHash"] == CORE_POLICY_HASH
    assert policy["catalog"]["sha256"] == CATALOG_SHA256
    assert len(catalog["questions"]) == 125
    assert [item["id"] for item in catalog["questions"]] == [f"SCI-{index:03d}" for index in range(1, 126)]
    assert cases["registryKind"] == "challenge_program_representative_cases"


def test_program_core_rejects_phase_semantics_drift() -> None:
    program = load_competition_program_core()

    def _reject(mutate) -> None:
        candidate = deepcopy(program)
        mutate(candidate)
        with pytest.raises(CompetitionResourceError):
            validate_competition_program_core(candidate)

    # Dropping the declared deep experiments (A-only) is not a valid 2.3.0 core.
    _reject(lambda value: value.update({"requiredDeepExperiments": []}))
    # Phase-2 experiments must stay gated behind the full catalog result set.
    _reject(
        lambda value: value["requiredDeepExperiments"][0].update({"executionPhase": 1})
    )
    _reject(
        lambda value: value["requiredDeepExperiments"][1].update(
            {"activationGate": "manual_activation"}
        )
    )
    # Phase-1 completion must stay exactly the full catalog result set.
    _reject(
        lambda value: value["executionPhases"]["phases"][0].update(
            {"completionRule": "half_catalog_approved"}
        )
    )
    # The final program rule still requires both directions.
    _reject(
        lambda value: value["completionContract"].update(
            {"programRule": "full_catalog_result_set_approved"}
        )
    )


def test_question_catalog_fails_closed_for_124_126_and_duplicate_entries() -> None:
    catalog = load_science_question_catalog()

    for invalid in (catalog["questions"][:-1], [*catalog["questions"], deepcopy(catalog["questions"][-1])]):
        candidate = deepcopy(catalog)
        candidate["questions"] = invalid
        candidate["question_count"] = len(invalid)
        with pytest.raises(CompetitionResourceError):
            validate_question_catalog(candidate)

    duplicate = deepcopy(catalog)
    duplicate["questions"][-1]["id"] = duplicate["questions"][-2]["id"]
    with pytest.raises(CompetitionResourceError):
        validate_question_catalog(duplicate)


def test_program_and_policy_hash_drift_fail_closed() -> None:
    program = load_competition_program_core()
    program["freezeLayers"]["programCore"]["coreBehaviorHash"] = "0" * 64
    with pytest.raises(CompetitionResourceError):
        validate_competition_program_core(program)

    policy = load_full_catalog_execution_core()
    policy["freezeLayers"]["programAndQuestionCore"]["corePolicyHash"] = "0" * 64
    with pytest.raises(CompetitionResourceError):
        validate_full_catalog_execution_core(policy)
