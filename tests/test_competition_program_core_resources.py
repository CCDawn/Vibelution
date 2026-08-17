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

    assert program["contractVersion"] == "2.2.0"
    assert program["freezeLayers"]["programCore"]["coreBehaviorHash"] == CORE_BEHAVIOR_HASH
    assert policy["version"] == "1.2.0"
    assert policy["freezeLayers"]["programAndQuestionCore"]["corePolicyHash"] == CORE_POLICY_HASH
    assert policy["catalog"]["sha256"] == CATALOG_SHA256
    assert len(catalog["questions"]) == 125
    assert [item["id"] for item in catalog["questions"]] == [f"SCI-{index:03d}" for index in range(1, 126)]
    assert cases["registryKind"] == "challenge_program_representative_cases"


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
