"""Chat room orchestration for multi-session agent discussion.

Lock order contract
-------------------

``_CHAT_ROOM_LOCK`` is the outer lock for the durable room store.  Inside its
critical sections only room-store in-memory mutations plus
``_store().load()``/``_store().save()`` are allowed.  Forbidden under this
lock: any ``session_service.*`` call, any chat-state transaction
(``session_service._CHAT_STATE_LOCK`` / ``chat_state_transaction``), session
turn scheduler calls, WorkRun persistence, runtime-scene event writes, and any
other potentially blocking I/O.  Publishing SSE snapshots is allowed because
it only copies into bounded subscriber queues.

``_CHAT_ROOM_LOCK`` and ``_CHAT_STATE_LOCK`` are sibling locks and must never
be held at the same time in either nesting order.  Cross-service work (session
transcript sync, agent-execution reservation cancels, participant repair
backed by directory/session reads) must snapshot what it needs inside the
lock, release the lock, then execute.  This prevents the AB-BA deadlock where
a round runner holds ``_CHAT_ROOM_LOCK`` while waiting for the chat-state
transaction lock, and a session-side path holds the chat-state lock while
waiting for ``_CHAT_ROOM_LOCK``.

Wider lock cascade (production py-spy evidence): the chat room lock also
interacts with ``_TEAM_LOCK`` (``core/web/services/team/team_crud.py``) and
with the chat-state file transaction's per-process thread lock
(``_CHAT_STATE_THREAD_LOCK`` inside ``core/ui/chat_state.py``'s
``chat_state_transaction``, held by ``session_service._CHAT_STATE_LOCK``).
The three subsystem locks — team store, room store, chat state — are siblings.
Code in this module must not hold ``_CHAT_ROOM_LOCK`` while acquiring
``_TEAM_LOCK``, ``_CHAT_STATE_LOCK``/``_CHAT_STATE_THREAD_LOCK``, the session
turn scheduler condition, or any other subsystem lock.  Nesting in the other
direction (another subsystem locking, then touching room state) is only safe
because this module never holds the room lock across a foreign lock, which
keeps the global lock graph acyclic.  Audited 2026-08-31: ``_TEAM_LOCK``
critical sections acquire no chat-room or chat-state locks (their only
``chat_room_service`` calls happen after the team lock is released).
"""

from __future__ import annotations

import copy
import hashlib
import json
import queue
import re
import threading
import time
import uuid
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    append_conversation_event,
    conversation_visible_messages_from_events,
    latest_ledger_sequence,
    load_conversation_events,
    rewrite_conversation_events,
)
from core.chat.chat_task_types import trim_lines
from core.chatroom.scheduler import get_scheduler_registry
from core.chatroom.store import ChatRoomStore, ChatRoomStoreReadError, utc_now_iso
from core.infrastructure import developer_sandbox
from core.orchestration.context_engine import build_agent_context, record_agent_turn_result
from core.orchestration.output_boundary import sanitize_assistant_visible_text
from core.orchestration.turn_runner import prepare_agent_turn, run_existing_agent_single_turn
from core.runtime_manager import work_run_store
from core.runtime_manager.work_run_leases import READONLY_CHAT_LEASE
from core.ui.chat_state import chat_state_path, load_chat_state, save_chat_state

from . import agent_directory_service, session_service
from .agent_directory_service import active_agent_runtime, evaluate_agent_workspace_write, write_group_context_event
from .i18n import get_web_language, text_for
from .runtime_scene_service import record_runtime_scene_event
from .team_case_orchestrator import (
    CONSULTATION_INTENTS,
    build_team_case_state,
    case_prompt_lines,
    format_case_state_prompt,
    select_speakers_for_case,
)
from .team_workflow.meeting_message_payload import (
    ingest_meeting_message_output,
    meeting_message_output_contract,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUN_KIND = "chat_room_round"
RUN_LEASES = [READONLY_CHAT_LEASE]
DEFAULT_MODE = "round_robin"
DEFAULT_PURPOSE = "discussion"
CHAT_ROOM_AGENT_LLM_SLOT = "dialogue"
_CHALLENGE_PRIOR_SEMANTIC_MEETING_TYPES = frozenset(
    {
        "hypothesis_candidate_generation",
        "hypothesis_review",
    }
)
_CASUAL_CHAT_TOPIC_RE = re.compile(
    r"^\s*(?:你们好|大家好|你好|您好|hello|hi|hey|嗨|哈喽|在吗|有人吗|辛苦了)[。！!,.，\s]*$",
    re.IGNORECASE,
)
CHAT_ROOM_PURPOSES = [
    {
        "id": "chat",
        "label": "Chat",
        "description": "Short, natural replies that follow the current topic and prior speaker.",
    },
    {
        "id": "discussion",
        "label": "Discussion",
        "description": "Point-of-view exchange with tradeoffs, disagreement, and suggestions.",
    },
    {
        "id": "meeting",
        "label": "Meeting",
        "description": "Structured meeting notes with decisions, risks, and action items.",
    },
    {
        "id": "medical_triage",
        "label": "Medical triage",
        "description": "User-facing medical intake, risk triage, specialist routing, and safe next-step advice.",
    },
    {
        "id": "research_coordination",
        "label": "Research coordination",
        "description": "Research organization coordination with role-aware reporting, evidence, and task routing.",
    },
    {
        "id": "knowledge_expansion",
        "label": "Knowledge expansion",
        "description": "Knowledge expansion coordination across source intake, extraction, quality review, candidate graph, and steward ingestion.",
    },
    {
        "id": "ai_search",
        "label": "AI search",
        "description": "AI source-scope curation, source tiering, default enablement, and signal quality checks.",
    },
    {
        "id": "self_evolution",
        "label": "Self evolution",
        "description": "Self-evolution role coordination across execution, review, and observation responsibilities.",
    },
    {
        "id": "supervised_evolution",
        "label": "Supervised evolution",
        "description": "Supervised evolution coordination across baseline, candidate, reviewer, auditor, and judge roles.",
    },
]
RUNNING_ROUND_STATUSES = {"queued", "running", "stopping"}
_CHAT_ROOM_API_HISTORY_MESSAGE_LIMIT = 50
# Lock order contract (see module docstring): outer lock for the room store.
# Only room-store memory ops + load/save inside; never hold it while calling
# session_service, chat-state transactions, the session turn scheduler, WorkRun
# persistence, or scene-event writes.  Never nest with _CHAT_STATE_LOCK.
_CHAT_ROOM_LOCK = threading.RLock()
_CHAT_ROOM_PARTICIPANT_REFRESH_MAX_ATTEMPTS = 3
_CHAT_ROOM_EXECUTOR_MAX_WORKERS = 4
_CHAT_ROOM_EXECUTOR = ThreadPoolExecutor(
    max_workers=_CHAT_ROOM_EXECUTOR_MAX_WORKERS,
    thread_name_prefix="web-chat-room",
)
# The executor queue is unbounded, so cap submitted-but-not-finished rounds;
# otherwise N rooms can all flip to durable "running" while queueing forever.
_CHAT_ROOM_MAX_INFLIGHT_ROUNDS = 16
_CHAT_ROOM_INFLIGHT_LOCK = threading.Lock()
_CHAT_ROOM_INFLIGHT_COUNT = 0
_CHAT_ROOM_STREAM_SUBSCRIBERS_LOCK = threading.Lock()
_CHAT_ROOM_STREAM_SUBSCRIBERS: dict[str, set[queue.Queue[dict[str, Any]]]] = {}
_CHAT_ROOM_STREAM_HEARTBEAT_SECONDS = 15.0
_CHAT_ROOM_STREAM_QUEUE_SIZE = 8
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
_PARTICIPANT_CONTEXT_FIELDS = (
    "teamId",
    "teamName",
    "teamPurpose",
    "teamRole",
    "teamMemberPurpose",
    "teamResponsibilities",
)

AgentRunner = Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]]
_CHAT_ROOM_ROUND_CONTROLS_LOCK = threading.Lock()
_CHAT_ROOM_ROUND_CONTROLS: dict[str, dict[str, str]] = {}
# Read-path reconcile gate: nearly every read API (room lists, room detail,
# team listing via list_chat_rooms_compact, conversation index) funnels through
# _reconcile_chat_room_round_state, which needs _CHAT_ROOM_LOCK.  Running it on
# every read turned one hijacked lock into a frozen API surface, so reconcile
# only runs when the room store changed on disk, after a bounded staleness TTL
# (external WorkRun changes), or once per process start — and only one
# reconcile runs at a time; concurrent readers skip it instead of queueing.
_CHAT_ROOM_RECONCILE_GATE_LOCK = threading.Lock()
_CHAT_ROOM_RECONCILE_LAST_RUN_AT: float | None = None
_CHAT_ROOM_RECONCILE_LAST_STORE_TOKEN: str | None = None
_CHAT_ROOM_RECONCILE_INFLIGHT = False
_CHAT_ROOM_RECONCILE_MIN_INTERVAL_SECONDS = 30.0
_CHALLENGE_ROOM_DEADLINE_CONFIG_KEY = "challengeDeadlineAtMs"
_CHALLENGE_ROOM_PER_CALL_DEADLINE_CONTEXT_KEY = "challengePerCallDeadlineAtMs"
_CHALLENGE_ROOM_DEADLINE_STOP_REASON = "challenge_logical_task_deadline_exhausted"
# Per-call budget exhaustion only fences the current speaker call.  It must
# never become a round terminalReason or a meeting terminalReason: the
# meeting-level clock below stays the only meeting termination authority.
_CHALLENGE_ROOM_PER_CALL_STOP_REASON = "challenge_per_call_budget_exhausted"
# Speaker watchdog: rooms without an explicit ``perCallBudgetMs`` still bound
# every speaker call at this budget (challenge rooms derive 300-600s budgets
# from their deadline policy; this matches the audited 300s floor), so a hung
# LLM call can never occupy a round indefinitely.
_CHAT_ROOM_SPEAKER_DEFAULT_PER_CALL_BUDGET_MS = 300_000
_CHALLENGE_ROOM_RUN_STOP_REASON_PREFIX = "challenge_workflow_run_"
_CHALLENGE_ROOM_RUN_POLL_INTERVAL_SECONDS = 0.5
_CHALLENGE_ROOM_HEARTBEAT_INTERVAL_SECONDS = 30.0
# Heartbeat-aware orphan exemption: a running WorkRun whose heartbeat (30s
# renewal cadence) is still inside this window proves the owning backend
# process is alive, so a missing in-memory round control record must not be
# treated as a dead orphan.  The window covers 3 missed heartbeats plus clock
# skew; a genuinely dead process stops renewing and expires out of it.
_CHAT_ROOM_WORK_RUN_HEARTBEAT_FRESH_SECONDS = 90.0
# Digest-wait TTL stop-loss: a meeting-bound round whose meeting has a digest
# draft waiting past the TTL stops before the next speaker call.  It fences
# the room round only; the meeting state machine and its digest stay intact.
_MEETING_DIGEST_TTL_STOP_REASON = "meeting_digest_ttl_muted"
_MEETING_DIGEST_TTL_POLL_INTERVAL_SECONDS = 15.0
_CHAT_ROOM_PARTICIPANT_INDEX_CACHE_LOCK = threading.Lock()
_CHAT_ROOM_PARTICIPANT_INDEX_CACHE_CONDITION = threading.Condition(_CHAT_ROOM_PARTICIPANT_INDEX_CACHE_LOCK)
_CHAT_ROOM_PARTICIPANT_INDEX_CACHE: dict[tuple[Any, ...], dict[str, dict[str, dict[str, Any]]]] = {}
_CHAT_ROOM_PARTICIPANT_INDEX_INFLIGHT: set[tuple[Any, ...]] = set()
_CHAT_ROOM_PARTICIPANT_INDEX_CACHE_MAX_ENTRIES = 8
_CHAT_ROOM_PARTICIPANT_INDEX_PREWARM_LOCK = threading.Lock()
_CHAT_ROOM_PARTICIPANT_INDEX_PREWARM_INFLIGHT = False
_MISSING_SESSION_STATUS_MESSAGE = "缺少有效 Agent：当前会话引用的 Agent 已不存在或不可用。"
_CHALLENGE_CUP_ROOM_RESET_STAGES: dict[str, dict[str, Any]] = {}


def _perf_counter() -> float:
    return time.perf_counter()


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((_perf_counter() - started_at) * 1000)))


def _elapsed_ms_between(started_at: Any, ended_at: float | None = None) -> int:
    try:
        start_value = float(started_at)
    except (TypeError, ValueError):
        return 0
    end_value = _perf_counter() if ended_at is None else float(ended_at)
    return max(0, int(round((end_value - start_value) * 1000)))


def _chat_room_lock_owned_by_current_thread() -> bool:
    ownership_probe = getattr(_CHAT_ROOM_LOCK, "_is_owned", None)
    return bool(ownership_probe()) if callable(ownership_probe) else False


def _sync_agent_directory_project_root() -> None:
    if agent_directory_service.PROJECT_ROOT != PROJECT_ROOT:
        agent_directory_service.PROJECT_ROOT = PROJECT_ROOT


class ChatRoomNotFoundError(ValueError):
    """Raised when a chat room does not exist."""


class ChatRoomValidationError(ValueError):
    """Raised when a chat room request is invalid."""


class ChatRoomBusyError(RuntimeError):
    """Raised when a chat room already has an active round."""


class SpeakerCallWatchdogTimeout(RuntimeError):
    """A speaker runner call exceeded its per-call budget and was abandoned."""


def list_chat_room_modes() -> list[dict[str, str]]:
    return get_scheduler_registry().list_modes()


def list_chat_room_purposes() -> list[dict[str, str]]:
    return [dict(item) for item in CHAT_ROOM_PURPOSES]


def read_chat_rooms_snapshot() -> list[dict[str, Any]]:
    """Read the durable room authority without reconciliation or repair.

    Workflow projections must remain zero-write.  Public list/detail APIs
    intentionally reconcile runtime state, so they are not safe for a query
    service that only needs the persisted room/scope bindings.
    """

    state = _store().load()
    return [
        copy.deepcopy(item)
        for item in list(state.get("rooms") or [])
        if isinstance(item, dict)
    ]


