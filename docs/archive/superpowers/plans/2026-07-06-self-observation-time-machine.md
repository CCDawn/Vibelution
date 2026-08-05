# Self-Observation Time Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** active-plan

**Owner:** Vibelution self-evolution runtime lane

**Claim / Branch / Worktree:** `codex/self-observation-time-machine-design` in `C:\Users\17533\Desktop\Vibelution-worktrees\self-observation-time-machine-design`

**Scope:** Upgrade existing self-observation mode into a durable time-machine run loop with effective runtime accounting, restart recovery, user guidance, compression markers, conversation-chain preservation, and UI metrics.

**Supersedes:** none

**Implementation link:** `docs/superpowers/specs/2026-07-06-self-observation-time-machine-design.md`

**Validation:** Plan self-review, placeholder scan, `git diff --check`

**Close condition:** All tasks pass their focused backend/frontend checks, final branch is committed, and Launcher refresh is reported as required before runtime UI verification.

**Goal:** Build a long-running 0-tool self-observation time-state regression mode that continues the same run across compression, guidance, and runtime interruption until the requested effective runtime is complete.

**Architecture:** Keep the existing `/api/evolution/self/observation-runs` surface and current no-tool observation adapter, but promote observation state from in-memory snapshots to a durable ledger persisted through `core.runtime_manager.evolution_store` with run kind `self_observation`. The scheduler advances one finite tick at a time, accumulates only confirmed tick runtime, records compression/resume/guidance as bounded ledger events, and derives all UI metrics from the persisted projection.

**Tech Stack:** Python service logic in `core/web/services/self_evolution_control_service.py`, shared work-run persistence in `core/runtime_manager/evolution_store.py`, FastAPI/Pydantic routes in `core/web/routes/evolution.py`, React/TypeScript UI in `web/src/routes/SelfEvolutionTrack.tsx`, API DTOs in `web/src/api/types.ts`, pytest, Vitest, and `npm --prefix web run build`.

## Global Constraints

- First version keeps 0 tools.
- Agent does not read files, write files, run commands, search, create worktrees, modify code, or generate merge candidates.
- Runtime duration is counted by `effectiveRunTime`; page close, crash, pause, backend restart, Launcher restart, Vibelution restart, and machine shutdown waiting time do not consume the budget.
- Page close, backend process restart, Launcher/Vibelution restart, and later Vibelution startup after machine restart must identify unfinished runs and continue them.
- The start surface shows and edits the full observation prompt; `goal` is compatibility/summary data, not the user's primary editing surface.
- User input during the run is a guidance event in the same run and does not reset the task.
- Context compression writes visible compression events and continues the same run.
- This stage does not generate a new observation analysis report, write project-memory records, or summarize the experiment into durable memory; it preserves the full conversation/event chain for the next stage to analyze.
- Do not edit `VERSION`, `CHANGELOG.md`, root `config.toml`, `config.example.toml`, operator config, `.docs/project-memory/**`, or `PROJECT_MEMORY.html` in this implementation branch.
- `web/src/api/types.ts` is a shared hot file; the implementation round must take a narrow project-memory guard claim before editing it unless the user explicitly skips guard use in that later round.
- Launcher refresh is not needed for this plan document. The implementation changes backend API, runtime scheduling, and frontend build inputs, so refresh is required before real runtime UI verification.
- Reuse-first rule: every implementation task must inspect and reuse project-native services, stores, UI components, and test helpers before adding new abstractions.
- Hard-part search rule: if durable scheduling, state-machine enforcement, recovery, compression, or timeline rendering cannot be implemented cleanly with local parts, pause that task and do read-only component research before coding further.
- Dependency rule: no external dependency may be installed or added to lockfiles unless a new plan update records the candidate, license, integration cost, validation strategy, and explicit user approval.

---

## File Structure

- Modify `core/runtime_manager/evolution_store.py`: include `self_observation` in evolution summary and cleanup helpers so tests and runtime scans handle the new durable run kind.
- Modify `core/web/services/self_evolution_control_service.py`: add durable observation ledger helpers, event schema, effective runtime accounting, tick loop, recovery scanner, guidance handling, compression marker handling, conversation/turn link preservation, and runtime-scene event records.
- Modify `core/web/routes/evolution.py`: extend observation start payload, add default prompt route, add active-run read route, add guidance route, and allow pause/resume/force_resume actions.
- Modify `web/src/api/types.ts`: extend observation DTOs with prompt, time-machine metrics, event fields, guidance/compression/resume counters, and request payloads.
- Modify `web/src/routes/EvolutionRoute.tsx`: wire guidance mutation and pass new observation metrics/action props into `SelfEvolutionTrack`.
- Modify `web/src/routes/SelfEvolutionTrack.tsx`: add prompt editor, effective time metrics, tick/compression/resume/guidance counters, guidance input, marker rendering, and action states.
- Modify `web/src/routes/SelfEvolutionTrack.styles.ts`: add compact operational styles for prompt editor, time-machine metrics, and guidance controls.
- Modify `web/src/routes/SelfEvolutionTrack.static.test.ts`: protect the no-tool UI boundary, prompt editor contract, time-machine metrics, and marker rendering source contracts.
- Modify `tests/test_self_evolution_control_service.py`: service-level tests for durable ledger, effective runtime, tick loop, recovery, guidance, compression marker, boundary violation, and conversation-chain preservation without a generated analysis report.
- Modify `tests/test_web_evolution_routes.py`: API tests for start/read/active/events/guidance/action behavior.

## Source Of Truth

| Fact | Canonical source | Writer | Readers / derived surfaces | Refresh or invalidation | Old source cleanup |
| --- | --- | --- | --- | --- | --- |
| Observation run existence | `evolution_store` kind `self_observation` snapshot | `self_evolution_control_service` | active run API, workspace snapshot, UI, recovery scanner | persist after every ledger event | in-memory `_OBSERVATION_RUNS` becomes cache only |
| Current status | event projection in persisted snapshot | scheduler/action/recovery helpers | UI status, actions, scheduler | append state event then persist | frontend local state never owns status |
| Effective runtime | `effectiveRunSeconds` and `tick_started`/`tick_completed` events | tick scheduler | completion gate, UI progress, future analyzer | tick completion or safe interruption | wall clock is audit only |
| User-confirmed observation prompt | persisted run snapshot `prompt` | start route / prompt editor | tick prompt builder, UI prompt preview, future analyzer | persisted at run start; later ticks append runtime context | `goal` is a compatibility title/summary, not the primary input |
| User guidance | bounded `guidanceQueue` and `user_guidance_*` events | guidance route | next tick prompt, UI markers, future analyzer | consumed event clears pending item | guidance never overwrites the confirmed prompt |
| Compression result | `compression_*` events plus bounded checkpoint summary fields | observation service compression adapter | tick prompt, UI marker, future analyzer | compression event persists before next tick | no assistant bubble is used as compression marker |
| Recovery count | `runtime_interrupted`, `resume_needed`, `force_resume_*` events | startup/API scanner | UI, future analyzer, scheduler | recovery scan persists transition | process memory counter is not authoritative |
| Full conversation chain | conversation session detail plus persisted `conversationSessionId`, `turnId`, `messages`, and event refs | session service and observation service | `ConversationView`, `LazyConversationView`, future analyzer | each tick preserves session/turn refs before terminal transition | compatibility `report` field is not the source of truth |

---

## Reuse Research And Component Decisions

Current project reuse is the default path. External packages are candidates only when a local component cannot satisfy the behavior without becoming brittle.

