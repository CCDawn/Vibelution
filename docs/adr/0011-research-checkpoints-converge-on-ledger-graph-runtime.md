# ADR 0011 · Research Checkpoints Use One Ledger Graph Runtime

## Status

Accepted (2026-09-05).

## Decision

Challenge Cup research runs use the canonical `challenge-cup-research@3.0.0`
definition and the Ledger-backed LangGraph runtime. A run has one checkpoint
identity: `threadId == runId` for creation, resume, reset, and fork children.

The workflow definition registry must resolve the exact pinned
`workflowVersionId` and `structureHash`. Query and mutation paths fail with
`workflow_definition_unavailable` when that identity is absent, unknown, or
drifted; they never substitute another topology.

Knowledge collection runs as the independent
`challenge-cup-knowledge-sideflow@1.0.0` child workflow. Its mailbox and
handoff evidence do not create a second main-flow checkpoint or transcript.

## Consequences

- `hypothesis_design` always continues to `protocol_design`.
- Checkpoint schema v4 removes obsolete early-terminal channels.
- Reset and fork operations address the same run identity used by execution.
- Historical topology snapshots and compatibility fallbacks are not loaded.
- Existing runtime data with a different identity must be archived or removed
  explicitly; it is not migrated implicitly.

## Verification

Definition snapshot equality, strict registry resolution, checkpoint
create/resume/fork/reset identity, the hypothesis-to-protocol successor, and
knowledge-sideflow independence are covered by the research workflow tests.
