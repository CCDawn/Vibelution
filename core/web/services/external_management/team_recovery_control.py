"""Project native Team repair state without reading prompts or replaying work."""
from pydantic import ValidationError

from . import runtime_operations as operations
from .service import ManagementError
from .team_recovery_contracts import (TeamRecoveryQuery, TeamRecoveryConfirmDeployment,
    TeamRecoveryMetadata, TeamRecoveryResponse, TeamRecoveryDeploymentResponse)


def metadata(raw):
    value = raw.get("recovery")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Invalid native recovery")
    evidence = value.get("evidenceRefs", [])
    if (not isinstance(evidence, list) or len(evidence) > 20
            or any(not isinstance(ref, str) or not 1 <= len(ref) <= 500 for ref in evidence)):
        raise ValueError("Invalid recovery evidence metadata")
    return TeamRecoveryMetadata.model_validate({**{key: value.get(key, "" if key in {
        "reason", "repairRunId", "codeRepairRunId"} else 0) for key in (
        "issueId", "nodeId", "status", "reason", "failureCount", "repairAttempts", "repairRunId", "codeRepairRunId")},
        "evidenceCount": len(evidence), "evidenceDigest": operations._fingerprint(evidence)}).model_dump()


def project(raw, query):
    native = operations._project("team_run", raw)
    if (native["teamId"], native["flowId"], native["resourceId"]) != (query.team_id, query.flow_id, query.run_id):
        raise ManagementError("OPERATION_UNAVAILABLE", 404)
    recovery = metadata(raw)
    allowed = (native["status"] == "failed" and not raw.get("stopRequested") and not raw.get("_recoveryParent")
        and recovery is not None and recovery["status"] == "awaiting_deployment")
    return TeamRecoveryResponse.model_validate({"teamId": native["teamId"], "flowId": native["flowId"],
        "runId": native["resourceId"], "revision": native["revision"], "runStatus": native["status"],
        "recovery": recovery, "commands": ["confirm_deployment"] if allowed else [],
        "businessAcceptance": "not_evaluated", "untrustedContent": True}).model_dump()


def read(gateway, parameters):
    try:
        query = TeamRecoveryQuery.model_validate(parameters)
    except ValidationError:
        raise ManagementError("INVALID_INPUT", 422) from None
    # The existing point read verifies the Team roster, workspace and all owner
    # references without calling snapshot(), reconcile(), or ensure_admission().
    gateway._owners()
    for value in (query.team_id, query.flow_id, query.run_id):
        operations._file_reference(value)
    try:
        raw = operations._point_operation(gateway, "team_run", query.run_id,
            {"team_id": query.team_id, "flow_id": query.flow_id})
        return project(raw, query)
    except ManagementError:
        raise
    except (ValueError, OSError, TypeError, KeyError):
        raise ManagementError("OPERATION_SOURCE_UNAVAILABLE", 503) from None


def confirm_deployment(gateway, parameters):
    try:
        query = TeamRecoveryConfirmDeployment.model_validate(parameters)
    except ValidationError:
        raise ManagementError("INVALID_INPUT", 422) from None
    before = read(gateway, query.model_dump(include={"team_id", "flow_id", "run_id"}))
    if before["revision"] != query.expected_revision:
        raise ManagementError("STATE_CONFLICT", 409)
    if "confirm_deployment" not in before["commands"]:
        raise ManagementError("COMMAND_UNAVAILABLE", 409)
    from core.web.services.team_workflow.generic import service, store
    try:
        raw = service.command_run(query.team_id, query.run_id, {"action": "confirm_deployment",
            "expectedRevision": int(query.expected_revision), "evidenceRef": query.evidence_ref})
        result = project(raw, query)
        if int(result["revision"]) <= int(before["revision"]):
            raise ManagementError("OPERATION_UNCONFIRMED", 503)
        return TeamRecoveryDeploymentResponse.model_validate({**result, "command": "confirm_deployment",
            "accepted": True, "evidenceDigest": operations._fingerprint(query.evidence_ref),
            "revisionCheck": "native_cas"}).model_dump()
    except store.Conflict:
        raise ManagementError("STATE_CONFLICT", 409) from None
    except store.NotFound:
        raise ManagementError("OPERATION_UNAVAILABLE", 404) from None
    except store.WorkflowError:
        raise ManagementError("STATE_CONFLICT", 409) from None
    except ManagementError:
        raise
    except Exception:
        raise ManagementError("OPERATION_UNCONFIRMED", 503) from None