| Capability | Decision | Reusable component or candidate | Evidence | Implementation boundary |
| --- | --- | --- | --- | --- |
| Durable observation run ledger | REUSE | `core.runtime_manager.evolution_store` and `core.runtime_manager.work_run_store.WorkRunStore` | Existing store persists per-kind snapshots, active/latest indexes, corrupt JSON quarantine, and runtime-scene lifecycle events. Tests already cover active/latest tracking and snapshot rejection in `tests/test_work_run_store.py`. | Add a `self_observation` kind; do not create a parallel JSON ledger. |
| Runtime-scene evidence | REUSE | `core.web.services.runtime_scene_service.record_runtime_scene_event` and WorkRunStore lifecycle events | Existing self-evolution and work-run paths already record bounded lifecycle evidence. | Add bounded `self_observation.*` event codes; do not log prompts, full outputs, or provider payloads. |
| Conversation execution | REUSE | `create_supervised_agent_session`, `submit_session_message`, `get_session_detail`, `get_session_turn_completion_snapshot`, `request_stop_session_turn` | Current observation mode already routes through supervised session creation and `message_source="self_observation"`. | Keep `_run_observation_session` as the adapter; do not add a direct provider client. |
| Default observation prompt | REUSE | `build_self_observation_prompt(goal, duration_seconds)` | Current backend already owns the 0-tool observation prompt template and tests assert the no-tool contract. | Add a small default-prompt route that returns this template for the UI prompt editor; do not maintain a second long-lived frontend prompt template. |
| Context compression | ADAPT | `core.chat.context_compression_ledger.append_context_compression_checkpoint`, `append_context_compression_attempt`, `context_compression_projection`, `latest_context_compression_checkpoint`; `core.chat.turn_journal` marker metadata | Existing compression ledger emits checkpoint/attempt events and projection fields such as `compressionCount`. | Observation run records marker summaries that point at conversation compression facts; it does not invent a second compression source. |
| Session interruption recovery | ADAPT | `session_service._repair_stale_running_conversation`, `_release_stale_chat_turn_work_run`, existing self-evolution restart/requeue patterns | Local code already repairs stale running conversations and requeues self-evolution restart intents. | Reuse the detection shape; keep observation-specific effective runtime accounting in observation ledger. |
| Tick scheduling | REUSE for v1; REFERENCE_ONLY for external packages | Local `_RUN_EXECUTOR`, persisted run snapshot, session turn polling. External references: [APScheduler docs](https://apscheduler.readthedocs.io/) and [APScheduler user guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html). | APScheduler supports triggers/job stores/executors/schedulers and database-backed jobs, but this feature needs sequential, single-run ticks tied to the existing session/runtime manager. | Do not add APScheduler in v1. Revisit only if multiple concurrent observation jobs or persistent scheduled jobs become required. |
| Durable workflow engine | REFERENCE_ONLY | [Temporal Python SDK docs](https://docs.temporal.io/develop/python), [Temporal Python timers](https://docs.temporal.io/develop/python/workflows/timers), [Prefect docs](https://docs.prefect.io/v3/get-started) | Temporal durable timers can resume after downtime; Prefect provides workflow orchestration and state tracking. Both introduce a separate orchestration runtime and deployment model. | Do not add Temporal or Prefect in v1. Revisit only if Vibelution adopts a dedicated durable workflow service. |
| State-machine library | REFERENCE_ONLY | [pytransitions/transitions](https://github.com/pytransitions/transitions), [python-statemachine docs](https://python-statemachine.readthedocs.io/en/latest/transitions.html) | Libraries provide explicit transition models, but the current state machine is small and must persist through project-owned ledger events. | Keep explicit status helper functions in-house for v1. If transition guards become hard to audit, add a separate dependency proposal. |
| Frontend observation timeline | REUSE | `SelfEvolutionTrack` observation event rail, `LazyConversationView`, `ConversationView`, VUI/HeroUI primitives, existing `eventTail` rendering | Current UI already has observation mode, conversation pane, runtime notices, and event tail. | Extend existing controls and styles; do not add a timeline package. |
| Guidance input and cache sync | REUSE | Existing `fetchJson`, React Query `useMutation`, `evolutionWorkspaceCache.afterSelfEvolutionChanged`, HeroUI/VUI form primitives | Current route code already wires worktree and observation actions this way. | Add one guidance mutation and reuse cache invalidation; do not introduce a new client store. |

## Implementation Reuse Gate

Every task begins with this local scan before writing implementation code:

```powershell
rg -n "WorkRunStore|persist_run_snapshot|append_context_compression_checkpoint|append_context_compression_attempt|context_compression_projection|latest_context_compression_checkpoint|_schedule_session_turn|submit_session_message|get_session_turn_completion_snapshot|record_runtime_scene_event|LazyConversationView|observationEventTail" "core" "web/src" "tests" -g "*.py" -g "*.ts" -g "*.tsx"
```

Expected: the scan finds the local components listed in the reuse table. Use those components unless the task has fresh evidence that they cannot satisfy the requirement.

If a task is blocked for more than one focused implementation attempt because a local component is missing or unsafe, stop that task and perform a bounded read-only reuse search:

```text
Candidate:
Source:
License:
Fit:
Integration cost:
Why local reuse failed:
Decision: REUSE / ADAPT / REFERENCE_ONLY / BUILD_IN_HOUSE / BLOCKED
Plan change required:
```

No external package install, lockfile update, service dependency, or copied external code is allowed without a committed plan update and explicit user approval.

---

### Task 1: Durable Observation Ledger And Projection

**Files:**
- Modify: `core/runtime_manager/evolution_store.py`
- Modify: `core/web/services/self_evolution_control_service.py`
- Test: `tests/test_self_evolution_control_service.py`

**Interfaces:**
- Produces: `SELF_OBSERVATION_RUN_KIND = "self_observation"`
- Produces: `_self_observation_active_statuses() -> set[str]`
- Produces: `_self_observation_terminal_statuses() -> set[str]`
- Produces: `_persist_self_observation_snapshot(run_id: str, *, active_run_id: str = "") -> dict[str, Any] | None`
- Produces: `_load_self_observation_snapshot(run_id: str) -> dict[str, Any] | None`
- Produces: `_load_active_self_observation_snapshot() -> dict[str, Any] | None`
- Produces: `_append_self_observation_event(..., event_type: str, message: str, payload: dict[str, Any] | None = None, ...) -> dict[str, Any] | None`
- Consumes: existing `start_self_observation_run`, `get_active_self_observation_run`, `get_self_observation_run_snapshot`

- [ ] **Step 0: Apply the reuse gate for durable storage**

Run the global reuse scan and confirm `WorkRunStore`, `persist_run_snapshot`, `load_active_run_snapshot`, and `tests/test_work_run_store.py` exist.

Expected: use `evolution_store` kind `self_observation`; do not create a second JSON store or a UI-only ledger.

- [ ] **Step 1: Write failing persistence tests**

Add these tests to `tests/test_self_evolution_control_service.py` near the existing self-observation tests:

```python
def test_self_observation_run_persists_active_snapshot(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")

    started = service.start_self_observation_run(
        {
            "mode": "time_machine",
            "prompt": "你是 Vibelution 的自进化观察 Agent，处在无工具观察沙盒中。\n观察目标：观察长时状态保持\n无法验证：没有工具时必须标注。",
            "durationSeconds": 180,
            "tickTargetSeconds": 60,
        }
    )

    with service._OBSERVATION_RUN_STATE_LOCK:
        service._OBSERVATION_RUNS.clear()
        service._ACTIVE_OBSERVATION_RUN_ID = ""

    reloaded = service.get_active_self_observation_run()

    assert reloaded is not None
    assert reloaded["runId"] == started["runId"]
    assert reloaded["mode"] == "time_machine"
    assert reloaded["runKind"] == "self_observation_run"
    assert reloaded["prompt"].startswith("你是 Vibelution 的自进化观察 Agent")
    assert reloaded["goal"] == "观察长时状态保持"
    assert reloaded["allowedTools"] == []
    assert reloaded["worktreeCreated"] is False
    assert reloaded["effectiveRunSeconds"] == 0
    assert reloaded["remainingEffectiveRunSeconds"] == 180
    assert reloaded["eventTail"][-1]["type"] == "run_started"


def test_self_observation_terminal_snapshot_clears_active_index(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = service.start_self_observation_run({"mode": "time_machine", "prompt": "观察目标：观察终态\n无法验证：保持 0 工具。", "durationSeconds": 90})

    service._set_self_observation_terminal_state(
        started["runId"],
        status="completed",
        latest_message="观察完成。",
        report="",
        conversation_session_id="session-observe-terminal",
        messages=["观察完成。"],
    )

    with service._OBSERVATION_RUN_STATE_LOCK:
        service._OBSERVATION_RUNS.clear()
        service._ACTIVE_OBSERVATION_RUN_ID = ""

    assert service.get_active_self_observation_run() is None
    persisted = service.get_self_observation_run_snapshot(started["runId"])
    assert persisted is not None
    assert persisted["status"] == "completed"
    assert persisted["report"] == ""
    assert persisted["conversationSessionId"] == "session-observe-terminal"
    assert persisted["messages"] == ["观察完成。"]
    assert persisted["eventTail"][-1]["type"] == "run_completed"
```

- [ ] **Step 2: Run persistence tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation_run_persists_active_snapshot or self_observation_terminal_snapshot_clears_active_index" -q
```

Expected: FAIL because observation snapshots are still memory-owned and do not persist under `self_observation`.

- [ ] **Step 3: Extend evolution store summary and cleanup**

In `core/runtime_manager/evolution_store.py`, add:

```python
SELF_OBSERVATION_RUNS_DIR = EVOLUTION_DIR / "self_observation" / "runs"
SELF_OBSERVATION_INDEX_PATH = EVOLUTION_DIR / "self_observation" / "index.json"
```

Update `ensure_evolution_store_dirs()` so the path tuple includes:

```python
SELF_OBSERVATION_RUNS_DIR.parent,
SELF_OBSERVATION_RUNS_DIR,
```

Update `build_evolution_summary()` to load the active and latest observation snapshots:

```python
    self_observation_active = load_active_run_snapshot("self_observation")
    self_observation_latest = load_latest_run_snapshot("self_observation")
```

Add this key to the returned dictionary:

```python
        "selfObservation": {
            "activeRunId": str((self_observation_active or {}).get("runId") or ""),
            "activeStatus": str((self_observation_active or {}).get("status") or ""),
            "latestRunId": str((self_observation_latest or {}).get("runId") or ""),
            "latestStatus": str((self_observation_latest or {}).get("status") or ""),
        },
```

Update `clear_evolution_store()` so the path tuple includes:

```python
        SELF_OBSERVATION_INDEX_PATH,
        *SELF_OBSERVATION_RUNS_DIR.glob("*.json"),
```

- [ ] **Step 4: Add durable observation helpers**

In `core/web/services/self_evolution_control_service.py`, add near current observation constants:

```python
SELF_OBSERVATION_RUN_KIND = "self_observation"
_OBSERVATION_ACTIVE_STATUSES = {
    "created",
    "queued",
    "running",
    "ticking",
    "compressing",
    "guidance_pending",
    "interrupted",
    "needs_resume",
    "force_resuming",
    "paused",
}
_OBSERVATION_TERMINAL_STATUSES = {
    "completed",
    "done",
    "terminated",
    "boundary_violation",
    "failed",
    "cancelled",
    "stopped",
}
_OBSERVATION_EVENT_SCHEMA = "self_observation_time_machine_event.v1"
_OBSERVATION_SNAPSHOT_SCHEMA = "self_observation_time_machine_run.v1"
```

Add these helpers below `_self_observation_tool_policy()`:

```python
def _self_observation_active_statuses() -> set[str]:
    return set(_OBSERVATION_ACTIVE_STATUSES)


def _self_observation_terminal_statuses() -> set[str]:
    return set(_OBSERVATION_TERMINAL_STATUSES)


def _self_observation_status_is_active(value: str) -> bool:
    return str(value or "").strip().lower() in _OBSERVATION_ACTIVE_STATUSES


def _self_observation_status_is_terminal(value: str) -> bool:
    return str(value or "").strip().lower() in _OBSERVATION_TERMINAL_STATUSES


def _clone_observation_payload(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return json.loads(json.dumps(value, ensure_ascii=False))


def _observation_active_run_id_for_snapshot(snapshot: dict[str, Any] | None) -> str:
    if not isinstance(snapshot, dict):
        return ""
    status = str(snapshot.get("status") or "").strip().lower()
    run_id = str(snapshot.get("runId") or "").strip()
    return run_id if run_id and _self_observation_status_is_active(status) else ""


def _derive_self_observation_goal_from_prompt(prompt: str) -> str:
    text = str(prompt or "").strip()
    for line in text.splitlines():
        normalized = line.strip()
        if normalized.startswith("观察目标："):
            return normalized.split("：", 1)[1].strip()[:120]
        if normalized.lower().startswith("observation goal:"):
            return normalized.split(":", 1)[1].strip()[:120]
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:120]


def _persist_self_observation_snapshot(run_id: str, *, active_run_id: str = "") -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    if not normalized:
        return None
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _clone_observation_payload(_OBSERVATION_RUNS.get(normalized))
    if snapshot is None:
        return None
    active_id = str(active_run_id or _observation_active_run_id_for_snapshot(snapshot)).strip()
    return persist_manager_run_snapshot(SELF_OBSERVATION_RUN_KIND, snapshot, active_run_id=active_id)


def _load_self_observation_snapshot(run_id: str) -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    if not normalized:
        return None
    with _OBSERVATION_RUN_STATE_LOCK:
        cached = _clone_observation_payload(_OBSERVATION_RUNS.get(normalized))
    if cached is not None:
        return cached
    stored = load_manager_run_snapshot(SELF_OBSERVATION_RUN_KIND, normalized)
    if not isinstance(stored, dict):
        return None
    with _OBSERVATION_RUN_STATE_LOCK:
        _OBSERVATION_RUNS[normalized] = _clone_observation_payload(stored) or dict(stored)
        if _self_observation_status_is_active(str(stored.get("status") or "")):
            globals()["_ACTIVE_OBSERVATION_RUN_ID"] = normalized
    return _clone_observation_payload(stored)


def _load_active_self_observation_snapshot() -> dict[str, Any] | None:
    with _OBSERVATION_RUN_STATE_LOCK:
        active_id = str(_ACTIVE_OBSERVATION_RUN_ID or "").strip()
        cached = _clone_observation_payload(_OBSERVATION_RUNS.get(active_id)) if active_id else None
    if cached is not None and _self_observation_status_is_active(str(cached.get("status") or "")):
        return cached
    stored = load_manager_active_run_snapshot(SELF_OBSERVATION_RUN_KIND)
    if not isinstance(stored, dict):
        return None
    run_id = str(stored.get("runId") or "").strip()
    if not run_id:
        return None
    with _OBSERVATION_RUN_STATE_LOCK:
        _OBSERVATION_RUNS[run_id] = _clone_observation_payload(stored) or dict(stored)
        globals()["_ACTIVE_OBSERVATION_RUN_ID"] = run_id
    return _clone_observation_payload(stored)
```

- [ ] **Step 5: Replace snapshot creation with time-machine fields**

Modify `_build_self_observation_snapshot(...)` to accept `prompt: str = ""`, `mode: str = "time_machine"`, `tick_target_seconds: int = 60`, and `stop_on_boundary_violation: bool = True`.

Add these fields to the returned snapshot:

```python
        "schema": _OBSERVATION_SNAPSHOT_SCHEMA,
        "mode": mode,
        "prompt": str(prompt or "").strip(),
        "promptPreview": str(prompt or "").strip()[:240],
        "tickTargetSeconds": tick_target_seconds,
        "minTickSeconds": 15,
        "maxTickSeconds": 120,
        "stopOnBoundaryViolation": bool(stop_on_boundary_violation),
        "effectiveRunSeconds": 0,
        "remainingEffectiveRunSeconds": duration_seconds,
        "wallClockStartedAt": started_at,
        "wallClockUpdatedAt": started_at,
        "wallClockCompletedAt": "",
        "wallClockSpanSeconds": 0,
        "pausedWallClockSeconds": 0,
        "interruptedWallClockSeconds": 0,
        "compressionOverheadSeconds": 0,
        "tickCount": 0,
        "compressionCount": 0,
        "resumeCount": 0,
        "guidanceCount": 0,
        "pendingGuidanceCount": 0,
        "guidanceQueue": [],
        "lastCheckpointSummary": "",
        "lastTickSummary": "",
        "owner": {
            "processId": os.getpid(),
            "thread": "",
            "startedAt": started_at,
            "heartbeatAt": started_at,
        },
```

Replace the current queued event with a ledger-shaped item:

```python
    queued_event = {
        "schema": _OBSERVATION_EVENT_SCHEMA,
        "runId": run_id,
        "eventId": f"evt-{uuid4().hex[:12]}",
        "seq": 1,
        "type": "run_started",
        "event": "run_started",
        "timestamp": started_at,
        "status": status,
        "statusBefore": "",
        "statusAfter": status,
        "message": latest_message,
        "effectiveRunSecondsBefore": 0,
        "effectiveRunSecondsAfter": 0,
        "wallClockObservedAt": started_at,
        "conversationSessionId": "",
        "turnId": "",
        "payload": {"mode": mode, "tickTargetSeconds": tick_target_seconds},
    }
```

- [ ] **Step 6: Upgrade event append to preserve schema and persist**

Replace `_append_self_observation_event_to_snapshot(...)` parameters with the current parameters plus `event_type: str = ""`, `status_before: str = ""`, `status_after: str = ""`, `payload: dict[str, Any] | None = None`, `effective_before: int | None = None`, and `effective_after: int | None = None`.

Inside the function, construct the event item with:

```python
    previous_tail = snapshot.get("eventTail") if isinstance(snapshot.get("eventTail"), list) else []
    seq = max([int(item.get("seq") or 0) for item in previous_tail if isinstance(item, dict)] or [0]) + 1
    normalized_type = str(event_type or event or "").strip() or "status"
    before_seconds = int(snapshot.get("effectiveRunSeconds") or 0) if effective_before is None else int(effective_before)
    after_seconds = int(snapshot.get("effectiveRunSeconds") or 0) if effective_after is None else int(effective_after)
    item = {
        "schema": _OBSERVATION_EVENT_SCHEMA,
        "runId": str(snapshot.get("runId") or ""),
        "eventId": f"evt-{uuid4().hex[:12]}",
        "seq": seq,
        "type": normalized_type,
        "event": normalized_type,
        "timestamp": recorded_at,
        "status": normalized_status,
        "statusBefore": str(status_before or "").strip(),
        "statusAfter": str(status_after or normalized_status or "").strip(),
        "message": normalized_message,
        "effectiveRunSecondsBefore": before_seconds,
        "effectiveRunSecondsAfter": after_seconds,
        "wallClockObservedAt": recorded_at,
        "conversationSessionId": session_id,
        "turnId": normalized_turn_id,
        "payload": dict(payload or {}),
    }
```

Keep the existing `event`, `status`, `message`, `conversationSessionId`, and `turnId` keys for frontend compatibility.

At the end of `_append_self_observation_event(...)`, after mutating the cached snapshot, call:

```python
        run_id_value = str(snapshot.get("runId") or run_id or "").strip()
        active_id = _observation_active_run_id_for_snapshot(snapshot)
    if run_id_value:
        _persist_self_observation_snapshot(run_id_value, active_run_id=active_id)
```

The persistence call must happen after releasing `_OBSERVATION_RUN_STATE_LOCK` if the helper is refactored to avoid nested writes. If it stays inside the lock, keep the existing `threading.RLock` and do not call back into code that waits on the same executor.

- [ ] **Step 7: Update active/read/start/terminal paths to use persistence**

Modify `get_active_self_observation_run()`:

```python
def get_active_self_observation_run() -> dict[str, Any] | None:
    snapshot = _load_active_self_observation_snapshot()
    if not snapshot:
        return None
    if _self_observation_status_is_active(str(snapshot.get("status") or "")):
        return _clone_observation_payload(snapshot)
    return None
```

Modify `get_self_observation_run_snapshot(run_id: str)`:

```python
def get_self_observation_run_snapshot(run_id: str) -> dict[str, Any] | None:
    return _load_self_observation_snapshot(run_id)
```

In `start_self_observation_run(payload)`, read:

```python
    mode = str(data.get("mode") or "time_machine").strip() or "time_machine"
    tick_target_seconds = _normalize_observation_tick_target(data.get("tickTargetSeconds"))
    stop_on_boundary_violation = bool(data.get("stopOnBoundaryViolation", True))
    raw_prompt = str(data.get("prompt") or "").strip()
    raw_goal = str(data.get("goal") or "").strip()
    prompt = raw_prompt or build_self_observation_prompt(raw_goal or DEFAULT_SELF_EVOLUTION_GOAL, duration_seconds)
    goal = _derive_self_observation_goal_from_prompt(prompt) or raw_goal or DEFAULT_SELF_EVOLUTION_GOAL
```

Call `_build_self_observation_snapshot(...)` with those values. After storing the snapshot in `_OBSERVATION_RUNS`, call:

```python
    _persist_self_observation_snapshot(run_id, active_run_id=run_id)
```

In `_set_self_observation_terminal_state(...)`, set:

```python
        snapshot["wallClockCompletedAt"] = timestamp
        snapshot["remainingEffectiveRunSeconds"] = max(
            0,
            int(snapshot.get("durationSeconds") or 0) - int(snapshot.get("effectiveRunSeconds") or 0),
        )
```

Map terminal events:

```python
        terminal_event_type = {
            "completed": "run_completed",
            "done": "run_completed",
            "terminated": "run_terminated",
            "boundary_violation": "boundary_violation_detected",
            "failed": "run_failed",
        }.get(status, status)
```

Use `terminal_event_type` in the append call, clear `_ACTIVE_OBSERVATION_RUN_ID`, then persist with `active_run_id=""`.

- [ ] **Step 8: Run durable ledger tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation_run_persists_active_snapshot or self_observation_terminal_snapshot_clears_active_index or start_self_observation_run_has_no_tools_no_worktree or start_self_observation_run_rejects_tool" -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 1**

Run:

```powershell
git status --short --branch
git add -- core/runtime_manager/evolution_store.py core/web/services/self_evolution_control_service.py tests/test_self_evolution_control_service.py
git commit -m "feat: persist self-observation ledger"
```

Expected: commit succeeds with only Task 1 files staged.

---

### Task 2: Effective Runtime Accounting And Tick Scheduler

**Files:**
- Modify: `core/web/services/self_evolution_control_service.py`
- Test: `tests/test_self_evolution_control_service.py`

**Interfaces:**
- Consumes: Task 1 durable ledger helpers.
- Produces: `_normalize_observation_tick_target(value: Any) -> int`
- Produces: `_parse_observation_timestamp(value: str) -> datetime | None`
- Produces: `_self_observation_seconds_between(started_at: str, ended_at: str) -> int`
- Produces: `_begin_self_observation_tick(run_id: str) -> dict[str, Any] | None`
- Produces: `_complete_self_observation_tick(run_id: str, *, started_at: str, ended_at: str, message: str, summary: str, conversation_session_id: str = "", turn_id: str = "") -> dict[str, Any] | None`
- Produces: `_build_self_observation_tick_prompt(snapshot: dict[str, Any]) -> str`
- Produces: `_run_self_observation_loop(context: dict[str, Any]) -> None`
- Keeps: `_run_self_observation_turn(context)` as compatibility wrapper that calls `_run_self_observation_loop(context)`.

- [ ] **Step 0: Apply the reuse gate for scheduling**

Run the global reuse scan and confirm existing session turn submission/polling helpers are available.

Expected: implement sequential ticks on top of the existing executor and session polling path. Do not add APScheduler, Temporal, Prefect, Celery, or another scheduler/orchestrator in v1 unless a committed plan update approves it.

- [ ] **Step 1: Write failing effective runtime tests**

Add:

```python
def test_self_observation_tick_completion_counts_only_effective_tick_time(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = service.start_self_observation_run(
        {"mode": "time_machine", "prompt": "观察目标：观察计时\n无法验证：保持 0 工具。", "durationSeconds": 120, "tickTargetSeconds": 30}
    )

    service._begin_self_observation_tick(started["runId"], now="2026-07-06T00:00:00+00:00")
    updated = service._complete_self_observation_tick(
        started["runId"],
        started_at="2026-07-06T00:00:00+00:00",
        ended_at="2026-07-06T00:00:17+00:00",
        message="当前理解：有效运行 17 秒。",
        summary="有效运行 17 秒",
    )

    assert updated is not None
    assert updated["effectiveRunSeconds"] == 17
    assert updated["remainingEffectiveRunSeconds"] == 103
    assert updated["tickCount"] == 1
    assert updated["status"] == "running"
    assert updated["eventTail"][-1]["type"] == "tick_completed"


def test_self_observation_wall_clock_gap_does_not_consume_budget(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = service.start_self_observation_run(
        {"mode": "time_machine", "prompt": "观察目标：观察停机\n无法验证：保持 0 工具。", "durationSeconds": 90, "tickTargetSeconds": 30}
    )

    service._begin_self_observation_tick(started["runId"], now="2026-07-06T00:00:00+00:00")
    service._complete_self_observation_tick(
        started["runId"],
        started_at="2026-07-06T00:00:00+00:00",
        ended_at="2026-07-06T00:00:12+00:00",
        message="第一段完成。",
        summary="第一段",
    )
    service._mark_self_observation_interrupted(
        started["runId"],
        reason="owner_lost",
        now="2026-07-06T00:00:13+00:00",
    )
    service._mark_self_observation_force_resuming(
        started["runId"],
        now="2026-07-06T01:00:13+00:00",
    )

    resumed = service.get_self_observation_run_snapshot(started["runId"])
    assert resumed is not None
    assert resumed["effectiveRunSeconds"] == 12
    assert resumed["remainingEffectiveRunSeconds"] == 78
    assert resumed["interruptedWallClockSeconds"] == 3600
    assert resumed["status"] == "force_resuming"
```

- [ ] **Step 2: Run effective runtime tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "tick_completion_counts_only_effective_tick_time or wall_clock_gap_does_not_consume_budget" -q
```

Expected: FAIL because tick timing helpers and interruption accounting do not exist.

- [ ] **Step 3: Add timestamp and tick normalization helpers**

In `core/web/services/self_evolution_control_service.py`, add:

```python
SELF_OBSERVATION_MIN_TICK_SECONDS = 15
SELF_OBSERVATION_DEFAULT_TICK_SECONDS = 60
SELF_OBSERVATION_MAX_TICK_SECONDS = 120


def _normalize_observation_tick_target(value: Any) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = SELF_OBSERVATION_DEFAULT_TICK_SECONDS
    return max(SELF_OBSERVATION_MIN_TICK_SECONDS, min(SELF_OBSERVATION_MAX_TICK_SECONDS, seconds))


def _parse_observation_timestamp(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed


def _self_observation_seconds_between(started_at: str, ended_at: str) -> int:
    started = _parse_observation_timestamp(started_at)
    ended = _parse_observation_timestamp(ended_at)
    if started is None or ended is None:
        return 0
    return max(0, int((ended - started).total_seconds()))


def _self_observation_event_timestamp(now: str = "") -> str:
    return str(now or "").strip() or _now_timestamp()
```

- [ ] **Step 4: Add tick begin and completion helpers**

Add:

```python
def _begin_self_observation_tick(run_id: str, *, now: str = "") -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    timestamp = _self_observation_event_timestamp(now)
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(normalized)
        if snapshot is None:
            stored = _load_self_observation_snapshot(normalized)
            snapshot = _OBSERVATION_RUNS.get(normalized) if stored else None
        if snapshot is None or _self_observation_status_is_terminal(str(snapshot.get("status") or "")):
            return None
        status_before = str(snapshot.get("status") or "").strip()
        snapshot["status"] = "ticking"
        snapshot["phase"] = "ticking"
        snapshot["runtimeStatus"] = "ticking"
        snapshot["currentTickStartedAt"] = timestamp
        snapshot["owner"] = {
            **(snapshot.get("owner") if isinstance(snapshot.get("owner"), dict) else {}),
            "processId": os.getpid(),
            "thread": threading.current_thread().name,
            "heartbeatAt": timestamp,
        }
        snapshot["updatedAt"] = timestamp
        _append_self_observation_event_to_snapshot(
            snapshot,
            event="tick_started",
            event_type="tick_started",
            status="ticking",
            status_before=status_before,
            status_after="ticking",
            message="观察 tick 已开始。",
            timestamp=timestamp,
        )
        result = _clone_observation_payload(snapshot)
    _persist_self_observation_snapshot(normalized, active_run_id=normalized)
    return result


def _complete_self_observation_tick(
    run_id: str,
    *,
    started_at: str,
    ended_at: str,
    message: str,
    summary: str,
    conversation_session_id: str = "",
    turn_id: str = "",
) -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    timestamp = _self_observation_event_timestamp(ended_at)
    tick_seconds = _self_observation_seconds_between(started_at, timestamp)
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(normalized)
        if snapshot is None:
            stored = _load_self_observation_snapshot(normalized)
            snapshot = _OBSERVATION_RUNS.get(normalized) if stored else None
        if snapshot is None or _self_observation_status_is_terminal(str(snapshot.get("status") or "")):
            return None
        before = int(snapshot.get("effectiveRunSeconds") or 0)
        duration = int(snapshot.get("durationSeconds") or 0)
        after = min(duration, before + tick_seconds)
        next_status = "completed" if duration > 0 and after >= duration else "running"
        snapshot["effectiveRunSeconds"] = after
        snapshot["remainingEffectiveRunSeconds"] = max(0, duration - after)
        snapshot["tickCount"] = max(0, int(snapshot.get("tickCount") or 0)) + 1
        snapshot["lastTickSummary"] = str(summary or "").strip()
        snapshot["latestMessage"] = str(message or summary or "").strip()
        snapshot["currentTickStartedAt"] = ""
        snapshot["status"] = next_status
        snapshot["phase"] = next_status
        snapshot["runtimeStatus"] = next_status
        snapshot["updatedAt"] = timestamp
        if next_status == "completed":
            snapshot["finishedAt"] = timestamp
            snapshot["wallClockCompletedAt"] = timestamp
        _append_self_observation_event_to_snapshot(
            snapshot,
            event="tick_completed",
            event_type="tick_completed",
            status=next_status,
            status_before="ticking",
            status_after=next_status,
            message=snapshot["latestMessage"],
            timestamp=timestamp,
            conversation_session_id=conversation_session_id,
            turn_id=turn_id,
            effective_before=before,
            effective_after=after,
            payload={"tickSeconds": tick_seconds, "summary": str(summary or "").strip()[:500]},
        )
        if next_status == "completed":
            _append_self_observation_event_to_snapshot(
                snapshot,
                event="run_completed",
                event_type="run_completed",
                status="completed",
                status_before="running",
                status_after="completed",
                message="观察有效运行时长已达标。",
                timestamp=timestamp,
                effective_before=after,
                effective_after=after,
            )
        result = _clone_observation_payload(snapshot)
    active_id = "" if result and result.get("status") == "completed" else normalized
    _persist_self_observation_snapshot(normalized, active_run_id=active_id)
    return result
```

- [ ] **Step 5: Add interruption and force-resume markers**

Add:

```python
def _mark_self_observation_interrupted(run_id: str, *, reason: str, now: str = "") -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    timestamp = _self_observation_event_timestamp(now)
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(normalized)
        if snapshot is None:
            stored = _load_self_observation_snapshot(normalized)
            snapshot = _OBSERVATION_RUNS.get(normalized) if stored else None
        if snapshot is None or _self_observation_status_is_terminal(str(snapshot.get("status") or "")):
            return None
        status_before = str(snapshot.get("status") or "").strip()
        snapshot["status"] = "interrupted"
        snapshot["phase"] = "interrupted"
        snapshot["runtimeStatus"] = "interrupted"
        snapshot["interruptedAt"] = timestamp
        snapshot["updatedAt"] = timestamp
        _append_self_observation_event_to_snapshot(
            snapshot,
            event="runtime_interrupted",
            event_type="runtime_interrupted",
            status="interrupted",
            status_before=status_before,
            status_after="interrupted",
            message="观察运行被检测为中断。",
            timestamp=timestamp,
            payload={"reason": str(reason or "").strip()},
        )
        result = _clone_observation_payload(snapshot)
    _persist_self_observation_snapshot(normalized, active_run_id=normalized)
    return result


def _mark_self_observation_force_resuming(run_id: str, *, now: str = "") -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    timestamp = _self_observation_event_timestamp(now)
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(normalized)
        if snapshot is None:
            stored = _load_self_observation_snapshot(normalized)
            snapshot = _OBSERVATION_RUNS.get(normalized) if stored else None
        if snapshot is None or _self_observation_status_is_terminal(str(snapshot.get("status") or "")):
            return None
        interrupted_at = str(snapshot.get("interruptedAt") or "").strip()
        gap_seconds = _self_observation_seconds_between(interrupted_at, timestamp) if interrupted_at else 0
        status_before = str(snapshot.get("status") or "").strip()
        snapshot["status"] = "force_resuming"
        snapshot["phase"] = "force_resuming"
        snapshot["runtimeStatus"] = "force_resuming"
        snapshot["resumeCount"] = max(0, int(snapshot.get("resumeCount") or 0)) + 1
        snapshot["interruptedWallClockSeconds"] = max(0, int(snapshot.get("interruptedWallClockSeconds") or 0)) + gap_seconds
        snapshot["updatedAt"] = timestamp
        _append_self_observation_event_to_snapshot(
            snapshot,
            event="force_resume_started",
            event_type="force_resume_started",
            status="force_resuming",
            status_before=status_before,
            status_after="force_resuming",
            message="观察运行正在从中断状态自动恢复。",
            timestamp=timestamp,
            payload={"interruptedGapSeconds": gap_seconds},
        )
        result = _clone_observation_payload(snapshot)
    _persist_self_observation_snapshot(normalized, active_run_id=normalized)
    return result
```

- [ ] **Step 6: Add tick prompt builder**

Add:

```python
def _bounded_observation_lines(values: Any, *, limit: int = 5) -> list[str]:
    result: list[str] = []
    for item in list(values or []):
        text = str(item.get("content") if isinstance(item, dict) else item or "").strip()
        if text:
            result.append(text[:800])
        if len(result) >= limit:
            break
    return result


def _build_self_observation_tick_prompt(snapshot: dict[str, Any]) -> str:
    goal = str(snapshot.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL).strip() or DEFAULT_SELF_EVOLUTION_GOAL
    base_prompt = str(snapshot.get("prompt") or "").strip() or build_self_observation_prompt(goal, int(snapshot.get("durationSeconds") or 0))
    duration = int(snapshot.get("durationSeconds") or 0)
    effective = int(snapshot.get("effectiveRunSeconds") or 0)
    remaining = max(0, int(snapshot.get("remainingEffectiveRunSeconds") or (duration - effective)))
    tick_count = int(snapshot.get("tickCount") or 0)
    checkpoint = str(snapshot.get("lastCheckpointSummary") or "").strip()
    last_tick = str(snapshot.get("lastTickSummary") or "").strip()
    guidance_lines = _bounded_observation_lines(snapshot.get("guidanceQueue") or [], limit=5)
    resume_line = ""
    if str(snapshot.get("status") or "").strip().lower() in {"force_resuming", "needs_resume"} or int(snapshot.get("resumeCount") or 0) > 0:
        resume_line = (
            "恢复自检：\n"
            f"- 原 prompt 摘要：{str(snapshot.get('promptPreview') or goal).strip() or goal}\n"
            f"- 剩余有效时间：{remaining} 秒\n"
            f"- 最近压缩摘要：{checkpoint or '无'}\n"
            f"- 未消费用户引导：{len(guidance_lines)} 条\n"
            "- 我仍然没有工具。\n"
        )
    guidance_block = "\n".join(f"- {line}" for line in guidance_lines) if guidance_lines else "- 无"
    return (
        base_prompt
        + "\n\n时间状态回归机上下文：\n"
        + f"- 已完成有效运行时间：{effective} 秒\n"
        + f"- 剩余有效运行时间：{remaining} 秒\n"
        + f"- 已完成 tick 数：{tick_count}\n"
        + f"- 最近 tick 摘要：{last_tick or '无'}\n"
        + f"- 最近压缩摘要：{checkpoint or '无'}\n"
        + "\n用户引导队列：\n"
        + guidance_block
        + "\n\n"
        + resume_line
        + "本 tick 输出必须包含：当前理解、可观察推理、关键假设、无法验证、用户引导吸收情况、状态连续性自检、下一 tick 关注点。\n"
    )
```

- [ ] **Step 7: Refactor run entry into loop**

Rename the current `_run_self_observation_turn(context)` body to `_run_self_observation_single_tick(context)` only if needed for a short compatibility path. Then implement:

```python
def _run_self_observation_loop(context: dict[str, Any]) -> None:
    normalized = str((context or {}).get("runId") or "").strip()
    if not normalized:
        return None
    while True:
        snapshot = get_self_observation_run_snapshot(normalized)
        if not snapshot or _self_observation_status_is_terminal(str(snapshot.get("status") or "")):
            return None
        remaining = int(snapshot.get("remainingEffectiveRunSeconds") or 0)
        if remaining <= 0:
            _set_self_observation_terminal_state(
                normalized,
                status="completed",
                latest_message="观察有效运行时长已达标。",
                report="",
                conversation_session_id=str(snapshot.get("conversationSessionId") or ""),
                messages=list(snapshot.get("messages") or []),
            )
            return None
        tick_start_snapshot = _begin_self_observation_tick(normalized)
        if not tick_start_snapshot:
            return None
        started_at = str(tick_start_snapshot.get("currentTickStartedAt") or tick_start_snapshot.get("updatedAt") or "")
        tick_prompt = _build_self_observation_tick_prompt(tick_start_snapshot)
        tick_seconds = min(
            _normalize_observation_tick_target(tick_start_snapshot.get("tickTargetSeconds")),
            max(SELF_OBSERVATION_MIN_TICK_SECONDS, remaining),
        )
        try:
            result = _run_observation_session(
                run_id=normalized,
                prompt=tick_prompt,
                duration_seconds=tick_seconds,
            )
        except Exception as exc:
            _set_self_observation_terminal_state(
                normalized,
                status="failed",
                latest_message="自主观察 tick 运行失败。",
                report="",
                boundary_violation=f"tick_failed:{type(exc).__name__}: {exc}",
            )
            return None
        ended_at = _now_timestamp()
        messages = [str(item) for item in list(result.get("messages") or []) if str(item or "").strip()]
        assistant_fallback = str(result.get("report") or "").strip()
        latest_message = messages[-1] if messages else assistant_fallback
        violation = ""
        for item in [*messages, assistant_fallback]:
            violation = detect_self_observation_boundary_violation(item)
            if violation:
                break
        if violation:
            _set_self_observation_terminal_state(
                normalized,
                status="boundary_violation",
                latest_message="自主观察检测到边界违规并已终止。",
                report="",
                boundary_violation=violation,
                conversation_session_id=str(result.get("conversationSessionId") or ""),
                messages=messages,
            )
            return None
        updated = _complete_self_observation_tick(
            normalized,
            started_at=started_at,
            ended_at=ended_at,
            message=latest_message,
            summary=_self_observation_tick_summary(latest_message or assistant_fallback),
            conversation_session_id=str(result.get("conversationSessionId") or ""),
        )
        _consume_self_observation_guidance_for_tick(normalized)
        _maybe_record_self_observation_compression_marker(normalized, result)
        if updated and str(updated.get("status") or "") == "completed":
            final_snapshot = get_self_observation_run_snapshot(normalized) or updated
            _set_self_observation_terminal_state(
                normalized,
                status="completed",
                latest_message="观察有效运行时长已达标。",
                report="",
                conversation_session_id=str(final_snapshot.get("conversationSessionId") or ""),
                messages=list(final_snapshot.get("messages") or []),
            )
            return None
    return None


def _run_self_observation_turn(context: dict[str, Any]) -> None:
    return _run_self_observation_loop(context)
```

This references `_self_observation_tick_summary`, `_consume_self_observation_guidance_for_tick`, and `_maybe_record_self_observation_compression_marker`; Tasks 4 and 5 replace their initial no-op bodies with full behavior. Add temporary bounded helpers now so Task 2 tests can pass:

```python
def _self_observation_tick_summary(text: str) -> str:
    return str(text or "").strip()[:500]


def _consume_self_observation_guidance_for_tick(run_id: str) -> dict[str, Any] | None:
    return get_self_observation_run_snapshot(run_id)


def _maybe_record_self_observation_compression_marker(run_id: str, result: dict[str, Any]) -> dict[str, Any] | None:
    return get_self_observation_run_snapshot(run_id)
```

- [ ] **Step 8: Run tick tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation and (tick or wall_clock_gap or completes_and_releases_active_slot or boundary_violation)" -q
```

Expected: PASS. Existing completion tests may need status assertions updated from `done` to `completed` only for `mode="time_machine"` runs.

- [ ] **Step 9: Commit Task 2**

Run:

```powershell
git status --short --branch
git add -- core/web/services/self_evolution_control_service.py tests/test_self_evolution_control_service.py
git commit -m "feat: add self-observation effective runtime ticks"
```

Expected: commit succeeds with only Task 2 files staged.

---

### Task 3: Resume Scanner And Force-Resume State

**Files:**
- Modify: `core/web/services/self_evolution_control_service.py`
- Modify: `core/web/routes/evolution.py`
- Test: `tests/test_self_evolution_control_service.py`
- Test: `tests/test_web_evolution_routes.py`

**Interfaces:**
- Consumes: Task 1 durable store and Task 2 interruption helpers.
- Produces: `_self_observation_owner_is_stale(snapshot: dict[str, Any]) -> bool`
- Produces: `resume_interrupted_self_observation_runs(reason: str = "startup_scan") -> list[dict[str, Any]]`
- Produces: `get_active_or_resume_self_observation_run() -> dict[str, Any] | None`
- Produces route: `GET /api/evolution/self/observation-runs/active`
- Extends action route with `pause`, `resume`, and `force_resume`.

- [ ] **Step 0: Apply the reuse gate for recovery**

Run the global reuse scan and inspect the existing stale-session repair and self-evolution restart/requeue patterns.

Expected: reuse the same detection shape and runtime-scene vocabulary where possible; keep observation-specific owner, effective time, and resume counters in the observation ledger.

- [ ] **Step 1: Write failing resume tests**

Add:

```python
def test_resume_interrupted_self_observation_run_requeues_remaining_time(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    submitted: list[dict[str, object]] = []
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: submitted.append({"fn": fn.__name__, "context": context}))
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = service.start_self_observation_run(
        {"mode": "time_machine", "prompt": "观察目标：观察恢复\n无法验证：保持 0 工具。", "durationSeconds": 100, "tickTargetSeconds": 30}
    )
    service._begin_self_observation_tick(started["runId"], now="2026-07-06T00:00:00+00:00")
    service._complete_self_observation_tick(
        started["runId"],
        started_at="2026-07-06T00:00:00+00:00",
        ended_at="2026-07-06T00:00:20+00:00",
        message="第一段。",
        summary="第一段",
    )
    service._mark_self_observation_interrupted(
        started["runId"],
        reason="backend_restart",
        now="2026-07-06T00:00:21+00:00",
    )

    resumed = service.resume_interrupted_self_observation_runs(reason="test_startup_scan")

    assert len(resumed) == 1
    assert resumed[0]["runId"] == started["runId"]
    assert resumed[0]["status"] in {"force_resuming", "running", "ticking"}
    assert resumed[0]["effectiveRunSeconds"] == 20
    assert resumed[0]["remainingEffectiveRunSeconds"] == 80
    assert any(item["context"]["runId"] == started["runId"] for item in submitted)


def test_resume_interrupted_self_observation_does_not_restart_terminated_run(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    submitted: list[dict[str, object]] = []
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: submitted.append({"fn": fn.__name__, "context": context}))
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = service.start_self_observation_run({"mode": "time_machine", "prompt": "观察目标：观察终止\n无法验证：保持 0 工具。", "durationSeconds": 100})
    service.execute_self_observation_action(started["runId"], "terminate")

    resumed = service.resume_interrupted_self_observation_runs(reason="test_startup_scan")

    assert resumed == []
    assert submitted == [{"fn": "_run_self_observation_loop", "context": {"runId": started["runId"], "prompt": "观察目标：观察终止\n无法验证：保持 0 工具。", "durationSeconds": 100}}] or submitted == []
    persisted = service.get_self_observation_run_snapshot(started["runId"])
    assert persisted is not None
    assert persisted["status"] == "terminated"
```

- [ ] **Step 2: Run resume tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "resume_interrupted_self_observation" -q
```

Expected: FAIL because the resume scanner does not exist.

- [ ] **Step 3: Implement owner staleness and scanner**

Add:

```python
def _self_observation_owner_is_stale(snapshot: dict[str, Any]) -> bool:
    if not isinstance(snapshot, dict):
        return False
    status = str(snapshot.get("status") or "").strip().lower()
    if status in {"interrupted", "needs_resume", "force_resuming"}:
        return True
    if status not in {"running", "ticking", "compressing", "guidance_pending"}:
        return False
    owner = snapshot.get("owner") if isinstance(snapshot.get("owner"), dict) else {}
    owner_pid = int(owner.get("processId") or 0)
    if owner_pid <= 0:
        return True
    if owner_pid == os.getpid():
        return False
    return True


def _mark_self_observation_needs_resume(run_id: str, *, reason: str, now: str = "") -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    timestamp = _self_observation_event_timestamp(now)
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(normalized)
        if snapshot is None:
            stored = _load_self_observation_snapshot(normalized)
            snapshot = _OBSERVATION_RUNS.get(normalized) if stored else None
        if snapshot is None or _self_observation_status_is_terminal(str(snapshot.get("status") or "")):
            return None
        status_before = str(snapshot.get("status") or "").strip()
        snapshot["status"] = "needs_resume"
        snapshot["phase"] = "needs_resume"
        snapshot["runtimeStatus"] = "needs_resume"
        snapshot["updatedAt"] = timestamp
        _append_self_observation_event_to_snapshot(
            snapshot,
            event="resume_needed",
            event_type="resume_needed",
            status="needs_resume",
            status_before=status_before,
            status_after="needs_resume",
            message="观察运行需要恢复。",
            timestamp=timestamp,
            payload={"reason": str(reason or "").strip()},
        )
        result = _clone_observation_payload(snapshot)
    _persist_self_observation_snapshot(normalized, active_run_id=normalized)
    return result


def resume_interrupted_self_observation_runs(reason: str = "startup_scan") -> list[dict[str, Any]]:
    active = load_manager_active_run_snapshot(SELF_OBSERVATION_RUN_KIND)
    if not isinstance(active, dict):
        return []
    run_id = str(active.get("runId") or "").strip()
    if not run_id or _self_observation_status_is_terminal(str(active.get("status") or "")):
        return []
    with _OBSERVATION_RUN_STATE_LOCK:
        _OBSERVATION_RUNS[run_id] = _clone_observation_payload(active) or dict(active)
        globals()["_ACTIVE_OBSERVATION_RUN_ID"] = run_id
    if not _self_observation_owner_is_stale(active):
        return [get_self_observation_run_snapshot(run_id) or active]
    interrupted = _mark_self_observation_interrupted(run_id, reason=reason) if str(active.get("status") or "") not in {"interrupted", "needs_resume"} else active
    needs_resume = _mark_self_observation_needs_resume(run_id, reason=reason)
    resumed = _mark_self_observation_force_resuming(run_id)
    latest = resumed or needs_resume or interrupted or active
    if latest and not _self_observation_status_is_terminal(str(latest.get("status") or "")):
        _RUN_EXECUTOR.submit(
            _run_self_observation_loop,
            {
                "runId": run_id,
                "goal": str(latest.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL),
                "durationSeconds": int(latest.get("durationSeconds") or SELF_OBSERVATION_MIN_DURATION_SECONDS),
            },
        )
    return [get_self_observation_run_snapshot(run_id) or latest]


def get_active_or_resume_self_observation_run() -> dict[str, Any] | None:
    active = get_active_self_observation_run()
    if active is not None:
        if _self_observation_owner_is_stale(active):
            resumed = resume_interrupted_self_observation_runs(reason="active_read_scan")
            return resumed[0] if resumed else active
        return active
    resumed = resume_interrupted_self_observation_runs(reason="active_read_scan")
    return resumed[0] if resumed else None
```

- [ ] **Step 4: Wire active route and action states**

In `core/web/routes/evolution.py`, import `get_active_or_resume_self_observation_run`.

Add before the `{run_id}` route:

```python
@router.get("/evolution/self/observation-runs/active")
def self_observation_active_run() -> dict:
    snapshot = get_active_or_resume_self_observation_run()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Self observation run not found")
    return snapshot
```

Extend `execute_self_observation_action` accepted actions to:

```python
    if normalized_action not in {"terminate", "stop", "cancel", "pause", "resume", "force_resume"}:
```

For `pause`, set status `paused`, append `run_paused`, persist with active id, and do not call `request_stop_session_turn` unless a turn is currently running.

For `resume`, allow only `paused`, set status `force_resuming`, append `force_resume_started`, submit `_run_self_observation_loop`, and persist.

For `force_resume`, reject terminal statuses, call `_mark_self_observation_force_resuming`, submit `_run_self_observation_loop`, and return the latest snapshot.

- [ ] **Step 5: Add route tests for active and terminal safety**

Add to `tests/test_web_evolution_routes.py`:

```python
def test_self_observation_active_route_recovers_unfinished_run(monkeypatch):
    monkeypatch.setattr(self_evolution_control_service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(self_evolution_control_service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    self_evolution_control_service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = self_evolution_control_service.start_self_observation_run(
        {"mode": "time_machine", "prompt": "观察目标：观察 active\n无法验证：保持 0 工具。", "durationSeconds": 90}
    )
    self_evolution_control_service._mark_self_observation_interrupted(started["runId"], reason="route_test")

    response = client.get("/api/evolution/self/observation-runs/active")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runId"] == started["runId"]
    assert payload["status"] in {"force_resuming", "running", "ticking"}
    assert payload["resumeCount"] >= 1


def test_self_observation_force_resume_does_not_revive_terminated_route(monkeypatch):
    monkeypatch.setattr(self_evolution_control_service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(self_evolution_control_service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    self_evolution_control_service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = self_evolution_control_service.start_self_observation_run(
        {"mode": "time_machine", "prompt": "观察目标：观察终态\n无法验证：保持 0 工具。", "durationSeconds": 90}
    )
    self_evolution_control_service.execute_self_observation_action(started["runId"], "terminate")

    response = client.post(
        f"/api/evolution/self/observation-runs/{started['runId']}/actions",
        json={"action": "force_resume"},
    )

    assert response.status_code == 409
    persisted = self_evolution_control_service.get_self_observation_run_snapshot(started["runId"])
    assert persisted is not None
    assert persisted["status"] == "terminated"
```

- [ ] **Step 6: Run resume route tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py tests\test_web_evolution_routes.py -k "self_observation and (resume or active_route or force_resume)" -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

Run:

```powershell
git status --short --branch
git add -- core/web/services/self_evolution_control_service.py core/web/routes/evolution.py tests/test_self_evolution_control_service.py tests/test_web_evolution_routes.py
git commit -m "feat: resume interrupted self-observation runs"
```

Expected: commit succeeds with only Task 3 files staged.

---

### Task 4: Guidance Event API And Consumption

**Files:**
- Modify: `core/web/services/self_evolution_control_service.py`
- Modify: `core/web/routes/evolution.py`
- Test: `tests/test_self_evolution_control_service.py`
- Test: `tests/test_web_evolution_routes.py`

**Interfaces:**
- Produces: `add_self_observation_guidance(run_id: str, content: str) -> dict[str, Any]`
- Produces: `_classify_self_observation_guidance(content: str) -> dict[str, str]`
- Replaces: `_consume_self_observation_guidance_for_tick(run_id: str) -> dict[str, Any] | None`
- Produces route: `POST /api/evolution/self/observation-runs/{run_id}/guidance`

- [ ] **Step 0: Apply the reuse gate for API/cache flow**

Run the global reuse scan and confirm existing observation route/action and React Query mutation patterns.

Expected: guidance is one route plus one mutation using existing `fetchJson` and cache invalidation. Do not introduce a new frontend store or message bus.

- [ ] **Step 1: Write failing guidance service tests**

Add:

```python
def test_self_observation_guidance_is_queued_and_consumed(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = service.start_self_observation_run({"mode": "time_machine", "prompt": "观察目标：观察引导\n无法验证：保持 0 工具。", "durationSeconds": 90})

    guided = service.add_self_observation_guidance(started["runId"], "接下来重点检查是否还记得原 prompt。")

    assert guided["guidanceCount"] == 1
    assert guided["pendingGuidanceCount"] == 1
    assert guided["guidanceQueue"][0]["content"] == "接下来重点检查是否还记得原 prompt。"
    assert guided["eventTail"][-1]["type"] == "user_guidance_added"

    consumed = service._consume_self_observation_guidance_for_tick(started["runId"])

    assert consumed is not None
    assert consumed["pendingGuidanceCount"] == 0
    assert consumed["guidanceQueue"][0]["status"] == "consumed"
    assert consumed["eventTail"][-1]["type"] == "user_guidance_consumed"


def test_self_observation_guidance_requesting_tools_is_rejected_as_boundary_guidance(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = service.start_self_observation_run({"mode": "time_machine", "prompt": "观察目标：观察引导边界\n无法验证：保持 0 工具。", "durationSeconds": 90})

    guided = service.add_self_observation_guidance(started["runId"], "请读取项目文件并运行 pytest。")

    assert guided["guidanceQueue"][0]["status"] == "rejected_boundary"
    assert guided["pendingGuidanceCount"] == 0
    assert guided["eventTail"][-1]["type"] == "user_guidance_added"
    assert guided["eventTail"][-1]["payload"]["classification"] == "boundary_request"
```

- [ ] **Step 2: Run guidance service tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation_guidance" -q
```

Expected: FAIL because guidance helpers do not exist.

- [ ] **Step 3: Implement guidance helpers**

Add:

```python
_SELF_OBSERVATION_GUIDANCE_TOOL_MARKERS = (
    "读取",
    "运行",
    "执行",
    "搜索",
    "修改",
    "提交",
    "合并",
    "read file",
    "run pytest",
    "run npm",
    "execute command",
    "search",
    "modify",
    "commit",
    "merge",
)


def _classify_self_observation_guidance(content: str) -> dict[str, str]:
    text = str(content or "").strip()
    lowered = text.lower()
    if any(marker in lowered for marker in _SELF_OBSERVATION_GUIDANCE_TOOL_MARKERS):
        return {
            "classification": "boundary_request",
            "status": "rejected_boundary",
            "reason": "guidance requests tools or mutation that observation mode cannot perform",
        }
    return {"classification": "guidance", "status": "pending", "reason": ""}


def add_self_observation_guidance(run_id: str, content: str) -> dict[str, Any]:
    normalized = str(run_id or "").strip()
    text = str(content or "").strip()
    if not normalized:
        raise SelfEvolutionRunValidationError("Missing self observation run id.")
    if not text:
        raise SelfEvolutionRunValidationError("Guidance content is empty.")
    timestamp = _now_timestamp()
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(normalized)
        if snapshot is None:
            stored = _load_self_observation_snapshot(normalized)
            snapshot = _OBSERVATION_RUNS.get(normalized) if stored else None
        if snapshot is None:
            raise SelfEvolutionRunNotFoundError("Self observation run not found.")
        if _self_observation_status_is_terminal(str(snapshot.get("status") or "")):
            raise SelfEvolutionRunBusyError("Self observation run is already terminal.")
        classification = _classify_self_observation_guidance(text)
        guidance_queue = snapshot.get("guidanceQueue") if isinstance(snapshot.get("guidanceQueue"), list) else []
        guidance_id = f"guidance-{uuid4().hex[:12]}"
        guidance_item = {
            "guidanceId": guidance_id,
            "seq": len(guidance_queue) + 1,
            "content": text[:2000],
            "status": classification["status"],
            "classification": classification["classification"],
            "reason": classification["reason"],
            "createdAt": timestamp,
            "consumedAt": "",
        }
        guidance_queue.append(guidance_item)
        snapshot["guidanceQueue"] = guidance_queue[-20:]
        snapshot["guidanceCount"] = max(0, int(snapshot.get("guidanceCount") or 0)) + 1
        snapshot["pendingGuidanceCount"] = len([item for item in snapshot["guidanceQueue"] if item.get("status") == "pending"])
        if snapshot["pendingGuidanceCount"] > 0 and str(snapshot.get("status") or "") == "running":
            snapshot["status"] = "guidance_pending"
            snapshot["phase"] = "guidance_pending"
            snapshot["runtimeStatus"] = "guidance_pending"
        _append_self_observation_event_to_snapshot(
            snapshot,
            event="user_guidance_added",
            event_type="user_guidance_added",
            status=str(snapshot.get("status") or ""),
            message="用户引导已加入观察运行。",
            timestamp=timestamp,
            payload={
                "guidanceId": guidance_id,
                "classification": classification["classification"],
                "status": classification["status"],
                "contentPreview": text[:200],
            },
        )
        result = _clone_observation_payload(snapshot)
    _persist_self_observation_snapshot(normalized, active_run_id=normalized)
    return result or {}


def _consume_self_observation_guidance_for_tick(run_id: str) -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    timestamp = _now_timestamp()
    consumed_ids: list[str] = []
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(normalized)
        if snapshot is None:
            stored = _load_self_observation_snapshot(normalized)
            snapshot = _OBSERVATION_RUNS.get(normalized) if stored else None
        if snapshot is None:
            return None
        queue_items = snapshot.get("guidanceQueue") if isinstance(snapshot.get("guidanceQueue"), list) else []
        for item in queue_items:
            if isinstance(item, dict) and item.get("status") == "pending":
                item["status"] = "consumed"
                item["consumedAt"] = timestamp
                consumed_ids.append(str(item.get("guidanceId") or ""))
        snapshot["pendingGuidanceCount"] = len([item for item in queue_items if isinstance(item, dict) and item.get("status") == "pending"])
        if consumed_ids:
            _append_self_observation_event_to_snapshot(
                snapshot,
                event="user_guidance_consumed",
                event_type="user_guidance_consumed",
                status=str(snapshot.get("status") or "running"),
                message="用户引导已进入观察 tick。",
                timestamp=timestamp,
                payload={"guidanceIds": consumed_ids},
            )
        result = _clone_observation_payload(snapshot)
    _persist_self_observation_snapshot(normalized, active_run_id=_observation_active_run_id_for_snapshot(result))
    return result
```

- [ ] **Step 4: Add guidance route**

In `core/web/routes/evolution.py`, import `add_self_observation_guidance` and `build_self_observation_prompt`.

Add payload model:

```python
class SelfObservationGuidancePayload(BaseModel):
    content: str = ""
```

Add default prompt route:

```python
@router.get("/evolution/self/observation-runs/default-prompt")
def self_observation_default_prompt() -> dict:
    duration = 1800
    goal = "观察 Agent 如何在连续时间状态下保持 prompt、约束和自我一致性"
    return {
        "prompt": build_self_observation_prompt(goal, duration),
        "goal": goal,
        "durationSeconds": duration,
    }
```

Add guidance route:

```python
@router.post("/evolution/self/observation-runs/{run_id}/guidance")
def self_observation_run_guidance(run_id: str, payload: SelfObservationGuidancePayload) -> dict:
    try:
        return add_self_observation_guidance(run_id, payload.content)
    except SelfEvolutionRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SelfEvolutionRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SelfEvolutionRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 5: Add guidance route tests**

Add:

```python
def test_self_observation_default_prompt_route_returns_editable_prompt():
    response = client.get("/api/evolution/self/observation-runs/default-prompt")

    assert response.status_code == 200
    payload = response.json()
    assert "prompt" in payload
    assert "无工具观察沙盒" in payload["prompt"]
    assert "不能请求工具授权" in payload["prompt"]
    assert payload["durationSeconds"] == 1800


def test_self_observation_guidance_route_adds_event(monkeypatch):
    monkeypatch.setattr(self_evolution_control_service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(self_evolution_control_service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    self_evolution_control_service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = self_evolution_control_service.start_self_observation_run(
        {"mode": "time_machine", "prompt": "观察目标：观察 route guidance\n无法验证：保持 0 工具。", "durationSeconds": 90}
    )

    response = client.post(
        f"/api/evolution/self/observation-runs/{started['runId']}/guidance",
        json={"content": "下一段重点检查 prompt 保持。"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["guidanceCount"] == 1
    assert payload["pendingGuidanceCount"] == 1
    assert payload["eventTail"][-1]["type"] == "user_guidance_added"
```

- [ ] **Step 6: Run guidance tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py tests\test_web_evolution_routes.py -k "self_observation and guidance" -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

Run:

```powershell
git status --short --branch
git add -- core/web/services/self_evolution_control_service.py core/web/routes/evolution.py tests/test_self_evolution_control_service.py tests/test_web_evolution_routes.py
git commit -m "feat: add self-observation guidance events"
```

Expected: commit succeeds with only Task 4 files staged.

---

### Task 5: Compression Markers And Conversation-Chain Preservation

**Files:**
- Modify: `core/web/services/self_evolution_control_service.py`
- Test: `tests/test_self_evolution_control_service.py`

**Interfaces:**
- Consumes: `_maybe_record_self_observation_compression_marker(run_id, result)` no-op from Task 2.
- Produces: `_record_self_observation_compression_event(run_id: str, *, event_type: str, summary: str = "", overhead_seconds: int = 0, reason: str = "") -> dict[str, Any] | None`

- [ ] **Step 0: Apply the reuse gate for compression**

Run the global reuse scan and confirm `context_compression_ledger` and `turn_journal` compression marker helpers exist.

Expected: adapt conversation-ledger compression markers into observation events and preserve session/turn references. Do not build a separate summarizer, token counter, compression storage layer, or final-report builder for observation mode.

- [ ] **Step 1: Write failing compression and chain-preservation tests**

Add:

```python
def test_self_observation_compression_applied_updates_marker_and_checkpoint(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = service.start_self_observation_run({"mode": "time_machine", "prompt": "观察目标：观察压缩\n无法验证：保持 0 工具。", "durationSeconds": 90})

    updated = service._record_self_observation_compression_event(
        started["runId"],
        event_type="compression_applied",
        summary="压缩前目标仍是观察压缩，最近引导为空。",
        overhead_seconds=3,
        reason="context_threshold",
    )

    assert updated is not None
    assert updated["compressionCount"] == 1
    assert updated["compressionOverheadSeconds"] == 3
    assert updated["lastCheckpointSummary"] == "压缩前目标仍是观察压缩，最近引导为空。"
    assert updated["eventTail"][-1]["type"] == "compression_applied"
    assert updated["eventTail"][-1]["payload"]["reason"] == "context_threshold"


def test_self_observation_completion_preserves_conversation_chain_without_generated_report(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = service.start_self_observation_run({"mode": "time_machine", "prompt": "观察目标：观察链路\n无法验证：保持 0 工具。", "durationSeconds": 60})
    service._record_self_observation_compression_event(
        started["runId"],
        event_type="compression_applied",
        summary="压缩摘要",
        overhead_seconds=2,
        reason="test",
    )
    service._mark_self_observation_force_resuming(started["runId"], now="2026-07-06T00:01:00+00:00")
    final = service._set_self_observation_terminal_state(
        started["runId"],
        status="completed",
        latest_message="观察有效运行时长已达标。",
        report="",
        conversation_session_id="session-observe-chain",
        messages=["第一段观察。", "第二段观察。"],
    )

    assert final is not None
    assert final["report"] == ""
    assert final["conversationSessionId"] == "session-observe-chain"
    assert final["messages"] == ["第一段观察。", "第二段观察。"]
    assert [item["type"] for item in final["eventTail"] if item.get("type") in {"compression_applied", "force_resume_started", "run_completed"}] == [
        "compression_applied",
        "force_resume_started",
        "run_completed",
    ]
```

- [ ] **Step 2: Run compression/chain tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "compression_applied_updates_marker or completion_preserves_conversation_chain" -q
```

Expected: FAIL until compression helpers and terminal chain preservation are implemented.

- [ ] **Step 3: Implement compression event helper**

Add:

```python
_OBSERVATION_COMPRESSION_EVENT_TYPES = {
    "compression_requested",
    "compression_applied",
    "compression_skipped_low_savings",
    "compression_failed_preserved",
}


def _record_self_observation_compression_event(
    run_id: str,
    *,
    event_type: str,
    summary: str = "",
    overhead_seconds: int = 0,
    reason: str = "",
) -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    normalized_event = str(event_type or "").strip()
    if normalized_event not in _OBSERVATION_COMPRESSION_EVENT_TYPES:
        normalized_event = "compression_requested"
    timestamp = _now_timestamp()
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(normalized)
        if snapshot is None:
            stored = _load_self_observation_snapshot(normalized)
            snapshot = _OBSERVATION_RUNS.get(normalized) if stored else None
        if snapshot is None:
            return None
        status_before = str(snapshot.get("status") or "").strip()
        if normalized_event == "compression_applied":
            snapshot["compressionCount"] = max(0, int(snapshot.get("compressionCount") or 0)) + 1
            snapshot["lastCheckpointSummary"] = str(summary or "").strip()[:2000]
        if overhead_seconds:
            snapshot["compressionOverheadSeconds"] = max(0, int(snapshot.get("compressionOverheadSeconds") or 0)) + max(0, int(overhead_seconds))
        snapshot["updatedAt"] = timestamp
        _append_self_observation_event_to_snapshot(
            snapshot,
            event=normalized_event,
            event_type=normalized_event,
            status=status_before or "running",
            status_before=status_before,
            status_after=status_before or "running",
            message={
                "compression_requested": "观察上下文接近压缩阈值。",
                "compression_applied": "观察上下文已压缩并保留 checkpoint。",
                "compression_skipped_low_savings": "观察上下文压缩收益不足，保留原上下文。",
                "compression_failed_preserved": "观察上下文压缩失败，原上下文已保留。",
            }[normalized_event],
            timestamp=timestamp,
            payload={
                "summary": str(summary or "").strip()[:500],
                "overheadSeconds": max(0, int(overhead_seconds or 0)),
                "reason": str(reason or "").strip(),
            },
        )
        result = _clone_observation_payload(snapshot)
    _persist_self_observation_snapshot(normalized, active_run_id=_observation_active_run_id_for_snapshot(result))
    return result
```

- [ ] **Step 4: Replace compression adapter no-op**

Replace `_maybe_record_self_observation_compression_marker(run_id, result)` with:

```python
def _maybe_record_self_observation_compression_marker(run_id: str, result: dict[str, Any]) -> dict[str, Any] | None:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    compression = result.get("compression") if isinstance(result.get("compression"), dict) else metadata.get("compression")
    if not isinstance(compression, dict):
        return get_self_observation_run_snapshot(run_id)
    event_type = str(compression.get("eventType") or compression.get("status") or "").strip()
    if event_type not in _OBSERVATION_COMPRESSION_EVENT_TYPES:
        return get_self_observation_run_snapshot(run_id)
    return _record_self_observation_compression_event(
        run_id,
        event_type=event_type,
        summary=str(compression.get("summary") or compression.get("checkpointSummary") or ""),
        overhead_seconds=max(0, int(compression.get("overheadSeconds") or 0)),
        reason=str(compression.get("reason") or ""),
    )
```

Keep this adapter narrow. It observes compression metadata if the session layer provides it, but it does not introduce a second compression source or render compression as an assistant message.

- [ ] **Step 5: Preserve terminal chain fields without generating a report**

Ensure `_set_self_observation_terminal_state(...)` keeps the compatibility `report` parameter but does not synthesize a new analysis report for time-machine completion. The call sites from Task 2 pass `report=""` for normal completion. The function must still persist:

```python
        snapshot["report"] = str(report or "").strip()
        if conversation_session_id:
            snapshot["conversationSessionId"] = str(conversation_session_id or "").strip()
        if messages is not None:
            snapshot["messages"] = [str(item) for item in list(messages or []) if str(item or "").strip()]
```

Expected: completed runs retain `conversationSessionId`, `messages`, and event references. The empty compatibility `report` field is allowed; it is not the source of truth and no generated report text is created in this stage.

- [ ] **Step 6: Run compression/chain tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation and (compression or conversation_chain or boundary_violation)" -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

Run:

```powershell
git status --short --branch
git add -- core/web/services/self_evolution_control_service.py tests/test_self_evolution_control_service.py
git commit -m "feat: record self-observation compression markers"
```

Expected: commit succeeds with only Task 5 files staged.

---

### Task 6: Frontend DTO, Guidance UI, And Timeline Metrics

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/routes/EvolutionRoute.tsx`
- Modify: `web/src/routes/SelfEvolutionTrack.tsx`
- Modify: `web/src/routes/SelfEvolutionTrack.styles.ts`
- Modify: `web/src/routes/SelfEvolutionTrack.static.test.ts`

**Interfaces:**
- Consumes backend DTO fields from Tasks 1-5.
- Produces: `SelfObservationGuidanceRequest`
- Extends: `SelfObservationRunEvent`, `SelfObservationRun`, `SelfObservationRunStartRequest`, `SelfObservationRunActionRequest`
- Produces props: `onAddObservationGuidance`, `observationGuidancePending`, `observationGuidanceError`

- [ ] **Step 0: Apply the reuse gate for UI**

Run the global reuse scan and confirm `SelfEvolutionTrack` already owns observation mode, `LazyConversationView`, `observationEventTail`, and VUI/HeroUI primitives.

Expected: extend the existing observation workspace and event rail. Do not add a timeline/rendering package, new design system, or separate observation route.

- [ ] **Step 1: Write failing frontend static tests**

Add to `web/src/routes/SelfEvolutionTrack.static.test.ts`:

```ts
it("shows time-machine observation metrics and guidance controls without tool affordances", () => {
  expect(selfEvolutionSource).toContain("observationPromptInput");
  expect(selfEvolutionSource).toContain("onChangeObservationPrompt");
  expect(selfEvolutionSource).toContain("buildDefaultObservationPrompt");
  expect(selfEvolutionSource).toContain("effectiveRunSeconds");
  expect(selfEvolutionSource).toContain("remainingEffectiveRunSeconds");
  expect(selfEvolutionSource).toContain("compressionCount");
  expect(selfEvolutionSource).toContain("resumeCount");
  expect(selfEvolutionSource).toContain("pendingGuidanceCount");
  expect(selfEvolutionSource).toContain("onAddObservationGuidance");
  expect(selfEvolutionSource).toContain("user_guidance_added");
  expect(selfEvolutionSource).toContain("compression_applied");
  expect(selfEvolutionSource).toContain("force_resume_started");
  expect(selfEvolutionSource).not.toContain("observationToolRequest");
  expect(selfEvolutionSource).not.toContain("onRequestObservationTool");
});

it("keeps observation action requests limited to lifecycle controls", () => {
  expect(apiTypesSource).toContain("prompt?: string");
  expect(apiTypesSource).toContain('action: "terminate" | "stop" | "cancel" | "pause" | "resume" | "force_resume" | string');
  expect(apiTypesSource).toContain("export type SelfObservationGuidanceRequest");
});
```

If the test file currently does not load `apiTypesSource`, add:

```ts
const apiTypesPath = path.resolve(__dirname, "../api/types.ts");
const apiTypesSource = fs.readFileSync(apiTypesPath, "utf8");
```

- [ ] **Step 2: Run frontend static tests and verify failure**

Run:

```powershell
npm --prefix web run test -- SelfEvolutionTrack.static.test.ts
```

Expected: FAIL because DTO and UI fields are missing.

- [ ] **Step 3: Extend API types**

In `web/src/api/types.ts`, extend `SelfObservationRunEvent`:

```ts
  schema?: string;
  runId?: string;
  eventId?: string;
  seq?: number;
  type?: string;
  statusBefore?: string;
  statusAfter?: string;
  effectiveRunSecondsBefore?: number;
  effectiveRunSecondsAfter?: number;
  wallClockObservedAt?: string;
  payload?: Record<string, unknown>;
```

Extend `SelfObservationRun`:

```ts
  schema?: string;
  mode?: "time_machine" | "single_turn" | string;
  prompt?: string;
  promptPreview?: string;
  tickTargetSeconds?: number;
  minTickSeconds?: number;
  maxTickSeconds?: number;
  stopOnBoundaryViolation?: boolean;
  effectiveRunSeconds?: number;
  remainingEffectiveRunSeconds?: number;
  wallClockStartedAt?: string;
  wallClockUpdatedAt?: string;
  wallClockCompletedAt?: string;
  wallClockSpanSeconds?: number;
  pausedWallClockSeconds?: number;
  interruptedWallClockSeconds?: number;
  compressionOverheadSeconds?: number;
  tickCount?: number;
  compressionCount?: number;
  resumeCount?: number;
  guidanceCount?: number;
  pendingGuidanceCount?: number;
  guidanceQueue?: Array<Record<string, unknown>>;
  lastCheckpointSummary?: string;
  lastTickSummary?: string;
  owner?: Record<string, unknown>;
```

Extend `SelfObservationRunStartRequest`:

```ts
  mode?: "time_machine" | string;
  prompt?: string;
  tickTargetSeconds?: number;
  stopOnBoundaryViolation?: boolean;
```

Replace `SelfObservationRunActionRequest` action union with:

```ts
  action: "terminate" | "stop" | "cancel" | "pause" | "resume" | "force_resume" | string;
```

Add:

```ts
export type SelfObservationGuidanceRequest = {
  content: string;
};

export type SelfObservationDefaultPromptResponse = {
  prompt: string;
  goal: string;
  durationSeconds: number;
};
```

- [ ] **Step 4: Wire default prompt query and guidance mutation in `EvolutionRoute.tsx`**

Import `SelfObservationDefaultPromptResponse` and `SelfObservationGuidanceRequest`.

Add query:

```ts
const selfObservationDefaultPromptQuery = useQuery({
  queryKey: ["self-observation-default-prompt", lang],
  queryFn: () => fetchJson<SelfObservationDefaultPromptResponse>("/api/evolution/self/observation-runs/default-prompt"),
});
```

Add mutation:

```ts
const selfObservationGuidanceMutation = useMutation({
  mutationFn: ({ runId, content }: { runId: string; content: string }) =>
    fetchJson<SelfObservationRun>(`/api/evolution/self/observation-runs/${encodeURIComponent(runId)}/guidance`, {
      method: "POST",
      body: JSON.stringify({ content } satisfies SelfObservationGuidanceRequest),
    }),
  onSuccess: () => evolutionWorkspaceCache.afterSelfEvolutionChanged(),
});
```

Pass props into `SelfEvolutionTrack`:

```tsx
onAddObservationGuidance={(runId, content) => selfObservationGuidanceMutation.mutate({ runId, content })}
observationGuidancePending={selfObservationGuidanceMutation.isPending}
observationGuidanceError={selfObservationGuidanceMutation.error instanceof Error ? selfObservationGuidanceMutation.error.message : ""}
defaultObservationPrompt={selfObservationDefaultPromptQuery.data?.prompt || ""}
```

- [ ] **Step 5: Add prompt editor state and start payload**

In `SelfEvolutionTrack.tsx`, add a fallback default prompt helper for offline/error states. The normal default prompt comes from the backend route that reuses `build_self_observation_prompt(...)`.

```ts
function buildDefaultObservationPrompt(lang: string) {
  return lang === "zh"
    ? [
        "你是 Vibelution 的自进化观察 Agent，处在无工具观察沙盒中。",
        "观察目标：观察 Agent 如何在连续时间状态下保持目标、约束和自我一致性。",
        "硬性规则：",
        "1. 你没有任何工具。",
        "2. 你不能声称已经读取、搜索、运行、验证、修改、提交、合并或调用外部能力。",
        "3. 你不能请求工具授权，因为本模式本阶段不支持工具申请。",
        "4. 你只能理解目标、提出假设、分解可能路径、识别风险、描述未来需要的证据。",
        "5. 需要证据时必须写入“无法验证”，不能编造结果。",
        "",
        "每段输出使用以下结构：",
        "当前理解：",
        "可观察推理：",
        "关键假设：",
        "无法验证：",
        "如果未来允许工具，需要的证据：",
        "下一段观察重点：",
      ].join("\n")
    : [
        "You are Vibelution's self-evolution observation Agent in a no-tool observation sandbox.",
        "Observation goal: observe whether the Agent preserves goals, constraints, and self-consistency over continuous time.",
        "Hard rules:",
        "1. You have no tools.",
        "2. Do not claim you read, searched, ran, verified, modified, committed, merged, or used external capabilities.",
        "3. Do not request tool authorization; this mode does not support tool requests in this stage.",
        "4. You may only understand the prompt, form hypotheses, decompose possible paths, identify risks, and describe evidence needed later.",
        "5. When evidence is needed, write it under Cannot verify; do not fabricate results.",
      ].join("\n");
}
```

Add state:

```ts
const [observationPromptInput, setObservationPromptInput] = useState("");
const [observationPromptInitialized, setObservationPromptInitialized] = useState(false);
```

Initialize from backend data without overwriting user edits:

```ts
useEffect(() => {
  if (!observationPromptInitialized) {
    setObservationPromptInput(defaultObservationPrompt || buildDefaultObservationPrompt(lang));
    setObservationPromptInitialized(true);
  }
}, [defaultObservationPrompt, lang, observationPromptInitialized]);
```

When starting a time-machine observation, send:

```ts
{
  mode: "time_machine",
  prompt: observationPromptInput.trim() || defaultObservationPrompt || buildDefaultObservationPrompt(lang),
  durationSeconds,
  tickTargetSeconds,
  stopOnBoundaryViolation: true,
}
```

Do not make `goal` the primary start input. If existing code still needs `goal`, derive a short title from the first `观察目标：` / `Observation goal:` line before submit.

- [ ] **Step 6: Add prompt editor UI**

In the observation start area, replace the primary goal input with a full prompt editor:

```tsx
<label className={styles.formField}>
  <span>{lang === "zh" ? "观察 Prompt" : "Observation prompt"}</span>
  <textarea
    className={styles.observationPromptEditor}
    rows={12}
    value={observationPromptInput}
    onChange={(event) => setObservationPromptInput(event.target.value)}
    spellCheck={false}
  />
</label>
<div className={styles.observationPromptActions}>
  <Button
    type="button"
    size="sm"
    variant="flat"
    onPress={() => setObservationPromptInput(defaultObservationPrompt || buildDefaultObservationPrompt(lang))}
  >
    {lang === "zh" ? "恢复默认 Prompt" : "Reset prompt"}
  </Button>
  <span className={styles.mutedText}>{lang === "zh" ? "后端仍强制 0 工具策略，Prompt 不能授予工具权限。" : "The backend still enforces no-tool policy; prompt text cannot grant tools."}</span>
</div>
```

Expected: the first editable control for observation setup is the prompt editor. Duration and tick controls stay available as run parameters, but the user does not need to edit a separate target/goal field.

- [ ] **Step 7: Extend `SelfEvolutionTrack` props and local state**

Add props:

```ts
onAddObservationGuidance: (runId: string, content: string) => void;
observationGuidancePending: boolean;
observationGuidanceError: string;
```

Add state:

```ts
const [observationGuidanceInput, setObservationGuidanceInput] = useState("");
```

Add helpers near existing observation helpers:

```ts
function observationMetricValue(value: number | undefined, fallback = "0") {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : fallback;
}

function observationEventKind(event: SelfObservationRunEvent) {
  return event.type || event.event || "status";
}

function observationEventTone(event: SelfObservationRunEvent) {
  const kind = observationEventKind(event);
  if (kind.includes("compression")) return "compression";
  if (kind.includes("guidance")) return "guidance";
  if (kind.includes("resume") || kind.includes("interrupted")) return "resume";
  if (kind.includes("violation")) return "danger";
  if (kind.includes("tick")) return "tick";
  return "neutral";
}
```

- [ ] **Step 8: Add metric grid fields**

In the observation runtime panel, render these metrics from `observationRun`:

```tsx
<div className={styles.observationMetricGrid}>
  <div>
    <span>{lang === "zh" ? "有效" : "Effective"}</span>
    <strong>{observationMetricValue(observationRun?.effectiveRunSeconds)}s</strong>
  </div>
  <div>
    <span>{lang === "zh" ? "剩余" : "Remaining"}</span>
    <strong>{observationMetricValue(observationRun?.remainingEffectiveRunSeconds)}s</strong>
  </div>
  <div>
    <span>tick</span>
    <strong>{observationMetricValue(observationRun?.tickCount)}</strong>
  </div>
  <div>
    <span>{lang === "zh" ? "压缩" : "Compression"}</span>
    <strong>{observationMetricValue(observationRun?.compressionCount)}</strong>
  </div>
  <div>
    <span>{lang === "zh" ? "恢复" : "Resume"}</span>
    <strong>{observationMetricValue(observationRun?.resumeCount)}</strong>
  </div>
  <div>
    <span>{lang === "zh" ? "引导待消费" : "Guidance pending"}</span>
    <strong>{observationMetricValue(observationRun?.pendingGuidanceCount)}</strong>
  </div>
</div>
```

Keep the existing `工具 0` and `worktree no` indicators visible in observation mode.

- [ ] **Step 9: Add guidance input**

In observation mode, below metrics and above timeline:

```tsx
{observationRun?.runId && observationRunActive ? (
  <form
    className={styles.observationGuidanceForm}
    onSubmit={(event) => {
      event.preventDefault();
      const content = observationGuidanceInput.trim();
      if (!content || !observationRun?.runId) return;
      onAddObservationGuidance(observationRun.runId, content);
      setObservationGuidanceInput("");
    }}
  >
    <label className={styles.formField}>
      <span>{lang === "zh" ? "中途引导" : "Guidance"}</span>
      <textarea
        className={styles.textArea}
        rows={2}
        value={observationGuidanceInput}
        onChange={(event) => setObservationGuidanceInput(event.target.value)}
        placeholder={lang === "zh" ? "输入引导，不会重置当前观察 run" : "Add guidance without resetting the run"}
      />
    </label>
    <Button
      type="submit"
      size="sm"
      variant="flat"
      isDisabled={observationGuidancePending || !observationGuidanceInput.trim()}
      startContent={observationGuidancePending ? <LoaderCircle size={15} className={styles.spinning} /> : <ArrowUpRight size={15} />}
    >
      {lang === "zh" ? "加入引导" : "Add guidance"}
    </Button>
  </form>
) : null}
{observationGuidanceError ? <p className={styles.errorText}>{observationGuidanceError}</p> : null}
```

- [ ] **Step 10: Render event markers by type**

In the observation event timeline map, add:

```tsx
const eventKind = observationEventKind(event);
const eventTone = observationEventTone(event);
```

Use a stable class:

```tsx
<div key={`${event.timestamp}-${eventKind}-${index}`} className={`${styles.observationEventItem} ${styles[`observationEventItem_${eventTone}`]}`}>
  <strong>{eventKind}</strong>
  {eventPreview ? <span className={styles.compactPreviewText}>{eventPreview}</span> : null}
  <span className={styles.mutedText}>{compactTimestamp(event.timestamp)}</span>
</div>
```

Add styles in `SelfEvolutionTrack.styles.ts`:

```ts
observationGuidanceForm: "grid min-w-0 gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
observationPromptEditor: "min-h-[260px] w-full resize-y rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-raised)] px-3 py-2 font-mono text-sm leading-6 outline-none focus:border-[var(--accent-cool)]",
observationPromptActions: "flex flex-wrap items-center gap-2",
observationEventItem_tick: "border-l-[3px] border-l-[color-mix(in_srgb,var(--accent-cool)_50%,var(--vui-border-subtle))]",
observationEventItem_compression: "border-l-[3px] border-l-[color-mix(in_srgb,var(--accent-warm)_55%,var(--vui-border-subtle))]",
observationEventItem_guidance: "border-l-[3px] border-l-[color-mix(in_srgb,var(--accent-success)_45%,var(--vui-border-subtle))]",
observationEventItem_resume: "border-l-[3px] border-l-[color-mix(in_srgb,var(--accent-info)_50%,var(--vui-border-subtle))]",
observationEventItem_danger: "border-l-[3px] border-l-[color-mix(in_srgb,var(--accent-danger)_55%,var(--vui-border-subtle))]",
observationEventItem_neutral: "border-l-[3px] border-l-[var(--vui-border-subtle)]",
```

- [ ] **Step 11: Run frontend static tests**

Run:

```powershell
npm --prefix web run test -- SelfEvolutionTrack.static.test.ts EvolutionRoute.layout.test.ts evolutionWorkspaceCache.test.ts
```

Expected: PASS.

- [ ] **Step 12: Commit Task 6**

Run:

```powershell
git status --short --branch
git add -- web/src/api/types.ts web/src/routes/EvolutionRoute.tsx web/src/routes/SelfEvolutionTrack.tsx web/src/routes/SelfEvolutionTrack.styles.ts web/src/routes/SelfEvolutionTrack.static.test.ts
git commit -m "feat(web): show observation time-machine controls"
```

Expected: commit succeeds with only Task 6 files staged.

---

### Task 7: Runtime Evidence, API Contract Sweep, And Final Validation

**Files:**
- Modify only files touched by Tasks 1-6 if validation exposes defects.
- Test: focused backend and frontend suites.

**Interfaces:**
- Consumes all prior tasks.
- Produces branch ready for local review, Launcher refresh, and later merge decision.

- [ ] **Step 1: Add runtime-scene assertions for critical state changes**

In `tests/test_self_evolution_control_service.py`, add:

```python
def test_self_observation_records_runtime_scene_events(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(
        service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded.append({"args": args, "kwargs": kwargs}),
    )
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")

    started = service.start_self_observation_run({"mode": "time_machine", "prompt": "观察目标：观察日志\n无法验证：保持 0 工具。", "durationSeconds": 60})
    service._begin_self_observation_tick(started["runId"], now="2026-07-06T00:00:00+00:00")
    service._complete_self_observation_tick(
        started["runId"],
        started_at="2026-07-06T00:00:00+00:00",
        ended_at="2026-07-06T00:00:16+00:00",
        message="日志观察",
        summary="日志观察",
    )

    event_codes = [str(item["args"][2]) for item in recorded if len(item["args"]) >= 3]
    assert "self_observation.run_started" in event_codes
    assert "self_observation.tick_completed" in event_codes
```

Implement a small helper in `core/web/services/self_evolution_control_service.py`:

```python
def _record_self_observation_scene_event(
    phase: str,
    event_code: str,
    *,
    run_id: str,
    snapshot: dict[str, Any] | None = None,
    message: str = "",
    outcome: str = "observed",
    level: str = "info",
    fields: dict[str, Any] | None = None,
    lifecycle: bool = True,
) -> None:
    payload = snapshot if isinstance(snapshot, dict) else {}
    event_fields = {
        "runKind": "self_observation_run",
        "runId": str(run_id or "").strip(),
        "status": str(payload.get("status") or "").strip(),
        "effectiveRunSeconds": int(payload.get("effectiveRunSeconds") or 0),
        "remainingEffectiveRunSeconds": int(payload.get("remainingEffectiveRunSeconds") or 0),
        "tickCount": int(payload.get("tickCount") or 0),
        "compressionCount": int(payload.get("compressionCount") or 0),
        "resumeCount": int(payload.get("resumeCount") or 0),
        "guidanceCount": int(payload.get("guidanceCount") or 0),
    }
    if fields:
        event_fields.update(fields)
    try:
        record_runtime_scene_event(
            "self_observation",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields=event_fields,
            lifecycle=lifecycle,
        )
    except Exception:
        return
```

Call it after `run_started`, `tick_completed`, `runtime_interrupted`, `force_resume_started`, `user_guidance_added`, `compression_applied`, `boundary_violation_detected`, and `run_completed` state changes. Use bounded fields only; do not log full prompt, full output, full guidance content, secrets, or provider payload.

- [ ] **Step 2: Run focused backend service tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation" -q
```

Expected: PASS.

- [ ] **Step 3: Run route contract tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_evolution_routes.py -k "self_observation or workspace_snapshot" -q
```

Expected: PASS.

- [ ] **Step 4: Run frontend focused tests**

Run:

```powershell
npm --prefix web run test -- SelfEvolutionTrack.static.test.ts EvolutionRoute.layout.test.ts evolutionWorkspaceCache.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run frontend build**

Run:

```powershell
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 6: Run diff hygiene**

Run:

```powershell
git diff --check
git status --short --branch
```

Expected: no whitespace errors; status shows only current-task changes before any final fix commit.

- [ ] **Step 7: Commit final validation fixes if needed**

If Steps 2-6 require small fixes, stage only the touched task files:

```powershell
git add -- core/runtime_manager/evolution_store.py core/web/services/self_evolution_control_service.py core/web/routes/evolution.py web/src/api/types.ts web/src/routes/EvolutionRoute.tsx web/src/routes/SelfEvolutionTrack.tsx web/src/routes/SelfEvolutionTrack.styles.ts web/src/routes/SelfEvolutionTrack.static.test.ts tests/test_self_evolution_control_service.py tests/test_web_evolution_routes.py
git commit -m "test: validate self-observation time machine"
```

Expected: commit succeeds, or no commit is needed because previous task commits already contain all fixes.

- [ ] **Step 8: Browser smoke after merge and Launcher refresh**

After the branch is merged locally into `main` and Launcher refresh passes the active-work guard:

1. Open `/evolution?track=self`.
2. Select `自主观察`.
3. Start a time-machine observation by editing the prompt to include `观察目标：观察 Agent 如何在连续状态下保持 prompt` and duration `60`.
4. Confirm UI shows `工具 0`, `worktree no`, effective time, remaining time, tick count, compression count, resume count, and pending guidance.
5. Submit guidance `下一段重点检查是否仍记得原 prompt`.
6. Confirm timeline shows `user_guidance_added`, then after a tick `user_guidance_consumed`.
7. Confirm compression and resume events render as markers in the event rail and not as ordinary assistant bubbles when test fixtures or real runtime produce those events.
8. Confirm terminate ends the run and a later active route read does not force-resume it.

Expected: the observation surface stays operational, compact, and no-tool; isolated development mode still shows worktree/review controls only in its own mode.

- [ ] **Step 9: Implementation closeout fields**

When implementation completes, the closeout message to the operator must include:

```text
Branch:
Worktree:
Commit SHA:
Changed files:
Validation:
Launcher refresh: required before real UI verification
Project memory: current design/plan rounds intentionally skip project-memory records by user instruction; implementation round follows the user's then-current instruction and project standard
Version impact: minor recommended because this adds a compatible runtime capability and API/UI surface; release steward decides whether to group it
```

---

## Self-Review

Spec coverage:

- 0-tool boundary: Task 1 preserves `allowedTools=[]`, forbidden request fields, no worktree fields, and Task 6 prevents tool UI affordances.
- Reuse-first behavior: the reuse table and per-task Step 0 gates require local component reuse before new abstractions, and require read-only component research before difficult parts proceed.
- Effective runtime: Task 2 adds tick accounting, remaining time, and wall-clock gap exclusion.
- Context compression: Task 5 records compression markers and checkpoint summaries without turning them into assistant bubbles.
- Runtime recovery: Task 3 scans persisted active observation runs and force-resumes only non-terminal interrupted runs.
- User guidance: Task 4 adds queued guidance, boundary classification, consumed events, and API route.
- Same run continuity: Tasks 1-5 use a single persisted run snapshot and event tail across ticks, compression, guidance, and recovery.
- Conversation-chain preservation: Task 5 keeps `conversationSessionId`, messages, compression markers, resume markers, guidance markers, and terminal markers available without generating a new analysis report.
- UI: Task 6 exposes metrics, guidance, and markers while keeping observation mode separate from development controls.

Placeholder scan:

- The plan contains no unresolved placeholder markers.
- Temporary helpers in Task 2 are explicit compatibility bodies and are replaced by Tasks 4 and 5.

Type consistency:

- Backend event fields match optional frontend `SelfObservationRunEvent` extensions.
- Backend run metrics match optional frontend `SelfObservationRun` extensions.
- Route action names match `SelfObservationRunActionRequest`.
- Guidance route payload matches `SelfObservationGuidanceRequest`.

Risk notes:

- This implementation touches runtime lifecycle, API DTOs, frontend UI, and a shared hot file; execution should be treated as `HIGH_RISK`.
- `web/src/api/types.ts` requires serialized scope claim before implementation.
- The durable run store is the canonical source; memory cache must never become the recovery source of truth.
- Launcher refresh is required before real UI verification, but not for this plan document.
