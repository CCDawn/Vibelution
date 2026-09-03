"""Preview-only automation policy contracts (R0.3, not activated).

Two frozen policy documents are described here:

- ``AutoAdvancePolicyV2`` — the capability-matrix automation policy frozen by
  decision #10/#12/#13 of the challenge-cup decision record: five capability
  switches plus bounded parameters, checkpoint/drain semantics, and a
  statistical calibration gate.  Persisted L1/L2/L3 levels are gone; they only
  survive as display-only UI presets.
- ``HumanReviewPolicyV2`` — the minimal mirror of decision #5: G12 full
  review, three rolling drift sentinels, risk-triggered specialty review, and
  manifest-level final approval.

Scope guard: this module validates and hashes policy documents only.  It does
not activate anything, does not subscribe to the canonical command chain, and
does not execute automation.  Two validation stages exist:

- ``stage="preview"`` (default): shadow documents only — an active policy is
  rejected with ``active_mode_forbidden_in_preview``.
- ``stage="activation"``: additionally accepts ``executionMode == "active"``
  but only with the full activation credential recorded fail-closed
  (``status == "approved"`` AND a non-empty ``approval.approvedBy``); this is
  the only stage the executor may load, and passing it still never executes
  anything by itself.  ``executionMode == "shadow"`` here means an
*automation policy shadow* (the policy would run without side effects); it is
unrelated to the ``hypothesis_session_scope_mode`` off/shadow/on session-scope
semantics and the two concepts must not be conflated.

Content hash rule (identical to the challenge-cup policy JSONs): sha256 over
the canonical JSON serialization (``json.dumps`` with ``sort_keys=True``,
``separators=(',', ':')``, ``ensure_ascii=False``) with every ``contentHash``
key set to ``null``, emitted as uppercase hex.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from ._validation import ContractValidationError

AUTO_ADVANCE_POLICY_SCHEMA_VERSION = "2.0.0-preview.1"
HUMAN_REVIEW_POLICY_SCHEMA_VERSION = "2.0.0-preview.1"

# The five decision-#10 capability switches.  Unknown or missing switches are
# rejected fail-closed; every switch is an explicit boolean (no implicit off).
AUTO_ADVANCE_CAPABILITIES: frozenset[str] = frozenset(
    {
        "autoCloseMeetingRound",
        "autoSelectCandidates",
        "autoStartEvidenceRepair",
        "autoConvergeQuestion",
        "autoAdvanceBatchGate",
    }
)

AUTO_ADVANCE_EXECUTION_MODES: frozenset[str] = frozenset({"shadow", "active"})
# Candidate family: plain "candidate" and the "candidate_pending_approval"
# status carried by the real policy candidate documents; "draft" and anything
# else stays rejected (fail-closed, code "unsupported_value").
AUTO_ADVANCE_POLICY_STATUSES: frozenset[str] = frozenset(
    {"candidate", "candidate_pending_approval", "approved"}
)
AUTO_ADVANCE_DRAIN_MODES: frozenset[str] = frozenset(
    {"none", "requested", "draining", "drained"}
)
AUTO_ADVANCE_UI_PRESET_IDS: frozenset[str] = frozenset({"L1", "L2", "L3"})

MAX_AUTO_REVISION_ROUNDS_DEFAULT = 2
MAX_AUTO_REVISION_ROUNDS_ADJUSTABLE_TO = 1

# autoSelectCandidates cost bound: the deterministic selection rule keeps at
# least two candidates (the review comparable-pair floor) and caps the
# auto-selected set so one generation digest cannot fan out an unbounded
# fleet of review meetings. ``selectionRule`` names the deterministic
# ordering the executor must apply and record; ``digest_proposal_order``
# takes the first N ids exactly in the generation digest's
# ``proposedCandidates`` order (no scoring signal exists at that surface).
CANDIDATE_SELECTION_DEFAULT_MAX = 2
CANDIDATE_SELECTION_MIN_MAX = 2
CANDIDATE_SELECTION_RULE_DIGEST_ORDER = "digest_proposal_order"
CANDIDATE_SELECTION_RULES: frozenset[str] = frozenset(
    {CANDIDATE_SELECTION_RULE_DIGEST_ORDER}
)

# Decision #13: kappa >= 0.75 with zero false auto-approvals is calibration
# evidence, never a permanent delegation of authority.
CALIBRATION_GATE_REQUIRED_FIELDS = (
    "confusionMatrix",
    "kappaWithCI",
    "stratifiedBy",
    "falseAutoApproveUpperBound",
    "sequentialSamplingDeclaration",
    "notAPermanentDelegation",
)
FALSE_AUTO_APPROVE_BOUND_METHODS: frozenset[str] = frozenset(
    {"wilson", "beta_binomial"}
)

# Decision #5 minimal mirror for the human review policy.
HUMAN_REVIEW_ROLLING_DRIFT_SENTINELS = 3
HUMAN_REVIEW_FINAL_APPROVAL = "manifest_level"

# ``preview`` keeps the R0.3 fail-closed boundary (shadow documents only).
# ``activation`` is the executor-facing stage: it additionally accepts
# ``executionMode == "active"`` but only when the activation credential is
# recorded fail-closed (status == approved AND approval.approvedBy non-empty).
PolicyStage = Literal["preview", "activation"]

# Activation-stage error codes (fail-closed; active is still rejected unless
# every activation credential is present).
ACTIVE_REQUIRES_APPROVED_STATUS = "active_requires_approved_status"
ACTIVE_REQUIRES_APPROVAL_RECORD = "active_requires_approval_record"

POLICY_CONTENT_HASH_RULE = (
    "sha256 over canonical JSON (sort_keys=True, separators=(',',':'), "
    "ensure_ascii=False) with contentHash set to null; uppercase hex"
)


class AutomationPolicyValidationError(ContractValidationError):
    """A policy document failed fail-closed validation.

    ``errors`` carries structured entries (``code`` / ``field`` / ``message``)
    so callers can surface precise rejection reasons instead of one blob.
    """

    def __init__(self, errors: Sequence[Mapping[str, str]]) -> None:
        self.errors: list[dict[str, str]] = [dict(item) for item in errors]
        summary = "; ".join(
            f"{item.get('code', 'invalid')}[{item.get('field', '')}]: "
            f"{item.get('message', '')}"
            for item in self.errors
        )
        super().__init__(f"automation policy rejected: {summary}")


def _error(code: str, field_name: str, message: str) -> dict[str, str]:
    return {"code": code, "field": field_name, "message": message}


def _collect(
    errors: list[dict[str, str]],
    payload: Mapping[str, Any],
    key: str,
    allowed: frozenset[str] | set[str],
    *,
    label: str,
) -> str:
    value = str(payload.get(key) or "").strip()
    if value not in allowed:
        errors.append(
            _error(
                "unsupported_value",
                key,
                f"{label} must be one of {', '.join(sorted(allowed))}; got {value!r}",
            )
        )
    return value


def _require_text(
    errors: list[dict[str, str]], payload: Mapping[str, Any], key: str
) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        errors.append(_error("missing_or_empty", key, "must be a non-empty string"))
    return value


def _require_mapping(
    errors: list[dict[str, str]],
    payload: Mapping[str, Any],
    key: str,
    *,
    non_empty: bool = True,
) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping) or (non_empty and not value):
        errors.append(
            _error("missing_or_invalid", key, "must be a non-empty object")
        )
        return {}
    return copy.deepcopy(dict(value))


def _require_bool(errors: list[dict[str, str]], mapping: Mapping[str, Any], key: str) -> bool | None:
    value = mapping.get(key)
    if not isinstance(value, bool):
        errors.append(_error("missing_or_invalid", key, "must be a boolean"))
        return None
    return value


def _supersedes(
    errors: list[dict[str, str]], payload: Mapping[str, Any]
) -> dict[str, Any]:
    raw = payload.get("supersedes")
    if not isinstance(raw, Mapping):
        errors.append(
            _error(
                "missing_supersedes",
                "supersedes",
                "a v2 policy must declare the policyId it supersedes",
            )
        )
        return {}
    supersedes = copy.deepcopy(dict(raw))
    if not str(supersedes.get("policyId") or "").strip():
        errors.append(
            _error(
                "missing_supersedes",
                "supersedes.policyId",
                "superseded policyId must be a non-empty string",
            )
        )
    return supersedes


def _declared_content_hash(
    errors: list[dict[str, str]], payload: Mapping[str, Any]
) -> str:
    approval = payload.get("approval")
    raw = approval.get("contentHash") if isinstance(approval, Mapping) else None
    value = str(raw or "").strip()
    if len(value) != 64 or any(char not in "0123456789ABCDEF" for char in value):
        errors.append(
            _error(
                "invalid_content_hash",
                "approval.contentHash",
                "must be an uppercase sha256 hex digest",
            )
        )
        return ""
    return value


def _strip_content_hashes(value: Any) -> Any:
    """Return a deep copy with every ``contentHash`` key set to ``None``."""

    if isinstance(value, Mapping):
        return {
            key: (None if key == "contentHash" else _strip_content_hashes(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_strip_content_hashes(item) for item in value]
    return value


def compute_policy_content_hash(payload: Mapping[str, Any]) -> str:
    """Content hash per the frozen rule: canonical JSON, contentHash nulled."""

    canonical = json.dumps(
        _strip_content_hashes(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()


def verify_policy_content_hash(
    payload: Mapping[str, Any], errors: list[dict[str, str]]
) -> str:
    """Recompute the content hash and compare against the declared value."""

    declared = _declared_content_hash(errors, payload)
    if not declared:
        return ""
    computed = compute_policy_content_hash(payload)
    if computed != declared:
        errors.append(
            _error(
                "content_hash_mismatch",
                "approval.contentHash",
                f"declared {declared} does not match recomputed {computed}",
            )
        )
    return declared


def _validated_status_and_mode(
    errors: list[dict[str, str]],
    payload: Mapping[str, Any],
    *,
    stage: PolicyStage,
) -> tuple[str, str]:
    if stage not in ("preview", "activation"):
        errors.append(
            _error(
                "unsupported_stage",
                "stage",
                "only preview and activation validation is implemented",
            )
        )
    status = _collect(
        errors,
        payload,
        "status",
        AUTO_ADVANCE_POLICY_STATUSES,
        label="status",
    )
    execution_mode = _collect(
        errors,
        payload,
        "executionMode",
        AUTO_ADVANCE_EXECUTION_MODES,
        label="executionMode",
    )
    if execution_mode == "active":
        if stage == "preview":
            # Preview stage accepts shadow only.  There is deliberately no
            # activation path in this contract layer for preview (R0.3
            # preview-only).
            errors.append(
                _error(
                    "active_mode_forbidden_in_preview",
                    "executionMode",
                    "preview-only validation accepts executionMode=shadow; an "
                    "active automation policy cannot be loaded here",
                )
            )
        else:
            # Activation stage: the active credential is fail-closed checked
            # here so an unapproved or unattributed document can never be
            # loaded for execution.
            if status != "approved":
                errors.append(
                    _error(
                        ACTIVE_REQUIRES_APPROVED_STATUS,
                        "status",
                        "an active automation policy requires "
                        "status=approved; got "
                        f"{status!r}",
                    )
                )
            approval = payload.get("approval")
            approvers = (
                approval.get("approvedBy") if isinstance(approval, Mapping) else None
            )
            has_record = isinstance(approvers, list) and bool(approvers) and all(
                isinstance(item, str) and item.strip() for item in approvers
            )
            if not has_record:
                errors.append(
                    _error(
                        ACTIVE_REQUIRES_APPROVAL_RECORD,
                        "approval.approvedBy",
                        "an active automation policy requires a non-empty "
                        "list of recorded approvers (explicit approval "
                        "against policyId + version + contentHash)",
                    )
                )
    return status, execution_mode


def _validated_capabilities(
    errors: list[dict[str, str]], payload: Mapping[str, Any]
) -> dict[str, bool]:
    raw = payload.get("capabilities")
    if not isinstance(raw, Mapping):
        errors.append(
            _error(
                "missing_or_invalid",
                "capabilities",
                "must be an object with exactly the five capability switches",
            )
        )
        return {}
    unknown = sorted(set(raw) - AUTO_ADVANCE_CAPABILITIES)
    if unknown:
        errors.append(
            _error(
                "unknown_capability",
                "capabilities",
                "unknown capability switches: " + ", ".join(unknown),
            )
        )
    missing = sorted(AUTO_ADVANCE_CAPABILITIES - set(raw))
    if missing:
        errors.append(
            _error(
                "missing_capability",
                "capabilities",
                "missing capability switches: " + ", ".join(missing),
            )
        )
    capabilities: dict[str, bool] = {}
    for name in sorted(AUTO_ADVANCE_CAPABILITIES):
        value = raw.get(name)
        if not isinstance(value, bool):
            if name in raw:
                errors.append(
                    _error(
                        "invalid_capability_value",
                        f"capabilities.{name}",
                        "must be a boolean",
                    )
                )
            continue
        capabilities[name] = value
    return capabilities


def _validated_calibration_gate(
    errors: list[dict[str, str]], payload: Mapping[str, Any]
) -> dict[str, Any]:
    gate = _require_mapping(errors, payload, "calibrationGate")
    if not gate:
        return gate
    for required in CALIBRATION_GATE_REQUIRED_FIELDS:
        if required not in gate:
            errors.append(
                _error(
                    "missing_calibration_gate_field",
                    f"calibrationGate.{required}",
                    "statistical calibration gate field is required (decision #13)",
                )
            )
    confusion_matrix = gate.get("confusionMatrix")
    if "confusionMatrix" in gate and not isinstance(confusion_matrix, Mapping):
        errors.append(
            _error(
                "invalid_calibration_gate_field",
                "calibrationGate.confusionMatrix",
                "must be an object declaring auto-advance vs human-review axes",
            )
        )
    kappa = gate.get("kappaWithCI")
    if "kappaWithCI" in gate and not isinstance(kappa, Mapping):
        errors.append(
            _error(
                "invalid_calibration_gate_field",
                "calibrationGate.kappaWithCI",
                "must be an object declaring Cohen's kappa with a CI",
            )
        )
    stratified_by = gate.get("stratifiedBy")
    if "stratifiedBy" in gate:
        if not isinstance(stratified_by, list) or not stratified_by:
            errors.append(
                _error(
                    "invalid_calibration_gate_field",
                    "calibrationGate.stratifiedBy",
                    "must be a non-empty list of stratification axes",
                )
            )
        else:
            axes = {str(axis).lower() for axis in stratified_by}
            if not any("risk" in axis for axis in axes) or not any(
                "domain" in axis for axis in axes
            ):
                errors.append(
                    _error(
                        "invalid_calibration_gate_field",
                        "calibrationGate.stratifiedBy",
                        "must stratify by both risk and domain",
                    )
                )
    bound = gate.get("falseAutoApproveUpperBound")
    if "falseAutoApproveUpperBound" in gate:
        if not isinstance(bound, Mapping):
            errors.append(
                _error(
                    "invalid_calibration_gate_field",
                    "calibrationGate.falseAutoApproveUpperBound",
                    "must be an object declaring the upper-bound method",
                )
            )
        else:
            method = str(bound.get("method") or "")
            if method not in FALSE_AUTO_APPROVE_BOUND_METHODS:
                errors.append(
                    _error(
                        "invalid_calibration_gate_field",
                        "calibrationGate.falseAutoApproveUpperBound.method",
                        "must be one of: "
                        + ", ".join(sorted(FALSE_AUTO_APPROVE_BOUND_METHODS)),
                    )
                )
            if str(bound.get("side") or "") != "one_sided_upper":
                errors.append(
                    _error(
                        "invalid_calibration_gate_field",
                        "calibrationGate.falseAutoApproveUpperBound.side",
                        "must declare a one-sided upper bound",
                    )
                )
    if gate.get("notAPermanentDelegation") is not True:
        errors.append(
            _error(
                "invalid_calibration_gate_field",
                "calibrationGate.notAPermanentDelegation",
                "must be true: passing the gate never constitutes permanent "
                "delegation (decision #13)",
            )
        )
    return gate


def _validated_candidate_selection(
    errors: list[dict[str, str]], payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate the optional bounded candidateSelection parameters.

    Absent means the frozen default (``maxSelected`` = 2,
    ``selectionRule`` = ``digest_proposal_order``) so existing documents
    stay valid; present it must be an object with an integer
    ``maxSelected`` >= the review comparable-pair floor and, when
    declared, a known deterministic ``selectionRule``.
    """

    default = {
        "maxSelected": CANDIDATE_SELECTION_DEFAULT_MAX,
        "selectionRule": CANDIDATE_SELECTION_RULE_DIGEST_ORDER,
    }
    raw = payload.get("candidateSelection")
    if raw is None:
        return default
    if not isinstance(raw, Mapping):
        errors.append(
            _error(
                "missing_or_invalid",
                "candidateSelection",
                "must be an object when present",
            )
        )
        return default
    max_selected = raw.get("maxSelected")
    if (
        isinstance(max_selected, bool)
        or not isinstance(max_selected, int)
        or max_selected < CANDIDATE_SELECTION_MIN_MAX
    ):
        errors.append(
            _error(
                "unsupported_value",
                "candidateSelection.maxSelected",
                "must be an integer >= "
                f"{CANDIDATE_SELECTION_MIN_MAX} (the review comparable-pair "
                "floor)",
            )
        )
        max_selected = CANDIDATE_SELECTION_DEFAULT_MAX
    rule = str(
        raw.get("selectionRule") or CANDIDATE_SELECTION_RULE_DIGEST_ORDER
    ).strip()
    if rule not in CANDIDATE_SELECTION_RULES:
        errors.append(
            _error(
                "unsupported_value",
                "candidateSelection.selectionRule",
                "must be one of: " + ", ".join(sorted(CANDIDATE_SELECTION_RULES)),
            )
        )
        rule = CANDIDATE_SELECTION_RULE_DIGEST_ORDER
    return {"maxSelected": max_selected, "selectionRule": rule}


