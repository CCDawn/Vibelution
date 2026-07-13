# Codex Conversation Chain Alignment Closure Plan

**Date:** 2026-07-13
**Status:** active-plan
**Owner:** conversation-chain alignment owner
**Claim:** `claim-0511423f8554` for this planning artifact only
**Scope:** model-visible history, turn continuation, protocol projection, canonical lifecycle events, journal persistence, SSE reconciliation, and frontend single-owner rendering
**Coordinates:** `2026-07-13-canonical-llm-lifecycle-owner.md`, `2026-07-12-llm-turn-chain-recovery.md`, and `2026-07-13-codex-chat-frontend-alignment.md`
**Supersedes:** none; this plan defines the dependency and closure order across the three existing plans
**Implementation link:** implementation worktrees and claims are created per task after Task 0 reconciliation
**Validation:** focused backend and frontend contract tests, protocol payload assertions, web build, Launcher refresh, and bounded runtime-scene evidence
**Close condition:** one same-session conversation remains semantically continuous across turns and protocols, every tool and assistant item has one lifecycle identity, and the frontend renders each canonical item exactly once

## 1. Objective

Align Vibelution with Codex at the semantic and lifecycle boundaries without copying Codex's Rust runtime shape.

The required observable chain is:

```text
durable journal facts
  -> deterministic model-context projection
  -> one current user item
  -> protocol-specific wire projection
  -> canonical model/tool lifecycle events
  -> idempotent journal persistence
  -> SSE snapshot/delta reconciliation
  -> one frontend item projection
```

This plan fixes four coupled failures as one architecture problem:

1. A visible conversation can be continuous while the next LLM request loses prior assistant and tool context.
2. Tool history can be downgraded to assistant text and lose `callId` pairing.
3. `activeTask.goal` or carryover can substitute for missing transcript history and repeat a completed task.
4. Live deltas, snapshots, timeline projections, and final messages can render the same canonical fact more than once.

## 2. Locked Decisions

1. `turn_journal.jsonl` is the durable conversation fact source. `ConversationLedger` is its typed access and projection boundary, not a second store.
2. Model-visible history is rebuilt deterministically from journal facts. A fresh Agent runtime may be created per web turn, but it cannot invent or select an alternative history source.
3. Existing `SemanticMessage`, `LLMProtocolEvent`, `TurnOutcome`, and `SessionTurnItem v2` are reused. No new competing conversation DTO is introduced.
4. Tool calls and tool results remain structured through the entire chain. They are never represented as `"历史工具结果"` assistant text on the canonical path.
5. `activeTask.goal` is product and planning metadata. It cannot replace, rewrite, or seed model-visible conversation history.
6. `carryover` is an incomplete-turn overlay only. It is valid only when its `turnId` matches a non-terminal current turn.
7. Normal `"继续"` is an ordinary user message appended once after complete history. Special recovery behavior is restricted to an explicitly interrupted or failed turn.
8. Responses and Chat Completions receive the same semantic history but encode it independently. Encoded payloads and provider replay state never cross protocol routes.
9. `previous_response_id` and equivalent replay state are provider optimizations within a compatible route. They are not cross-turn memory.
10. The frontend is a reducer over canonical item identities. Streaming cells are provisional revisions of an item, not additional transcript messages.

## 3. Source Of Truth Contract

| Fact | Canonical source | Writer | Derived readers | Invalidation rule |
| --- | --- | --- | --- | --- |
| Durable user, assistant, tool, and terminal facts | `turn_journal.jsonl` | canonical journal writer | ledger, model context, session detail, diagnostics | append-only; corrections use identity and revision |
| Model-visible context | deterministic ledger projection | context assembler | Agent turn runner, protocol adapters | rebuilt for each turn from bounded journal input |
| Current submitted user item | current `turnId` journal event | session submit boundary | context assembler, UI | appended exactly once by identity |
| Incomplete tool chain | non-terminal canonical items for current `turnId` | lifecycle bridge | next invocation in the same turn | removed when the turn becomes terminal |
| Provider wire payload | selected wire adapter | Responses or Chat adapter | provider only | request-scoped; never persisted as conversation truth |
| Invocation terminal result | `TurnOutcome` | invocation bridge | Agent policy, journal bridge | exactly one terminal outcome per invocation |
| Public turn projection | `SessionTurnItem v2` | ledger/session projector | SSE and frontend | recomputed from journal and canonical live overlay |
| Visible transcript | normalized frontend item store | frontend reducer | `ConversationView` | reconcile by `ledgerSeq`, `revision`, and terminal state |
| Active task goal | session task state | task owner | status and planning UI | cannot write model history |
| Diagnostics | runtime-scene events | owning decision boundary | Agent diagnostics | bounded IDs, counts, status, and reason only |

## 4. Existing Plan Reconciliation

| Existing artifact | Retain | Replace or constrain |
| --- | --- | --- |
| Canonical LLM lifecycle owner | Canonical APIs, `LLMProtocolEvent`, `TurnOutcome`, explicit replay state, XML quarantine, idempotent journal writer | Re-audit every unchecked task against current `main`; do not replay the stale checklist blindly |
| LLM turn-chain recovery | Exact current-turn exclusion, route identity, one distinct fallback, fresh invocation identity | Replace the lossy tool-history seed contract; completed-turn carryover cannot participate |
| Codex chat frontend alignment | `SessionTurnItem v2`, terminal error items, active-layer settlement, native transcript precedence | Backend lifecycle completion is a hard dependency; layout and responsive work are not prerequisites for semantic correctness |
| Conversation observability active claim | End-to-end IDs, bounded counts, error presentation | Logging cannot become another state owner or include prompt/tool contents |
| Chat transaction telemetry active claim | Browser/backend transaction correlation | Its event identity must consume, not redefine, canonical turn and item IDs |
| Message-column alignment active claim | Visual reading-column improvements | Keep outside semantic reducer files until its claim closes |

## 4.1 Task 0 Reconciliation Snapshot

**Observed branch:** local `main`, 431 commits ahead of `origin/main` at inspection time.

**Observed worktree:** no unrelated dirty files; this untracked closure-plan artifact was the only worktree entry.

**Evidence boundary:** commit ancestry, current claim state, current source contracts, and existing test contracts were inspected. No test or Launcher command was run in Task 0, so this section does not claim fresh executable validation.

### Commit Ancestry

| Capability | Mainline evidence | Classification |
| --- | --- | --- |
| Canonical LLM lifecycle owner | `08a2683d refactor: unify canonical LLM lifecycle` | `IMPLEMENTED` |
| LLM turn-chain recovery and route isolation | `a4010c6c merge: normalize llm turn chain recovery` | `IMPLEMENTED_WITH_SUPERSEDED_HISTORY_RULE` |
| Canonical transcript phase projection | `49db2667 fix(chat): preserve canonical transcript phases` | `IMPLEMENTED` |
| Terminal active-layer settlement | `7ea16470 fix(chat): settle canonical terminal outcomes` | `IMPLEMENTED` |
| Native transcript visible single owner | `47e84bea fix(chat): render canonical turns once` | `IMPLEMENTED_WITH_RUNTIME_GAPS` |
| Submission, turn, and tool identity correlation | `b466df8a`, `e9ba927c`, `8d8363f9` | `IMPLEMENTED` |
| Failure observability | `7c2a1ff4 feat(chat): correlate turn failure diagnostics` | `IMPLEMENTED_CODE_CLAIM_OPEN` |
| Live and settled tool-card dedupe | `79aa0939`, `af9ca0e4`, `fe8fe2fa` | `IMPLEMENTED_HEURISTIC` |
| Responses HTTP tool-turn replay | `86f8bd66 fix(llm): replay Responses tool turns over HTTP` | `IMPLEMENTED` |
| Transaction telemetry | `a8aa1548 fix(chat): secure and correlate transaction telemetry` | `READY_ON_BRANCH_NOT_IN_MAIN` |

All commits except `a8aa1548` were confirmed ancestors of local `main`. The transaction telemetry branch had merged current `main` but had not been integrated back into `main`.

### Remaining Gap Classification

| Requirement | Current state | Task 0 decision |
| --- | --- | --- |
| Canonical invocation events and outcomes | Present in main | Do not rerun the old canonical lifecycle checklist |
| Exact route identity and one distinct fallback | Present in main | Retain as a protected regression contract |
| Full structured cross-turn tool history | Current tests explicitly require removing `tool_calls` and `role=tool`, then inserting `"历史工具结果"` assistant text | `CONFLICTING`; Task 1 replaces this contract test-first |
| Fresh Agent receives assembled history | `prepare_agent_turn` accepts history, but the shared single-turn runner does not forward it on its canonical request path | `MISSING`; Task 2 owns the wiring fix |
| Completed-turn continuation | Goal and carryover can still influence a new `"继续"` turn when complete history is absent | `PARTIAL`; Task 2 enforces terminal gating |
| Responses and Chat wire structure | Canonical adapters and replay tests exist | `IMPLEMENTED_PARTIAL`; Task 3 adds cross-turn semantic parity assertions |
| Canonical item lifecycle projection | Native items and terminal settlement exist | `IMPLEMENTED_PARTIAL`; Task 4 removes remaining reconstruction ownership |
| Frontend one-item reducer | Native transcript precedence exists, but recent fixes still add dedupe rules in timeline projection | `PARTIAL`; Task 5 replaces accumulated heuristics with identity/revision reconciliation |
| End-to-end context continuity | No fresh runtime evidence proves previous final answer plus tool chain reaches the next provider request exactly once | `MISSING_ACCEPTANCE`; Task 6 owns the proof |

