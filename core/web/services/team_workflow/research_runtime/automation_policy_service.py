"""Preview/activation load/validate/hash/preview service for automation policies.

R0.3 boundary (challenge-cup decision record, decisions #10/#12/#13): this
service loads policy documents, recomputes and verifies their content hash,
validates them fail-closed, and renders a *static* preview snapshot of what
activation would change.  It never activates a policy and never executes an
automation decision itself; the gated execution path lives in
``automation_policy_executor`` (safety ladder + audit), which uses the
``stage="activation"`` loader for approved active documents.

Hash-chain style mirrors the catalog model-policy chain
(``model_routing.resolve_catalog_model_policy`` feeding
``catalog_run_authorization.model_policy_sha256``): a document is trusted only
after its declared hash matches a freshly recomputed one, and any mismatch is
a typed fail-closed error.

Naming note: ``executionMode`` here is the automation-policy shadow/active
switch (shadow = validated and previewed without side effects).  It is
unrelated to the ``off/shadow/on`` session-scope modes of
``hypothesis_session_scope_mode``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.research.workflow.contracts.automation_policy import (
    AUTO_ADVANCE_CAPABILITIES,
    AutoAdvancePolicyV2,
    AutomationPolicyValidationError,
    HumanReviewPolicyV2,
    verify_policy_content_hash,
)

CAPABILITY_DESCRIPTIONS: dict[str, str] = {
    "autoCloseMeetingRound": "close a meeting round automatically when its hard gates pass",
    "autoSelectCandidates": "select finalists automatically inside the bounded draft/screen flow",
    "autoStartEvidenceRepair": "start an evidence repair pass automatically on detected gaps",
    "autoConvergeQuestion": "converge a question automatically when all hard gates pass",
    "autoAdvanceBatchGate": "advance a batch gate automatically between questions",
}

DRAIN_MODE_DESCRIPTIONS: dict[str, str] = {
    "none": "no drain: policy applies only from the declared checkpoint onward",
    "requested": "a policy switch has been requested; new work uses the new generation",
    "draining": "in-flight rounds are finishing under the old generation",
    "drained": "all in-flight rounds finished; the new generation is authoritative",
}


class AutomationPolicyServiceError(ValueError):
    """Typed fail-closed error for automation policy handling."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def load_policy_document(path: Path | str) -> dict[str, Any]:
    """Load a policy JSON document from disk, failing closed on any error."""

    resolved = Path(path)
    try:
        raw_text = resolved.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AutomationPolicyServiceError(
            f"policy document not found: {resolved}", code="policy_file_missing"
        ) from exc
    except OSError as exc:
        raise AutomationPolicyServiceError(
            f"policy document unreadable: {resolved}: {exc}",
            code="policy_file_unreadable",
        ) from exc
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AutomationPolicyServiceError(
            f"policy document is not valid JSON: {resolved}: {exc}",
            code="policy_json_invalid",
        ) from exc
    if not isinstance(payload, dict):
        raise AutomationPolicyServiceError(
            f"policy document must be a JSON object: {resolved}",
            code="policy_json_invalid",
        )
    return payload


def compute_and_verify_content_hash(payload: Mapping[str, Any]) -> str:
    """Recompute the document hash and compare it with the declared value."""

    errors: list[dict[str, str]] = []
    declared = verify_policy_content_hash(payload, errors)
    if errors:
        if any(item.get("code") == "content_hash_mismatch" for item in errors):
            raise AutomationPolicyServiceError(
                "; ".join(item.get("message", "") for item in errors),
                code="content_hash_mismatch",
            )
        raise AutomationPolicyServiceError(
            "; ".join(item.get("message", "") for item in errors),
            code="policy_hash_unverifiable",
        )
    return declared


def validate_auto_advance_policy_v2(
    payload: Mapping[str, Any],
    *,
    stage: str = "preview",
) -> AutoAdvancePolicyV2:
    """Validate an AutoAdvancePolicyV2 document.

    ``stage="preview"`` (default) keeps the R0.3 boundary: shadow documents
    only.  ``stage="activation"`` additionally accepts an active policy whose
    activation credential (status=approved + approval.approvedBy) is recorded
    fail-closed; validation itself still never executes anything.
    """

    try:
        return AutoAdvancePolicyV2.from_dict(dict(payload), stage=stage)
    except AutomationPolicyValidationError as exc:
        raise _service_validation_error(exc) from exc


def validate_human_review_policy_v2(
    payload: Mapping[str, Any],
) -> HumanReviewPolicyV2:
    """Validate a HumanReviewPolicyV2 document; preview stage only."""

    try:
        return HumanReviewPolicyV2.from_dict(dict(payload), stage="preview")
    except AutomationPolicyValidationError as exc:
        raise _service_validation_error(exc) from exc


def _service_validation_error(
    exc: AutomationPolicyValidationError,
) -> AutomationPolicyServiceError:
    codes = {item.get("code") for item in exc.errors}
    if "content_hash_mismatch" in codes:
        code = "content_hash_mismatch"
    elif "active_mode_forbidden_in_preview" in codes:
        code = "active_mode_forbidden_in_preview"
    else:
        code = "policy_validation_failed"
    return AutomationPolicyServiceError(str(exc), code=code)


