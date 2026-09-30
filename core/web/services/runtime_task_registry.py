"""Unified runtime task registry for cross-surface background work.

One ledger for every runtime task that outlives a single turn: CLI Agent
terminal tasks, child sessions and research project Agent tasks. The registry
owns five things that used to be implicit or missing:

1. A typed snapshot per task, persisted as one JSON file per task id.
2. Mandatory ``branchGeneration`` stamping at registration. The stamp is the
   session rewind generation captured when the task started; late completion
   notifications are fenced against it (generation mismatch -> dropped), so a
   session fork or rewind never receives a result from before the fork.
   Unlike the legacy CLI kernel behavior, a missing or unreadable session no
   longer leaves the stamp ``None`` (which disabled fencing): registration
   always writes an integer stamp and records how it was derived in
   ``branchGenerationStampSource``.
3. A ``pendingMessages`` mailbox per task (queue + drain) for messages that
   arrive while the task is still running.
4. An active-task index (``_index.json``) so watchdog-style consumers read
   only currently active tasks instead of scanning the full task directory
   every tick. A periodic full-directory reconcile heals index drift (for
   example a crash between the snapshot write and the index update, or legacy
   snapshots written before the index existed).
5. Lifecycle verbs that used to live in each surface: ``request_stop`` (who
   asked to wind a task down) and ``request_background`` (the task passed its
   wait threshold and is handed to the background once, with conservative
   refusals for stop-requested, never-started and explicitly-disabled tasks).
   The auto-background sweeper that drives ``request_background`` lives in
   ``runtime_task_auto_background``.

Cross-process safety: snapshot writes go through
``core.infrastructure.atomic_io.atomic_write_json`` (temp file + ``os.replace``
under a per-target sidecar lock), and read-modify-write sequences (status
updates, mailbox queue/drain, index membership) hold that sidecar lock for the
whole read-modify-write. In-process callers are additionally serialized by a
per-store reentrant lock. Lock ordering is always task-file lock, then index
lock; no code path acquires them in the opposite order.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock
from vibelution_storage import resolve_project_runtime_home


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_VERSION = 1
INDEX_SCHEMA_VERSION = 1
INDEX_FILE_NAME = "_index.json"
STORE_DIR_NAME = "runtime_tasks"
MAX_PENDING_MESSAGES = 200

KIND_CLI_AGENT = "cli_agent"
KIND_CHILD_SESSION = "child_session"
KIND_RESEARCH_TASK = "research_task"
TASK_KINDS = frozenset({KIND_CLI_AGENT, KIND_CHILD_SESSION, KIND_RESEARCH_TASK})

# Union of active statuses across the three surfaces:
# - cli_agent: queued / sent / running
# - child_session: idle / queued / running
# - research_task: queued / running
ACTIVE_STATUSES = frozenset({"queued", "sent", "running", "idle"})
# Union of terminal statuses across the three surfaces (cli_agent terminal
# plus research TERMINAL_STATUSES plus the child-session return outcomes).
TERMINAL_STATUSES = frozenset(
    {
        "blocked",
        "canceled",
        "cancelled",
        "closed",
        "completed",
        "dropped",
        "error",
        "exited",
        "failed",
        "incomplete",
        "stale",
        "stopped",
        "superseded",
        "timed_out",
        "timeout",
    }
)

STOP_INITIATORS = frozenset({"user", "model"})
FENCING_DECISION_ALLOWED = "allowed"
FENCING_DECISION_DROPPED = "dropped"

# Notification sealing: when the owning session turn is explicitly cancelled,
# the whole descendant subtree is sealed so late completion notifications can
# never wake a settled turn. Idempotent keep-first marks; normal completion
# never seals.
SEAL_REASON_PARENT_TURN_CANCELLED = "parent_turn_cancelled"

# Descendant cascade collection bounds: breadth comes from the active-task
# index, the depth cap plus the visited set bound the walk against registry
# corruption (a parentSessionId cycle) and runaway chains.
MAX_CASCADE_DEPTH = 8
# Outcomes of ``request_background`` (mirrors the request_stop verb): a task
# whose threshold elapsed without completing is stamped once and keeps
# running; the parent learns "already backgrounded, completion will notify".
BACKGROUND_OUTCOME_BACKGROUNDED = "backgrounded"
BACKGROUND_OUTCOME_ALREADY = "already_backgrounded"
BACKGROUND_OUTCOME_SETTLED = "settled"
BACKGROUND_OUTCOME_UNKNOWN = "unknown"
# Conservative refusals: a stop already requested makes backgrounding
# pointless, an idle child session never started, and a task may opt out
# explicitly. Refusals stamp a one-shot audit instead of retrying per tick.
BACKGROUND_REFUSAL_STOP_REQUESTED = "stop_requested"
BACKGROUND_REFUSAL_NOT_STARTED = "task_not_started"
BACKGROUND_REFUSAL_DISABLED_BY_TASK = "disabled_by_task"
BACKGROUND_REFUSAL_REASONS = frozenset(
    {
        BACKGROUND_REFUSAL_STOP_REQUESTED,
        BACKGROUND_REFUSAL_NOT_STARTED,
        BACKGROUND_REFUSAL_DISABLED_BY_TASK,
    }
)

# Sentinel for "stamp argument not provided"; distinct from an explicit None.
UNSET_BRANCH_GENERATION = object()

BranchGenerationReader = Callable[[str], int | None]

_STORE_CACHE: dict[str, RuntimeTaskStore] = {}
_STORE_CACHE_LOCK = threading.Lock()


def is_terminal_status(status: str) -> bool:
    """True when the status ends a task lifecycle on any surface."""

    return str(status or "").strip().lower() in TERMINAL_STATUSES


def is_active_status(status: str) -> bool:
    """True when the status still needs watchdog or recovery attention."""

    return str(status or "").strip().lower() in ACTIVE_STATUSES


def backgrounding_refusal_reason(state: dict[str, Any]) -> str:
    """Conservative auto-background guard for one task snapshot.

    Refuses when:

    - a stop was already requested (user/model): the task is being wound
      down, backgrounding it would only confuse the stop chain;
    - the task never started (an idle child session created with
      ``auto_start=False``): there is nothing running to hand to the
      background;
    - the task explicitly opted out (``backgroundingDisabled``), the escape
      hatch for borrowed/synchronous-style executions that must stay under
      their caller's lifecycle.
    """

    snapshot = normalize_snapshot(state)
    if str(snapshot.get("stopInitiator") or "") in STOP_INITIATORS:
        return BACKGROUND_REFUSAL_STOP_REQUESTED
    if bool(snapshot.get("backgroundingDisabled")):
        return BACKGROUND_REFUSAL_DISABLED_BY_TASK
    if str(snapshot.get("status") or "").strip().lower() == "idle":
        return BACKGROUND_REFUSAL_NOT_STARTED
    return ""


def new_snapshot(
    *,
    kind: str,
    task_id: str,
    status: str,
    source_session_id: str = "",
    parent_session_id: str = "",
    branch_generation: Any = UNSET_BRANCH_GENERATION,
    label: str = "",
    output: str = "",
    backgrounding_disabled: bool = False,
) -> dict[str, Any]:
    """Build a registry snapshot envelope for one new task."""

    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind not in TASK_KINDS:
        raise ValueError(f"Unknown runtime task kind: {normalized_kind or '(empty)'}")
    snapshot: dict[str, Any] = {
        "registryVersion": REGISTRY_VERSION,
        "kind": normalized_kind,
        "taskId": str(task_id or "").strip(),
        "status": str(status or "").strip().lower(),
        "branchGeneration": None,
        "branchGenerationStampSource": "",
        "parentSessionId": str(parent_session_id or "").strip(),
        "sourceSessionId": str(source_session_id or "").strip(),
        "stopInitiator": None,
        "pendingMessages": [],
        "notificationSealed": False,
        "notificationSealedAt": "",
        "notificationSealedReason": "",
        "notificationSealedByTurnId": "",
        "cascadeStop": None,
        "lastNotificationDrop": None,
        "output": str(output or ""),
        "label": str(label or "").strip(),
        "resultSummary": "",
        "startedAt": "",
        "createdAt": _now_iso(),
        "updatedAt": _now_iso(),
        "completedAt": "",
        # Escape hatch for borrowed/synchronous-style executions that must
        # stay under their caller's lifecycle and never move to the
        # background (ZCode's borrowed-foreground-agent rule).
        "backgroundingDisabled": bool(backgrounding_disabled),
    }
    if branch_generation is not UNSET_BRANCH_GENERATION:
        snapshot["branchGeneration"] = _coerce_generation(branch_generation)
        snapshot["branchGenerationStampSource"] = (
            "explicit" if snapshot["branchGeneration"] is not None else ""
        )
    return snapshot


def normalize_snapshot(payload: Any) -> dict[str, Any]:
    """Return a defensive copy with the registry envelope keys normalized.

    Legacy CLI kernel snapshots (written before the registry existed) carry no
    ``kind``; they are adopted as ``cli_agent`` rows. Their absent
    ``branchGeneration`` stays unstamped so completion fencing fails open for
    in-flight legacy work; only fresh registration stamps.
    """

    if not isinstance(payload, dict):
        return {}
    state = dict(payload)
    kind = str(state.get("kind") or "").strip().lower()
    state["kind"] = kind if kind in TASK_KINDS else KIND_CLI_AGENT
    state["taskId"] = str(state.get("taskId") or "").strip()
    state["status"] = str(state.get("status") or "").strip().lower()
    state["parentSessionId"] = str(state.get("parentSessionId") or "").strip()
    state["sourceSessionId"] = str(state.get("sourceSessionId") or "").strip()
    stop_initiator = state.get("stopInitiator")
    state["stopInitiator"] = (
        str(stop_initiator) if str(stop_initiator or "") in STOP_INITIATORS else None
    )
    state["notificationSealed"] = bool(state.get("notificationSealed"))
    state["notificationSealedAt"] = str(state.get("notificationSealedAt") or "")
    state["notificationSealedReason"] = str(state.get("notificationSealedReason") or "")
    state["notificationSealedByTurnId"] = str(state.get("notificationSealedByTurnId") or "")
    state["cascadeStop"] = (
        dict(state.get("cascadeStop")) if isinstance(state.get("cascadeStop"), dict) else None
    )
    state["lastNotificationDrop"] = (
        dict(state.get("lastNotificationDrop"))
        if isinstance(state.get("lastNotificationDrop"), dict)
        else None
    )
    messages = state.get("pendingMessages")
    state["pendingMessages"] = [
        dict(item) for item in messages if isinstance(item, dict)
    ] if isinstance(messages, list) else []
    if not isinstance(state.get("branchGeneration"), int) or isinstance(
        state.get("branchGeneration"), bool
    ):
        raw = state.get("branchGeneration")
        state["branchGeneration"] = _coerce_generation(raw)
        if state["branchGeneration"] is None:
            state["branchGenerationStampSource"] = str(
                state.get("branchGenerationStampSource") or ""
            )
    state["branchGenerationStampSource"] = str(
        state.get("branchGenerationStampSource") or ""
    )
    state["backgroundingDisabled"] = bool(state.get("backgroundingDisabled"))
    return state


def default_store() -> RuntimeTaskStore:
    """Store for the shared runtime_tasks directory of the active project."""

    return store_for(str(_default_store_root()))


def store_for(root: str | Path) -> RuntimeTaskStore:
    """Return the cached store for one root (tests may point at tmp roots)."""

    key = str(root)
    with _STORE_CACHE_LOCK:
        store = _STORE_CACHE.get(key)
        if store is None:
            store = RuntimeTaskStore(key)
            _STORE_CACHE[key] = store
        return store


class RuntimeTaskStore:
    """File-backed registry store: one JSON snapshot per task plus an index."""

    def __init__(
        self,
        root: str | Path,
        *,
        branch_generation_reader: BranchGenerationReader | None = None,
    ) -> None:
        self._root = Path(root)
        self._lock = threading.RLock()
        self._terminal_condition = threading.Condition(self._lock)
        self._branch_generation_reader: BranchGenerationReader = (
            branch_generation_reader or _session_branch_generation_reader
        )

    @property
    def root(self) -> Path:
        return self._root

    # -- paths -----------------------------------------------------------

    def task_state_path(self, task_id: str) -> Path:
        return self._root / f"{_safe_filename(task_id)}.json"

    @property
    def index_path(self) -> Path:
        return self._root / INDEX_FILE_NAME

    # -- registration and lifecycle --------------------------------------

    def register_task(
        self,
        snapshot: dict[str, Any],
        *,
        branch_generation: Any = UNSET_BRANCH_GENERATION,
    ) -> dict[str, Any]:
        """Register (or idempotently re-register) one task, stamping fencing."""

        state = normalize_snapshot(snapshot)
        task_id = str(state.get("taskId") or "").strip()
        if not task_id:
            raise ValueError("Runtime task snapshot requires a non-empty taskId.")
        self._stamp_branch_generation(state, branch_generation)
        if not str(state.get("startedAt") or "").strip():
            state["startedAt"] = str(state.get("createdAt") or "").strip() or _now_iso()
        state["updatedAt"] = _now_iso()
        self.save_state(state)
        # Lazy hook: when the auto-background threshold is configured, make
        # sure the sweeper daemon is running. A disabled threshold turns this
        # into a strict no-op (no thread, no poke); failures never block
        # registration.
        try:
            from . import runtime_task_auto_background

            if runtime_task_auto_background.resolve_threshold_seconds() is not None:
                runtime_task_auto_background.ensure_auto_background_sweeper()
        except Exception:
            pass
        return state

    def save_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Persist one snapshot and sync active-index membership."""

        normalized = normalize_snapshot(state)
        task_id = str(normalized.get("taskId") or "").strip()
        if not task_id:
            raise ValueError("Runtime task snapshot requires a non-empty taskId.")
        with self._lock:
            atomic_write_json(self.task_state_path(task_id), normalized)
            self._sync_index_membership(
                task_id, active=is_active_status(str(normalized.get("status") or ""))
            )
            if is_terminal_status(str(normalized.get("status") or "")):
                self._terminal_condition.notify_all()
        return normalized

    def update_task(
        self,
        task_id: str,
        mutator: Callable[[dict[str, Any]], dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        """Read-modify-write one snapshot; returns None when it does not exist."""

        normalized_id = str(task_id or "").strip()
        if not normalized_id:
            return None
        with self._lock, cross_process_file_lock(self.task_state_path(normalized_id)):
            state = self._load_state_unlocked(normalized_id)
            if not state:
                return None
            mutated = mutator(dict(state))
            if mutated is None:
                return state
            mutated = normalize_snapshot(mutated)
            mutated["taskId"] = normalized_id
            return self.save_state(mutated)

    def mark_task_terminal(
        self,
        task_id: str,
        *,
        status: str,
        stop_initiator: str | None = None,
        reason: str = "",
    ) -> dict[str, Any] | None:
        """Move one registered task to a terminal status (idempotent)."""

        normalized_status = str(status or "").strip().lower()
        if normalized_status not in TERMINAL_STATUSES:
            raise ValueError(f"Status is not terminal: {normalized_status or '(empty)'}")
        if stop_initiator is not None and str(stop_initiator) not in STOP_INITIATORS:
            raise ValueError(f"Unknown stop initiator: {stop_initiator}")

        def _mutate(state: dict[str, Any]) -> dict[str, Any]:
            now = _now_iso()
            state["status"] = normalized_status
            state["completedAt"] = now
            state["updatedAt"] = now
            if reason:
                state["terminalReason"] = str(reason)
            if stop_initiator is not None:
                state["stopInitiator"] = str(stop_initiator)
            return state

        return self.update_task(task_id, _mutate)

    def request_stop(self, task_id: str, initiator: str) -> dict[str, Any] | None:
        """Record who asked to stop an active task ("user" or "model").

        Returns None for unknown tasks and for tasks already terminal
        (a settled task is never re-armed by a late stop request).
        """

        normalized = str(initiator or "").strip().lower()
        if normalized not in STOP_INITIATORS:
            raise ValueError(f"Unknown stop initiator: {normalized or '(empty)'}")
        current = self.load_state(task_id)
        if not current or is_terminal_status(str(current.get("status") or "")):
            return None

        def _mutate(state: dict[str, Any]) -> dict[str, Any] | None:
            if is_terminal_status(str(state.get("status") or "")):
                return None
            state["stopInitiator"] = normalized
            state["stopRequestedAt"] = _now_iso()
            state["updatedAt"] = state["stopRequestedAt"]
            return state

        return self.update_task(task_id, _mutate)

    def seal_and_request_stop(
        self,
        task_id: str,
        *,
        reason: str,
        turn_id: str = "",
        cascaded_from: str = "",
        initiator: str = "user",
    ) -> dict[str, Any] | None:
        """Seal completion notifications and record stop intent in one RMW.

        Used by the descendant cascade when an owning session turn is
        explicitly cancelled. The seal is keep-first idempotent: re-sealing
        keeps the original seal timestamp and reason so the audit trail shows
        the first cause. Stop intent follows the same rules as
        :meth:`request_stop` (terminal tasks are never re-armed), but the seal
        itself still lands on a terminal task: a settled task may still emit
        late delivery attempts that must be dropped.
        """

        normalized = str(initiator or "").strip().lower()
        if normalized not in STOP_INITIATORS:
            raise ValueError(f"Unknown stop initiator: {normalized or '(empty)'}")
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ValueError("Notification sealing requires a non-empty reason.")

        def _mutate(state: dict[str, Any]) -> dict[str, Any]:
            now = _now_iso()
            if not state.get("notificationSealed"):
                state["notificationSealed"] = True
                state["notificationSealedAt"] = now
                state["notificationSealedReason"] = normalized_reason
                state["notificationSealedByTurnId"] = str(turn_id or "").strip()
            if cascaded_from and not state.get("cascadeStop"):
                state["cascadeStop"] = {
                    "cascadedFrom": str(cascaded_from).strip(),
                    "cascadedAt": now,
                    "reason": normalized_reason,
                    "turnId": str(turn_id or "").strip(),
                }
            if not is_terminal_status(str(state.get("status") or "")):
                state["stopInitiator"] = normalized
                state["stopRequestedAt"] = now
                state["updatedAt"] = now
            else:
                state["updatedAt"] = now
            return state

        return self.update_task(task_id, _mutate)

    def is_notification_sealed(self, task_id: str) -> bool:
        """True when late completion notifications for the task are sealed."""

        state = self.load_state(task_id)
        return bool(state.get("notificationSealed"))

    def collect_cascade_targets(
        self, session_id: str, *, max_depth: int = MAX_CASCADE_DEPTH
    ) -> list[dict[str, Any]]:
        """Collect the active descendant task subtree of one session.

        Level 0 holds tasks whose ``parentSessionId`` equals ``session_id``;
        every ``child_session`` task recurses into its ``taskId`` as the next
        session id, so grandchildren spawned by a child session are covered.
        The walk is bounded by the visited set (cycles cannot loop it) and by
        ``max_depth``. Returns snapshots in breadth-first order, annotated
        in-memory only with ``cascadeDepth``.
        """

        root = str(session_id or "").strip()
        if not root or max_depth <= 0:
            return []
        by_parent: dict[str, list[dict[str, Any]]] = {}
        for state in self.active_task_states():
            parent = str(state.get("parentSessionId") or "").strip()
            if not parent:
                continue
            by_parent.setdefault(parent, []).append(state)
        targets: list[dict[str, Any]] = []
        visited_tasks: set[str] = set()
        visited_sessions = {root}
        frontier = [root]
        for depth in range(max_depth):
            next_frontier: list[str] = []
            for current in frontier:
                for state in by_parent.get(current, []):
                    task_id = str(state.get("taskId") or "").strip()
                    if not task_id or task_id in visited_tasks:
                        continue
                    visited_tasks.add(task_id)
                    annotated = dict(state)
                    annotated["cascadeDepth"] = depth
                    targets.append(annotated)
                    if str(state.get("kind") or "").strip() == KIND_CHILD_SESSION:
                        if task_id not in visited_sessions:
                            visited_sessions.add(task_id)
                            next_frontier.append(task_id)
            frontier = next_frontier
            if not frontier:
                break
        return targets
    def request_background(
        self, task_id: str, *, reason: str = "auto_background_timeout"
    ) -> str:
        """Stamp one active task as backgrounded (idempotent, once per task).

        The task itself keeps running unchanged: stopInitiator, terminal
        statuses and the completion notification chain are untouched. A task
        that already carries the stamp, already settled, or is conservatively
        refused (see ``backgrounding_refusal_reason``) is left alone; refusals
        write a one-shot audit so a per-tick sweeper does not rewrite the
        snapshot every second.

        Returns one of the ``BACKGROUND_OUTCOME_*`` strings.
        """

        normalized_reason = str(reason or "").strip() or "auto_background_timeout"
        outcome = BACKGROUND_OUTCOME_UNKNOWN

        def _mutate(state: dict[str, Any]) -> dict[str, Any] | None:
            nonlocal outcome
            if is_terminal_status(str(state.get("status") or "")):
                outcome = BACKGROUND_OUTCOME_SETTLED
                return None
            refusal = backgrounding_refusal_reason(state)
            if refusal:
                if str(state.get("backgroundingRefusedReason") or "") != refusal:
                    now = _now_iso()
                    state["backgroundingRefusedAt"] = now
                    state["backgroundingRefusedReason"] = refusal
                    state["updatedAt"] = now
                    outcome = f"refused:{refusal}"
                    return state
                outcome = f"refused:{refusal}"
                return None
            if state.get("backgroundedAt"):
                outcome = BACKGROUND_OUTCOME_ALREADY
                return None
            now = _now_iso()
            state["backgroundedAt"] = now
            state["backgroundedReason"] = normalized_reason
            state["updatedAt"] = now
            outcome = BACKGROUND_OUTCOME_BACKGROUNDED
            return state

        current = self.load_state(task_id)
        if not current:
            return BACKGROUND_OUTCOME_UNKNOWN
        self.update_task(task_id, _mutate)
        return outcome

    # -- reads -----------------------------------------------------------

    def load_state(self, task_id: str) -> dict[str, Any]:
        normalized_id = str(task_id or "").strip()
        if not normalized_id:
            return {}
        with self._lock:
            return self._load_state_unlocked(normalized_id)

    # Kept as a symmetric alias for kernel-style call sites.
    get_task = load_state

    def active_task_ids(self) -> list[str]:
        """Active task ids according to the index (no directory scan)."""

        return list(self._read_index_task_ids())

    def active_task_states(
        self,
        *,
        mtime_cache: dict[str, tuple[float, dict[str, Any]]] | None = None,
    ) -> list[dict[str, Any]]:
        """Load snapshots for index-listed active tasks only.

        ``mtime_cache`` maps snapshot file path -> (mtime, parsed state); when
        the file mtime is unchanged the cached parse is reused, so a per-second
        watchdog never re-parses unchanged files and never touches finished
        tasks at all.
        """

        task_ids = self.active_task_ids()
        states: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for task_id in task_ids:
            path = self.task_state_path(task_id)
            key = str(path)
            seen_keys.add(key)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime_cache is not None:
                cached = mtime_cache.get(key)
                if cached is not None and cached[0] == mtime:
                    states.append(cached[1])
                    continue
            state = self.load_state(task_id)
            if not state:
                continue
            if mtime_cache is not None:
                mtime_cache[key] = (mtime, state)
            states.append(state)
        if mtime_cache is not None:
            for stale_key in list(mtime_cache.keys()):
                if stale_key not in seen_keys:
                    mtime_cache.pop(stale_key, None)
        return states

    def iter_task_states(self) -> list[dict[str, Any]]:
        """Full-directory scan (reconcile and fallback path, not per-tick)."""

        if not self._root.exists():
            return []
        states: list[dict[str, Any]] = []
        for path in sorted(self._root.glob("*.json")):
            if path.name.startswith("_") or path.name.endswith(".lock"):
                continue
            state = self._read_snapshot_file(path)
            if state:
                states.append(state)
        return states

    def reconcile_index(self) -> list[dict[str, Any]]:
        """Rebuild the active index from a full directory scan; heal drift."""

        states = self.iter_task_states()
        active_ids = [
            str(state.get("taskId") or "")
            for state in states
            if is_active_status(str(state.get("status") or ""))
            and str(state.get("taskId") or "").strip()
        ]
        with self._lock, cross_process_file_lock(self.index_path):
            atomic_write_json(
                self.index_path,
                {"schemaVersion": INDEX_SCHEMA_VERSION, "activeTaskIds": active_ids},
            )
        return [state for state in states if str(state.get("taskId")) in set(active_ids)]

    def has_active_tasks(self) -> bool:
        return bool(self.active_task_ids())

    # -- completion fencing ----------------------------------------------

    def evaluate_completion_fencing(
        self, task: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        """Decide whether a completion notification may still be delivered.

        Returns ``(allowed, audit_fields)``. Rules:

        - Snapshot stamped (the only state fresh registration produces):
          read the source session's current generation; mismatch -> dropped.
          A session that vanished reads as generation 0.
        - Reader hard-fails or legacy snapshot is unstamped: fail open and say
          so in the audit fields (delivery availability beats fencing when the
          fence itself cannot be evaluated).
        """

        state = normalize_snapshot(task)
        session_id = str(state.get("sourceSessionId") or "").strip()
        audit: dict[str, Any] = {
            "fencingAuditedAt": _now_iso(),
            "fencingTaskBranchGeneration": None,
            "fencingCurrentBranchGeneration": None,
            "fencingDecision": FENCING_DECISION_ALLOWED,
            "fencingReason": "",
        }
        stamped = _coerce_generation(state.get("branchGeneration"))
        if stamped is None:
            audit["fencingReason"] = "legacy_unstamped_fail_open"
            return True, audit
        audit["fencingTaskBranchGeneration"] = stamped
        if not session_id:
            audit["fencingReason"] = "no_target_session"
            return True, audit
        try:
            value = self._branch_generation_reader(session_id)
        except Exception:
            value = None
        if value is None:
            audit["fencingReason"] = "generation_unreadable_fail_open"
            return True, audit
        current = max(0, int(value))
        audit["fencingCurrentBranchGeneration"] = current
        if current != stamped:
            audit["fencingDecision"] = FENCING_DECISION_DROPPED
            audit["fencingReason"] = "stale_branch_generation"
            return False, audit
        audit["fencingReason"] = "generation_match"
        return True, audit

    def apply_completion_fencing(self, task: dict[str, Any]) -> bool:
        """Evaluate fencing and write the audit fields into the snapshot dict."""

        allowed, audit = self.evaluate_completion_fencing(task)
        task.update(audit)
        return allowed

    # -- mailbox ---------------------------------------------------------

    def queue_message(
        self,
        task_id: str,
        *,
        message: str,
        message_id: str = "",
        origin: str = "",
    ) -> dict[str, Any] | None:
        """Append one pending message to the task mailbox (bounded)."""

        text = str(message or "")
        if not text.strip():
            raise ValueError("Runtime task mailbox message must not be empty.")

        def _mutate(state: dict[str, Any]) -> dict[str, Any]:
            pending = list(state.get("pendingMessages") or [])
            entry: dict[str, Any] = {
                "id": str(message_id or "").strip() or f"rtm-{uuid.uuid4().hex[:16]}",
                "message": text,
                "origin": str(origin or "").strip(),
                "queuedAt": _now_iso(),
            }
            pending.append(entry)
            if len(pending) > MAX_PENDING_MESSAGES:
                pending = pending[-MAX_PENDING_MESSAGES:]
            state["pendingMessages"] = pending
            state["updatedAt"] = entry["queuedAt"]
            return state

        return self.update_task(task_id, _mutate)

    def drain_messages(self, task_id: str) -> list[dict[str, Any]]:
        """Return and clear the task mailbox in queue order."""

        drained: list[dict[str, Any]] = []

        def _mutate(state: dict[str, Any]) -> dict[str, Any]:
            drained.extend(list(state.get("pendingMessages") or []))
            state["pendingMessages"] = []
            state["updatedAt"] = _now_iso()
            return state

        self.update_task(task_id, _mutate)
        return drained

    # -- waiting ---------------------------------------------------------

    def wait_for_terminal(
        self, task_id: str, *, timeout_seconds: float = 5.0
    ) -> dict[str, Any] | None:
        """Wait (in-process) until the task reaches a terminal status."""

        deadline = time.monotonic() + max(0.0, timeout_seconds)
        with self._lock:
            while True:
                state = self.load_state(task_id)
                if state and is_terminal_status(str(state.get("status") or "")):
                    return state
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return state or None
                self._terminal_condition.wait(remaining)

    # -- internals -------------------------------------------------------

    def _stamp_branch_generation(
        self, state: dict[str, Any], explicit: Any
    ) -> None:
        if explicit is not UNSET_BRANCH_GENERATION and explicit is not None:
            value = _coerce_generation(explicit)
            if value is not None:
                state["branchGeneration"] = value
                state["branchGenerationStampSource"] = "explicit"
                return
        if isinstance(state.get("branchGeneration"), int) and not isinstance(
            state.get("branchGeneration"), bool
        ) and str(state.get("branchGenerationStampSource") or "").strip():
            return  # already stamped; registration is idempotent
        session_id = str(state.get("sourceSessionId") or "").strip()
        value: int | None = None
        if session_id:
            try:
                value = self._branch_generation_reader(session_id)
            except Exception:
                value = None
            if value is not None:
                value = max(0, int(value))
        if value is None:
            # Mandatory stamp: a missing session fences as generation 0, an
            # unreadable one defaults to 0 too. The escape hatch is gone.
            state["branchGeneration"] = 0
            state["branchGenerationStampSource"] = (
                "no_session_default_zero" if not session_id else "reader_error_default_zero"
            )
            return
        state["branchGeneration"] = value
        state["branchGenerationStampSource"] = "session"

    def _load_state_unlocked(self, task_id: str) -> dict[str, Any]:
        return self._read_snapshot_file(self.task_state_path(task_id))

    def _read_snapshot_file(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return normalize_snapshot(payload) if isinstance(payload, dict) else {}

    def _read_index_task_ids(self) -> list[str]:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(payload, dict):
            return []
        raw_ids = payload.get("activeTaskIds")
        if not isinstance(raw_ids, list):
            return []
        return list(dict.fromkeys(str(item).strip() for item in raw_ids if str(item).strip()))

    def _sync_index_membership(self, task_id: str, *, active: bool) -> None:
        with cross_process_file_lock(self.index_path):
            ids = self._read_index_task_ids()
            changed = False
            if active and task_id not in ids:
                ids.append(task_id)
                changed = True
            elif not active and task_id in ids:
                ids.remove(task_id)
                changed = True
            if changed:
                atomic_write_json(
                    self.index_path,
                    {"schemaVersion": INDEX_SCHEMA_VERSION, "activeTaskIds": ids},
                )


def _default_store_root() -> Path:
    project_root = ""
    try:
        from . import session_service

        project_root = str(getattr(session_service, "PROJECT_ROOT", "") or "")
    except Exception:
        project_root = ""
    if not project_root:
        project_root = str(PROJECT_ROOT)
    return resolve_project_runtime_home(project_root) / STORE_DIR_NAME


def _session_branch_generation_reader(session_id: str) -> int | None:
    """Current rewind generation of one session; None when unreadable."""

    normalized = str(session_id or "").strip()
    if not normalized:
        return 0
    try:
        from . import session_service

        return max(0, int(session_service.session_branch_generation(normalized)))
    except Exception:
        return None


def _coerce_generation(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _safe_filename(value: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "")
    )
    return cleaned[:120] or "task"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