def _validated_ui_presets(
    errors: list[dict[str, str]], payload: Mapping[str, Any]
) -> dict[str, Any]:
    """UI presets are display-only; they never carry authoritative capability truth."""

    raw = payload.get("uiPresets")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        errors.append(
            _error(
                "invalid_ui_presets",
                "uiPresets",
                "must be an object keyed by L1/L2/L3",
            )
        )
        return {}
    presets = copy.deepcopy(dict(raw))
    for preset_id, preset in presets.items():
        if preset_id not in AUTO_ADVANCE_UI_PRESET_IDS:
            errors.append(
                _error(
                    "invalid_ui_preset",
                    f"uiPresets.{preset_id}",
                    "preset ids are limited to L1/L2/L3 (decision #10: presets "
                    "are display-only, not persisted truth)",
                )
            )
            continue
        if not isinstance(preset, Mapping):
            errors.append(
                _error(
                    "invalid_ui_preset",
                    f"uiPresets.{preset_id}",
                    "preset must be an object",
                )
            )
            continue
        if preset.get("displayOnly") is not True:
            errors.append(
                _error(
                    "invalid_ui_preset",
                    f"uiPresets.{preset_id}.displayOnly",
                    "every preset must declare displayOnly=true",
                )
            )
        if "capabilities" in preset:
            errors.append(
                _error(
                    "invalid_ui_preset",
                    f"uiPresets.{preset_id}.capabilities",
                    "presets must not carry an authoritative capabilities key; "
                    "use displayCapabilities for UI hints",
                )
            )
    return presets


