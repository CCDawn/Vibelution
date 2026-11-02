"""Batch admission for the archived-agent purge; one approval, per-item receipts.

The batch adds no second deletion authority: admission reuses the single
delete's existing-only read-only preview for every target before any native
side effect, and execution reuses the exact same native purge core per item.
"""
from __future__ import annotations

from .contracts import AgentPurgeResult
from .service import ManagementError


def prevalidate(native, parameters):
    """Existing-only, read-only admission for every target; nothing executes.

    Returns ``{agent_id: code}`` for every rejected target. The caller rejects
    the whole batch when this mapping is non-empty (all-or-nothing admission),
    so one stale revision can never silently delete the remaining list.
    """
    rejections = {}
    for item in parameters["purges"]:
        agent_id = item["agent_id"]
        try:
            agent = native.read_purge_preview(agent_id)
            if not isinstance(agent, dict) or agent.get("agentId") != agent_id:
                rejections[agent_id] = "AGENT_UNAVAILABLE"
            elif agent.get("configRevision") != item["expected_config_revision"]:
                rejections[agent_id] = "STATE_CONFLICT"
        except ManagementError as exc:
            rejections[agent_id] = exc.code
        except (OSError, ValueError, TypeError, KeyError):
            rejections[agent_id] = "AGENT_UNAVAILABLE"
    return rejections


def purge_item(native, item, marker):
    """Execute one admitted target through the single-delete core."""
    agent_id = item["agent_id"]
    try:
        result = AgentPurgeResult.model_validate(native.purge({"agent_id": agent_id,
            "expected_config_revision": item["expected_config_revision"]}, marker))
        if result.agentId != agent_id:
            raise ValueError("Mismatched native purge acknowledgement")
        return {"agentId": agent_id, "outcome": "purged", "cleanupPending": result.cleanupPending}
    except ManagementError as exc:
        if exc.code == "OPERATION_UNCONFIRMED":
            # A lost acknowledgement stays unknown; it is never re-executed
            # under this or any other request id.
            return {"agentId": agent_id, "outcome": "unknown", "code": exc.code}
        # Admission denials raise before any native write, so they are proven
        # no-write rejections and never poison the surviving items.
        return {"agentId": agent_id, "outcome": "rejected", "code": exc.code}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # The native owner may already have deleted records; absence is not ACK.
        return {"agentId": agent_id, "outcome": "unknown", "code": "OPERATION_UNCONFIRMED"}
