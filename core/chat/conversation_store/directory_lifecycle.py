"""CAS repair for drifted owners in the session directory.

Two proof shapes rebind a ``sessions.agent_id`` that no longer matches the
runtime payload's Agent. An ``agent_archive`` seal proves which Agent owned
a session at seal time (the 2026-10-20 incident shape); a live Agent's
direct-session claim proves the live rebind behind an Agent rebind. Both
repairs refuse session families and active admissions, and the seal repair
never touches live rows.
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


def repair_live_directory_owner(
    connection: Any,
    *,
    session_id: str,
    expected_agent_id: str,
    agent_id: str,
    agent_config_revision_id: str,
    now_ms: int,
) -> dict[str, str]:
    """CAS rebind for a live row whose payload Agent holds the direct claim.

    The bridge only dispatches this after proving the payload Agent is live
    and claims the session as its own direct session; the store keeps its own
    guards: live rows only (sealed rows keep the archive-seal repair), no
    session families, no active admissions, and a persisted target config
    revision. Rebinding an already-rebound row is a reported noop so a stale
    ``expected_agent_id`` read racing a concurrent repair never fails.
    """

    row = connection.execute(
        "SELECT agent_id, parent_session_id, archived_at_ms FROM sessions WHERE session_id=?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Directory owner repair requires an existing session row.")
    if row["archived_at_ms"] is not None:
        raise ValueError("Directory owner repair does not rebind sealed rows.")
    target_agent_id = str(agent_id).strip()
    if str(row["agent_id"] or "") == target_agent_id:
        return {
            "sessionId": session_id,
            "agentId": target_agent_id,
            "previousAgentId": target_agent_id,
            "action": "already_bound",
        }
    if str(row["agent_id"] or "") != str(expected_agent_id).strip():
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
        "UPDATE sessions SET agent_id=?, agent_config_revision_id=?, updated_at_ms=? "
        "WHERE session_id=? AND agent_id=?",
        (agent_id, revision, now_ms, session_id, str(expected_agent_id).strip()),
    )
    return {
        "sessionId": session_id,
        "agentId": target_agent_id,
        "previousAgentId": str(expected_agent_id).strip(),
        "action": "repaired",
    }
