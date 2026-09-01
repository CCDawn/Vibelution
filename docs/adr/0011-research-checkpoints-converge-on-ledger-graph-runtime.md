# ADR 0011 · Research Checkpoints Converge On The Ledger Graph Runtime

## Status

Proposed (2026-08-31). Design-review input; not an accepted decision yet.

## Context

The research workflow persists LangGraph checkpoints into one SQLite store
(`core/research/workflow/checkpoint_store.py::open_sqlite_checkpointer` →
`checkpoints.sqlite`) through **two parallel structures**:

- **Control-graph path (Path A).** `ChallengeCupState`
  (`core/research/workflow/challenge_cup_graph.py:31`) compiled by
  `challenge_cup_graph`, driven by the four lifecycle functions in
  `core/web/services/team_workflow/research_runtime/checkpoint_lifecycle.py`
  (`prepare_initial_checkpoint`, `latest_checkpoint_id`,
  `advance_checkpoint`, `fork_checkpoint_at_node`). Thread id convention:
  `thread-{runId}` (`run_creation.py:685`, `service.py:820`, `run_fork.py:82`,
  `evidence_remediation_fork.py:250`, `iteration_revision_fork.py:50`).
  Its remaining producers/consumers are the transitional JSON facade
  (`service.py`, `node_completion`, `human_task_resolution`, `run_fork`,
  `evidence_remediation_fork`, `iteration_revision_fork`) — and, still today,
  the **formal** Ledger run creation (`run_creation.py`, "Create a WorkflowRun
  in the Ledger (T8; no JSON writer)"), which seeds a `thread-{runId}` initial
  checkpoint for every new formal run.
- **Formal graph runtime path (Path B).** `ChallengeCupGraphState` +
  `ChallengeCupGraphCoordinator`
  (`core/research/workflow/challenge_cup_runtime.py`), driven by
  `GraphDispatchWorker` / `WorkflowCommandService` / `CheckpointForkWorker`,
  with forks routed through `fork_coordinator.py` outside Ledger
  transactions. Thread id convention: `threadId == runId`
  (`challenge_cup_runtime.py:10`, `fork_coordinator.py:1-5`,
  `command_service.py:1656`). This schema carries the run identity, scope
  binding, `PendingAction`/`ExecutionReceipt` identity, aggregate
  `node_attempts`, and the `checkpoint_version` stamp.

### Observed drift

1. **Silent drop of undeclared channels.** LangGraph 1.2.10 discards state
   writes for channels that are not declared on the graph schema. Commit
   6df9c2b6a had to declare `parent_run_id`, `binding_snapshot_id`,
   `budget_policy_hash` and `evidence_remediation_contract` on **both**
   schemas; before that, fork contracts never reached child checkpoints and
   `build_pending_action` read empty binding/budget identity
   (`challenge_cup_graph.py:41-48`). Every future channel must be declared
   twice; missing one side silently drops writes again. This is the concrete
   mechanism by which the dual schemas drift.
2. **Two threads per formal run.** `run_creation.create_run` seeds a
   `thread-{runId}` initial checkpoint that the formal runtime never advances
   (the coordinator drives the `{runId}` thread), so every Ledger run carries
   a dead second thread in the same store. Run records store
   `threadId=thread-{runId}` while reset inventory
   (`challenge_cup_reset_live_adapter.py:458-483`) requires
   `runId == threadId` for canonical authority and admits
   `thread-{workflowRunId}` only as a legacy convention backed by artifact
   proof — new formal runs sit on the wrong side of that gate.
3. **Cross-path reads.** `runtime_factory.py:197` wires the formal revise
   offer resolver to Path A's `latest_checkpoint_id(run.threadId)`
   (`query_service.py:114`), so root-run revise fork bases resolve against
   the stale, never-advanced `thread-{runId}` thread instead of the live
   formal thread. The documented intent ("resolve the thread's latest durable
   checkpoint") and the effective behavior (always the node-0 initial
   checkpoint) already disagree.
4. **Channel semantics are subtle.** The retry path's last-value split
   finding (`challenge_cup_runtime.py:706-714`,
   `INVALID_CONCURRENT_GRAPH_UPDATE`, discovered on golden-sample experiment
   SCI-096) shows how easily checkpoint channel semantics break; maintaining
   two schemas doubles the surface for this defect class.

### Stopgap already merged (6df9c2b6a)

`CHALLENGE_CUP_CHECKPOINT_VERSION = 2` (`challenge_cup_runtime.py:52`) is
stamped on formal writes; `checkpoint_values_discarded()`
(`challenge_cup_runtime.py:1308`) reports mismatched threads as absent so
decision callers rebuild from the Ledger attempt authority. Residuals:

- an **int counter** can collide with historical values across semantic
  changes of the same number;
- Path A checkpoints carry **no** `checkpoint_version`, so the discard gate
  cannot see them at all.

**User ruling:** old checkpoints are not migrated. A version mismatch means
discard; the Ledger is the rebuild authority (start/retry/entry paths).

## Decision

1. **Single schema: `ChallengeCupGraphState`.** It is the only checkpoint
   schema going forward; `ChallengeCupState` is retired (deleted together
   with the transitional facade, or reduced to an alias of the formal schema
   in the interim). Rationale: the Ledger is the run authority (composition
   root `runtime_factory.py`, migration gate in
   `start_production_workflow_runtime`, reset inventory admits only Ledger
   rows), and everything that makes checkpoints safe — five-way scope
   binding gates, action/receipt identity, aggregate `node_attempts`,
   version stamping and discard semantics, crash-replay idempotent fork —
   exists only on the formal schema, which already declares a superset of
   the control schema's channels. A shared-channel-subset schema was
   considered and rejected: it keeps two declaration points alive and
   re-creates the exact drift 6df9c2b6a had to patch.
2. **Single fork implementation:
   `ChallengeCupGraphCoordinator.fork_from_checkpoint`
   (`challenge_cup_runtime.py:1049`), invoked only through
   `fork_coordinator.py`** (after the Ledger commit, crash-replay
   idempotent). `fork_checkpoint_at_node` retires with the JSON facade. It
   cannot simply be "upgraded": it has no run identity to re-point, no scope
   binding to validate, and no version to stamp — the guarantees would have
   to be reinvented there, which is the duplication this ADR removes.
3. **Single thread-id convention: `threadId == runId`**, including run
   creation records. The pre-created `thread-{runId}` initial checkpoint is
   abolished: formal run creation stops writing a second thread, and the
   revise offer resolver reads the coordinator snapshot of `{runId}` (same
   fail-soft contract). This also aligns run records with the reset
   inventory's `runId == threadId` pairing requirement.
4. **Old checkpoints: no migration, discard on mismatch, Ledger rebuilds.**
   Schema identity becomes a **string label** (adopt as `"cc-graph-v1"`,
   bump on every channel-set change) compared by equality in
   `checkpoint_values_discarded`, eliminating the int-counter collision
   window left by 6df9c2b6a. Threads without a version label (Path A
   writes) are foreign to the formal reader and are discarded/rebuilt the
   same way.
5. **No dual-mode flag.** Convergence lands per phase below; the
   transitional facade keeps functioning during the transition, but no
   production formal path reads or writes Path A threads once the phases
   land.

## Staged implementation

Each phase is independently mergeable and revertible; none requires data
migration (the discard ruling covers every stale thread).

### Phase 1 — thread-id unification + version label

- `CHALLENGE_CUP_CHECKPOINT_VERSION` becomes the string label
  `"cc-graph-v1"`; `checkpoint_values_discarded` compares labels.
- `run_creation.create_run` stops calling `prepare_initial_checkpoint`;
  run records store `threadId = runId`; the initial `checkpointId` field
  stays shape-compatible (empty until the first formal checkpoint exists).
- `runtime_factory` revise resolver re-points to
  `coordinator.snapshot(runId)` with unchanged fail-soft behavior.
- Boundary: `run_creation.py`, `run_lifecycle.py`, `runtime_factory.py`,
  `challenge_cup_runtime.py` (label), their tests. No fork code changes.
- Risk: runs whose formal thread has no checkpoint yet resolve no revise
  offer (fail-soft covers it); tests asserting the `thread-{runId}` shape
  need updating. Rollback: revert the commits; Path A seeding resumes; stale
  threads remain harmless under the discard ruling.

### Phase 2 — fork implementation merge

- Fork triggers that survive the formal world (human-gate correction,
  evidence remediation, iteration revision) move onto Ledger fork commands
  handled by `CheckpointForkWorker` / `fork_coordinator`
  (`execute_checkpoint_fork`), so child runs are Ledger records and forks
  run after the commit with crash-replay idempotency.
- `fork_checkpoint_at_node` keeps serving only the transitional JSON facade
  and is deleted together with it (or at Phase 3 if the facade outlives this
  ADR).
- Boundary: fork call sites, `fork_coordinator.py`, `checkpoint_fork_worker`,
  fork tests. No schema changes.
- Risk: facade forks operate on `thread-{runId}` parents that exist only in
  the facade world; each trigger needs an explicit owner decision
  (Ledger command vs facade-scoped) and must not be silently re-pointed.
  Rollback: keep both implementations during the transition; revert per
  call site.

### Phase 3 — schema convergence and lifecycle retirement

- `challenge_cup_graph` compiles over `ChallengeCupGraphState` (or
  `ChallengeCupState` is deleted with the facade); the four
  `checkpoint_lifecycle` functions are deleted or become thin wrappers over
  the coordinator. One declaration point for channels remains.
- Boundary: `challenge_cup_graph.py`, `checkpoint_lifecycle.py` and their
  direct tests
  (`test_research_workflow_challenge_cup_graph.py`,
  `test_knowledge_sideflow_run.py`, `test_research_workflow_ux_bugfixes.py`,
  `test_research_workflow_bounded_auto_revision.py`,
  `test_research_workflow_v21_iteration_governance.py`,
  `test_research_workflow_graph_fork_lineage.py`,
  `test_research_workflow_interrupt_checkpoint_recovery.py`).
- Risk: facade-era tests that drive the control graph directly need porting
  or retirement with the facade. Rollback: per commit; discard semantics
  rebuild threads from the Ledger.

## Consequences

Positive:

- One channel declaration point ends the silent-drop drift class; a 6df9c2b6a
  -shaped patch becomes structurally unnecessary.
- One thread per run with `runId == threadId`; run records, Ledger rows and
  reset inventory authority finally agree.
- Fork lineage, scope binding and schema identity have a single
  implementation to test, heal and evolve.
- String version labels make schema identity self-describing inside the
  store and remove the int-collision window.

Negative / costs:

- The transitional JSON facade needs coordinated retirement; until then its
  forks and its `thread-{runId}` threads remain facade-scoped and invisible
  to the formal reader (discarded on read).
- Revise-offer semantics change deliberately: the root-run fork base moves
  from the never-advanced node-0 checkpoint to the live formal thread's
  latest checkpoint. This matches the documented resolver intent but is a
  behavior change that design review must explicitly confirm.
- Consumers reading a run record's `checkpointId` before the first dispatch
  observe an empty value until the formal checkpoint exists
  (`hypothesis_first_chain.py` checkpoint payloads, catalog run dicts).

Consumers to re-verify per phase: `runtime_factory` composition,
`query_service` revise offers, `challenge_cup_reset_live_adapter`
inventory pairing, `command_service` child-fork path (already conformant),
`hypothesis_first_chain` checkpoint payloads, and the tests listed in
Phase 3.