### Claim Reconciliation

| Owner | Current evidence | Execution effect |
| --- | --- | --- |
| Conversation observability | implementation commit is in `main`, but coordination ownership remains active | do not edit its claimed files until release or explicit handoff |
| Chat transaction telemetry | implementation commit exists only on its task branch | Task 4 and Task 5 wait for merge or explicit handoff |
| Message-column alignment | implementation is in `main`; code claim is stale and memory closeout remains active | semantic work must preserve the merged layout and avoid memory-writer scopes |

### Task 0 Outcome

Task 0 is complete for planning purposes. The critical path is narrowed as follows:

```text
Task 1 structured semantic history
  -> Task 2 fresh-Agent context wiring and continuation gate
  -> Task 3 cross-turn protocol parity
  -> Task 4 canonical lifecycle closeout after active claim handoff
  -> Task 5 frontend identity reducer after telemetry integration
  -> Task 6 runtime acceptance
```

Old plan checkboxes remain historical execution instructions. They are not current status and must not be replayed without this reconciliation matrix.

## 5. Coordination Gate

Task 0 must consume or wait for these current active claims before implementation touches their files:

| Active owner | Claimed surface | Required handoff input |
| --- | --- | --- |
| `agent-agent-codex-conversation-observability` | `agent.py`, `session_service.py`, `turn_journal.py`, related tests and error presentation | merged commit or explicit handoff, event codes, identity fields, and focused test evidence |
| `agent-agent-codex-chat-transaction-telemetry` | `session_service.py`, `ChatCodingRoute.tsx`, browser telemetry, related tests | merged commit or explicit handoff and the final transaction-correlation contract |
| `agent-codex-chat-message-column-alignment` | `ConversationView` styles and tests | merged commit or explicit handoff; no semantic reducer change is allowed to overwrite its layout work |

Stale historical claims are evidence, not active blockers. Their implementation claims and plan checkboxes must be reconciled against current source before reuse.

## 6. Target Identities And Lifecycle

Canonical identity tuple:

```text
(sessionId, turnId, invocationId, iteration, itemId, revision, kind, callId)
```

Ordering identity:

```text
ledgerSeq
```

Invocation lifecycle:

```text
prepared -> streaming -> tool_calls | final_answer | incomplete | failed | cancelled
```

User-turn lifecycle:

```text
turn_started
  -> item_started
  -> item_delta*
  -> item_completed
  -> turn_completed | turn_failed | turn_interrupted
```

Required invariants:

1. One current user item exists in the provider projection.
2. Every tool result references an existing `callId`.
3. A completed turn contributes no carryover to the next turn.
4. A final answer is committed once after pending tools settle.
5. A terminal event cannot be changed by a late delta or reconnect replay.
6. A newer `revision` replaces an older item with the same identity.
7. A newer `ledgerSeq` snapshot settles and removes the matching live overlay.

## 7. Task Graph

**Split decision:** `SPLIT_REQUIRED` because backend context, provider contracts, persistence, frontend state, and runtime acceptance have distinct owners, write surfaces, and verification gates.

**Critical path:** Task 0 -> Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 5 -> Task 6

**Parallel boundary:** no runtime code tasks run in parallel through Task 4. After Task 4 publishes the stable `SessionTurnItem v2` contract, frontend reducer implementation may proceed without touching provider code. Visual layout work remains independently claim-owned.

## 8. Task Cards

### Task 0: Reconcile Current Main And Active Claims

**Observable output:** a current-state matrix marking every relevant old task as implemented, missing, superseded, or conflicting, with exact owner and commit evidence.

**Files/Boundary:** read-only inspection of the three coordinated plans, their listed source files, active claims, and focused test inventory. Only this plan may be updated during reconciliation.

**Dependencies:** active owner status and current local `main`.

**Mode:** SIMPLE.

**Verification:** source and tests confirm whether canonical APIs, route identity, explicit replay, terminal items, and frontend settlement already exist. Plan checkbox state alone is not evidence.

**Risk/Stop:** stop code implementation on any overlapping active scope until its owner merges or hands off.

### Task 1: Make Journal Projection Preserve Full Semantic History

**Observable output:** the context assembler returns bounded semantic history containing prior user messages, assistant commentary/final messages, structured tool calls, and paired tool results.

**Files/Boundary:** modify `core/chat/model_messages.py` and `core/chat/context_assembler.py`; add or update focused assertions in `tests/test_session_context_pipeline.py` and `tests/test_conversation_ledger.py`. Treat `core/chat/history_ledger.py` and `core/chat/tool_result_replacement.py` as reused contracts. Do not modify `core/chat/turn_journal.py` in this task.

**Dependencies:** Task 0.

**Mode:** BDD_TDD.

**Behavior contract:** replace tests that require complete tool calls to disappear or become `"历史工具结果"` text. Preserve complete paired chains in both persisted shapes: an assistant item with inline tool results and an assistant `tool_calls` item followed by separate `role=tool` items. Compression may summarize oversized output content but must retain role, `tool_call_id`, tool name, and call/result ordering. Only orphaned, malformed, or incomplete legacy chains may be demoted to bounded compatibility text.

**Verification:** `tests/test_conversation_ledger.py` and `tests/test_session_context_pipeline.py` assert exact semantic item sequences and current-turn exclusion by identity rather than text. Existing journal tests remain a later integration gate owned by Task 4.

**Risk/Stop:** no journal rewrite or migration of existing files. Legacy events are normalized one-way at read time and labeled compatibility when structure cannot be recovered.

#### Task 1 Locked Behavior

Primary BDD statement:

```text
Given a completed historical turn containing user input, an assistant tool call,
its matched tool result, and a final assistant answer,
when the next turn assembles model context,
then the complete paired tool chain and final answer remain ordered and structured,
and the current turn's user item is absent from seeded history.
```

Expected historical sequence:

```text
user(previous request)
assistant(tool_calls=[call-1])
tool(tool_call_id=call-1)
assistant(previous final answer)
```

Required boundaries:

1. Inline persisted tool result data is expanded into the same assistant-call plus tool-result sequence.
2. A separate `role=tool` message is retained only when its `tool_call_id` matches the immediately pending assistant call set.
3. Missing result payload is not treated as complete merely because a lifecycle `status` field exists.
4. Orphan tool results and unresolved calls continue through the existing bounded compatibility demotion and expose repair metadata.
5. Recent-history limits keep a complete tool chain atomically or omit it atomically. They never begin after an assistant tool call or end before all matched tool results.
6. If an atomic chain exceeds the hard message limit, omit the whole chain and expose an omitted-chain count instead of exceeding the bound.
7. Compression changes only tool-result content. It preserves `role=tool`, `tool_call_id`, metadata, and the paired assistant call.
8. The `agent_inbox` profile may shorten or suppress old failure bodies but cannot change the structural envelope of a complete chain.
9. Retrieved history/tool-search evidence remains contextual assistant or system text because it is evidence injection, not a replayable provider call.

#### Task 1 Reuse Decisions

| Existing capability | Decision |
| --- | --- |
| `ProviderMessageChain` | reuse its complete-chain validation, dedupe, and orphan repair behavior for historical projection |
| `_repair_provider_tool_chain` | keep as the only final structural repair boundary |
| `history_ledger.build_history_events` | reuse unchanged; it already recognizes assistant calls and `role=tool` results |
| `replace_large_tool_results_for_compression` | reuse unchanged; it already preserves role and `tool_call_id` for structured tool messages |
| `historical_orphan_tool_result` | retain as compatibility output only, never as the normal completed-tool representation |
| Retrieved history seed | retain as contextual text; do not synthesize fake provider tool calls |

#### Task 1 Minimal Implementation Steps

1. Add RED assertions for complete separate-role and inline-result histories.
2. Add RED assertions for orphan demotion, status-without-output, atomic tail trimming, and structural compression.
3. Change `normalize_model_history_messages()` from unconditional text history to the provider-safe structured normalization path.
4. Change inline-result expansion so every real result produces one matched `role=tool` message; lifecycle status alone does not satisfy result completeness.
5. Replace forward-only safe-tail skipping with an atomic chain boundary selector that remains under the existing hard cap.
6. Extend `agent_inbox` compaction to compact structured tool content without changing identity fields.
7. Keep compatibility metadata and existing hash inputs stable enough to invalidate context only when semantic content or identity changes.

#### Task 1 Test Anchors

Add these behavior tests, using existing fixtures where possible:

```text
test_context_assembly_preserves_complete_separate_tool_chain
test_context_assembly_expands_inline_tool_result_to_complete_chain
test_context_assembly_demotes_orphan_tool_result_only
test_context_assembly_does_not_treat_status_as_tool_output
test_context_tail_keeps_or_omits_tool_chain_atomically
test_agent_inbox_compacts_structured_tool_result_without_losing_identity
test_compression_replacement_preserves_structured_tool_pair
```

Focused RED/GREEN command:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_session_context_pipeline.py tests/test_conversation_ledger.py -k 'complete_separate_tool_chain or inline_tool_result or orphan_tool_result_only or status_as_tool_output or tool_chain_atomically or structured_tool_result or structured_tool_pair' -q
```

Related regression after GREEN:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_session_context_pipeline.py tests/test_conversation_ledger.py -q
```

