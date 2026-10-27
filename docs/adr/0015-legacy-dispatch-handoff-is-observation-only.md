# ADR 0015 · Legacy Dispatch Handoff Is Observation Only

## Status

Accepted (2026-10-27), following the user's explicit selection of receipt
observation with fresh authorization for controls. Refines the migration
handoff in [ADR 0012](0012-launcher-owns-personal-assistant-runtime.md), while
retaining the native SDK boundary in
[ADR 0013](0013-launcher-assistant-reuses-native-project-sdk.md).

## Context

Old personal-assistant A2A dispatches execute in the target project's native
Session/Turn. They have no existing transferable external-task lease. Treating
delivery success as task completion or rebuilding the request under a new
owner could duplicate work and inherit temporary permissions incorrectly.
Launcher must still observe unfinished work and late replies after its own
restart, without keeping a second scheduler or changing ordinary Sessions.

## Decision

1. The original Session/Turn remains the execution authority. Launcher adopts
   only a fixed whitelist of legacy message references through a distinct
   `legacy:receipts:read` grant. Native tasks, leases and workers are not
   recreated, renewed or transferred by this handoff.
2. Creation binds the original operator subject, project/instance, PA identity,
   physical source authority, registry fingerprint, target Session and proved
   native Turn references. Identical registry IDs in another workspace cannot
   substitute for the selected source. The existing Store persists immutable
   intent/proof and readback; unknown recovery never recreates dispatch work.
3. Cancel, continue and approve require new native authorization in the active
   project/Session scope. Old pending approvals, process windows and temporary
   Session grants are never rebound or extended. Saved old subjects retain
   their exact scopes until an explicit governed upgrade.
4. History is retained in a separate assistant-scoped immutable archive using
   native Journal parsing/projection. Imported text and tool results are
   untrusted sources, not new instructions. Original IDs/bytes remain; no
   ordinary Session admission, worker, Journal or transcript owner changes.
5. Stable snapshots do not establish source quiescence. Keep the old receipt
   address active until late-delivery semantics, remaining data promotion and
   real-model/package acceptance are verified. This decision does not authorize
   formal-data migration, installation, deletion or platform PA retirement.

## Alternatives

- Transfer the old execution lease: unavailable for these Session/Turn A2A
  operations and would require a new native ownership protocol.
- Re-dispatch with a new task ID: rejected because it can execute work twice.
- Copy temporary approvals into Launcher: rejected because authority is bound
  to the old actor, Session and action context.
- Keep a project PA as the permanent proxy: rejected by the settled Launcher
  ownership decision and its duplicate-maintenance cost.

## Consequences

The same SDK, native execution, journals and existing intent store keep their
roles, reducing duplicated state and maintenance. Receipt-only authorization
requires a small additive contract and explicit source proofs. Old work can
remain unresolved or require fresh control approval; observing a completed
Turn does not prove business-task completion. Old source retirement remains a
separate acceptance step rather than an effect of archive import.
