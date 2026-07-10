# Chat Room Stop Reconciliation Design

## Goal

Ensure an Agent group-chat round cannot remain indefinitely visible as `stopping` after its background worker disappears, the backend restarts, or Launcher force-stops the persisted WorkRun.

The user-visible result is that room detail, active-work guards, and WorkRun snapshots converge on one terminal state without requiring direct edits to `chat_rooms.json`.

## Confirmed Failure

The observed round `round-20260710-023052-932954-d4bc7161` had two conflicting persisted states:

- `workspace/chat_rooms/chat_rooms.json` kept the round and room at `stopping`, retained `activeRoundId`, and left `finishedAt` empty.
- `.runtime/runtime-manager/work_runs/chat_room_round/...` recorded the same round as `stopped` with `runtimeStatus=force_stopped` and `forceStopReason=launcher_force_stop_button`.

The current room API and active-work probe derive active rounds from the chat-room store, while WorkRun summary surfaces derive terminal status from the WorkRun store. After restart, no in-memory round controller or background worker exists to call `_stopped_chat_room_round_detail`, so the two stores never reconcile.

## Requirements

1. A terminal WorkRun snapshot must repair a matching persisted `running`, `queued`, or `stopping` chat-room round.
2. A persisted active round from an earlier backend process must be treated as orphaned when the current process has no matching round controller.
3. A normal active round with a live in-process controller must not be repaired or interrupted.
4. Reconciliation must clear `activeRoundId`, set `finishedAt`, choose a stable room status, and preserve existing messages and bounded diagnostic context.
5. Reconciliation must be idempotent and safe to invoke from multiple read/probe paths.
6. The repair must use service APIs and atomic store writes; no frontend-only masking or direct operator data edit is acceptable.

## Non-Goals

- Do not redesign group-chat scheduling, participant execution, or provider retry behavior.
- Do not replace cooperative stop handling for a live worker.
- Do not add an arbitrary elapsed-time timeout.
- Do not modify frontend status rendering.
- Do not rewrite historical terminal rounds or remove room history.
- Do not make WorkRun storage the sole owner of full room content.

## Approaches Considered

### Selected: service-level reconciliation

Add one focused reconciliation path in `chat_room_service` that compares active room records with the matching WorkRun snapshot and the current process's controller registry. Reuse it before returning room detail and before reporting active chat-room work.

This covers Launcher force-stop, backend restart, and stale probes while retaining cooperative stopping for a live worker.

### Rejected: Launcher-only cascade

Updating `chat_rooms.json` only during Launcher force-stop would fix the observed command path but would not cover crashes, abrupt restarts, or an already orphaned record.

### Rejected: time-based stopping timeout

A fixed timeout cannot distinguish a genuinely slow current speaker from an abandoned worker and would create false terminal states.

## Source Of Truth

The two stores own different facts:

| Fact | Canonical source |
| --- | --- |
| Room membership, messages, active round pointer, user-facing room state | chat-room store |
| Runtime-manager terminal decision such as `force_stopped` | WorkRun snapshot |
| Whether a background round belongs to the current backend process | in-memory round controller registry |

Reconciliation follows this precedence:

1. Existing terminal chat-room state remains unchanged.
2. A matching terminal WorkRun snapshot is authoritative for runtime termination.
3. An active chat-room record without a current-process controller is an interrupted/orphaned round and must become terminal.
4. An active chat-room record with a current-process controller remains active, including cooperative `stopping`.

## Backend Design

Add a focused internal reconciliation helper in `core/web/services/chat_room_service.py`.

For every room whose `activeRoundId` points to a round in `RUNNING_ROUND_STATUSES`, the helper will:

1. Load the matching WorkRun snapshot.
2. Check whether the round controller registry contains that round id.
3. Leave the round unchanged when a controller exists and the WorkRun is still active.
4. Repair the round when the WorkRun is terminal or when no current-process controller exists.
5. Set round status to `stopped`, write a bounded recovery summary, preserve messages, set `updatedAt` and `finishedAt`, set the room to `ready`, and clear the matching `activeRoundId`.
6. Persist the room store once for the reconciliation batch.
7. Persist the reconciled WorkRun as terminal only when its snapshot is not already terminal.
8. Record a bounded runtime-scene event describing the repair source without logging prompts or message bodies.

