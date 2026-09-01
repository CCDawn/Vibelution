"""Fail-closed evidence authority for Challenge Cup node-7 termination."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from core.research.competition.stage_one_completion_policy import (
    StageOneCompletionPolicy,
    StageOneCompletionPolicyError,
)
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)
from core.research.workflow.definition_registry import (
    WorkflowDefinitionRegistryError,
    resolve_definition_for_run_record,
)
from core.research.workflow.stage_one_completion import (
    STAGE_ONE_ACCEPTED_STATE,
    STAGE_ONE_CHECKPOINT_FIELD,
    route_after_stage_one_closure,
)

from .node_execution_support import NodeExecutionError

STAGE_ONE_CLOSEOUT_COMMAND = "close_stage_one"
_REQUIRED_GATE_ARTIFACT_KINDS = ("hypothesis_set", "stage1_research_plan")
_ACCEPTED_HUMAN_TASK_STATUSES = {"resolved_accept", "succeeded"}


@dataclass(frozen=True, slots=True)
class StageOneCloseoutOutcome:
    completion_state: str
    policy_sha256: str
    artifact_refs: tuple[str, ...]
    receipt_stages: tuple[str, ...]
    receipt_refs: tuple[str, ...]
    human_gate_count: int
    status: str = "accepted"
    completion_manifest_sha256: str = ""
    program_record_id: str = ""
    program_output_sha256: str = ""
    canonical_package_sha256: str = ""

    @property
    def accepted(self) -> bool:
        return self.status == "accepted" and bool(self.completion_state)

    def to_dict(self) -> dict[str, Any]:
        return {
            "completionState": self.completion_state,
            "policySha256": self.policy_sha256,
            "artifactRefs": list(self.artifact_refs),
            "receiptStages": list(self.receipt_stages),
            "receiptRefs": list(self.receipt_refs),
            "humanGateCount": self.human_gate_count,
            "status": self.status,
            "accepted": self.accepted,
            "completionManifestSha256": self.completion_manifest_sha256,
            "programRecordId": self.program_record_id,
            "programOutputSha256": self.program_output_sha256,
            "canonicalPackageSha256": self.canonical_package_sha256,
        }


def _completion_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    payload = {
        key: value
        for key, value in manifest.items()
        if key != "manifestSha256"
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validated_completion_manifest(
    record: Mapping[str, Any],
    *,
    policy: StageOneCompletionPolicy,
    verified_manifest: Mapping[str, Any] | None = None,
) -> tuple[str, str, str, str]:
    # A persisted workflow manifest is evidence, not Program authority.  The
    # validator only accepts the manifest created from this call's fresh
    # Program readback; ordinary run fields can never self-assert acceptance.
    raw = verified_manifest
    if raw is None:
        return "", "", "", ""
    if not isinstance(raw, Mapping):
        _fail(
            "stage-one completion manifest is malformed",
            code="stage_one_completion_manifest_invalid",
        )
    expected = {
        "workflowRunId": str(record.get("runId") or ""),
        "questionId": str(record.get("questionId") or "").upper(),
        "policySha256": policy.policySha256,
    }
    if (
        raw.get("schemaVersion") != 1
        or str(raw.get("manifestKind") or "") != "stage_one_completion"
        or any(str(raw.get(key) or "") != value for key, value in expected.items())
        or str(raw.get("programRecordId") or "")
        != f"{expected['questionId']}:{expected['workflowRunId']}"
    ):
        _fail(
            "stage-one completion manifest is not bound to this run",
            code="stage_one_completion_manifest_invalid",
        )
    human_gates = raw.get("humanGates")
    human_gates = human_gates if isinstance(human_gates, Mapping) else {}
    package_hash = str(raw.get("sourceResultPackageHash") or "").lower()
    output_hash = str(raw.get("programOutputSha256") or "").lower()
    canonical_hash = str(raw.get("canonicalPackageHash") or "").lower()
    if (
        str(raw.get("programRecordId") or "").strip() == ""
        or str(raw.get("programReviewStatus") or "") != "approved"
        or raw.get("officialModelCall") is not True
        or str(raw.get("receiptStatus") or "") != "passed"
        or human_gates.get("allApproved") is not True
        or int(human_gates.get("approvedCount") or 0) != 4
        or len(package_hash) != 64
        or len(output_hash) != 64
        or len(canonical_hash) != 64
        or any(
            char not in "0123456789abcdef"
            for char in package_hash + output_hash + canonical_hash
        )
    ):
        _fail(
            "Challenge Program approval is incomplete",
            code="stage_one_program_review_not_approved",
        )
    supplied_sha256 = str(raw.get("manifestSha256") or "").lower()
    calculated_sha256 = _completion_manifest_sha256(raw)
    if supplied_sha256 != calculated_sha256:
        _fail(
            "stage-one completion manifest hash does not match",
            code="stage_one_completion_manifest_invalid",
        )
    return (
        calculated_sha256,
        str(raw.get("programRecordId") or ""),
        output_hash,
        canonical_hash,
    )


def _fail(message: str, *, code: str) -> None:
    raise NodeExecutionError(message, code=code)


def _stage_one_policy(record: Mapping[str, Any]) -> StageOneCompletionPolicy | None:
    snapshot = record.get("inputSnapshot")
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    raw_policy = snapshot.get("stageOneCompletionPolicy")
    if raw_policy is None:
        return None
    if not isinstance(raw_policy, Mapping):
        _fail("stage-one completion policy is malformed", code="stage_one_policy_invalid")
    try:
        policy = StageOneCompletionPolicy.from_dict(raw_policy)
    except (StageOneCompletionPolicyError, KeyError, TypeError, ValueError) as exc:
        raise NodeExecutionError(
            f"stage-one completion policy is invalid: {exc}",
            code="stage_one_policy_invalid",
        ) from exc
    try:
        definition = resolve_definition_for_run_record(record)
    except WorkflowDefinitionRegistryError as exc:
        raise NodeExecutionError(
            "stage-one run definition cannot be resolved",
            code="stage_one_policy_mismatch",
        ) from exc
    resolved_definition_id = f"{definition.workflowId}@{definition.schemaVersion}"
    if resolved_definition_id != policy.workflowDefinitionId:
        _fail(
            "stage-one policy does not match the run workflow definition",
            code="stage_one_policy_mismatch",
        )
    if str(record.get("questionId") or "").upper() not in policy.questionIds:
        _fail(
            "stage-one policy does not authorize this question",
            code="stage_one_policy_mismatch",
        )
    return policy


def _artifact_kind(manifest: Mapping[str, Any]) -> str:
    return str(manifest.get("artifactId") or "").split(":", 1)[0].strip()


def _receipt_payloads(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in {"modelInvocationReceipts", "model_invocation_receipts", "receipts"}:
                if isinstance(child, Mapping):
                    for receipt in child.values():
                        if isinstance(receipt, Mapping):
                            yield receipt
                elif isinstance(child, list):
                    for receipt in child:
                        if isinstance(receipt, Mapping):
                            yield receipt
                continue
            yield from _receipt_payloads(child)
    elif isinstance(value, list):
        for child in value:
            yield from _receipt_payloads(child)


def _human_gates(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in {"human_gate", "humanGate"} and isinstance(child, Mapping):
                yield child
            else:
                yield from _human_gates(child)
    elif isinstance(value, list):
        for child in value:
            yield from _human_gates(child)


def _validate_human_tasks(record: Mapping[str, Any]) -> None:
    for task in record.get("humanTasks") or []:
        if not isinstance(task, Mapping):
            _fail("stage-one human task is malformed", code="stage_one_human_gate_not_approved")
        status = str(task.get("status") or "").strip().lower()
        decision = str(task.get("decision") or "").strip().lower()
        if status not in _ACCEPTED_HUMAN_TASK_STATUSES or decision not in {"accept", "approved"}:
            _fail(
                "every stage-one human task must be explicitly accepted",
                code="stage_one_human_gate_not_approved",
            )


def evaluate_stage_one_closeout(
    record: Mapping[str, Any],
    *,
    node_id: str,
    program_handoff: Mapping[str, Any] | None = None,
) -> StageOneCloseoutOutcome | None:
    """Validate the immutable evidence set needed to stop at node 7."""

    policy = _stage_one_policy(record)
    if policy is None or node_id != policy.closureNodeId:
        return None
    deferred = set(policy.deferredNodeIds)
    if any(
        isinstance(item, Mapping) and str(item.get("nodeId") or "") in deferred
        for item in record.get("nodeRuns") or []
    ):
        _fail(
            "a phase-two node attempt already exists",
            code="stage_one_phase_two_attempt_exists",
        )

    manifests = [
        item for item in record.get("artifactManifests") or [] if isinstance(item, Mapping)
    ]
    payloads = record.get("artifactPayloads")
    payloads = payloads if isinstance(payloads, Mapping) else {}
    manifests_by_kind: dict[str, list[Mapping[str, Any]]] = {}
    for manifest in manifests:
        manifests_by_kind.setdefault(_artifact_kind(manifest), []).append(manifest)
    missing = [kind for kind in policy.requiredArtifactKinds if not manifests_by_kind.get(kind)]
    if missing:
        _fail(
            "stage-one required artifacts are missing: " + ", ".join(missing),
            code="stage_one_artifact_missing",
        )

    required_payloads: dict[str, list[Mapping[str, Any]]] = {}
    artifact_refs: list[str] = []
    for kind in policy.requiredArtifactKinds:
        for manifest in manifests_by_kind[kind]:
            artifact_id = str(manifest.get("artifactId") or "").strip()
            payload = payloads.get(artifact_id)
            if not artifact_id or not isinstance(payload, Mapping):
                _fail(
                    f"stage-one artifact payload is missing for {kind}",
                    code="stage_one_artifact_payload_missing",
                )
            artifact_refs.append(artifact_id)
            required_payloads.setdefault(kind, []).append(payload)

    human_gate_count = 0
    for kind, kind_payloads in required_payloads.items():
        kind_gate_count = 0
        for payload in kind_payloads:
            for gate in _human_gates(payload):
                kind_gate_count += 1
                human_gate_count += 1
                if gate.get("required") is not True or str(gate.get("decision") or "").lower() != "approved":
                    _fail(
                        f"stage-one human gate is not approved for {kind}",
                        code="stage_one_human_gate_not_approved",
                    )
        if kind in _REQUIRED_GATE_ARTIFACT_KINDS and kind_gate_count == 0:
            _fail(
                f"stage-one human gate is missing for {kind}",
                code="stage_one_human_gate_missing",
            )
    _validate_human_tasks(record)

    question_id = str(record.get("questionId") or "").upper()
    run_id = str(record.get("runId") or "")
    receipt_stages: dict[str, str] = {}
    for kind_payloads in required_payloads.values():
        for payload in kind_payloads:
            for raw_receipt in _receipt_payloads(payload):
                try:
                    receipt = ModelInvocationReceipt.from_dict(raw_receipt)
                except (KeyError, TypeError, ValueError) as exc:
                    raise NodeExecutionError(
                        f"stage-one model receipt is invalid: {exc}",
                        code="stage_one_receipt_invalid",
                    ) from exc
                scope = dict(receipt.scope or {})
                stage = str(scope.get("stageId") or scope.get("stage_id") or "").lower()
                if stage not in policy.requiredReceiptStages:
                    continue
                if (
                    receipt.status not in {ModelInvocationStatus.SUCCEEDED, ModelInvocationStatus.RETRIED}
                    or str(scope.get("questionId") or "").upper() != question_id
                    or str(scope.get("runId") or "") != run_id
                ):
                    _fail(
                        f"stage-one {stage} receipt is not bound to this run",
                        code="stage_one_receipt_invalid",
                    )
                receipt_stages[stage] = receipt.receipt_id
    missing_stages = [stage for stage in policy.requiredReceiptStages if stage not in receipt_stages]
    if missing_stages:
        _fail(
            "stage-one receipt stages are missing: " + ", ".join(missing_stages),
            code="stage_one_receipt_missing",
        )
    verified_manifest: Mapping[str, Any] | None = None
    if program_handoff is not None:
        from .program_candidate_handoff import (
            ProgramCandidateHandoffContractError,
            stage_one_completion_manifest_from_handoff,
        )

        try:
            verified_manifest = stage_one_completion_manifest_from_handoff(
                dict(program_handoff),
                policy_sha256=policy.policySha256,
            )
        except ProgramCandidateHandoffContractError as exc:
            raise NodeExecutionError(
                str(exc), code="stage_one_program_review_not_approved"
            ) from exc
    (
        completion_manifest_sha256,
        program_record_id,
        program_output_sha256,
        canonical_package_sha256,
    ) = _validated_completion_manifest(
        record,
        policy=policy,
        verified_manifest=verified_manifest,
    )
    accepted = bool(completion_manifest_sha256)
    return StageOneCloseoutOutcome(
        completion_state=policy.completionState if accepted else "",
        policy_sha256=policy.policySha256,
        artifact_refs=tuple(dict.fromkeys(artifact_refs)),
        receipt_stages=tuple(policy.requiredReceiptStages),
        receipt_refs=tuple(receipt_stages[stage] for stage in policy.requiredReceiptStages),
        human_gate_count=human_gate_count,
        status="accepted" if accepted else "program_review_required",
        completion_manifest_sha256=completion_manifest_sha256,
        program_record_id=program_record_id,
        program_output_sha256=program_output_sha256,
        canonical_package_sha256=canonical_package_sha256,
    )


def build_stage_one_closeout_action(
    *,
    record: Mapping[str, Any],
    node_run: Mapping[str, Any],
    idempotency_key: str,
    completed_at: str,
    outcome: StageOneCloseoutOutcome,
) -> dict[str, Any]:
    action_key = f"{idempotency_key}:{STAGE_ONE_CLOSEOUT_COMMAND}"
    action_id = "action-stage1-" + hashlib.sha256(action_key.encode("utf-8")).hexdigest()[:12]
    return {
        "actionId": action_id,
        "runId": str(record.get("runId") or ""),
        "nodeId": str(node_run.get("nodeId") or ""),
        "nodeRunId": str(node_run.get("nodeRunId") or ""),
        "attempt": int(node_run.get("attempt") or 0),
        "command": STAGE_ONE_CLOSEOUT_COMMAND,
        "idempotencyKey": action_key,
        "status": "succeeded" if outcome.accepted else "pending_human",
        "inputSummary": {
            "policySha256": outcome.policy_sha256,
            "artifactRefs": list(outcome.artifact_refs),
        },
        "issuedAt": completed_at,
        "completedAt": completed_at if outcome.accepted else "",
        "observation": {
            "status": "completed" if outcome.accepted else "program_review_required",
            **outcome.to_dict(),
        },
        "artifactRef": "",
    }


def finalize_stage_one_closeout(
    store: Any,
    *,
    record: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-read Program authority and atomically promote a pending closeout."""

    idempotency_key = str(payload.get("idempotencyKey") or "").strip()
    if not idempotency_key:
        _fail(
            "finalize_stage_one requires idempotencyKey",
            code="stage_one_finalize_invalid",
        )
    existing = record.get("stageOneCompletionManifest")
    if isinstance(existing, Mapping) and str(record.get("completionState") or "") == STAGE_ONE_ACCEPTED_STATE:
        return dict(record)
    policy = _stage_one_policy(record)
    if policy is None:
        _fail("stage-one policy is missing", code="stage_one_policy_invalid")
    team_id = str(record.get("teamId") or "").strip()
    workflow_run_id = str(record.get("runId") or "").strip()
    source_collection_run_id = str(
        ((record.get("inputSnapshot") or {}) if isinstance(record.get("inputSnapshot"), Mapping) else {}).get(
            "sourceCollectionRunId"
        )
        or workflow_run_id
    )
    from .program_candidate_handoff import (
        HANDOFF_STATUS_NEEDS_CONTEXT,
        ProgramCandidateHandoffContractError,
        handoff_result_package_to_challenge_program,
        stage_one_completion_manifest_from_handoff,
    )

    handoff = handoff_result_package_to_challenge_program(
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_collection_run_id,
        registered_by="stage_one_closeout_finalizer",
    )
    if str(handoff.get("status") or "") == HANDOFF_STATUS_NEEDS_CONTEXT:
        _fail(
            "canonical result package has not been registered",
            code="stage_one_result_package_missing",
        )
    try:
        manifest = stage_one_completion_manifest_from_handoff(
            handoff,
            policy_sha256=policy.policySha256,
        )
    except ProgramCandidateHandoffContractError as exc:
        raise NodeExecutionError(
            str(exc), code="stage_one_program_review_not_approved"
        ) from exc
    candidate = {**dict(record), "stageOneCompletionManifest": manifest}
    outcome = evaluate_stage_one_closeout(
        candidate,
        node_id=policy.closureNodeId,
        program_handoff=handoff,
    )
    if outcome is None or not outcome.accepted:
        _fail(
            "stage-one completion manifest did not authorize acceptance",
            code="stage_one_completion_manifest_invalid",
        )
    from .node_execution_support import iso, utc_now
    from .system_artifact_builder import build_system_artifact
    from .workflow_artifact_store import put_workflow_artifact

    completed_at = iso(utc_now())
    node_run = next(
        (
            dict(item)
            for item in reversed(record.get("nodeRuns") or [])
            if isinstance(item, Mapping)
            and str(item.get("nodeId") or "") == policy.closureNodeId
        ),
        None,
    )
    if node_run is None:
        _fail(
            "stage-one closure node run is missing",
            code="stage_one_completion_manifest_invalid",
        )
    completion_artifact = build_system_artifact(
        record=dict(record),
        node_run=node_run,
        artifact_kind="stage_one_completion_manifest",
        payload=manifest,
        source_artifact_ids=[
            *list(outcome.artifact_refs),
            *(
                [str(record.get("resultPackageRef"))]
                if str(record.get("resultPackageRef") or "")
                else []
            ),
        ],
        adapter_name="stage_one_closeout_finalizer",
    )
    put_workflow_artifact(
        team_id,
        kind="stage_one_completion_manifest",
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_collection_run_id,
        payload=manifest,
        artifact_identity=idempotency_key,
    )
    formal_closeout_enqueued = _enqueue_production_stage_one_closeout(
        record=record,
        outcome=outcome,
        idempotency_key=idempotency_key,
        completed_at=completed_at,
    )

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        if str(current.get("completionState") or "") == STAGE_ONE_ACCEPTED_STATE:
            return current
        actions = []
        for item in current.get("systemActions") or []:
            if isinstance(item, Mapping) and str(item.get("command") or "") == STAGE_ONE_CLOSEOUT_COMMAND:
                actions.append(
                    {
                        **dict(item),
                        "status": "succeeded",
                        "completedAt": completed_at,
                        "observation": {"status": "completed", **outcome.to_dict()},
                    }
                )
            else:
                actions.append(item)
        return {
            **current,
            "status": "succeeded",
            "completionState": outcome.completion_state,
            "completionKind": "stage_one_g1_accepted",
            "terminalReason": outcome.completion_state,
            "completedAt": completed_at,
            "stageOneCompletionManifest": manifest,
            "stageOneCompletionManifestRef": completion_artifact.artifactId,
            "stageOneCloseout": outcome.to_dict(),
            "formalCloseoutEnqueued": formal_closeout_enqueued,
            "artifactManifests": [
                *(current.get("artifactManifests") or []),
                *(
                    [completion_artifact.to_dict()]
                    if not any(
                        isinstance(item, Mapping)
                        and item.get("artifactId") == completion_artifact.artifactId
                        for item in current.get("artifactManifests") or []
                    )
                    else []
                ),
            ],
            "artifactPayloads": {
                **(current.get("artifactPayloads") or {}),
                completion_artifact.artifactId: manifest,
            },
            "systemActions": actions,
        }

    return store.mutate_run(workflow_run_id, mutation)