def _challenge_cup_reset_text(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ChatRoomValidationError(f"{field} is required")
    return normalized


def _challenge_cup_room_team_id(room: Mapping[str, Any]) -> str:
    config = room.get("config") if isinstance(room.get("config"), Mapping) else {}
    return str(
        room.get("teamId")
        or room.get("researchTeamId")
        or config.get("teamId")
        or config.get("researchTeamId")
        or ""
    ).strip()


def _challenge_cup_room_reset_fingerprint(rooms: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(rooms, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _challenge_cup_room_stage_summary(stage: Mapping[str, Any]) -> dict[str, Any]:
    rooms = stage.get("rooms") if isinstance(stage.get("rooms"), list) else []
    return {
        "kind": "chat_room_team_reset",
        "schemaVersion": 1,
        "stageId": str(stage["stageId"]),
        "resetId": str(stage["resetId"]),
        "teamId": str(stage["teamId"]),
        "status": str(stage.get("status") or "staged"),
        "roomCount": len(rooms),
        "roomIds": [str(room.get("roomId") or "") for room in rooms],
        "fingerprint": str(stage["fingerprint"]),
    }


def _challenge_cup_room_stage(stage: Mapping[str, Any], *, reset_id: str | None = None) -> dict[str, Any]:
    if not isinstance(stage, Mapping) or stage.get("kind") != "chat_room_team_reset" or stage.get("schemaVersion") != 1:
        raise ChatRoomValidationError("Chat room reset stage schema is invalid.")
    stage_id = _challenge_cup_reset_text(stage.get("stageId"), field="stageId")
    cached = _CHALLENGE_CUP_ROOM_RESET_STAGES.get(stage_id)
    if cached is None:
        raise ChatRoomValidationError("Chat room reset stage is unavailable.")
    for key in ("resetId", "teamId", "fingerprint"):
        if str(stage.get(key) or "") != str(cached.get(key) or ""):
            raise ChatRoomValidationError(f"Chat room reset stage {key} does not match.")
    if reset_id is not None and str(reset_id).strip() != str(cached["resetId"]):
        raise ChatRoomValidationError("Chat room reset stage resetId does not match.")
    return cached


def prepare_team_chat_room_reset(
    team_id: str,
    *,
    reset_id: str,
    room_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Stage exactly one team's idle rooms for a reversible governed reset."""

    team = _challenge_cup_reset_text(team_id, field="teamId")
    reset = _challenge_cup_reset_text(reset_id, field="resetId")
    requested_ids = {str(value or "").strip() for value in (room_ids or [])}
    if "" in requested_ids:
        raise ChatRoomValidationError("Chat room reset plan contains an empty room id.")
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        all_rooms = [item for item in list(state.get("rooms") or []) if isinstance(item, dict)]
        target = [room for room in all_rooms if _challenge_cup_room_team_id(room) == team]
        target_ids = {str(room.get("roomId") or "").strip() for room in target}
        if requested_ids and requested_ids != target_ids:
            raise ChatRoomValidationError("Chat room reset plan does not match the current team room set.")
        for room in target:
            _raise_if_room_busy(room)
        snapshot = [copy.deepcopy(room) for room in target]
        stage = {
            "kind": "chat_room_team_reset",
            "schemaVersion": 1,
            "stageId": f"chat-room-stage-{uuid.uuid4().hex}",
            "resetId": reset,
            "teamId": team,
            "rooms": snapshot,
            "fingerprint": _challenge_cup_room_reset_fingerprint(snapshot),
            "status": "staged",
        }
        # Persist the inverse operation before the selected rooms disappear.
        _CHALLENGE_CUP_ROOM_RESET_STAGES[str(stage["stageId"])] = stage
        state["rooms"] = [room for room in all_rooms if room not in target]
        _store().save(state)
    return _challenge_cup_room_stage_summary(stage)


def purge_team_chat_room_reset(stage: Mapping[str, Any], *, reset_id: str | None = None) -> dict[str, Any]:
    """Commit a staged room reset after the parent transaction succeeds."""

    with _CHAT_ROOM_LOCK:
        cached = _challenge_cup_room_stage(stage, reset_id=reset_id)
        if cached.get("status") == "destroyed":
            raise ChatRoomValidationError("A finalized chat room reset cannot be purged.")
        current = _store().load()
        staged_ids = {str(room.get("roomId") or "") for room in cached.get("rooms") or []}
        if any(str(room.get("roomId") or "") in staged_ids for room in current.get("rooms") or [] if isinstance(room, dict)):
            raise ChatRoomValidationError("A staged chat room reappeared before commit.")
        cached["status"] = "purged"
        return {**_challenge_cup_room_stage_summary(cached), "operation": "purge"}


def restore_team_chat_room_reset(stage: Mapping[str, Any], *, reset_id: str | None = None) -> dict[str, Any]:
    """Restore exactly the staged room records when a later reset port fails."""

    with _CHAT_ROOM_LOCK:
        cached = _challenge_cup_room_stage(stage, reset_id=reset_id)
        if cached.get("status") == "destroyed":
            raise ChatRoomValidationError("A finalized chat room reset cannot be restored.")
        state = _store().load()
        rooms = [item for item in list(state.get("rooms") or []) if isinstance(item, dict)]
        by_id = {str(room.get("roomId") or "").strip(): room for room in rooms}
        restored = 0
        for room in cached.get("rooms") or []:
            room_id = str(room.get("roomId") or "").strip()
            existing = by_id.get(room_id)
            if existing is not None:
                if _challenge_cup_room_reset_fingerprint([existing]) != _challenge_cup_room_reset_fingerprint([room]):
                    raise ChatRoomValidationError("Chat room reset restore conflicts with a current room.")
                continue
            rooms.append(copy.deepcopy(room))
            restored += 1
        state["rooms"] = rooms
        if restored:
            _store().save(state)
        cached["status"] = "restored"
        return {**_challenge_cup_room_stage_summary(cached), "operation": "restore", "restoredCount": restored}


def destroy_team_chat_room_reset(stage: Mapping[str, Any], *, reset_id: str | None = None) -> dict[str, Any]:
    """Discard staged room payloads only after the reset has fully succeeded."""

    with _CHAT_ROOM_LOCK:
        cached = _challenge_cup_room_stage(stage, reset_id=reset_id)
        if cached.get("status") not in {"purged", "destroyed"}:
            raise ChatRoomValidationError("Only a purged chat room reset can be finalized.")
        cached["status"] = "destroyed"
        cached["rooms"] = []
        return _challenge_cup_room_stage_summary(cached)


def list_chat_rooms(
    *,
    session_summaries: dict[str, dict[str, Any]] | None = None,
    repair_participants: bool = False,
) -> list[dict[str, Any]]:
    _reconcile_chat_room_round_state()
    state = _store().load()
    summaries = session_summaries
    if repair_participants:
        summaries = session_summaries if session_summaries is not None else _session_summary_index()
    if repair_participants and _repair_room_participants_in_state(state, session_summaries=summaries):
        _store().save(state)
    available_modes = list_chat_room_modes()
    available_purposes = list_chat_room_purposes()
    rooms = [
        _room_to_api(
            item,
            available_modes=available_modes,
            available_purposes=available_purposes,
        )
        for item in state.get("rooms") or []
        if isinstance(item, dict)
    ]
    rooms.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return rooms


def list_chat_rooms_for_conversation_index(
    *,
    session_summaries: dict[str, dict[str, Any]] | None = None,
    repair_room_participants: bool = False,
) -> list[dict[str, Any]]:
    """Return compact room references suitable for `/conversations` payload."""

    _reconcile_chat_room_round_state()
    state = _store().load()
    if repair_room_participants:
        summaries = session_summaries if session_summaries is not None else _session_summary_index()
        if _repair_room_participants_in_state(state, session_summaries=summaries):
            _store().save(state)
    rooms = [
        _room_to_conversation_index_reference(item)
        for item in list(state.get("rooms") or [])
        if isinstance(item, dict)
    ]
    rooms.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return rooms


def list_chat_rooms_compact() -> list[dict[str, Any]]:
    """Return room references without scanning sessions or full room hydration."""

    _reconcile_chat_room_round_state()
    state = _store().load()
    rooms = [
        _room_to_compact_reference(item)
        for item in list(state.get("rooms") or [])
        if isinstance(item, dict)
    ]
    rooms.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return rooms


def get_chat_room_compact(room_id: str) -> dict[str, Any] | None:
    """Return one room reference without session repair or full room hydration."""

    normalized_room_id = str(room_id or "").strip()
    if not normalized_room_id:
        return None
    _reconcile_chat_room_round_state()
    state = _store().load()
    room = _find_room(state, normalized_room_id)
    return _room_to_compact_reference(room) if room else None


def get_chat_room_detail(room_id: str) -> dict[str, Any] | None:
    started_at = _perf_counter()
    phase_timings: list[dict[str, Any]] = []
    stage_started_at = _perf_counter()
    reconciled_rounds = _reconcile_chat_room_round_state()
    _append_chat_room_detail_timing(
        phase_timings,
        "round_state.reconcile",
        stage_started_at,
        count=len(reconciled_rounds),
    )
    stage_started_at = _perf_counter()
    state = _store().load()
    _append_chat_room_detail_timing(phase_timings, "state.load", stage_started_at)
    stage_started_at = _perf_counter()
    room = _find_room(state, room_id)
    _append_chat_room_detail_timing(phase_timings, "room.find", stage_started_at)
    if not room:
        _record_chat_room_detail_loaded(
            "",
            started_at,
            repaired=False,
            found=False,
            participant_index_cache_hit=False,
            phase_timings=phase_timings,
        )
        return None
    stage_started_at = _perf_counter()
    participant_indexes, participant_index_cache_hit, participant_index_timings = _participant_refresh_indexes(
        participants=room.get("participants") if isinstance(room.get("participants"), list) else []
    )
    _append_chat_room_detail_timing(
        phase_timings,
        "participant_index.refresh",
        stage_started_at,
        cache_hit=participant_index_cache_hit,
    )
    phase_timings.extend(participant_index_timings)
    stage_started_at = _perf_counter()
    repaired = _repair_room_participants(
        room,
        session_summaries=participant_indexes["session_summaries"],
        active_agents_by_id=participant_indexes["active_agents_by_id"],
        active_agents_by_session_id=participant_indexes["active_agents_by_session_id"],
        preserve_scoped_session_ids=_is_challenge_discussion_room(room),
    )
    _append_chat_room_detail_timing(phase_timings, "participant_repair", stage_started_at)
    if repaired:
        _clear_participant_refresh_index_cache()
        stage_started_at = _perf_counter()
        # Read-modify-write must hold the room lock: this detail read runs on
        # round worker threads between speakers, and an unlocked save here can
        # roll back concurrent round writes (lost messages / phantom running).
        with _CHAT_ROOM_LOCK:
            fresh_state = _store().load()
            fresh_room = _find_room(fresh_state, room_id)
            if fresh_room is not None:
                fresh_room["participants"] = room["participants"]
                fresh_room["updatedAt"] = room.get("updatedAt") or utc_now_iso()
                _store().save(fresh_state)
        _append_chat_room_detail_timing(phase_timings, "state.save_repair", stage_started_at)
    stage_started_at = _perf_counter()
    detail = _room_to_api(
        room,
        available_modes=list_chat_room_modes(),
        available_purposes=list_chat_room_purposes(),
    )
    _append_chat_room_detail_timing(phase_timings, "payload.build", stage_started_at)
    _record_chat_room_detail_loaded(
        str(detail.get("roomId") or room_id),
        started_at,
        repaired=repaired,
        found=True,
        participant_index_cache_hit=participant_index_cache_hit,
        phase_timings=phase_timings,
    )
    return detail


def update_chat_room(
    room_id: str,
    *,
    title: str | None = None,
    participant_session_ids: list[str] | None = None,
    participant_contexts_by_agent_id: dict[str, dict[str, Any]] | None = None,
    allow_empty_participants: bool = False,
    mode: str | None = None,
    purpose: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lang = get_web_language()
    normalized_room_id = str(room_id or "").strip()
    # Lock order contract: participant resolution reads the session directory
    # (session_service) and must not run under _CHAT_ROOM_LOCK; resolve before
    # taking the lock and apply the resolved list inside.
    resolved_participants_override: list[dict[str, Any]] | None = None
    if participant_session_ids is not None:
        resolved_participants_override = _apply_participant_contexts(
            _resolve_participants(participant_session_ids),
            participant_contexts_by_agent_id=participant_contexts_by_agent_id,
        )
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        room = _find_room(state, normalized_room_id)
        if room is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
        _raise_if_room_busy(room)

        if title is not None:
            normalized_title = trim_lines(title or "", max_lines=1).strip()
            if normalized_title:
                room["title"] = normalized_title
        if mode is not None:
            normalized_mode = _normalize_mode(mode or room.get("mode") or DEFAULT_MODE)
            _require_ready_mode(normalized_mode)
            room["mode"] = normalized_mode
        if purpose is not None:
            room["purpose"] = _normalize_purpose(purpose or room.get("purpose") or DEFAULT_PURPOSE)
        if config is not None:
            room["config"] = _safe_config(config)
        if resolved_participants_override is not None:
            if not resolved_participants_override and not allow_empty_participants:
                raise ChatRoomValidationError(
                    text_for(lang, zh="至少需要一个可用会话才能更新群聊。", en="At least one session is required.")
                )
            room["participants"] = resolved_participants_override

        room["updatedAt"] = utc_now_iso()
        _store().save(state)

    _record_room_event(
        "room",
        "chat_room.updated",
        room,
        fields={
            "participantCount": len(room.get("participants") or []),
            "mode": room.get("mode") or DEFAULT_MODE,
            "purpose": room.get("purpose") or DEFAULT_PURPOSE,
        },
    )
    return _room_to_api(room)


def update_agent_chat_room_membership(agent_id: str, room_ids: list[str] | None) -> dict[str, Any]:
    """Update the rooms a single persistent Agent belongs to without touching peers."""

    lang = get_web_language()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise ChatRoomValidationError(text_for(lang, zh="缺少 Agent。", en="Agent id is required."))

    target_room_ids = _dedupe_room_ids(room_ids)
    participant = _resolve_agent_participant(normalized_agent_id)
    direct_session_id = str(participant.get("sessionId") or participant.get("directSessionId") or "").strip()
    changed_rooms: list[dict[str, Any]] = []
    now = utc_now_iso()

    with _CHAT_ROOM_LOCK:
        state = _store().load()
        rooms = [item for item in list(state.get("rooms") or []) if isinstance(item, dict)]
        rooms_by_id = {
            str(room.get("roomId") or "").strip(): room
            for room in rooms
            if str(room.get("roomId") or "").strip()
        }
        missing_room_ids = [room_id for room_id in target_room_ids if room_id not in rooms_by_id]
        if missing_room_ids:
            raise ChatRoomValidationError(f"Unknown chat room: {missing_room_ids[0]}")

        target_set = set(target_room_ids)
        for room in rooms:
            room_id = str(room.get("roomId") or "").strip()
            if not room_id:
                continue
            selected = room_id in target_set
            participants = [dict(item) for item in list(room.get("participants") or []) if isinstance(item, dict)]
            currently_selected = False
            kept_selected = False
            next_participants: list[dict[str, Any]] = []
            for item in participants:
                if _participant_matches_agent(item, normalized_agent_id, direct_session_id):
                    currently_selected = True
                    if selected and not kept_selected:
                        next_participants.append(dict(participant))
                        kept_selected = True
                    continue
                next_participants.append(item)
            if selected and not kept_selected:
                next_participants.append(dict(participant))
            if not selected and currently_selected and not next_participants:
                raise ChatRoomValidationError(
                    text_for(
                        lang,
                        zh="不能移除群聊中的最后一个成员。请先在群管理中添加其他成员或删除群聊。",
                        en="Cannot remove the last room participant. Add another member or delete the room first.",
                    )
                )
            if next_participants == participants:
                continue
            _raise_if_room_busy(room)
            room["participants"] = next_participants
            room["updatedAt"] = now
            changed_rooms.append(room)

        if changed_rooms:
            _store().save(state)

    for room in changed_rooms:
        _record_room_event(
            "membership",
            "chat_room.agent_membership.updated",
            room,
            fields={
                "agentId": normalized_agent_id,
                "selected": str(room.get("roomId") or "").strip() in set(target_room_ids),
                "participantCount": len(room.get("participants") or []),
            },
        )
    rooms_payload = list_chat_rooms()
    return {
        "agentId": normalized_agent_id,
        "roomIds": [
            str(room.get("roomId") or "").strip()
            for room in rooms_payload
            if normalized_agent_id
            in {
                str(participant.get("agentId") or "").strip()
                for participant in list(room.get("participants") or [])
                if isinstance(participant, dict)
            }
        ],
        "changedRoomIds": [str(room.get("roomId") or "").strip() for room in changed_rooms],
        "chatRooms": rooms_payload,
    }


def remove_agent_from_chat_rooms(
    agent_id: str,
    *,
    allow_empty_rooms: bool = False,
    direct_session_id: str = "",
    include_restore_token: bool = False,
) -> dict[str, Any]:
    """Remove one Agent from all chat room participant lists before safe archival."""

    lang = get_web_language()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise ChatRoomValidationError(text_for(lang, zh="缺少 Agent。", en="Agent id is required."))
    direct_session_id = str(direct_session_id or "").strip()
    agent = agent_directory_service.get_agent(normalized_agent_id, include_archived=True)
    if isinstance(agent, dict) and not direct_session_id:
        direct_session_id = str(agent.get("directSessionId") or "").strip()

    changed_rooms: list[dict[str, Any]] = []
    restore_rooms: list[dict[str, Any]] = []
    now = utc_now_iso()
    session_summaries = _session_summary_index()
    # Lock order contract: the participant repair reads the agent directory and
    # writes scene events (file I/O); precompute the directory index here and
    # defer event writes until after _CHAT_ROOM_LOCK is released.
    repair_indexes = _active_agent_participant_indexes()
    deferred_repair_events: list[dict[str, Any]] = []
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        if _repair_room_participants_in_state(
            state,
            session_summaries=session_summaries,
            active_agent_indexes=repair_indexes,
            deferred_events=deferred_repair_events,
        ):
            _store().save(state)
            state = _store().load()
        rooms = [item for item in list(state.get("rooms") or []) if isinstance(item, dict)]
        for room in rooms:
            participants = [dict(item) for item in list(room.get("participants") or []) if isinstance(item, dict)]
            next_participants = [
                item
                for item in participants
                if not _participant_matches_agent(item, normalized_agent_id, direct_session_id)
            ]
            if next_participants == participants:
                continue
            if not next_participants and not allow_empty_rooms:
                raise ChatRoomValidationError(
                    text_for(
                        lang,
                        zh="不能归档仍是某个群聊唯一成员的 Agent。请先删除该群聊或添加其他成员。",
                        en="Cannot archive an Agent that is the only member of a group room. Delete the room or add another member first.",
                    )
                )
            _raise_if_room_busy(room)
            if include_restore_token:
                restore_rooms.append(copy.deepcopy(room))
            room["participants"] = next_participants
            room["updatedAt"] = now
            changed_rooms.append(room)
        if changed_rooms:
            _store().save(state)

    _emit_deferred_participant_repair_events(deferred_repair_events)

    for room in changed_rooms:
        _record_room_event(
            "membership",
            "chat_room.agent_membership.removed",
            room,
            fields={
                "agentId": normalized_agent_id,
                "participantCount": len(room.get("participants") or []),
            },
        )
    result = {
        "agentId": normalized_agent_id,
        "changedRoomIds": [str(room.get("roomId") or "").strip() for room in changed_rooms],
        "chatRooms": list_chat_rooms(),
    }
    if include_restore_token:
        result["restoreToken"] = {"rooms": restore_rooms}
    return result


def remove_agents_from_chat_rooms(
    agent_ids: list[str] | None,
    *,
    allow_empty_rooms: bool = False,
    direct_session_ids_by_agent_id: dict[str, str] | None = None,
    include_chat_rooms: bool = True,
    repair_participants: bool = True,
    include_restore_token: bool = False,
) -> dict[str, Any]:
    """Remove multiple Agents from all room participant lists in one atomic room update."""

    lang = get_web_language()
    requested = [str(item or "").strip() for item in list(agent_ids or []) if str(item or "").strip()]
    normalized_agent_ids: list[str] = []
    seen_agent_ids: set[str] = set()
    for agent_id in requested:
        if agent_id in seen_agent_ids:
            continue
        seen_agent_ids.add(agent_id)
        normalized_agent_ids.append(agent_id)
    if not normalized_agent_ids:
        return {"agentIds": [], "changedRoomIds": [], "removedByAgentId": {}}

    direct_session_ids_by_agent_id = {
        str(agent_id or "").strip(): str(direct_session_id or "").strip()
        for agent_id, direct_session_id in dict(direct_session_ids_by_agent_id or {}).items()
        if str(agent_id or "").strip()
    }
    for agent_id in normalized_agent_ids:
        if agent_id in direct_session_ids_by_agent_id:
            continue
        agent = agent_directory_service.get_agent(agent_id, include_archived=True)
        if isinstance(agent, dict):
            direct_session_ids_by_agent_id[agent_id] = str(agent.get("directSessionId") or "").strip()
        else:
            direct_session_ids_by_agent_id[agent_id] = ""

    changed_rooms: list[dict[str, Any]] = []
    restore_rooms: list[dict[str, Any]] = []
    removed_by_agent_id: dict[str, list[str]] = {agent_id: [] for agent_id in normalized_agent_ids}
    agent_id_set = set(normalized_agent_ids)
    now = utc_now_iso()
    session_summaries = _session_summary_index() if repair_participants or include_chat_rooms else None
    # Lock order contract: same as remove_agent_from_chat_rooms — precompute
    # the directory index and defer scene-event writes out of the lock.
    repair_indexes = _active_agent_participant_indexes()
    deferred_repair_events: list[dict[str, Any]] = []
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        if repair_participants and _repair_room_participants_in_state(
            state,
            session_summaries=session_summaries,
            active_agent_indexes=repair_indexes,
            deferred_events=deferred_repair_events,
        ):
            _store().save(state)
            state = _store().load()
        rooms = [item for item in list(state.get("rooms") or []) if isinstance(item, dict)]
        planned_changes: list[tuple[dict[str, Any], list[dict[str, Any]], set[str]]] = []
        for room in rooms:
            participants = [dict(item) for item in list(room.get("participants") or []) if isinstance(item, dict)]
            removed_agent_ids_for_room: set[str] = set()
            next_participants: list[dict[str, Any]] = []
            for participant in participants:
                matched_agent_id = _matching_agent_id(
                    participant,
                    agent_id_set,
                    direct_session_ids_by_agent_id,
                )
                if matched_agent_id:
                    removed_agent_ids_for_room.add(matched_agent_id)
                    continue
                next_participants.append(participant)
            if next_participants == participants:
                continue
            if not next_participants and not allow_empty_rooms:
                raise ChatRoomValidationError(
                    text_for(
                        lang,
                        zh="不能归档仍是某个群聊唯一成员的 Agent。请先删除该群聊或添加其他成员。",
                        en="Cannot archive an Agent that is the only member of a group room. Delete the room or add another member first.",
                    )
                )
            _raise_if_room_busy(room)
            planned_changes.append((room, next_participants, removed_agent_ids_for_room))
        for room, next_participants, removed_agent_ids_for_room in planned_changes:
            if include_restore_token:
                restore_rooms.append(copy.deepcopy(room))
            room["participants"] = next_participants
            room["updatedAt"] = now
            changed_rooms.append(room)
            room_id = str(room.get("roomId") or "").strip()
            for removed_agent_id in removed_agent_ids_for_room:
                removed_by_agent_id.setdefault(removed_agent_id, []).append(room_id)
        if changed_rooms:
            _store().save(state)

    _emit_deferred_participant_repair_events(deferred_repair_events)

    for room in changed_rooms:
        room_id = str(room.get("roomId") or "").strip()
        removed_agent_ids = [
            agent_id
            for agent_id, room_ids in removed_by_agent_id.items()
            if room_id in set(room_ids)
        ]
        _record_room_event(
            "membership",
            "chat_room.agent_membership.removed",
            room,
            fields={
                "agentIds": removed_agent_ids,
                "agentCount": len(removed_agent_ids),
                "participantCount": len(room.get("participants") or []),
            },
        )
    result = {
        "agentIds": normalized_agent_ids,
        "changedRoomIds": [str(room.get("roomId") or "").strip() for room in changed_rooms],
        "removedByAgentId": {
            agent_id: list(room_ids)
            for agent_id, room_ids in removed_by_agent_id.items()
            if room_ids
        },
    }
    if include_chat_rooms:
        result["chatRooms"] = list_chat_rooms(session_summaries=session_summaries)
    if include_restore_token:
        result["restoreToken"] = {"rooms": restore_rooms}
    return result


def restore_removed_agents_to_chat_rooms(restore_token: dict[str, Any] | None) -> dict[str, Any]:
    """Restore exact room participant snapshots after a failed archive."""

    snapshots = [copy.deepcopy(item) for item in list(dict(restore_token or {}).get("rooms") or []) if isinstance(item, dict)]
    if not snapshots:
        return {"restoredRoomIds": []}
    restored_ids: list[str] = []
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        rooms = [item for item in list(state.get("rooms") or []) if isinstance(item, dict)]
        by_id = {str(item.get("roomId") or "").strip(): index for index, item in enumerate(rooms)}
        for snapshot in snapshots:
            room_id = str(snapshot.get("roomId") or "").strip()
            if not room_id or room_id not in by_id:
                continue
            rooms[by_id[room_id]] = snapshot
            restored_ids.append(room_id)
        state["rooms"] = rooms
        if restored_ids:
            _store().save(state)
    return {"restoredRoomIds": restored_ids}


def delete_chat_room(room_id: str) -> dict[str, Any]:
    lang = get_web_language()
    normalized_room_id = str(room_id or "").strip()
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        rooms = [item for item in list(state.get("rooms") or []) if isinstance(item, dict)]
        room = _find_room(state, normalized_room_id)
        if room is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
        _raise_if_room_busy(room)
        state["rooms"] = [
            item
            for item in rooms
            if str(item.get("roomId") or "").strip() != normalized_room_id
        ]
        _store().save(state)

    _record_room_event("room", "chat_room.deleted", room, fields={"roundCount": len(room.get("rounds") or [])})
    return {"deleted": True, "roomId": normalized_room_id}


def reset_chat_room(room_id: str) -> dict[str, Any]:
    """Clear one room's discussion history while keeping its members and settings."""

    lang = get_web_language()
    normalized_room_id = str(room_id or "").strip()
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        room = _find_room(state, normalized_room_id)
        if room is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
        _raise_if_room_busy(room)
        old_rounds = [item for item in list(room.get("rounds") or []) if isinstance(item, dict)]
        cleared_round_count = len(old_rounds)
        cleared_message_count = sum(
            len([message for message in list(item.get("messages") or []) if isinstance(message, dict)])
            for item in old_rounds
        )
        now = utc_now_iso()
        room["rounds"] = []
        room["status"] = "ready"
        room["activeRoundId"] = ""
        room["updatedAt"] = now
        _store().save(state)
        room_payload = dict(room)

    session_cleanup = _remove_group_room_transcripts_from_participant_sessions(room_payload, normalized_room_id)
    group_context_cleanup = _disable_group_context_for_room(
        normalized_room_id,
    )
    _record_room_event(
        "room",
        "chat_room.reset",
        room_payload,
        fields={
            "clearedRoundCount": cleared_round_count,
            "clearedMessageCount": cleared_message_count,
            "participantCount": len(room_payload.get("participants") or []),
            "clearedSessionTranscriptCount": session_cleanup.get("removedMessageCount", 0),
            "cleanedSessionCount": session_cleanup.get("changedSessionCount", 0),
            "disabledGroupContextEventCount": group_context_cleanup.get("disabledEventCount", 0),
            "disabledGroupContextAgentCount": group_context_cleanup.get("changedAgentCount", 0),
        },
        outcome="reset",
        lifecycle=True,
    )
    _publish_chat_room_detail_snapshot(normalized_room_id)
    return _room_to_api(room_payload)


def create_chat_room(
    *,
    room_id: str = "",
    title: str = "",
    participant_session_ids: list[str] | None = None,
    participant_agent_ids: list[str] | None = None,
    participant_contexts_by_agent_id: dict[str, dict[str, Any]] | None = None,
    allow_empty_participants: bool = False,
    mode: str = DEFAULT_MODE,
    purpose: str = DEFAULT_PURPOSE,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lang = get_web_language()
    normalized_mode = _normalize_mode(mode or DEFAULT_MODE)
    normalized_purpose = _normalize_purpose(purpose or DEFAULT_PURPOSE)
    requested_room_id = str(room_id or "").strip()
    if requested_room_id and (_safe_fragment(requested_room_id) != requested_room_id or not requested_room_id.startswith("room-")):
        raise ChatRoomValidationError("Invalid chat room id.")
    _require_ready_mode(normalized_mode)
    # Lock order contract: participant resolution reads the session directory
    # (session_service / agent directory) and must not run under
    # _CHAT_ROOM_LOCK; resolve before taking the lock.
    participants = (
        _resolve_agent_participants(participant_agent_ids)
        if participant_agent_ids
        else _resolve_participants(participant_session_ids)
    )
    participants = _apply_participant_contexts(
        participants,
        participant_contexts_by_agent_id=participant_contexts_by_agent_id,
    )
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        existing_room_ids = {
            str(item.get("roomId") or "").strip()
            for item in state.get("rooms") or []
            if isinstance(item, dict)
        }
        if requested_room_id:
            if requested_room_id in existing_room_ids:
                raise ChatRoomValidationError("Chat room id already exists.")
            room_id = requested_room_id
        else:
            room_id = _new_id("room", existing_room_ids)
        if not participants and not allow_empty_participants:
            raise ChatRoomValidationError(
                text_for(lang, zh="至少需要一个可用会话才能创建群聊。", en="At least one session is required.")
            )
        now = utc_now_iso()
        room = {
            "roomId": room_id,
            "title": trim_lines(title or "", max_lines=1).strip()
            or text_for(lang, zh="Agent 群聊", en="Agent room"),
            "mode": normalized_mode,
            "purpose": normalized_purpose,
            "config": _safe_config(config),
            "participants": participants,
            "rounds": [],
            "status": "ready",
            "activeRoundId": "",
            "createdAt": now,
            "updatedAt": now,
        }
        state["rooms"] = list(state.get("rooms") or []) + [room]
        _store().save(state)
    _record_room_event(
        "room",
        "chat_room.created",
        room,
        fields={"participantCount": len(participants), "purpose": normalized_purpose},
    )
    return _room_to_api(room)


def start_chat_room_round(
    room_id: str,
    topic: str,
    *,
    mode: str = "",
    purpose: str = "",
    config: dict[str, Any] | None = None,
    agent_runner: AgentRunner | None = None,
    background: bool = False,
    lightweight_response: bool = False,
    max_topic_lines: int = 6,
    _model_invocation_receipt_authority: Mapping[str, Any] | None = None,
    _on_round_persisted: Callable[[Mapping[str, Any], Mapping[str, Any]], None]
    | None = None,
) -> dict[str, Any]:
    submit_started_at = _perf_counter()
    submit_timings: dict[str, Any] = {}
    lang = get_web_language()
    normalized_room_id = str(room_id or "").strip()
    normalized_topic = trim_lines(topic or "", max_lines=max_topic_lines).strip()
    if not normalized_topic:
        raise ChatRoomValidationError(text_for(lang, zh="请输入本轮群聊议题。", en="Enter a room topic."))

    # The meeting runtime passes teamId in the round config.  Resolve it from
    # the persisted room as a fallback for callers that only pass roomId; the
    # read is deliberately before inflight acquisition or any round write.
    supplied_config = config if isinstance(config, Mapping) else {}
    supplied_team_id = str(
        supplied_config.get("teamId")
        or supplied_config.get("researchTeamId")
        or ""
    ).strip()
    persisted_team_id = ""
    if normalized_room_id:
        existing_room = get_chat_room_detail(normalized_room_id)
        existing_config = (
            existing_room.get("config")
            if isinstance(existing_room, Mapping)
            and isinstance(existing_room.get("config"), Mapping)
            else {}
        )
        persisted_team_id = str(
            existing_config.get("teamId")
            or existing_config.get("researchTeamId")
            or ""
        ).strip()
    # A caller cannot evade a fenced research room by supplying a different
    # teamId in the round payload; persisted room scope is authoritative.
    maintenance_team_id = persisted_team_id or supplied_team_id
    from core.web.services.team_workflow.research_runtime.challenge_cup_maintenance_fence import (
        assert_writes_allowed,
    )

    assert_writes_allowed(maintenance_team_id, operation="chat_room_round_start")

    runner = agent_runner or _run_participant_agent
    if _model_invocation_receipt_authority is not None and not isinstance(
        _model_invocation_receipt_authority, Mapping
    ):
        raise ChatRoomValidationError("model invocation receipt authority must be an object")
    receipt_authority = (
        dict(_model_invocation_receipt_authority)
        if isinstance(_model_invocation_receipt_authority, Mapping)
        else None
    )
    if receipt_authority is None and _is_scoped_discussion_room(existing_room):
        # A workflow-scoped meeting room only exists for formal hypothesis
        # stages; its speaker turns must stay receipt-bound. Failing closed
        # here keeps every driving path (reopen, direct round API, scheduler)
        # from landing unverified formal content.
        raise ChatRoomValidationError(
            text_for(
                lang,
                zh="该群聊绑定正式工作流阶段，必须携带模型调用回执授权才能发起轮次。",
                en="This room is bound to a formal workflow stage; rounds require model invocation receipt authority.",
            )
        )
    challenge_deadline_at_ms = _resolve_challenge_room_deadline_at_ms(
        existing_room,
        supplied_config,
        receipt_authority=receipt_authority,
    )
    if background and not _try_acquire_chat_room_inflight():
        # Reject before any durable round write so the room stays clean.
        raise ChatRoomBusyError(
            text_for(
                lang,
                zh="当前群聊讨论任务较多，请稍后再发起。",
                en="Too many chat room rounds are queued; please retry in a moment.",
            )
        )
    for refresh_attempt in range(_CHAT_ROOM_PARTICIPANT_REFRESH_MAX_ATTEMPTS):
        with _CHAT_ROOM_LOCK:
            stage_started_at = _perf_counter()
            state = _store().load()
            submit_timings["storeLoadMs"] = _elapsed_ms(stage_started_at)
            room = _find_room(state, normalized_room_id)
            if room is None:
                if background:
                    _release_chat_room_inflight()
                raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
            try:
                _raise_if_room_busy(room)
            except ChatRoomBusyError:
                if background:
                    _release_chat_room_inflight()
                raise
            round_mode = _normalize_mode(mode or room.get("mode") or DEFAULT_MODE)
            round_purpose = _resolve_round_purpose(
                normalized_topic,
                purpose or room.get("purpose") or DEFAULT_PURPOSE,
            )
            stage_started_at = _perf_counter()
            try:
                _require_ready_mode(round_mode)
            except ChatRoomValidationError:
                if background:
                    _release_chat_room_inflight()
                raise
            submit_timings["schedulerResolveMs"] = _elapsed_ms(stage_started_at)
            round_config = {**_safe_config(room.get("config")), **_safe_config(config)}
            round_config.pop(_CHALLENGE_ROOM_DEADLINE_CONFIG_KEY, None)
            if challenge_deadline_at_ms is not None:
                round_config[_CHALLENGE_ROOM_DEADLINE_CONFIG_KEY] = challenge_deadline_at_ms
            participant_seed = copy.deepcopy(room.get("participants") or [])

        stage_started_at = _perf_counter()
        refreshed_participants = _refresh_chat_room_round_participants(
            participant_seed,
            preserve_scoped_session_ids=_is_challenge_discussion_room(room),
        )
        refreshed_participant_count = len(refreshed_participants)
        participants = _dedupe_chat_room_participants(refreshed_participants)
        submit_timings["participantDedupeRemoved"] = max(0, refreshed_participant_count - len(participants))
        submit_timings["participantRefreshMs"] = _elapsed_ms(stage_started_at)

        lock_wait_started_at = _perf_counter()
        with _CHAT_ROOM_LOCK:
            lock_acquired_at = _perf_counter()
            submit_timings["chatRoomLockWaitMs"] = _elapsed_ms_between(lock_wait_started_at, lock_acquired_at)
            stage_started_at = _perf_counter()
            state = _store().load()
            submit_timings["storeLoadMs"] = _elapsed_ms(stage_started_at)
            room = _find_room(state, normalized_room_id)
            if room is None:
                if background:
                    _release_chat_room_inflight()
                raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
            try:
                _raise_if_room_busy(room)
            except ChatRoomBusyError:
                if background:
                    _release_chat_room_inflight()
                raise
            if list(room.get("participants") or []) != participant_seed:
                if refresh_attempt == _CHAT_ROOM_PARTICIPANT_REFRESH_MAX_ATTEMPTS - 1:
                    if background:
                        _release_chat_room_inflight()
                    raise ChatRoomBusyError(
                        text_for(
                            lang,
                            zh="群聊成员正在更新，请重试",
                            en="Chat room members are being updated; please try again.",
                        )
                    )
                continue

            round_mode = _normalize_mode(mode or room.get("mode") or DEFAULT_MODE)
            round_purpose = _resolve_round_purpose(
                normalized_topic,
                purpose or room.get("purpose") or DEFAULT_PURPOSE,
            )
            stage_started_at = _perf_counter()
            try:
                scheduler = _require_ready_mode(round_mode)
            except ChatRoomValidationError:
                if background:
                    _release_chat_room_inflight()
                raise
            submit_timings["schedulerResolveMs"] = _elapsed_ms(stage_started_at)
            round_config = {**_safe_config(room.get("config")), **_safe_config(config)}
            round_config.pop(_CHALLENGE_ROOM_DEADLINE_CONFIG_KEY, None)
            if challenge_deadline_at_ms is not None:
                round_config[_CHALLENGE_ROOM_DEADLINE_CONFIG_KEY] = challenge_deadline_at_ms
            try:
                participant_candidates = (
                    refreshed_participants
                    if "participantAgentIds" in round_config
                    else participants
                )
                round_participants = _filter_round_participants_by_agent_ids(
                    participant_candidates, round_config
                )
            except ChatRoomValidationError:
                if background:
                    _release_chat_room_inflight()
                raise
            stage_started_at = _perf_counter()
            speakers = scheduler.select_speakers(
                round_participants,
                topic=normalized_topic,
                history=list(room.get("rounds") or []),
                config=round_config,
            )
            case_state = build_team_case_state(
                room=room,
                topic=normalized_topic,
                purpose=round_purpose,
                participants=round_participants,
                history=list(room.get("rounds") or []),
                config=round_config,
            )
            speakers = select_speakers_for_case(
                speakers,
                participants=round_participants,
                case_state=case_state,
            )
            speakers = _dedupe_chat_room_participants(speakers)
            try:
                _require_exact_frozen_speaker_roster(speakers, round_config)
            except ChatRoomValidationError:
                if background:
                    _release_chat_room_inflight()
                raise
            submit_timings["speakerSelectMs"] = _elapsed_ms(stage_started_at)
            if not speakers:
                if background:
                    _release_chat_room_inflight()
                raise ChatRoomValidationError(
                    text_for(lang, zh="群聊没有可发言的参与者。", en="The chat room has no enabled speakers.")
                )
            round_id = _new_id(
                "round",
                {
                    str(item.get("roundId") or "").strip()
                    for item in list(room.get("rounds") or [])
                    if isinstance(item, dict)
                },
            )
            now = utc_now_iso()
            round_payload = {
                "roundId": round_id,
                "roomId": normalized_room_id,
                "topic": normalized_topic,
                "mode": round_mode,
                "purpose": round_purpose,
                "config": round_config,
                "caseState": case_state,
                "status": "running",
                "speakerOrder": [item["participantId"] for item in speakers],
                "messages": [],
                "summary": "",
                "startedAt": now,
                "updatedAt": now,
                "finishedAt": "",
            }
            room["participants"] = participants
            room["rounds"] = list(room.get("rounds") or []) + [round_payload]
            room["status"] = "running"
            room["activeRoundId"] = round_id
            room["updatedAt"] = now
            stage_started_at = _perf_counter()
            _store().save(state)
            submit_timings["storeSaveMs"] = _elapsed_ms(stage_started_at)
            stage_started_at = _perf_counter()
            _create_chat_room_round_control(normalized_room_id, round_id)
            submit_timings["roundControlCreateMs"] = _elapsed_ms(stage_started_at)
            submit_timings["chatRoomLockedMs"] = _elapsed_ms_between(lock_acquired_at)
            break

    inflight_submitted = False
    try:
        if _on_round_persisted is not None:
            _on_round_persisted(room, round_payload)
        # A background round must become observable as soon as its durable room
        # and round records exist. Kernel tracing and WorkRun persistence can
        # touch other stores, so doing either before ``submit`` makes sibling
        # candidate reviews wait behind an unrelated slow trace.
        if not background:
            stage_started_at = _perf_counter()
            kernel_trace = _create_chat_room_round_kernel_trace(room, round_payload, speakers)
            if kernel_trace:
                room, round_payload = _attach_chat_room_round_kernel_trace(
                    normalized_room_id,
                    round_id,
                    kernel_trace,
                    fallback_room=room,
                    fallback_round=round_payload,
                )
            submit_timings["kernelTraceMs"] = _elapsed_ms(stage_started_at)

            stage_started_at = _perf_counter()
            _persist_chat_room_work_run(room, round_payload, status="running", summary="")
            submit_timings["workRunPersistMs"] = _elapsed_ms(stage_started_at)
        submit_timings["submitElapsedBeforeStartLogMs"] = _elapsed_ms(submit_started_at)
        _record_room_event(
            "round",
            "chat_room.round.started",
            room,
            round_payload,
            fields={
                "mode": round_mode,
                "purpose": round_purpose,
                "participantCount": len(speakers),
                "caseIntent": case_state.get("intent") or "",
                "caseNextAction": case_state.get("nextAction") or "",
                "caseInformationSufficiency": case_state.get("informationSufficiency") or "",
                "caseUserFacingMode": case_state.get("userFacingMode") or "",
                "caseDiscussionVisibility": case_state.get("discussionVisibility") or "",
                "caseMissingFactCount": len(list(case_state.get("missingFacts") or [])),
                **submit_timings,
            },
            outcome="running",
            lifecycle=True,
        )
        stage_started_at = _perf_counter()
        _publish_chat_room_detail_snapshot(normalized_room_id)
        submit_timings["initialSnapshotPublishMs"] = _elapsed_ms(stage_started_at)

        if background:
            schedule_started_at = _perf_counter()
            _submit_chat_room_round_background(
                normalized_room_id,
                round_id,
                room,
                round_payload,
                speakers,
                runner,
                lang,
                receipt_authority,
            )
            inflight_submitted = True
            submit_timings["scheduleSubmitMs"] = _elapsed_ms(schedule_started_at)
            _record_room_event(
                "round",
                "chat_room.round.background_started",
                room,
                round_payload,
                fields={
                    "mode": round_mode,
                    "purpose": round_purpose,
                    "participantCount": len(speakers),
                    "caseIntent": case_state.get("intent") or "",
                    "caseNextAction": case_state.get("nextAction") or "",
                    "caseInformationSufficiency": case_state.get("informationSufficiency") or "",
                    "caseUserFacingMode": case_state.get("userFacingMode") or "",
                    "caseDiscussionVisibility": case_state.get("discussionVisibility") or "",
                    "caseMissingFactCount": len(list(case_state.get("missingFacts") or [])),
                    **submit_timings,
                },
                outcome="running",
                lifecycle=True,
            )
            if lightweight_response:
                return _accepted_chat_room_round_payload(room, round_payload)
            detail_started_at = _perf_counter()
            detail = get_chat_room_detail(normalized_room_id)
            submit_timings["returnDetailMs"] = _elapsed_ms(detail_started_at)
            if detail is None:
                raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
            return detail

        return _execute_chat_room_round(
            normalized_room_id,
            round_id,
            room,
            round_payload,
            speakers,
            runner,
            lang,
            receipt_authority,
        )


    except Exception as exc:  # noqa: BLE001 - the round is already durable-running
        # The launch window between the durable running write and the executor
        # submission must fail the round on any error, otherwise the control
        # marker keeps reconcile away and the room stays busy until restart.
        if background and not inflight_submitted:
            # submit never enqueued the wrapper, so the slot is still ours.
            _release_chat_room_inflight()
        _fail_chat_room_round(
            normalized_room_id,
            round_id,
            room,
            round_payload,
            exc,
            lang=lang,
        )
        raise
def _try_acquire_chat_room_inflight() -> bool:
    global _CHAT_ROOM_INFLIGHT_COUNT
    with _CHAT_ROOM_INFLIGHT_LOCK:
        if _CHAT_ROOM_INFLIGHT_COUNT >= _CHAT_ROOM_MAX_INFLIGHT_ROUNDS:
            return False
        _CHAT_ROOM_INFLIGHT_COUNT += 1
        return True


def _release_chat_room_inflight() -> None:
    global _CHAT_ROOM_INFLIGHT_COUNT
    with _CHAT_ROOM_INFLIGHT_LOCK:
        _CHAT_ROOM_INFLIGHT_COUNT = max(0, _CHAT_ROOM_INFLIGHT_COUNT - 1)


def _submit_chat_room_round_background(
    room_id: str,
    round_id: str,
    room: dict[str, Any],
    round_payload: dict[str, Any],
    speakers: list[dict[str, Any]],
    runner: AgentRunner,
    lang: str,
    receipt_authority: dict[str, Any] | None,
) -> None:
    """Submit the worker; the wrapper always releases the inflight slot.

    A failed ``submit`` never enqueues the wrapper, so the caller's launch
    window handler stays responsible for the release in that case.
    """

    _CHAT_ROOM_EXECUTOR.submit(
        _run_chat_room_round_background_with_release,
        room_id,
        round_id,
        room,
        round_payload,
        speakers,
        runner,
        lang,
        receipt_authority,
        _perf_counter(),
    )


def _run_chat_room_round_background_with_release(*args: Any, **kwargs: Any) -> Any:
    try:
        return _run_chat_room_round_background(*args, **kwargs)
    finally:
        _release_chat_room_inflight()


def _create_chat_room_round_kernel_trace(
    room: dict[str, Any],
    round_payload: dict[str, Any],
    speakers: list[dict[str, Any]],
) -> dict[str, Any]:
    room_id = str(room.get("roomId") or round_payload.get("roomId") or "").strip()
    round_id = str(round_payload.get("roundId") or "").strip()
    if not room_id or not round_id:
        return {}
    speaker_agent_ids = _speaker_agent_ids(speakers)
    topic = str(round_payload.get("topic") or "").strip()
    event_payload = {
        "eventId": f"chat-room-round-{room_id}-{round_id}",
        "sender": {"type": "system", "id": "chat_room_service"},
        "recipientAgentIds": speaker_agent_ids,
        "semanticType": "chat_room.round",
        "payload": {
            "goal": f"Chat room round: {topic or round_id}",
            "content": topic,
            "roomId": room_id,
            "roundId": round_id,
            "mode": str(round_payload.get("mode") or DEFAULT_MODE).strip() or DEFAULT_MODE,
            "purpose": _normalize_purpose(round_payload.get("purpose") or room.get("purpose") or DEFAULT_PURPOSE),
            "speakerCount": len(speakers),
        },
        "correlationId": f"chat-room:{room_id}",
        "idempotencyKey": f"chat-room-round:{room_id}:{round_id}",
        "wakeTarget": False,
        "traceOnly": True,
        "metadata": {
            "sourceSurface": "chat_room_round",
            "sourceRoomId": room_id,
            "sourceMessageId": round_id,
            "projectionRef": {"kind": "chat_room_round", "id": round_id},
            "adapterVersion": "chat-room-kernel-shadow-v1",
            "roomId": room_id,
            "roundId": round_id,
            "mode": str(round_payload.get("mode") or DEFAULT_MODE).strip() or DEFAULT_MODE,
            "purpose": _normalize_purpose(round_payload.get("purpose") or room.get("purpose") or DEFAULT_PURPOSE),
            "participantCount": len(speakers),
            "speakerAgentIds": speaker_agent_ids,
            "messageSummary": topic,
            "inboxCreatedBy": "chat_room_kernel_trace",
        },
    }
    try:
        from core.agent_kernel import service as agent_kernel_service

        if getattr(agent_kernel_service, "PROJECT_ROOT", PROJECT_ROOT) != PROJECT_ROOT:
            agent_kernel_service.PROJECT_ROOT = PROJECT_ROOT
        result = agent_kernel_service.handle_kernel_event(event_payload)
    except Exception as exc:
        trace = {
            "source": "agent_kernel",
            "traceOnly": True,
            "status": "failed",
            "errorType": type(exc).__name__,
            "reason": trim_lines(str(exc), max_lines=2),
        }
        _record_room_event(
            "kernel",
            "chat_room.round.kernel_trace_failed",
            room,
            round_payload,
            fields={
                "errorType": trace["errorType"],
                "reason": trace["reason"],
                "traceOnly": True,
            },
            outcome="failed",
            level="warning",
        )
        return trace

    event = result.get("event") if isinstance(result.get("event"), dict) else {}
    task = result.get("task") if isinstance(result.get("task"), dict) else {}
    execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
    outcome_payload = result.get("outcome") if isinstance(result.get("outcome"), dict) else {}
    trace = {
        "source": "agent_kernel",
        "traceOnly": True,
        "status": "recorded",
        "eventId": str(event.get("eventId") or "").strip(),
        "taskId": str(task.get("taskId") or "").strip(),
        "workRunId": str(execution.get("workRunId") or "").strip(),
        "outcomeId": str(outcome_payload.get("outcomeId") or "").strip(),
        "outcomeStatus": str(outcome_payload.get("status") or task.get("status") or "").strip(),
        "reused": bool(result.get("reused")),
    }
    _record_room_event(
        "kernel",
        "chat_room.round.kernel_trace_recorded",
        room,
        round_payload,
        fields={
            "traceOnly": True,
            "kernelEventId": trace["eventId"],
            "kernelTaskId": trace["taskId"],
            "kernelWorkRunId": trace["workRunId"],
            "kernelOutcomeId": trace["outcomeId"],
            "kernelOutcomeStatus": trace["outcomeStatus"],
            "reused": trace["reused"],
        },
        outcome=trace["outcomeStatus"] or "succeeded",
        lifecycle=True,
    )
    return trace


def _attach_chat_room_round_kernel_trace(
    room_id: str,
    round_id: str,
    kernel_trace: dict[str, Any],
    *,
    fallback_room: dict[str, Any],
    fallback_round: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    safe_trace = _chat_room_kernel_trace_summary({"kernel": kernel_trace})
    if not safe_trace:
        return fallback_room, fallback_round
    next_room = dict(fallback_room)
    next_round = {**dict(fallback_round), "kernel": safe_trace}
    next_rounds = []
    for item in list(next_room.get("rounds") or []):
        if isinstance(item, dict) and str(item.get("roundId") or "").strip() == round_id:
            next_rounds.append(dict(next_round))
        else:
            next_rounds.append(item)
    next_room["rounds"] = next_rounds

    try:
        with _CHAT_ROOM_LOCK:
            state = _store().load()
            live_room = _find_room(state, room_id)
            if live_room is None:
                return next_room, next_round
            target_round = _find_round(live_room, round_id)
            if target_round is None:
                return dict(live_room), next_round
            target_round["kernel"] = dict(safe_trace)
            live_room["updatedAt"] = utc_now_iso()
            _store().save(state)
            return dict(live_room), dict(target_round)
    except Exception:
        return next_room, next_round


def _speaker_agent_ids(speakers: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for speaker in list(speakers or []):
        if not isinstance(speaker, dict):
            continue
        agent_id = str(speaker.get("agentId") or "").strip()
        if agent_id and agent_id not in seen:
            seen.add(agent_id)
            result.append(agent_id)
    return result


def _accepted_chat_room_round_payload(room: dict[str, Any], round_payload: dict[str, Any]) -> dict[str, Any]:
    """Return a small accepted-round payload for clients that refresh via SSE/refetch."""

    accepted_at = str(round_payload.get("startedAt") or "").strip() or utc_now_iso()
    return {
        "accepted": True,
        "roomId": str(room.get("roomId") or round_payload.get("roomId") or "").strip(),
        "roundId": str(round_payload.get("roundId") or "").strip(),
        "activeRoundId": str(round_payload.get("roundId") or "").strip(),
        "status": str(round_payload.get("status") or "running").strip() or "running",
        "topic": str(round_payload.get("topic") or "").strip(),
        "mode": str(round_payload.get("mode") or "").strip(),
        "purpose": str(round_payload.get("purpose") or "").strip(),
        "speakerOrder": list(round_payload.get("speakerOrder") or []),
        "acceptedAt": accepted_at,
    }


def stop_chat_room_round(room_id: str, *, reason: str = "") -> dict[str, Any]:
    """Request and persist a user stop for the active chat room round."""

    lang = get_web_language()
    normalized_room_id = str(room_id or "").strip()
    if not normalized_room_id:
        raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
    stop_reason = str(reason or "").strip() or text_for(
        lang,
        zh="用户请求停止当前群聊轮次。",
        en="The user requested the current chat room round to stop.",
    )
    stopping_at = utc_now_iso()
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        room = _find_room(state, normalized_room_id)
        if room is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
        active_round_id = str(room.get("activeRoundId") or "").strip()
        target_round = _find_round(room, active_round_id) if active_round_id else None
        if (
            target_round is None
            or str(target_round.get("status") or "").strip().lower() not in RUNNING_ROUND_STATUSES
        ):
            raise ChatRoomBusyError(text_for(lang, zh="当前群聊没有正在运行的轮次。", en="No chat room round is running."))
        _request_chat_room_round_stop(active_round_id, stop_reason)
        target_round["status"] = "stopping"
        target_round["summary"] = text_for(
            lang,
            zh="正在停止当前群聊轮次，等待正在发言的 Agent 收尾。",
            en="Stopping this chat room round while the current agent finishes.",
        )
        target_round["updatedAt"] = stopping_at
        target_round["finishedAt"] = ""
        room["status"] = "stopping"
        room["activeRoundId"] = active_round_id
        room["updatedAt"] = stopping_at
        _store().save(state)
        room_payload = dict(room)
        round_payload = dict(target_round)

    # Lock order contract: the scheduler cancel touches the session turn
    # scheduler's own lock and must never run while holding _CHAT_ROOM_LOCK.
    session_service.cancel_agent_execution_reservation(active_round_id)
    _persist_chat_room_work_run(
        room_payload,
        round_payload,
        status="stopping",
        summary=str(round_payload.get("summary") or stop_reason),
    )
    _record_room_event(
        "round",
        "chat_room.round.stop_requested",
        room_payload,
        round_payload,
        fields={"reason": trim_lines(stop_reason, max_lines=2)},
        outcome="stopping",
        lifecycle=True,
    )
    _publish_chat_room_detail_snapshot(normalized_room_id)
    return _room_to_api(room_payload)


def stream_chat_room_events(room_id: str, initial_detail: dict[str, Any] | None = None):
    """Yield SSE snapshots for one chat room."""

    normalized_room_id = str(room_id or "").strip()
    if not normalized_room_id:
        raise ChatRoomNotFoundError(text_for(get_web_language(), zh="未找到群聊。", en="Chat room not found."))
    detail = initial_detail or get_chat_room_detail(normalized_room_id)
    if detail is None:
        raise ChatRoomNotFoundError(text_for(get_web_language(), zh="未找到群聊。", en="Chat room not found."))

    subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_CHAT_ROOM_STREAM_QUEUE_SIZE)
    _register_chat_room_stream_subscriber(normalized_room_id, subscriber)
    try:
        yield _encode_chat_room_sse_event(
            "chat_room_detail",
            {
                "type": "chat_room_detail",
                "roomId": normalized_room_id,
                "detail": detail,
            },
        )
        while True:
            try:
                event = subscriber.get(timeout=_CHAT_ROOM_STREAM_HEARTBEAT_SECONDS)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield _encode_chat_room_sse_event(str(event.get("type") or "message"), event)
    finally:
        _unregister_chat_room_stream_subscriber(normalized_room_id, subscriber)


def _run_chat_room_round_background(
    room_id: str,
    round_id: str,
    room: dict[str, Any],
    round_payload: dict[str, Any],
    speakers: list[dict[str, Any]],
    runner: AgentRunner,
    lang: str,
    receipt_authority: dict[str, Any] | None = None,
    submitted_at_monotonic: float | None = None,
) -> None:
    worker_started_at = _perf_counter()
    _record_room_event(
        "round",
        "chat_room.round.worker_started",
        room,
        round_payload,
        fields={
            "participantCount": len(speakers),
            "scheduleToWorkerStartedMs": _elapsed_ms_between(submitted_at_monotonic, worker_started_at),
        },
        outcome="running",
        lifecycle=True,
    )
    try:
        kernel_trace = _create_chat_room_round_kernel_trace(room, round_payload, speakers)
        if kernel_trace:
            room, round_payload = _attach_chat_room_round_kernel_trace(
                room_id,
                round_id,
                kernel_trace,
                fallback_room=room,
                fallback_round=round_payload,
            )
        _persist_chat_room_work_run(room, round_payload, status="running", summary="")
        _execute_chat_room_round(
            room_id,
            round_id,
            room,
            round_payload,
            speakers,
            runner,
            lang,
            receipt_authority,
        )
    except Exception as exc:
        _fail_chat_room_round(room_id, round_id, room, round_payload, exc, lang=lang)


def _meeting_digest_ttl_mute_for_context(
    context: Mapping[str, Any],
    probe: dict[str, Any],
) -> dict[str, Any] | None:
    """Digest-wait TTL projection for one meeting-bound speaker boundary.

    ``probe`` outlives the per-speaker context rebuilds: the meeting record
    is re-read at most once per poll interval.  The mute engages
    monotonically (digest age only grows), so the short cache keeps the
    per-speaker cost flat without delaying the stop-loss meaningfully.
    """

    meeting_round_id = str(context.get("meetingRoundId") or "").strip()
    team_id = str(context.get("teamId") or "").strip()
    if not meeting_round_id or not team_id:
        return None
    now = time.monotonic()
    read_at = probe.get("readAtMonotonic")
    if (
        isinstance(read_at, (int, float))
        and now - float(read_at) < _MEETING_DIGEST_TTL_POLL_INTERVAL_SECONDS
    ):
        mute = probe.get("mute")
        return mute if isinstance(mute, dict) else None
    from core.web.services.team_workflow import meeting_runtime

    mute = meeting_runtime.meeting_digest_ttl_mute(team_id, meeting_round_id)
    probe["readAtMonotonic"] = now
    probe["mute"] = mute
    return mute


def _execute_chat_room_round(
    normalized_room_id: str,
    round_id: str,
    room: dict[str, Any],
    round_payload: dict[str, Any],
    speakers: list[dict[str, Any]],
    runner: AgentRunner,
    lang: str,
    receipt_authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    round_mode = str(round_payload.get("mode") or DEFAULT_MODE).strip() or DEFAULT_MODE
    round_purpose = _normalize_purpose(round_payload.get("purpose") or room.get("purpose") or DEFAULT_PURPOSE)
    normalized_topic = str(round_payload.get("topic") or "").strip()

    messages: list[dict[str, Any]] = []
    # Digest-wait TTL probe cache; it outlives the per-speaker context
    # rebuild so one round re-reads the meeting record at most once per
    # poll interval.
    meeting_ttl_probe: dict[str, Any] = {"readAtMonotonic": 0.0, "mute": None}
    for index, participant in enumerate(speakers):
        speaker_started_at = _perf_counter()
        stopped_detail = _stopped_chat_room_round_detail(normalized_room_id, round_id)
        if stopped_detail is not None:
            _clear_chat_room_round_control(round_id)
            return stopped_detail
        round_config = (
            round_payload.get("config")
            if isinstance(round_payload.get("config"), dict)
            else {}
        )
        context = {
            "roomId": normalized_room_id,
            "roundId": round_id,
            "topic": normalized_topic,
            "mode": round_mode,
            "purpose": round_purpose,
            "caseState": dict(round_payload.get("caseState") or {})
            if isinstance(round_payload.get("caseState"), dict)
            else {},
            "speakerIndex": index,
            "meetingRoundId": str(round_config.get("meetingRoundId") or "").strip(),
            "meetingType": str(round_config.get("meetingType") or "").strip().lower(),
            "teamId": str(round_config.get("teamId") or "").strip(),
            "questionId": str(round_config.get("question") or "").strip().upper(),
            "challengeDeadlineAtMs": _positive_int(
                round_config.get(_CHALLENGE_ROOM_DEADLINE_CONFIG_KEY)
            ),
            "_structuredMeetingMessage": _uses_structured_meeting_message(
                room, round_payload
            ),
            "_modelInvocationReceiptAuthority": receipt_authority,
        }
        per_call_budget_ms = _positive_int(round_config.get("perCallBudgetMs"))
        if per_call_budget_ms is None:
            # Speaker watchdog: plain meeting/discussion rooms have no
            # challenge meeting clock, but every speaker call still needs a
            # bounded budget so a hung LLM call cannot occupy the round
            # forever.  Challenge rooms keep their policy-derived budget.
            per_call_budget_ms = _CHAT_ROOM_SPEAKER_DEFAULT_PER_CALL_BUDGET_MS
        from core.web.services.team_workflow.challenge_deadline_policy import (
            effective_call_deadline_at_ms,
        )

        # The meeting-level clock stays in ``challengeDeadlineAtMs``; the
        # per-call fence lives in its own key so an exhausted speaker call
        # can never be mistaken for an exhausted meeting.  Plain rooms have
        # no outer deadline, so the per-call budget alone defines the fence.
        context[_CHALLENGE_ROOM_PER_CALL_DEADLINE_CONTEXT_KEY] = effective_call_deadline_at_ms(
            call_started_at_ms=int(time.time() * 1000),
            per_call_budget_ms=per_call_budget_ms,
            meeting_deadline_at_ms=_positive_int(
                round_config.get("meetingDeadlineAtMs")
            )
            or context["challengeDeadlineAtMs"],
            outer_deadline_at_ms=context["challengeDeadlineAtMs"],
        )
        # A deadline is an absolute round fence.  Check it before constructing
        # the next prompt so an expired formal round never starts another
        # speaker, even when the previous runner returned a late result.
        if _request_challenge_room_execution_stop(round_id, context, force_run_read=True):
            stopped_detail = _stopped_chat_room_round_detail(normalized_room_id, round_id)
            if stopped_detail is not None:
                _clear_chat_room_round_control(round_id)
                return stopped_detail
        # Digest-wait TTL stop-loss: a meeting whose digest draft has been
        # waiting past the TTL gets no further speaker calls.  Completed
        # speakers stay persisted; the meeting record, its digest draft and
        # operator approve/close are untouched (finalize guard in
        # meeting_runtime keeps the TTL stop from terminating the meeting).
        meeting_ttl_mute = _meeting_digest_ttl_mute_for_context(context, meeting_ttl_probe)
        if meeting_ttl_mute is not None:
            _request_chat_room_round_stop(round_id, _MEETING_DIGEST_TTL_STOP_REASON)
            try:
                from core.web.services.team_workflow import meeting_runtime

                meeting_runtime.record_meeting_digest_ttl_mute_event(
                    str(context.get("teamId") or ""),
                    str(context.get("meetingRoundId") or ""),
                    surface="chat_room_round",
                    room_id=normalized_room_id,
                    room_round_id=round_id,
                )
            except Exception:  # noqa: BLE001 - evidence never blocks the fence
                pass
            stopped_detail = _stopped_chat_room_round_detail(normalized_room_id, round_id)
            if stopped_detail is not None:
                _clear_chat_room_round_control(round_id)
                return stopped_detail
        prompt = _build_participant_prompt(
            room=room,
            round_payload=round_payload,
            participant=participant,
            prior_messages=messages,
        )
        prompt_build_ms = _elapsed_ms(speaker_started_at)
        context["speakerStartedAtMonotonic"] = speaker_started_at
        context["promptBuildMs"] = prompt_build_ms
        message = _run_one_speaker(participant, prompt, context, runner)
        speaker_run_ms = _elapsed_ms(speaker_started_at)
        # Tiered fence: only a meeting-level (or workflow-run) expiry returns a
        # reason that has registered a round stop.  A per-call expiry aborts
        # just this speaker call, so a late result is discarded and the round
        # advances to the next speaker.
        stop_reason = _challenge_room_speaker_abort_reason(
            round_id,
            context,
            force_run_read=True,
        )
        if stop_reason and str(message.get("status") or "").strip().lower() == "completed":
            # The provider/custom runner returned after the formal fence. Keep
            # only auditable stop metadata; late content cannot become formal
            # meeting evidence.
            message = {
                **message,
                "status": "stopped",
                "resultStatus": "stopped",
                "content": "",
                "summary": stop_reason,
                "lateResultDiscarded": True,
            }
            message.pop("messagePayload", None)
        messages.append(message)
        message_time = utc_now_iso()
        stop_pending = False
        with _CHAT_ROOM_LOCK:
            state = _store().load()
            live_room = _find_room(state, normalized_room_id)
            if live_room is None:
                raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
            target_round = _find_round(live_room, round_id)
            if target_round is None:
                raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊轮次。", en="Chat room round not found."))
            if _chat_room_round_is_terminal(live_room, target_round, round_id):
                _clear_chat_room_round_control(round_id)
                return _room_to_api(live_room)
            if _chat_room_round_stop_reason(round_id):
                # A stop arrived between the outer check and this lock: persist
                # the latest messages without rewinding the round to running,
                # then let the shared stop finalizer close the round.  The
                # finalizer performs session sync (chat-state transaction), so
                # per the lock order contract it must run after releasing
                # _CHAT_ROOM_LOCK.
                target_round["messages"] = [dict(item) for item in messages]
                target_round["updatedAt"] = message_time
                _store().save(state)
                locked_room_snapshot = dict(live_room)
                stop_pending = True
            else:
                target_round["messages"] = [dict(item) for item in messages]
                target_round["status"] = "running"
                target_round["updatedAt"] = message_time
                live_room["status"] = "running"
                live_room["activeRoundId"] = round_id
                live_room["updatedAt"] = message_time
                _store().save(state)
                room = dict(live_room)
                round_payload = dict(target_round)
        if stop_pending:
            stopped = _stopped_chat_room_round_detail(normalized_room_id, round_id)
            if stopped is not None:
                _clear_chat_room_round_control(round_id)
                return stopped
            return _room_to_api(locked_room_snapshot)
        _persist_chat_room_work_run(
            room,
            round_payload,
            status="running",
            summary=text_for(
                lang,
                zh=f"群聊进行中：{len(messages)}/{len(speakers)} 位 Agent 已发言。",
                en=f"Group discussion running: {len(messages)}/{len(speakers)} agents responded.",
            ),
        )
        _publish_chat_room_detail_snapshot(normalized_room_id)
        _record_room_event(
            "speaker",
            _speaker_event_code(message.get("status")),
            room,
            round_payload,
            fields={
                "participantId": participant["participantId"],
                "sessionId": participant.get("sessionId") or "",
                "speakerIndex": index,
                "status": message["status"],
                "purpose": round_purpose,
                "caseIntent": (round_payload.get("caseState") or {}).get("intent") if isinstance(round_payload.get("caseState"), dict) else "",
                "caseNextAction": (round_payload.get("caseState") or {}).get("nextAction") if isinstance(round_payload.get("caseState"), dict) else "",
                "caseInformationSufficiency": (round_payload.get("caseState") or {}).get("informationSufficiency") if isinstance(round_payload.get("caseState"), dict) else "",
                "caseUserFacingMode": (round_payload.get("caseState") or {}).get("userFacingMode") if isinstance(round_payload.get("caseState"), dict) else "",
                "caseDiscussionVisibility": (round_payload.get("caseState") or {}).get("discussionVisibility") if isinstance(round_payload.get("caseState"), dict) else "",
                "contentChars": len(message.get("content") or ""),
                "errorType": message.get("errorType") or "",
                "promptBuildMs": prompt_build_ms,
                "speakerRunMs": speaker_run_ms,
                **_participant_team_event_fields(participant),
                **(message.get("timings") if isinstance(message.get("timings"), dict) else {}),
            },
            outcome=message["status"],
            level="info" if message["status"] == "completed" else "warning",
        )

    completed_count = sum(1 for item in messages if item.get("status") == "completed")
    failed_count = sum(1 for item in messages if item.get("status") == "failed")
    blocked_count = sum(1 for item in messages if item.get("status") == "blocked")
    stopped_count = sum(1 for item in messages if item.get("status") == "stopped")
    partial_count = sum(1 for item in messages if item.get("status") == "partial")
    unsuccessful_count = len(messages) - completed_count
    if completed_count == len(messages):
        final_status = "completed"
    elif completed_count > 0 or partial_count > 0:
        final_status = "partial"
    else:
        final_status = "failed"
    summary = _round_summary(messages, lang=lang)
    finished_at = utc_now_iso()
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        room = _find_room(state, normalized_room_id)
        if room is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
        target_round = _find_round(room, round_id)
        if target_round is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊轮次。", en="Chat room round not found."))
        if _chat_room_round_is_terminal(room, target_round, round_id):
            _clear_chat_room_round_control(round_id)
            return _room_to_api(room)
        target_round["messages"] = messages
        target_round["summary"] = summary
        target_round["status"] = final_status
        target_round["updatedAt"] = finished_at
        target_round["finishedAt"] = finished_at
        room["status"] = "ready" if final_status in {"completed", "partial"} else "failed"
        room["activeRoundId"] = ""
        room["updatedAt"] = finished_at
        _store().save(state)

    _persist_chat_room_work_run(room, target_round, status=final_status, summary=summary)
    _record_room_event(
        "round",
        f"chat_room.round.{final_status}",
        room,
        target_round,
        fields={
            "mode": round_mode,
            "purpose": round_purpose,
            "messageCount": len(messages),
            "completedCount": completed_count,
            "failedCount": failed_count,
            "blockedCount": blocked_count,
            "stoppedCount": stopped_count,
            "partialCount": partial_count,
            "unsuccessfulCount": unsuccessful_count,
            "caseIntent": (target_round.get("caseState") or {}).get("intent") if isinstance(target_round.get("caseState"), dict) else "",
            "caseNextAction": (target_round.get("caseState") or {}).get("nextAction") if isinstance(target_round.get("caseState"), dict) else "",
            "caseInformationSufficiency": (target_round.get("caseState") or {}).get("informationSufficiency") if isinstance(target_round.get("caseState"), dict) else "",
            "caseUserFacingMode": (target_round.get("caseState") or {}).get("userFacingMode") if isinstance(target_round.get("caseState"), dict) else "",
            "caseDiscussionVisibility": (target_round.get("caseState") or {}).get("discussionVisibility") if isinstance(target_round.get("caseState"), dict) else "",
        },
        outcome=final_status,
        level="info" if final_status == "completed" else ("warning" if final_status == "partial" else "error"),
        lifecycle=True,
    )
    if completed_count > 0:
        _sync_group_context_events(room, target_round)
        _sync_group_round_to_participant_sessions(room, target_round)
    _publish_chat_room_detail_snapshot(normalized_room_id)
    _clear_chat_room_round_control(round_id)
    try:
        from core.web.services.team_workflow import meeting_runtime

        meeting_runtime.maybe_auto_draft_after_chat_round(room, target_round)
    except Exception:
        pass
    return _room_to_api(room)


def load_chat_room_work_run_summary() -> dict[str, Any]:
    store = _work_run_store()
    active_items = list_active_chat_room_work_runs()
    active = store.load_active_snapshot(RUN_KIND)
    if not active_items and isinstance(active, dict):
        active = _reconcile_missing_room_active_work_run(store, active)
    if not active and active_items:
        active = active_items[0]
    return {
        "active": active,
        "activeItems": active_items,
        "latest": store.load_latest_snapshot(RUN_KIND),
    }


def list_active_chat_room_work_runs() -> list[dict[str, Any]]:
    """Return all active chat room rounds as lightweight WorkRun snapshots."""

    _reconcile_chat_room_round_state()
    try:
        state = _store().load()
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for room in list(state.get("rooms") or []):
        if not isinstance(room, dict):
            continue
        active_round_id = str(room.get("activeRoundId") or "").strip()
        for round_payload in list(room.get("rounds") or []):
            if not isinstance(round_payload, dict):
                continue
            round_id = str(round_payload.get("roundId") or "").strip()
            status = str(round_payload.get("status") or "").strip().lower()
            if status not in RUNNING_ROUND_STATUSES:
                continue
            if active_round_id and round_id != active_round_id:
                continue
            items.append(_chat_room_work_run_snapshot(room, round_payload, status=status))
    items.sort(key=lambda item: str(item.get("updatedAt") or item.get("startedAt") or ""))
    return items


def _reconcile_missing_room_active_work_run(
    store: work_run_store.WorkRunStore,
    active_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    """Close an indexed active round only after its persisted room is gone.

    A WorkRun is an audit record, not an independent execution authority.  When
    the room record no longer exists, leaving a ``running`` snapshot indexed as
    active can indefinitely block a managed restart even though no task can be
    stopped or resumed.  Preserve the snapshot and make the terminal reason
    explicit instead of deleting it or guessing about a surviving room.
    """

    room_id = str(active_snapshot.get("roomId") or "").strip()
    round_id = str(active_snapshot.get("roundId") or active_snapshot.get("runId") or "").strip()
    if not room_id or not round_id:
        return active_snapshot
    try:
        state = _store().load()
    except Exception:
        return active_snapshot
    rooms = state.get("rooms") if isinstance(state, dict) else None
    if not isinstance(rooms, list) or any(
        isinstance(room, dict) and str(room.get("roomId") or "").strip() == room_id
        for room in rooms
    ):
        return active_snapshot

    status = str(active_snapshot.get("status") or active_snapshot.get("currentPhase") or "").strip().lower()
    if status not in RUNNING_ROUND_STATUSES:
        store.persist_snapshot(RUN_KIND, active_snapshot, active_run_id="")
        return None

    reconciled_at = utc_now_iso()
    reason = text_for(
        get_web_language(),
        zh="关联群聊已不存在，已收口遗留运行记录。",
        en="The linked chat room no longer exists, so the stale work run was closed.",
    )
    reconciled = dict(active_snapshot)
    reconciled.update(
        {
            "status": "stopped",
            "currentPhase": "stopped",
            "runtimeStatus": "orphaned_room_reconciled",
            "reconciliationSource": "missing_room_record",
            "summary": reason,
            "updatedAt": reconciled_at,
            "finishedAt": reconciled_at,
        }
    )
    store.persist_snapshot(RUN_KIND, reconciled, active_run_id="")
    return None


def force_stop_active_chat_room_rounds_for_shutdown(reason: str) -> list[dict[str, object]]:
    """Mark active chat room rounds as stopped before the backend exits."""

    stop_reason = str(reason or "").strip() or text_for(
        get_web_language(),
        zh="工作台关闭前停止活跃群聊轮次。",
        en="Stopped active chat room rounds before workbench shutdown.",
    )
    stopped_at = utc_now_iso()
    stopped: list[dict[str, object]] = []
    changed = False
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        for room in list(state.get("rooms") or []):
            if not isinstance(room, dict):
                continue
            active_round_id = str(room.get("activeRoundId") or "").strip()
            for round_payload in list(room.get("rounds") or []):
                if not isinstance(round_payload, dict):
                    continue
                round_id = str(round_payload.get("roundId") or "").strip()
                status = str(round_payload.get("status") or "").strip().lower()
                if status not in RUNNING_ROUND_STATUSES:
                    continue
                if active_round_id and round_id != active_round_id:
                    continue
                _request_chat_room_round_stop(round_id, stop_reason)
                summary = _stopped_round_summary(
                    stop_reason,
                    message_count=len(list(round_payload.get("messages") or [])),
                    speaker_count=len(list(round_payload.get("speakerOrder") or [])),
                )
                round_payload["status"] = "stopped"
                round_payload["summary"] = summary
                round_payload["updatedAt"] = stopped_at
                round_payload["finishedAt"] = stopped_at
                room["status"] = "ready"
                if active_round_id == round_id:
                    room["activeRoundId"] = ""
                room["updatedAt"] = stopped_at
                changed = True
                stopped.append(
                    {
                        "kind": RUN_KIND,
                        "roomId": str(room.get("roomId") or ""),
                        "runId": round_id,
                        "roundId": round_id,
                        "status": "stopped",
                        "_room": dict(room),
                        "_round": dict(round_payload),
                    }
                )
        if changed:
            _store().save(state)

    # Lock order contract: scheduler cancels must not run under _CHAT_ROOM_LOCK.
    for item in stopped:
        session_service.cancel_agent_execution_reservation(str(item.get("roundId") or ""))

    for item in stopped:
        room_payload = item.pop("_room", {})
        round_payload = item.pop("_round", {})
        if isinstance(room_payload, dict) and isinstance(round_payload, dict):
            _persist_chat_room_work_run(
                room_payload,
                round_payload,
                status="stopped",
                summary=str(round_payload.get("summary") or stop_reason),
            )
            _record_room_event(
                "round",
                "chat_room.round.shutdown_stopped",
                room_payload,
                round_payload,
                fields={"reason": trim_lines(stop_reason, max_lines=2)},
                outcome="stopped",
                lifecycle=True,
            )
            _publish_chat_room_detail_snapshot(str(room_payload.get("roomId") or ""))
    return stopped


def _start_challenge_speaker_heartbeat(
    context: Mapping[str, Any],
) -> tuple[threading.Event, threading.Thread | None]:
    """Refresh only the Challenge WorkRun projection while a speaker runs."""

    stop = threading.Event()
    if _positive_int(context.get("challengeDeadlineAtMs")) is None:
        return stop, None
    room_id = str(context.get("roomId") or "").strip()
    round_id = str(context.get("roundId") or "").strip()
    if not room_id or not round_id:
        return stop, None

    def heartbeat() -> None:
        while not stop.wait(_CHALLENGE_ROOM_HEARTBEAT_INTERVAL_SECONDS):
            if _challenge_room_speaker_abort_reason(round_id, context):
                return
            heartbeat_at = utc_now_iso()
            with _CHAT_ROOM_LOCK:
                state = _store().load()
                room = _find_room(state, room_id)
                target_round = _find_round(room, round_id) if isinstance(room, dict) else None
                if (
                    not isinstance(room, dict)
                    or not isinstance(target_round, dict)
                    or _chat_room_round_is_terminal(room, target_round, round_id)
                ):
                    return
                target_round["heartbeatAt"] = heartbeat_at
                target_round["updatedAt"] = heartbeat_at
                room["updatedAt"] = heartbeat_at
                _store().save(state)
                room_snapshot = dict(room)
                round_snapshot = dict(target_round)
            _persist_chat_room_work_run(
                room_snapshot,
                round_snapshot,
                status="running",
                summary="challenge_meeting_speaker_heartbeat",
            )
            _publish_chat_room_detail_snapshot(room_id)

    worker = threading.Thread(
        target=heartbeat,
        name=f"challenge-room-heartbeat:{round_id}",
        daemon=True,
    )
    worker.start()
    return stop, worker


def _speaker_call_timeout_seconds(context: Mapping[str, Any]) -> float:
    """Bounded wall-clock budget for the current speaker call."""

    deadline_at_ms = _positive_int(
        context.get(_CHALLENGE_ROOM_PER_CALL_DEADLINE_CONTEXT_KEY)
    )
    if deadline_at_ms is None:
        return max(1.0, _CHAT_ROOM_SPEAKER_DEFAULT_PER_CALL_BUDGET_MS / 1000.0)
    remaining_seconds = (deadline_at_ms - int(time.time() * 1000)) / 1000.0
    return max(1.0, remaining_seconds)


def _record_speaker_watchdog_timeout_event(
    context: Mapping[str, Any],
    *,
    timeout_seconds: float,
) -> None:
    try:
        record_runtime_scene_event(
            "chat_room",
            "speaker_watchdog",
            "chat_room.speaker_call.watchdog_timeout",
            message=(
                "Speaker call exceeded its per-call budget; the round abandoned "
                "the runner and closed this speaker as failed/stopped."
            ),
            level="warning",
            outcome="failed",
            fields={
                "roomId": str(context.get("roomId") or "").strip(),
                "roundId": str(context.get("roundId") or "").strip(),
                "speakerIndex": context.get("speakerIndex"),
                "timeoutSeconds": max(0, int(timeout_seconds)),
            },
        )
    except Exception:
        return


def _invoke_speaker_runner_with_watchdog(
    runner: AgentRunner,
    participant: dict[str, Any],
    prompt: str,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Run one speaker call behind a hard watchdog timeout.

    Every speaker turn must be bounded: a hung provider call must never keep
    occupying a round indefinitely.  The runner executes on a daemon thread;
    when it does not finish inside the per-call budget the call is abandoned
    (raising ``SpeakerCallWatchdogTimeout`` so the shared exception path
    persists the speaker as failed/stopped) and the round advances.  The
    abandoned thread keeps running detached and its late result is discarded —
    it never touches room state, because the caller alone persists messages.
    """

    timeout_seconds = _speaker_call_timeout_seconds(context)
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["result"] = runner(participant, prompt, context)
        except Exception as exc:  # re-raised on the waiting thread below
            outcome["error"] = exc

    round_id = str(context.get("roundId") or "").strip()
    worker = threading.Thread(
        target=target,
        name=f"chat-room-speaker-call:{round_id}",
        daemon=True,
    )
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        _record_speaker_watchdog_timeout_event(context, timeout_seconds=timeout_seconds)
        raise SpeakerCallWatchdogTimeout(
            f"speaker call exceeded its per-call budget of {timeout_seconds:.0f}s "
            "and was abandoned; the runner thread was left running in the background"
        )
    error = outcome.get("error")
    if error is not None:
        raise error
    return outcome.get("result")


def _run_one_speaker(
    participant: dict[str, Any],
    prompt: str,
    context: dict[str, Any],
    runner: AgentRunner,
) -> dict[str, Any]:
    speaker_started_at = context.get("speakerStartedAtMonotonic") or _perf_counter()
    stage_started_at = _perf_counter()
    supervision_decision = _evaluate_speaker_supervision_policy(participant)
    supervision_policy_ms = _elapsed_ms(stage_started_at)
    agent_directory_service.record_supervision_policy_decision(supervision_decision)
    supervision_payload = _supervision_decision_to_message(supervision_decision)
    if not supervision_decision.allowed:
        timestamp = utc_now_iso()
        return {
            "messageId": _new_id("message", set()),
            "participantId": participant["participantId"],
            "agentId": participant.get("agentId") or "",
            "speakerCode": participant.get("agentCode") or "",
            "sessionId": participant.get("sessionId") or "",
            "speakerTitle": _participant_speaker_label(participant),
            "status": "blocked",
            "content": "",
            "summary": supervision_decision.reason,
            "timestamp": timestamp,
            **_case_message_metadata(context),
            "supervision": supervision_payload,
            "timings": {
                "supervisionPolicyMs": supervision_policy_ms,
                "totalSpeakerMs": _elapsed_ms_between(speaker_started_at),
            },
        }
    try:
        stage_started_at = _perf_counter()
        heartbeat_stop, heartbeat_thread = _start_challenge_speaker_heartbeat(context)
        try:
            result = _invoke_speaker_runner_with_watchdog(runner, participant, prompt, context)
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1.0)
        runner_ms = _elapsed_ms(stage_started_at)
        structured_meeting_message = bool(context.get("_structuredMeetingMessage"))
        message_payload: dict[str, Any] | None = None
        if structured_meeting_message:
            raw_content = _result_full_visible_text(result)
            if not raw_content:
                raw_content = _result_summary(result) or "No visible response."
            ingested_message = ingest_meeting_message_output(raw_content)
            content = str(ingested_message.get("content") or "").strip()
            payload = ingested_message.get("messagePayload")
            message_payload = dict(payload) if isinstance(payload, Mapping) else None
        else:
            content = _result_visible_text(result)
            if not content:
                content = _result_summary(result) or "No visible response."
            content = _strip_redundant_speaker_prefix(content, participant)
        summary = _strip_redundant_speaker_prefix(_result_summary(result), participant)
        if not structured_meeting_message:
            content = _enforce_case_visible_output_boundary(content, context, participant)
        summary = _enforce_case_visible_output_boundary(summary, context, participant, record_event=False)
        result_timings = dict(result.get("timings") or {}) if isinstance(result, dict) else {}
        message_status, result_status = _structured_speaker_result_status(result)
        error_type = _structured_speaker_result_error_type(result) if message_status == "failed" else ""
        timestamp = utc_now_iso()
        return {
            "messageId": _new_id("message", set()),
            "participantId": participant["participantId"],
            "agentId": participant.get("agentId") or "",
            "speakerCode": participant.get("agentCode") or "",
            "sessionId": participant.get("sessionId") or "",
            "speakerTitle": _participant_speaker_label(participant),
            "status": message_status,
            "resultStatus": result_status,
            "content": content,
            "summary": summary,
            **({"messagePayload": message_payload} if message_payload is not None else {}),
            **({"errorType": error_type} if error_type else {}),
            "timestamp": timestamp,
            **_case_message_metadata(context),
            "supervision": supervision_payload,
            "timings": {
                "supervisionPolicyMs": supervision_policy_ms,
                "runnerMs": runner_ms,
                "totalSpeakerMs": _elapsed_ms_between(speaker_started_at),
                **result_timings,
            },
        }
    except Exception as exc:
        total_speaker_ms = _elapsed_ms_between(speaker_started_at)
        normalized_round_id = str(context.get("roundId") or "").strip()
        stop_reason = _chat_room_round_stop_reason(normalized_round_id)
        if not stop_reason:
            stop_reason = _challenge_room_speaker_abort_reason(
                normalized_round_id,
                context,
            )
        if stop_reason:
            timestamp = utc_now_iso()
            return {
                "messageId": _new_id("message", set()),
                "participantId": participant["participantId"],
                "agentId": participant.get("agentId") or "",
                "speakerCode": participant.get("agentCode") or "",
                "sessionId": participant.get("sessionId") or "",
                "speakerTitle": _participant_speaker_label(participant),
                "status": "stopped",
                "content": "",
                "summary": stop_reason,
                "timestamp": timestamp,
                "errorType": type(exc).__name__,
                "error": str(exc),
                **_case_message_metadata(context),
                "timings": {
                    "supervisionPolicyMs": supervision_policy_ms,
                    "totalSpeakerMs": total_speaker_ms,
                },
            }
        timestamp = utc_now_iso()
        return {
            "messageId": _new_id("message", set()),
            "participantId": participant["participantId"],
            "agentId": participant.get("agentId") or "",
            "speakerCode": participant.get("agentCode") or "",
            "sessionId": participant.get("sessionId") or "",
            "speakerTitle": _participant_speaker_label(participant),
            "status": "failed",
            "content": "",
            "summary": f"{type(exc).__name__}: {exc}",
            "errorType": type(exc).__name__,
            "timestamp": timestamp,
            **_case_message_metadata(context),
            "supervision": supervision_payload,
            "timings": {
                "supervisionPolicyMs": supervision_policy_ms,
                "totalSpeakerMs": total_speaker_ms,
            },
        }


def _case_message_metadata(context: dict[str, Any]) -> dict[str, str]:
    case_state = context.get("caseState") if isinstance(context.get("caseState"), dict) else {}
    next_action = str(case_state.get("nextAction") or "").strip()
    visibility = str(case_state.get("discussionVisibility") or "").strip()
    user_facing_mode = str(case_state.get("userFacingMode") or "").strip()
    if next_action == "clarify" or user_facing_mode == "direct_clarification":
        message_kind = "user_clarification"
        audience = "user"
    elif visibility == "collapsed_by_default":
        message_kind = "team_discussion"
        audience = "internal"
    else:
        message_kind = "team_message"
        audience = "user"
    return {
        "messageKind": message_kind,
        "audience": audience,
        "visibility": "collapsed_by_default" if audience == "internal" else "default",
    }


_MATERNAL_CHILD_CLARIFY_PRODUCT_TALK_RE = re.compile(
    r"(智能问诊记录|妇幼数字健康|产品能力|方案映射|平台联动|Demo|demo|演示|展示|母子健康手册|云上妇幼|专科电子病历)"
)


def _enforce_case_visible_output_boundary(
    content: str,
    context: dict[str, Any],
    participant: dict[str, Any],
    *,
    record_event: bool = True,
) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    case_state = context.get("caseState") if isinstance(context.get("caseState"), dict) else {}
    if str(case_state.get("nextAction") or "").strip() != "clarify":
        return text
    if str(case_state.get("intent") or "").strip() != "maternal_child_consultation_demo":
        return text
    sanitized, removed_segment_count = _remove_maternal_child_clarify_product_talk(text)
    if not removed_segment_count:
        return text
    if record_event:
        _record_case_visible_output_boundary_applied(
            context,
            participant,
            before_chars=len(text),
            after_chars=len(sanitized),
            removed_segment_count=removed_segment_count,
        )
    return sanitized or _maternal_child_clarify_fallback(case_state)


def _remove_maternal_child_clarify_product_talk(text: str) -> tuple[str, int]:
    kept_lines: list[str] = []
    removed_segment_count = 0
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if kept_lines and kept_lines[-1] != "":
                kept_lines.append("")
            continue
        kept_sentence_parts: list[str] = []
        removed_in_line = 0
        for sentence in _split_visible_sentences(stripped):
            if _MATERNAL_CHILD_CLARIFY_PRODUCT_TALK_RE.search(sentence):
                removed_in_line += 1
                continue
            kept_sentence_parts.append(sentence)
        if kept_sentence_parts:
            kept_lines.append("".join(kept_sentence_parts).strip())
        elif removed_in_line:
            removed_segment_count += removed_in_line
        removed_segment_count += removed_in_line if kept_sentence_parts else 0
    sanitized = "\n".join(kept_lines).strip()
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized).strip()
    return sanitized, removed_segment_count


def _split_visible_sentences(text: str) -> list[str]:
    parts = re.split(r"([^。！？!?；;]+[。！？!?；;]?)", str(text or ""))
    sentences = [part for part in parts if part and not part.isspace()]
    return sentences or [str(text or "")]


def _maternal_child_clarify_fallback(case_state: dict[str, Any]) -> str:
    missing = [str(item or "").strip() for item in list(case_state.get("missingFacts") or []) if str(item or "").strip()]
    if missing:
        focus = "、".join(missing[:3])
        return f"孩子夜间哭闹需要先补齐几个关键信息：{focus}。如果出现发热不退、精神很差、呼吸异常、抽搐或持续无法安抚，请及时就医。"
    return "孩子夜间哭闹需要先补齐年龄、哭闹持续情况和伴随症状。如果出现明显异常或持续无法安抚，请及时就医。"


def _record_case_visible_output_boundary_applied(
    context: dict[str, Any],
    participant: dict[str, Any],
    *,
    before_chars: int,
    after_chars: int,
    removed_segment_count: int,
) -> None:
    case_state = context.get("caseState") if isinstance(context.get("caseState"), dict) else {}
    try:
        record_runtime_scene_event(
            "chat_room",
            "case_output_boundary",
            "chat_room.case_visible_output_boundary.applied",
            message="Removed product/demo mapping text from a clarify-stage maternal-child consultation response.",
            level="warning",
            outcome="sanitized",
            fields={
                "roomId": str(context.get("roomId") or "").strip(),
                "roundId": str(context.get("roundId") or "").strip(),
                "participantId": str(participant.get("participantId") or "").strip(),
                "agentId": str(participant.get("agentId") or "").strip(),
                "sessionId": str(participant.get("sessionId") or "").strip(),
                "caseIntent": str(case_state.get("intent") or "").strip(),
                "caseNextAction": str(case_state.get("nextAction") or "").strip(),
                "beforeChars": max(0, int(before_chars)),
                "afterChars": max(0, int(after_chars)),
                "removedSegmentCount": max(0, int(removed_segment_count)),
            },
        )
    except Exception:
        return


def _evaluate_speaker_supervision_policy(participant: dict[str, Any]):
    agent_id = str(participant.get("agentId") or "").strip()
    return agent_directory_service.evaluate_supervision_policy(
        agent_directory_service.resolve_supervision_policy_for_agent(agent_id),
        agent_id=agent_id,
        action="chat_room_speaker",
        human_override=False,
        user_initiated=False,
    )


def _supervision_decision_to_message(decision: Any) -> dict[str, Any]:
    return {
        "allowed": bool(getattr(decision, "allowed", True)),
        "reason": str(getattr(decision, "reason", "") or ""),
        "supervisionEnabled": bool(getattr(decision, "supervision_enabled", False)),
        "requiresReview": bool(getattr(decision, "requires_review", False)),
        "reviewMode": str(getattr(decision, "review_mode", "") or ""),
        "evidenceLevel": str(getattr(decision, "evidence_level", "") or ""),
    }


def _run_participant_agent(participant: dict[str, Any], prompt: str, context: dict[str, Any]) -> dict[str, Any]:
    prepare_started_at = _perf_counter()
    timings: dict[str, Any] = {}
    session_id = str(participant.get("sessionId") or "").strip()
    stage_started_at = _perf_counter()
    session_workspace = _participant_workspace(session_id, context.get("roomId"), participant.get("participantId"))
    timings["sessionWorkspaceMs"] = _elapsed_ms(stage_started_at)
    stage_started_at = _perf_counter()
    _sync_agent_directory_project_root()
    timings["agentDirectorySyncMs"] = _elapsed_ms(stage_started_at)
    agent_id = str(participant.get("agentId") or "").strip()
    round_id = str(context.get("roundId") or "").strip()
    participant_id = str(participant.get("participantId") or agent_id or session_id).strip()
    turn_identity = f"chat-room:{round_id}:{participant_id}"
    interrupt_checker = _chat_room_interrupt_checker(round_id, context)
    from core.web.services.team_workflow.research_runtime.meeting_receipt_authority import (
        build_speaker_receipt_context,
    )
    stage_started_at = _perf_counter()
    agent = agent_directory_service.get_agent(agent_id, include_archived=False) if agent_id else None
    if agent_id and not agent:
        historical_agent = agent_directory_service.get_agent(agent_id, include_archived=True)
        status = str((historical_agent or {}).get("status") or "").strip().lower()
        reason = "archived_agent" if status == "archived" else "missing_agent"
        _record_participant_agent_unavailable_event(
            participant,
            context,
            reason=reason,
            agent_status=status,
        )
        raise ChatRoomValidationError(
            text_for(
                get_web_language(),
                zh="群聊成员引用的 Agent 已归档或不可用，不能继续作为发言者运行。",
                en="This room participant references an archived or unavailable Agent and cannot run as a speaker.",
            )
        )
    timings["agentLookupMs"] = _elapsed_ms(stage_started_at)
    agent_context = None
    result: dict[str, Any] | Any
    with session_service.reserve_session_execution_slot(
        agent_id=agent_id,
        run_id=round_id,
        session_id=session_id,
        owner="chat_room_round",
        wait_timeout_seconds=_challenge_room_execution_slot_wait_seconds(context),
    ):
        stop_reason = interrupt_checker()
        if stop_reason:
            raise RuntimeError(stop_reason)
        stage_started_at = _perf_counter()
        agent_context = build_agent_context(agent_id, session_id=session_id, run_id=round_id) if agent_id else None
        timings["agentContextBuildMs"] = _elapsed_ms(stage_started_at)
        if agent_context is not None:
            for timing_key, timing_value in dict(getattr(agent_context, "timings", {}) or {}).items():
                normalized_key = str(timing_key or "").strip()
                if normalized_key:
                    timings[f"agentContext.{normalized_key}"] = timing_value
        stage_started_at = _perf_counter()
        agent_workspace = (
            agent_directory_service._ensure_agent_workspace(str((agent or {}).get("workspacePath") or "")).resolve()
            if agent and str((agent or {}).get("workspacePath") or "").strip()
            else session_workspace
        )
        timings["agentWorkspaceMs"] = _elapsed_ms(stage_started_at)
        stage_started_at = _perf_counter()
        write_decision = evaluate_agent_workspace_write(agent_id, agent_workspace, purpose="chat_room_agent_workspace") if agent_id else None
        timings["workspacePolicyMs"] = _elapsed_ms(stage_started_at)
        workspace = agent_workspace if not write_decision or write_decision.allowed else session_workspace
        stage_started_at = _perf_counter()
        resolved_agent_llm = _resolve_chat_room_agent_llm(agent)
        agent_config = resolved_agent_llm.config
        receipt_context = build_speaker_receipt_context(
            participant,
            context,
            session_id=session_id,
            turn_identity=turn_identity,
            expected_model_route={
                "modelRef": str(getattr(resolved_agent_llm, "model_ref", "") or "").strip(),
                "providerId": str(getattr(resolved_agent_llm, "provider_id", "") or "").strip(),
                "modelId": str(getattr(resolved_agent_llm, "model", "") or "").strip(),
            },
        )
        timings["agentConfigMs"] = _elapsed_ms(stage_started_at)
        stage_started_at = _perf_counter()
        ledger_events = load_conversation_events(PROJECT_ROOT, session_id) if session_id else []
        history_assembly = session_service.assemble_conversation_context(
            [],
            session_id=session_id,
            current_turn_id=turn_identity,
            ledger_events=ledger_events or None,
            recent_message_limit=None,
        )
        canonical_chat_history = list(history_assembly.history_messages or [])
        timings["ledgerHistoryMs"] = _elapsed_ms(stage_started_at)
        with active_agent_runtime(
            agent_id,
            session_id=session_id,
            turn_id=turn_identity,
            room_id=str(context.get("roomId") or "").strip(),
            round_id=round_id,
        ), session_service._session_tool_workspace_override(workspace):
            stage_started_at = _perf_counter()
            agent_runtime = session_service.create_chat_agent(workspace_path=workspace, config=agent_config)
            timings["agentCreateMs"] = _elapsed_ms(stage_started_at)
            _record_room_event(
                "round",
                "chat_room.agent_llm.resolved",
                {"roomId": str(context.get("roomId") or "").strip()},
                fields={
                    "roundId": round_id,
                    "participantId": str(participant.get("participantId") or "").strip(),
                    "sessionId": session_id,
                    "agentCreateMs": timings["agentCreateMs"],
                    "agentConfigMs": timings["agentConfigMs"],
                    **resolved_agent_llm.log_fields(),
                },
            )
            stage_started_at = _perf_counter()
            prepare_agent_turn(
                agent_runtime,
                turn_identity=turn_identity,
                interrupt_checker=interrupt_checker,
                chat_history=canonical_chat_history,
                runtime_context=agent_context.context_block if agent_context is not None else "",
                static_runtime_context=(
                    getattr(agent_context, "static_context_block", "") if agent_context is not None else ""
                ),
                dynamic_runtime_context=(
                    getattr(agent_context, "dynamic_context_block", "") if agent_context is not None else ""
                ),
            )
            timings["agentSeedMs"] = _elapsed_ms(stage_started_at)
            timings["totalPrepareMs"] = _elapsed_ms(prepare_started_at)
            stage_started_at = _perf_counter()
            from core.llm.client import llm_status_context, model_invocation_receipt_context_scope

            meeting_outcomes: list[Any] = []
            llm_response_callback_id = ""
            if receipt_context is not None:
                # Formal meeting turns bypass the session UI stream. Capture
                # canonical outcomes so conversation content can still be
                # committed while receipts go directly to the Challenge Cup
                # registry instead of becoming conversation state.
                from core.infrastructure.event_bus import EventNames, get_event_bus

                def _capture_meeting_llm_outcome(event: Any) -> None:
                    data = getattr(event, "data", None)
                    outcome = data.get("turn_outcome") if isinstance(data, dict) else None
                    identity = getattr(outcome, "identity", None)
                    if (
                        outcome is not None
                        and str(getattr(identity, "session_id", "") or "").strip() == session_id
                        and str(getattr(identity, "turn_id", "") or "").strip() == turn_identity
                    ):
                        meeting_outcomes.append(outcome)

                llm_response_callback_id = get_event_bus().subscribe(
                    EventNames.LLM_RESPONSE,
                    _capture_meeting_llm_outcome,
                    callback_id=f"chat_room_meeting_{session_id}_{round_id}_{participant_id}",
                )
            try:
                # The status context is the only meeting-side source for the
                # invocation session/turn identity; without it the LLM scope
                # degrades to a synthetic namespace whose outcomes can never
                # match the speaker Child Session journal.
                with model_invocation_receipt_context_scope(receipt_context), llm_status_context(
                    session_id=session_id,
                    turn_id=turn_identity,
                ):
                    result = run_existing_agent_single_turn(
                        agent_runtime,
                        initial_prompt=prompt,
                        disable_tools=True,
                        turn_identity=turn_identity,
                        interrupt_checker=interrupt_checker,
                        chat_history=canonical_chat_history,
                    )
            finally:
                if llm_response_callback_id:
                    from core.infrastructure.event_bus import get_event_bus as _get_event_bus

                    _get_event_bus().unsubscribe_by_id(llm_response_callback_id)
            timings["llmElapsedMs"] = _elapsed_ms(stage_started_at)
            if receipt_context is not None:
                from core.chat.conversation_ledger import append_conversation_turn_outcome
                from core.web.services.team_workflow.research_runtime.meeting_receipt_authority import (
                    register_speaker_receipts,
                )

                for outcome in meeting_outcomes:
                    append_conversation_turn_outcome(
                        PROJECT_ROOT,
                        session_id,
                        turn_identity,
                        outcome,
                    )
                meeting_receipts = [
                    dict(receipt)
                    for outcome in meeting_outcomes
                    if isinstance(
                        receipt := getattr(outcome, "model_invocation_receipt", None),
                        Mapping,
                    )
                ]
                register_speaker_receipts(
                    project_root=PROJECT_ROOT,
                    team_id=str(context.get("teamId") or "").strip(),
                    question_id=str(context.get("questionId") or "").strip().upper(),
                    workflow_run_id=str(receipt_context.get("receiptRunId") or "").strip(),
                    session_id=session_id,
                    turn_identity=turn_identity,
                    receipts=meeting_receipts,
                )
    if agent_context is not None and agent_context.agent_id:
        stage_started_at = _perf_counter()
        record_agent_turn_result(
            agent_context.agent_id,
            session_id,
            result if isinstance(result, dict) else {},
            run_id=round_id,
        )
        timings["agentTurnResultRecordMs"] = _elapsed_ms(stage_started_at)
    if isinstance(result, dict):
        result = dict(result)
        result["timings"] = {**dict(result.get("timings") or {}), **timings}
    return result


def _record_participant_agent_unavailable_event(
    participant: dict[str, Any],
    context: dict[str, Any],
    *,
    reason: str,
    agent_status: str = "",
) -> None:
    normalized_reason = str(reason or "").strip() or "missing_agent"
    event_code = (
        "chat_room.participant_agent_archived"
        if normalized_reason == "archived_agent"
        else "chat_room.participant_agent_missing"
    )
    try:
        record_runtime_scene_event(
            "chat_room",
            "participant_agent",
            event_code,
            message="Chat room participant Agent is unavailable at execution time.",
            level="warning",
            outcome="blocked",
            fields={
                "roomId": str(context.get("roomId") or "").strip(),
                "roundId": str(context.get("roundId") or "").strip(),
                "participantId": str(participant.get("participantId") or "").strip(),
                "agentId": str(participant.get("agentId") or "").strip(),
                "sessionId": str(participant.get("sessionId") or "").strip(),
                "reason": normalized_reason,
                "agentStatus": str(agent_status or "").strip(),
                **_participant_team_event_fields(participant),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _build_participant_prompt(
    *,
    room: dict[str, Any],
    round_payload: dict[str, Any],
    participant: dict[str, Any],
    prior_messages: list[dict[str, Any]],
) -> str:
    recent_session_lines = _format_recent_session_messages(participant.get("recentMessages") or [])
    purpose = _normalize_purpose(round_payload.get("purpose") or room.get("purpose") or DEFAULT_PURPOSE)
    case_state = round_payload.get("caseState") if isinstance(round_payload.get("caseState"), dict) else {}
    case_state_lines = format_case_state_prompt(case_state)
    case_guidance_lines = case_prompt_lines(case_state)
    effective_purpose = _effective_prompt_purpose(purpose, case_state)
    purpose_lines = _purpose_prompt_lines(effective_purpose)
    role_view = _participant_role_view(participant)
    team_context_lines = _format_participant_team_context(participant)
    structured_meeting_message = _uses_structured_meeting_message(
        room, round_payload
    )
    prior_lines = _format_prior_room_messages(
        prior_messages,
        preserve_meeting_semantics=_is_challenge_meeting_round(round_payload),
    )
    challenge_short_answer_lines = (
        [
            "挑战杯会议短答合同：只给 1 个新增判断和 1 个依据，正文不超过 180 个中文字符。",
            "不要复述题目、其他 Agent 发言或自己的角色；候选生成时只输出一条 CANDIDATE 标记。",
        ]
        if isinstance(round_payload.get("config"), Mapping)
        and _positive_int(
            (round_payload.get("config") or {}).get("challengeDeadlineAtMs")
        )
        is not None
        and str((round_payload.get("config") or {}).get("meetingType") or "").strip()
        == "hypothesis_candidate_generation"
        and not structured_meeting_message
        else []
    )
    response_contract_lines = (
        [meeting_message_output_contract()]
        if structured_meeting_message
        else [
            "请给出一段紧凑、可读、只读的群聊发言。不要修改文件、不要提交、不要启动进化或部署。",
            "如果你没有新信息，请明确说明你的确认、保留意见或下一步建议。",
        ]
    )
    return "\n".join(
        [
            "你正在参加 Vibelution 的只读 Agent 群聊。",
            f"群聊: {room.get('title') or room.get('roomId')}",
            f"当前议题: {round_payload.get('topic') or ''}",
            f"调度模式: {round_payload.get('mode') or DEFAULT_MODE}",
            f"对话目的: {purpose}",
            f"本轮推进模式: {effective_purpose}",
            f"你的发言视角: {role_view}",
            f"你的界面代号: {participant.get('agentCode') or ''}",
            f"来源会话: {participant.get('sessionId') or ''}",
            "发言时直接代入这个角色，不要在正文开头写 Agent 编号、姓名、职位、标题或“某某 Agent：”；这些会由界面显示。",
            "不要写“作为/我是/我的身份是…”来介绍自己，除非用户明确要求自我介绍。",
            "",
            "你的团队岗位上下文:",
            team_context_lines or "- 当前群聊未绑定团队岗位；按会话 Agent 的可用上下文发言。",
            "",
            "你的会话近况:",
            recent_session_lines or "- 暂无可用会话消息。",
            "",
            "本轮已经出现的群聊发言:",
            prior_lines or "- 你是本轮第一位发言者。",
            "",
            "本轮用户需求 Case 状态:",
            case_state_lines or "- 当前群聊未启用 case 编排；按对话目的和岗位职责发言。",
            "",
            "Case 推进规则:",
            *(case_guidance_lines or ["- 围绕用户当前目标推进，不要机械轮流复述岗位职责。"]),
            "",
            "本轮发言风格:",
            *purpose_lines,
            *challenge_short_answer_lines,
            "",
            *response_contract_lines,
        ]
    )


def _effective_prompt_purpose(purpose: str, case_state: dict[str, Any]) -> str:
    if str(case_state.get("nextAction") or "").strip() == "clarify":
        if str(case_state.get("intent") or "").strip() in CONSULTATION_INTENTS:
            return "medical_clarification"
        return "chat"
    return purpose


def _purpose_prompt_lines(purpose: str) -> list[str]:
    normalized = _normalize_purpose(purpose)
    if normalized == "chat":
        return [
            "- 像真实群聊一样回应当前用户话题，优先接住上一位发言者，不要写成任务报告。",
            "- 用 1-3 句自然短句表达；除非用户明确要求，不要使用标题、列表、表格或会议纪要格式。",
            "- 如果只是问候或轻量寒暄，先自然回应，不要主动扩展成科研方向、组织调整或能力审查。",
            "- 如果会话近况与当前话题无关，只保留一句必要背景，不要把旧任务上下文搬进来。",
        ]
    if normalized == "meeting":
        return [
            "- 按会议协作发言：聚焦议题、决策、风险和下一步行动。",
            "- 可以使用简短项目符号，但每条都要服务于结论、责任或待确认事项。",
            "- 明确指出需要谁确认、后续要做什么，避免闲聊式扩散。",
        ]
    if normalized == "medical_triage":
        return [
            "- 按协同问诊会诊模式发言：目标是分诊与就医准备，不替代医生面诊、检查、诊断或治疗。",
            "- 先识别急症红旗信号；如出现胸痛、呼吸困难、意识障碍、大出血、严重过敏、疑似卒中等风险，优先建议立即就医或急救。",
            "- 信息不足时只提出最少必要追问，优先补齐年龄、性别、主诉、持续时间、伴随症状、既往史、用药和过敏史。",
            "- 严禁给出确定诊断、处方、剂量、停药/换药指令或保证性结论；只能给风险等级、可能方向、建议科室、观察重点和下一步建议。",
            "- 如果你不是问诊主持或结果整理岗位，不要直接生成最终答复；只给本岗位的简短结论、风险提示或需要补充的信息。",
            "- 最终面向用户的合并结果应包含：风险等级、可能方向、建议科室、需补充/观察信息、立即就医条件、下一步建议和免责声明。",
        ]
    if purpose == "medical_clarification":
        return [
            "- 像真实问诊接话一样自然回应，先接住担忧，再问少量真正影响判断的问题。",
            "- 用短段落表达，最多 2-3 个问题；不要写标题、表格、编号问卷或信息采集清单。",
            "- 问题要围绕当前主诉选择，例如夜间哭闹优先问年龄、哭闹持续/能否安抚、是否发热或呕吐腹泻等伴随异常；不要一次性铺开所有病史字段。",
            "- 提醒急症边界即可，不做诊断、处方、剂量或保证性判断。",
        ]
    if normalized == "research_coordination":
        return [
            "- 按科研组织协作发言：先回应当前议题，再说明本岗位能推进的研究、证据或组织动作。",
            "- 区分建议、事实和待确认事项；需要 CEO 或其他角色决策时明确点出。",
            "- 避免把发言写成泛泛聊天，优先服务科研任务拆解、能力配置、证据流转和下一步协调。",
        ]
    if normalized == "self_evolution":
        return [
            "- 按自进化系统团队职责发言：executor 说执行进展，reviewer 说质量风险，observer 只报告旁路观察信号。",
            "- 聚焦本轮演化目标、验证证据、阻塞点和下一步，不要把系统团队说成普通闲聊群。",
            "- 不要擅自承诺已部署、已提交或已验证；只报告上下文中真实可见的状态。",
        ]
    if normalized == "supervised_evolution":
        return [
            "- 按监督进化流程发言：baseline/candidate 提方案，reviewer 评审，auditor 查证据，judge 给裁决倾向。",
            "- 明确区分候选改动、验证结果、审计风险和裁决依据。",
            "- 不要越过当前角色直接替其他角色下最终结论，除非上下文要求合并总结。",
        ]
    return [
        "- 按讨论模式发言：回应前文观点，给出一个清晰立场、补充角度、权衡或反对意见。",
        "- 可以提出建议或分歧，但保持紧凑，不要写成长篇报告。",
        "- 让发言接在上一位之后，避免孤立复述自己的会话近况。",
    ]


def _strip_redundant_speaker_prefix(text: str, participant: dict[str, Any]) -> str:
    content = str(text or "").strip()
    if not content:
        return ""
    labels = [
        _participant_speaker_label(participant),
        _participant_role_view(participant),
        str(participant.get("title") or "").strip(),
        str(participant.get("agentCode") or "").strip(),
    ]
    for label in labels:
        if not label:
            continue
        content = re.sub(rf"^\s*(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*[:：]\s*", "", content, count=1).strip()
    code = str(participant.get("agentCode") or "").strip()
    if code:
        content = re.sub(
            rf"^\s*(?:\*\*)?{re.escape(code)}\s*[·\-]\s*[^\n:：]{{1,60}}(?:\*\*)?\s*[:：]\s*",
            "",
            content,
            count=1,
        ).strip()
    return content


def _format_recent_session_messages(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in messages[-6:]:
        role = str(item.get("role") or "").strip() or "message"
        content = trim_lines(str(item.get("content") or ""), max_lines=2)
        if content:
            lines.append(f"- {role}: {content}")
    return "\n".join(lines)


def _format_prior_room_messages(
    messages: list[dict[str, Any]],
    *,
    preserve_meeting_semantics: bool = False,
) -> str:
    lines: list[str] = []
    for item in messages[-8:]:
        speaker = str(item.get("speakerTitle") or item.get("participantId") or "speaker").strip()
        raw_content = str(item.get("content") or item.get("summary") or "")
        content = (
            raw_content.strip()
            if preserve_meeting_semantics
            else trim_lines(raw_content, max_lines=3)
        )
        if content:
            lines.append(f"- {speaker}: {content}")
    return "\n".join(lines)


def _participant_speaker_label(participant: dict[str, Any]) -> str:
    code = str(participant.get("agentCode") or "").strip()
    if code:
        return code
    title = str(participant.get("title") or "").strip()
    if title:
        return title
    return str(participant.get("participantId") or "").strip()


def _participant_role_view(participant: dict[str, Any]) -> str:
    team_purpose = str(participant.get("teamMemberPurpose") or "").strip()
    team_role = str(participant.get("teamRole") or "").strip()
    if team_purpose and team_role and team_purpose != team_role:
        return f"{team_role} / {team_purpose}"
    if team_purpose or team_role:
        return team_purpose or team_role
    title = str(participant.get("title") or "").strip()
    if title:
        title = re.sub(r"\s*Agent\s*$", "", title, flags=re.IGNORECASE).strip()
    return title or str(participant.get("participantId") or "").strip() or "群聊成员"


def _format_participant_team_context(participant: dict[str, Any]) -> str:
    team_name = str(participant.get("teamName") or "").strip()
    team_id = str(participant.get("teamId") or "").strip()
    team_purpose = trim_lines(participant.get("teamPurpose") or "", max_lines=2).strip()
    team_role = trim_lines(participant.get("teamRole") or "", max_lines=1).strip()
    member_purpose = trim_lines(participant.get("teamMemberPurpose") or "", max_lines=2).strip()
    responsibilities = [
        trim_lines(str(item or ""), max_lines=1).strip()
        for item in list(participant.get("teamResponsibilities") or [])[:5]
        if trim_lines(str(item or ""), max_lines=1).strip()
    ]
    lines: list[str] = []
    if team_name or team_id:
        lines.append(f"- 所属团队: {team_name or team_id}")
    if team_purpose:
        lines.append(f"- 团队目标: {team_purpose}")
    if team_role:
        lines.append(f"- 团队岗位: {team_role}")
    if member_purpose:
        lines.append(f"- 岗位职责: {member_purpose}")
    if responsibilities:
        lines.append(f"- 职责清单: {'；'.join(responsibilities)}")
    if lines:
        lines.append("- 你是在团队群聊中承担这个岗位的 Agent，不是普通直连会话 Agent。")
    return "\n".join(lines)


def _participant_team_event_fields(participant: dict[str, Any]) -> dict[str, Any]:
    team_id = str(participant.get("teamId") or "").strip()
    if not team_id:
        return {}
    responsibilities = [
        trim_lines(str(item or ""), max_lines=1).strip()
        for item in list(participant.get("teamResponsibilities") or [])[:5]
        if trim_lines(str(item or ""), max_lines=1).strip()
    ]
    return {
        "runContext": "team_room",
        "teamId": team_id,
        "teamName": str(participant.get("teamName") or "").strip(),
        "teamRole": str(participant.get("teamRole") or "").strip(),
        "teamMemberPurpose": str(participant.get("teamMemberPurpose") or "").strip(),
        "teamResponsibilitiesCount": len(responsibilities),
    }


def _result_visible_text(result: Any) -> str:
    if isinstance(result, dict):
        raw = result.get("raw_output") or result.get("content") or result.get("response") or ""
    else:
        raw = str(result or "")
    return sanitize_assistant_visible_text(trim_lines(str(raw or ""), max_lines=20)).strip()


def _result_full_visible_text(result: Any) -> str:
    """Return the complete visible output for structured meeting ingestion."""

    if isinstance(result, dict):
        raw = result.get("raw_output") or result.get("content") or result.get("response") or ""
    else:
        raw = str(result or "")
    return sanitize_assistant_visible_text(str(raw or "")).strip()


def _result_summary(result: Any) -> str:
    if isinstance(result, dict):
        return trim_lines(str(result.get("summary") or result.get("message") or ""), max_lines=4)
    return ""


def _structured_speaker_result_status(result: Any) -> tuple[str, str]:
    if not isinstance(result, dict):
        return "completed", ""
    result_status = str(result.get("status") or "").strip().lower()
    if not result_status or result_status in {"completed", "success", "succeeded", "done", "ready"}:
        return "completed", result_status
    if result_status in {"failed", "failed_provider", "failed_runtime", "error"}:
        return "failed", result_status
    if result_status == "blocked":
        return "blocked", result_status
    if result_status in {"stopped", "stopped_by_user", "cancelled"}:
        return "stopped", result_status
    if result_status in {"partial", "degraded", "needs_continue", "paused_limit"}:
        return "partial", result_status
    return "failed", result_status


def _structured_speaker_result_error_type(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    llm_failure = result.get("llm_failure") if isinstance(result.get("llm_failure"), dict) else {}
    result_status = str(result.get("status") or "").strip().lower()
    known_failure_statuses = {"failed", "failed_provider", "failed_runtime", "error"}
    return trim_lines(
        str(
            result.get("errorType")
            or result.get("error_type")
            or llm_failure.get("category")
            or ("AgentTurnFailed" if result_status in known_failure_statuses else "UnexpectedResultStatus")
        ),
        max_lines=1,
    ).strip()


def _speaker_event_code(status: Any) -> str:
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"completed", "failed", "blocked", "stopped", "partial"}:
        normalized_status = "failed"
    return f"chat_room.speaker.{normalized_status}"


def _round_summary(messages: list[dict[str, Any]], *, lang: str) -> str:
    total = len(messages)
    completed = sum(1 for item in messages if item.get("status") == "completed")
    failed = sum(1 for item in messages if item.get("status") == "failed")
    blocked = sum(1 for item in messages if item.get("status") == "blocked")
    stopped = sum(1 for item in messages if item.get("status") == "stopped")
    partial = sum(1 for item in messages if item.get("status") == "partial")
    unsuccessful = total - completed
    return text_for(
        lang,
        zh=(
            f"本轮群聊完成：{completed}/{total} 位参与者成功发言，{unsuccessful} 位未成功"
            f"（失败 {failed}、受阻 {blocked}、停止 {stopped}、{partial} 位部分完成）。"
        ),
        en=(
            f"Chat room round finished: {completed}/{total} participants responded successfully; "
            f"{unsuccessful} did not fully succeed "
            f"({failed} failed, {blocked} blocked, {stopped} stopped, {partial} partially completed)."
        ),
    )


def _sync_group_context_events(room: dict[str, Any], round_payload: dict[str, Any]) -> None:
    _sync_agent_directory_project_root()
    participants = [
        item for item in list(room.get("participants") or [])
        if isinstance(item, dict) and str(item.get("agentId") or "").strip()
    ]
    messages = [
        item for item in list(round_payload.get("messages") or [])
        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "completed"
    ]
    if not participants or not messages:
        return
    room_id = str(room.get("roomId") or "").strip()
    round_id = str(round_payload.get("roundId") or "").strip()
    topic = str(round_payload.get("topic") or "").strip()
    summary = str(round_payload.get("summary") or "").strip()
    message_by_participant = {
        str(message.get("participantId") or "").strip(): message
        for message in messages
    }
    peer_highlights_by_participant: dict[str, list[str]] = {}
    for participant in participants:
        participant_id = str(participant.get("participantId") or "").strip()
        highlights: list[str] = []
        for message in messages:
            if str(message.get("participantId") or "").strip() == participant_id:
                continue
            speaker = str(message.get("speakerTitle") or message.get("participantId") or "").strip()
            content = trim_lines(str(message.get("content") or message.get("summary") or ""), max_lines=2)
            if content:
                highlights.append(f"{speaker}: {content}" if speaker else content)
        peer_highlights_by_participant[participant_id] = highlights[:8]

    synced_count = 0
    for participant in participants:
        agent_id = str(participant.get("agentId") or "").strip()
        participant_id = str(participant.get("participantId") or "").strip()
        own_message = message_by_participant.get(participant_id) or {}
        try:
            write_group_context_event(
                agent_id,
                {
                    "sourceRoomId": room_id,
                    "sourceRoundId": round_id,
                    "targetSessionId": participant.get("sessionId") or participant.get("directSessionId") or "",
                    "topic": topic,
                    "summary": summary,
                    "ownMessage": own_message.get("content") or own_message.get("summary") or "",
                    "peerHighlights": peer_highlights_by_participant.get(participant_id) or [],
                    "promptEligible": True,
                    "createdAt": utc_now_iso(),
                },
            )
            synced_count += 1
        except Exception as exc:
            _record_room_event(
                "group_context",
                "group_context.sync_failed",
                room,
                round_payload,
                fields={
                    "agentId": agent_id,
                    "participantId": participant_id,
                    "errorType": type(exc).__name__,
                    "errorPreview": trim_lines(str(exc), max_lines=2),
                },
                outcome="failed",
                level="warning",
                lifecycle=True,
            )
    _record_room_event(
        "group_context",
        "group_context.synced",
        room,
        round_payload,
        fields={"syncedCount": synced_count, "participantCount": len(participants)},
        outcome="written",
        lifecycle=True,
    )


def _sync_group_round_to_participant_sessions(room: dict[str, Any], round_payload: dict[str, Any]) -> None:
    participants = [
        item for item in list(room.get("participants") or [])
        if isinstance(item, dict) and str(item.get("sessionId") or item.get("directSessionId") or "").strip()
    ]
    messages = [
        item for item in list(round_payload.get("messages") or [])
        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "completed"
    ]
    room_id = str(room.get("roomId") or round_payload.get("roomId") or "").strip()
    round_id = str(round_payload.get("roundId") or "").strip()
    if not participants or not messages or not room_id or not round_id:
        return

    timestamp = (
        str(round_payload.get("finishedAt") or round_payload.get("updatedAt") or "").strip()
        or utc_now_iso()
    )
    synced_count = 0
    skipped_count = 0
    missing_count = 0
    materialized_count = 0
    materialized_snapshots: list[dict[str, Any]] = []
    with session_service._CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            return
        for participant in participants:
            session_id = str(participant.get("sessionId") or participant.get("directSessionId") or "").strip()
            if not session_id:
                continue
            conversation = session_service._find_conversation_entry(payload, session_id)
            if conversation is None:
                if session_service._materialize_agent_directory_conversation_locked(
                    payload,
                    session_id,
                    source="chat_room_round_sync",
                ):
                    materialized_count += 1
                    conversation = session_service._find_conversation_entry(payload, session_id)
                    if isinstance(conversation, dict):
                        materialized_snapshots.append(dict(conversation))
                if conversation is None:
                    missing_count += 1
                    continue
            session_messages = conversation_visible_messages_from_events(
                load_conversation_events(PROJECT_ROOT, session_id)
            )
            if _has_group_round_session_sync(session_messages, room_id=room_id, round_id=round_id):
                skipped_count += 1
                continue
            transcript_message = _build_group_round_session_message(
                room,
                round_payload,
                participant,
                messages,
                timestamp=timestamp,
            )
            append_conversation_event(
                PROJECT_ROOT,
                session_id,
                f"chat-room-{round_id or uuid.uuid4().hex}",
                EVENT_ASSISTANT_MESSAGE,
                status="completed",
                payload={
                    "content": str(transcript_message.get("content") or ""),
                    "metadata": transcript_message.get("metadata") if isinstance(transcript_message.get("metadata"), dict) else {},
                },
                source="chat_room_round_sync",
                timestamp=timestamp,
            )
            conversation.pop("messages", None)
            conversation["updated_at"] = timestamp
            synced_count += 1
        if synced_count:
            payload["updated_at"] = timestamp
            save_chat_state(PROJECT_ROOT, payload)

    if materialized_snapshots:
        from core.web.services.session import directory_bridge

        directory_bridge.sync_conversation_records(materialized_snapshots, wait=False)

    _record_room_event(
        "group_context",
        "group_context.session_transcript_synced",
        room,
        round_payload,
        fields={
            "syncedSessionCount": synced_count,
            "skippedSessionCount": skipped_count,
            "missingSessionCount": missing_count,
            "materializedSessionCount": materialized_count,
            "participantCount": len(participants),
        },
        outcome="written" if synced_count else "skipped",
        lifecycle=True,
    )


def _sync_stopped_round_to_sessions_if_needed(room: dict[str, Any], round_payload: dict[str, Any]) -> None:
    """Stop/fail closures must still sync completed speaker messages.

    The happy path syncs at round completion; without this the transcript and
    group-context events for completed messages never reach participant
    sessions when the round is stopped or fails midway. Both sync helpers are
    idempotent per room+round, so double closure paths stay safe.
    """

    has_completed = any(
        isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "completed"
        for item in list(round_payload.get("messages") or [])
    )
    if not has_completed:
        return
    _sync_group_context_events(room, round_payload)
    _sync_group_round_to_participant_sessions(room, round_payload)


def _remove_group_room_transcripts_from_participant_sessions(
    room: dict[str, Any],
    room_id: str,
) -> dict[str, int]:
    normalized_room_id = str(room_id or room.get("roomId") or "").strip()
    if not normalized_room_id:
        return {"changedSessionCount": 0, "removedMessageCount": 0}
    changed_session_count = 0
    removed_message_count = 0
    with session_service._CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            return {"changedSessionCount": 0, "removedMessageCount": 0}
        for conversation in conversations:
            if not isinstance(conversation, dict):
                continue
            session_id = str(conversation.get("conversation_id") or conversation.get("id") or "").strip()
            if not session_id:
                continue
            events = load_conversation_events(PROJECT_ROOT, session_id)
            kept_events = [
                event
                for event in events
                if not _is_group_room_transcript_event(event, normalized_room_id)
            ]
            removed_count = len(events) - len(kept_events)
            if removed_count <= 0:
                continue
            rewrite_conversation_events(PROJECT_ROOT, session_id, kept_events)
            conversation.pop("messages", None)
            conversation["updated_at"] = utc_now_iso()
            changed_session_count += 1
            removed_message_count += removed_count
        if removed_message_count:
            payload["updated_at"] = utc_now_iso()
            save_chat_state(PROJECT_ROOT, payload)
    return {
        "changedSessionCount": changed_session_count,
        "removedMessageCount": removed_message_count,
    }


def _is_group_room_transcript_message(message: dict[str, Any], room_id: str) -> bool:
    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        return (
            str(metadata.get("kind") or "").strip() == "group_room_transcript"
            and str(metadata.get("sourceRoomId") or "").strip() == room_id
        )
    content = str(message.get("content") or "")
    return "[群聊同步]" in content and room_id in content


def _is_group_room_transcript_event(event: Any, room_id: str) -> bool:
    if event is None:
        return False
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict):
        return False
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        return (
            str(metadata.get("kind") or "").strip() == "group_room_transcript"
            and str(metadata.get("sourceRoomId") or "").strip() == room_id
        )
    content = str(payload.get("content") or "")
    return "[群聊同步]" in content and room_id in content


def _disable_group_context_for_room(room_id: str, *, agent_ids: list[str] | None = None) -> dict[str, int]:
    try:
        result = agent_directory_service.disable_group_context_events_for_room(
            room_id,
            agent_ids=agent_ids,
            reason="chat_room_reset",
        )
    except Exception as exc:
        _record_room_event(
            "group_context",
            "group_context.disable_for_room_failed",
            {"roomId": room_id, "title": ""},
            fields={
                "errorType": type(exc).__name__,
                "errorPreview": trim_lines(str(exc), max_lines=2),
            },
            outcome="failed",
            level="warning",
            lifecycle=True,
        )
        return {"changedAgentCount": 0, "disabledEventCount": 0}
    return {
        "changedAgentCount": int(result.get("changedAgentCount") or 0),
        "disabledEventCount": int(result.get("disabledEventCount") or 0),
    }


def _has_group_round_session_sync(messages: list[dict[str, Any]], *, room_id: str, round_id: str) -> bool:
    marker = f"sourceRoundId: {round_id}"
    for item in list(messages or []):
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            if (
                str(metadata.get("kind") or "").strip() == "group_room_transcript"
                and str(metadata.get("sourceRoomId") or "").strip() == room_id
                and str(metadata.get("sourceRoundId") or "").strip() == round_id
            ):
                return True
        content = str(item.get("content") or "")
        if room_id in content and marker in content:
            return True
    return False


def _build_group_round_session_message(
    room: dict[str, Any],
    round_payload: dict[str, Any],
    participant: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    timestamp: str,
) -> dict[str, Any]:
    room_id = str(room.get("roomId") or round_payload.get("roomId") or "").strip()
    round_id = str(round_payload.get("roundId") or "").strip()
    participant_id = str(participant.get("participantId") or "").strip()
    own_lines: list[str] = []
    peer_lines: list[str] = []
    for message in messages:
        speaker = str(message.get("speakerTitle") or message.get("participantId") or "").strip()
        content = trim_lines(str(message.get("content") or message.get("summary") or ""), max_lines=4)
        if not content:
            continue
        line = f"- {speaker}: {content}" if speaker else f"- {content}"
        if str(message.get("participantId") or "").strip() == participant_id:
            own_lines.append(line)
        else:
            peer_lines.append(line)
    content_lines = [
        "[群聊同步]",
        f"群聊: {room.get('title') or room_id}",
        f"议题: {round_payload.get('topic') or ''}",
        f"摘要: {round_payload.get('summary') or ''}",
        "",
        "你的发言:",
        *(own_lines or ["- 本轮你没有发言。"]),
        "",
        "其他 Agent 发言:",
        *(peer_lines or ["- 本轮暂无其他 Agent 发言。"]),
    ]
    return {
        "role": "assistant",
        "content": "\n".join(str(line) for line in content_lines if str(line).strip() or line == ""),
        "timestamp": str(timestamp or utc_now_iso()).strip(),
        "metadata": {
            "kind": "group_room_transcript",
            "sourceRoomId": room_id,
            "sourceRoundId": round_id,
            "sourceRoomTitle": str(room.get("title") or "").strip(),
            "targetSessionId": str(participant.get("sessionId") or participant.get("directSessionId") or "").strip(),
            "targetAgentId": str(participant.get("agentId") or "").strip(),
            "participantId": participant_id,
        },
    }


def _resolve_participants(session_ids: list[str] | None) -> list[dict[str, Any]]:
    summaries = session_service.list_sessions(include_hidden_internal=True)
    by_id = {str(item.get("id") or "").strip(): item for item in summaries}
    requested = [str(item or "").strip() for item in list(session_ids or []) if str(item or "").strip()]
    if session_ids is not None:
        _hydrate_requested_session_details(by_id, requested)
        return [_participant_from_session(by_id[session_id]) for session_id in _dedupe_requested_session_ids(requested, by_id)]
    if not requested:
        requested = [str(item.get("id") or "").strip() for item in summaries if str(item.get("id") or "").strip()]
    return [_participant_from_session(by_id[session_id]) for session_id in _dedupe_requested_session_ids(requested, by_id)]


def _hydrate_requested_session_details(by_id: dict[str, dict[str, Any]], requested: list[str]) -> None:
    for session_id in requested:
        if not session_id or session_id in by_id:
            continue
        detail = session_service.get_session_detail(session_id)
        if isinstance(detail, dict) and str(detail.get("id") or "").strip() == session_id:
            by_id[session_id] = detail


def _dedupe_requested_session_ids(requested: list[str], by_id: dict[str, dict[str, Any]]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for session_id in requested:
        if session_id in seen:
            continue
        seen.add(session_id)
        if session_id not in by_id:
            raise ChatRoomValidationError(f"Unknown chat session: {session_id}")
        normalized.append(session_id)
    return normalized


def _dedupe_chat_room_participants(participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for participant in list(participants or []):
        if not isinstance(participant, dict):
            continue
        keys = _chat_room_participant_identity_keys(participant)
        if keys and any(key in seen for key in keys):
            continue
        deduped.append(participant)
        seen.update(keys)
    return deduped


def _filter_round_participants_by_agent_ids(
    participants: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply a persisted meeting roster without mutating room membership."""

    frozen_agent_ids = _frozen_participant_agent_ids(config)
    if frozen_agent_ids is None:
        return participants
    participants_by_agent_id: dict[str, list[dict[str, Any]]] = {
        agent_id: [] for agent_id in frozen_agent_ids
    }
    for participant in participants:
        agent_id = str(participant.get("agentId") or "").strip()
        if agent_id in participants_by_agent_id:
            participants_by_agent_id[agent_id].append(participant)
    missing = [
        agent_id for agent_id in frozen_agent_ids if not participants_by_agent_id[agent_id]
    ]
    if missing:
        raise ChatRoomValidationError(
            "frozen participant agent is missing from the chat room: "
            + ", ".join(missing)
        )
    ambiguous = [
        agent_id
        for agent_id in frozen_agent_ids
        if len(participants_by_agent_id[agent_id]) != 1
    ]
    if ambiguous:
        raise ChatRoomValidationError(
            "frozen participant agent resolves to ambiguous chat room members: "
            + ", ".join(ambiguous)
        )
    resolved = [participants_by_agent_id[agent_id][0] for agent_id in frozen_agent_ids]
    disabled = [
        agent_id
        for agent_id, participant in zip(frozen_agent_ids, resolved)
        if participant.get("enabled", True) is not True
        or bool(participant.get("agentMissing"))
    ]
    if disabled:
        raise ChatRoomValidationError(
            "frozen participant agent must remain present and enabled: "
            + ", ".join(disabled)
        )
    return resolved


def _frozen_participant_agent_ids(config: dict[str, Any]) -> list[str] | None:
    if "participantAgentIds" not in config:
        return None
    raw_agent_ids = config.get("participantAgentIds")
    if not isinstance(raw_agent_ids, list):
        raise ChatRoomValidationError("frozen participant agent ids must be a list")
    frozen_agent_ids = [str(item or "").strip() for item in raw_agent_ids]
    if not frozen_agent_ids or any(not agent_id for agent_id in frozen_agent_ids):
        raise ChatRoomValidationError("frozen participant agent ids must be non-empty")
    if len(set(frozen_agent_ids)) != len(frozen_agent_ids):
        raise ChatRoomValidationError("frozen participant agent ids must be unique")
    return frozen_agent_ids


def _require_exact_frozen_speaker_roster(
    speakers: list[dict[str, Any]],
    config: dict[str, Any],
) -> None:
    frozen_agent_ids = _frozen_participant_agent_ids(config)
    if frozen_agent_ids is None:
        return
    speaker_agent_ids = [
        str(speaker.get("agentId") or "").strip() for speaker in speakers
    ]
    if speaker_agent_ids != frozen_agent_ids:
        raise ChatRoomValidationError(
            "frozen participant roster must remain complete and in frozen order after speaker selection"
        )


def _chat_room_participant_identity_keys(participant: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    agent_id = str(participant.get("agentId") or "").strip()
    if agent_id:
        keys.append(f"agent:{agent_id}")
    for field in ("directSessionId", "sessionId"):
        session_id = str(participant.get(field) or "").strip()
        if session_id:
            keys.append(f"session:{session_id}")
    participant_id = str(participant.get("participantId") or "").strip()
    if participant_id:
        keys.append(f"participant:{participant_id}")
    return keys


def _apply_participant_contexts(
    participants: list[dict[str, Any]],
    *,
    participant_contexts_by_agent_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    contexts = participant_contexts_by_agent_id if isinstance(participant_contexts_by_agent_id, dict) else {}
    if not contexts:
        return participants
    next_participants: list[dict[str, Any]] = []
    for participant in participants:
        item = dict(participant)
        agent_id = str(item.get("agentId") or "").strip()
        context = contexts.get(agent_id) if agent_id else None
        if isinstance(context, dict):
            for field in _PARTICIPANT_CONTEXT_FIELDS:
                value = context.get(field)
                if field == "teamResponsibilities":
                    item[field] = [
                        trim_lines(str(entry or ""), max_lines=1).strip()
                        for entry in list(value or [])[:8]
                        if trim_lines(str(entry or ""), max_lines=1).strip()
                    ]
                else:
                    item[field] = trim_lines(str(value or ""), max_lines=4).strip()
        next_participants.append(item)
    return next_participants


def _resolve_agent_participants(agent_ids: list[str] | None) -> list[dict[str, Any]]:
    lang = get_web_language()
    _sync_agent_directory_project_root()
    requested = [str(item or "").strip() for item in list(agent_ids or []) if str(item or "").strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for agent_id in requested:
        if agent_id in seen:
            continue
        seen.add(agent_id)
        deduped.append(agent_id)
    if len(deduped) < 2:
        raise ChatRoomValidationError(
            text_for(lang, zh="群聊至少需要选择两个可用 Agent。", en="Choose at least two available agents.")
        )

    active_agents = {
        str(item.get("agentId") or "").strip(): item
        for item in agent_directory_service.list_agents(include_archived=False)
        if isinstance(item, dict)
    }
    session_ids: list[str] = []
    for agent_id in deduped:
        agent = active_agents.get(agent_id)
        if not agent:
            raise ChatRoomValidationError(f"Unknown active agent: {agent_id}")
        if str(agent.get("kind") or "").strip() != agent_directory_service.DEFAULT_AGENT_KIND:
            raise ChatRoomValidationError(f"Agent is not persistent: {agent_id}")
        direct_session_id = str(agent.get("directSessionId") or "").strip()
        if not direct_session_id:
            raise ChatRoomValidationError(f"Agent has no direct chat session: {agent_id}")
        session_ids.append(direct_session_id)

    return _resolve_participants(session_ids)


def _resolve_agent_participant(agent_id: str) -> dict[str, Any]:
    lang = get_web_language()
    _sync_agent_directory_project_root()
    normalized_agent_id = str(agent_id or "").strip()
    agent = agent_directory_service.get_agent(normalized_agent_id, include_archived=False)
    if not agent:
        raise ChatRoomValidationError(f"Unknown active agent: {normalized_agent_id}")
    if str(agent.get("kind") or "").strip() != agent_directory_service.DEFAULT_AGENT_KIND:
        raise ChatRoomValidationError(f"Agent is not persistent: {normalized_agent_id}")
    direct_session_id = str(agent.get("directSessionId") or "").strip()
    if not direct_session_id:
        raise ChatRoomValidationError(
            text_for(
                lang,
                zh=f"Agent 没有直连会话: {normalized_agent_id}",
                en=f"Agent has no direct chat session: {normalized_agent_id}",
            )
        )
    return _resolve_participants([direct_session_id])[0]


def _resolve_chat_room_agent_llm(agent: dict[str, Any] | None) -> Any:
    """Resolve the room speaker runtime LLM from the Agent instance itself."""

    if not isinstance(agent, dict):
        raise ChatRoomValidationError(
            text_for(
                get_web_language(),
                zh="群聊成员缺少有效 Agent，不能解析运行模型。",
                en="The room participant has no valid Agent for runtime model resolution.",
            )
        )
    try:
        return session_service._resolve_session_agent_llm(agent, CHAT_ROOM_AGENT_LLM_SLOT)
    except session_service.SessionValidationError as exc:
        raise ChatRoomValidationError(str(exc)) from exc


def _participant_matches_agent(participant: dict[str, Any], agent_id: str, direct_session_id: str) -> bool:
    participant_agent_id = str(participant.get("agentId") or "").strip()
    if participant_agent_id and participant_agent_id == agent_id:
        return True
    if not direct_session_id:
        return False
    participant_session_ids = {
        str(participant.get("sessionId") or "").strip(),
        str(participant.get("directSessionId") or "").strip(),
    }
    return direct_session_id in participant_session_ids


def _matching_agent_id(
    participant: dict[str, Any],
    agent_ids: set[str],
    direct_session_ids_by_agent_id: dict[str, str],
) -> str:
    participant_agent_id = str(participant.get("agentId") or "").strip()
    if participant_agent_id and participant_agent_id in agent_ids:
        return participant_agent_id
    participant_session_ids = {
        str(participant.get("sessionId") or "").strip(),
        str(participant.get("directSessionId") or "").strip(),
    }
    for agent_id, direct_session_id in direct_session_ids_by_agent_id.items():
        if direct_session_id and direct_session_id in participant_session_ids:
            return agent_id
    return ""


def _dedupe_room_ids(room_ids: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for room_id in list(room_ids or []):
        normalized = str(room_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _participant_from_session(
    summary: dict[str, Any],
    *,
    include_recent_messages: bool = False,
    recent_messages: list[dict[str, str]] | None = None,
    active_agent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_id = str(summary.get("id") or "").strip()
    title = str(summary.get("title") or session_id).strip() or session_id
    detail = (session_service.get_session_detail(session_id) or {}) if include_recent_messages else {}
    agent_id = str(summary.get("agentId") or detail.get("agentId") or "").strip()
    agent = active_agent if isinstance(active_agent, dict) else None
    if agent is None and agent_id:
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
    llm_bindings = agent_directory_service.normalize_agent_llm_bindings((agent or {}).get("llmBindings"))
    dialogue_model_id = agent_directory_service.agent_dialogue_model_id({"llmBindings": llm_bindings})
    agent_missing = bool(summary.get("agentMissing") or detail.get("agentMissing"))
    agent_status_code = str(summary.get("agentStatusCode") or detail.get("agentStatusCode") or "").strip()
    agent_status_message = str(summary.get("agentStatusMessage") or detail.get("agentStatusMessage") or "").strip()
    return {
        "participantId": f"session-{_safe_fragment(session_id)}",
        "kind": "session_agent",
        "agentId": agent_id,
        "agentCode": str(summary.get("agentCode") or detail.get("agentCode") or "").strip(),
        "agentAvatarImageUrl": str(summary.get("agentAvatarImageUrl") or detail.get("agentAvatarImageUrl") or "").strip(),
        "directSessionId": session_id,
        "sessionId": session_id,
        "title": title,
        "workspacePath": str(summary.get("workspacePath") or detail.get("workspacePath") or ""),
        "dialogueModelId": dialogue_model_id,
        "llmBindings": llm_bindings,
        "agentMissing": agent_missing,
        "agentStatusCode": agent_status_code,
        "agentStatusMessage": agent_status_message,
        "enabled": not agent_missing,
        "status": str(summary.get("status") or ""),
        "recentMessages": (
            _compact_messages(detail.get("messages") or [])
            if include_recent_messages
            else list(recent_messages or [])
        ),
    }


def _is_scoped_discussion_room(value: Mapping[str, Any] | None) -> bool:
    """Identify the formal room envelope that owns Child Session bindings."""

    if not isinstance(value, Mapping):
        return False
    config = value.get("config") if isinstance(value.get("config"), Mapping) else value
    if str(config.get("scopeAuthority") or "").strip() != "workflow_discussion_scope.v1":
        return False
    return isinstance(config.get("discussionScope"), Mapping) and bool(
        str(config.get("scopeHash") or "").strip()
    )


def _is_challenge_discussion_room(value: Mapping[str, Any] | None) -> bool:
    """Recognize formal and preformal server-scoped Challenge rooms."""

    if not isinstance(value, Mapping):
        return False
    config = value.get("config") if isinstance(value.get("config"), Mapping) else value
    if str(config.get("scopeAuthority") or "").strip() not in {
        "workflow_discussion_scope.v1",
        "preformal_candidate_review_scope.v1",
    }:
        return False
    return isinstance(config.get("discussionScope"), Mapping) and bool(
        str(config.get("discussionScopeHash") or config.get("scopeHash") or "").strip()
    )


def _uses_structured_meeting_message(
    room: Mapping[str, Any] | None,
    round_payload: Mapping[str, Any] | None,
) -> bool:
    """Use the full protocol contract for formal grounded R1 generation."""

    if _is_scoped_discussion_room(room):
        return True
    if not isinstance(round_payload, Mapping):
        return False
    config = (
        round_payload.get("config")
        if isinstance(round_payload.get("config"), Mapping)
        else {}
    )
    return (
        str(config.get("meetingType") or "").strip()
        == "hypothesis_candidate_generation"
        and str(config.get("candidateAuthority") or "").strip().lower()
        == "formal_grounded_candidate"
    )


def _is_challenge_meeting_round(
    round_payload: Mapping[str, Any] | None,
) -> bool:
    """Identify candidate-generation/review context for prompt hydration."""

    if not isinstance(round_payload, Mapping):
        return False
    config = (
        round_payload.get("config")
        if isinstance(round_payload.get("config"), Mapping)
        else {}
    )
    meeting_type = str(
        config.get("meetingType") or round_payload.get("meetingType") or ""
    ).strip().lower()
    return meeting_type in _CHALLENGE_PRIOR_SEMANTIC_MEETING_TYPES


def _refresh_participants(
    participants: list[dict[str, Any]],
    *,
    include_recent_messages: bool = False,
    session_summaries: dict[str, dict[str, Any]] | None = None,
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
    active_agents_by_session_id: dict[str, dict[str, Any]] | None = None,
    preserve_scoped_session_ids: bool = False,
) -> list[dict[str, Any]]:
    refreshed: list[dict[str, Any]] = []
    for item in participants:
        if not isinstance(item, dict):
            continue
        active_agent = _active_agent_for_participant(
            item,
            active_agents_by_id=active_agents_by_id,
            active_agents_by_session_id=active_agents_by_session_id,
        )
        current_direct_session_id = str((active_agent or {}).get("directSessionId") or "").strip()
        stored_session_id = str(
            item.get("sessionId") or item.get("directSessionId") or ""
        ).strip()
        session_id = (
            stored_session_id
            if preserve_scoped_session_ids and stored_session_id
            else current_direct_session_id or stored_session_id
        )
        summary = _session_summary(session_id, session_summaries=session_summaries)
        if summary:
            participant = _participant_from_session(
                summary,
                include_recent_messages=include_recent_messages,
                recent_messages=list(item.get("recentMessages") or []),
                active_agent=active_agent,
            )
            participant["participantId"] = str(item.get("participantId") or participant["participantId"])
            participant["enabled"] = False if participant.get("agentMissing") else bool(item.get("enabled", True))
            participant["agentId"] = str(
                (active_agent or {}).get("agentId") or item.get("agentId") or participant.get("agentId") or ""
            ).strip()
            participant["agentCode"] = str(
                (active_agent or {}).get("agentCode") or item.get("agentCode") or participant.get("agentCode") or ""
            ).strip()
            participant["agentAvatarImageUrl"] = str(
                (active_agent or {}).get("avatarImageUrl")
                or item.get("agentAvatarImageUrl")
                or participant.get("agentAvatarImageUrl")
                or ""
            ).strip()
            participant["directSessionId"] = str(
                current_direct_session_id
                or item.get("directSessionId")
                or participant.get("directSessionId")
                or participant.get("sessionId")
                or ""
            ).strip()
            participant["sessionId"] = str(
                session_id if preserve_scoped_session_ids else current_direct_session_id
                or participant.get("sessionId")
                or ""
            ).strip()
            for field in _PARTICIPANT_CONTEXT_FIELDS:
                if field in item:
                    participant[field] = item.get(field)
            refreshed.append(participant)
        else:
            fallback = dict(item)
            if current_direct_session_id and not preserve_scoped_session_ids:
                fallback["sessionId"] = current_direct_session_id
                fallback["directSessionId"] = current_direct_session_id
            if active_agent:
                fallback["agentId"] = str(active_agent.get("agentId") or fallback.get("agentId") or "").strip()
                fallback["agentCode"] = str(active_agent.get("agentCode") or fallback.get("agentCode") or "").strip()
                fallback["agentAvatarImageUrl"] = str(active_agent.get("avatarImageUrl") or fallback.get("agentAvatarImageUrl") or "").strip()
                llm_bindings = agent_directory_service.normalize_agent_llm_bindings(active_agent.get("llmBindings"))
                dialogue_model_id = agent_directory_service.agent_dialogue_model_id({"llmBindings": llm_bindings})
                fallback["dialogueModelId"] = dialogue_model_id
                fallback["llmBindings"] = llm_bindings
                fallback["agentMissing"] = False
                fallback["agentStatusCode"] = ""
                fallback["agentStatusMessage"] = ""
                fallback["enabled"] = bool(item.get("enabled", True))
            session_id = str(fallback.get("sessionId") or fallback.get("directSessionId") or "").strip()
            if not active_agent and session_id and str(fallback.get("agentId") or "").strip():
                archived_agent = agent_directory_service.get_agent(str(fallback.get("agentId") or "").strip(), include_archived=True)
                archived_status = str((archived_agent or {}).get("status") or "").strip().lower()
                fallback["agentMissing"] = True
                fallback["agentStatusCode"] = "archived_agent" if archived_status == "archived" else "missing_agent"
                fallback["agentStatusMessage"] = _MISSING_SESSION_STATUS_MESSAGE
                fallback["enabled"] = False
            refreshed.append(fallback)
    return refreshed


def _refresh_chat_room_round_participants(
    participants: list[dict[str, Any]],
    *,
    preserve_scoped_session_ids: bool = False,
) -> list[dict[str, Any]]:
    """Refresh round participants without holding the chat-room persistence lock."""

    participant_indexes, _, _ = _participant_refresh_indexes(participants=participants)
    return _refresh_participants(
        participants,
        include_recent_messages=True,
        session_summaries=participant_indexes["session_summaries"],
        active_agents_by_id=participant_indexes["active_agents_by_id"],
        active_agents_by_session_id=participant_indexes["active_agents_by_session_id"],
        preserve_scoped_session_ids=preserve_scoped_session_ids,
    )


def _active_agent_for_participant(
    participant: dict[str, Any],
    *,
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
    active_agents_by_session_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    agent_id = str(participant.get("agentId") or "").strip()
    if agent_id:
        if active_agents_by_id is not None:
            agent = active_agents_by_id.get(agent_id)
            return dict(agent) if isinstance(agent, dict) else None
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        return dict(agent) if isinstance(agent, dict) else None
    session_ids = {
        str(participant.get("sessionId") or "").strip(),
        str(participant.get("directSessionId") or "").strip(),
    }
    session_ids.discard("")
    if not session_ids:
        return None
    if active_agents_by_session_id is not None:
        for session_id in session_ids:
            agent = active_agents_by_session_id.get(session_id)
            if isinstance(agent, dict):
                return dict(agent)
        return None
    try:
        agents = agent_directory_service.list_agents(include_archived=False)
    except Exception:
        return None
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("directSessionId") or "").strip() in session_ids:
            return dict(agent)
    return None


def _active_agent_participant_indexes(
    *,
    agent_ids: set[str] | None = None,
    session_ids: set[str] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    target_agent_ids = set(agent_ids or set())
    target_session_ids = set(session_ids or set())
    if target_agent_ids or target_session_ids:
        try:
            state = agent_directory_service.load_state()
            raw_agents = [
                item
                for item in list(state.get("agents") or [])
                if isinstance(item, dict)
                and str(item.get("status") or "active").strip().lower() != "archived"
                and (
                    str(item.get("agentId") or "").strip() in target_agent_ids
                    or str(item.get("directSessionId") or "").strip() in target_session_ids
                )
            ]
            agents = [agent_directory_service._agent_to_api_summary(item) for item in raw_agents]
        except Exception:
            try:
                agents = agent_directory_service.list_agents(include_archived=False, detail="summary")
            except Exception:
                agents = []
    else:
        try:
            agents = agent_directory_service.list_agents(include_archived=False, detail="summary")
        except Exception:
            agents = []
    by_id: dict[str, dict[str, Any]] = {}
    by_session_id: dict[str, dict[str, Any]] = {}
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        session_id = str(agent.get("directSessionId") or "").strip()
        if (target_agent_ids or target_session_ids) and agent_id not in target_agent_ids and session_id not in target_session_ids:
            continue
        if agent_id:
            by_id[agent_id] = dict(agent)
        if session_id:
            by_session_id[session_id] = dict(agent)
    return {"by_id": by_id, "by_session_id": by_session_id}


def prewarm_chat_room_participant_indexes(*, reason: str = "startup") -> dict[str, Any]:
    """Build the participant refresh index before the first room detail request."""

    global _CHAT_ROOM_PARTICIPANT_INDEX_PREWARM_INFLIGHT
    normalized_reason = trim_lines(reason, max_lines=1) or "startup"
    started_at = _perf_counter()
    with _CHAT_ROOM_PARTICIPANT_INDEX_PREWARM_LOCK:
        if _CHAT_ROOM_PARTICIPANT_INDEX_PREWARM_INFLIGHT:
            return {
                "status": "skipped",
                "reason": normalized_reason,
                "skipReason": "inflight",
                "durationMs": _elapsed_ms(started_at),
            }
        _CHAT_ROOM_PARTICIPANT_INDEX_PREWARM_INFLIGHT = True

    try:
        indexes, cache_hit, timings = _participant_refresh_indexes()
        duration_ms = _elapsed_ms(started_at)
        session_count = len(indexes.get("session_summaries") or {})
        active_agent_count = len(indexes.get("active_agents_by_id") or {})
        result = {
            "status": "completed",
            "reason": normalized_reason,
            "cacheHit": bool(cache_hit),
            "durationMs": duration_ms,
            "sessionCount": session_count,
            "activeAgentCount": active_agent_count,
        }
        _record_chat_room_participant_index_prewarm(
            status="completed",
            reason=normalized_reason,
            elapsed_ms=duration_ms,
            cache_hit=cache_hit,
            session_count=session_count,
            active_agent_count=active_agent_count,
            phase_timings=timings,
        )
        return result
    except Exception as exc:
        duration_ms = _elapsed_ms(started_at)
        _record_chat_room_participant_index_prewarm(
            status="failed",
            reason=normalized_reason,
            elapsed_ms=duration_ms,
            error_type=type(exc).__name__,
            error_message=trim_lines(str(exc), max_lines=2),
        )
        return {
            "status": "failed",
            "reason": normalized_reason,
            "durationMs": duration_ms,
            "errorType": type(exc).__name__,
        }
    finally:
        with _CHAT_ROOM_PARTICIPANT_INDEX_PREWARM_LOCK:
            _CHAT_ROOM_PARTICIPANT_INDEX_PREWARM_INFLIGHT = False


def _participant_refresh_indexes(
    *,
    participants: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, dict[str, dict[str, Any]]], bool, list[dict[str, Any]]]:
    timings: list[dict[str, Any]] = []
    participant_session_ids, participant_agent_ids = _participant_lookup_keys(participants)
    stage_started_at = _perf_counter()
    signature = _participant_refresh_index_signature(
        session_ids=participant_session_ids if participants is not None else None,
        agent_ids=participant_agent_ids if participants is not None else None,
    )
    _append_chat_room_detail_timing(timings, "participant_index.signature", stage_started_at)
    stage_started_at = _perf_counter()
    with _CHAT_ROOM_PARTICIPANT_INDEX_CACHE_CONDITION:
        while True:
            cached = _CHAT_ROOM_PARTICIPANT_INDEX_CACHE.get(signature)
            if isinstance(cached, dict):
                indexes = _copy_participant_refresh_indexes(cached)
                _append_chat_room_detail_timing(
                    timings,
                    "participant_index.cache_copy",
                    stage_started_at,
                    count=len(indexes.get("session_summaries") or {}),
                    cache_hit=True,
                )
                return indexes, True, timings
            if signature not in _CHAT_ROOM_PARTICIPANT_INDEX_INFLIGHT:
                _CHAT_ROOM_PARTICIPANT_INDEX_INFLIGHT.add(signature)
                break
            _CHAT_ROOM_PARTICIPANT_INDEX_CACHE_CONDITION.wait()

    try:
        stage_started_at = _perf_counter()
        active_agent_indexes = _active_agent_participant_indexes(
            agent_ids=participant_agent_ids if participants is not None else None,
            session_ids=participant_session_ids if participants is not None else None,
        )
        _append_chat_room_detail_timing(
            timings,
            "participant_index.active_agents",
            stage_started_at,
            count=len(active_agent_indexes.get("by_id") or {}),
        )
        effective_session_ids = set(participant_session_ids)
        for agent in active_agent_indexes.get("by_id", {}).values():
            if isinstance(agent, dict):
                direct_session_id = str(agent.get("directSessionId") or "").strip()
                if direct_session_id:
                    effective_session_ids.add(direct_session_id)
        stage_started_at = _perf_counter()
        session_summaries = _session_summary_index(
            session_ids=effective_session_ids if participants is not None else None
        )
        _append_chat_room_detail_timing(
            timings,
            "participant_index.session_summary",
            stage_started_at,
            count=len(session_summaries),
        )
        indexes = {
            "session_summaries": session_summaries,
            "active_agents_by_id": active_agent_indexes["by_id"],
            "active_agents_by_session_id": active_agent_indexes["by_session_id"],
        }
        stage_started_at = _perf_counter()
        with _CHAT_ROOM_PARTICIPANT_INDEX_CACHE_CONDITION:
            _CHAT_ROOM_PARTICIPANT_INDEX_CACHE.pop(signature, None)
            _CHAT_ROOM_PARTICIPANT_INDEX_CACHE[signature] = _copy_participant_refresh_indexes(indexes)
            while len(_CHAT_ROOM_PARTICIPANT_INDEX_CACHE) > _CHAT_ROOM_PARTICIPANT_INDEX_CACHE_MAX_ENTRIES:
                oldest_signature = next(iter(_CHAT_ROOM_PARTICIPANT_INDEX_CACHE))
                _CHAT_ROOM_PARTICIPANT_INDEX_CACHE.pop(oldest_signature, None)
        _append_chat_room_detail_timing(timings, "participant_index.cache_store", stage_started_at, cache_hit=False)
    finally:
        with _CHAT_ROOM_PARTICIPANT_INDEX_CACHE_CONDITION:
            _CHAT_ROOM_PARTICIPANT_INDEX_INFLIGHT.discard(signature)
            _CHAT_ROOM_PARTICIPANT_INDEX_CACHE_CONDITION.notify_all()

    stage_started_at = _perf_counter()
    copied = _copy_participant_refresh_indexes(indexes)
    _append_chat_room_detail_timing(
        timings,
        "participant_index.result_copy",
        stage_started_at,
        count=len(copied.get("session_summaries") or {}),
        cache_hit=False,
    )
    return copied, False, timings


def _clear_participant_refresh_index_cache() -> None:
    with _CHAT_ROOM_PARTICIPANT_INDEX_CACHE_CONDITION:
        _CHAT_ROOM_PARTICIPANT_INDEX_CACHE.clear()


def _participant_lookup_keys(participants: list[dict[str, Any]] | None) -> tuple[set[str], set[str]]:
    session_ids: set[str] = set()
    agent_ids: set[str] = set()
    if participants is None:
        return session_ids, agent_ids
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        for key in ("sessionId", "directSessionId"):
            session_id = str(participant.get(key) or "").strip()
            if session_id:
                session_ids.add(session_id)
        agent_id = str(participant.get("agentId") or "").strip()
        if agent_id:
            agent_ids.add(agent_id)
    return session_ids, agent_ids


def _participant_refresh_index_signature(
    *,
    session_ids: set[str] | None = None,
    agent_ids: set[str] | None = None,
) -> tuple[Any, ...]:
    return (
        _chat_state_participant_index_signature(session_ids=session_ids),
        _file_signature(agent_directory_service.registry_path()),
        (
            "participant_scope_v1",
            tuple(sorted(session_ids)) if session_ids is not None else "__all_sessions__",
            tuple(sorted(agent_ids)) if agent_ids is not None else "__all_agents__",
        ),
    )


def _chat_state_participant_index_signature(*, session_ids: set[str] | None = None) -> tuple[Any, ...]:
    path = chat_state_path(PROJECT_ROOT)
    payload = load_chat_state(PROJECT_ROOT)
    conversations = payload.get("conversations") if isinstance(payload, dict) else None
    if not isinstance(conversations, list):
        return ("chat_state_participants_unavailable", _file_signature(path))
    target_session_ids = set(session_ids or set()) if session_ids is not None else None
    rows: list[tuple[Any, ...]] = []
    for raw in conversations:
        if not isinstance(raw, dict):
            continue
        session_id = _signature_text(raw, "conversation_id", "id")
        if not session_id:
            continue
        if target_session_ids is not None and session_id not in target_session_ids:
            continue
        has_ledger_messages = bool(latest_ledger_sequence(PROJECT_ROOT, session_id))
        rows.append(
            (
                session_id,
                _signature_text(raw, "title"),
                _signature_text(raw, "agent_id", "agentId"),
                _signature_text(raw, "agent_missing_id", "agentMissingId"),
                bool(raw.get("agentMissing")),
                _signature_text(raw, "agentStatusCode"),
                bool(raw.get("agentDirectSessionMismatch")),
                _signature_text(raw, "agentPrimaryDirectSessionId"),
                _signature_text(raw, "workspace_path", "workspacePath"),
                has_ledger_messages,
            )
        )
    return ("chat_state_participants_v1", str(path), tuple(rows))


def _signature_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _signature_sequence(item: dict[str, Any], *keys: str) -> tuple[str, ...]:
    for key in keys:
        value = item.get(key)
        if isinstance(value, list):
            return tuple(str(child).strip() for child in value if str(child).strip())
    return ()


def _file_signature(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _copy_participant_refresh_indexes(
    indexes: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "session_summaries": _copy_index(indexes.get("session_summaries")),
        "active_agents_by_id": _copy_index(indexes.get("active_agents_by_id")),
        "active_agents_by_session_id": _copy_index(indexes.get("active_agents_by_session_id")),
    }


def _copy_index(index: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {
        str(key): dict(value)
        for key, value in dict(index or {}).items()
        if str(key) and isinstance(value, dict)
    }


def _repair_room_participants(
    room: dict[str, Any],
    *,
    session_summaries: dict[str, dict[str, Any]] | None = None,
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
    active_agents_by_session_id: dict[str, dict[str, Any]] | None = None,
    preserve_scoped_session_ids: bool = False,
    deferred_events: list[dict[str, Any]] | None = None,
) -> bool:
    participants = list(room.get("participants") or [])
    refreshed = _refresh_participants(
        participants,
        session_summaries=session_summaries,
        active_agents_by_id=active_agents_by_id,
        active_agents_by_session_id=active_agents_by_session_id,
        preserve_scoped_session_ids=preserve_scoped_session_ids,
    )
    previous_missing_sessions = {
        str(item.get("sessionId") or item.get("directSessionId") or "").strip()
        for item in participants
        if isinstance(item, dict) and bool(item.get("agentMissing"))
    }
    newly_missing = [
        item for item in refreshed
        if isinstance(item, dict)
        and bool(item.get("agentMissing"))
        and str(item.get("sessionId") or item.get("directSessionId") or "").strip() not in previous_missing_sessions
    ]
    for participant in newly_missing:
        # Scene-event writes are file I/O; per the lock order contract callers
        # that repair under _CHAT_ROOM_LOCK defer them until after the lock.
        event_fields = {
            "sessionId": str(participant.get("sessionId") or participant.get("directSessionId") or "").strip(),
            "agentId": str(participant.get("agentId") or "").strip(),
            "agentStatusCode": str(participant.get("agentStatusCode") or "").strip(),
            "enabled": bool(participant.get("enabled")),
        }
        if deferred_events is not None:
            deferred_events.append(
                {
                    "room": dict(room),
                    "fields": event_fields,
                }
            )
            continue
        _record_room_event(
            "participant",
            "chat_room.participant_agent_missing",
            room,
            fields=event_fields,
            outcome="disabled",
            level="warning",
            lifecycle=True,
        )
    if refreshed == participants:
        return False
    room["participants"] = refreshed
    room["updatedAt"] = utc_now_iso()
    return True


def _repair_room_participants_in_state(
    state: dict[str, Any],
    *,
    session_summaries: dict[str, dict[str, Any]] | None = None,
    active_agent_indexes: dict[str, dict[str, dict[str, Any]]] | None = None,
    deferred_events: list[dict[str, Any]] | None = None,
) -> bool:
    changed = False
    # ``active_agent_indexes`` lets callers that repair under _CHAT_ROOM_LOCK
    # precompute the directory read outside the lock (lock order contract).
    indexes = active_agent_indexes if active_agent_indexes is not None else _active_agent_participant_indexes()
    for room in list(state.get("rooms") or []):
        if not isinstance(room, dict):
            continue
        if _repair_room_participants(
            room,
            session_summaries=session_summaries,
            active_agents_by_id=indexes["by_id"],
            active_agents_by_session_id=indexes["by_session_id"],
            preserve_scoped_session_ids=_is_challenge_discussion_room(room),
            deferred_events=deferred_events,
        ):
            changed = True
    return changed


def _emit_deferred_participant_repair_events(events: list[dict[str, Any]]) -> None:
    for item in events:
        _record_room_event(
            "participant",
            "chat_room.participant_agent_missing",
            item.get("room") or {},
            fields=item.get("fields") or {},
            outcome="disabled",
            level="warning",
            lifecycle=True,
        )


def _session_summary_index(*, session_ids: set[str] | None = None) -> dict[str, dict[str, Any]]:
    if session_ids is not None:
        return _targeted_session_summary_index(session_ids)
    return {
        str(item.get("id") or "").strip(): item
        for item in session_service.list_sessions(include_hidden_internal=True)
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }


def _targeted_session_summary_index(session_ids: set[str]) -> dict[str, dict[str, Any]]:
    target_session_ids = {str(item or "").strip() for item in session_ids if str(item or "").strip()}
    if not target_session_ids:
        return {}
    if getattr(session_service, "PROJECT_ROOT", PROJECT_ROOT) != PROJECT_ROOT:
        session_service.PROJECT_ROOT = PROJECT_ROOT
    try:
        payload = load_chat_state(PROJECT_ROOT)
        conversations = payload.get("conversations") if isinstance(payload, dict) else []
        agent_by_id = session_service._agent_lookup_for_conversations()
        summaries: dict[str, dict[str, Any]] = {}
        for raw in list(conversations or []):
            if not isinstance(raw, dict):
                continue
            session_id = str(raw.get("conversation_id") or raw.get("id") or "").strip()
            if session_id not in target_session_ids:
                continue
            conversation = session_service._normalize_conversation(
                raw,
                agent_by_id=agent_by_id,
                ensure_workspace=False,
                lightweight=True,
            )
            if not isinstance(conversation, dict):
                continue
            summary = session_service._build_session_summary(conversation, hydrate_agent=False)
            if session_service._session_agent_visible_in_indexes(summary):
                summaries[session_id] = summary
        missing_session_ids = target_session_ids.difference(summaries)
        for session_id in missing_session_ids:
            stub = session_service._agent_directory_session_stub_for_id(session_id, agent_by_id=agent_by_id)
            if not isinstance(stub, dict):
                continue
            summary = session_service._build_session_summary(stub, hydrate_agent=False)
            if session_service._session_agent_visible_in_indexes(summary):
                summaries[session_id] = summary
        return summaries
    except Exception:
        return {
            session_id: item
            for session_id, item in _session_summary_index().items()
            if session_id in target_session_ids
        }


def _session_summary(
    session_id: str,
    *,
    session_summaries: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    if session_summaries is not None:
        return session_summaries.get(normalized_session_id)
    for item in session_service.list_sessions(include_hidden_internal=True):
        if str(item.get("id") or "").strip() == normalized_session_id:
            return item
    return None


def _compact_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for item in list(messages or [])[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = trim_lines(str(item.get("content") or ""), max_lines=3)
        if role and content:
            compact.append({"role": role, "content": content})
    return compact


def _require_ready_mode(mode: str):
    scheduler = get_scheduler_registry().get(mode)
    if scheduler is None:
        raise ChatRoomValidationError(f"Unknown chat room mode: {mode}")
    if scheduler.status != "ready":
        raise ChatRoomValidationError(f"Chat room mode {mode} is not ready.")
    return scheduler


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or DEFAULT_MODE).strip().lower().replace("-", "_")
    return normalized or DEFAULT_MODE


def _normalize_purpose(purpose: Any) -> str:
    normalized = str(purpose or DEFAULT_PURPOSE).strip().lower().replace("-", "_")
    allowed = {str(item["id"]) for item in CHAT_ROOM_PURPOSES}
    return normalized if normalized in allowed else DEFAULT_PURPOSE


def _resolve_round_purpose(topic: str, purpose: Any) -> str:
    normalized = _normalize_purpose(purpose)
    if normalized == DEFAULT_PURPOSE and _CASUAL_CHAT_TOPIC_RE.match(str(topic or "")):
        return "chat"
    return normalized


def _safe_config(config: Any) -> dict[str, Any]:
    return dict(config) if isinstance(config, dict) else {}


def _chat_room_kernel_trace_summary(round_payload: dict[str, Any]) -> dict[str, Any]:
    trace = round_payload.get("kernel") if isinstance(round_payload.get("kernel"), dict) else {}
    if not trace:
        return {}
    return {
        "source": str(trace.get("source") or "agent_kernel").strip() or "agent_kernel",
        "traceOnly": bool(trace.get("traceOnly", True)),
        "status": str(trace.get("status") or "").strip(),
        "eventId": str(trace.get("eventId") or "").strip(),
        "taskId": str(trace.get("taskId") or "").strip(),
        "workRunId": str(trace.get("workRunId") or "").strip(),
        "outcomeId": str(trace.get("outcomeId") or "").strip(),
        "outcomeStatus": str(trace.get("outcomeStatus") or "").strip(),
        "reused": bool(trace.get("reused")),
        "errorType": str(trace.get("errorType") or "").strip(),
        "reason": str(trace.get("reason") or "").strip(),
    }


def _room_to_api(
    room: dict[str, Any],
    *,
    available_modes: list[dict[str, str]] | None = None,
    available_purposes: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload = dict(room)
    payload["mode"] = str(payload.get("mode") or DEFAULT_MODE).strip() or DEFAULT_MODE
    payload["purpose"] = _normalize_purpose(payload.get("purpose") or DEFAULT_PURPOSE)
    payload["participants"] = [dict(item) for item in list(room.get("participants") or []) if isinstance(item, dict)]
    rounds = [item for item in list(room.get("rounds") or []) if isinstance(item, dict)]
    # The UI only reads the newest round's transcript; cap older rounds so a
    # long-lived room does not ship every historical message on each snapshot.
    payload["rounds"] = [
        _round_to_api(
            item,
            payload,
            message_limit=None if index == len(rounds) - 1 else _CHAT_ROOM_API_HISTORY_MESSAGE_LIMIT,
        )
        for index, item in enumerate(rounds)
    ]
    payload["availableModes"] = available_modes if available_modes is not None else list_chat_room_modes()
    payload["availablePurposes"] = available_purposes if available_purposes is not None else list_chat_room_purposes()
    return payload


def _room_to_conversation_index_reference(room: dict[str, Any]) -> dict[str, Any]:
    rounds = [item for item in list(room.get("rounds") or []) if isinstance(item, dict)]
    latest_round = rounds[-1] if rounds else {}
    return {
        "roomId": str(room.get("roomId") or "").strip(),
        "title": str(room.get("title") or room.get("roomId") or "").strip(),
        "status": str(room.get("status") or "").strip(),
        "summary": str(latest_round.get("summary") or "").strip(),
        "updatedAt": str(room.get("updatedAt") or "").strip(),
        "mode": str(room.get("mode") or "").strip(),
        "participants": [
            dict(item)
            for item in list(room.get("participants") or [])
            if isinstance(item, dict)
        ],
    }


def _round_to_api(
    round_payload: dict[str, Any],
    room_payload: dict[str, Any],
    *,
    message_limit: int | None = None,
) -> dict[str, Any]:
    payload = dict(round_payload)
    payload["mode"] = str(payload.get("mode") or room_payload.get("mode") or DEFAULT_MODE).strip() or DEFAULT_MODE
    payload["purpose"] = _normalize_purpose(payload.get("purpose") or room_payload.get("purpose") or DEFAULT_PURPOSE)
    case_state = _normalize_case_state_for_api(payload.get("caseState"))
    if case_state:
        payload["caseState"] = case_state
    messages = [
        _message_to_api(message, case_state)
        for message in list(payload.get("messages") or [])
        if isinstance(message, dict)
    ]
    if message_limit is not None and len(messages) > message_limit:
        payload["messagesTruncated"] = True
        payload["messagesTotalCount"] = len(messages)
        messages = messages[-message_limit:]
    payload["messages"] = messages
    return payload


def _normalize_case_state_for_api(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    payload = dict(value)
    intent = str(payload.get("intent") or "").strip()
    next_action = str(payload.get("nextAction") or "").strip()
    if next_action == "ask_user":
        next_action = "clarify"
    elif next_action == "delegate":
        next_action = "discuss"
    elif not next_action:
        next_action = "discuss"
    payload["nextAction"] = next_action
    missing_facts = list(payload.get("missingFacts") or []) if isinstance(payload.get("missingFacts"), list) else []
    risk_flags = list(payload.get("riskFlags") or []) if isinstance(payload.get("riskFlags"), list) else []
    if not str(payload.get("informationSufficiency") or "").strip():
        if risk_flags:
            payload["informationSufficiency"] = "urgent_boundary_needed"
        elif intent in CONSULTATION_INTENTS and len(missing_facts) >= 3:
            payload["informationSufficiency"] = "insufficient"
        elif intent in CONSULTATION_INTENTS and missing_facts:
            payload["informationSufficiency"] = "partially_sufficient"
        else:
            payload["informationSufficiency"] = "sufficient"
    if not str(payload.get("userFacingMode") or "").strip():
        if next_action == "clarify":
            payload["userFacingMode"] = "direct_clarification"
        elif next_action == "synthesize":
            payload["userFacingMode"] = "final_answer"
        elif intent in CONSULTATION_INTENTS:
            payload["userFacingMode"] = "team_discussion_then_advice"
        else:
            payload["userFacingMode"] = "team_discussion"
    if not str(payload.get("discussionVisibility") or "").strip():
        payload["discussionVisibility"] = "collapsed_by_default" if next_action in {"discuss", "synthesize"} else "user_visible"
    return payload


def _message_to_api(message: dict[str, Any], case_state: dict[str, Any]) -> dict[str, Any]:
    payload = dict(message)
    if not str(payload.get("messageKind") or "").strip():
        payload.update(_case_message_metadata({"caseState": case_state}))
    return payload


def _room_to_compact_reference(room: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "roomId": str(room.get("roomId") or "").strip(),
        "title": str(room.get("title") or "").strip(),
        "mode": str(room.get("mode") or DEFAULT_MODE).strip() or DEFAULT_MODE,
        "purpose": _normalize_purpose(room.get("purpose") or DEFAULT_PURPOSE),
        "status": str(room.get("status") or "").strip(),
        "activeRoundId": str(room.get("activeRoundId") or "").strip(),
        "updatedAt": str(room.get("updatedAt") or "").strip(),
        "config": _safe_config(room.get("config") or {}),
        "participants": [
            {
                "participantId": str(item.get("participantId") or "").strip(),
                "agentId": str(item.get("agentId") or "").strip(),
                "agentCode": str(item.get("agentCode") or "").strip(),
                "sessionId": str(item.get("sessionId") or item.get("directSessionId") or "").strip(),
                "directSessionId": str(item.get("directSessionId") or item.get("sessionId") or "").strip(),
                "dialogueModelId": str(item.get("dialogueModelId") or "").strip(),
                "llmBindings": agent_directory_service.normalize_agent_llm_bindings(item.get("llmBindings")),
                "enabled": bool(item.get("enabled", True)),
                **{field: item.get(field) for field in _PARTICIPANT_CONTEXT_FIELDS if field in item},
            }
            for item in list(room.get("participants") or [])
            if isinstance(item, dict)
        ],
        "rounds": [
            {
                "roundId": str(item.get("roundId") or "").strip(),
                "status": str(item.get("status") or "").strip(),
            }
            for item in list(room.get("rounds") or [])
            if isinstance(item, dict)
        ],
    }
    return payload


def _store() -> ChatRoomStore:
    workspace_root = developer_sandbox.formal_workspace_path(PROJECT_ROOT)
    return ChatRoomStore(root=workspace_root.parent)


def _work_run_store() -> work_run_store.WorkRunStore:
    return work_run_store.WorkRunStore(root=work_run_store.WORK_RUNS_DIR)


def _create_chat_room_round_control(room_id: str, round_id: str) -> None:
    normalized_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        return
    with _CHAT_ROOM_ROUND_CONTROLS_LOCK:
        _CHAT_ROOM_ROUND_CONTROLS[normalized_round_id] = {
            "roomId": str(room_id or "").strip(),
            "roundId": normalized_round_id,
            "stopReason": "",
            "stopRequestedAt": "",
        }


def _request_chat_room_round_stop(round_id: str, reason: str) -> None:
    normalized_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        return
    with _CHAT_ROOM_ROUND_CONTROLS_LOCK:
        control = _CHAT_ROOM_ROUND_CONTROLS.setdefault(
            normalized_round_id,
            {
                "roomId": "",
                "roundId": normalized_round_id,
                "stopReason": "",
                "stopRequestedAt": "",
            },
        )
        control["stopReason"] = str(reason or "").strip()
        control["stopRequestedAt"] = utc_now_iso()


def _chat_room_round_stop_reason(round_id: str) -> str:
    normalized_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        return ""
    with _CHAT_ROOM_ROUND_CONTROLS_LOCK:
        control = _CHAT_ROOM_ROUND_CONTROLS.get(normalized_round_id) or {}
        return str(control.get("stopReason") or "").strip()


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _resolve_challenge_room_deadline_at_ms(
    room: Mapping[str, Any] | None,
    supplied_config: Mapping[str, Any],
    *,
    receipt_authority: Mapping[str, Any] | None,
) -> int | None:
    """Carry one persisted logical-meeting clock into all of its room rounds."""

    supplied_deadline_at_ms = _positive_int(
        supplied_config.get(_CHALLENGE_ROOM_DEADLINE_CONFIG_KEY)
    )
    # An explicitly supplied deadline is server-derived by the meeting
    # runtime from the persisted MeetingRound policy.  It must survive even
    # when the round runs on the team base room, which is not itself a
    # scoped Challenge room; otherwise formal meetings would lose both of
    # their fences.  Ordinary rooms never carry the key and stay unaffected.
    if not _is_challenge_discussion_room(room) and supplied_deadline_at_ms is None:
        return None
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        current_challenge_task_deadline_at_ms,
    )

    # Follow-up meeting rounds execute in their own scheduler thread. Their
    # config is server-derived from the persisted formal MeetingRound.
    candidates = [
        value
        for value in (
            supplied_deadline_at_ms,
            _positive_int(current_challenge_task_deadline_at_ms()),
        )
        if value is not None
    ]
    return min(candidates) if candidates else None


def _challenge_room_deadline_stop_reason(context: Mapping[str, Any]) -> str:
    deadline_at_ms = _positive_int(context.get("challengeDeadlineAtMs"))
    if deadline_at_ms is None:
        return ""
    return (
        _CHALLENGE_ROOM_DEADLINE_STOP_REASON
        if int(time.time() * 1000) >= deadline_at_ms
        else ""
    )


def _challenge_room_per_call_stop_reason(context: Mapping[str, Any]) -> str:
    """Expiry of the current speaker call budget only, never the meeting."""

    deadline_at_ms = _positive_int(
        context.get(_CHALLENGE_ROOM_PER_CALL_DEADLINE_CONTEXT_KEY)
    )
    if deadline_at_ms is None:
        return ""
    return (
        _CHALLENGE_ROOM_PER_CALL_STOP_REASON
        if int(time.time() * 1000) >= deadline_at_ms
        else ""
    )


def _challenge_room_speaker_abort_reason(
    round_id: str,
    context: Mapping[str, Any],
    *,
    force_run_read: bool = False,
) -> str:
    """Return the reason to abort the current speaker call, if any.

    Meeting-level and workflow-run fences may register a round stop (and thus
    terminate the whole meeting); the per-call fence only aborts the in-flight
    speaker call so the round can advance to the next speaker.
    """

    reason = _request_challenge_room_execution_stop(
        round_id,
        context,
        force_run_read=force_run_read,
    )
    if reason:
        return reason
    return _challenge_room_per_call_stop_reason(context)


def _challenge_room_workflow_run_stop_reason(
    context: Mapping[str, Any],
    *,
    force: bool = False,
) -> str:
    authority = context.get("_modelInvocationReceiptAuthority")
    if not isinstance(authority, Mapping):
        return ""
    now = time.monotonic()
    if isinstance(context, dict):
        last_read = context.get("_challengeWorkflowRunReadAtMonotonic")
        if (
            not force
            and isinstance(last_read, (int, float))
            and now - float(last_read) < _CHALLENGE_ROOM_RUN_POLL_INTERVAL_SECONDS
        ):
            return str(context.get("_challengeWorkflowRunStopReason") or "")
    from core.web.services.team_workflow.research_runtime.meeting_receipt_authority import (
        workflow_run_stop_reason,
    )

    reason = workflow_run_stop_reason(authority)
    if isinstance(context, dict):
        context["_challengeWorkflowRunReadAtMonotonic"] = now
        context["_challengeWorkflowRunStopReason"] = reason
    return reason


def _request_challenge_room_execution_stop(
    round_id: str,
    context: Mapping[str, Any],
    *,
    force_run_read: bool = False,
) -> str:
    reason = _challenge_room_deadline_stop_reason(context)
    if not reason:
        reason = _challenge_room_workflow_run_stop_reason(
            context,
            force=force_run_read,
        )
    if reason and _chat_room_round_has_process_control(round_id):
        _request_chat_room_round_stop(round_id, reason)
    return reason


def _challenge_room_execution_slot_wait_seconds(context: Mapping[str, Any]) -> float:
    deadline_at_ms = _positive_int(context.get("challengeDeadlineAtMs"))
    if deadline_at_ms is None:
        return 900.0
    remaining_seconds = max(0.001, (deadline_at_ms - int(time.time() * 1000)) / 1000.0)
    return min(900.0, remaining_seconds)


def _chat_room_interrupt_checker(
    round_id: str,
    context: Mapping[str, Any],
) -> Callable[[], str]:
    """Compose manual stop + formal deadline and opt Chat transport into abort."""

    def interrupt_checker() -> str:
        reason = _chat_room_round_stop_reason(round_id)
        if reason:
            return reason
        return _challenge_room_speaker_abort_reason(round_id, context)

    interrupt_checker._vibelution_chat_provider_abort_enabled = bool(  # type: ignore[attr-defined]
        _positive_int(context.get("challengeDeadlineAtMs"))
        or _positive_int(context.get(_CHALLENGE_ROOM_PER_CALL_DEADLINE_CONTEXT_KEY))
        or isinstance(context.get("_modelInvocationReceiptAuthority"), Mapping)
    )
    return interrupt_checker


def _clear_chat_room_round_control(round_id: str) -> None:
    normalized_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        return
    with _CHAT_ROOM_ROUND_CONTROLS_LOCK:
        _CHAT_ROOM_ROUND_CONTROLS.pop(normalized_round_id, None)


def _chat_room_round_has_process_control(round_id: str) -> bool:
    normalized_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        return False
    with _CHAT_ROOM_ROUND_CONTROLS_LOCK:
        return normalized_round_id in _CHAT_ROOM_ROUND_CONTROLS


def _chat_room_work_run_snapshot(
    room: dict[str, Any],
    round_payload: dict[str, Any],
    *,
    status: str = "",
) -> dict[str, Any]:
    normalized_status = str(status or round_payload.get("status") or "running").strip().lower()
    payload = {
        "runId": str(round_payload.get("roundId") or "").strip(),
        "runKind": RUN_KIND,
        "track": "dialogue",
        "roomId": str(room.get("roomId") or "").strip(),
        "roundId": str(round_payload.get("roundId") or "").strip(),
        "status": normalized_status,
        "currentPhase": normalized_status,
        "leases": list(RUN_LEASES),
        "topic": str(round_payload.get("topic") or "").strip(),
        "mode": str(round_payload.get("mode") or DEFAULT_MODE).strip(),
        "purpose": _normalize_purpose(round_payload.get("purpose") or room.get("purpose") or DEFAULT_PURPOSE),
        "summary": str(round_payload.get("summary") or "").strip(),
        "startedAt": str(round_payload.get("startedAt") or "").strip(),
        "updatedAt": str(round_payload.get("updatedAt") or "").strip(),
        "finishedAt": str(round_payload.get("finishedAt") or "").strip(),
    }
    kernel_trace = _chat_room_kernel_trace_summary(round_payload)
    if kernel_trace:
        payload["kernel"] = kernel_trace
    return payload


def _stopped_round_summary(reason: str, *, message_count: int, speaker_count: int) -> str:
    return text_for(
        get_web_language(),
        zh=f"群聊轮次已停止：{message_count}/{speaker_count} 位 Agent 已发言。{reason}".strip(),
        en=f"Chat room round stopped: {message_count}/{speaker_count} agents responded. {reason}".strip(),
    )


def _chat_room_round_is_terminal(room: dict[str, Any], round_payload: dict[str, Any], round_id: str) -> bool:
    normalized_round_id = str(round_id or "").strip()
    status = str(round_payload.get("status") or "").strip().lower()
    if status and status not in RUNNING_ROUND_STATUSES:
        return True
    active_round_id = str(room.get("activeRoundId") or "").strip()
    return bool(active_round_id and normalized_round_id and active_round_id != normalized_round_id)


def _terminal_chat_room_status_from_work_run(snapshot: dict[str, Any] | None) -> str:
    payload = snapshot if isinstance(snapshot, dict) else {}
    status = str(payload.get("status") or payload.get("currentPhase") or payload.get("phase") or "").strip().lower()
    runtime_status = str(payload.get("runtimeStatus") or "").strip().lower()
    if status in {"completed", "done", "ready", "routed", "success", "succeeded"}:
        return "completed"
    if status in {"partial", "needs_continue", "paused_limit"}:
        return "partial"
    if status in {"stopped", "stopped_by_user", "cancelled", "canceled", "closed", "idle", "superseded", "terminated"}:
        return "stopped"
    if runtime_status in {"force_stopped", "stopped", "cancelled", "canceled", "terminated"}:
        return "stopped"
    if status in {"failed", "failed_provider", "failed_runtime", "error", "stop_failed"}:
        return "failed"
    if runtime_status in {"failed", "failed_provider", "failed_runtime", "error"}:
        return "failed"
    return ""


def _parse_utc_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _chat_room_work_run_heartbeat_fresh(work_run: Mapping[str, Any] | None) -> bool:
    """True when a running WorkRun snapshot was renewed inside the heartbeat window.

    A round executor renews its WorkRun every ``_CHALLENGE_ROOM_HEARTBEAT_INTERVAL_SECONDS``
    while a speaker call runs, and every speaker completion persists the snapshot
    too.  A fresh heartbeat therefore proves the owning backend process is alive,
    even when the in-memory round control record went missing; a genuinely dead
    process stops renewing and the snapshot ages out of the window.  Terminal or
    missing snapshots never count as fresh.
    """

    payload = work_run if isinstance(work_run, Mapping) else {}
    if str(payload.get("finishedAt") or "").strip():
        return False
    status = str(
        payload.get("status") or payload.get("currentPhase") or payload.get("phase") or ""
    ).strip().lower()
    if status and status not in RUNNING_ROUND_STATUSES:
        return False
    updated_at = _parse_utc_datetime(payload.get("updatedAt"))
    if updated_at is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
    return 0.0 <= age_seconds < _CHAT_ROOM_WORK_RUN_HEARTBEAT_FRESH_SECONDS


def _record_round_heartbeat_exempt_event(
    room_id: str,
    round_id: str,
    *,
    stage: str,
) -> None:
    try:
        record_runtime_scene_event(
            "chat_room",
            "reconcile",
            "chat_room.round.orphan_heartbeat_exempt",
            message=(
                "Running chat room round without an in-process controller kept alive "
                "by a fresh WorkRun heartbeat; orphan close-out skipped."
            ),
            outcome="exempted",
            fields={
                "roomId": str(room_id or "").strip(),
                "roundId": str(round_id or "").strip(),
                "stage": str(stage or "").strip(),
                "heartbeatWindowSeconds": _CHAT_ROOM_WORK_RUN_HEARTBEAT_FRESH_SECONDS,
            },
        )
    except Exception:
        return


def _chat_room_reconciliation_reason(snapshot: dict[str, Any], *, final_status: str) -> str:
    reason = trim_lines(
        str(
            snapshot.get("forceStopReason")
            or snapshot.get("stopReason")
            or snapshot.get("reason")
            or snapshot.get("summary")
            or snapshot.get("error")
            or ""
        ),
        max_lines=2,
    ).strip()
    if reason:
        return reason
    fallback_messages = {
        "completed": (
            "运行任务已完成，群聊状态已完成对账。",
            "The work run completed and the chat room state was reconciled.",
        ),
        "partial": (
            "运行任务已部分完成，群聊状态已完成对账。",
            "The work run partially completed and the chat room state was reconciled.",
        ),
        "stopped": (
            "运行任务已终止，群聊状态已完成对账。",
            "The work run terminated and the chat room state was reconciled.",
        ),
        "failed": (
            "运行任务失败，群聊状态已完成对账。",
            "The work run failed and the chat room state was reconciled.",
        ),
    }
    zh, en = fallback_messages.get(final_status, fallback_messages["failed"])
    return text_for(
        get_web_language(),
        zh=zh,
        en=en,
    )


def _chat_room_reconcile_store_token() -> str:
    try:
        stat = _store().state_path.stat()
    except OSError:
        return "missing"
    return f"{stat.st_mtime_ns}"


def _acquire_chat_room_reconcile_run() -> bool:
    """Return True when this caller may run a reconcile pass.

    See the gate notes next to the module-level gate state: runs are deduped
    per store-file change, bounded by a staleness TTL, and never overlap.
    """

    global _CHAT_ROOM_RECONCILE_INFLIGHT
    now = _perf_counter()
    token = _chat_room_reconcile_store_token()
    with _CHAT_ROOM_RECONCILE_GATE_LOCK:
        if _CHAT_ROOM_RECONCILE_INFLIGHT:
            return False
        if _CHAT_ROOM_RECONCILE_LAST_RUN_AT is not None:
            unchanged = token == _CHAT_ROOM_RECONCILE_LAST_STORE_TOKEN
            within_ttl = now - _CHAT_ROOM_RECONCILE_LAST_RUN_AT < _CHAT_ROOM_RECONCILE_MIN_INTERVAL_SECONDS
            if unchanged and within_ttl:
                return False
        _CHAT_ROOM_RECONCILE_INFLIGHT = True
        return True


def _release_chat_room_reconcile_run() -> None:
    global _CHAT_ROOM_RECONCILE_INFLIGHT, _CHAT_ROOM_RECONCILE_LAST_RUN_AT, _CHAT_ROOM_RECONCILE_LAST_STORE_TOKEN
    with _CHAT_ROOM_RECONCILE_GATE_LOCK:
        _CHAT_ROOM_RECONCILE_INFLIGHT = False
        _CHAT_ROOM_RECONCILE_LAST_RUN_AT = _perf_counter()
        _CHAT_ROOM_RECONCILE_LAST_STORE_TOKEN = _chat_room_reconcile_store_token()


def _reconcile_chat_room_round_state() -> list[dict[str, Any]]:
    """Converge persisted active rooms with terminal WorkRuns or process ownership."""

    if not _acquire_chat_room_reconcile_run():
        return []
    try:
        return _reconcile_chat_room_round_state_locked_gate()
    except ChatRoomStoreReadError as exc:
        # An unreadable room store means the durable state is unknown.  Skip
        # this pass instead of treating it as an empty store: closing rounds
        # (or overwriting state) from an unknown baseline would be unsafe, and
        # the next read retries the reconciliation.
        _record_store_read_failed_event(exc)
        return []
    finally:
        _release_chat_room_reconcile_run()


def _record_store_read_failed_event(exc: ChatRoomStoreReadError) -> None:
    try:
        record_runtime_scene_event(
            "chat_room",
            "reconcile",
            "chat_room.store.read_failed",
            message=(
                "Chat room state file could not be read; reconciliation skipped "
                "instead of treating the store as empty."
            ),
            level="warning",
            outcome="failed",
            fields={
                "path": str(getattr(exc, "path", "")),
                "errorType": type(exc).__name__,
                "errorPreview": trim_lines(str(exc), max_lines=2),
            },
        )
    except Exception:
        return


def _reconcile_chat_room_round_state_locked_gate() -> list[dict[str, Any]]:
    if _chat_room_lock_owned_by_current_thread():
        return []
    store = _work_run_store()
    reconciled_at = utc_now_iso()

    # WorkRun reads can touch a separate persistent store.  Take a small room
    # snapshot first, then resolve the WorkRun state without holding the room
    # mutex.  Holding this mutex across that I/O blocks detail, stop, and room
    # recovery requests behind one slow reconciliation read.
    active_rounds: list[tuple[str, str]] = []
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        for room in list(state.get("rooms") or []):
            if not isinstance(room, dict):
                continue
            round_id = str(room.get("activeRoundId") or "").strip()
            if not round_id:
                continue
            round_payload = _find_round(room, round_id)
            if not isinstance(round_payload, dict):
                continue
            previous_status = str(round_payload.get("status") or "").strip().lower()
            if previous_status not in RUNNING_ROUND_STATUSES:
                continue
            active_rounds.append((str(room.get("roomId") or "").strip(), round_id))

    candidates: list[dict[str, Any]] = []
    for room_id, round_id in active_rounds:
        if not room_id:
            continue
        work_run = store.load_snapshot(RUN_KIND, round_id)
        final_status = _terminal_chat_room_status_from_work_run(work_run)
        reconciliation_source = "terminal_work_run"
        if not final_status and not _chat_room_round_has_process_control(round_id):
            # A fresh WorkRun heartbeat proves the round's backend process is
            # alive; a missing in-memory control record must never kill such a
            # round (the historical mis-kill restarted live meetings from
            # round 1 in a loop).  A genuinely dead process stops renewing the
            # heartbeat and expires out of the window, so this exemption only
            # spares live rounds.
            if _chat_room_work_run_heartbeat_fresh(work_run):
                _record_round_heartbeat_exempt_event(room_id, round_id, stage="first_pass")
                continue
            final_status = "stopped"
            reconciliation_source = "missing_process_controller"
        if final_status:
            candidates.append(
                {
                    "roomId": room_id,
                    "roundId": round_id,
                    "workRun": dict(work_run) if isinstance(work_run, Mapping) else {},
                    "finalStatus": final_status,
                    "reconciliationSource": reconciliation_source,
                }
            )

    reconciled: list[dict[str, Any]] = []
    if candidates:
        with _CHAT_ROOM_LOCK:
            state = _store().load()
            for candidate in candidates:
                room = _find_room(state, str(candidate["roomId"]))
                round_id = str(candidate["roundId"])
                if not isinstance(room, dict) or str(room.get("activeRoundId") or "").strip() != round_id:
                    continue
                round_payload = _find_round(room, round_id)
                if not isinstance(round_payload, dict):
                    continue
                previous_status = str(round_payload.get("status") or "").strip().lower()
                if previous_status not in RUNNING_ROUND_STATUSES:
                    continue
                # A user stop can create a process control record while this
                # reconciliation is resolving its WorkRun snapshot.  Do not
                # replace that live, user-owned stop with an orphan recovery.
                # The same protection applies to a heartbeat that turned fresh
                # between the two passes: re-read the WorkRun snapshot so a
                # live round that renewed its heartbeat is exempted here too.
                if candidate["reconciliationSource"] == "missing_process_controller":
                    if _chat_room_round_has_process_control(round_id):
                        continue
                    if _chat_room_work_run_heartbeat_fresh(
                        store.load_snapshot(RUN_KIND, round_id)
                    ):
                        _record_round_heartbeat_exempt_event(
                            str(candidate["roomId"]),
                            round_id,
                            stage="reconfirm",
                        )
                        continue
                work_run = candidate["workRun"]
                final_status = str(candidate["finalStatus"])
                reconciliation_source = str(candidate["reconciliationSource"])
                finished_at = (
                    reconciled_at
                    if reconciliation_source == "missing_process_controller"
                    else str(work_run.get("finishedAt") or work_run.get("updatedAt") or reconciled_at).strip()
                )
                reason = (
                    text_for(
                        get_web_language(),
                        zh="后端进程已重启，已收口没有当前进程控制器的群聊轮次。",
                        en="The backend process restarted, so the chat room round without a current process controller was closed.",
                    )
                    if reconciliation_source == "missing_process_controller"
                    else _chat_room_reconciliation_reason(work_run, final_status=final_status)
                )
                message_count = len(list(round_payload.get("messages") or []))
                speaker_count = len(list(round_payload.get("speakerOrder") or []))
                round_payload["status"] = final_status
                round_payload["summary"] = (
                    _stopped_round_summary(reason, message_count=message_count, speaker_count=speaker_count)
                    if final_status == "stopped"
                    else reason
                )
                if final_status == "stopped" and not str(
                    round_payload.get("terminalReason") or ""
                ).strip():
                    round_payload["terminalReason"] = reason
                round_payload["updatedAt"] = finished_at
                round_payload["finishedAt"] = finished_at
                room["status"] = "ready" if final_status in {"completed", "partial", "stopped"} else "failed"
                room["activeRoundId"] = ""
                room["updatedAt"] = finished_at
                reconciled.append(
                    {
                        "room": dict(room),
                        "round": dict(round_payload),
                        "previousStatus": previous_status,
                        "finalStatus": final_status,
                        "reconciliationSource": reconciliation_source,
                        "workRunStatus": str(work_run.get("status") or "").strip(),
                        "runtimeStatus": str(work_run.get("runtimeStatus") or "").strip(),
                        "messageCount": message_count,
                        "speakerCount": speaker_count,
                        "persistWorkRun": not _terminal_chat_room_status_from_work_run(work_run),
                    }
                )
            if reconciled:
                _store().save(state)

    for item in reconciled:
        if item["persistWorkRun"]:
            work_run_payload = _chat_room_work_run_snapshot(item["room"], item["round"], status=item["finalStatus"])
            work_run_payload.update(
                {
                    "summary": str(item["round"].get("summary") or "").strip(),
                    "finishedAt": str(item["round"].get("finishedAt") or "").strip(),
                    "runtimeStatus": "orphan_reconciled",
                    "reconciliationSource": item["reconciliationSource"],
                }
            )
            store.persist_snapshot(RUN_KIND, work_run_payload, active_run_id="")
        _sync_stopped_round_to_sessions_if_needed(item["room"], item["round"])
        if (
            item["finalStatus"] == "stopped"
            and str(item["round"].get("terminalReason") or "").strip()
        ):
            from core.web.services.team_workflow import meeting_runtime

            meeting_runtime.finalize_stopped_meeting_after_chat_round(
                item["room"], item["round"]
            )
        _record_room_event(
            "round",
            "chat_room.round.orphan_reconciled",
            item["room"],
            item["round"],
            fields={
                "previousStatus": item["previousStatus"],
                "reconciliationSource": item["reconciliationSource"],
                "workRunStatus": item["workRunStatus"],
                "runtimeStatus": item["runtimeStatus"],
                "messageCount": item["messageCount"],
                "speakerCount": item["speakerCount"],
            },
            outcome=item["finalStatus"],
            level=(
                "error"
                if item["finalStatus"] == "failed"
                else "warning"
                if item["finalStatus"] in {"partial", "stopped"}
                else "info"
            ),
            lifecycle=True,
        )
    return reconciled


def _stopped_chat_room_round_detail(room_id: str, round_id: str) -> dict[str, Any] | None:
    stop_reason = _chat_room_round_stop_reason(round_id)
    if not stop_reason:
        return None
    stopped_at = utc_now_iso()
    changed = False
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        room = _find_room(state, room_id)
        if room is None:
            return None
        target_round = _find_round(room, round_id)
        if target_round is None:
            return None
        if str(target_round.get("status") or "").strip().lower() in RUNNING_ROUND_STATUSES:
            target_round["status"] = "stopped"
            target_round["summary"] = _stopped_round_summary(
                stop_reason,
                message_count=len(list(target_round.get("messages") or [])),
                speaker_count=len(list(target_round.get("speakerOrder") or [])),
            )
            target_round["terminalReason"] = stop_reason
            target_round["updatedAt"] = stopped_at
            target_round["finishedAt"] = stopped_at
            room["status"] = "ready"
            if str(room.get("activeRoundId") or "").strip() == str(round_id or "").strip():
                room["activeRoundId"] = ""
            room["updatedAt"] = stopped_at
            _store().save(state)
            changed = True
    if changed:
        _persist_chat_room_work_run(room, target_round, status="stopped", summary=str(target_round.get("summary") or ""))
        _record_room_event(
            "round",
            "chat_room.round.stopped",
            room,
            target_round,
            fields={"reason": trim_lines(stop_reason, max_lines=2)},
            outcome="stopped",
            lifecycle=True,
        )
        _sync_stopped_round_to_sessions_if_needed(room, target_round)
        _publish_chat_room_detail_snapshot(room_id)
    if str(target_round.get("terminalReason") or "").strip():
        from core.web.services.team_workflow import meeting_runtime

        meeting_runtime.finalize_stopped_meeting_after_chat_round(room, target_round)
    return _room_to_api(room)


def _persist_chat_room_work_run(
    room: dict[str, Any],
    round_payload: dict[str, Any],
    *,
    status: str,
    summary: str,
) -> None:
    round_id = str(round_payload.get("roundId") or "").strip()
    if not round_id:
        return
    normalized_status = str(status or "running").strip().lower()
    now = utc_now_iso()
    payload = {
        "runId": round_id,
        "runKind": RUN_KIND,
        "track": "dialogue",
        "roomId": str(room.get("roomId") or "").strip(),
        "roundId": round_id,
        "status": normalized_status,
        "currentPhase": normalized_status,
        "leases": list(RUN_LEASES),
        "topic": str(round_payload.get("topic") or "").strip(),
        "mode": str(round_payload.get("mode") or DEFAULT_MODE).strip(),
        "purpose": _normalize_purpose(round_payload.get("purpose") or room.get("purpose") or DEFAULT_PURPOSE),
        "summary": str(summary or round_payload.get("summary") or "").strip(),
        "startedAt": str(round_payload.get("startedAt") or now).strip(),
        "updatedAt": now,
        "heartbeatAt": str(round_payload.get("heartbeatAt") or now).strip()
        if normalized_status in RUNNING_ROUND_STATUSES
        else str(round_payload.get("heartbeatAt") or "").strip(),
        "finishedAt": str(round_payload.get("finishedAt") or "").strip()
        if normalized_status not in RUNNING_ROUND_STATUSES
        else "",
    }
    kernel_trace = _chat_room_kernel_trace_summary(round_payload)
    if kernel_trace:
        payload["kernel"] = kernel_trace
    active_run_id = round_id if normalized_status in RUNNING_ROUND_STATUSES else ""
    _work_run_store().persist_snapshot(RUN_KIND, payload, active_run_id=active_run_id)


def _record_room_event(
    phase: str,
    event_code: str,
    room: dict[str, Any],
    round_payload: dict[str, Any] | None = None,
    *,
    fields: dict[str, Any] | None = None,
    outcome: str = "observed",
    level: str = "info",
    lifecycle: bool = False,
) -> None:
    event_fields = {
        "roomId": str(room.get("roomId") or "").strip(),
        "roomTitle": str(room.get("title") or "").strip(),
        "purpose": _normalize_purpose(room.get("purpose") or DEFAULT_PURPOSE),
    }
    room_config = _safe_config(room.get("config"))
    if str(room_config.get("source") or "").strip() == "team":
        event_fields.update(
            {
                "runContext": "team_room",
                "teamId": str(room_config.get("teamId") or "").strip(),
                "teamName": str(room_config.get("teamName") or "").strip(),
                "teamPurpose": str(room_config.get("teamPurpose") or "").strip(),
            }
        )
    if round_payload:
        event_fields.update(
            {
                "roundId": str(round_payload.get("roundId") or "").strip(),
                "topicLength": len(str(round_payload.get("topic") or "")),
                "purpose": _normalize_purpose(round_payload.get("purpose") or room.get("purpose") or DEFAULT_PURPOSE),
            }
        )
        kernel_trace = _chat_room_kernel_trace_summary(round_payload)
        if kernel_trace:
            event_fields.update(
                {
                    "kernelTraceOnly": kernel_trace["traceOnly"],
                    "kernelTraceStatus": kernel_trace["status"],
                    "kernelEventId": kernel_trace["eventId"],
                    "kernelTaskId": kernel_trace["taskId"],
                    "kernelWorkRunId": kernel_trace["workRunId"],
                    "kernelOutcomeId": kernel_trace["outcomeId"],
                    "kernelOutcomeStatus": kernel_trace["outcomeStatus"],
                }
            )
    if fields:
        event_fields.update(fields)
    try:
        record_runtime_scene_event(
            "chat_room",
            phase,
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields=event_fields,
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _record_chat_room_detail_loaded(
    room_id: str,
    started_at: float,
    *,
    repaired: bool,
    found: bool,
    participant_index_cache_hit: bool,
    phase_timings: list[dict[str, Any]] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "chat_room",
            "room_detail",
            "chat_room.detail.loaded",
            message="Chat room detail loaded.",
            outcome="observed" if found else "missing",
            fields={
                "roomId": str(room_id or "").strip(),
                "elapsedMs": _elapsed_ms(started_at),
                "participantRepair": bool(repaired),
                "found": bool(found),
                "participantIndexCacheHit": bool(participant_index_cache_hit),
                "phaseTimingsMs": list(phase_timings or []),
            },
        )
    except Exception:
        return


def _append_chat_room_detail_timing(
    timings: list[dict[str, Any]],
    phase: str,
    started_at: float,
    *,
    count: int | None = None,
    cache_hit: bool | None = None,
) -> None:
    timing: dict[str, Any] = {
        "phase": trim_lines(str(phase or "unknown"), max_lines=1)[:120],
        "durationMs": _elapsed_ms(started_at),
    }
    if count is not None:
        timing["count"] = int(count)
    if cache_hit is not None:
        timing["cacheHit"] = bool(cache_hit)
    timings.append(timing)


def _record_chat_room_participant_index_prewarm(
    *,
    status: str,
    reason: str,
    elapsed_ms: int,
    cache_hit: bool = False,
    session_count: int = 0,
    active_agent_count: int = 0,
    phase_timings: list[dict[str, Any]] | None = None,
    error_type: str = "",
    error_message: str = "",
) -> None:
    normalized_status = str(status or "").strip().lower() or "observed"
    try:
        record_runtime_scene_event(
            "chat_room",
            "participant_index",
            "chat_room.participant_index.prewarm",
            message=(
                "Chat room participant index prewarm failed before the first room detail request."
                if normalized_status == "failed"
                else "Chat room participant index prewarm completed outside the room detail request path."
            ),
            level="warning" if normalized_status == "failed" else "info",
            outcome=normalized_status,
            fields={
                "status": normalized_status,
                "reason": trim_lines(reason, max_lines=1) or "startup",
                "elapsedMs": max(0, int(elapsed_ms)),
                "cacheHit": bool(cache_hit),
                "sessionCount": max(0, int(session_count)),
                "activeAgentCount": max(0, int(active_agent_count)),
                "phaseTimingsMs": list(phase_timings or []),
                "errorType": str(error_type or "").strip(),
                "errorMessage": trim_lines(error_message, max_lines=2),
            },
            lifecycle=False,
        )
    except Exception:
        return


def _fail_chat_room_round(
    room_id: str,
    round_id: str,
    room: dict[str, Any],
    round_payload: dict[str, Any],
    exc: Exception,
    *,
    lang: str,
) -> None:
    # The in-memory round control record must outlive any failed store
    # finalization.  Popping it before the durable terminal state is written
    # used to create "running without a controller" zombie rounds: the next
    # reconcile pass then force-stopped them as orphans (the backend had
    # never restarted), which restarted the same meeting from round 1 and
    # looped.  The control record is therefore cleared only after the store
    # holds a terminal state (or after the round was already terminal); a
    # store read/write failure keeps it so the finalization can be retried
    # or the heartbeat-aware reconcile path can close the round correctly.
    failed_at = utc_now_iso()
    summary = text_for(
        lang,
        zh=f"群聊后台轮次失败：{type(exc).__name__}: {exc}",
        en=f"Chat room background round failed: {type(exc).__name__}: {exc}",
    )
    already_terminal = False
    store_finalized = False
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        live_room = _find_room(state, room_id)
        if live_room is None:
            live_room = room
        target_round = _find_round(live_room, round_id) if isinstance(live_room, dict) else None
        if target_round is None:
            target_round = round_payload
        if str(target_round.get("status") or "").strip().lower() not in RUNNING_ROUND_STATUSES:
            already_terminal = True
        else:
            target_round["status"] = "failed"
            target_round["summary"] = summary
            target_round["updatedAt"] = failed_at
            target_round["finishedAt"] = failed_at
            live_room["status"] = "failed"
            live_room["activeRoundId"] = ""
            live_room["updatedAt"] = failed_at
            if _find_room(state, room_id) is not None:
                _store().save(state)
            # Either the terminal state is durable now, or the room is gone
            # from the store entirely (nothing left to converge); both make
            # it safe to drop the control record.  A save failure above
            # propagates and leaves the control record in place.
            store_finalized = True

    if already_terminal:
        _clear_chat_room_round_control(round_id)
        _publish_chat_room_detail_snapshot(room_id)
        return

    if store_finalized:
        _clear_chat_room_round_control(round_id)
    _persist_chat_room_work_run(live_room, target_round, status="failed", summary=summary)
    _sync_stopped_round_to_sessions_if_needed(live_room, target_round)
    _record_room_event(
        "round",
        "chat_room.round.background_failed",
        live_room,
        target_round,
        fields={
            "errorType": type(exc).__name__,
            "errorPreview": trim_lines(str(exc), max_lines=2),
        },
        outcome="failed",
        level="error",
        lifecycle=True,
    )
    _publish_chat_room_detail_snapshot(room_id)


def _register_chat_room_stream_subscriber(room_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _CHAT_ROOM_STREAM_SUBSCRIBERS_LOCK:
        bucket = _CHAT_ROOM_STREAM_SUBSCRIBERS.setdefault(room_id, set())
        bucket.add(subscriber)


def _unregister_chat_room_stream_subscriber(room_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _CHAT_ROOM_STREAM_SUBSCRIBERS_LOCK:
        bucket = _CHAT_ROOM_STREAM_SUBSCRIBERS.get(room_id)
        if not bucket:
            return
        bucket.discard(subscriber)
        if not bucket:
            _CHAT_ROOM_STREAM_SUBSCRIBERS.pop(room_id, None)


def _publish_chat_room_detail_snapshot(room_id: str) -> None:
    normalized_room_id = str(room_id or "").strip()
    if not normalized_room_id:
        return
    detail = get_chat_room_detail(normalized_room_id)
    if detail is None:
        return
    event = {
        "type": "chat_room_detail",
        "roomId": normalized_room_id,
        "detail": detail,
    }
    with _CHAT_ROOM_STREAM_SUBSCRIBERS_LOCK:
        subscribers = list(_CHAT_ROOM_STREAM_SUBSCRIBERS.get(normalized_room_id) or [])
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            try:
                subscriber.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                continue


def _encode_chat_room_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"


def _find_room(state: dict[str, Any], room_id: str) -> dict[str, Any] | None:
    normalized = str(room_id or "").strip()
    for item in state.get("rooms") or []:
        if isinstance(item, dict) and str(item.get("roomId") or "").strip() == normalized:
            return item
    return None


def _find_round(room: dict[str, Any], round_id: str) -> dict[str, Any] | None:
    normalized = str(round_id or "").strip()
    for item in room.get("rounds") or []:
        if isinstance(item, dict) and str(item.get("roundId") or "").strip() == normalized:
            return item
    return None


def _raise_if_room_busy(room: dict[str, Any]) -> None:
    active_round_id = str(room.get("activeRoundId") or "").strip()
    for item in room.get("rounds") or []:
        if not isinstance(item, dict):
            continue
        if active_round_id and str(item.get("roundId") or "").strip() != active_round_id:
            continue
        if str(item.get("status") or "").strip().lower() in RUNNING_ROUND_STATUSES:
            raise ChatRoomBusyError("Chat room already has an active round.")


def _participant_workspace(session_id: Any, room_id: Any, participant_id: Any) -> Path:
    normalized_session_id = str(session_id or "").strip()
    if normalized_session_id:
        return session_service._ensure_session_workspace(normalized_session_id)
    chat_rooms_root = developer_sandbox.seeded_sandbox_workspace_path(PROJECT_ROOT, "chat_rooms")
    base = (chat_rooms_root / _safe_fragment(room_id) / _safe_fragment(participant_id)).resolve()
    root = chat_rooms_root.resolve()
    if not base.is_relative_to(root):
        raise ChatRoomValidationError("Invalid chat room workspace path.")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _new_id(prefix: str, existing: set[str]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    base = f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _safe_fragment(value: Any) -> str:
    fragment = _SAFE_ID_FRAGMENT.sub("-", str(value or "").strip()).strip("._-")
    return fragment[:96] or "item"
