"""G12 calibration gate wiring service (pure projection, no execution).

Connects the three frozen G12 gate bases into one read-only data flow:

1. ``audit_sampling`` manifest (G12 full-pilot sampling scope)
2. ``calibration_records`` judgement records bound to that manifest
3. ``calibration_stats`` stratified report + activation gate assessment
4. a *thin* activation-advice projection against an ``AutoAdvancePolicyV2``
   ``calibrationGate`` (advice only -- activation still goes through the
   frozen policy contentHash gate; this module never activates anything)

Like its siblings (``audit_sampling_service``, ``automation_policy_service``)
this module never executes workflow work, never subscribes to the command
chain and never touches the ledger.  Every entry point fails closed: an
incomplete bundle produces a ``pending`` assessment without statistics, a
complete-but-underpowered pilot produces ``insufficient``, and a policy with
missing ``calibrationGate`` fields produces explicit gaps mirroring the
automation-policy contract's ``missing_calibration_gate_field`` semantics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from core.research.competition.calibration_records import (
    BUNDLE_STATUS_COMPLETE,
    G12CalibrationBundle,
    G12JudgementRecord,
)
from core.research.competition.calibration_stats import (
    DEFAULT_CONFIDENCE,
    DEFAULT_UPPER_BOUND_METHOD,
    PILOT_SAMPLE_SIZE_CEILING,
    UPPER_BOUND_METHODS,
    activation_gate_assessment,
    stratum_report,
)
from core.research.workflow.contracts.automation_policy import (
    CALIBRATION_GATE_REQUIRED_FIELDS,
    AutoAdvancePolicyV2,
)
from core.research.workflow.contracts.audit_sampling import AuditSampleManifest
from core.web.services.team_workflow.research_runtime.audit_sampling_service import (
    AuditSamplingError,
    policy_reference,
)

G12_GATE = "G12"

ASSESSMENT_STATUS_PENDING = "pending"
ASSESSMENT_STATUS_INSUFFICIENT = "insufficient"
ASSESSMENT_STATUS_COMPLETE = "complete"

#: Error codes mirrored from the automation_policy contract validation
#: semantics so advice gaps read exactly like the frozen validator's output.
CODE_MISSING_CALIBRATION_GATE_FIELD = "missing_calibration_gate_field"
CODE_MISSING_OR_INVALID = "missing_or_invalid"
CODE_ACTIVE_MODE_FORBIDDEN_IN_PREVIEW = "active_mode_forbidden_in_preview"

_FIELD_GAP_MESSAGE = (
    "statistical calibration gate field is required (decision #13)"
)


class G12CalibrationServiceError(ValueError):
    """Typed fail-closed error for G12 calibration gate wiring."""


def collect_pending_records(
    manifest: AuditSampleManifest,
    records: Sequence[G12JudgementRecord] = (),
) -> dict[str, Any]:
    """Project the pending judgement checklist for one G12 manifest.

    ``records`` optionally carries already-collected
    :class:`G12JudgementRecord` items; each is fail-closed checked against
    the manifest scope so a foreign record can never mask a pending
    question.  The projection is descriptive only -- it records WHAT still
    needs a judgement, never one itself.
    """

    if not isinstance(manifest, AuditSampleManifest):
        raise G12CalibrationServiceError(
            "manifest must be an AuditSampleManifest"
        )
    if manifest.gate != G12_GATE:
        raise G12CalibrationServiceError(
            f"gate must be {G12_GATE}; got {manifest.gate!r}"
        )
    record_items = tuple(records)
    recorded_ids: set[str] = set()
    for record in record_items:
        if not isinstance(record, G12JudgementRecord):
            raise G12CalibrationServiceError(
                "records must be G12JudgementRecord items"
            )
        if record.questionId not in set(manifest.questionIds):
            raise G12CalibrationServiceError(
                f"judgement record question {record.questionId!r} is outside "
                "the manifest sampling scope"
            )
        if manifest.sampleKinds.get(record.questionId) is not record.sampleKind:
            raise G12CalibrationServiceError(
                f"judgement record sampleKind does not match the manifest "
                f"assignment for question {record.questionId!r}"
            )
        recorded_ids.add(record.questionId)
    pending = [
        {
            "questionId": question_id,
            "sampleKind": manifest.sampleKinds[question_id].value,
        }
        for question_id in sorted(set(manifest.questionIds) - recorded_ids)
    ]
    return {
        "manifestId": manifest.manifestId,
        "gate": manifest.gate,
        "policyId": manifest.policyId,
        "policyVersion": manifest.policyVersion,
        "policyContentHash": manifest.policyContentHash,
        "totalRequired": len(manifest.questionIds),
        "totalRecorded": len(recorded_ids),
        "pendingCount": len(pending),
        "pending": pending,
        "status": (
            ASSESSMENT_STATUS_COMPLETE
            if not pending
            else ASSESSMENT_STATUS_PENDING
        ),
    }


@dataclass(frozen=True, slots=True)
class G12GateAssessment:
    """Gate evidence for one G12 calibration bundle (decision #13 shape).

    ``status`` is ``pending`` while records are still missing (no statistics
    are computed -- an incomplete collection is never gate evidence),
    ``insufficient`` when the full collection is too small or degenerate to
    produce gate-grade strata, and ``complete`` when the stats layer
    returned sufficient overall coverage.  ``notPermanentDelegation`` is
    always ``True``: no pilot result ever constitutes a permanent
    delegation of authority (decision #13).
    """

    bundleId: str
    manifestId: str
    policyId: str
    policyVersion: str
    policyContentHash: str
    status: str
    sampleSize: int = 0
    notPermanentDelegation: bool = True
    kappa: dict[str, Any] | None = None
    confusionMatrix: dict[str, int] | None = None
    falseAutoApproveUpperBounds: dict[str, float | None] = field(
        default_factory=dict
    )
    strataCoverage: tuple[dict[str, Any], ...] = ()
    approvableStrata: tuple[str, ...] = ()
    activation: dict[str, Any] | None = None
    stratumReport: dict[str, Any] | None = None
    upperBoundMethod: str = DEFAULT_UPPER_BOUND_METHOD
    confidence: float = DEFAULT_CONFIDENCE
    minStratumN: int = PILOT_SAMPLE_SIZE_CEILING
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundleId": self.bundleId,
            "manifestId": self.manifestId,
            "policyId": self.policyId,
            "policyVersion": self.policyVersion,
            "policyContentHash": self.policyContentHash,
            "status": self.status,
            "sampleSize": self.sampleSize,
            "notPermanentDelegation": self.notPermanentDelegation,
            "kappa": self.kappa,
            "confusionMatrix": self.confusionMatrix,
            "falseAutoApproveUpperBounds": dict(self.falseAutoApproveUpperBounds),
            "strataCoverage": [dict(row) for row in self.strataCoverage],
            "approvableStrata": list(self.approvableStrata),
            "activation": self.activation,
            "stratumReport": self.stratumReport,
            "upperBoundMethod": self.upperBoundMethod,
            "confidence": self.confidence,
            "minStratumN": self.minStratumN,
            "notes": list(self.notes),
        }


def assess_bundle(
    bundle: G12CalibrationBundle,
    *,
    min_stratum_n: int = PILOT_SAMPLE_SIZE_CEILING,
    method: str = DEFAULT_UPPER_BOUND_METHOD,
    confidence: float = DEFAULT_CONFIDENCE,
    gate_policy: Mapping[str, Any] | None = None,
) -> G12GateAssessment:
    """Run the calibration statistics + activation gate over a full bundle.

    ``gate_policy`` is the loose dict ``calibration_stats`` reads
    (``maxFalseAutoApproveUpperBound`` / ``minKappa`` /
    ``approvableRiskClasses``); :func:`gate_policy_from_policy` builds it
    from an ``AutoAdvancePolicyV2``.  The false-auto-approve upper bound is
    reported for BOTH frozen methods (the gate itself uses ``method``);
    per-stratum bounds come from the primary-method report.
    """

    if not isinstance(bundle, G12CalibrationBundle):
        raise G12CalibrationServiceError("bundle must be a G12CalibrationBundle")
    if bundle.manifest.gate != G12_GATE:
        raise G12CalibrationServiceError(
            f"bundle manifest gate must be {G12_GATE}; got {bundle.manifest.gate!r}"
        )
    if method not in UPPER_BOUND_METHODS:
        raise G12CalibrationServiceError(
            f"unknown upper bound method {method!r}; expected one of: "
            + ", ".join(UPPER_BOUND_METHODS)
        )
    if (
        isinstance(min_stratum_n, bool)
        or not isinstance(min_stratum_n, int)
        or min_stratum_n < 1
    ):
        raise G12CalibrationServiceError("min_stratum_n must be an integer >= 1")

    def _base(**extra: Any) -> G12GateAssessment:
        return G12GateAssessment(
            bundleId=bundle.bundleId,
            manifestId=bundle.manifestId,
            policyId=bundle.policyId,
            policyVersion=bundle.policyVersion,
            policyContentHash=bundle.policyContentHash,
            minStratumN=min_stratum_n,
            upperBoundMethod=method,
            confidence=confidence,
            **extra,
        )

    if bundle.status != BUNDLE_STATUS_COMPLETE:
        missing = bundle.missing_question_ids()
        return _base(
            status=ASSESSMENT_STATUS_PENDING,
            notes=(
                (
                    f"bundle is {bundle.status}: {len(missing)} of "
                    f"{len(bundle.manifest.questionIds)} manifest questions "
                    "lack judgement records; no gate statistics are computed"
                ),
            ),
        )

    other_method = next(item for item in UPPER_BOUND_METHODS if item != method)
    report = stratum_report(
        bundle.stats_records(),
        min_stratum_n=min_stratum_n,
        method=method,
        confidence=confidence,
    )
    report_other = stratum_report(
        bundle.stats_records(),
        min_stratum_n=min_stratum_n,
        method=other_method,
        confidence=confidence,
    )
    activation = activation_gate_assessment(report, gate_policy)
    overall = report.overall
    coverage_rows = [
        {
            "axis": overall.axis,
            "value": overall.value,
            "sampleSize": overall.sample_size,
            "coverage": overall.coverage,
        }
    ]
    coverage_rows.extend(
        {
            "axis": stratum.axis,
            "value": stratum.value,
            "sampleSize": stratum.sample_size,
            "coverage": stratum.coverage,
        }
        for stratum in report.strata
    )
    notes = list(activation.notes)
    status = ASSESSMENT_STATUS_COMPLETE
    if not overall.sufficient:
        status = ASSESSMENT_STATUS_INSUFFICIENT
        notes.insert(
            0,
            "overall coverage is insufficient: " + "; ".join(overall.insufficient_reasons),
        )
    return _base(
        status=status,
        sampleSize=report.total_sample_size,
        kappa=overall.kappa.as_dict() if overall.kappa is not None else None,
        confusionMatrix=overall.matrix.as_dict(),
        falseAutoApproveUpperBounds={
            method: overall.upper_bound,
            other_method: report_other.overall.upper_bound,
        },
        strataCoverage=tuple(coverage_rows),
        approvableStrata=activation.approvable_strata,
        activation=activation.as_dict(),
        stratumReport=report.as_dict(),
        notes=tuple(notes),
    )


def _policy_identity(
    policy: AutoAdvancePolicyV2 | Mapping[str, Any],
) -> tuple[str, str, str]:
    if isinstance(policy, AutoAdvancePolicyV2):
        return policy.policyId, policy.version, policy.declaredContentHash
    if isinstance(policy, Mapping):
        try:
            return policy_reference(policy)
        except AuditSamplingError as exc:
            raise G12CalibrationServiceError(
                f"policy identity is unusable for activation advice: {exc}"
            ) from exc
    raise G12CalibrationServiceError(
        "policy must be an AutoAdvancePolicyV2 or a policy payload mapping"
    )


def _calibration_gate_view(
    policy: AutoAdvancePolicyV2 | Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Return (calibrationGate mapping view, whether it is a valid mapping)."""

    if isinstance(policy, AutoAdvancePolicyV2):
        return dict(policy.calibrationGate), True
    raw = policy.get("calibrationGate") if isinstance(policy, Mapping) else None
    if isinstance(raw, Mapping):
        return dict(raw), True
    return {}, False


def _declared_thresholds(
    gate: Mapping[str, Any], policy: AutoAdvancePolicyV2 | Mapping[str, Any]
) -> dict[str, Any]:
    """Read the numeric gate thresholds the frozen document may declare."""

    kappa_declaration = gate.get("kappaWithCI")
    minimum_kappa = (
        kappa_declaration.get("minimumKappa")
        if isinstance(kappa_declaration, Mapping)
        else None
    )
    max_bound = gate.get("maxFalseAutoApproveUpperBound")
    if max_bound is None and isinstance(policy, Mapping):
        max_bound = policy.get("maxFalseAutoApproveUpperBound")
    return {
        "minimumKappa": minimum_kappa,
        "maxFalseAutoApproveUpperBound": max_bound,
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def gate_policy_from_policy(
    policy: AutoAdvancePolicyV2 | Mapping[str, Any],
) -> dict[str, Any]:
    """Build the loose ``calibration_stats`` gate dict from a policy document.

    Only explicitly declared numeric thresholds are forwarded; undeclared
    thresholds fall through to the ``calibration_stats`` frozen defaults.
    ``approvableRiskClasses`` is deliberately not derived from
    ``allowedRiskClasses`` -- the two vocabularies differ and the stats
    default (low risk only) stays authoritative unless declared explicitly.
    """

    gate, _ = _calibration_gate_view(policy)
    thresholds = _declared_thresholds(gate, policy)
    loose: dict[str, Any] = {}
    if _is_number(thresholds["minimumKappa"]):
        loose["minKappa"] = float(thresholds["minimumKappa"])
    if _is_number(thresholds["maxFalseAutoApproveUpperBound"]):
        loose["maxFalseAutoApproveUpperBound"] = float(
            thresholds["maxFalseAutoApproveUpperBound"]
        )
    return loose


def policy_activation_advice(
    assessment: G12GateAssessment,
    policy: AutoAdvancePolicyV2 | Mapping[str, Any],
) -> dict[str, Any]:
    """Project which strata this policy could activate under this evidence.

    Thin, read-only projection: it maps the policy's ``calibrationGate``
    fields against a :class:`G12GateAssessment` and reports advisable
    strata plus an explicit gap list.  It never activates anything -- real
    activation still requires the frozen policy contentHash gate
    (decision #12).  Missing ``calibrationGate`` fields are reported with
    the automation-policy contract's own ``missing_calibration_gate_field``
    code and message, so advice gaps read exactly like validator output.
    """

    if not isinstance(assessment, G12GateAssessment):
        raise G12CalibrationServiceError(
            "assessment must be a G12GateAssessment"
        )
    policy_id, version, content_hash = _policy_identity(policy)
    if isinstance(policy, AutoAdvancePolicyV2):
        policy_status = policy.status
        execution_mode = policy.executionMode
        activation_requires = policy.activationRequires
    else:
        policy_status = str(policy.get("status") or "").strip()
        execution_mode = str(policy.get("executionMode") or "").strip()
        activation_requires = str(policy.get("activationRequires") or "").strip()

    gate, gate_is_mapping = _calibration_gate_view(policy)
    gaps: list[dict[str, str]] = []
    gate_field_checks: list[dict[str, Any]] = []
    if not gate_is_mapping:
        gate_field_checks.append(
            {"field": "calibrationGate", "present": False, "code": CODE_MISSING_OR_INVALID}
        )
        gaps.append(
            {
                "code": CODE_MISSING_OR_INVALID,
                "field": "calibrationGate",
                "message": "must be a non-empty object",
            }
        )
    for required in CALIBRATION_GATE_REQUIRED_FIELDS:
        present = required in gate
        gate_field_checks.append(
            {
                "field": f"calibrationGate.{required}",
                "present": present,
                **({} if present else {"code": CODE_MISSING_CALIBRATION_GATE_FIELD}),
            }
        )
        if not present:
            gaps.append(
                {
                    "code": CODE_MISSING_CALIBRATION_GATE_FIELD,
                    "field": f"calibrationGate.{required}",
                    "message": _FIELD_GAP_MESSAGE,
                }
            )
    if execution_mode == "active":
        gaps.append(
            {
                "code": CODE_ACTIVE_MODE_FORBIDDEN_IN_PREVIEW,
                "field": "executionMode",
                "message": (
                    "preview-only validation accepts executionMode=shadow; an "
                    "active automation policy cannot be loaded here"
                ),
            }
        )

    if assessment.status == ASSESSMENT_STATUS_PENDING:
        gaps.append(
            {
                "code": "evidence_pending",
                "field": "bundle",
                "message": (
                    "calibration bundle still lacks judgement records; no "
                    "activation advice is possible yet"
                ),
            }
        )
    elif assessment.status == ASSESSMENT_STATUS_INSUFFICIENT:
        gaps.append(
            {
                "code": "evidence_insufficient",
                "field": "bundle",
                "message": (
                    "calibration evidence is complete but underpowered or "
                    "degenerate; treat every stratum as not approvable"
                ),
            }
        )
    for verdict in (assessment.activation or {}).get("verdicts", []):
        if verdict.get("approvable"):
            continue
        gaps.append(
            {
                "code": "stratum_not_approvable",
                "field": f"stratum:{verdict.get('value', '')}",
                "message": "; ".join(verdict.get("reasons", [])),
            }
        )

    thresholds = _declared_thresholds(gate, policy)
    declared_method = ""
    bound_declaration = gate.get("falseAutoApproveUpperBound")
    if isinstance(bound_declaration, Mapping):
        declared_method = str(bound_declaration.get("method") or "").strip()
    advisable = (
        assessment.status == ASSESSMENT_STATUS_COMPLETE
        and gate_is_mapping
        and not any(
            gap["code"]
            in (CODE_MISSING_CALIBRATION_GATE_FIELD, CODE_MISSING_OR_INVALID)
            for gap in gaps
        )
        and bool(assessment.approvableStrata)
    )
    notes = [
        "advice only: nothing is activated; activation still requires the "
        "frozen policy contentHash gate (decision #12)",
        "no pilot result constitutes a permanent delegation of authority "
        "(decision #13)",
    ]
    if declared_method and declared_method in assessment.falseAutoApproveUpperBounds:
        notes.append(
            f"policy declares false-auto-approve upper bound method "
            f"{declared_method!r}; evidence bound for that method is "
            f"{assessment.falseAutoApproveUpperBounds[declared_method]!r}"
        )
    return {
        "adviceOnly": True,
        "executed": False,
        "policyId": policy_id,
        "policyVersion": version,
        "policyContentHash": content_hash,
        "policyStatus": policy_status,
        "executionMode": execution_mode,
        "activationRequires": activation_requires,
        "bundleId": assessment.bundleId,
        "manifestId": assessment.manifestId,
        "evidenceStatus": assessment.status,
        "advisable": advisable,
        "advisableStrata": list(assessment.approvableStrata),
        "gateFieldChecks": gate_field_checks,
        "declaredThresholds": {
            "minimumKappa": thresholds["minimumKappa"],
            "maxFalseAutoApproveUpperBound": thresholds[
                "maxFalseAutoApproveUpperBound"
            ],
            "falseAutoApproveUpperBoundMethod": declared_method,
        },
        "gateEvidence": {
            "sampleSize": assessment.sampleSize,
            "kappa": assessment.kappa,
            "confusionMatrix": assessment.confusionMatrix,
            "falseAutoApproveUpperBounds": dict(
                assessment.falseAutoApproveUpperBounds
            ),
            "strataCoverage": [dict(row) for row in assessment.strataCoverage],
            "notAPermanentDelegation": assessment.notPermanentDelegation,
        },
        "gaps": gaps,
        "notes": notes,
    }


__all__ = [
    "ASSESSMENT_STATUS_COMPLETE",
    "ASSESSMENT_STATUS_INSUFFICIENT",
    "ASSESSMENT_STATUS_PENDING",
    "G12CalibrationServiceError",
    "G12GateAssessment",
    "G12_GATE",
    "assess_bundle",
    "collect_pending_records",
    "gate_policy_from_policy",
    "policy_activation_advice",
]
