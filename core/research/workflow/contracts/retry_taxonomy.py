"""Retry outcome taxonomy: the frozen single-owner classification of retry endings.

R3.4 "single retry owner" freeze. Every retry-decidable workflow outcome code
(``failureCode`` / blocker code strings) maps to exactly one outcome class,
one owning layer and one charge rule. The taxonomy freezes the semantics
settled by the 2026-08-27 repair sequence:

- Infrastructure failures (``lease_expired`` / ``external_task_interrupted``)
  recover as a new attempt that never charges ``budgetPolicy.maxRetries``.
- Business failures retry within ``budgetPolicy.maxRetries`` (formal runs
  default to 2); once the budget is exhausted the only way forward is a human
  action family (``retry_node`` / ``reconcile_run`` / ``archive_run`` ...).
- ``needs_continue`` is fatal for the source-collection family and must never
  be auto-reconciled (P0 contract frozen by commit ``cf789360c``); the parked
  run blocks as ``collection_run_needs_continue`` and only a human
  reconcile/archive rebuild resolves it.
- Hollow-success reruns of idempotent collection nodes (``714e1b837``) and
  explicit reruns that skip completed ancestor reuse (``b83056dbb``) keep
  their blockers classified as charged business retries.

Fail-closed rule: looking up an outcome code that is not part of the taxonomy
raises :class:`UnknownRetryOutcomeCodeError`. Unknown codes are never
silently classified as retryable. The one documented exception is the frozen
NodeRun-lineage view (:meth:`RetryTaxonomy.node_lineage_retry_kind`) consumed
by ``research_runtime.retry_policy``; it must not change observable behavior
for codes outside the taxonomy, so it keeps the charged ``business_retry``
fallback there instead of raising.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._validation import ContractValidationError, require_text

NODE_LINEAGE_RETRY_KIND_INFRASTRUCTURE_RECOVERY = "infrastructure_recovery"
NODE_LINEAGE_RETRY_KIND_BUSINESS = "business_retry"


class RetryOutcomeClass(str, Enum):
    """Frozen classification of a retry outcome.

    ``retryable_infra`` attempts recover without charging the retry budget;
    ``retryable_business`` attempts charge ``budgetPolicy.maxRetries``;
    ``terminal`` outcomes can never be retried; ``human_required`` outcomes
    leave a human action family as the only way forward.
    """

    RETRYABLE_INFRA = "retryable_infra"
    RETRYABLE_BUSINESS = "retryable_business"
    TERMINAL = "terminal"
    HUMAN_REQUIRED = "human_required"


class RetryOutcomeOwner(str, Enum):
    """The single layer that owns retry decisions for an outcome code.

    ``llm_adapter`` owns transport-level retries (attempt/backoff budget
    inside ``core/llm/client.py``) and never surfaces them as workflow
    outcome codes; ``stage_session`` owns stage/session execution failures;
    ``graph_dispatch`` owns dispatch and readiness-blocking outcomes;
    ``operator`` owns outcomes whose only resolution is a human action.
    """

    LLM_ADAPTER = "llm_adapter"
    STAGE_SESSION = "stage_session"
    GRAPH_DISPATCH = "graph_dispatch"
    OPERATOR = "operator"


class RetryChargeRule(str, Enum):
    """How an attempt with this outcome charges ``budgetPolicy.maxRetries``."""

    NOT_CHARGED = "not_charged"
    CHARGED = "charged"
    NOT_RETRYABLE = "not_retryable"


class HumanActionFamily(str, Enum):
    """Human command families that can resolve a ``human_required`` outcome."""

    RETRY_NODE = "retry_node"
    RECONCILE_RUN = "reconcile_run"
    ARCHIVE_RUN = "archive_run"
    FORK_REVISION = "fork_revision"


_CHARGE_RULE_BY_OUTCOME_CLASS: dict[RetryOutcomeClass, RetryChargeRule] = {
    RetryOutcomeClass.RETRYABLE_INFRA: RetryChargeRule.NOT_CHARGED,
    RetryOutcomeClass.RETRYABLE_BUSINESS: RetryChargeRule.CHARGED,
    RetryOutcomeClass.TERMINAL: RetryChargeRule.NOT_RETRYABLE,
    RetryOutcomeClass.HUMAN_REQUIRED: RetryChargeRule.NOT_RETRYABLE,
}

_MACHINE_OWNERS = frozenset(
    {
        RetryOutcomeOwner.LLM_ADAPTER,
        RetryOutcomeOwner.STAGE_SESSION,
        RetryOutcomeOwner.GRAPH_DISPATCH,
    }
)


class UnknownRetryOutcomeCodeError(ContractValidationError):
    """A retry outcome code is not part of the frozen taxonomy (fail-closed)."""


@dataclass(frozen=True, slots=True)
class RetryTaxonomyEntry:
    """One frozen outcome-code classification.

    ``basis`` records the evidence the classification was settled from (fix
    commit or contract test); it is mandatory so the freeze stays auditable.
    """

    outcome_code: str
    outcome_class: RetryOutcomeClass
    owner: RetryOutcomeOwner
    charge_rule: RetryChargeRule
    basis: str
    human_actions: tuple[HumanActionFamily, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "outcomeCode": self.outcome_code,
            "outcomeClass": self.outcome_class.value,
            "owner": self.owner.value,
            "chargeRule": self.charge_rule.value,
            "basis": self.basis,
        }
        if self.human_actions:
            payload["humanActions"] = [
                action.value for action in self.human_actions
            ]
        return payload


class RetryTaxonomy:
    """Immutable, fail-closed outcome-code registry.

    Construction validates every invariant eagerly; lookups raise
    :class:`UnknownRetryOutcomeCodeError` for codes outside the registry so
    callers can never default an unknown outcome into an automatic retry.
    """

    def __init__(self, entries: Iterable[RetryTaxonomyEntry]) -> None:
        mapping: dict[str, RetryTaxonomyEntry] = {}
        for entry in entries:
            if not isinstance(entry, RetryTaxonomyEntry):
                raise ContractValidationError(
                    "retry taxonomy entries must be RetryTaxonomyEntry instances"
                )
            code = str(entry.outcome_code or "").strip()
            require_text({"outcome_code": code}, "outcome_code")
            if code != entry.outcome_code:
                raise ContractValidationError(
                    f"retry outcome code must be normalized: {entry.outcome_code!r}"
                )
            if not str(entry.basis or "").strip():
                raise ContractValidationError(
                    f"retry outcome code {code} must record its settlement basis"
                )
            if code in mapping:
                raise ContractValidationError(
                    f"duplicate retry outcome code: {code}"
                )
            expected_charge = _CHARGE_RULE_BY_OUTCOME_CLASS[entry.outcome_class]
            if entry.charge_rule is not expected_charge:
                raise ContractValidationError(
                    f"retry outcome code {code} declares charge rule "
                    f"{entry.charge_rule.value} but class "
                    f"{entry.outcome_class.value} requires "
                    f"{expected_charge.value}"
                )
            if entry.outcome_class is RetryOutcomeClass.HUMAN_REQUIRED:
                if entry.owner is not RetryOutcomeOwner.OPERATOR:
                    raise ContractValidationError(
                        f"human-required outcome code {code} must be owned by "
                        "the operator layer"
                    )
                if not entry.human_actions:
                    raise ContractValidationError(
                        f"human-required outcome code {code} must declare at "
                        "least one human action family"
                    )
            else:
                if entry.human_actions:
                    raise ContractValidationError(
                        f"retry outcome code {code} declares human actions "
                        "without being human-required"
                    )
                if entry.owner not in _MACHINE_OWNERS:
                    raise ContractValidationError(
                        f"retry outcome code {code} must be owned by a machine "
                        "layer, not the operator"
                    )
            mapping[code] = entry
        if not mapping:
            raise ContractValidationError("retry taxonomy must not be empty")
        self._entries: dict[str, RetryTaxonomyEntry] = mapping

    def knows(self, outcome_code: str) -> bool:
        """True when the code is part of this taxonomy (the only soft lookup)."""
        return str(outcome_code or "").strip() in self._entries

    def entry(self, outcome_code: str) -> RetryTaxonomyEntry:
        code = str(outcome_code or "").strip()
        try:
            return self._entries[code]
        except KeyError:
            raise UnknownRetryOutcomeCodeError(
                f"unknown retry outcome code: {code!r}"
            ) from None

    def classify(self, outcome_code: str) -> RetryOutcomeClass:
        return self.entry(outcome_code).outcome_class

    def owner_of(self, outcome_code: str) -> RetryOutcomeOwner:
        return self.entry(outcome_code).owner

    def charges_attempt(self, outcome_code: str) -> bool:
        """True when an attempt with this outcome charges the retry budget."""
        return self.entry(outcome_code).charge_rule is RetryChargeRule.CHARGED

    def may_auto_retry(self, outcome_code: str) -> bool:
        """True when this outcome may be retried without a human decision."""
        outcome_class = self.classify(outcome_code)
        return outcome_class in {
            RetryOutcomeClass.RETRYABLE_INFRA,
            RetryOutcomeClass.RETRYABLE_BUSINESS,
        }

    def codes(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def entries(self) -> tuple[RetryTaxonomyEntry, ...]:
        return tuple(self._entries.values())

    def codes_for_outcome_class(
        self, outcome_class: RetryOutcomeClass
    ) -> tuple[str, ...]:
        return tuple(
            code
            for code, entry in self._entries.items()
            if entry.outcome_class is outcome_class
        )

    def node_lineage_retry_kind(self, outcome_code: str) -> str:
        """Frozen NodeRun-lineage mapping consumed by ``retry_policy``.

        Known infrastructure codes map to ``infrastructure_recovery``; every
        other code -- including codes outside the taxonomy -- keeps the
        charged ``business_retry`` lineage kind. This fallback is a frozen
        behavior guarantee of the NodeRun retry lineage (the fail-closed
        contract lives in :meth:`classify`, not here); it can only change
        together with the lineage tests that pin it.
        """
        entry = self._entries.get(str(outcome_code or "").strip())
        if entry is not None and entry.outcome_class is (
            RetryOutcomeClass.RETRYABLE_INFRA
        ):
            return NODE_LINEAGE_RETRY_KIND_INFRASTRUCTURE_RECOVERY
        return NODE_LINEAGE_RETRY_KIND_BUSINESS


def _entry(
    outcome_code: str,
    outcome_class: RetryOutcomeClass,
    owner: RetryOutcomeOwner,
    basis: str,
    *,
    human_actions: tuple[HumanActionFamily, ...] = (),
) -> RetryTaxonomyEntry:
    return RetryTaxonomyEntry(
        outcome_code=outcome_code,
        outcome_class=outcome_class,
        owner=owner,
        charge_rule=_CHARGE_RULE_BY_OUTCOME_CLASS[outcome_class],
        basis=basis,
        human_actions=human_actions,
    )


_DEFAULT_RETRY_TAXONOMY_ENTRIES: tuple[RetryTaxonomyEntry, ...] = (
    # -- retryable_infra: recover for free, never charge maxRetries --------
    _entry(
        "external_task_interrupted",
        RetryOutcomeClass.RETRYABLE_INFRA,
        RetryOutcomeOwner.STAGE_SESSION,
        "retry_policy.py INFRASTRUCTURE_FAILURE_CODES (pre-freeze set); "
        "tests/test_research_workflow_v21_node_retry_capability.py::"
        "test_infrastructure_interruption_recovers_without_reopening_business_"
        "retry_budget pins countsAgainstRetryBudget=false",
    ),
    _entry(
        "lease_expired",
        RetryOutcomeClass.RETRYABLE_INFRA,
        RetryOutcomeOwner.STAGE_SESSION,
        "retry_policy.py INFRASTRUCTURE_FAILURE_CODES (pre-freeze set); "
        "lease loss is an execution infrastructure event, not a content "
        "verdict",
    ),
    # -- retryable_business: charged against budgetPolicy.maxRetries -------
    _entry(
        "counter_evidence_missing",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "default business failure code of "
        "tests/test_research_workflow_v21_node_retry_capability.py; "
        "exhausts maxRetries with the charged-business lineage kind",
    ),
    _entry(
        "external_task_needs_review",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "evidence_remediation_fork.py gates its remediation fork on the "
        "business_retry lineage kind for this code; needs a human review "
        "outcome before the stage can settle",
    ),
    _entry(
        "external_agent_task_missing",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "external_agent_task_reconciliation.py:285,413; lineage "
        "classification stays charged business (no settlement exempts it)",
    ),
    _entry(
        "external_agent_task_mismatch",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "external_agent_task_reconciliation.py; charged business lineage "
        "kind",
    ),
    _entry(
        "external_agent_task_lookup_failed",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "external_agent_task_reconciliation.py; charged business lineage "
        "kind",
    ),
    _entry(
        "external_agent_session_mismatch",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "external_agent_task_reconciliation.py:338,478; charged business "
        "lineage kind",
    ),
    _entry(
        "external_task_completion_gate_failed",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "external_agent_task_reconciliation.py:469; charged business lineage "
        "kind",
    ),
    _entry(
        "external_task_completion_invalid",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "external_agent_task_reconciliation.py:358,532 (fallback code of "
        "completion exceptions); charged business lineage kind",
    ),
    _entry(
        "task_bundle_cancelled",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "task_bundle_lifecycle.py:998,1028; the lineage keeps it charged "
        "business -- bundle cancellation blocks the run and a retry within "
        "budget is the only automatic path",
    ),
    _entry(
        "agent_turn_continuation_exhausted",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "agent_turn_completion.py:405-449; continuation budget exhaustion "
        "fails the attempt and is never downgraded into success",
    ),
    _entry(
        "session_needs_continue",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "research_project_agent_tasks.py:1919-1927; the project-task "
        "authority owns the verdict (cf789360c counterpart contract) and "
        "may reconcile needs_continue for the research_project family -- "
        "unlike the source-collection family this is not human_required",
    ),
    _entry(
        "source_candidates_missing",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "714e1b837 hollow-success rerun: readiness blocker of "
        "readiness/source_collection.py:117; "
        "command_offers/retry_node.py _RERUN_BLOCKER_TARGET_NODES routes it "
        "to an idempotent source_finding rerun",
    ),
    _entry(
        "evidence_graph_incomplete",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.STAGE_SESSION,
        "b83056dbb explicit rerun: evidence_relations rerun skips completed "
        "ancestor reuse; command_offers/retry_node.py "
        "_RERUN_BLOCKER_TARGET_NODES",
    ),
    _entry(
        "auto_advance_not_ready",
        RetryOutcomeClass.RETRYABLE_BUSINESS,
        RetryOutcomeOwner.GRAPH_DISPATCH,
        "blocked_reason.py:87-88; run-level blocked problem code produced by "
        "the graph/readiness layer whose details route to the "
        "hollow-success rerun mapping in command_offers/retry_node.py:44",
    ),
    # -- human_required: the only way forward is a human action ------------
    _entry(
        "collection_run_needs_continue",
        RetryOutcomeClass.HUMAN_REQUIRED,
        RetryOutcomeOwner.OPERATOR,
        "hypothesis_first_state_v2.py:1366-1368 parked-run blocked code; "
        "cf789360c P0 contract: source-collection turns keep needs_continue "
        "fatal and must never be auto-reconciled, so reconcile_run/archive_run "
        "rebuild is the only way forward",
        human_actions=(HumanActionFamily.RECONCILE_RUN, HumanActionFamily.ARCHIVE_RUN),
    ),
    _entry(
        "budget_exceeded",
        RetryOutcomeClass.HUMAN_REQUIRED,
        RetryOutcomeOwner.OPERATOR,
        "settled 2026-08-27 semantics: once the run is over budget "
        "(budget_lifecycle.py:175-206, budget_overrun_reconciliation.py:86,104) "
        "the only way forward is a human reconcile_run/archive_run rebuild; "
        "no automatic retry may consume budget that no longer exists",
        human_actions=(HumanActionFamily.RECONCILE_RUN, HumanActionFamily.ARCHIVE_RUN),
    ),
    _entry(
        "collection_auto_retry_exhausted",
        RetryOutcomeClass.HUMAN_REQUIRED,
        RetryOutcomeOwner.OPERATOR,
        "hypothesis_first_chain.py collection auto-retry contract: a failed "
        "hypothesis-first collection request receives at most "
        "SOURCE_COLLECTION_AUTO_RETRY_MAX_ATTEMPTS automatic recover attempts "
        "(same in-process implementation as the recover endpoint, exponential "
        "backoff on a background thread); once that budget is exhausted the "
        "request stays failed and only the human recover endpoint resolves it "
        "(needs_continue is out of scope entirely: it stays fatal per the "
        "cf789360c P0 contract); contract tests "
        "test_research_workflow_hypothesis_first_chain.py and "
        "test_research_workflow_retry_taxonomy.py",
        human_actions=(HumanActionFamily.RETRY_NODE, HumanActionFamily.RECONCILE_RUN),
    ),
    # -- terminal: never retried ------------------------------------------
    _entry(
        "session_cancelled",
        RetryOutcomeClass.TERMINAL,
        RetryOutcomeOwner.STAGE_SESSION,
        "research_project_agent_tasks.py:1905-1912 maps a cancelled session "
        "phase to the terminal kind with failureCode session_<phase>; a "
        "cancelled task is a verdict, not a retry candidate",
    ),
    _entry(
        "session_canceled",
        RetryOutcomeClass.TERMINAL,
        RetryOutcomeOwner.STAGE_SESSION,
        "same mapping as session_cancelled, alternate spelling accepted by "
        "research_project_agent_tasks.py:1905",
    ),
    _entry(
        "session_stopped",
        RetryOutcomeClass.TERMINAL,
        RetryOutcomeOwner.STAGE_SESSION,
        "research_project_agent_tasks.py:1905-1912 maps a stopped session "
        "phase to the terminal kind; reviving it is the task authority's "
        "decision, never an automatic retry",
    ),
)

DEFAULT_RETRY_TAXONOMY = RetryTaxonomy(_DEFAULT_RETRY_TAXONOMY_ENTRIES)
