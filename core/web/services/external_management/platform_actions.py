"""Small native acknowledgements for the additive platform control actions."""
from .asset_contracts import ASSET_ACTION_MODELS, AssetMutationResponse
from .configuration_actions import CONFIGURATION_ACTION_MODELS
from .team_lifecycle_contracts import TEAM_LIFECYCLE_ACTION_MODELS
from .flow_contracts import FLOW_ACTION_MODELS, FlowMutationResponse
from .runtime_contracts import RuntimeCommandResponse
from .research_contracts import ResearchCommandResponse
from .team_recovery_contracts import TeamRecoveryDeploymentResponse


PLATFORM_ACTIONS = frozenset({"runtime_command", "research_command", "team_recovery_confirm_deployment", *ASSET_ACTION_MODELS, *CONFIGURATION_ACTION_MODELS, *TEAM_LIFECYCLE_ACTION_MODELS, *FLOW_ACTION_MODELS})
RESULT_FIELDS = {"runtime_command": "operation", **{key: "asset" for key in {*ASSET_ACTION_MODELS, *CONFIGURATION_ACTION_MODELS, *TEAM_LIFECYCLE_ACTION_MODELS}},
                 **{key: "flow" for key in FLOW_ACTION_MODELS}, "research_command": "research",
                 "team_recovery_confirm_deployment": "recovery"}


def native_result(action, raw):
    if action not in PLATFORM_ACTIONS:
        raise ValueError("Unknown platform action")
    model = (TeamRecoveryDeploymentResponse if action == "team_recovery_confirm_deployment" else
             RuntimeCommandResponse if action == "runtime_command" else ResearchCommandResponse if action == "research_command" else
             AssetMutationResponse if action in {*ASSET_ACTION_MODELS, *CONFIGURATION_ACTION_MODELS, *TEAM_LIFECYCLE_ACTION_MODELS} else FlowMutationResponse)
    result = model.model_validate(raw).model_dump(exclude_none=True)
    if action not in {"runtime_command", "research_command", "team_recovery_confirm_deployment"} and (result["action"] != action or result["verified"] is not True):
        raise ValueError("Native acknowledgement is not verified for this action")
    if action == "runtime_command":
        # Historical command receipts keep their closed SDK operation shape.
        result["operation"].pop("progressFingerprint", None)
    return result


def verify_target(action, result, parameters, marker=None):
    if action == "team_recovery_confirm_deployment":
        from .runtime_operations import _fingerprint
        valid = ((result["teamId"], result["flowId"], result["runId"]) ==
            (parameters["team_id"], parameters["flow_id"], parameters["run_id"])
            and result["evidenceDigest"] == _fingerprint(parameters["evidence_ref"])
            and int(result["revision"]) > int(parameters["expected_revision"]))
    elif action == "runtime_command":
        operation = result["operation"]
        valid = (operation["kind"] == parameters["kind"] and operation["resourceId"] == parameters["resource_id"]
            and result["command"] == parameters["command"]
            and all(operation.get(output, "") == parameters.get(key, "") for key, output in
                    (("session_id", "sessionId"), ("team_id", "teamId"), ("flow_id", "flowId")) if parameters.get(key)))
    elif action == "research_command":
        operation, receipt = result["operation"], result["receipt"]
        valid = (operation["kind"] == "research_run" and result["command"] == parameters["command"]
            and (operation["resourceId"], operation["teamId"], operation["flowId"])
                == (parameters["run_id"], parameters["team_id"], parameters["flow_id"])
            and all(receipt.get(field, "") == parameters.get(key, "") for field, key in
                    (("runId", "run_id"), ("teamId", "team_id"), ("flowId", "flow_id"), ("command", "command"),
                     ("expectedRevision", "expected_revision"), ("nodeId", "node_id"), ("taskId", "task_id"),
                     ("decision", "decision"), ("checkpointId", "checkpoint_id")))
            and (marker is None or receipt["requestId"] == marker["requestKey"]))
    elif action == "team_create":
        from .asset_contracts import TeamAssetQuery
        TeamAssetQuery.model_validate({"team_id": result["resourceId"]})
        valid = result["action"] == action
    elif action in TEAM_LIFECYCLE_ACTION_MODELS:
        valid = result["action"] == action and result["resourceId"] == parameters["team_id"]
    elif action in {*ASSET_ACTION_MODELS, *CONFIGURATION_ACTION_MODELS}:
        target = next(parameters[key] for key in ("agent_id", "team_id", "knowledge_base_id") if key in parameters)
        valid = result["action"] == action and result["resourceId"] == target
    else:
        valid = (result["action"] == action and result["teamId"] == parameters["team_id"]
                 and result["flowId"] == parameters["flow_id"])
    if not valid:
        raise ValueError("Native acknowledgement target changed")