@dataclass(frozen=True, slots=True)
class AutoAdvancePolicyV2:
    """Capability-matrix auto-advance policy (decision #10/#12/#13).

    ``executionMode`` uses the automation-policy meaning: ``shadow`` marks a
    policy that is validated/previewed without side effects, ``active`` marks
    one that would act.  This is unrelated to the ``off/shadow/on`` session
    scope modes in ``hypothesis_session_scope_mode``.
    """

    policyId: str
    version: str
    status: str
    executionMode: str
    schemaVersion: str
    capabilities: dict[str, bool]
    maxRevisionRounds: int
    maxRevisionRoundsAdjustableTo: int
    allowedRiskClasses: list[str]
    effectiveFromCheckpoint: str | None
    drainMode: str
    calibrationGate: dict[str, Any]
    uiPresets: dict[str, Any]
    supersedes: dict[str, Any]
    activationRequires: str
    declaredContentHash: str
    contentHashRule: str = POLICY_CONTENT_HASH_RULE
    # Optional bounded selection parameters; defaulted (never None) so the
    # executor can always read a concrete cap.  Sits after the defaulted
    # contentHashRule to keep direct keyword constructions compatible.
    candidateSelection: dict[str, Any] = field(
        default_factory=lambda: {
            "maxSelected": CANDIDATE_SELECTION_DEFAULT_MAX,
            "selectionRule": CANDIDATE_SELECTION_RULE_DIGEST_ORDER,
        }
    )
    previewStageOnly: Literal["preview"] = field(
        default="preview", init=False
    )

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, stage: PolicyStage = "preview"
    ) -> AutoAdvancePolicyV2:
        errors: list[dict[str, str]] = []
        policy_id = _require_text(errors, payload, "policyId")
        version = _require_text(errors, payload, "version")
        _require_text(errors, payload, "schemaVersion")
        status, execution_mode = _validated_status_and_mode(
            errors, payload, stage=stage
        )
        supersedes = _supersedes(errors, payload)
        declared_hash = verify_policy_content_hash(payload, errors)
        capabilities = _validated_capabilities(errors, payload)
        calibration_gate = _validated_calibration_gate(errors, payload)
        candidate_selection = _validated_candidate_selection(errors, payload)
        ui_presets = _validated_ui_presets(errors, payload)

        activation_requires = str(payload.get("activationRequires") or "").strip()
        if not activation_requires:
            errors.append(
                _error(
                    "missing_or_empty",
                    "activationRequires",
                    "must declare what activation requires",
                )
            )

        drain_mode = _collect(
            errors, payload, "drainMode", AUTO_ADVANCE_DRAIN_MODES, label="drainMode"
        )

        raw_rounds = payload.get("maxRevisionRounds")
        if isinstance(raw_rounds, bool) or not isinstance(raw_rounds, int):
            errors.append(
                _error(
                    "missing_or_invalid",
                    "maxRevisionRounds",
                    "must be an integer (decision #3: default 2, adjustable to 1)",
                )
            )
            max_revision_rounds = 0
        else:
            max_revision_rounds = raw_rounds
            if not 1 <= raw_rounds <= MAX_AUTO_REVISION_ROUNDS_DEFAULT:
                errors.append(
                    _error(
                        "unsupported_value",
                        "maxRevisionRounds",
                        "must be between 1 and "
                        f"{MAX_AUTO_REVISION_ROUNDS_DEFAULT} (decision #3)",
                    )
                )
        raw_adjustable = payload.get("maxRevisionRoundsAdjustableTo")
        if isinstance(raw_adjustable, bool) or not isinstance(
            raw_adjustable, int
        ):
            errors.append(
                _error(
                    "missing_or_invalid",
                    "maxRevisionRoundsAdjustableTo",
                    "must be an integer",
                )
            )
            max_adjustable = 0
        else:
            max_adjustable = raw_adjustable
            if raw_adjustable < MAX_AUTO_REVISION_ROUNDS_ADJUSTABLE_TO:
                errors.append(
                    _error(
                        "unsupported_value",
                        "maxRevisionRoundsAdjustableTo",
                        "must be at least "
                        f"{MAX_AUTO_REVISION_ROUNDS_ADJUSTABLE_TO} (decision #3)",
                    )
                )

        allowed_risk_classes = payload.get("allowedRiskClasses")
        if (
            not isinstance(allowed_risk_classes, list)
            or not allowed_risk_classes
            or not all(
                isinstance(item, str) and item.strip()
                for item in allowed_risk_classes
            )
        ):
            errors.append(
                _error(
                    "missing_or_invalid",
                    "allowedRiskClasses",
                    "must be a non-empty list of risk class names",
                )
            )
            allowed_risk_classes = []

        checkpoint = payload.get("effectiveFromCheckpoint")
        if checkpoint is not None and not (
            isinstance(checkpoint, str) and checkpoint.strip()
        ):
            errors.append(
                _error(
                    "invalid_checkpoint",
                    "effectiveFromCheckpoint",
                    "must be a non-empty string or null",
                )
            )
            checkpoint = None

        if errors:
            raise AutomationPolicyValidationError(errors)

        return cls(
            policyId=policy_id,
            version=version,
            status=status,
            executionMode=execution_mode,
            schemaVersion=str(payload["schemaVersion"]),
            capabilities=capabilities,
            maxRevisionRounds=max_revision_rounds,
            maxRevisionRoundsAdjustableTo=max_adjustable,
            allowedRiskClasses=list(allowed_risk_classes),
            effectiveFromCheckpoint=checkpoint,
            drainMode=drain_mode,
            calibrationGate=calibration_gate,
            candidateSelection=candidate_selection,
            uiPresets=ui_presets,
            supersedes=supersedes,
            activationRequires=activation_requires,
            declaredContentHash=declared_hash,
        )

    @property
    def enabled_capabilities(self) -> tuple[str, ...]:
        """Sorted names of the switches currently set to ``True``."""

        return tuple(sorted(name for name, on in self.capabilities.items() if on))

    def to_dict(self) -> dict[str, Any]:
        return {
            "policyId": self.policyId,
            "version": self.version,
            "status": self.status,
            "executionMode": self.executionMode,
            "schemaVersion": self.schemaVersion,
            "capabilities": dict(self.capabilities),
            "maxRevisionRounds": self.maxRevisionRounds,
            "maxRevisionRoundsAdjustableTo": self.maxRevisionRoundsAdjustableTo,
            "allowedRiskClasses": list(self.allowedRiskClasses),
            "effectiveFromCheckpoint": self.effectiveFromCheckpoint,
            "drainMode": self.drainMode,
            "calibrationGate": copy.deepcopy(self.calibrationGate),
            "candidateSelection": copy.deepcopy(self.candidateSelection),
            "uiPresets": copy.deepcopy(self.uiPresets),
            "supersedes": copy.deepcopy(self.supersedes),
            "activationRequires": self.activationRequires,
            "declaredContentHash": self.declaredContentHash,
            "contentHashRule": self.contentHashRule,
        }


