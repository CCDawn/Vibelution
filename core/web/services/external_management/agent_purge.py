"""Existing-only purge admission and the canonical operator lifecycle adapter."""
from __future__ import annotations

from contextlib import ExitStack

from fastapi import HTTPException
from pydantic import ValidationError

from .archive_state import ArchiveState
from .contracts import AgentPurge, AgentPurgeResult
from .service import ManagementError


def _target(gateway, directory, agent_id):
    if not isinstance(agent_id, str) or not 1 <= len(agent_id) <= 128:
        raise ManagementError("INVALID_INPUT", 422)
    raw = ArchiveState(gateway.project_root, directory).agent(agent_id)
    if raw is None:
        raise ManagementError("AGENT_UNAVAILABLE", 404)
    if raw.get("status") != "archived":
        raise ManagementError("STATE_CONFLICT", 409)
    if directory._agent_archive_protected(raw):
        raise ManagementError("AGENT_PROTECTED", 403)
    revision = raw.get("configRevision")
    if type(revision) is not int or revision < 0:
        raise ManagementError("STATE_CONFLICT", 409)
    # Reuse the native lexical private-workspace and junction boundary before
    # any getter can repair state or lifecycle owner can remove references.
    try:
        directory.ensure_agent_purge_workspace_deletable(raw)
    except directory.AgentDirectoryError:
        raise ManagementError("AGENT_PROTECTED", 403) from None
    metadata = raw.get("metadata")
    avatar = directory._agent_avatar_path_from_metadata(metadata if isinstance(metadata, dict) else {})
    return {**raw, "avatarImagePath": avatar}


def preview(gateway, agent_id):
    directory = gateway._owners()
    try:
        with directory._STATE_LOCK:
            return _target(gateway, directory, agent_id)
    except ManagementError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise ManagementError("AGENT_UNAVAILABLE", 503) from None


def purge(gateway, parameters):
    from core.web.routes import agents as owner
    from core.web.services import session_service as sessions

    try:
        parameters = AgentPurge.model_validate(parameters).model_dump()
    except ValidationError:
        raise ManagementError("INVALID_INPUT", 422) from None
    directory = gateway._owners()
    agent_id = parameters["agent_id"]
    try:
        # Check raw existing authority before entering native legacy readers.
        preview(gateway, agent_id)
        with ExitStack() as lifecycle:
            with sessions.agent_archive_transaction(agent_id):
                with directory._STATE_LOCK:
                    current = _target(gateway, directory, agent_id)
                    if current["configRevision"] != parameters["expected_config_revision"]:
                        raise ManagementError("STATE_CONFLICT", 409)
                # Retain the canonical reentrant lifecycle locks before
                # releasing admission handles: on Windows those handles live
                # inside Session workspaces and prevent the native staged move.
                # The shared chat lock's nested transaction stack keeps its
                # original cross-process lock held until this outer stack exits.
                lifecycle.enter_context(sessions.session_agent_lifecycle_transaction(timeout=30.0))
            # The full native owner stages every Session, removes references,
            # purges the Agent and commits or compensates Session cleanup.
            try:
                result = owner.agent_purge(agent_id)
            except HTTPException as exc:
                if isinstance(exc.__cause__, sessions.SessionBusyError):
                    # Native staging rejects busy Sessions before any write.
                    raise ManagementError("AGENT_BUSY", 409) from None
                # Other failures can follow partial effects or incomplete
                # compensation. Do not persist them as proven no-write denials.
                raise ManagementError("OPERATION_UNCONFIRMED", 503) from exc
            try:
                if (result.get("agentId") != agent_id or result.get("status") != "purged"
                    or result.get("deleted") is not True):
                    raise ValueError("Missing native deletion acknowledgement")
                pending = result["purgeSummary"]["sessions"]["cleanupPending"]
                return AgentPurgeResult.model_validate({"agentId": agent_id, "status": "purged",
                    "cleanupPending": pending}).model_dump()
            except (AttributeError, ValueError, TypeError, KeyError):
                raise ManagementError("OPERATION_UNCONFIRMED", 503) from None
    except sessions.SessionBusyError:
        raise ManagementError("AGENT_BUSY", 409) from None
    except ManagementError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        # The native owner may already have deleted records; absence is not ACK.
        raise ManagementError("OPERATION_UNCONFIRMED", 503) from None