def execute(native, action, parameters, marker):
    from .operation_receipts import owner, record_success
    if action == "agent_dispatch_access_set":
        from .dispatch_access import DispatchAccessControl
        # This operation's completed config manifest is the native proof.
        # Do not introduce a second acknowledgement authority after commit.
        result = native_result(action, DispatchAccessControl(native).set(parameters, marker))
        verify_target(action, result, parameters, marker)
        return result
    outcome = owner(native)
    if outcome is not None:
        previous = outcome.read(action, parameters, marker)
        if previous is not None:
            return previous
    if action == "team_recovery_confirm_deployment":
        from .team_recovery_control import confirm_deployment
        raw = confirm_deployment(native, parameters)
    elif action == "runtime_command":
        raw = native.runtime_command(parameters, marker)
    elif action == "research_command":
        from .research_control import command
        raw = command(native, parameters, request_id=marker["requestKey"])
    elif action == "agent_parameters_update":
        from .agent_configuration import AgentConfigurationControl
        raw = AgentConfigurationControl(native).update_parameters(parameters, marker)
    elif action == "agent_prompt_update":
        from .configuration_discovery import ConfigurationDiscovery
        raw = ConfigurationDiscovery(native).update_prompt(parameters, marker)
    elif action in TEAM_LIFECYCLE_ACTION_MODELS:
        from .team_lifecycle_control import TeamLifecycleControl
        method = {"team_create": "create_team", "team_member_add": "add_member",
                  "team_member_remove": "remove_member", "team_archive": "archive_team"}[action]
        raw = getattr(TeamLifecycleControl(native), method)(parameters, marker)
    elif action in ASSET_ACTION_MODELS:
        from .asset_control import AssetControl
        method = {"team_update": "update_team", "agent_tool_policy_update": "update_tool_policy",
            "knowledge_acl_grant": "grant_knowledge_acl", "knowledge_acl_revoke": "revoke_knowledge_acl"}[action]
        raw = getattr(AssetControl(native), method)(parameters, marker)
    else:
        from .flow_control import FlowControl
        owner = FlowControl(native)
        raw = (owner.save_flow(parameters, marker=marker) if action == "flow_save"
               else owner.start_flow(parameters, request_id=marker["requestKey"], marker=marker))
    result = native_result(action, raw)
    verify_target(action, result, parameters, marker)
    return record_success(native, action, parameters, marker, result)


def reconcile(native, action, parameters, marker):
    """Read original causal evidence; absence requires review, never replay."""
    from .operation_receipts import owner, _binding
    def response(state, evidence="none", result=None):
        code = {"confirmed": "NATIVE_OUTCOME_CONFIRMED", "requires_review": "NATIVE_OUTCOME_REQUIRES_REVIEW",
                "unavailable": "NATIVE_OUTCOME_UNAVAILABLE"}[state]
        return {"state": state, "evidence": evidence, "result": result, "code": code}
    try:
        _binding(native.project_root, action, parameters, marker)
        if action == "agent_dispatch_access_set":
            from .dispatch_access import DispatchAccessControl
            result = DispatchAccessControl(native).receipt(parameters, marker)
            if result is None:
                return response("requires_review")
            result = native_result(action, result)
            verify_target(action, result, parameters, marker)
            return response("confirmed", "native_outcome", result)
        outcome = owner(native)
        result = outcome.read(action, parameters, marker) if outcome is not None else None
        if result is not None:
            return response("confirmed", "native_outcome", result)
        if action == "runtime_command" and parameters.get("kind") in {"supervised_run", "self_evolution_run"}:
            from .runtime_operations import read_command_receipt
            result = read_command_receipt(native, parameters, request_id=marker["requestKey"])
            if result is None:
                return response("requires_review")
            evidence = "native_outcome"
        elif action == "research_command":
            from .research_control import read_receipt
            result = read_receipt(native, parameters, request_id=marker["requestKey"])
            evidence = "research_ledger"
        elif action == "flow_start":
            from .flow_control import FlowControl
            result = FlowControl(native).read_start_receipt(parameters, request_id=marker["requestKey"])
            evidence = "flow_start_identity"
        else:
            return response("requires_review")
        result = native_result(action, result)
        verify_target(action, result, parameters, marker)
        return response("confirmed", evidence, result)
    except Exception as exc:
        # Missing formal proof is different from an unreadable/corrupt proof.
        if getattr(exc, "code", "") in {"OPERATION_UNCONFIRMED", "FLOW_START_UNCONFIRMED"}:
            return response("requires_review")
        return response("unavailable")


def public_receipt(payload, action, request_id, parameters=None):
    from .contracts import ReceiptResponse
    receipt = ReceiptResponse.model_validate(payload)
    if receipt.action != action or receipt.requestId != request_id:
        raise ValueError("Native request identity changed")
    field = RESULT_FIELDS[action]
    result = getattr(receipt, field)
    if receipt.status == "completed":
        if receipt.verified is not True or receipt.code is not None or result is None:
            raise ValueError("Native acknowledgement is missing")
        native = native_result(action, result.model_dump(exclude_none=True))
        if parameters is not None:
            verify_target(action, native, parameters)
    elif receipt.verified is not False or receipt.code != "OPERATION_UNCONFIRMED" or result is not None:
        raise ValueError("Unconfirmed request cannot carry a success result")
    if any(getattr(receipt, key) is not None for key in
           ("agent", "session", "authorization", "purge", "operation", "asset", "flow", "research", "recovery", "teamRun", "phase", "resumeAllowed") if key != field):
        raise ValueError("Unexpected native result for this action")
    result = receipt.model_dump(exclude_none=True)
    if action == "runtime_command" and "operation" in result:
        result["operation"]["operation"].pop("progressFingerprint", None)
    return result