def load_auto_advance_policy_v2(
    path: Path | str,
    *,
    stage: str = "preview",
) -> AutoAdvancePolicyV2:
    """Load, hash-verify and validate an AutoAdvancePolicyV2 document."""

    payload = load_policy_document(path)
    compute_and_verify_content_hash(payload)
    return validate_auto_advance_policy_v2(payload, stage=stage)


def load_auto_advance_policy_v2_document(
    path: Path | str,
    *,
    stage: str = "preview",
) -> tuple[AutoAdvancePolicyV2, dict[str, Any]]:
    """Load + validate and also return the raw verified payload.

    The executor needs the raw ``approval.approvedBy`` credential, which the
    frozen ``AutoAdvancePolicyV2`` dataclass intentionally does not carry.
    The hash is verified exactly once for both views of the document.
    """

    payload = load_policy_document(path)
    compute_and_verify_content_hash(payload)
    return validate_auto_advance_policy_v2(payload, stage=stage), payload


def load_human_review_policy_v2(path: Path | str) -> HumanReviewPolicyV2:
    """Load, hash-verify and validate a HumanReviewPolicyV2 document."""

    payload = load_policy_document(path)
    compute_and_verify_content_hash(payload)
    return validate_human_review_policy_v2(payload)


def preview_auto_advance_policy_v2(
    payload_or_policy: Mapping[str, Any] | AutoAdvancePolicyV2,
) -> dict[str, Any]:
    """Render the static preview snapshot: what activation would change.

    The snapshot is descriptive only.  ``executed`` is always ``False``; no
    capability is engaged, no checkpoint is forked, and no command is emitted.
    """

    policy = (
        payload_or_policy
        if isinstance(payload_or_policy, AutoAdvancePolicyV2)
        else validate_auto_advance_policy_v2(payload_or_policy)
    )
    capability_states = {
        name: {
            "enabledInPolicy": policy.capabilities.get(name, False),
            "description": CAPABILITY_DESCRIPTIONS[name],
        }
        for name in sorted(AUTO_ADVANCE_CAPABILITIES)
    }
    return {
        "previewOnly": True,
        "executed": False,
        "policyId": policy.policyId,
        "version": policy.version,
        "status": policy.status,
        "executionMode": policy.executionMode,
        "contentHash": policy.declaredContentHash,
        "wouldChangeIfActivated": {
            "capabilityStates": capability_states,
            "enabledCapabilities": list(policy.enabled_capabilities),
            "maxRevisionRounds": policy.maxRevisionRounds,
            "maxRevisionRoundsAdjustableTo": policy.maxRevisionRoundsAdjustableTo,
            "allowedRiskClasses": list(policy.allowedRiskClasses),
            "effectiveFromCheckpoint": policy.effectiveFromCheckpoint,
            "drainMode": policy.drainMode,
            "drainModeDescription": DRAIN_MODE_DESCRIPTIONS.get(
                policy.drainMode, ""
            ),
            "supersedes": dict(policy.supersedes),
            "calibrationGateSummary": {
                "notAPermanentDelegation": policy.calibrationGate.get(
                    "notAPermanentDelegation"
                ),
                "stratifiedBy": policy.calibrationGate.get("stratifiedBy"),
                "falseAutoApproveUpperBoundMethod": (
                    policy.calibrationGate.get("falseAutoApproveUpperBound")
                    or {}
                ).get("method"),
            },
            "activationRequires": policy.activationRequires,
            "uiPresetsDisplayOnly": sorted(policy.uiPresets),
        },
        "notes": [
            "preview snapshot only: nothing is activated and no side effect occurs",
            "policy hash change starts a new checkpoint generation or fork "
            "(decision #12: checkpoint + drain, no immediate residue-free downgrade)",
            "executionMode=shadow is the automation-policy preview mode, not the "
            "hypothesis session-scope shadow semantics",
        ],
    }


def preview_human_review_policy_v2(
    payload_or_policy: Mapping[str, Any] | HumanReviewPolicyV2,
) -> dict[str, Any]:
    """Render the static preview snapshot for the human review policy mirror."""

    policy = (
        payload_or_policy
        if isinstance(payload_or_policy, HumanReviewPolicyV2)
        else validate_human_review_policy_v2(payload_or_policy)
    )
    return {
        "previewOnly": True,
        "executed": False,
        "policyId": policy.policyId,
        "version": policy.version,
        "status": policy.status,
        "contentHash": policy.declaredContentHash,
        "wouldChangeIfActivated": {
            "gateCalibration": dict(policy.gateCalibration),
            "rollingDriftSentinels": policy.rollingDriftSentinels,
            "specialtyReviewRule": policy.specialtyReviewRule,
            "finalApproval": policy.finalApproval,
            "mandatoryExceptionReview": list(policy.mandatoryExceptionReview),
            "supersedes": dict(policy.supersedes),
        },
        "notes": [
            "preview snapshot only: the current 36-question review baseline "
            "remains binding until this policy is frozen and explicitly approved",
        ],
    }


__all__ = [
    "AutomationPolicyServiceError",
    "compute_and_verify_content_hash",
    "load_auto_advance_policy_v2",
    "load_auto_advance_policy_v2_document",
    "load_human_review_policy_v2",
    "load_policy_document",
    "preview_auto_advance_policy_v2",
    "preview_human_review_policy_v2",
    "validate_auto_advance_policy_v2",
    "validate_human_review_policy_v2",
]
