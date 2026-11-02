"""Complete review metadata for bounded goal and platform recovery actions."""
import hashlib
import json

AUTONOMY_ACTIONS = frozenset({"delegation_goal_create", "delegation_goal_revoke", "dispatch_derived",
    "research_command", "authorization_reduce", "authorization_revoke"})


def approval_summary(action, parameters):
    if action not in AUTONOMY_ACTIONS:
        raise ValueError("Unknown autonomy action")
    from .actions import _management_contracts
    from .platform_approval import _decimal_values
    values = _management_contracts()[action][0].model_validate(parameters).model_dump()
    digest = hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    task = values.pop("task", None)
    summary = {"assistantAction": action, "assistantAutonomyPreviewVersion": 1,
        "assistantParametersDigest": digest, "assistantDetailsOmitted": False,
        "assistantTargets": _decimal_values(values)}
    if task is not None:
        summary.update(assistantTask=task, assistantTaskChars=str(len(task)),
            assistantTaskDigest=hashlib.sha256(task.encode()).hexdigest(),
            assistantRequestedPermission=values["permission_profile"])
    return summary
