# Chat Mode Governance Contract

Date: 2026-05-26
Owner: dialogue line

## Goal

Treat chat mode as a stable agent execution mode, not a pile of UI patches. A chat session must preserve one continuous user-agent relationship, while each chat turn is the only execution unit.

## Confirmed Scope

Phase 1 governs the chat execution core loop:

- message send
- visible reply persistence
- thought, mental model, and tool trace display
- stop and continue semantics
- latest user message edit/delete/resend semantics
- task-level pause semantics
- provider/runtime failure semantics
- lifecycle conversation subpackage logs
- minimal execution registry for main loop, LLM turn, tool trace, and mental model trace

Out of scope for phase 1:

- redesigning the whole config page
- supervised or unsupervised evolution decision logic
- research workflow UI
- full process-kill coverage for every possible external tool type

## Core Model

- `ChatSession` is the only user-visible conversation container.
- `ChatTurn` is the only execution unit.
- A single session belongs to one continuous user and one continuous agent context.
- Raw chat is evidence/candidate material only. It must not directly decide promotion, hold, rollback, training, or formal supervision outcomes.

## Turn Status Contract

Only `completed` means the user request is done.

Allowed terminal and transitional statuses:

- `completed`
- `needs_continue`
- `paused_limit`
- `stopping`
- `stopped_by_user`
- `force_stopping`
- `stop_failed`
- `failed_provider`
- `failed_runtime`
- `superseded`

UI must never present `paused_limit`, `needs_continue`, `stopped_by_user`, `failed_provider`, or `failed_runtime` as completed.

## Persistence Contract

Each `ChatTurn` must preserve three layers:

- `visible_messages`: user-visible user/assistant content.
- `trace_events`: thought, mental model, tool, state, stop, continue, and failure events.
- `turn_result`: final status, visible summary, recovery pointer, and audit paths.

Editing or deleting the latest user message and resending supersedes the affected downstream assistant answer, trace, and result. Superseded data leaves the current visible conversation but remains in audit logs.

## Continue Contract

`继续` is a resume command, not a new goal. It resumes the previous `needs_continue`, `paused_limit`, or `stopped_by_user` turn. Resume must preserve the original goal and append a resume event. It must not build prompt text by recursively prepending "continue the same user goal".

Prompt recovery may use only:

- non-superseded visible messages from the current `ChatSession`
- previous `turn_result` recovery pointer
- necessary trace summaries

It must not derive the goal from UI labels or active-task helper text.

## Mental Model Contract

The mental model is a `trace_event`, not a `visible_message`, not a `tool_call`, and not the user goal.

`mental_model_enabled` is a per-turn input option:

- enabled: the new turn may run mental model invoke and may include mental recovery summary.
- disabled: the new turn must not run new mental invoke and must not inject previous mental summaries into the prompt.
- historical mental trace remains visible in UI/audit logs either way.

## UI Contract

Assistant message UI must separate:

- thought
- mental model
- tool calls
- final response

These sections must be counted and named separately. UI must not use a generic "executed N operations" label that mixes mental model with real tools.

Tool call UI should show:

- tool name
- status
- start/end time or duration when available
- argument summary when available
- result summary
- error summary
- owner agent/subagent when available
- path to complete trace when available

Full arguments and full results should remain in safe logs/artifacts, not expanded inline by default.

## Stop Contract

Stop is not an impossible promise of physical instant termination. It is a strong cooperative cancellation contract plus bounded forced-stop tracking.

Each active `ChatTurn` must have an execution registry. Anything started or occupied by the turn must register:

- main agent loop
- LLM stream/invoke
- tool call
- shell/process when available
- subagent
- mental model invoke
- context compression
- workspace/file write
- runtime background task

On stop:

- the turn immediately enters `stopping`
- cancel tokens are broadcast to registered entries
- completed trace is preserved
- incomplete trace is marked `cancelled`
- uncontrolled residue enters `force_stopping` or `stop_failed`
- resume may only use confirmed trace and recovery pointers as evidence

## Logging Contract

There is one top-level runtime lifecycle package. Chat data lives inside its conversation subpackage:

```text
logs/runtime_scenes/<lifecycle_id>/conversations/<session_id>/<turn_id>/
  turn_manifest.jsonl
  visible_messages.jsonl
  trace_events.jsonl
  tool_calls.jsonl
  llm_events.jsonl
  execution_registry.jsonl
  turn_result.jsonl
```

Top-level `events/conversation.jsonl` remains the index stream.

Logs must write safe versions:

- redact API keys, tokens, authorization headers, passwords, cookies, and environment secrets
- preserve bounded summaries inline
- store large results as artifacts or path references
- never require UI text to reconstruct the turn

## Phase 1 Acceptance

Phase 1 is not complete until focused tests cover:

- state contract does not crash when runtime telemetry gains fields
- only `completed` is treated as complete
- thought, mental model, and tools render as separate collapsible sections
- a mental-only assistant message does not display "executed 1 operation"
- lifecycle conversation subpackage receives trace, execution registry, visible message, and turn result records
- stop/continue/edit/delete-resend behavior remains compatible with the contract