Task 1 does not run `tests/test_session_turn_journal.py`, edit `turn_journal.py`, or enter Agent/session runner files. Those are serialized behind the current observability ownership and Task 2/Task 4 gates.

### Task 2: Wire One Context Assembly Into The Fresh Agent Runtime

**Observable output:** every web turn seeds the new Agent from Task 1 output, then appends the current user item exactly once.

**Files/Boundary:** Slice A modifies `core/orchestration/turn_runner.py`, `agent.py`, `core/orchestration/turn_outcome.py`, `tests/test_turn_runner.py`, and focused `tests/test_agent_protocol.py` assertions. Slice B modifies only the narrow context handoff in `core/web/services/session_service.py` and focused `tests/test_web_app.py` assertions after the transaction-telemetry owner merges or explicitly hands off. Consume `core/chat/context_assembler.py` output without modifying it.

**Dependencies:** Task 1. Slice B additionally depends on transaction telemetry merge or explicit handoff because its active claim owns `session_service.py` and `tests/test_web_app.py`.

**Mode:** BDD_TDD.

**Behavior contract:** make `prepare_agent_turn` the only production owner that seeds model history and same-turn carryover for both fresh and existing Agent runtimes. Pass Task 1 semantic history explicitly through `AgentSingleTurnRequest`; reject terminal, cross-turn, or unidentified chat carryover; keep `"继续"` literal and ordinary after a completed or different turn. The web session path supplies data to `prepare_agent_turn` and no longer calls an Agent restore method directly.

**Verification:** runner and Agent tests prove deterministic source ordering and one current user item. A provider-facing request capture proves the previous final assistant answer and tool chain are present exactly once before a new-turn `"继续"`. A same-turn recovery test proves valid carryover is retained without appending the current user again. Slice B integration proves the web session calls the same preparation owner.

**Risk/Stop:** `activeTask.goal` may remain visible metadata but must not enter message assembly. Do not redesign the Agent into a long-lived process in this stage.

#### Task 2 Single Preparation Owner

Both runtime shapes use the same preparation function:

```text
fresh runtime
  -> create_agent_runtime
  -> prepare_agent_turn
  -> run_existing_agent_single_turn

web-configured existing runtime
  -> create/configure Agent and UI hooks
  -> prepare_agent_turn
  -> run_existing_agent_single_turn
```

Forbidden production paths:

1. `run_agent_single_turn` creates an Agent but omits assembled history.
2. `session_service.py` calls `seed_chat_history`, `restore`, or another Agent history mutation directly.
3. `prepare_agent_turn` independently invokes history seeding and carryover seeding when the second call can overwrite the first.
4. `TurnOutcomeController.prepare_turn_messages` infers conversation continuity from `activeTask.goal` or user text.

`seed_chat_history` may remain temporarily as a one-way compatibility wrapper, but the production host path uses one explicit semantic turn-context seed operation.

#### Task 2 Input Contract

| Input | Owner | Contract |
| --- | --- | --- |
| `history_messages` | Task 1 context assembler | prior durable turns only; current `turnId` excluded by identity |
| `current_turn_id` | session submit/lifecycle owner | stable identity for this user-visible turn |
| `initial_prompt` | current submitted user event | literal current content; never replaced with effective goal |
| `carryover` | Agent turn outcome owner | non-terminal state for the same `turnId`; contains the current-turn user item and subsequent progress |
| dynamic runtime context | current host preparation | regenerated each attempt; not persisted in history or carryover |
| `activeTask.goal` | task/status owner | policy and UI metadata only; forbidden as a model-message fallback |

Carryover schema requirements:

```text
schemaVersion
turnId
lifecycleStatus
messages
containsCurrentUser
```

Chat-mode compatibility rule: carryover without a stable `turnId`, with a mismatched `turnId`, with `containsCurrentUser=false`, or with terminal status is rejected. Non-chat modes may temporarily retain the existing goal-based compatibility gate until a separate migration owns them.

#### Task 2 Two Exclusive Assembly Modes

New user turn:

```text
base instructions
  -> prior durable semantic history
  -> fresh dynamic runtime context
  -> current user exactly once
```

Same-turn runtime recovery:

```text
base instructions
  -> prior durable semantic history
  -> fresh dynamic runtime context
  -> validated current-turn carryover
```

The validated carryover already starts with the current-turn user item, so `initial_prompt` is not appended again in same-turn recovery.

State decisions:

| Situation | History | Carryover | Current prompt append |
| --- | --- | --- | --- |
| new normal turn | keep | none | once |
| new turn whose text is `"继续"` | keep | none | once |
| same `turnId`, running/incomplete carryover | keep | keep | zero |
| completed/cancelled/failed terminal carryover | keep | reject | once as a new attempt only when a new turn exists |
| mismatched carryover `turnId` | keep | reject | once |
| chat carryover missing identity | keep | reject with compatibility reason | once |

Repeated text across distinct turns remains distinct. No text-based deduplication is permitted.

#### Task 2 Internal State Separation

Do not continue using one `_active_turn_messages` value as both durable history and resumable current-turn state.

The Agent preparation boundary keeps two explicit sources until final assembly:

```text
seeded_history_messages
seeded_same_turn_carryover
```

`TurnOutcomeController.prepare_turn_messages` consumes both sources and returns one provider-ready list plus an explicit `resumed_same_turn` decision. Goal equality does not decide chat continuity. Dynamic runtime context is inserted fresh and is never exported into carryover.

When a turn reaches `completed`, `failed`, `cancelled`, or another terminal lifecycle action, exported chat carryover is empty. Only a genuinely non-terminal same-turn result exports the identity-bearing carryover envelope.

#### Task 2 Minimal Implementation Steps

1. Add Slice A RED tests showing `run_agent_single_turn` currently omits history and the current preparation path conflates history with carryover.
2. Extend `AgentSingleTurnRequest` and `prepare_agent_turn` with `history_messages` and `current_turn_id`.
3. Add one production semantic turn-context seed operation that stores history and same-turn carryover separately.
4. Refactor chat-mode `prepare_turn_messages` into the two exclusive assembly modes while preserving the existing non-chat compatibility path.
5. Export identity-bearing carryover only for a non-terminal same turn.
6. Run Slice A GREEN and focused Agent regressions.
7. After telemetry handoff, replace the web session's direct restore block with one `prepare_agent_turn` call and pass the assembled history plus current `turnId`.
8. Run Slice B integration assertions without changing telemetry event identity or payload policy.

#### Task 2 Test Anchors

Slice A:

```text
test_run_agent_single_turn_forwards_history_to_single_context_seed
test_prepare_agent_turn_keeps_history_and_carryover_as_separate_sources
test_chat_new_turn_appends_current_user_once_after_history
test_chat_same_turn_resume_does_not_append_current_user_twice
test_chat_rejects_terminal_mismatched_or_unidentified_carryover
test_chat_continue_uses_history_not_active_task_goal
test_chat_repeated_user_text_is_preserved_by_turn_identity
test_chat_semantic_tool_chain_survives_agent_seed_bridge
```

Slice A focused RED/GREEN command:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_turn_runner.py tests/test_agent_protocol.py -k 'single_context_seed or separate_sources or current_user_once or same_turn_resume or unidentified_carryover or continue_uses_history or preserved_by_turn_identity or semantic_tool_chain' -q
```

Slice B after telemetry handoff:

```text
test_web_session_prepares_agent_from_assembled_history_once
test_web_session_does_not_restore_history_outside_prepare_agent_turn
test_web_continue_turn_preserves_previous_final_and_tool_chain
```

Slice B focused RED/GREEN command:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py tests/test_session_context_pipeline.py -k 'prepares_agent_from_assembled_history_once or does_not_restore_history_outside or continue_turn_preserves_previous_final' -q
```

#### Task 2 Bounded Diagnostics

Reuse the active observability and telemetry contracts. Add only bounded decision fields at the preparation boundary:

```text
sessionId
turnId
historyMessageCount
carryoverMessageCount
carryoverDecision
carryoverReason
currentUserAppendCount
resumedSameTurn
```

`currentUserAppendCount` must be `1` for a new turn and `0` for a validated same-turn recovery. Logs never include prompt text, history content, tool arguments, tool output, credentials, or full payloads.

### Task 3: Lock Responses And Chat Semantic Parity

**Observable output:** both adapters receive the same semantic item list and independently emit valid standard wire payloads.

**Files/Boundary:** `core/llm/semantic_messages.py`, `core/llm/client.py`, `core/llm/wire/responses.py`, `core/llm/wire/chat_completions.py`, `core/llm/provider_replay_state.py`, and outbound bridge tests.

**Dependencies:** Task 2.

**Mode:** BDD_TDD.

**Behavior contract:** Responses emits ordered `input` items and `function_call_output`; Chat emits ordered `messages`, `assistant.tool_calls`, and matching `tool_call_id`. A fallback route receives a fresh invocation and re-encodes complete semantic history.

**Verification:** structured payload assertions cover user, assistant, tool call, tool result, final answer, and next user message for both protocols. No external provider is required for the focused gate.

**Risk/Stop:** encoded payloads, response IDs, replay bookmarks, and compatibility `AIMessage` objects cannot become semantic history.

