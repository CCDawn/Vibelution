# Challenge workflow recovery closure plan

Status: implementing

Owner: challenge recovery coordinator

Base: local `main@a0a877ab5`

## Outcome

Restore a user-operable exit for terminal formal runs, orphaned source collection,
and multi-action recovery UI without reviving immutable terminal executions or
bypassing State V2 authorization/CAS checks.

The first delivery covers the confirmed P0/P1 deadlocks whose behavior is
already determined. It deliberately leaves two product decisions fail-closed:
choosing one branch during a formal lineage conflict, and editing/replacing
upstream material for deterministic program-delivery blockers. Those require a
separate interaction and data contract instead of guessing a winner or silently
changing research inputs.

## Reuse decision

Ranked candidates:

1. Existing Vibelution command envelope, command receipts, run-version CAS,
   scope lock, State V2 `allowedActions`, `VActionGroup`, and `VConfirmDialog`.
   Reuse and extend these owning surfaces; they already preserve authorization,
   idempotency, focus management, and one projection source.
2. Temporal's immutable execution model. Borrow only the rule that a terminal
   execution is never moved back to running: archive the old run and create a
   fresh run identity for a retry.
3. Radix/shadcn and WAI-ARIA dialog patterns. Borrow the modal confirmation,
   cancel-first focus, focus return, and pending-state lock behavior through the
   project's existing VUI wrapper.

Rejected: a second recovery API, direct ledger/storage edits from the UI,
reusing `reconcile_formal_run` for terminal runs, or copying an external workflow
engine. Each would create another writer or weaken the current safety model.

## Recovery contracts

### Terminal formal run

- `failed`, `cancelled`, and other legally archivable terminal runs expose an
  explicit confirmation-gated archive action.
- The command applies the existing terminal-to-`archived` transition with run
  version CAS and an idempotent command receipt. It never performs
  `failed|cancelled -> running`.
- Once archived, the current formal-run creation rules may create a new run with
  a new run id. Historical evidence remains readable.
- A succeeded run with missing delivery terminal writeback exposes
  `retry_program_handoff`, not `reconcile_formal_run`.
- Program-record validation failure exposes an honest recovery route (archive
  and rebuild) rather than `actions=[]`; it must not report success before
  official model evidence validates.

### Source collection

- A running request is recoverable only after durable run state plus worker/
  lease/heartbeat evidence proves it is orphaned or its terminal writeback was
  lost.
- `stop_collection` / `declare_collection_failed` re-check liveness under the
  hypothesis-first scope lock, require privileged operator authority, use State
  V2 action identity and version CAS, and record an idempotent receipt.
- A terminal child run whose request writeback is missing can replay the
  existing terminal notification; an orphan restart creates a fresh execution
  instead of pretending the old worker is still live.
- A healthy worker or live lease remains non-actionable. Reset is not broadened
  to cancel live work implicitly.

### Frontend and HTTP errors

- Render all projected commands, including disabled commands and their reasons;
  ordering remains the server's order but no action is hidden by `commands[0]`.
- Any action carrying `requiresConfirmation` opens the existing
  `VConfirmDialog`; mutation starts only after confirmation. Pending confirmation
  disables both dialog actions and destructive actions never receive initial
  focus.
- `formal_runtime` surfaces run-level recovery commands even when the action has
  no node id. Toolbar stage/status labels reflect runtime and reconciliation
  states instead of claiming convergence.
- A 412 `node_not_ready` response preserves all readiness blockers, and every
  surfaced workflow problem is rendered as a list.

## Task graph

1. Terminal command worker: command kind, handler/offer, CAS/receipt tests. It
   must not edit State V2 or hypothesis chain.
2. Collection worker: liveness evidence, terminal notification replay, orphan
   recovery commands, routes/models, and State V2 collection projection. It
   owns `hypothesis_first_state_v2.py` during parallel implementation.
3. Frontend worker: action list/confirmation, formal-runtime visibility,
   labels, blockers/problems, route error contract, focused tests and typecheck.
4. Coordinator, after 1-3 commit: integrate into this branch, then serialize the
   terminal/program State V2 projection after the collection claim is released.
   Resolve only in-scope conflicts; do not absorb SCI-003 changes until their
   owner has merged them to local main and this branch is refreshed.
5. Coordinator: record reuse evidence, run selected backend tests, focused
   Vitest, VUI contracts, TypeScript build check, diff review, closeout, and
   ff-only local-main integration.

## Verification

- Regression matrix proves: failed/cancelled run offers archive; archive is
  legal/idempotent; archived run allows a fresh run; succeeded+missing handoff
  offers retry; invalid program evidence never yields an empty recovery set.
- Collection matrix proves: live worker rejected; stale lease/heartbeat permits
  recovery; terminal notification failure is visible and replayable; repeated
  idempotency key returns the stored result; reset does not cancel healthy work.
- Frontend matrix proves: multiple enabled actions remain reachable; confirmation
  blocks direct mutation; disabled reasons and all problems render; formal
  runtime shows run-level actions; 412 includes blocker details.
- Required frontend gates: focused Vitest, VUI route/component contracts, and
  `npx tsc -b --pretty false` before any Launcher rebuild recommendation.

## Deferred follow-ups

- Formal lineage conflict needs an explicit select/abandon-branch command and
  audit record; no automatic winner selection in this delivery.
- Deterministic program blockers need a material-repair interaction contract;
  blind retry remains disabled or clearly explained.
- Hypothesis-round generation fail-closed and maintenance-fence TTL/manual
  release remain separate P2 work because the current SCI-003 owner holds the
  chain/test hot files and fence release changes runtime lifecycle governance.
- Runtime acceptance waits for the managed Launcher/backend identity mismatch to
  be repaired; offline code, contract, and build evidence are still required.
