"""Small native acknowledgements for the additive platform control actions."""
from .asset_contracts import ASSET_ACTION_MODELS, AssetMutationResponse
from .flow_contracts import FLOW_ACTION_MODELS, FlowMutationResponse
from .runtime_contracts import RuntimeCommandResponse


PLATFORM_ACTIONS = frozenset({"runtime_command", *ASSET_ACTION_MODELS, *FLOW_ACTION_MODELS})
RESULT_FIELDS = {"runtime_command": "operation", **{key: "asset" for key in ASSET_ACTION_MODELS},
                 **{key: "flow" for key in FLOW_ACTION_MODELS}}


def native_result(action, raw):
    model = (RuntimeCommandResponse if action == "runtime_command" else
             AssetMutationResponse if action in ASSET_ACTION_MODELS else FlowMutationResponse)
    result = model.model_validate(raw).model_dump(exclude_none=True)
    if action != "runtime_command" and (result["action"] != action or result["verified"] is not True):
        raise ValueError("Native acknowledgement is not verified for this action")
    return result


def verify_target(action, result, parameters):
    if action == "runtime_command":
        operation = result["operation"]
        valid = (operation["kind"] == parameters["kind"] and operation["resourceId"] == parameters["resource_id"]
            and result["command"] == parameters["command"]
            and all(operation.get(output, "") == parameters.get(key, "") for key, output in
                    (("session_id", "sessionId"), ("team_id", "teamId"), ("flow_id", "flowId")) if parameters.get(key)))
    elif action in ASSET_ACTION_MODELS:
        target = next(parameters[key] for key in ("agent_id", "team_id", "knowledge_base_id") if key in parameters)
        valid = result["action"] == action and result["resourceId"] == target
    else:
        valid = (result["action"] == action and result["teamId"] == parameters["team_id"]
                 and result["flowId"] == parameters["flow_id"])
    if not valid:
        raise ValueError("Native acknowledgement target changed")


def execute(native, action, parameters, marker):
    if action == "runtime_command":
        raw = native.runtime_command(parameters, marker)
    elif action in ASSET_ACTION_MODELS:
        from .asset_control import AssetControl
        method = {"team_update": "update_team", "agent_tool_policy_update": "update_tool_policy",
            "knowledge_acl_grant": "grant_knowledge_acl", "knowledge_acl_revoke": "revoke_knowledge_acl"}[action]
        raw = getattr(AssetControl(native), method)(parameters, marker)
    else:
        from .flow_control import FlowControl
        owner = FlowControl(native)
        raw = (owner.save_flow(parameters) if action == "flow_save"
               else owner.start_flow(parameters, request_id=marker["requestKey"]))
    result = native_result(action, raw)
    verify_target(action, result, parameters)
    return result


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
           ("agent", "session", "authorization", "purge", "operation", "asset", "flow", "teamRun", "phase", "resumeAllowed") if key != field):
        raise ValueError("Unexpected native result for this action")
    return receipt.model_dump(exclude_none=True)