### Task 4: Establish One Canonical Turn And Item Event Stream

**Observable output:** `LLMProtocolEvent -> TurnOutcome -> journal` produces one ordered and idempotent lifecycle for assistant, tool, error, and terminal items.

**Files/Boundary:** `core/llm/invocation.py`, `core/orchestration/turn_outcome.py`, `core/chat/turn_journal.py`, `core/chat/conversation_ledger.py`, session projection helpers, `web/src/api/types/chat.ts`, and focused lifecycle tests.

**Dependencies:** Task 3, observability claim handoff, and transaction telemetry contract.

**Mode:** BDD_TDD.

**Behavior contract:** every event carries stable IDs and revision; repeated chunks and journal retries are idempotent; terminal state is committed once; compatibility messages are one-way outputs only.

**Verification:** duplicate event, late delta, cancellation, provider failure, tool failure, and reconnect replay tests assert the final ordered journal and `SessionTurnItem v2` projection.

**Risk/Stop:** shared DTO changes are serialized. Do not add another public event family when an existing canonical event can be extended compatibly.

### Task 5: Replace Frontend Projection Heuristics With An Item Reducer

**Observable output:** live and persisted data update the same normalized item, status settles on terminal events, and each assistant/tool/error item renders once.

**Files/Boundary:** `web/src/routes/chatSessionStreamProtocol.ts`, `web/src/routes/chatStreamApplyController.ts`, `web/src/routes/chatSessionState.ts`, `web/src/components/conversation/conversationMessageIdentity.ts`, `timelineMessageProcessProjection.ts`, `useAgentMessageTimelineProjection.ts`, `ConversationView.tsx`, and focused tests. Add a small reducer module instead of growing `ChatCodingRoute.tsx` or `ConversationView.tsx`.

**Dependencies:** Task 4, transaction telemetry handoff, and layout-claim reconciliation.

**Mode:** BDD_TDD.

**Behavior contract:** key items by `turnId + itemId`; apply deltas as revisions; reject stale `ledgerSeq`; settle live overlay from the canonical terminal snapshot; derive working status from active non-terminal turns; suppress legacy timeline blocks when native items exist.

**Verification:** tests cover repeated SSE delivery, out-of-order snapshot/delta, reconnect, final answer consolidation, duplicate tool projections, failed turns, interrupted turns, and two distinct turns containing identical text.

**Risk/Stop:** do not combine semantic reducer work with responsive layout or style redesign. Preserve the active message-column owner's result.

### Task 6: End-To-End Acceptance And Cutover

**Observable output:** bounded runtime evidence demonstrates continuous context and single rendering on both protocol routes.

**Files/Boundary:** scenario tests, `scripts/diagnose_session_turn.py`, runtime-scene evidence, and acceptance notes. Production code changes return to their owning task rather than being patched during acceptance.

**Dependencies:** Tasks 1 through 5.

**Mode:** SIMPLE with an explicit runtime gate.

**Verification scenarios:**

1. Responses tool turn followed by `"继续"` includes the previous complete semantic chain once.
2. Chat tool turn followed by `"继续"` includes the same semantic facts in Chat form once.
3. Completed turn has zero carryover; interrupted turn restores only its matching incomplete items.
4. One tool call produces one running item and one completed revision, not two cards.
5. Commentary, tool call, tool result, and final answer render in order with one terminal status.
6. Provider failure renders one error item and clears the working indicator.
7. SSE reconnect and repeated snapshot delivery do not duplicate content.
8. Distinct turns with identical text remain distinct by identity.

**Runtime gate:** run focused backend tests, focused frontend tests, `npm --prefix web run build`, Launcher refresh, then capture a real session diagnostic package containing IDs, counts, route, lifecycle states, and terminal outcome without prompts, secrets, or full tool output.

**Risk/Stop:** missing runtime conversation evidence is a telemetry gap, not acceptance. A Launcher refresh blocked by active work uses the standard project block message and is not bypassed.

## 9. Compatibility And Migration

1. Existing journal files are not rewritten.
2. Legacy events pass through a one-way compatibility normalizer into canonical semantic items.
3. New turns write canonical facts only. No canonical-plus-legacy dual write is introduced.
4. Frontend legacy projection remains only for sessions without valid native v2 items.
5. Compatibility use is observable through bounded counters and a `compatibility` source label.
6. Removal of legacy adapters is deferred until runtime evidence shows zero required fallback for the supported retention window.

## 10. Rollback

1. Journal schema changes remain additive so old readers can ignore new fields.
2. Each task is committed independently and can be reverted without deleting conversation data.
3. Provider adapter cutover can return to the previous adapter consumer while preserving canonical journal facts.
4. Frontend reducer cutover can return to the prior native projection while retaining the same `SessionTurnItem v2` payload.
5. No rollback may restore tool-result-as-assistant-text as the canonical context path.

## 11. Acceptance Evidence Map

| Requirement | Required evidence |
| --- | --- |
| Same-session continuity | captured outbound semantic sequence includes prior final answer and current user once |
| Tool semantic preservation | paired call/result IDs survive journal, context assembly, and both wire adapters |
| No completed-turn replay | terminal turn contributes no carryover and `activeTask.goal` is absent from provider messages |
| Protocol correctness | Responses and Chat structured payload tests pass independently |
| Canonical lifecycle | one started/completed sequence and one terminal outcome per identity |
| Frontend single ownership | reducer tests and runtime capture show one visible item per canonical `itemId` |
| Working status correctness | completed, failed, and interrupted scenarios clear the status deterministically |
| Traceability | one diagnostic query reconstructs session, turn, invocation, items, tools, and terminal state using bounded metadata |

## 12. Deferred

1. Long-lived in-memory Agent sessions.
2. Native Anthropic or Gemini adapters.
3. Rewriting historical journals into the new schema.
4. General chat layout, responsive drawer, typography, and visual-density redesign.
5. Provider configuration, credentials, model discovery, and external endpoint reliability.
6. Legacy compatibility deletion before usage evidence exists.

## 13. Execution Route

**Route:** `SPLIT_REQUIRED`.

**Current task:** Task 0, reconcile current `main` and active claim outputs before any runtime edit.

**Continuous execution:** yes. Move through the critical path without user reconfirmation, but obey claim, test, build, and Launcher gates.

**Success evidence:** the Task 6 acceptance map is complete with fresh commands and runtime evidence.

**Stop conditions:** active scope conflict, unexpected unrelated file changes, incompatible public DTO migration, missing terminal identity, or inability to preserve existing journal data.

## Task 3 refinement: Responses and Chat semantic protocol parity

### Reconciliation snapshot

Task 3 does not need another universal transport abstraction. `SemanticModelRequest` and `WireAdapterRegistry.encode_request()` already establish one provider-neutral request and one outbound payload owner. The remaining risk is semantic loss or protocol leakage between the semantic projector and the two standard wire adapters.

Fresh source inspection found these concrete boundaries:

- `core/llm/semantic_projector.py` already preserves assistant `tool_calls` as `ToolCallPart`, preserves `role=tool` as `ToolResultPart`, rejects duplicate call IDs, and rejects orphan tool results.
- `core/llm/wire/responses.py` already emits first-class `function_call` and `function_call_output` items correlated by `call_id`.
- `core/llm/wire/chat_completions.py` already emits `assistant.tool_calls` followed by `role=tool` messages correlated by `tool_call_id`.
- Existing tests prove one call/result shape, but they do not prove a complete multi-turn history, parallel tools, route switching, or the absence of foreign protocol fields.
- Responses currently ignores `ReasoningTextPart` silently.
- Chat currently drops a reasoning-only message because `ReasoningTextPart` alone does not create a primary message.
- Chat currently accepts `ReasoningReplayPart` and injects decoded provider JSON into standard `messages`; this is an opaque-provider escape hatch inside the standard Chat adapter.
- Responses currently has an automatic replay insertion fallback keyed by `response_id`; that fallback can move all opaque replay items before the first tool call instead of preserving their explicit semantic position.

The local Codex source confirms the target model: `ResponseItem::FunctionCall`, `ResponseItem::FunctionCallOutput`, and reasoning items remain first-class transcript items, and call/output matching is tested by `call_id`. They are not flattened into assistant prose. The previous Hermes, OpenCode, and pi-agent research remains an architectural constraint: continuity belongs to the canonical conversation model, while each provider codec owns only its wire representation. Task 3 will reuse that boundary rather than copy an external runtime or introduce another dependency.

### Decision

Use one complete semantic fixture as the source of truth, then encode it independently into standard Responses and standard Chat payloads. Raw payload equality is not a goal because the protocols intentionally have different shapes. Semantic equivalence, correlation identity, ordering, and protocol isolation are the goals.

The implementation must fail closed on invalid semantic chains. Wire adapters must never repair, flatten, invent, or silently discard tool-chain semantics.

### Protocol-neutral semantic contract

A provider-ready `SemanticModelRequest.messages` sequence must satisfy all of these invariants:

