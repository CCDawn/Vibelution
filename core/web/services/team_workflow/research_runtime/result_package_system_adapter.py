"""Final System adapter that commits the deterministic research result package."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .node_completion import complete_node_execution
from .node_execution import start_node_execution
from .node_execution_support import NodeExecutionError, latest_node_run
from .result_package import (
    ResultPackageError,
    build_result_package,
    terminal_package_candidate,
)
from .result_package_v2 import (
    ResultPackageV2Error,
    build_challenge_result_package_v2,
    build_proposal_result_package_base,
    is_proposal_only_challenge_run,
)
from .store import WorkflowRunStore
from .system_action_records import (
    SystemActionError,
    begin_system_action,
    complete_system_action,
    fail_system_action,
    find_system_action,
)
from .system_artifact_builder import build_system_artifact


def build_stage_one_proposal_package(
    record: Any,
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    """Build the stage-one proposal result package (single shared build path).

    Pure domain build used by BOTH the legacy file-store adapter and the
    ledger ``build_stage_one_package`` command: builds the generic proposal
    envelope, mirrors the scoped ``stage1_research_plan`` authority onto the
    shared ``research_plan`` alias once, and assembles the canonical v2
    output.  The alias write is idempotent by content identity; no run/store
    mutation happens here.

    Returns ``(package, plan_alias_written)``.  Raises the builders' own
    typed failures (``ResultPackageError`` / ``ResultPackageV2Error``).
    """

    candidate = {
        **record,
        "terminalReason": "STAGE1_PROGRAM_REVIEW_REQUIRED",
        "completedAt": str(record.get("updatedAt") or record.get("createdAt") or ""),
    }
    generic = build_proposal_result_package_base(candidate)
    # Stage one owns ``stage1_research_plan`` while the canonical v2 builder
    # reads the shared ``research_plan`` authority. Project that exact
    # payload once; do not synthesize missing plan fields.
    from .artifact_readback_registry import load_scoped_artifact_payload
    from .workflow_artifact_store import put_workflow_artifact

    plan_alias_written = False
    plan_envelope = load_scoped_artifact_payload(
        "stage1_research_plan",
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        authority_run_id=source_collection_run_id,
    )
    if isinstance(plan_envelope, dict):
        plan_payload = plan_envelope.get("payload")
        plan_payload = plan_payload if isinstance(plan_payload, dict) else plan_envelope
        put_workflow_artifact(
            team_id,
            kind="research_plan",
            workflow_run_id=workflow_run_id,
            source_collection_run_id=source_collection_run_id,
            payload=deepcopy(plan_payload),
            artifact_identity=f"{idempotency_key}:research-plan-alias",
        )
        plan_alias_written = True
    package = build_challenge_result_package_v2(
        generic_package=generic,
        record=candidate,
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_collection_run_id,
    )
    return package, plan_alias_written


def execute_stage_one_package_action(
    store: WorkflowRunStore,
    *,
    record: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Materialize/register the node-7 proposal without creating node 17."""

    idempotency_key = str(payload.get("idempotencyKey") or "").strip()
    if not idempotency_key:
        raise SystemActionError(
            "build_stage_one_package requires idempotencyKey",
            code="invalid_system_action",
        )
    closeout = record.get("stageOneCloseout")
    if not isinstance(closeout, dict) or closeout.get("status") != "program_review_required":
        raise SystemActionError(
            "stage-one evidence is not ready for packaging",
            code="stage_one_package_not_ready",
        )
    existing_package = record.get("resultPackage")
    existing_handoff = record.get("programCandidateHandoff")
    if isinstance(existing_package, dict) and isinstance(existing_handoff, dict):
        return {
            "command": "build_stage_one_package",
            "idempotent": True,
            "resultPackage": deepcopy(existing_package),
            "programCandidateHandoff": deepcopy(existing_handoff),
        }
    team_id = str(record.get("teamId") or "")
    workflow_run_id = str(record.get("runId") or "")
    snapshot = record.get("inputSnapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    authority_run_id = str(snapshot.get("sourceCollectionRunId") or workflow_run_id)
    try:
        package, _plan_alias_written = build_stage_one_proposal_package(
            record,
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=authority_run_id,
            idempotency_key=idempotency_key,
        )
    except (ResultPackageError, ResultPackageV2Error) as exc:
        raise SystemActionError(
            str(exc), code=str(getattr(exc, "code", "challenge_v2_package_failed"))
        ) from exc
    completion_policy = snapshot.get("stageOneCompletionPolicy")
    completion_policy = completion_policy if isinstance(completion_policy, dict) else {}
    node_run = latest_node_run(
        record,
        str(completion_policy.get("closureNodeId") or "hypothesis_design"),
    )
    manifest = build_system_artifact(
        record=record,
        node_run=node_run,
        artifact_kind="research_result_package",
        payload=package,
        source_artifact_ids=list(closeout.get("artifactRefs") or []),
        adapter_name="stage_one_result_package_adapter",
    )
    from .workflow_artifact_store import put_workflow_artifact

    put_workflow_artifact(
        team_id,
        kind="research_result_package",
        workflow_run_id=workflow_run_id,
        source_collection_run_id=authority_run_id,
        payload={
            "teamId": team_id,
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": authority_run_id,
            "package": package,
        },
        artifact_identity=idempotency_key,
    )
    from .program_candidate_handoff import (
        HANDOFF_STATUS_NEEDS_CONTEXT,
        handoff_result_package_to_challenge_program,
    )

    handoff = handoff_result_package_to_challenge_program(
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        source_collection_run_id=authority_run_id,
        registered_by="stage_one_result_package_adapter",
    )
    if str(handoff.get("status") or "") == HANDOFF_STATUS_NEEDS_CONTEXT:
        raise SystemActionError(
            str(handoff.get("reason") or "stage-one package handoff needs context"),
            code="program_candidate_handoff_needs_context",
        )
    updated = store.update_run(
        workflow_run_id,
        {
            "artifactManifests": [
                *(record.get("artifactManifests") or []),
                manifest.to_dict(),
            ],
            "artifactPayloads": {
                **(record.get("artifactPayloads") or {}),
                manifest.artifactId: package,
            },
            "resultPackage": package,
            "resultPackageRef": manifest.artifactId,
            "programCandidateHandoff": handoff,
        },
    )
    return {
        "command": "build_stage_one_package",
        "idempotent": False,
        "resultPackage": package,
        "programCandidateHandoff": handoff,
        "run": updated,
    }


def execute_result_package_action(
    store: WorkflowRunStore,
    *,
    checkpoint_path: str,
    record: dict[str, Any],
    research_ledger: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    idempotency_key = str(payload.get("idempotencyKey") or "").strip()
    if not idempotency_key:
        raise SystemActionError(
            "build_package requires idempotencyKey",
            code="invalid_system_action",
        )
    existing = find_system_action(
        record,
        node_id="result_package",
        command="build_package",
        idempotency_key=idempotency_key,
    )
    if existing is not None and existing.get("status") == "succeeded":
        return {
            "command": "build_package",
            "systemAction": existing,
            "resultPackage": record.get("resultPackage"),
        }
    node_run = latest_node_run(record, "result_package")
    if node_run.get("status") != "ready":
        raise SystemActionError(
            "result_package must be ready",
            code="invalid_node_state",
        )
    candidate = terminal_package_candidate(record)
    proposal_only = is_proposal_only_challenge_run(candidate)
    try:
        package = (
            build_proposal_result_package_base(candidate)
            if proposal_only
            else build_result_package(candidate, research_ledger=research_ledger)
        )
        if proposal_only:
            package = build_challenge_result_package_v2(
                generic_package=package,
                record=candidate,
                team_id=str(record["teamId"]),
                workflow_run_id=str(record["runId"]),
                source_collection_run_id=str(
                    (record.get("inputSnapshot") or {}).get("sourceCollectionRunId")
                    or record["runId"]
                ),
            )
    except (ResultPackageError, ResultPackageV2Error) as exc:
        raise SystemActionError(
            str(exc), code=str(getattr(exc, "code", "challenge_v2_package_failed"))
        ) from exc
    action, created = begin_system_action(
        store,
        record=record,
        node_id="result_package",
        node_run_id=str(node_run["nodeRunId"]),
        attempt=int(node_run["attempt"]),
        command="build_package",
        idempotency_key=idempotency_key,
        input_summary={
            "factChainHash": package["factChainHash"],
            "officialVersionId": str(
                (package.get("officialVersion") or {}).get("versionId") or ""
            ),
        },
    )
    if not created:
        return {
            "command": "build_package",
            "systemAction": action,
            "resultPackage": record.get("resultPackage"),
        }
    lease_owner = "system:result_package"
    try:
        start_node_execution(
            store,
            run_id=str(record["runId"]),
            node_id="result_package",
            payload={
                "idempotencyKey": f"{idempotency_key}:lease",
                "leaseOwner": lease_owner,
                "leaseSeconds": 300,
                "deadlineSeconds": 1800,
            },
        )
        manifest = build_system_artifact(
            record=record,
            node_run=node_run,
            artifact_kind="research_result_package",
            payload=package,
            source_artifact_ids=[
                str(item.get("artifactId") or "")
                for item in record.get("artifactManifests") or []
                if str(item.get("artifactId") or "")
            ],
            adapter_name="result_package_system_adapter",
        )
        from .workflow_artifact_store import put_workflow_artifact

        put_workflow_artifact(
            str(record["teamId"]),
            kind="research_result_package",
            workflow_run_id=str(record["runId"]),
            source_collection_run_id=str(
                (record.get("inputSnapshot") or {}).get("sourceCollectionRunId")
                or record["runId"]
            ),
            payload={
                "teamId": str(record["teamId"]),
                "workflowRunId": str(record["runId"]),
                "sourceCollectionRunId": str(
                    (record.get("inputSnapshot") or {}).get("sourceCollectionRunId")
                    or record["runId"]
                ),
                "package": package,
            },
            artifact_identity=str(action.get("actionId") or idempotency_key),
        )
        completed_run = complete_node_execution(
            store,
            checkpoint_path=checkpoint_path,
            run_id=str(record["runId"]),
            node_id="result_package",
            payload={
                "idempotencyKey": f"{idempotency_key}:complete",
                "leaseOwner": lease_owner,
                "artifactManifests": [manifest.to_dict()],
                "artifactPayloads": {manifest.artifactId: package},
            },
        )
        if completed_run.get("status") != "succeeded" or completed_run.get(
            "runtimeCurrentNodeIds"
        ):
            raise SystemActionError(
                "result package did not reach terminal WorkflowRun state",
                code="result_package_not_terminal",
            )
        store.update_run(
            str(record["runId"]),
            {
                "resultPackage": package,
                "resultPackageRef": manifest.artifactId,
            },
        )
    except (NodeExecutionError, SystemActionError) as exc:
        fail_system_action(
            store,
            run_id=str(record["runId"]),
            action=action,
            error_code=str(getattr(exc, "code", "result_package_failed")),
            message=str(exc),
        )
        raise
    observation = {
        "status": "completed",
        "observationRef": manifest.artifactId,
        "packageId": package["packageId"],
        "factChainHash": package["factChainHash"],
    }
    completed_action = complete_system_action(
        store,
        run_id=str(record["runId"]),
        action=action,
        observation=observation,
    )
    return {
        "command": "build_package",
        "systemAction": completed_action,
        "resultPackage": package,
    }
