"""Read-only Challenge Cup inventory adapter.

This module is the bridge between governed list/readback owners and
``ChallengeCupResetService``. It never opens SQLite, walks a data directory,
or calls a lifecycle/purge operation. A missing read owner becomes an empty
identity sentinel, which the existing reset service turns into a blocker.
Only bounded identity/status metadata crosses this boundary; chat content and
prompts are intentionally not copied or hashed.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


SCHEMA_VERSION = 1
RESEARCH_TEAM_ID = "research-team"
ACTIVE_STATUSES = frozenset(
    {
        "queued",
        "starting",
        "dispatching",
        "running",
        "stopping",
        "paused",
        "waiting_human",
        "summarizing",
        "awaiting_approval",
        "collecting",
    }
)

ARTIFACT_KINDS = (
    "run_artifacts",
    "research_result_package",
    "smoke_evidence",
    "smoke_release",
    "frozen_protocol",
    "evaluation_report",
    "hypothesis_fragment",
    "hypothesis_set",
    "research_plan",
    "protocol_draft",
    "protocol_review_report",
    "iteration_decision",
    "version_governance_record",
    "delivery_orchestration_result",
    "problem_understanding",
    "dimension_reviews",
    "feedback_iterations",
    "stage1_research_plan",
    "competition_alignment",
    "stage_one_completion_manifest",
    "evolution_lineage",
    "candidate_screening",
    "core_hypothesis_coherence",
    "review_independence",
    "review_disagreement",
)
ARTIFACT_FAMILY_BY_KIND = {
    "research_plan": "plans",
    "protocol_draft": "plans",
    "hypothesis_fragment": "candidates",
    "hypothesis_set": "candidates",
    "iteration_decision": "selections",
    "research_result_package": "results",
    "evaluation_report": "results",
    "smoke_evidence": "results",
    "smoke_release": "results",
}
PROTECTION_FAMILIES = ("teams", "agents", "sessions", "rooms", "meetings", "workflowRuns", "projects", "artifacts")

_ID_KEYS = (
    "id",
    "teamId",
    "team_id",
    "agentId",
    "agent_id",
    "sessionId",
    "session_id",
    "roomId",
    "room_id",
    "roundId",
    "round_id",
    "meetingRoundId",
    "meeting_round_id",
    "runId",
    "run_id",
    "workflowRunId",
    "workflow_run_id",
    "recordId",
    "artifactId",
    "artifact_id",
    "checkpointId",
    "checkpoint_id",
    "receiptId",
    "receipt_id",
    "projectId",
    "project_id",
    "planId",
    "plan_id",
    "candidateId",
    "candidate_id",
    "selectionId",
    "selection_id",
    "catalogId",
    "catalog_id",
    "programId",
    "program_id",
    "policyId",
    "policy_id",
)
_FAMILY_ID_KEYS = {
    "teams": ("teamId", "team_id", "id"),
    "agents": ("agentId", "agent_id", "id"),
    "sessions": ("sessionId", "session_id", "id"),
    "rooms": ("roomId", "room_id", "id"),
    "meetings": ("meetingRoundId", "meeting_round_id", "id"),
    "rounds": ("roundId", "round_id", "id"),
    "workflowRuns": ("workflowRunId", "workflow_run_id", "runId", "run_id", "id"),
    "plans": ("planId", "plan_id", "recordId", "artifactId", "artifact_id", "id"),
    "candidates": ("candidateId", "candidate_id", "recordId", "artifactId", "artifact_id", "id"),
    "selections": ("selectionId", "selection_id", "recordId", "artifactId", "artifact_id", "id"),
    "results": ("recordId", "artifactId", "artifact_id", "id"),
    "artifacts": ("recordId", "artifactId", "artifact_id", "id"),
    "receipts": ("receiptId", "receipt_id", "id"),
    "checkpoints": ("checkpointId", "checkpoint_id", "id"),
}
_SAFE_KEYS = {
    "status",
    "state",
    "currentPhase",
    "kind",
    "runKind",
    "workflowId",
    "scopeHash",
    "discussionScopeHash",
    "questionId",
    "projectId",
    "researchProjectId",
    "workflowRunId",
    "workflowNodeId",
    "selectionId",
    "candidateId",
    "roleKey",
    "agentId",
    "sessionId",
    "roomId",
    "roundId",
    "meetingRoundId",
    "activeRoundId",
    "createdAt",
    "updatedAt",
    "finishedAt",
    "immutable",
    "sha256",
    "contentHash",
    "recordId",
    "sourceCollectionRunId",
    "questionCount",
}
_ALIASES = {
    "agentId": ("agentId", "agent_id"),
    "roleKey": ("roleKey", "role_key", "agentRoleKey", "role"),
    "questionId": ("questionId", "question_id"),
    "researchProjectId": ("researchProjectId", "research_project_id"),
    "workflowRunId": ("workflowRunId", "workflow_run_id"),
    "workflowNodeId": ("workflowNodeId", "workflow_node_id"),
    "selectionId": ("selectionId", "selection_id"),
    "candidateId": ("candidateId", "candidate_id"),
    "scopeHash": ("scopeHash", "scope_hash"),
    "discussionScopeHash": ("discussionScopeHash", "discussion_scope_hash"),
    "sessionId": ("sessionId", "session_id"),
    "roomId": ("roomId", "room_id"),
    "roundId": ("roundId", "round_id"),
    "meetingRoundId": ("meetingRoundId", "meeting_round_id"),
}


class LiveInventoryAuthorityError(RuntimeError):
    """A required managed read owner is unavailable."""


def _text(value: Any, *, upper: bool = False, limit: int = 240) -> str:
    value = str(value or "").strip()[:limit]
    return value.upper() if upper else value


def _first(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return ""


def _nested(item: Mapping[str, Any], *keys: str) -> Any:
    value = _first(item, *keys)
    if value not in (None, ""):
        return value
    for container in ("scope", "config", "metadata", "binding", "experimentBinding", "roomConfig"):
        nested = item.get(container)
        if isinstance(nested, Mapping):
            value = _first(nested, *keys)
            if value not in (None, ""):
                return value
    return ""


def _record_id(item: Any) -> str:
    if isinstance(item, str):
        return _text(item, limit=320)
    if not isinstance(item, Mapping):
        return ""
    return _text(_first(item, *_ID_KEYS), limit=320)


def _owner(item: Mapping[str, Any], agent_team_by_id: Mapping[str, str]) -> str:
    owner = _text(
        _nested(item, "teamId", "team_id", "ownerTeamId", "owner_team_id", "researchTeamId")
    )
    if owner:
        return owner
    agent_id = _text(_nested(item, "agentId", "agent_id"))
    return _text(agent_team_by_id.get(agent_id)) if agent_id else ""


def _rows(value: Any, *keys: str) -> list[Any]:
    if isinstance(value, Mapping):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes, bytearray)):
                return list(candidate)
        return [value] if _record_id(value) else []
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else []


def _safe_record(
    item: Any,
    *,
    family: str,
    owner_team_id: str = "",
    agent_team_by_id: Mapping[str, str] | None = None,
    role_by_id: Mapping[str, str] | None = None,
    source_kind: str = "",
    immutable: bool | None = None,
    observation_only_fields: Sequence[str] = (),
) -> dict[str, Any]:
    source = item if isinstance(item, Mapping) else {"id": item}
    identifier = _text(
        _first(source, *_FAMILY_ID_KEYS.get(family, _ID_KEYS)),
        limit=320,
    )
    payload: dict[str, Any] = {"id": identifier}
    owner = owner_team_id or _owner(source, agent_team_by_id or {})
    if owner:
        payload["teamId"] = owner
    for public_key, aliases in _ALIASES.items():
        value = _nested(source, *aliases)
        if value not in (None, ""):
            payload[public_key] = _text(value, upper=public_key == "questionId")
    for key in _SAFE_KEYS:
        if key in payload or key not in source:
            continue
        value = source[key]
        if isinstance(value, (str, int, float, bool)):
            payload[key] = _text(value, limit=160) if isinstance(value, str) else value
    if payload.get("agentId") and not payload.get("roleKey") and role_by_id:
        payload["roleKey"] = _text(role_by_id.get(payload["agentId"]))
    if source_kind:
        payload["sourceKind"] = _text(source_kind, limit=120)
    if immutable is not None:
        payload["immutable"] = bool(immutable)
    payload["sourceFamily"] = _text(family, limit=80)
    normalized_observation_fields = sorted(
        {
            _text(field, limit=80)
            for field in observation_only_fields
            if _text(field, limit=80)
        }
    )
    if normalized_observation_fields:
        payload["observationOnlyFields"] = normalized_observation_fields
    return payload


def _looks_challenge_scoped(item: Any) -> bool:
    """Keep ambiguous Challenge-shaped records fail-closed, but not unrelated sessions.

    The global Session inventory also contains ordinary personal and system
    conversations with no team authority.  They must remain outside both the
    target delete set and the other-team snapshot.  A row that advertises a
    Challenge Cup / hypothesis / workflow scope is different: without a
    provable team owner it remains in the bounded inventory so the reset
    service blocks rather than silently overlooking target data.
    """

    if not isinstance(item, Mapping):
        return False
    source = _text(
        _nested(
            item,
            "source",
            "sourceKind",
            "workflowKind",
            "workflowId",
            "teamKind",
        ),
        limit=240,
    ).lower()
    if any(token in source for token in ("challenge", "hypothesis", "research_workflow")):
        return True
    return bool(
        _nested(
            item,
            "questionId",
            "question_id",
            "researchProjectId",
            "research_project_id",
            "workflowRunId",
            "workflow_run_id",
        )
    )


def _member_owned_team(item: Any, agent_team_by_id: Mapping[str, str]) -> str:
    """Resolve Agent-derived ownership only from the current Team membership graph."""

    if not isinstance(item, Mapping):
        return ""
    agent_id = _text(_nested(item, "agentId", "agent_id"))
    if agent_id:
        return _text(agent_team_by_id.get(agent_id))
    return _owner(item, agent_team_by_id)


def _reset_inventory_records(
    rows: Sequence[Any],
    *,
    agent_team_by_id: Mapping[str, str],
) -> list[Any]:
    """Return only records with a proven owner or explicit Challenge scope."""

    return [
        item
        for item in rows
        if isinstance(item, Mapping)
        and (
            _member_owned_team(item, agent_team_by_id)
            or _looks_challenge_scoped(item)
        )
    ]


def _sentinel(family: str, reason: str) -> dict[str, Any]:
    return {
        "id": "",
        "sourceFamily": _text(family, limit=80),
        "authorityMissing": _text(reason, limit=160) or "authority_missing",
    }


def _status(item: Mapping[str, Any]) -> str:
    return _text(_first(item, "status", "state", "currentPhase")).lower()


# Managed defaults are late-bound so constructing this reader performs no live
# read and no data-root initialization.
def _list_teams() -> Any:
    from core.web.services import team_service

    return team_service.list_team_graph_references(include_archived=True)


def _list_agents() -> Any:
    from core.web.services import agent_directory_service

    return agent_directory_service.list_agents(include_archived=True, detail="summary")


def _list_sessions() -> Any:
    from core.web.services import session_service

    return session_service.list_sessions(include_hidden_internal=True, repair_collisions=False)


def _list_rooms() -> Any:
    from core.web.services import chat_room_service

    # Every public room-list facade currently reconciles orphan rounds before
    # returning and can persist that repair.  Reset PREVIEW must be strictly
    # read-only, so use the room owner's bounded store load until it exposes a
    # zero-write read facade.  Do not call detail/list APIs here: they can also
    # repair participant bindings and would mutate the inventory being hashed.
    return chat_room_service.read_chat_rooms_snapshot()


def _list_meetings(team_id: str) -> Any:
    from core.web.services.team_workflow import meeting_rounds

    return meeting_rounds.list_meeting_rounds(team_id)


def _list_runs(team_id: str) -> Any:
    """Read the formal ledger when it is available, otherwise the legacy run store.

    Reset inventory must not silently omit formal runs merely because the
    process also still exposes the transitional JSON-run facade.  A formal
    reader which is unavailable is an expected migration state, so only that
    bounded condition falls back to the legacy owner.
    """

    try:
        from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
        from core.web.services.team_workflow.research_runtime.formal_read_runtime import (
            FormalReadRuntimeUnavailable,
            get_query_service,
        )

        return get_query_service().list_runs(
            team_id=team_id,
            workflow_id=CHALLENGE_CUP_WORKFLOW_ID,
        )
    except FormalReadRuntimeUnavailable:
        from core.web.services.team_workflow.research_runtime.service import (
            get_research_workflow_runtime_service,
        )

        return get_research_workflow_runtime_service().list_runs(team_id=team_id)


def _run_scope_rows(team_id: str) -> list[dict[str, str]]:
    """Build only explicitly provable checkpoint/receipt scope authority.

    The destructive ports deliberately reject a path-only or inferred scope.
    When a ledger row lacks the fields they need, PREVIEW is blocked rather
    than trying to recover ownership from a filename or a UI projection.
    """

    payload = _list_runs(team_id)
    rows = _rows(payload, "runs", "workflowRuns")
    result: list[dict[str, str]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise LiveInventoryAuthorityError("workflow run authority is malformed")
        owner = _text(_first(raw, "teamId", "team_id"))
        if owner != team_id:
            raise LiveInventoryAuthorityError("workflow run authority has a team mismatch")
        run_id = _text(_first(raw, "runId", "run_id", "workflowRunId", "workflow_run_id", "id"))
        thread_id = _text(_first(raw, "threadId", "thread_id", "workflowThreadId"))
        if not run_id or not thread_id or run_id != thread_id:
            raise LiveInventoryAuthorityError("workflow run lacks matching run/thread authority")
        item = {
            "teamId": team_id,
            "runId": run_id,
            "threadId": thread_id,
            "scopeHash": _text(_first(raw, "scopeHash", "scope_hash")).lower(),
            "questionId": _text(_first(raw, "questionId", "question_id"), upper=True),
            "projectId": _text(_first(raw, "projectId", "project_id", "researchProjectId")),
        }
        result.append(item)
    # A pre-formal runtime used ``thread-<workflowRunId>`` checkpoint threads
    # before the ledger began persisting matching run/thread rows.  That
    # legacy convention is not enough by itself: it is admitted only when a
    # current team-owned canonical workflow artifact proves the exact run and
    # the checkpoint port subsequently validates the stored team/run fields.
    # Any unpaired checkpoint thread remains a hard blocker.
    from core.research.workflow.checkpoint_store import list_checkpoint_thread_ids
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        list_workflow_artifacts,
    )

    checkpoint_threads = set(list_checkpoint_thread_ids())
    by_thread = {item["threadId"]: item for item in result}
    if not checkpoint_threads:
        return sorted(by_thread.values(), key=lambda item: item["runId"])
    legacy_threads: dict[str, dict[str, str]] = {}
    for kind in ARTIFACT_KINDS:
        for artifact in list_workflow_artifacts(team_id, kind=kind):
            if not isinstance(artifact, Mapping):
                raise LiveInventoryAuthorityError("legacy artifact run authority is malformed")
            if _text(_first(artifact, "teamId", "team_id")) != team_id:
                raise LiveInventoryAuthorityError("legacy artifact run authority has a team mismatch")
            workflow_run_id = _text(_first(artifact, "workflowRunId", "workflow_run_id"))
            if not workflow_run_id:
                continue
            thread_id = f"thread-{workflow_run_id}"
            if thread_id not in checkpoint_threads:
                continue
            candidate = {
                "teamId": team_id,
                "runId": thread_id,
                "threadId": thread_id,
                "scopeHash": "",
                "questionId": "",
                "projectId": "",
            }
            previous = legacy_threads.get(thread_id) or by_thread.get(thread_id)
            if previous is not None and previous != candidate:
                raise LiveInventoryAuthorityError("legacy checkpoint thread authority conflicts")
            legacy_threads[thread_id] = candidate
    by_thread.update(legacy_threads)
    unresolved_threads = checkpoint_threads - set(by_thread)
    if unresolved_threads:
        raise LiveInventoryAuthorityError("checkpoint thread scope authority is absent")
    return sorted(by_thread.values(), key=lambda item: item["runId"])


def _list_checkpoints(team_id: str) -> Any:
    from core.research.workflow.checkpoint_store import (
        checkpoint_store_has_rows,
        default_checkpoint_path,
        list_team_scoped_checkpoints,
    )

    authority = _run_scope_rows(team_id)
    path = default_checkpoint_path()
    if not authority:
        # An empty, absent store has no reset work.  A non-empty store without
        # run/thread authority is dangerous and must be reported as unavailable.
        if checkpoint_store_has_rows(path):
            raise LiveInventoryAuthorityError("checkpoint scope authority is absent")
        return []
    return list_team_scoped_checkpoints(
        team_id,
        checkpoint_path=path,
        scope_authority=authority,
    )


def _list_receipts(team_id: str) -> Any:
    from core.web.services.team_workflow.research_runtime.model_invocation_receipt_registry import (
        list_team_scoped_model_invocation_receipts,
    )
    from core.web.services.team_workflow.research_projects import resolve_team_program_root

    authority = _run_scope_rows(team_id)
    receipt_authority = [
        {
            "teamId": item["teamId"],
            "questionId": item["questionId"],
            "workflowRunId": item["runId"],
        }
        for item in authority
        if item["questionId"]
    ]
    if not receipt_authority:
        root = resolve_team_program_root(team_id) / "challenge_program" / "model_invocation_receipts"
        if root.exists() and any(path.is_file() for path in root.rglob("*")):
            raise LiveInventoryAuthorityError("receipt scope authority is absent")
        return []
    return list_team_scoped_model_invocation_receipts(
        team_id,
        scope_authority=receipt_authority,
    )


def _list_projects(team_id: str) -> Any:
    from core.web.services.team_workflow.research_projects import read_research_projects_snapshot

    return read_research_projects_snapshot(team_id)


def _list_workspace_state(team_id: str) -> Any:
    from core.web.services.team_workflow.research_projects import list_challenge_cup_experiment_state

    return list_challenge_cup_experiment_state(team_id)


def _list_artifacts(team_id: str, kind: str) -> Any:
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import list_workflow_artifacts

    return list_workflow_artifacts(team_id, kind=kind)


def _list_active_session_work() -> Any:
    from core.web.services import session_service

    return session_service.list_active_session_work_runs(reconcile=False)


def _load_catalog() -> Any:
    from core.research.competition.resources import load_science_question_catalog

    return load_science_question_catalog()


def _load_program() -> Any:
    from core.research.competition.resources import load_competition_program_core

    return load_competition_program_core()


def _load_policy() -> Any:
    from core.research.competition.resources import load_full_catalog_execution_core

    return load_full_catalog_execution_core()


@dataclass(frozen=True)
class ChallengeCupInventoryPorts:
    """Read-only owner ports. ``None`` deliberately means unavailable."""

    list_teams: Callable[[], Any] | None = None
    list_agents: Callable[[], Any] | None = None
    list_sessions: Callable[[], Any] | None = None
    list_rooms: Callable[[], Any] | None = None
    list_meeting_rounds: Callable[[str], Any] | None = None
    list_workflow_runs: Callable[[str], Any] | None = None
    list_artifacts: Callable[[str, str], Any] | None = None
    list_checkpoints: Callable[[str], Any] | None = None
    list_receipts: Callable[[str], Any] | None = None
    list_projects: Callable[[str], Any] | None = None
    list_workspace_state: Callable[[str], Any] | None = None
    list_active_session_work: Callable[[], Any] | None = None
    load_catalog: Callable[[], Any] | None = None
    load_program: Callable[[], Any] | None = None
    load_policy: Callable[[], Any] | None = None

    @classmethod
    def managed_defaults(cls) -> "ChallengeCupInventoryPorts":
        return cls(
            list_teams=_list_teams,
            list_agents=_list_agents,
            list_sessions=_list_sessions,
            list_rooms=_list_rooms,
            list_meeting_rounds=_list_meetings,
            list_workflow_runs=_list_runs,
            list_artifacts=_list_artifacts,
            list_checkpoints=_list_checkpoints,
            list_receipts=_list_receipts,
            list_projects=_list_projects,
            list_workspace_state=_list_workspace_state,
            list_active_session_work=_list_active_session_work,
            load_catalog=_load_catalog,
            load_program=_load_program,
            load_policy=_load_policy,
        )


class LiveChallengeCupInventoryReader:
    """Read-only ``ChallengeCupInventoryReader`` implementation."""

    def __init__(
        self,
        ports: ChallengeCupInventoryPorts | None = None,
        *,
        sources: ChallengeCupInventoryPorts | None = None,
    ) -> None:
        if ports is not None and sources is not None:
            raise ValueError("Pass either ports or sources, not both.")
        self._ports = ports or sources or ChallengeCupInventoryPorts.managed_defaults()
        self._authority_lock = threading.RLock()
        self._last_authority: dict[str, Any] = {}

    @property
    def ports(self) -> ChallengeCupInventoryPorts:
        return self._ports

    def read_authority(self, team_id: str = RESEARCH_TEAM_ID) -> dict[str, Any]:
        with self._authority_lock:
            value = copy.deepcopy(self._last_authority)
        return value or {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": _text(team_id),
            "status": "not_read",
            "families": {},
        }

    def _read(
        self,
        family: str,
        reader: Callable[..., Any] | None,
        args: tuple[Any, ...] = (),
        keys: tuple[str, ...] = (),
    ) -> tuple[list[Any], bool]:
        if not callable(reader):
            return [_sentinel(family, "authority_not_registered")], False
        try:
            return _rows(reader(*args), *keys), True
        except Exception:  # noqa: BLE001 - fail closed without leaking details
            return [_sentinel(family, "authority_read_failed")], False

    def read_inventory(self, team_id: str) -> dict[str, Any]:
        team_id = _text(team_id)
        if not team_id:
            raise ValueError("team_id is required")
        authority: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": team_id,
            "status": "ready",
            "families": {},
            "blockers": [],
        }
        raw_teams, teams_ok = self._read("teams", self._ports.list_teams, keys=("teams",))
        raw_agents, agents_ok = self._read("agents", self._ports.list_agents, keys=("agents",))
        raw_sessions, sessions_ok = self._read("sessions", self._ports.list_sessions, keys=("sessions",))
        raw_rooms, rooms_ok = self._read("rooms", self._ports.list_rooms, keys=("rooms",))
        team_rows = [item for item in raw_teams if isinstance(item, Mapping)]
        team_ids = {_text(_first(item, "teamId", "team_id", "id")) for item in team_rows}
        team_ids.discard("")
        if team_id not in team_ids:
            authority["blockers"].append("target_team_missing")
            raw_teams.append(_sentinel("teams", "target_team_missing"))

        agent_team: dict[str, str] = {}
        role_by_agent: dict[str, str] = {}
        for item in raw_agents:
            if not isinstance(item, Mapping):
                continue
            agent_id = _text(_first(item, "agentId", "agent_id", "id"))
            if not agent_id:
                continue
            owner = _owner(item, {})
            if owner:
                agent_team[agent_id] = owner
            role = _text(_nested(item, "roleKey", "role_key", "agentRoleKey", "role"))
            if role:
                role_by_agent[agent_id] = role
        for item in team_rows:
            owner = _text(_first(item, "teamId", "team_id", "id"))
            members = item.get("members")
            if not owner or not isinstance(members, Sequence) or isinstance(members, (str, bytes, bytearray)):
                continue
            for member in members:
                if isinstance(member, Mapping):
                    agent_id = _text(_first(member, "agentId", "agent_id", "id"))
                    if agent_id:
                        agent_team.setdefault(agent_id, owner)

        safe_teams = [
            _safe_record(
                item,
                family="teams",
                owner_team_id=_text(_first(item, "teamId", "team_id", "id")),
                observation_only_fields=("updatedAt",),
            )
            for item in raw_teams
        ]
        scoped_agents = [
            item
            for item in raw_agents
            if isinstance(item, Mapping)
            and _text(_nested(item, "agentId", "agent_id")) in agent_team
        ]
        scoped_sessions = _reset_inventory_records(raw_sessions, agent_team_by_id=agent_team)
        scoped_rooms = _reset_inventory_records(raw_rooms, agent_team_by_id=agent_team)
        safe_agents = [
            _safe_record(
                item,
                family="agents",
                owner_team_id=_member_owned_team(item, agent_team),
                agent_team_by_id=agent_team,
                role_by_id=role_by_agent,
            )
            for item in scoped_agents
        ]
        safe_sessions = [
            _safe_record(
                item,
                family="sessions",
                owner_team_id=_member_owned_team(item, agent_team),
                agent_team_by_id=agent_team,
                role_by_id=role_by_agent,
            )
            for item in scoped_sessions
        ]
        safe_rooms = [
            _safe_record(
                item,
                family="rooms",
                owner_team_id=_member_owned_team(item, agent_team),
                agent_team_by_id=agent_team,
                role_by_id=role_by_agent,
                observation_only_fields=("updatedAt",),
            )
            for item in scoped_rooms
        ]
        session_team = {
            _record_id(item): _member_owned_team(item, agent_team)
            for item in scoped_sessions
            if _record_id(item)
        }

        all_team_ids = sorted(team_ids | {team_id})
        meetings: list[dict[str, Any]] = []
        meetings_ok = True
        runs: list[dict[str, Any]] = []
        runs_ok = True
        for current_team in all_team_ids:
            rows, ok = self._read(f"meetings:{current_team}", self._ports.list_meeting_rounds, (current_team,), ("meetings", "meetingRounds", "rounds"))
            meetings_ok = meetings_ok and ok
            meetings.extend(_safe_record(item, family="meetings", owner_team_id=current_team, source_kind="meeting_round") for item in rows)
            rows, ok = self._read(f"workflowRuns:{current_team}", self._ports.list_workflow_runs, (current_team,), ("runs", "workflowRuns"))
            runs_ok = runs_ok and ok
            runs.extend(_safe_record(item, family="workflowRuns", owner_team_id=current_team, agent_team_by_id=agent_team, role_by_id=role_by_agent) for item in rows)
        if not meetings_ok:
            meetings.append(_sentinel("meetings", "meeting_round_authority_missing"))
        if not runs_ok:
            runs.append(_sentinel("workflowRuns", "workflow_run_authority_missing"))

        projects: list[dict[str, Any]] = []
        projects_ok = True
        for current_team in all_team_ids:
            rows, ok = self._read(f"projects:{current_team}", self._ports.list_projects, (current_team,), ("projects",))
            projects_ok = projects_ok and ok
            projects.extend(
                _safe_record(
                    item,
                    family="projects",
                    owner_team_id=current_team,
                    source_kind="research_project",
                )
                for item in rows
            )
        if not projects_ok:
            projects.append(_sentinel("projects", "research_project_authority_missing"))

        workspace_state, workspace_state_ok = self._read(
            "workspaceState",
            self._ports.list_workspace_state,
            (team_id,),
            ("state", "entries", "items"),
        )
        if not workspace_state_ok:
            workspace_state.append(_sentinel("workspaceState", "workspace_state_authority_missing"))
        safe_workspace_state = [
            _safe_record(item, family="workspaceState", owner_team_id=team_id)
            for item in workspace_state
        ]

        artifact_families: dict[str, list[dict[str, Any]]] = {"plans": [], "candidates": [], "selections": [], "results": [], "artifacts": []}
        artifacts_ok = True
        for current_team in all_team_ids:
            for kind in ARTIFACT_KINDS:
                rows, ok = self._read(f"artifacts:{current_team}:{kind}", self._ports.list_artifacts, (current_team, kind), ("artifacts", "rows"))
                artifacts_ok = artifacts_ok and ok
                family = ARTIFACT_FAMILY_BY_KIND.get(kind, "artifacts")
                artifact_families[family].extend(_safe_record(item, family=family, owner_team_id=current_team, agent_team_by_id=agent_team, role_by_id=role_by_agent, source_kind=kind) for item in rows)
        if not artifacts_ok:
            artifact_families["artifacts"].append(_sentinel("artifacts", "workflow_artifact_authority_missing"))

        checkpoints, checkpoints_ok = self._read("checkpoints", self._ports.list_checkpoints, (team_id,), ("checkpoints", "rows"))
        receipts, receipts_ok = self._read("receipts", self._ports.list_receipts, (team_id,), ("receipts", "rows"))
        if not checkpoints_ok:
            checkpoints.append(_sentinel("checkpoints", "checkpoint_readback_authority_missing"))
        if not receipts_ok:
            receipts.append(_sentinel("receipts", "receipt_readback_authority_missing"))
        safe_checkpoints = [
            _safe_record(
                item,
                family="checkpoints",
                owner_team_id=team_id if _record_id(item) else "",
            )
            for item in checkpoints
        ]
        safe_receipts = [
            _safe_record(
                item,
                family="receipts",
                owner_team_id=team_id if _record_id(item) else "",
            )
            for item in receipts
        ]

        rounds: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []
        for raw_room, room in zip(scoped_rooms, safe_rooms):
            if not isinstance(raw_room, Mapping):
                continue
            owner = _text(room.get("teamId"))
            for raw_round in _rows(raw_room.get("rounds"), "rounds"):
                compact = _safe_record(raw_round, family="rounds", owner_team_id=owner, source_kind="chat_room_round")
                if compact["id"]:
                    rounds.append(compact)
            participants = raw_room.get("participants")
            if isinstance(participants, Sequence) and not isinstance(participants, (str, bytes, bytearray)):
                for participant in participants:
                    if not isinstance(participant, Mapping):
                        continue
                    participant_id = _text(_first(participant, "participantId", "participant_id", "agentId", "sessionId"))
                    if participant_id:
                        bindings.append({"id": f"{room.get('id')}:{participant_id}", "teamId": owner, "roomId": _text(room.get("id")), "participantId": participant_id, "agentId": _text(_first(participant, "agentId", "agent_id")), "sessionId": _text(_first(participant, "sessionId", "session_id", "directSessionId")), "sourceFamily": "legacyParticipantBindings"})
        if not rooms_ok:
            rounds.append(_sentinel("rounds", "room_round_authority_missing"))
            bindings.append(_sentinel("legacyParticipantBindings", "room_participant_authority_missing"))

        active, active_ok = self._active(team_id, scoped_rooms, runs, session_team)
        protection, protection_ok = self._protection(
            team_id,
            team_ids,
            {"teams": safe_teams, "agents": safe_agents, "sessions": safe_sessions, "rooms": safe_rooms, "meetings": meetings, "workflowRuns": runs, "projects": projects, **artifact_families},
            {"teams": teams_ok, "agents": agents_ok, "sessions": sessions_ok, "rooms": rooms_ok, "meetings": meetings_ok, "workflowRuns": runs_ok, "projects": projects_ok, "artifacts": artifacts_ok},
        )
        authority["families"].update({"teams": teams_ok, "agents": agents_ok, "sessions": sessions_ok, "rooms": rooms_ok, "meetings": meetings_ok, "workflowRuns": runs_ok, "projects": projects_ok, "workspaceState": workspace_state_ok, "artifacts": artifacts_ok, "checkpoints": checkpoints_ok, "receipts": receipts_ok, "activeWork": active_ok, "otherTeamProtection": protection_ok})
        if not active_ok:
            authority["blockers"].append("active_work_authority_missing")
        if not protection_ok:
            authority["blockers"].append("other_team_protection_missing")
        if authority["blockers"]:
            authority["status"] = "blocked"
        authority["families"] = dict(sorted(authority["families"].items()))
        with self._authority_lock:
            self._last_authority = copy.deepcopy(authority)

        objects = {"teams": safe_teams, "agents": safe_agents, "sessions": safe_sessions, "rooms": safe_rooms, "meetings": meetings, "rounds": rounds, "workflowRuns": runs, "projects": projects, "workspaceState": safe_workspace_state, **artifact_families, "receipts": safe_receipts, "checkpoints": safe_checkpoints, "legacyParticipantBindings": bindings}
        objects.update(self._immutable(authority))
        return {"schemaVersion": SCHEMA_VERSION, "teamId": team_id, "objects": objects, "activeWork": active, "otherTeamProtection": protection}

    def _immutable(self, authority: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        specs = (("catalog", self._ports.load_catalog, "catalogId", "science-125-questions-2021"), ("program", self._ports.load_program, "programId", "competition_program_core"), ("policy", self._ports.load_policy, "policyId", "full_catalog_execution_core"))
        result: dict[str, list[dict[str, Any]]] = {}
        for family, loader, id_key, fallback in specs:
            if not callable(loader):
                result[family] = [_sentinel(family, "immutable_resource_authority_missing")]
                authority["families"][family] = False
                continue
            try:
                source = loader()
                source = source if isinstance(source, Mapping) else {}
                row = {"id": _text(_first(source, id_key, "catalog_id", "id", "version")) or fallback, "immutable": True, "sourceFamily": family}
                for key in ("sha256", "catalogSha256", "coreBehaviorHash", "corePolicyHash", "version", "contractVersion", "questionCount", "question_count"):
                    if key in source and isinstance(source[key], (str, int, float, bool)):
                        row["questionCount" if key == "question_count" else key] = source[key]
                result[family] = [row]
                authority["families"][family] = True
            except Exception:  # noqa: BLE001 - resource drift is a blocker
                result[family] = [_sentinel(family, "immutable_resource_read_failed")]
                authority["families"][family] = False
        return result

    def _active(self, team_id: str, raw_rooms: Sequence[Any], runs: Sequence[Mapping[str, Any]], session_team: Mapping[str, str]) -> tuple[dict[str, Any], bool]:
        rows, ok = self._read("activeSessionWork", self._ports.list_active_session_work, keys=("activeItems", "items", "runs"))
        active: dict[tuple[str, str], dict[str, str]] = {}
        for raw in rows:
            item = raw if isinstance(raw, Mapping) else {"id": raw}
            session_id = _text(_first(item, "sessionId", "session_id"))
            owner = _text(session_team.get(session_id))
            status = _status(item)
            if owner != team_id or status not in ACTIVE_STATUSES:
                continue
            item_id = _text(
                _first(
                    item,
                    "runId",
                    "run_id",
                    "workRunId",
                    "work_run_id",
                    "turnId",
                    "turn_id",
                    "taskId",
                    "task_id",
                    "id",
                ),
                limit=320,
            )
            kind = _text(_first(item, "kind", "runKind", "family", "type"))
            if item_id:
                active[(item_id, kind)] = {"id": item_id, "kind": kind, "status": status}
        for raw in raw_rooms:
            if not isinstance(raw, Mapping) or _owner(raw, {}) != team_id:
                continue
            round_id = _text(_first(raw, "activeRoundId", "active_round_id"))
            if round_id and _status(raw) in ACTIVE_STATUSES:
                active[(round_id, "chat_room_round")] = {"id": round_id, "kind": "chat_room_round", "status": _status(raw)}
        for raw in runs:
            status = _status(raw)
            if status in ACTIVE_STATUSES and not _text(_first(raw, "finishedAt", "endedAt")):
                item_id = _text(
                    _first(raw, *_FAMILY_ID_KEYS["workflowRuns"]),
                    limit=320,
                )
                if item_id:
                    kind = _text(_first(raw, "workflowId", "workflowKind", "kind")) or "workflow_run"
                    active[(item_id, kind)] = {"id": item_id, "kind": kind, "status": status}
        items = sorted(active.values(), key=lambda item: (item["kind"], item["id"]))
        statuses: dict[str, int] = {}
        for item in items:
            statuses[item["status"]] = statuses.get(item["status"], 0) + 1
        return {"authorityPresent": ok, "activeCount": len(items), "items": items, "statuses": dict(sorted(statuses.items()))}, ok

    def _protection(self, team_id: str, team_ids: set[str], families: Mapping[str, Sequence[Mapping[str, Any]]], source_ok: Mapping[str, bool]) -> tuple[dict[str, Any], bool]:
        good = bool(team_ids) and all(bool(source_ok.get(family)) for family in PROTECTION_FAMILIES)
        counts: dict[str, dict[str, int]] = {}
        unresolved = 0
        for family, rows in families.items():
            for row in rows:
                owner = _text(row.get("teamId")) if isinstance(row, Mapping) else ""
                if not owner:
                    if _text(row.get("id")):
                        unresolved += 1
                elif owner != team_id:
                    counts.setdefault(owner, {})[family] = counts.setdefault(owner, {}).get(family, 0) + 1
        if unresolved:
            good = False
        snapshot = {"teamIds": sorted(team_ids), "otherTeamCounts": {key: dict(sorted(value.items())) for key, value in sorted(counts.items())}, "unresolvedRuntimeObjectCount": unresolved}
        return {"authorityPresent": good, "snapshot": snapshot}, good


ChallengeCupLiveInventoryAdapter = LiveChallengeCupInventoryReader
ChallengeCupResetLiveInventoryReader = LiveChallengeCupInventoryReader


def build_live_challenge_cup_inventory_reader(ports: ChallengeCupInventoryPorts | None = None) -> LiveChallengeCupInventoryReader:
    return LiveChallengeCupInventoryReader(ports=ports)


__all__ = ["ChallengeCupInventoryPorts", "ChallengeCupLiveInventoryAdapter", "ChallengeCupResetLiveInventoryReader", "LiveChallengeCupInventoryReader", "LiveInventoryAuthorityError", "build_live_challenge_cup_inventory_reader"]
