"""CAS repair for legacy agent-archive owner splits in the session directory.

The runtime payload's ``agent_archive`` seal is the durable proof of which
Agent owned a session at seal time. Legacy rows whose ``sessions.agent_id``
drifted to a different Agent while the payload seal stayed intact (the
2026-10-20 incident shape) are rebound here. The seal is the only accepted
proof, and live session families or admissions are never migrated.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def archived_payload_owner(payload: Mapping[str, Any]) -> str:
    """Return the agent id proven by a canonical agent_archive seal, or ''.

    A seal only proves ownership when the payload's own agent id and the
    seal's ``agentId`` agree; anything else seals visibility at most.
    """

    archive = payload.get("archive_state") or payload.get("archiveState") or {}
    if not isinstance(archive, Mapping):
        return ""
    if str(archive.get("status") or "").strip().lower() != "archived":
        return ""
    if str(archive.get("source") or "").strip() != "agent_archive":
        return ""
    agent_id = str(payload.get("agent_id") or payload.get("agentId") or "").strip()
    sealed_agent_id = str(archive.get("agentId") or "").strip()
    if not agent_id or agent_id != sealed_agent_id:
        return ""
    return agent_id


def repair_archived_directory_owner(
    connection: Any,
    *,
    session_id: str,
    expected_agent_id: str,
    agent_id: str,
    agent_config_revision_id: str,
    now_ms: int,
) -> dict[str, str]:
    """CAS rebind for a proven, sealed legacy session; never migrate live rows."""

    runtime = connection.execute(
        "SELECT payload_json FROM session_runtime_state WHERE session_id=?",
        (session_id,),
    ).fetchone()
    payload = json.loads(runtime["payload_json"]) if runtime is not None else {}
    if archived_payload_owner(payload) != agent_id:
        raise ValueError("Directory owner repair requires the current Agent archive seal.")
    row = connection.execute(
        "SELECT agent_id, parent_session_id FROM sessions WHERE session_id=?",
        (session_id,),
    ).fetchone()
    if row is None or str(row["agent_id"] or "") != str(expected_agent_id).strip():
        raise ValueError("Directory owner changed before repair.")
    if row["parent_session_id"] or connection.execute(
        "SELECT 1 FROM sessions WHERE parent_session_id=? LIMIT 1", (session_id,),
    ).fetchone():
        raise ValueError("Directory owner repair cannot migrate a session family.")
    if connection.execute(
        "SELECT 1 FROM session_admissions WHERE session_id=? "
        "AND state IN ('reserved','journaled') LIMIT 1",
        (session_id,),
    ).fetchone():
        raise ValueError("Directory owner repair cannot migrate an active admission.")
    revision = str(agent_config_revision_id or "").strip()
    if not connection.execute(
        "SELECT 1 FROM agent_config_revisions WHERE agent_id=? AND revision_id=?",
        (agent_id, revision),
    ).fetchone():
        raise ValueError("Directory owner repair requires a persisted Agent config revision.")
    connection.execute(
        "UPDATE sessions SET agent_id=?, agent_config_revision_id=?, "
        "archived_at_ms=COALESCE(archived_at_ms,?), updated_at_ms=? "
        "WHERE session_id=? AND agent_id=?",
        (agent_id, revision, now_ms, now_ms, session_id, str(expected_agent_id).strip()),
    )
    return {
        "sessionId": session_id,
        "agentId": agent_id,
        "previousAgentId": str(expected_agent_id).strip(),
        "action": "repaired",
    }
