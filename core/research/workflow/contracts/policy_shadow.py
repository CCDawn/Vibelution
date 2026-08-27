"""Automation policy shadow evaluation contracts (R1.4).

Naming guard: everything here is the *automation policy shadow* — a policy
with ``executionMode == "shadow"`` (see ``automation_policy``) evaluated next
to a real decision point to record "what would the system policy do if it
were active".  It is unrelated to the ``off/shadow/on`` session-scope modes of
``hypothesis_session_scope_mode`` and the two concepts must not be conflated.

Two frozen documents are described:

- ``PolicyShadowDecision`` — the recommendation produced at one decision
  point: which capability switch was consulted, which action the policy
  *would* take if active, the summarized payload (candidate ids etc.) and the
  real gate evidence observed at that point.
- ``PolicyShadowEvaluationRecord`` — the human-comparison record that pairs
  one shadow decision with what actually happened at the same decision point
  (the real command/outcome reference) plus the would-vs-actual agreement
  class, mirroring the G12 calibration judgment-record shape (machine decision
  vs human decision per question, with ``false_auto_approve`` defined as
  "machine would auto-advance while the human escalated or vetoed").

Scope guard: these contracts never authorize execution.  Records about a
policy whose ``executionMode`` is not ``shadow`` are rejected fail-closed, the
agreement enum is closed, and ``false_auto_approve`` is structurally
impossible unless the would-decide is an ``auto_*`` action AND the actual
human outcome is an escalation/veto.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ._validation import ContractValidationError

POLICY_SHADOW_SCHEMA_VERSION = "1"

# The five real decision points (one per capability switch, frozen mapping).
POLICY_SHADOW_DECISION_POINTS: frozenset[str] = frozenset(
    {
        "meeting_close",
        "candidate_selection",
        "evidence_repair",
        "converge_question",
        "batch_gate",
    }
)

POLICY_SHADOW_CAPABILITY_FOR_POINT: dict[str, str] = {
    "meeting_close": "autoCloseMeetingRound",
    "candidate_selection": "autoSelectCandidates",
    "evidence_repair": "autoStartEvidenceRepair",
    "converge_question": "autoConvergeQuestion",
    "batch_gate": "autoAdvanceBatchGate",
}

# The action the system policy would take when the switch is enabled and all
# hard gates pass at that point; "hold" means it would do nothing (switch off
# or gates failed) and the human stays in the loop.
POLICY_SHADOW_ACTION_FOR_POINT: dict[str, str] = {
    "meeting_close": "auto_close",
    "candidate_selection": "auto_select",
    "evidence_repair": "auto_repair",
    "converge_question": "auto_converge",
    "batch_gate": "auto_gate",
}

POLICY_SHADOW_AUTO_ACTIONS: frozenset[str] = frozenset(
    set(POLICY_SHADOW_ACTION_FOR_POINT.values())
)
POLICY_SHADOW_WOULD_DECIDE_VALUES: frozenset[str] = frozenset(
    {*POLICY_SHADOW_AUTO_ACTIONS, "hold"}
)

# What the human actually did at the same decision point, coarse-classified:
# "acted" performed the automation-equivalent action, "escalated" asked for
# more work (e.g. requested new evidence instead of closing), "vetoed"
# rejected the direction outright, "none" means no comparable human decision.
POLICY_SHADOW_OUTCOME_CLASSES: frozenset[str] = frozenset(
    {"acted", "escalated", "vetoed", "none"}
)

POLICY_SHADOW_AGREEMENTS: frozenset[str] = frozenset(
    {"agree", "false_auto_approve", "false_escalate", "neutral"}
)

PolicyShadowAgreement = Literal["agree", "false_auto_approve", "false_escalate", "neutral"]


def derive_shadow_agreement(
    would_decide: str, actual_outcome_class: str
) -> PolicyShadowAgreement:
    """Derive the would-vs-actual agreement class (G12 calibration shape).

    The four-cell confusion matrix over ``wouldDecide`` (auto action vs hold)
    and the human outcome class (acted vs escalated/vetoed):

    - would ``auto_*`` + human acted the same way      -> ``agree``
    - would ``auto_*`` + human escalated/vetoed        -> ``false_auto_approve``
    - would ``hold``    + human escalated/vetoed       -> ``agree`` (both conservative)
    - would ``hold``    + human did the action anyway  -> ``false_escalate``
    - no comparable human outcome                      -> ``neutral``
    """

    if actual_outcome_class == "none":
        return "neutral"
    if would_decide in POLICY_SHADOW_AUTO_ACTIONS:
        if actual_outcome_class == "acted":
            return "agree"
        return "false_auto_approve"
    if actual_outcome_class == "acted":
        return "false_escalate"
    return "agree"


def _shadow_error(field: str, message: str) -> ContractValidationError:
    return ContractValidationError(f"policy shadow contract rejected [{field}]: {message}")


def _normalized_decision_point(value: Any) -> str:
    point = str(value or "").strip()
    if point not in POLICY_SHADOW_DECISION_POINTS:
        raise _shadow_error(
            "decisionPoint",
            f"must be one of {', '.join(sorted(POLICY_SHADOW_DECISION_POINTS))}; got {point!r}",
        )
    return point


def _normalized_capability(point: str, value: Any) -> str:
    capability = str(value or "").strip()
    expected = POLICY_SHADOW_CAPABILITY_FOR_POINT[point]
    if capability != expected:
        raise _shadow_error(
            "capability",
            f"decision point {point!r} is owned by {expected!r}; got {capability!r}",
        )
    return capability


def _normalized_would_decide(point: str, value: Any) -> str:
    would = str(value or "").strip()
    if would not in POLICY_SHADOW_WOULD_DECIDE_VALUES:
        raise _shadow_error(
            "wouldDecide",
            f"must be one of {', '.join(sorted(POLICY_SHADOW_WOULD_DECIDE_VALUES))}; got {would!r}",
        )
    action = POLICY_SHADOW_ACTION_FOR_POINT[point]
    if would not in {"hold", action}:
        raise _shadow_error(
            "wouldDecide",
            f"decision point {point!r} can only recommend {action!r} or 'hold'; got {would!r}",
        )
    return would


def _validated_evidence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise _shadow_error("evidence", "must be a list of gate entries")
    evidence: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise _shadow_error("evidence", "every gate entry must be an object")
        entry = dict(item)
        gate_id = str(entry.get("gateId") or "").strip()
        if not gate_id:
            raise _shadow_error("evidence.gateId", "every gate entry needs a gateId")
        if not isinstance(entry.get("passed"), bool):
            raise _shadow_error(
                "evidence.passed", f"gate {gate_id!r} must declare a boolean passed"
            )
        evidence.append(entry)
    return evidence


def _validated_mapping_field(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _shadow_error(field, "must be an object")
    return dict(value)


def _require_text_field(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise _shadow_error(field, "must be a non-empty string")
    return text


@dataclass(frozen=True, slots=True)
class PolicyShadowDecision:
    """One recommendation computed beside a real decision point.

    Pure advisory output of the shadow evaluator: the capability consulted,
    the action the policy *would* take if active, a bounded payload summary
    (e.g. candidate ids) and the real gate evidence observed at the point.
    Carries no authority: nothing here may be executed or emitted as a
    command.
    """

    schemaVersion: str
    capability: str
    decisionPoint: str
    wouldDecide: str
    wouldDecidePayload: dict[str, Any]
    evidence: list[dict[str, Any]]
    evaluatedAt: str

    def __post_init__(self) -> None:
        if self.schemaVersion != POLICY_SHADOW_SCHEMA_VERSION:
            raise _shadow_error(
                "schemaVersion",
                f"must be {POLICY_SHADOW_SCHEMA_VERSION}",
            )
        point = _normalized_decision_point(self.decisionPoint)
        _normalized_capability(point, self.capability)
        _normalized_would_decide(point, self.wouldDecide)
        _validated_mapping_field(self.wouldDecidePayload, "wouldDecidePayload")
        _validated_evidence(self.evidence)
        _require_text_field(self.evaluatedAt, "evaluatedAt")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "capability": self.capability,
            "decisionPoint": self.decisionPoint,
            "wouldDecide": self.wouldDecide,
            "wouldDecidePayload": dict(self.wouldDecidePayload),
            "evidence": [dict(item) for item in self.evidence],
            "evaluatedAt": self.evaluatedAt,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> PolicyShadowDecision:
        if not isinstance(payload, dict):
            raise _shadow_error("payload", "must be a JSON object")
        return cls(
            schemaVersion=str(payload.get("schemaVersion") or "").strip(),
            capability=str(payload.get("capability") or "").strip(),
            decisionPoint=str(payload.get("decisionPoint") or "").strip(),
            wouldDecide=str(payload.get("wouldDecide") or "").strip(),
            wouldDecidePayload=dict(payload.get("wouldDecidePayload") or {}),
            evidence=list(payload.get("evidence") or []),
            evaluatedAt=str(payload.get("evaluatedAt") or "").strip(),
        )


@dataclass(frozen=True, slots=True)
class PolicyShadowEvaluationRecord:
    """Human-comparison record pairing one shadow decision with the reality.

    ``actualOutcome`` references the real command/outcome observed at the same
    decision point (outcome text plus coarse ``outcomeClass``); ``agreement``
    is the derived would-vs-actual class used by the G12 calibration stream.
    ``policyId``/``policyVersion``/``policyContentHash`` pin the exact policy
    snapshot consulted; records about a non-shadow policy are rejected.
    """

    schemaVersion: str
    recordId: str
    teamId: str
    questionId: str
    scope: dict[str, Any]
    decisionPoint: str
    capability: str
    wouldDecide: str
    wouldDecidePayload: dict[str, Any]
    evidence: list[dict[str, Any]]
    actualOutcome: dict[str, Any]
    agreement: PolicyShadowAgreement
    evaluatedAt: str
    policyId: str
    policyVersion: str
    policyContentHash: str
    policyExecutionMode: str

    def __post_init__(self) -> None:
        if self.schemaVersion != POLICY_SHADOW_SCHEMA_VERSION:
            raise _shadow_error(
                "schemaVersion",
                f"must be {POLICY_SHADOW_SCHEMA_VERSION}",
            )
        _require_text_field(self.recordId, "recordId")
        _require_text_field(self.teamId, "teamId")
        _require_text_field(self.questionId, "questionId")
        _validated_mapping_field(self.scope, "scope")

        point = _normalized_decision_point(self.decisionPoint)
        _normalized_capability(point, self.capability)
        would = _normalized_would_decide(point, self.wouldDecide)
        _validated_mapping_field(self.wouldDecidePayload, "wouldDecidePayload")
        _validated_evidence(self.evidence)

        outcome = _validated_mapping_field(self.actualOutcome, "actualOutcome")
        outcome_class = str(outcome.get("outcomeClass") or "").strip()
        if outcome_class not in POLICY_SHADOW_OUTCOME_CLASSES:
            raise _shadow_error(
                "actualOutcome.outcomeClass",
                "must be one of "
                f"{', '.join(sorted(POLICY_SHADOW_OUTCOME_CLASSES))}; got {outcome_class!r}",
            )

        agreement = str(self.agreement or "").strip()
        expected_agreement = derive_shadow_agreement(would, outcome_class)
        if agreement != expected_agreement:
            raise _shadow_error(
                "agreement",
                f"wouldDecide={would!r} with outcomeClass={outcome_class!r} "
                f"derives agreement={expected_agreement!r}; got {agreement!r}",
            )

        _require_text_field(self.evaluatedAt, "evaluatedAt")
        _require_text_field(self.policyId, "policyId")
        _require_text_field(self.policyVersion, "policyVersion")
        content_hash = _require_text_field(self.policyContentHash, "policyContentHash")
        if len(content_hash) != 64 or any(
            char not in "0123456789ABCDEF" for char in content_hash
        ):
            raise _shadow_error(
                "policyContentHash", "must be an uppercase sha256 hex digest"
            )
        if self.policyExecutionMode != "shadow":
            # Fail-closed: an evaluation record is only meaningful for a
            # shadow policy.  Nothing may produce a record about an active
            # policy; that state belongs to activation, not to shadow trials.
            raise _shadow_error(
                "policyExecutionMode",
                f"shadow records require executionMode='shadow'; got {self.policyExecutionMode!r}",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "recordId": self.recordId,
            "teamId": self.teamId,
            "questionId": self.questionId,
            "scope": dict(self.scope),
            "decisionPoint": self.decisionPoint,
            "capability": self.capability,
            "wouldDecide": self.wouldDecide,
            "wouldDecidePayload": dict(self.wouldDecidePayload),
            "evidence": [dict(item) for item in self.evidence],
            "actualOutcome": dict(self.actualOutcome),
            "agreement": self.agreement,
            "evaluatedAt": self.evaluatedAt,
            "policyId": self.policyId,
            "policyVersion": self.policyVersion,
            "policyContentHash": self.policyContentHash,
            "policyExecutionMode": self.policyExecutionMode,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> PolicyShadowEvaluationRecord:
        if not isinstance(payload, dict):
            raise _shadow_error("payload", "must be a JSON object")
        return cls(
            schemaVersion=str(payload.get("schemaVersion") or "").strip(),
            recordId=str(payload.get("recordId") or "").strip(),
            teamId=str(payload.get("teamId") or "").strip(),
            questionId=str(payload.get("questionId") or "").strip(),
            scope=dict(payload.get("scope") or {}),
            decisionPoint=str(payload.get("decisionPoint") or "").strip(),
            capability=str(payload.get("capability") or "").strip(),
            wouldDecide=str(payload.get("wouldDecide") or "").strip(),
            wouldDecidePayload=dict(payload.get("wouldDecidePayload") or {}),
            evidence=list(payload.get("evidence") or []),
            actualOutcome=dict(payload.get("actualOutcome") or {}),
            agreement=str(payload.get("agreement") or "").strip(),
            evaluatedAt=str(payload.get("evaluatedAt") or "").strip(),
            policyId=str(payload.get("policyId") or "").strip(),
            policyVersion=str(payload.get("policyVersion") or "").strip(),
            policyContentHash=str(payload.get("policyContentHash") or "").strip(),
            policyExecutionMode=str(payload.get("policyExecutionMode") or "").strip(),
        )


__all__ = [
    "POLICY_SHADOW_ACTION_FOR_POINT",
    "POLICY_SHADOW_AGREEMENTS",
    "POLICY_SHADOW_AUTO_ACTIONS",
    "POLICY_SHADOW_CAPABILITY_FOR_POINT",
    "POLICY_SHADOW_DECISION_POINTS",
    "POLICY_SHADOW_OUTCOME_CLASSES",
    "POLICY_SHADOW_SCHEMA_VERSION",
    "POLICY_SHADOW_WOULD_DECIDE_VALUES",
    "PolicyShadowAgreement",
    "PolicyShadowDecision",
    "PolicyShadowEvaluationRecord",
    "derive_shadow_agreement",
]
