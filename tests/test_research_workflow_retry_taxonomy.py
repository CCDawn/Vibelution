"""R3.4 single retry owner: the frozen retry outcome taxonomy contract."""

from __future__ import annotations

from collections import Counter

import pytest

from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.retry_taxonomy import (
    DEFAULT_RETRY_TAXONOMY,
    HumanActionFamily,
    RetryChargeRule,
    RetryOutcomeClass,
    RetryOutcomeOwner,
    RetryTaxonomy,
    RetryTaxonomyEntry,
    UnknownRetryOutcomeCodeError,
)
from core.web.services.team_workflow.research_runtime.retry_policy import (
    INFRASTRUCTURE_FAILURE_CODES,
    charged_retry_count,
    retry_is_available,
    retry_kind_for,
)

# The frozen classification registry. Every default taxonomy entry must be
# listed here with its settled class and owner; adding an entry to the
# taxonomy without pinning it here (or vice versa) fails the suite.
EXPECTED_DEFAULT_CLASSIFICATION: dict[str, tuple[RetryOutcomeClass, RetryOutcomeOwner]] = {
    "external_task_interrupted": (
        RetryOutcomeClass.RETRYABLE_INFRA,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "lease_expired": (
        RetryOutcomeClass.RETRYABLE_INFRA,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "counter_evidence_missing": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "external_task_needs_review": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "external_agent_task_missing": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "external_agent_task_mismatch": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "external_agent_task_lookup_failed": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "external_agent_session_mismatch": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "external_task_completion_gate_failed": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "external_task_completion_invalid": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "task_bundle_cancelled": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "agent_turn_continuation_exhausted": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "session_needs_continue": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "source_candidates_missing": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "evidence_graph_incomplete": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "auto_advance_not_ready": (
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.GRAPH_DISPATCH,
    ),
    "collection_run_needs_continue": (
        RetryOutcomeClass.HUMAN_REQUIRED,
        RetryOutcomeOwner.OPERATOR,
    ),
    "budget_exceeded": (
        RetryOutcomeClass.HUMAN_REQUIRED,
        RetryOutcomeOwner.OPERATOR,
    ),
    "session_cancelled": (
        RetryOutcomeClass.TERMINAL,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "session_canceled": (
        RetryOutcomeClass.TERMINAL,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
    "session_stopped": (
        RetryOutcomeClass.TERMINAL,
        RetryOutcomeOwner.STAGE_SESSION,
    ),
}


def _taxonomy_entry(
    outcome_code: str = "some_failure_code",
    outcome_class: RetryOutcomeClass = RetryOutcomeClass.RETRYABLE_BUSINESS,
    owner: RetryOutcomeOwner = RetryOutcomeOwner.STAGE_SESSION,
    charge_rule: RetryChargeRule | None = None,
    basis: str = "test basis",
    human_actions: tuple[HumanActionFamily, ...] = (),
) -> RetryTaxonomyEntry:
    if charge_rule is None:
        charge_rule = {
            RetryOutcomeClass.RETRYABLE_INFRA: RetryChargeRule.NOT_CHARGED,
            RetryOutcomeClass.RETRYABLE_BUSINESS: RetryChargeRule.CHARGED,
            RetryOutcomeClass.TERMINAL: RetryChargeRule.NOT_RETRYABLE,
            RetryOutcomeClass.HUMAN_REQUIRED: RetryChargeRule.NOT_RETRYABLE,
        }[outcome_class]
    return RetryTaxonomyEntry(
        outcome_code=outcome_code,
        outcome_class=outcome_class,
        owner=owner,
        charge_rule=charge_rule,
        basis=basis,
        human_actions=human_actions,
    )


def _node_run(
    node_id: str,
    attempt: int,
    failure_code: str,
    *,
    counts_against: bool = True,
) -> dict:
    item: dict = {
        "nodeId": node_id,
        "attempt": attempt,
        "status": "blocked",
        "failureCode": failure_code,
    }
    if not counts_against:
        item["countsAgainstRetryBudget"] = False
    return item


# -- frozen default classification ------------------------------------------


@pytest.mark.parametrize("outcome_code", sorted(EXPECTED_DEFAULT_CLASSIFICATION))
def test_default_taxonomy_classification_is_frozen(outcome_code: str) -> None:
    entry = DEFAULT_RETRY_TAXONOMY.entry(outcome_code)
    expected_class, expected_owner = EXPECTED_DEFAULT_CLASSIFICATION[outcome_code]
    assert entry.outcome_class is expected_class
    assert entry.owner is expected_owner
    assert entry.basis.strip() != ""


def test_default_taxonomy_covers_exactly_the_frozen_registry() -> None:
    assert set(DEFAULT_RETRY_TAXONOMY.codes()) == set(
        EXPECTED_DEFAULT_CLASSIFICATION
    )
    distribution = Counter(
        entry.outcome_class for entry in DEFAULT_RETRY_TAXONOMY.entries()
    )
    assert distribution[RetryOutcomeClass.RETRYABLE_INFRA] == 2
    assert distribution[RetryOutcomeClass.RETRYABLE_BUSINESS] == 14
    assert distribution[RetryOutcomeClass.HUMAN_REQUIRED] == 2
    assert distribution[RetryOutcomeClass.TERMINAL] == 3


# -- fail-closed lookups ------------------------------------------------------


@pytest.mark.parametrize(
    "unknown_code", ["", "   ", "totally_unknown_code", "LEASE_EXPIRED"]
)
def test_unknown_outcome_codes_fail_closed(unknown_code: str) -> None:
    assert DEFAULT_RETRY_TAXONOMY.knows(unknown_code) is False
    with pytest.raises(UnknownRetryOutcomeCodeError):
        DEFAULT_RETRY_TAXONOMY.classify(unknown_code)
    with pytest.raises(UnknownRetryOutcomeCodeError):
        DEFAULT_RETRY_TAXONOMY.entry(unknown_code)
    with pytest.raises(UnknownRetryOutcomeCodeError):
        DEFAULT_RETRY_TAXONOMY.may_auto_retry(unknown_code)
    with pytest.raises(UnknownRetryOutcomeCodeError):
        DEFAULT_RETRY_TAXONOMY.charges_attempt(unknown_code)


def test_unknown_codes_are_never_silently_retryable() -> None:
    assert issubclass(UnknownRetryOutcomeCodeError, ContractValidationError)
    # The only non-raising path for unknown codes is the frozen NodeRun
    # lineage view, and it maps unknown to the charged business kind there.
    assert (
        DEFAULT_RETRY_TAXONOMY.node_lineage_retry_kind("totally_unknown_code")
        == "business_retry"
    )


# -- container invariants ------------------------------------------------------


def test_duplicate_outcome_codes_are_rejected() -> None:
    with pytest.raises(ContractValidationError, match="duplicate"):
        RetryTaxonomy(
            [
                _taxonomy_entry("dup_code"),
                _taxonomy_entry("dup_code"),
            ]
        )


def test_human_required_requires_operator_owner_and_actions() -> None:
    with pytest.raises(ContractValidationError, match="operator"):
        RetryTaxonomy(
            [
                _taxonomy_entry(
                    "human_code",
                    RetryOutcomeClass.HUMAN_REQUIRED,
                    RetryOutcomeOwner.STAGE_SESSION,
                    human_actions=(HumanActionFamily.RETRY_NODE,),
                )
            ]
        )
    with pytest.raises(ContractValidationError, match="human action"):
        RetryTaxonomy(
            [
                _taxonomy_entry(
                    "human_code",
                    RetryOutcomeClass.HUMAN_REQUIRED,
                    RetryOutcomeOwner.OPERATOR,
                )
            ]
        )


def test_non_human_required_entries_may_not_declare_human_actions() -> None:
    with pytest.raises(ContractValidationError, match="human actions"):
        RetryTaxonomy(
            [
                _taxonomy_entry(
                    "business_code",
                    RetryOutcomeClass.RETRYABLE_BUSINESS,
                    human_actions=(HumanActionFamily.RETRY_NODE,),
                )
            ]
        )


def test_machine_owned_classes_reject_operator_owner() -> None:
    with pytest.raises(ContractValidationError, match="machine layer"):
        RetryTaxonomy(
            [
                _taxonomy_entry(
                    "business_code",
                    RetryOutcomeClass.RETRYABLE_BUSINESS,
                    RetryOutcomeOwner.OPERATOR,
                )
            ]
        )


def test_charge_rule_must_match_outcome_class() -> None:
    with pytest.raises(ContractValidationError, match="charge rule"):
        RetryTaxonomy(
            [
                _taxonomy_entry(
                    "infra_code",
                    RetryOutcomeClass.RETRYABLE_INFRA,
                    charge_rule=RetryChargeRule.CHARGED,
                )
            ]
        )
    with pytest.raises(ContractValidationError, match="charge rule"):
        RetryTaxonomy(
            [
                _taxonomy_entry(
                    "business_code",
                    RetryOutcomeClass.RETRYABLE_BUSINESS,
                    charge_rule=RetryChargeRule.NOT_CHARGED,
                )
            ]
        )


def test_basis_is_mandatory_and_codes_must_be_normalized() -> None:
    with pytest.raises(ContractValidationError, match="basis"):
        RetryTaxonomy([_taxonomy_entry("some_code", basis="   ")])
    with pytest.raises(ContractValidationError, match="normalized"):
        RetryTaxonomy([_taxonomy_entry("  padded_code  ")])
    with pytest.raises(ContractValidationError, match="must not be empty"):
        RetryTaxonomy([])


# -- charge semantics through retry_policy -------------------------------------


def test_infra_recovery_never_charges_the_retry_budget() -> None:
    record = {
        "inputSnapshot": {"budgetPolicy": {"maxRetries": 0}},
        "nodeRuns": [
            _node_run("source_finding", 1, "counter_evidence_missing"),
            _node_run("source_finding", 2, "counter_evidence_missing"),
            _node_run(
                "source_finding",
                3,
                "external_task_interrupted",
                counts_against=False,
            ),
            _node_run("source_finding", 4, "lease_expired", counts_against=False),
        ],
    }
    # Only the business retry (attempt 2) charges; both infra recoveries
    # leave the charged count untouched even with maxRetries=0.
    assert charged_retry_count(record, "source_finding") == 1

    available, kind = retry_is_available(
        record, "source_finding", record["nodeRuns"][-1]
    )
    assert available is True
    assert kind == "infrastructure_recovery"

    for code in ("external_task_interrupted", "lease_expired"):
        assert retry_kind_for({"failureCode": code}) == "infrastructure_recovery"
        assert (
            DEFAULT_RETRY_TAXONOMY.classify(code) is RetryOutcomeClass.RETRYABLE_INFRA
        )
        assert DEFAULT_RETRY_TAXONOMY.charges_attempt(code) is False


def test_business_failures_charge_and_exhaust_the_budget() -> None:
    record = {
        "inputSnapshot": {"budgetPolicy": {"maxRetries": 2}},
        "nodeRuns": [
            _node_run("node_a", 1, "counter_evidence_missing"),
            _node_run("node_a", 2, "counter_evidence_missing"),
            _node_run("node_a", 3, "counter_evidence_missing"),
        ],
    }
    assert charged_retry_count(record, "node_a") == 2

    available, kind = retry_is_available(record, "node_a", record["nodeRuns"][-1])
    assert available is False
    assert kind == "business_retry"

    within_budget = {
        "inputSnapshot": {"budgetPolicy": {"maxRetries": 2}},
        "nodeRuns": record["nodeRuns"][:2],
    }
    available_mid, _ = retry_is_available(
        within_budget, "node_a", within_budget["nodeRuns"][-1]
    )
    assert available_mid is True

    missing_policy = {"inputSnapshot": {}, "nodeRuns": record["nodeRuns"]}
    available_default, _ = retry_is_available(
        missing_policy, "node_a", record["nodeRuns"][-1]
    )
    assert available_default is False


# -- human-required outcomes ----------------------------------------------------


def test_source_collection_needs_continue_is_fatal_and_human_required() -> None:
    entry = DEFAULT_RETRY_TAXONOMY.entry("collection_run_needs_continue")
    assert entry.outcome_class is RetryOutcomeClass.HUMAN_REQUIRED
    assert entry.owner is RetryOutcomeOwner.OPERATOR
    assert HumanActionFamily.RECONCILE_RUN in entry.human_actions
    assert HumanActionFamily.ARCHIVE_RUN in entry.human_actions

    assert DEFAULT_RETRY_TAXONOMY.may_auto_retry("collection_run_needs_continue") is False
    assert DEFAULT_RETRY_TAXONOMY.charges_attempt("collection_run_needs_continue") is False

    # The NodeRun lineage must never hand it a free infrastructure recovery.
    assert (
        retry_kind_for({"failureCode": "collection_run_needs_continue"})
        == "business_retry"
    )


def test_budget_exhaustion_leaves_only_human_actions() -> None:
    entry = DEFAULT_RETRY_TAXONOMY.entry("budget_exceeded")
    assert entry.outcome_class is RetryOutcomeClass.HUMAN_REQUIRED
    assert entry.owner is RetryOutcomeOwner.OPERATOR
    assert set(entry.human_actions) == {
        HumanActionFamily.RECONCILE_RUN,
        HumanActionFamily.ARCHIVE_RUN,
    }
    assert DEFAULT_RETRY_TAXONOMY.may_auto_retry("budget_exceeded") is False


def test_terminal_outcomes_are_never_auto_retryable() -> None:
    terminal_codes = DEFAULT_RETRY_TAXONOMY.codes_for_outcome_class(
        RetryOutcomeClass.TERMINAL
    )
    assert set(terminal_codes) == {"session_cancelled", "session_canceled", "session_stopped"}
    for code in terminal_codes:
        assert DEFAULT_RETRY_TAXONOMY.may_auto_retry(code) is False
        assert retry_kind_for({"failureCode": code}) == "business_retry"


# -- hollow-success rerun blockers ----------------------------------------------


@pytest.mark.parametrize(
    "blocker_code", ["source_candidates_missing", "evidence_graph_incomplete"]
)
def test_hollow_success_rerun_blockers_stay_charged_business(
    blocker_code: str,
) -> None:
    assert DEFAULT_RETRY_TAXONOMY.classify(blocker_code) is (
        RetryOutcomeClass.RETRYABLE_BUSINESS
    )
    assert DEFAULT_RETRY_TAXONOMY.owner_of(blocker_code) is (
        RetryOutcomeOwner.STAGE_SESSION
    )
    assert DEFAULT_RETRY_TAXONOMY.charges_attempt(blocker_code) is True


# -- NodeRun lineage behavior stays frozen ---------------------------------------


@pytest.mark.parametrize(
    "failure_code",
    [
        "",
        "unknown_lineage_code",
        "session_needs_continue",
        "collection_run_needs_continue",
        "budget_exceeded",
        "session_stopped",
        "counter_evidence_missing",
        "auto_advance_not_ready",
    ],
)
def test_lineage_keeps_charged_business_fallback(failure_code: str) -> None:
    assert retry_kind_for({"failureCode": failure_code}) == "business_retry"
    assert retry_kind_for({}) == "business_retry"


def test_infrastructure_codes_are_derived_from_the_taxonomy() -> None:
    assert INFRASTRUCTURE_FAILURE_CODES == frozenset(
        DEFAULT_RETRY_TAXONOMY.codes_for_outcome_class(
            RetryOutcomeClass.RETRYABLE_INFRA
        )
    )
    assert INFRASTRUCTURE_FAILURE_CODES == frozenset(
        {"external_task_interrupted", "lease_expired"}
    )