- `ToolCallPart` appears only in an assistant semantic message.
- `ToolResultPart` appears only in a tool semantic message.
- Every tool call has a non-empty stable `call_id`.
- Every tool result matches exactly one preceding unresolved call by `call_id`.
- Duplicate calls, duplicate results, orphan results, and unresolved calls at request end are rejected before HTTP serialization.
- Parallel calls remain grouped in the original assistant message; their results remain separate semantic tool messages.
- Canonical order is preserved. The adapters do not sort by completion time or synthesize replacement IDs.
- Tool messages are atomic. Text, image, reasoning, and tool-result semantics are not mixed in one tool message.
- UI-only `toolCalls` projections remain invalid model input.
- Historical assistant text, tool calls, tool results, and the next user message remain separate semantic items. No component converts a complete historical chain into prose.

Add a small provider-ready chain validator at the semantic boundary and call it from the single outbound encode path. Prefer a shared validator in `core/llm/semantic_messages.py` or `core/llm/semantic_projector.py`; do not duplicate pairing repair in both wire adapters.

### Standard Responses contract

Vibelution continues to use stateless standard Responses encoding for relay compatibility.

- Do not send `previous_response_id`.
- Replay the required prior response items explicitly in `input`.
- Emit assistant calls as `{"type":"function_call","call_id":...}`.
- Emit tool results as `{"type":"function_call_output","call_id":...}`.
- A continuation request that includes a function output must also contain the matching prior function call unless a future, separately designed state-linked route explicitly owns `previous_response_id`.
- Preserve explicit semantic order: reasoning replay item, function call, matching function output, then subsequent user input.
- Require `ReasoningReplayPart` to identify each opaque reasoning item at its semantic position.
- Remove or narrowly retire `response_id`-driven automatic replay insertion after the explicit path is wired. Do not keep two replay-position owners.
- Accept opaque replay only when `ProviderReplayState.require_compatible()` matches adapter, provider, endpoint fingerprint, model, and wire protocol.
- Reject `ReasoningTextPart` at the Responses encoder boundary instead of silently dropping it. Standard Responses reasoning continuity uses compatible opaque replay, not plain reasoning text.
- Never emit Chat-only `messages`, `assistant.tool_calls`, `tool_call_id`, or `reasoning_content` fields.

### Standard Chat Completions contract

Standard Chat uses full message replay on every invocation.

- Emit only `messages` plus standard Chat request fields.
- Emit one assistant message containing `tool_calls` in canonical order.
- Emit one `role=tool` message per result with the exact `tool_call_id`.
- Keep historical assistant final text as an assistant message and append the next user message exactly once.
- Permit `ReasoningTextPart` only when the resolved capability enables Chat reasoning roundtrip; encode it as bounded `reasoning_content` on the same assistant message.
- A reasoning-only semantic message must either produce a valid assistant message or be rejected explicitly. It must not disappear silently.
- Reject `ReasoningReplayPart` and Responses-issued opaque replay in the standard Chat adapter. Provider-specific opaque Chat extensions require a separate explicit adapter, not arbitrary JSON injection into this adapter.
- Never emit Responses-only `input`, `function_call`, `function_call_output`, `call_id`, `previous_response_id`, or encrypted reasoning items.

### Route-switch contract

Protocol switching keeps canonical history and discards incompatible provider replay state.

- Responses to Chat: retain semantic assistant/tool/user history, clear Responses opaque replay, and re-encode standard Chat messages.
- Chat to Responses: retain semantic assistant/tool/user history, clear Chat-only reasoning extension state, and re-encode explicit Responses items.
- `ProviderReplayState.require_compatible()` remains the hard guard against cross-provider, cross-endpoint, cross-model, and cross-protocol replay.
- A route switch must not fall back to flattened text merely because opaque reasoning cannot cross the boundary.
- Loss of provider-private reasoning is allowed and diagnosed; loss of user, assistant final, tool call, or tool result semantics is not allowed.

### Implementation ownership and file scope

Slice A owns semantic validation:

- `core/llm/semantic_messages.py`
- `core/llm/semantic_projector.py`
- `tests/test_llm_semantic_messages.py`

Slice B owns standard Responses serialization:

- `core/llm/wire/responses.py`
- `tests/test_llm_wire_responses.py`

Slice C owns standard Chat serialization:

- `core/llm/wire/chat_completions.py`
- `tests/test_llm_wire_chat_completions.py`

Slice D owns the narrow cross-adapter regression gate:

- `tests/test_llm_provider_replay_state.py`
- focused additions to `tests/test_llm_client.py` only if the registry/client bridge is needed to prove one encode owner

Protected boundaries:

- Do not change `core/chat/model_messages.py` in Task 3; Task 1 owns structured historical-chain preservation.
- Do not change Agent seeding or `session_service.py` in Task 3; Task 2 owns context preparation.
- Do not add protocol fields to `SemanticModelRequest` merely to mirror one provider payload.
- Do not add a third generic adapter, a shared raw JSON payload, or protocol guessing inside either wire adapter.
- Do not modify frontend projections or terminal lifecycle state in this task.

### Compact BDD/TDD anchors

Start with one complete shared semantic fixture containing system text, user text, assistant commentary/final text, two parallel tool calls, two matching results, and a subsequent user message.

Add these focused tests before implementation:

- `test_semantic_projector_preserves_complete_parallel_tool_chain`
- `test_semantic_projector_rejects_duplicate_or_incomplete_tool_chain`
- `test_semantic_projector_rejects_out_of_order_tool_result`
- `test_responses_stateless_history_emits_full_call_output_pairs_without_previous_response_id`
- `test_responses_preserves_explicit_reasoning_call_output_order`
- `test_responses_rejects_plain_reasoning_text_instead_of_silent_drop`
- `test_chat_history_emits_assistant_tool_calls_then_tool_messages`
- `test_chat_reasoning_only_message_is_not_silently_dropped`
- `test_chat_rejects_opaque_responses_replay`
- `test_protocol_switch_reencodes_semantic_history_without_foreign_fields`
- `test_parallel_tool_chain_preserves_ids_and_order_in_both_protocols`

Assertions must cover the complete payload sequence, not only membership of one output item.

Responses assertions:

- `input` contains each call before its matching output.
- Every `call_id` appears once as a call and once as an output.
- `previous_response_id` and `messages` are absent.
- The next user message is the final new input message.

Chat assertions:

- `messages` contains one assistant tool-call message followed by matching tool messages.
- Every `tool_call_id` matches an assistant tool call exactly once.
- `input`, `function_call_output`, and Responses opaque items are absent.
- The next user message appears exactly once.