@dataclass(frozen=True, slots=True)
class HumanReviewPolicyV2:
    """Minimal mirror of the decision-#5 human review policy.

    Enforces the frozen review shape: G12 full review, exactly three rolling
    drift sentinels, risk-triggered (never class-wide) specialty review, and
    manifest-level final approval.
    """

    policyId: str
    version: str
    status: str
    schemaVersion: str
    gateCalibration: dict[str, Any]
    rollingDriftSentinels: int
    specialtyReviewRule: str
    finalApproval: str
    mandatoryExceptionReview: list[str]
    calibrationMetrics: dict[str, Any]
    supersedes: dict[str, Any]
    declaredContentHash: str
    contentHashRule: str = POLICY_CONTENT_HASH_RULE

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, stage: PolicyStage = "preview"
    ) -> HumanReviewPolicyV2:
        if stage != "preview":
            raise AutomationPolicyValidationError(
                [
                    _error(
                        "unsupported_stage",
                        "stage",
                        "only preview validation is implemented (R0.3 is "
                        "preview-only)",
                    )
                ]
            )
        errors: list[dict[str, str]] = []
        policy_id = _require_text(errors, payload, "policyId")
        version = _require_text(errors, payload, "version")
        _require_text(errors, payload, "schemaVersion")
        status = _collect(
            errors,
            payload,
            "status",
            AUTO_ADVANCE_POLICY_STATUSES,
            label="status",
        )
        supersedes = _supersedes(errors, payload)
        declared_hash = verify_policy_content_hash(payload, errors)

        gate_calibration = _require_mapping(errors, payload, "gateCalibration")
        if gate_calibration:
            g12 = str(gate_calibration.get("G12") or "")
            if not g12.startswith("review_all"):
                errors.append(
                    _error(
                        "invalid_gate_calibration",
                        "gateCalibration.G12",
                        "G12 must be a full review declaration (decision #5)",
                    )
                )

        sentinels_raw = payload.get("rollingDriftSentinels")
        sampling = payload.get("postG12LowRiskSampling")
        nested_sentinels = (
            sampling.get("rollingDriftSentinels")
            if isinstance(sampling, Mapping)
            else None
        )
        if sentinels_raw is None and nested_sentinels is not None:
            # The reference candidate document nests the sentinel count under
            # postG12LowRiskSampling; accept either location.
            sentinels_raw = nested_sentinels
        elif (
            sentinels_raw is not None
            and nested_sentinels is not None
            and sentinels_raw != nested_sentinels
        ):
            errors.append(
                _error(
                    "conflicting_sentinel_count",
                    "rollingDriftSentinels",
                    "top-level and postG12LowRiskSampling values disagree",
                )
            )
        sentinels = sentinels_raw
        if isinstance(sentinels, bool) or not isinstance(sentinels, int):
            errors.append(
                _error(
                    "missing_or_invalid",
                    "rollingDriftSentinels",
                    "must be an integer",
                )
            )
        elif sentinels != HUMAN_REVIEW_ROLLING_DRIFT_SENTINELS:
            errors.append(
                _error(
                    "unsupported_value",
                    "rollingDriftSentinels",
                    "must be exactly "
                    f"{HUMAN_REVIEW_ROLLING_DRIFT_SENTINELS} (decision record 3.1)",
                )
            )

        specialty_rule = str(payload.get("specialtyReviewRule") or "").strip()
        if "risk_triggered" not in specialty_rule:
            errors.append(
                _error(
                    "invalid_specialty_rule",
                    "specialtyReviewRule",
                    "specialty review must be risk-triggered, never class-wide "
                    "(decision #6)",
                )
            )

        final_approval = str(payload.get("finalApproval") or "").strip()
        if final_approval != HUMAN_REVIEW_FINAL_APPROVAL:
            errors.append(
                _error(
                    "unsupported_value",
                    "finalApproval",
                    f"must be {HUMAN_REVIEW_FINAL_APPROVAL} (decision #5)",
                )
            )

        exceptions = payload.get("mandatoryExceptionReview")
        if not isinstance(exceptions, list) or not exceptions:
            errors.append(
                _error(
                    "missing_or_invalid",
                    "mandatoryExceptionReview",
                    "must be a non-empty list of mandatory review exceptions",
                )
            )
            exceptions = []
        elif "auto_revision_exhausted" not in exceptions:
            errors.append(
                _error(
                    "missing_exception",
                    "mandatoryExceptionReview",
                    "auto_revision_exhausted is a mandatory exception (decision #3)",
                )
            )

        calibration_metrics = _require_mapping(
            errors, payload, "calibrationMetrics"
        )
        if calibration_metrics:
            if (
                str(calibration_metrics.get("agreementMeasure") or "")
                != "cohens_kappa"
            ):
                errors.append(
                    _error(
                        "invalid_calibration_metric",
                        "calibrationMetrics.agreementMeasure",
                        "must be cohens_kappa (decision #13)",
                    )
                )
            if not str(
                calibration_metrics.get("falseAutoApproveDefinition") or ""
            ).strip():
                errors.append(
                    _error(
                        "missing_or_empty",
                        "calibrationMetrics.falseAutoApproveDefinition",
                        "must define what counts as a false auto-approval",
                    )
                )

        if errors:
            raise AutomationPolicyValidationError(errors)

        return cls(
            policyId=policy_id,
            version=version,
            status=status,
            schemaVersion=str(payload["schemaVersion"]),
            gateCalibration=gate_calibration,
            rollingDriftSentinels=sentinels,
            specialtyReviewRule=specialty_rule,
            finalApproval=final_approval,
            mandatoryExceptionReview=list(exceptions),
            calibrationMetrics=calibration_metrics,
            supersedes=supersedes,
            declaredContentHash=declared_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policyId": self.policyId,
            "version": self.version,
            "status": self.status,
            "schemaVersion": self.schemaVersion,
            "gateCalibration": copy.deepcopy(self.gateCalibration),
            "rollingDriftSentinels": self.rollingDriftSentinels,
            "specialtyReviewRule": self.specialtyReviewRule,
            "finalApproval": self.finalApproval,
            "mandatoryExceptionReview": list(self.mandatoryExceptionReview),
            "calibrationMetrics": copy.deepcopy(self.calibrationMetrics),
            "supersedes": copy.deepcopy(self.supersedes),
            "declaredContentHash": self.declaredContentHash,
            "contentHashRule": self.contentHashRule,
        }