The helper returns enough metadata for tests and diagnostics but callers do not need to expose a new public DTO.

## Invocation Points

Reconciliation will run at the smallest existing ownership boundaries:

- before returning chat-room detail, so opening the affected room repairs its visible state;
- before listing active chat-room WorkRuns, so Launcher guards do not keep reporting a ghost task;
- before full, conversation-index, and compact room-list projections, so no list surface can continue displaying stale aggregate status.

All calls use the same idempotent helper. No frontend polling behavior changes.

## State Mapping

| Condition | Reconciled round | Reconciled room | Summary source |
| --- | --- | --- | --- |
| WorkRun `stopped`, `cancelled`, or runtime `force_stopped` | `stopped` | `ready` | WorkRun stop/force-stop reason when available |
| WorkRun `failed` or `failed_*` | `failed` | `failed` | bounded WorkRun failure reason |
| WorkRun still active, no current controller after process restart | `stopped` | `ready` | backend restart/orphan recovery reason |
| WorkRun active and controller present | unchanged | unchanged | unchanged |

The repair intentionally uses the existing room terminal vocabulary `stopped` rather than adding a new persisted status.

## Concurrency And Error Handling

- Reconciliation reads and writes the chat-room store under `_CHAT_ROOM_LOCK`.
- Controller lookup uses `_CHAT_ROOM_ROUND_CONTROLS_LOCK` through a small helper.
- WorkRun reads occur outside the chat-room write critical section where practical; the final state is rechecked under lock before mutation.
- Missing or unreadable WorkRun snapshots do not block orphan recovery when the controller is absent.
- WorkRun persistence and runtime-scene logging are best-effort follow-up operations; room-store convergence remains the primary repair.
- Repeated calls observe terminal state and perform no additional writes.

## Tests

Add focused service tests using isolated chat-room and WorkRun stores:

1. A room at `stopping` with a matching `force_stopped` WorkRun is repaired to `stopped`, clears `activeRoundId`, and no longer appears in the active-work list.
2. A persisted active round with no current-process controller is repaired as an orphan after simulated restart.
3. A `stopping` round with a live controller and active WorkRun remains `stopping`.
4. Reconciliation is idempotent and preserves existing messages.
5. If the route layer has independent behavior, a focused route test proves `GET /api/chat-rooms/{roomId}` returns the reconciled terminal state.

TDD order is mandatory: each regression test must fail for the stale-state reason before production code is added.

## Logging Decision

This runtime lifecycle repair requires bounded runtime-scene evidence. Record a lifecycle event such as `chat_room.round.orphan_reconciled` with:

- room id and round id through existing event correlation;
- previous status;
- reconciliation source (`terminal_work_run` or `missing_process_controller`);
- WorkRun status/runtime status;
- message and speaker counts;
- no prompt, message body, provider payload, or secret.

## Validation

- Focused `pytest` for chat-room service and route regression cases.
- Existing chat-room service/route suites.
- `git diff --check`.
- A read-only runtime/API smoke after Launcher refresh, only after active-work guards allow refresh.

## Runtime Refresh And Existing Data

The code change affects the running backend and active-work guard behavior, so Launcher refresh is required before runtime verification. If another active task blocks refresh, report the standard active-work message and defer the smoke test.

No migration script is required. After deployment, the first relevant room-detail or active-work query will reconcile the observed stale record through the service path.

## Completion Criteria

- The known split-brain fixture converges to terminal room and WorkRun state.
- Restart-orphaned rounds no longer remain active indefinitely.
- Live cooperative stopping remains unchanged.
- Focused tests pass and the diff contains no unrelated changes.
- Root `main` remains untouched until scoped local integration gates pass.