Suggested focused commands for the implementation round:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_llm_semantic_messages.py -q
& '.\.venv\Scripts\python.exe' -m pytest tests/test_llm_wire_responses.py tests/test_llm_wire_chat_completions.py -q
& '.\.venv\Scripts\python.exe' -m pytest tests/test_llm_provider_replay_state.py tests/test_llm_client.py -q
```

### Diagnostics decision

Reuse the existing bounded payload snapshots in `core/llm/payload_builder.py`:

- protocol route and adapter ID
- role or Responses item-type sequence
- assistant tool-call count
- tool-result count
- paired, orphan, missing, and duplicate counts
- bounded shape hash and tail

Only add a semantic validation decision and reason code if the existing payload summary cannot represent a pre-encode rejection. Do not log prompt text, reasoning text, tool arguments, tool outputs, opaque replay payloads, API keys, or full request bodies.

### Acceptance gate

Task 3 is complete only when all of these are demonstrated by focused tests:

- The same complete canonical history produces a valid standard Responses payload and a valid standard Chat payload.
- Both payloads preserve tool identity, tool ordering, prior assistant final text, and the next user message.
- Neither payload contains fields owned by the other protocol.
- Stateless Responses continuation includes complete call/output pairs and never relies on hidden `previous_response_id` state.
- Chat never injects opaque Responses JSON.
- Unsupported reasoning representation fails explicitly or is excluded by capability policy; it is never silently dropped.
- Cross-protocol route switching retains semantic conversation continuity while rejecting incompatible provider-private replay.
- Existing stream/non-stream `TurnOutcome` parity and single-final-answer tests remain green.

Task 3 route: `DIRECT_IMPLEMENTATION` after Task 1 exposes structured history and Task 2 exposes one preparation owner. The three slices are serial parts of one protocol-owner change, not independent deliverables. No runtime code should begin while either upstream contract is still changing.

## Task 4 refinement: end-to-end conversation acceptance and Agent traceability

### Reconciliation snapshot

The repository already has broad layer-level coverage. Backend tests cover session submission, history seeding, continuation, SSE snapshots, persistence, interruption, tool lifecycle, and terminal failures. Frontend tests cover canonical v2 items, active overlays, committed projections, tool-card convergence, stream scheduling, duplicate suppression, and final-answer ownership. Protocol tests cover individual Responses and Chat shapes.

That breadth does not yet prove one conversation crosses every boundary correctly. The missing evidence is one identity-stable golden scenario that starts at submission, crosses context assembly and protocol encoding, executes tools, persists one canonical outcome, converges the live frontend layer, survives reload, and then continues into a second turn with history.

Fresh runtime-scene inspection confirms the gap:

- The newest package `3bcd27f81c3a` is Launcher-only with `conversation_logs=0` and `agent_logs=0`; it is not conversation acceptance evidence.
- The newest conversation-bearing package found was `b58293c912ff`.
- Package `b58293c912ff` contains five conversation logs and one Agent log, but its visible turn remains in early running stages and does not provide a terminal conversation reconstruction.
- `session-live-turns.jsonl` carries `session_id` and `turn_id`, but the inspected records do not carry `invocation_id` or `submission_id`.
- The top-level user-message logs do not carry `turn_id`, so cross-file correlation depends on filename and timing rather than explicit identity.
- `conversation_log_inspect_tool` can summarize a selected JSONL file and accepts an explicit runtime-scene path, but it does not join all files for one runtime scene/session/turn or report the last successful chain boundary.

Task 4 therefore owns acceptance composition and diagnostic reconstruction. It does not own the semantic-history, Agent preparation, or wire-protocol implementation already assigned to Tasks 1 through 3.

### Evidence model

Keep four evidence classes separate:

- Contract evidence: deterministic semantic, protocol, backend DTO, and frontend projection assertions.
- Integration evidence: one fake-provider conversation crossing the backend session boundary and producing canonical persisted plus streamed records.
- Runtime evidence: a fresh Launcher-managed chat scene with non-empty conversation and Agent logs, complete identities, and a terminal outcome.
- Visual evidence: the visible transcript has one user row, one lifecycle per tool call, one final answer, no stale spinner, and preserved prior-turn context.

Passing unit tests does not imply live runtime acceptance. A live model reply does not replace deterministic protocol tests. A clean screenshot does not prove history or payload identity.

### Shared golden scenario

Create one provider-neutral fixture with stable, synthetic identities and no secrets or real prompt content.

Recommended fixture path:

- `tests/fixtures/conversation_chain/canonical_tool_followup_v2.json`

The fixture contains these ordered facts:

- `runtimeSceneId=scene-golden`
- `sessionId=session-golden`
- first `submissionId=submission-1`
- first `turnId=turn-1`
- first invocation and iteration identities
- one bounded commentary item
- two parallel tool calls with stable IDs and distinct names
- one terminal result for each call
- one committed final answer for turn 1
- second `submissionId=submission-2`
- second `turnId=turn-2`
- literal follow-up user text such as `继续说明刚才的结果`
- one committed final answer for turn 2 that depends on turn 1 history

The fixture stores content placeholders, lengths, hashes, IDs, lifecycle states, revisions, and ordering. It does not store API keys, real user prompts, raw reasoning, full tool arguments, full tool output, or provider-private replay payloads.

Both Python and TypeScript tests consume this one JSON artifact. Do not maintain separately hand-copied backend and frontend golden timelines. If the existing test runners cannot read the same path directly, add one tiny fixture loader per language; do not generate or copy a second fixture.

### Golden-chain invariants

The complete scenario must prove all of these behaviors:

- Each submission creates exactly one user message and one new turn identity.
- Turn 1 commentary remains process content and never becomes final-answer text.
- Each tool call has one stable identity across running, completed, persisted, streamed, and rendered projections.
- Each tool call renders once after live-to-persisted convergence.
- Turn 1 has exactly one committed final answer.
- The active assistant shell disappears when the canonical terminal item settles the same turn.
- Reloading session detail during or after convergence yields the same visible transcript.
- Turn 2 receives the complete semantic history from turn 1 and appends its current user message once.
- Turn 2 does not use `activeTask.goal` as conversation history.
- Turn 1 final answer remains visible after turn 2 completes.
- Identical assistant text in different turn identities remains two valid rows.
- Repeated stream delivery or lower canonical revisions do not create duplicate rows or tool cards.
- A terminal failure produces one error-owned turn, removes the spinner, and does not fabricate a final answer.

### Pairwise protocol matrix

Avoid a combinatorial suite. Use a bounded pairwise matrix:

- Responses, streaming, one explicit reasoning replay item, one tool chain, follow-up turn.
- Chat Completions, streaming, two parallel tools, reasoning text only when capability allows, follow-up turn.
- Shared non-stream terminal response parity at the adapter level.
- Shared provider failure or incomplete terminal projection.
- Cross-protocol route switch using canonical history with provider-private replay cleared.

Deterministic tests use fake transports and fixed events. Live runtime acceptance uses only currently configured, reachable models and is recorded separately. Lack of a live Chat model must be reported as missing runtime coverage, not as a protocol-test failure.

### Task 4A: deterministic backend chain

Owned files:

- `tests/fixtures/conversation_chain/canonical_tool_followup_v2.json`
- new `tests/test_conversation_chain_acceptance.py`
- focused additions to `tests/test_session_codex_transcript_projection.py`
- focused additions to `tests/test_llm_client.py` only for registry-to-adapter traversal

Behavior:

- Drive the same semantic fixture through Responses and Chat routes.
- Run a fake session submission through scheduling, Agent preparation, provider events, tool results, canonical outcome, ledger persistence, and session detail projection.
- Capture the initial session detail, assistant deltas, terminal detail, and reload detail.
- Assert identity and cardinality at every boundary rather than comparing full unbounded payload bodies.
- Keep provider transport fake and deterministic. No API key or network is required.

Task 4A waits for Tasks 1 through 3 implementation contracts to stabilize, but it does not wait for browser telemetry work.

### Task 4B: frontend convergence chain

Owned files:

- new `web/src/routes/chatConversationChainAcceptance.test.ts`
- focused reuse of helpers exported by `chatSessionStreamProtocol.ts`
- focused reuse of helpers exported by `chatStreamApplyController.ts`
- focused reuse of canonical projection helpers from `chatTurnProtocol.ts`, `ChatActiveTurnLayer.ts`, and `useAgentMessageTimelineProjection.ts`

Behavior:

- Load the shared fixture.
- Route the same initial detail and assistant deltas through the production stream router.
- Drain them through the production scheduler and apply controller.
- Project the active and committed layers through the production conversation adapters.
- Assert one commentary cell, one cell per tool call, one final-answer cell, no status text in answer content, and no duplicate after terminal detail.
- Replay terminal detail a second time and assert idempotence.
- Reconstruct from reload detail without the live overlay and assert the same semantic transcript.
- Apply turn 2 and assert turn separation plus preserved turn 1 content.

Do not add a new frontend transcript reducer. This test composes existing production helpers and exposes the first boundary that diverges.

### Task 4C: identity-complete diagnostics

Owned files after telemetry handoff:

- `tools/conversation_log_tools.py`
- `tests/test_conversation_log_tools.py`
- narrow runtime-scene summary tests only if package-level joining requires them
- telemetry-owned production files only after `claim-506d622c3b24` is completed or their exact scopes are released

Required correlation fields:

- `runtimeSceneId`
- `sessionId`
- `submissionId`
- `turnId`
- `invocationId`
- `iteration`
- `providerId`
- `modelId`
- `adapterId`
- canonical item or tool-call identity where applicable
- event code, lifecycle status, bounded duration, and terminal reason code

Required boundary sequence:

- submission accepted
- turn scheduled
- worker started
- context prepared
- LLM invocation started
- provider first event
- tool call started and terminal
- canonical outcome decided
- ledger persisted
- terminal session detail or SSE event published
- frontend terminal apply accepted

Not every process owns every field, but all records for one turn must carry enough shared identity to join without timestamps or content matching.

Extend `conversation_log_inspect_tool` with a package/identity query that returns:

- matched package and files
- identity completeness report
- ordered boundary list
- last successful boundary
- missing or duplicated boundary codes
- tool call/result pairing counts
- terminal outcome and reason
- bounded durations
- one concise likely-breakpoint summary

The default inspector output must not return prompt text, reasoning text, raw tool arguments, raw tool output, opaque replay data, API keys, or full error bodies. Use field names, counts, lengths, hashes, redacted categories, and bounded reason codes. Any optional preview mode remains explicit and separately protected.

Add these focused tests:

- `test_conversation_log_inspect_reconstructs_turn_across_runtime_scene_files`
- `test_conversation_log_inspect_reports_last_successful_boundary`
- `test_conversation_log_inspect_reports_missing_identity_without_timestamp_guessing`
- `test_conversation_log_inspect_pairs_tool_lifecycle_by_canonical_identity`
- `test_conversation_log_inspect_redacts_prompt_reasoning_and_tool_payloads`
- `test_conversation_log_inspect_output_is_bounded`

Task 4C is serialized behind the active transaction telemetry claim because that owner is changing redaction and correlation contracts in `session_service.py`, runtime-scene service, browser telemetry, and shared tests. Do not duplicate or preempt those fields.

### Task 4D: fresh live acceptance

Run only after 4A through 4C pass and the relevant implementation is merged into local `main`.

Preconditions:

- Root remains on `main` with no unresolved merge.
- Launcher active-work guard permits refresh.
- Operator config resolves the intended provider, profile, model, and API key.
- At least one deterministic Responses route and, when available, one deterministic Chat route are configured.
- The browser is using the refreshed frontend build and backend process.

Live scenario:

- Create a fresh session.
- Submit one bounded tool-required prompt.
- Observe commentary, one lifecycle per call, and one final answer.
- Reload the page and confirm the transcript is unchanged.
- Submit the literal follow-up `继续说明刚才的结果`.
- Confirm the second answer uses prior context without duplicating the first answer or reusing a stale active layer.
- Capture one safe screenshot after turn 1 and one after turn 2.
- Inspect the resulting runtime scene with the Agent diagnostic tool.

A valid runtime package must have:

- `conversation_logs > 0`
- `agent_logs > 0`
- non-empty session, submission, turn, and invocation identities for the accepted turn
- at least one LLM invocation boundary
- complete tool call/result lifecycle when a tool is used
- one canonical terminal outcome
- no active spinner after terminal settlement
- an inspector summary that identifies the last successful boundary without opening raw prompts

Record the runtime scene ID, session ID, turn IDs, model route, visible cardinalities, inspector result, and screenshot paths. Do not record secrets or full request bodies.

### Failure acceptance

Use deterministic tests for these failures and one live check only when safely reproducible:

- Missing API key: one canonical configuration error, no endless processing state.
- Provider `failed` or `incomplete`: one terminal error with provider reason category, no fake final answer.
- Stop during streaming: partial content remains process/status content unless explicitly committed, and the next turn can continue.
- Reload during an active turn: live checkpoint restores once and settles against the later committed turn.
- Stale old-turn delta: cannot overwrite or clear the new active turn.
- Duplicate event delivery: canonical identity and revision make application idempotent.

### Focused implementation commands

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_conversation_chain_acceptance.py tests/test_session_codex_transcript_projection.py -q
& '.\.venv\Scripts\python.exe' -m pytest tests/test_llm_client.py tests/test_conversation_log_tools.py -q
npm --prefix web run test -- chatConversationChainAcceptance.test.ts chatSessionStreamProtocol.test.ts chatTurnProtocol.test.ts chatStreamApplyController.test.ts ChatActiveTurnLayer.test.ts
npm --prefix web run build
```