def enqueue_ledger_stage_one_closeout(
    store: Any,
    *,
    workflow_run_id: str,
    outcome: StageOneCloseoutOutcome,
    idempotency_key: str,
    completed_at_ms: int,
) -> bool:
    """Atomically enqueue the authoritative Ledger resume after Program approval."""

    if not outcome.accepted:
        _fail(
            "stage-one Ledger finalize requires approved Program authority",
            code="stage_one_program_review_not_approved",
        )
    from core.research.workflow.challenge_cup_runtime import action_id_for
    from core.research.workflow.contracts import ExecutionReceipt

    from .graph_dispatch_factory import build_graph_dispatch_record

    run = store.get_run(workflow_run_id)
    if run is None:
        return False
    policy = _stage_one_policy(_ledger_run_mapping(run))
    if policy is None:
        _fail("stage-one policy is missing", code="stage_one_policy_invalid")
    attempt = store.latest_attempt(workflow_run_id, policy.closureNodeId)
    if attempt is None or str(attempt.status) != "succeeded":
        _fail(
            "stage-one closure attempt is not durably succeeded",
            code="stage_one_closure_attempt_missing",
        )
    receipt_action_id = action_id_for(
        workflow_run_id,
        policy.closureNodeId,
        int(attempt.attempt),
    )
    receipt = ExecutionReceipt(
        action_id=receipt_action_id,
        node_run_id=str(attempt.node_run_id),
        outcome="succeeded",
        artifact_receipt_ids=(),
        execution_anchor_id=attempt.execution_anchor_id,
        budget_receipt_id=None,
        problem=None,
        completed_at_ms=int(completed_at_ms),
    )
    identity = f"{workflow_run_id}:{idempotency_key}:formal-closeout"
    outbox_action_id = "act-stage1-finalize-" + hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()[:12]
    outbox = build_graph_dispatch_record(
        run=run,
        attempt=attempt,
        command_id=str(attempt.command_id or "cmd-stage-one-finalize"),
        dispatch_kind="resume_action",
        now_ms=int(completed_at_ms),
        receipt_payload=receipt.to_dict(),
        state_update={
            STAGE_ONE_CHECKPOINT_FIELD: outcome.completion_state,
            "stage_one_closeout": outcome.to_dict(),
        },
        idempotency_key=f"graph:stage-one-finalize:{workflow_run_id}:{idempotency_key}",
        action_id=outbox_action_id,
    )

    def mutation(uow: Any) -> bool:
        if uow.repository.get_outbox(outbox_action_id) is not None:
            return True
        current = uow.repository.get_run(workflow_run_id)
        current_attempt = uow.repository.get_attempt(str(attempt.node_run_id))
        if current is None or current_attempt is None:
            return False
        if str(current_attempt.status) != "succeeded":
            return False
        uow.repository.insert_outbox(outbox)
        return True

    return bool(store.submit(mutation, force_flush=True).result(timeout=30))


