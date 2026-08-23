"""Final System adapter that commits the deterministic research result package."""

from __future__ import annotations

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
