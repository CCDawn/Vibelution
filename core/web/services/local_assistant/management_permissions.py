"""Launcher management approval settings, separate from native tool permissions.

Only the trusted native host setter writes this metadata. Ordinary Agent
permissionPreset, ToolPolicy and accepted Session configuration stay untouched.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from core.web.services.agent_config_authority import PERMISSION_PRESETS

METADATA_KEY = "launcherManagementApproval"
MAX_SAFE_REVISION = 2**53 - 1
_metadata_write_context: ContextVar[tuple[str, str, int] | None] = ContextVar(
    "launcher_management_permission_write", default=None)


class ManagementPermissionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _valid_revision(value: Any) -> bool:
    return type(value) is int and 0 <= value <= MAX_SAFE_REVISION


def assert_metadata_write_allowed(agent_id: str, metadata: dict | None) -> None:
    """Canonical Agent mutators reject model/operator JSON for this reserved key.

    Authorization exists only during this owner's exact one-field update; it
    cannot be supplied as an Agent update field or inherited by another thread.
    """
    if metadata is None:
        return
    if not isinstance(metadata, dict):
        raise ManagementPermissionError("ASSISTANT_PERMISSION_INVALID")
    if METADATA_KEY not in metadata:
        return
    context = _metadata_write_context.get()
    policy = metadata[METADATA_KEY]
    if (context is None or context[0] != agent_id or not isinstance(policy, dict)
            or set(policy) != {"preset", "revision"} or not isinstance(policy["preset"], str)
            or not _valid_revision(policy["revision"])
            or (policy["preset"], policy["revision"]) != context[1:]):
        raise ManagementPermissionError("ASSISTANT_PERMISSION_INVALID")


def projection(agent: dict) -> dict[str, str | int]:
    """Pure projection; only absent metadata gets the compatibility default."""
    metadata = agent.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ManagementPermissionError("ASSISTANT_PERMISSION_UNAVAILABLE")
    if METADATA_KEY not in metadata:
        return {"preset": "request_approval", "revision": 0}
    policy = metadata[METADATA_KEY]
    if (not isinstance(policy, dict) or set(policy) != {"preset", "revision"}
            or not isinstance(policy["preset"], str) or policy["preset"] not in PERMISSION_PRESETS
            or not _valid_revision(policy["revision"])):
        raise ManagementPermissionError("ASSISTANT_PERMISSION_UNAVAILABLE")
    return {"preset": policy["preset"], "revision": policy["revision"]}


def read(agent_id: str) -> dict[str, str | int]:
    """Read only the active singleton; never provision or repair its identity."""
    from core.web.services import personal_assistant_service as personal
    try:
        with personal._LOCK:
            agent = personal._active_profile_agent()
            if not isinstance(agent_id, str) or not agent_id or agent["agentId"] != agent_id:
                raise ManagementPermissionError("ASSISTANT_PERMISSION_UNAVAILABLE")
            return projection(agent)
    except ManagementPermissionError:
        raise
    except Exception:
        raise ManagementPermissionError("ASSISTANT_PERMISSION_UNAVAILABLE") from None


def update(
    preset: str,
    expected_revision: int,
    *,
    expected_agent_id: str | None = None,
    expected_session_id: str | None = None,
) -> dict[str, str | int]:
    """CAS one metadata field; callable only from the trusted native setter.

    The lifecycle and registry locks cover the final active identity read, both
    revision checks and merge/write. The ordinary Agent updater performs its
    own updatedAt CAS and preserves unrelated metadata.
    """
    from core.web.services import agent_directory_service as directory
    from core.web.services import personal_assistant_service as personal
    if not isinstance(preset, str) or preset not in PERMISSION_PRESETS or not _valid_revision(expected_revision):
        raise ManagementPermissionError("ASSISTANT_PERMISSION_INVALID")
    if ((expected_agent_id is not None or expected_session_id is not None)
            and (not isinstance(expected_agent_id, str) or not expected_agent_id
                 or not isinstance(expected_session_id, str) or not expected_session_id)):
        raise ManagementPermissionError("ASSISTANT_PERMISSION_UNAVAILABLE")
    try:
        with personal._LOCK, directory.agent_session_lifecycle_transaction(), directory._STATE_LOCK:
            try:
                agent = personal._active_profile_agent()
            except directory.AgentDirectoryError:
                raise ManagementPermissionError("ASSISTANT_PERMISSION_UNAVAILABLE") from None
            # Native callers bind both IDs before the first settings read.
            # Generic directory writers do not share personal._LOCK, so only
            # this final lifecycle/state-locked check closes identity rebinding.
            if (expected_agent_id is not None
                    and (agent.get("agentId"), agent.get("directSessionId"))
                        != (expected_agent_id, expected_session_id)):
                raise ManagementPermissionError("ASSISTANT_PERMISSION_UNAVAILABLE")
            current = projection(agent)
            if current["revision"] != expected_revision:
                raise ManagementPermissionError("ASSISTANT_PERMISSION_CONFLICT")
            if current["preset"] == preset:
                return current
            if expected_revision == MAX_SAFE_REVISION:
                raise ManagementPermissionError("ASSISTANT_PERMISSION_UNAVAILABLE")
            updated_at = agent.get("updatedAt")
            if not isinstance(updated_at, str) or not updated_at:
                raise ManagementPermissionError("ASSISTANT_PERMISSION_UNAVAILABLE")
            policy = {"preset": preset, "revision": expected_revision + 1}
            token = _metadata_write_context.set((agent["agentId"], preset, expected_revision + 1))
            try:
                updated = directory.update_agent_instance(agent["agentId"],
                    metadata={METADATA_KEY: policy}, expected_updated_at=updated_at)
            finally:
                _metadata_write_context.reset(token)
            if projection(updated) != policy:
                raise ManagementPermissionError("ASSISTANT_PERMISSION_UNAVAILABLE")
            return policy
    except ManagementPermissionError:
        raise
    except directory.AgentStateConflictError:
        raise ManagementPermissionError("ASSISTANT_PERMISSION_CONFLICT") from None
    except Exception:
        raise ManagementPermissionError("ASSISTANT_PERMISSION_UNAVAILABLE") from None