def _enqueue_production_stage_one_closeout(
    *,
    record: Mapping[str, Any],
    outcome: StageOneCloseoutOutcome,
    idempotency_key: str,
    completed_at: str,
) -> bool:
    from datetime import datetime

    from .runtime_factory import (
        production_workflow_runtime,
        wake_production_workflow_runtime,
    )

    runtime = production_workflow_runtime()
    if runtime is None or runtime.store.get_run(str(record.get("runId") or "")) is None:
        return False
    completed_at_ms = int(datetime.fromisoformat(completed_at).timestamp() * 1000)
    enqueued = enqueue_ledger_stage_one_closeout(
        runtime.store,
        workflow_run_id=str(record.get("runId") or ""),
        outcome=outcome,
        idempotency_key=idempotency_key,
        completed_at_ms=completed_at_ms,
    )
    if not enqueued:
        _fail(
            "formal stage-one closeout could not be enqueued",
            code="stage_one_formal_closeout_enqueue_failed",
        )
    wake_production_workflow_runtime()
    return True


def _ledger_run_mapping(run: Any) -> dict[str, Any]:
    try:
        snapshot = json.loads(str(getattr(run, "input_snapshot_json", "") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        snapshot = {}
    return {
        "runId": str(getattr(run, "run_id", "") or ""),
        "teamId": str(getattr(run, "team_id", "") or ""),
        "projectId": str(getattr(run, "project_id", "") or ""),
        "workflowId": str(getattr(run, "workflow_id", "") or ""),
        "workflowVersionId": str(getattr(run, "workflow_version_id", "") or ""),
        "structureHash": str(getattr(run, "structure_hash", "") or ""),
        "questionId": str(getattr(run, "question_id", "") or "").upper(),
        "inputSnapshot": snapshot if isinstance(snapshot, Mapping) else {},
    }


def _ledger_receipt_payload(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return {
            "receiptId": str(row.get("receiptId") or row.get("receipt_id") or ""),
            "artifactType": str(
                row.get("artifactType") or row.get("artifact_kind") or ""
            ),
            "canonicalRef": str(
                row.get("canonicalRef") or row.get("canonical_ref") or ""
            ),
            "version": str(row.get("version") or row.get("artifact_version") or ""),
            "sha256": str(row.get("sha256") or ""),
            "domainRevision": str(
                row.get("domainRevision") or row.get("domain_revision") or ""
            ),
        }
    canonical_ref = ""
    try:
        decoded = json.loads(str(row[5] or "{}"))
        canonical_ref = str(decoded.get("canonicalRef") or "")
    except (IndexError, TypeError, ValueError, json.JSONDecodeError, AttributeError):
        canonical_ref = ""
    return {
        "receiptId": str(row[0] or ""),
        "artifactType": str(row[4] or ""),
        "canonicalRef": canonical_ref,
        "version": str(row[6] or ""),
        "sha256": str(row[7] or ""),
        "domainRevision": str(row[8] or ""),
    }


def _load_ledger_artifact_payload(receipt: Mapping[str, Any]) -> dict[str, Any] | None:
    from .artifact_readback_registry import (
        load_scoped_artifact_payload,
        parse_canonical_ref,
        read_domain_artifact,
    )

    canonical_ref = str(receipt.get("canonicalRef") or "").strip()
    parsed = parse_canonical_ref(canonical_ref)
    if parsed is None or parsed.get("legacy") == "1":
        return None
    readback = read_domain_artifact(canonical_ref)
    if (
        readback is None
        or readback.content_hash != str(receipt.get("sha256") or "")
        or readback.domain_revision != str(receipt.get("domainRevision") or "")
    ):
        return None
    envelope = load_scoped_artifact_payload(
        str(parsed.get("kind") or ""),
        team_id=str(parsed.get("teamId") or ""),
        authority_run_id=str(parsed.get("authorityRunId") or ""),
        content_hash=str(receipt.get("sha256") or ""),
    )
    if not isinstance(envelope, Mapping):
        return None
    payload = envelope.get("payload")
    if isinstance(payload, Mapping):
        return dict(payload)
    return dict(envelope)


def evaluate_ledger_stage_one_closeout(
    store: Any,
    *,
    action: Any,
    current_artifact_receipts: Iterable[Mapping[str, Any]],
) -> StageOneCloseoutOutcome | None:
    """Project the formal Ledger snapshot into the shared closeout validator."""

    run, attempts, prior_receipts, pending_human_tasks = store.read(
        lambda repo: (
            repo.get_run(str(action.run_id)),
            repo.list_attempts(str(action.run_id)),
            repo.list_artifact_receipts_for_run(str(action.run_id)),
            repo.list_pending_human_tasks(str(action.run_id)),
        )
    )
    if run is None:
        _fail("stage-one Ledger run is missing", code="stage_one_run_missing")
    record = _ledger_run_mapping(run)
    policy = _stage_one_policy(record)
    if policy is None or str(action.node_id) != policy.closureNodeId:
        return None

    selected_by_kind: dict[str, dict[str, Any]] = {}
    for raw in [*prior_receipts, *current_artifact_receipts]:
        receipt = _ledger_receipt_payload(raw)
        kind = str(receipt.get("artifactType") or "").split(":", 1)[0].strip()
        if kind:
            selected_by_kind[kind] = receipt

    manifests: list[dict[str, Any]] = []
    payloads: dict[str, dict[str, Any]] = {}
    for kind in policy.requiredArtifactKinds:
        receipt = selected_by_kind.get(kind)
        if receipt is None:
            continue
        canonical_ref = str(receipt.get("canonicalRef") or "").strip()
        artifact_id = canonical_ref or f"{kind}:{receipt.get('receiptId') or kind}"
        payload = _load_ledger_artifact_payload(receipt)
        if payload is None:
            _fail(
                f"stage-one artifact payload is unreadable for {kind}",
                code="stage_one_artifact_payload_missing",
            )
        manifests.append({"artifactId": artifact_id})
        payloads[artifact_id] = payload

    record.update(
        {
            "artifactManifests": manifests,
            "artifactPayloads": payloads,
            "nodeRuns": [
                {"nodeId": str(item.node_id), "status": str(item.status)}
                for item in attempts
            ],
            "humanTasks": [
                {
                    "taskId": str(item[0] or ""),
                    "status": str(item[6] or "pending"),
                    "decision": "",
                }
                for item in pending_human_tasks
            ],
        }
    )
    evidence_outcome = evaluate_stage_one_closeout(
        record,
        node_id=str(action.node_id),
    )
    if evidence_outcome is None:
        return None

    from .program_candidate_handoff import (
        HANDOFF_STATUS_NEEDS_CONTEXT,
        ProgramCandidateHandoffContractError,
        handoff_result_package_to_challenge_program,
    )

    snapshot = record.get("inputSnapshot")
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    try:
        handoff = handoff_result_package_to_challenge_program(
            store=store,
            team_id=str(record.get("teamId") or ""),
            workflow_run_id=str(record.get("runId") or ""),
            source_collection_run_id=str(
                snapshot.get("sourceCollectionRunId") or record.get("runId") or ""
            ),
            registered_by="stage_one_ledger_closeout",
        )
    except ProgramCandidateHandoffContractError as exc:
        raise NodeExecutionError(
            str(exc), code="stage_one_program_authority_invalid"
        ) from exc
    if (
        str(handoff.get("status") or "") == HANDOFF_STATUS_NEEDS_CONTEXT
        or str(handoff.get("reviewStatus") or "") != "approved"
    ):
        return evidence_outcome
    return evaluate_stage_one_closeout(
        record,
        node_id=str(action.node_id),
        program_handoff=handoff,
    )


def stage_one_terminal_facts(
    run: Any,
    *,
    node_id: str,
    state_update: Mapping[str, Any] | None,
) -> tuple[str, str] | None:
    """Return terminal facts only for a server-authorized stage-one marker."""

    if (
        str((state_update or {}).get(STAGE_ONE_CHECKPOINT_FIELD) or "")
        != STAGE_ONE_ACCEPTED_STATE
    ):
        return None
    record = _ledger_run_mapping(run)
    policy = _stage_one_policy(record)
    if policy is None or str(node_id or "") != policy.closureNodeId:
        return None
    return "stage_one_g1_accepted", policy.completionState


__all__ = [
    "STAGE_ONE_ACCEPTED_STATE",
    "STAGE_ONE_CLOSEOUT_COMMAND",
    "StageOneCloseoutOutcome",
    "build_stage_one_closeout_action",
    "enqueue_ledger_stage_one_closeout",
    "evaluate_ledger_stage_one_closeout",
    "evaluate_stage_one_closeout",
    "finalize_stage_one_closeout",
    "route_after_stage_one_closure",
    "stage_one_terminal_facts",
]