__all__ = [
    "ACTIVE_REQUIRES_APPROVAL_RECORD",
    "ACTIVE_REQUIRES_APPROVED_STATUS",
    "AUTO_ADVANCE_CAPABILITIES",
    "AUTO_ADVANCE_DRAIN_MODES",
    "AUTO_ADVANCE_EXECUTION_MODES",
    "AUTO_ADVANCE_POLICY_SCHEMA_VERSION",
    "AUTO_ADVANCE_POLICY_STATUSES",
    "AUTO_ADVANCE_UI_PRESET_IDS",
    "CALIBRATION_GATE_REQUIRED_FIELDS",
    "CANDIDATE_SELECTION_DEFAULT_MAX",
    "CANDIDATE_SELECTION_MIN_MAX",
    "CANDIDATE_SELECTION_RULES",
    "CANDIDATE_SELECTION_RULE_DIGEST_ORDER",
    "FALSE_AUTO_APPROVE_BOUND_METHODS",
    "HUMAN_REVIEW_POLICY_SCHEMA_VERSION",
    "HUMAN_REVIEW_ROLLING_DRIFT_SENTINELS",
    "MAX_AUTO_REVISION_ROUNDS_ADJUSTABLE_TO",
    "MAX_AUTO_REVISION_ROUNDS_DEFAULT",
    "AutoAdvancePolicyV2",
    "AutomationPolicyValidationError",
    "HumanReviewPolicyV2",
    "POLICY_CONTENT_HASH_RULE",
    "compute_policy_content_hash",
    "verify_policy_content_hash",
]