Run `tests/test_web_app.py` and telemetry-owned focused tests only after their active claim is completed or handed off. Do not treat the current schema-v2 `model_library` fixture failure as a Launcher failure or bypass it in Task 4.

### Ownership and route decision

Task 4 route: `SPLIT_REQUIRED`.

- Task 4A produces the shared fixture and deterministic backend evidence.
- Task 4B consumes that fixture and proves frontend convergence.
- Task 4C consumes the final telemetry correlation contract and upgrades Agent diagnosis.
- Task 4D consumes all prior evidence and produces fresh runtime plus visual acceptance.

The sequence is strict because later artifacts consume earlier identities and DTOs. Task 4A and 4B may be developed in separate worktrees with disjoint write sets after the fixture schema is frozen. Task 4C waits for telemetry handoff. Task 4D is a single integration-owner closeout and must not run while active work blocks Launcher refresh.

### Completion gate

Task 4 is complete only when:

- one shared fixture drives both backend and frontend acceptance
- deterministic Responses and Chat routes preserve the same canonical history
- the backend emits one terminal canonical outcome per turn
- the frontend converges live and persisted projections without duplicates
- turn 2 visibly and semantically continues turn 1
- package-level Agent diagnostics reconstruct the chain by identity
- a fresh runtime scene contains complete conversation and Agent evidence
- visible failure states settle and remain diagnosable
- engineering, runtime, and visual evidence are reported separately

No Task 4 production change is accepted merely because an existing broad suite is green. The golden chain and fresh runtime package are the decisive evidence.

## Executable task graph

### Split decision

Split is required because later work consumes concrete artifacts from earlier work, three production ownership boundaries can proceed independently only after the history contract is fixed, Web integration overlaps an active telemetry claim, and final acceptance requires a separate runtime/Launcher gate.

Critical path:

```text
Activation gate
  -> Task 1 structured history
  -> [Task 2 Agent preparation || Task 3 wire parity]
  -> Task 4 Web session integration
  -> Task 5 golden-chain acceptance
  -> Task 6 Agent diagnostics and live closeout
```

Parallel boundary:

- Task 1 is strictly first.
- Task 2 and Task 3 may run in parallel only after Task 1 is merged into local `main`.
- Task 2 and Task 3 have disjoint production files and independent focused tests.
- Task 4 starts only after Task 2 and Task 3 are merged and `claim-506d622c3b24` has explicitly released the overlapping files. Claim expiry alone is not a handoff.
- Task 5 consumes the integrated backend contract from Task 4.
- Task 6 consumes the final telemetry identity contract and Task 5 fixture; live acceptance remains last.

### Activation gate

Before creating implementation worktrees:

- Make the accepted plan available from local `main` so new worktrees consume the same contract.
- Re-run guard `status` and exact-scope `check` immediately before every claim.
- Create each branch from the then-current local `main`, not `origin/main` and not an old task branch.
- Keep root `C:\Users\17533\Desktop\Vibelution` on `main`.
- Do not start Task 4 while telemetry still owns `core/web/services/session_service.py` or `tests/test_web_app.py`.
- Preserve the open Launcher coordination until telemetry fixes the schema-v2 fixture or releases its single-file scope.

No implementation task may broaden its claim to `core/chat`, `core/llm`, `core/web`, `tests`, or `web/src` as a directory. Claims use the exact files listed below.

### Task 1: preserve complete structured model history

Observable output:

A complete historical assistant tool-call plus tool-result chain survives context assembly as structured provider history. Only malformed orphan fragments downgrade, and trimming/compression treats each complete chain atomically.

Files and claim boundary:

- `core/chat/model_messages.py`
- `core/chat/context_assembler.py`
- `tests/test_session_context_pipeline.py`
- `tests/test_conversation_ledger.py`

Branch and worktree:

- Branch: `codex/conversation-history-structure`
- Worktree: `C:\Users\17533\Desktop\Vibelution-worktrees\conversation-history-structure`

Dependencies:

- Accepted closure plan only.
- No dependency on telemetry or frontend work.

Mode: `BDD_TDD`

Test anchors:

- Preserve assistant `tool_calls` plus following `role=tool` messages.
- Preserve parallel call IDs and result order.
- Downgrade only orphan results or incomplete fragments.
- Trim a complete call/result chain as one unit.
- Compress tool output without removing `tool_call_id`.
- Preserve repeated user or assistant text when turn identities differ.

Verification:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_session_context_pipeline.py tests/test_conversation_ledger.py -q
```

Handoff artifact:

- Test-backed `normalize_model_history_messages()` behavior.
- Explicit complete-chain, orphan, trimming, and compression decisions.
- Exact message sequence fixture that Task 2 and Task 3 can consume.

Risk and stop:

- Stop if complete chains cannot be preserved without changing durable ledger schema.
- Stop if another active claim appears on either production file.
- Do not move fresh current-turn ReAct messages into historical normalization.

### Task 2: make `prepare_agent_turn` the only Agent context owner

Observable output:

Fresh Agents and Web-configured Agents both enter execution through one preparation function. New-turn assembly and same-turn recovery are mutually exclusive, current user input appears once, and `activeTask.goal` is not conversation history.

Files and claim boundary:

- `core/chat/turn_runner.py`
- `agent.py`
- `core/orchestration/turn_outcome.py`
- `tests/test_turn_runner.py`
- `tests/test_agent_protocol.py`

Branch and worktree:

- Branch: `codex/conversation-turn-preparation`
- Worktree: `C:\Users\17533\Desktop\Vibelution-worktrees\conversation-turn-preparation`

Dependencies:

- Task 1 merged into local `main`.
- Consumes Task 1 structured history sequence and complete-chain semantics.

Mode: `BDD_TDD`

Test anchors:

- `test_run_agent_single_turn_forwards_history_to_single_context_seed`
- `test_prepare_agent_turn_keeps_history_and_carryover_as_separate_sources`
- `test_chat_new_turn_appends_current_user_once_after_history`
- `test_chat_same_turn_resume_does_not_append_current_user_twice`
- `test_chat_rejects_terminal_mismatched_or_unidentified_carryover`
- `test_chat_continue_uses_history_not_active_task_goal`
- `test_chat_repeated_user_text_is_preserved_by_turn_identity`
- `test_chat_semantic_tool_chain_survives_agent_seed_bridge`

Verification:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_turn_runner.py tests/test_agent_protocol.py -q
```

Handoff artifact:

- One `prepare_agent_turn` call contract.
- Separate history and same-turn carryover inputs.
- Identity-bearing carryover schema and rejection reasons.
- Provider-ready ordered messages plus `resumed_same_turn` decision.

Risk and stop:

- Stop if available identity cannot distinguish cross-turn `继续` from same-turn recovery.
- Stop rather than adding text-based deduplication.
- Do not edit `session_service.py`; Task 4 owns Web adoption after telemetry handoff.

### Task 3: enforce standard Responses and Chat wire parity

Observable output:

One validated semantic request encodes into a complete stateless Responses chain or a complete standard Chat message chain without foreign protocol fields, silent reasoning loss, or arbitrary opaque replay injection.

Files and claim boundary:

- `core/llm/semantic_messages.py`
- `core/llm/semantic_projector.py`
- `core/llm/wire/responses.py`
- `core/llm/wire/chat_completions.py`
- `tests/test_llm_semantic_messages.py`
- `tests/test_llm_wire_responses.py`
- `tests/test_llm_wire_chat_completions.py`
- `tests/test_llm_provider_replay_state.py`
- `tests/test_llm_client.py`

Branch and worktree:

- Branch: `codex/conversation-wire-parity`
- Worktree: `C:\Users\17533\Desktop\Vibelution-worktrees\conversation-wire-parity`

Dependencies:

- Task 1 merged into local `main`.
- May run in parallel with Task 2 because write sets are disjoint.

Mode: `BDD_TDD`

Test anchors:

- Validate complete and parallel semantic tool chains.
- Responses emits ordered `function_call` plus `function_call_output` pairs and no `previous_response_id`.
- Chat emits `assistant.tool_calls` plus matching `role=tool` messages.
- Responses rejects plain reasoning text instead of silently dropping it.
- Chat rejects Responses opaque replay.
- Route switching retains semantic history and clears provider-private replay.
- Registry/client traversal proves one outbound adapter owner.

Verification:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_llm_semantic_messages.py tests/test_llm_wire_responses.py tests/test_llm_wire_chat_completions.py tests/test_llm_provider_replay_state.py -q
& '.\.venv\Scripts\python.exe' -m pytest tests/test_llm_client.py -q
```

Handoff artifact:

- Provider-ready semantic chain validator.
- Explicit Responses and Chat reasoning/replay policy.
- Test-backed proof that `WireAdapterRegistry.encode_request()` remains the sole payload owner.

Risk and stop:

- Stop if a live provider requires state-linked `previous_response_id`; that is a separate route design, not an exception inside stateless Responses.
- Stop if an existing provider-specific Chat extension cannot be represented without arbitrary JSON injection; route it to a dedicated adapter decision.
- Do not edit Agent context assembly or Web session code.

### Task 4: adopt the unified preparation contract at the Web session boundary

Observable output:

The Web session worker assembles durable history once, calls `prepare_agent_turn` once, and runs the configured Agent without a second restore/seed path. A follow-up turn preserves previous assistant/tool history and the literal current prompt.

Files and claim boundary:

- `core/web/services/session_service.py`
- `tests/test_web_app.py`

Branch and worktree:

- Branch: `codex/conversation-session-integration`
- Worktree: `C:\Users\17533\Desktop\Vibelution-worktrees\conversation-session-integration`

Dependencies:

- Task 2 merged into local `main`.
- Task 3 merged into local `main`.
- `claim-506d622c3b24` completed or exact scopes explicitly released.
- Re-read the telemetry owner handoff before editing either file.

Mode: `BDD_TDD`

Test anchors:

- `test_web_session_prepares_agent_from_assembled_history_once`
- `test_web_session_does_not_restore_history_outside_prepare_agent_turn`
- `test_web_continue_turn_preserves_previous_final_and_tool_chain`
- Schema-v2 operator config fixture does not assume `llm.model_library`.
- Existing stop, restart recovery, stale delta, and terminal failure behavior remains unchanged.

Verification:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py -q -k 'history_seed or continue or prepares_agent or restore_history or tool_chain'
```

Run the broader file only after the focused anchors pass and the telemetry fixture baseline is repaired:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py -q
```

Handoff artifact:

- One Web-to-Agent preparation path.
- Test evidence that cross-turn history is preserved and current input is not duplicated.
- Reconciled telemetry fields from the prior claim owner.

Risk and stop:

- Stop if telemetry has not explicitly handed off both files.
- Stop on new changes from the telemetry owner and reconcile before patching.
- Do not modify `ChatCodingRoute.tsx` merely to mask backend duplication.

### Task 5: prove the golden chain across backend and frontend

Observable output:

One shared canonical fixture drives deterministic backend and frontend acceptance for a tool-using first turn and a context-dependent follow-up turn. Live and persisted projections converge to one visible lifecycle per tool and one final answer per turn.

Files and claim boundary:

- `tests/fixtures/conversation_chain/canonical_tool_followup_v2.json`
- new `tests/test_conversation_chain_acceptance.py`
- `tests/test_session_codex_transcript_projection.py`
- new `web/src/routes/chatConversationChainAcceptance.test.ts`

Branch and worktree:

- Branch: `codex/conversation-golden-acceptance`
- Worktree: `C:\Users\17533\Desktop\Vibelution-worktrees\conversation-golden-acceptance`

Dependencies:

- Task 4 merged into local `main`.
- Consumes Task 3 protocol invariants and Task 4 Web DTO/SSE contract.

Mode: `BDD_TDD`

Test anchors:

- One fixture is loaded by both Python and TypeScript tests.
- Responses and Chat preserve equivalent canonical history.
- The frontend production router, scheduler, apply controller, and projection helpers consume the same ordered fixture.
- Terminal detail replay is idempotent.
- Reload detail produces the same semantic transcript without a live overlay.
- Turn 2 retains turn 1 and appends one new user input.
- Failure fixture settles to one error and no spinner.

Verification:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_conversation_chain_acceptance.py tests/test_session_codex_transcript_projection.py -q
npm --prefix web run test -- chatConversationChainAcceptance.test.ts chatSessionStreamProtocol.test.ts chatTurnProtocol.test.ts chatStreamApplyController.test.ts ChatActiveTurnLayer.test.ts
npm --prefix web run build
```

Handoff artifact:

- Shared golden fixture with stable identities and bounded placeholder content.
- Backend acceptance evidence.
- Frontend convergence and idempotence evidence.

Risk and stop:

- If a production defect is found outside the listed files, open one exact follow-up claim for its real owner rather than broadening Task 5.
- Do not duplicate the fixture under `web/`.
- Do not use a live provider as the deterministic test oracle.

### Task 6: make the chain Agent-diagnosable and close it live

Observable output:

An Agent can reconstruct one turn across a runtime scene by identity, identify the last successful boundary and terminal reason without opening raw prompts, and correlate the result with a fresh visible two-turn acceptance run.

Files and claim boundary:

- `tools/conversation_log_tools.py`
- `tests/test_conversation_log_tools.py`
- focused `tests/test_runtime_scene_package_diagnosis.py` only if package joining requires it
- no telemetry-owned production file unless its owner explicitly hands off an exact scope

Branch and worktree:

- Branch: `codex/conversation-trace-closeout`
- Worktree: `C:\Users\17533\Desktop\Vibelution-worktrees\conversation-trace-closeout`

Dependencies:

- Task 5 merged into local `main`.
- Final telemetry identity/redaction contract available.
- Launcher active-work guard permits refresh.

Mode: `BDD_TDD` for inspector behavior, followed by a `SIMPLE` live acceptance gate.

Test anchors:

- Reconstruct a turn across runtime-scene files using session, submission, turn, and invocation identities.
- Report missing identities without timestamp guessing.
- Report ordered boundaries and last successful boundary.
- Pair tool lifecycle by canonical call identity.
- Redact prompts, reasoning, tool payloads, replay data, and secrets.
- Keep output bounded.

Verification:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_conversation_log_tools.py tests/test_runtime_scene_package_diagnosis.py -q
```

Live gate:

- Refresh through Launcher once after all runtime/frontend changes are integrated.
- Run one Responses two-turn tool scenario and one Chat scenario when a configured route is available.
- Reload between live and settled states.
- Record safe runtime scene/session/turn identities, one screenshot after each turn, inspector output, and visible cardinalities.
- Require `conversation_logs > 0`, `agent_logs > 0`, complete correlation, one terminal outcome, and no stale spinner.

Handoff artifact:

- Agent-friendly bounded diagnosis result.
- Fresh runtime scene ID and safe evidence summary.
- Visual acceptance paths.
- Final version-impact judgment and project-memory delta proposal.

Risk and stop:

- Use the standard active-work block message if Launcher refresh is blocked.
- Do not force refresh without the exact project confirmation phrase.
- Do not claim runtime acceptance when only deterministic tests ran.
- If Chat runtime is unavailable, report missing live coverage while retaining deterministic Chat protocol evidence.

### Integration order and merge gates

Merge order into local `main`:

```text
Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 5 -> Task 6
```

Task 2 and Task 3 may develop in parallel, but integration remains serial so Task 4 starts from one reconciled mainline.

Each task owner must:

- Check guard state before edits and before merge.
- Keep a clean, task-scoped worktree.
- Write failing behavior tests first for the declared BDD/TDD anchors.
- Run only focused verification until the local behavior is green.
- Review its own diff for unrelated changes and secret/log exposure.
- Stage only listed task files.
- Commit with a behavior-oriented message.
- Re-check local `main`, merge safely, and rerun the focused gate on local `main`.
- Release its claim with commit and verification evidence.
- Report Launcher refresh as deferred until Task 6 unless immediate runtime verification is required by a discovered risk.

No task pushes remotely, creates a PR, edits version files, or cleans another task's worktree without explicit authorization. Ordinary task owners report version impact; the final integration owner makes one consolidated SemVer decision. Project memory is synchronized once at final closeout from merged evidence rather than rewritten by every parallel worker.

### Execution route

Current task after graph activation: Task 1.

Continuous execution: yes. Once the plan artifact is available to task worktrees and Task 1 obtains its exact claim, proceed along the critical path without reopening design or asking between tasks. Pause only at the declared claim, contract, validation, merge, or Launcher gates.

Success evidence:

- Every task produces the handoff artifact consumed by its successor.
- No production file has simultaneous owners.
- Task 2 and Task 3 merge cleanly after their allowed parallel development.
- Task 4 uses the final telemetry contract rather than duplicating it.
- Task 5 proves one canonical two-turn chain across backend and frontend.
- Task 6 produces identity-complete, Agent-readable, fresh runtime evidence.

Global stop conditions:

- Unexpected user or Agent changes appear in a file owned by the current task.
- Guard reports an overlapping active claim.
- A predecessor artifact is missing or contradicts the accepted contract.
- A focused test failure reveals a different owning surface.
- Local `main` cannot accept a safe scoped merge.
- Launcher refresh is blocked by active work or the runtime config cannot resolve a valid model route.
