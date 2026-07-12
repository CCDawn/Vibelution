# LLM Turn Chain Recovery Design

- Date: 2026-07-12
- Status: Approved direction, written review pending
- Lane: `llm-turn-chain-recovery`
- Branch: `codex/llm-turn-chain-recovery`

## 1. Context

The protocol adapter cutover already gives Chat Completions and Responses separate wire encoders and decoders. The remaining defects are above and below that adapter boundary:

1. The current user submission can appear in seeded chat history and then be appended again by turn preparation.
2. `LLMClient` retries a failed effective route while `Agent` can retry the same route again after client exhaustion.
3. Agent fallback can reuse invocation state created for the primary route instead of resolving a fresh route, adapter, endpoint, and invocation scope.
4. Frontend rendering is event-driven. It cannot display assistant content that the backend has not committed, but it must display canonical progress and terminal failure items consistently.

The observed Pixel `502 upstream_error` is an external provider failure. It is useful evidence for exposing the duplicate-input and nested-retry defects, but provider repair is not part of this change.

## 2. Goals

1. Send exactly one canonical current user submission to every effective model route.
2. Preserve identical user text from different historical turns.
3. Keep dynamic runtime context immediately before the canonical current user message.
4. Make `LLMClient` the sole owner of retries within one effective route.
5. Allow `Agent` at most one fallback to a different effective route.
6. Build a fresh route, adapter, endpoint, client, and invocation scope for fallback.
7. Keep Chat payloads in the Chat protocol and Responses payloads in the Responses protocol.
8. Publish bounded lifecycle evidence without raw prompts, secrets, or unbounded provider output.

## 3. Non-goals

This design does not change:

- the XML tool fast path;
- frontend visual layout or React projection precedence;
- Pixel provider availability or upstream behavior;
- API key persistence lifecycle;
- operator model/provider configuration;
- Anthropic, Gemini, or other native protocol implementations;
- version files or release metadata.

## 4. Source-of-truth ownership

| Concern | Canonical owner | Required invariant |
| --- | --- | --- |
| Current submission identity | Host/session turn lifecycle | One stable submission or turn identity per user send |
| Prior conversation history | Host/session history projection | Contains completed prior turns, not the current submission |
| Current turn message ordering | Turn message preparation | Dynamic context is directly before one current user message |
| Same-route retry policy | `LLMClient` plus profile retry policy | One invocation scope, bounded transport attempts |
| Cross-route fallback | `Agent` recovery decision | Zero or one distinct fallback route |
| Wire request body | Route-specific `WireAdapter` | Encode semantic input separately for each route |
| Visible assistant outcome | `TurnOutcome` and journal events | One canonical committed item or terminal failure |
| Frontend projection | SessionTurnItem v2 projection | Render backend truth without reconstructing hidden model state |

No downstream layer may compensate for a violated upstream invariant by guessing from message text.

## 5. Canonical message assembly

### 5.1 Host/session contract

The host/session layer owns the boundary between historical turns and the active submission. When it creates model history for a new turn, it must exclude entries belonging to the current turn or submission identity.

The current submission is passed separately to turn preparation. History remains an ordered collection of completed prior messages. Two prior turns with the same text are two distinct messages and must both remain present.

If internal history records carry submission metadata, turn preparation may remove or reject only an entry whose identity exactly equals the current submission identity. It must never deduplicate by normalized text, content hash, role/content equality, or adjacency alone.

### 5.2 Turn preparation contract

Turn preparation produces this semantic order:

1. stable system instructions;
2. completed prior conversation history;
3. volatile or dynamic system context for the active turn;
4. exactly one canonical current user message.

The canonical current user message is always built from the explicit current submission argument. It is never selected from the history tail.

Text and multimodal submissions follow the same identity rule. Their content representation may differ, but each active submission appears once.

### 5.3 Protocol boundary

The semantic message sequence is protocol-neutral. A route-specific adapter encodes it into either Chat Completions or Responses format.

Fallback starts from the same semantic sequence and invokes a newly resolved adapter. It must not reuse, mutate, or translate the primary route's already encoded wire payload.

## 6. Retry and fallback state machine

### 6.1 Route attempt

A route attempt consists of:

- one resolved effective route;
- one route-specific adapter;
- one `LLMClient` instance or route-bound client view;
- one invocation context and invocation ID;
- one bounded same-route retry policy.

`LLMClient` owns all transport attempts for that route, including retryability classification, backoff, cancellation, and any permitted streaming downgrade. Transport attempts share the route invocation ID.

After `LLMClient` succeeds or exhausts its policy, `Agent` must not call the same effective route again.

### 6.2 Agent recovery

`Agent` acts as a route transition controller, not a second retry loop:

1. Resolve and invoke the primary route.
2. On success, return the canonical outcome.
3. On terminal or non-retryable failure, publish one terminal failure.
4. On exhausted retryable failure, select a configured fallback only when it resolves to a different effective route.
5. Resolve a fresh adapter, endpoint, client, and invocation context for that fallback.
6. Invoke the fallback once; its client may perform its own bounded same-route transport retries.
7. Return fallback success or publish one terminal failure.

The maximum number of effective route attempts per Agent turn is two: primary plus one fallback. The Agent never returns to the primary route, selects a third route, or performs a same-route stream-to-nonstream retry after client exhaustion.

### 6.3 Effective route identity

Fallback eligibility uses the resolver's canonical effective-route identity, not a display name. The identity must distinguish the resolved provider/profile, protocol, normalized endpoint, model, and adapter family without exposing credentials.

If a configured fallback resolves to the same effective route as the primary route, it is rejected as a duplicate route and the primary failure becomes terminal.

### 6.4 Invocation lineage

Primary and fallback route attempts have different invocation IDs. Both carry the same parent turn identity so logs and outcomes can be correlated without conflating transport attempts.

Within a route, transport retries retain the route invocation ID and increment a bounded transport-attempt counter.

## 7. Protocol alignment

Each effective route performs the complete semantic-to-wire lifecycle independently:

1. resolve route and protocol;
2. create the matching adapter;
3. encode canonical semantic messages and tool definitions;
4. invoke the route endpoint;
5. decode that protocol's events;
6. normalize decoded events into canonical turn events;
7. commit visible outcome items.

A Responses route uses Responses request and event semantics. A Chat route uses Chat Completions request and event semantics. A fallback may use a different protocol only because its own resolved route declares that protocol; no protocol is inferred from the failed request body.

## 8. Frontend relationship

No frontend code change is required for this slice. The frontend already prioritizes SessionTurnItem v2 and canonical committed outcomes over legacy deltas.

The backend must continue to emit:

- process feedback before the first assistant token when work is active;
- normalized reasoning or text items as they become visible;
- one canonical terminal failure when all permitted routes fail;
- one committed assistant outcome when a route succeeds.

The frontend must not fabricate assistant text while the provider has emitted none. A provider outage should therefore appear as progress followed by a clear terminal error, not as a blank successful answer.

## 9. Bounded observability

Lifecycle logs distinguish route transitions from transport retries:

| Event | Required bounded fields |
| --- | --- |
| `llm_route_attempt_started` | turn ID, invocation ID, route attempt, provider/profile/model/protocol identifiers |
| `llm_transport_retry_scheduled` | invocation ID, transport attempt, maximum attempts, reason code, bounded delay |
| `llm_route_attempt_exhausted` | invocation ID, attempts used, normalized error class, retryable flag |
| `llm_fallback_selected` | turn ID, primary route ID, fallback route ID, normalized reason code |
| `llm_turn_terminal` | turn ID, route attempts used, final normalized error class |

Logs must not include API keys, authorization headers, full prompts, full wire bodies, raw tool output, or unbounded provider responses.

## 10. Error semantics

The client returns or raises a structured route-attempt failure containing only the information Agent needs for route transition:

- effective route identity;
- invocation identity;
- normalized error class;
- retryability after policy exhaustion;
- transport attempts used;
- safe diagnostic summary.

The Agent does not reclassify individual transport failures. It decides only whether a distinct fallback route is permitted.

When fallback also fails, one canonical terminal outcome summarizes the final safe error while preserving bounded primary/fallback evidence in logs.

## 11. Test-first implementation requirements

Implementation starts with failing tests and demonstrates the expected failure before production edits.

### 11.1 Message assembly tests

- The active text submission appears exactly once.
- The active multimodal submission appears exactly once.
- Identical text from two completed historical turns is preserved twice.
- A history item with the exact current submission identity is excluded or rejected without text-based deduplication.
- Dynamic system context is immediately before the canonical current user message.

### 11.2 Recovery ownership tests

- Client retry exhaustion does not cause another Agent call to the same effective route.
- Agent does not perform its own stream-to-nonstream retry for the same route.
- A distinct fallback is invoked at most once.
- Primary and fallback use different route, adapter, endpoint, client scope, and invocation ID.
- Fallback starts from semantic messages rather than the primary wire payload.
- A fallback resolving to the primary effective route is rejected.
- Fallback failure produces one terminal outcome and no third route attempt.

### 11.3 Protocol and logging tests

- Responses fallback is encoded and decoded by a Responses adapter.
- Chat fallback is encoded and decoded by a Chat adapter.
- Route-attempt and transport-attempt counters remain distinct.
- Logs contain bounded identifiers and reason codes but no prompt or secret fields.

## 12. Planned implementation surface

Expected files are intentionally narrow:

- `agent.py` for route-transition control and fresh fallback invocation construction;
- the existing owner under `core/agent/` for canonical turn message preparation;
- `core/llm/client.py` only where a structured exhausted-route result or logging boundary is needed;
- `tests/test_agent_protocol.py` for message and Agent recovery contracts;
- `tests/test_llm_client.py` for same-route retry ownership;
- `tests/test_llm_client_outbound_wire_bridge.py` for invocation and adapter isolation.

Exact symbols and the smallest file set will be resolved in the implementation plan. No frontend file is expected to change.

## 13. Acceptance criteria

The change is accepted when focused evidence proves all of the following:

1. A model request contains one current user submission, with repeated historical text preserved.
2. Dynamic runtime context directly precedes that current submission.
3. Same-route call count never exceeds the client profile retry budget.
4. Agent route count never exceeds primary plus one distinct fallback.
5. Fallback has a fresh effective route, adapter, endpoint, and invocation ID.
6. Chat and Responses each retain their native wire lifecycle.
7. Successful and failed turns each produce one canonical visible terminal state.
8. Runtime-scene evidence is bounded and contains no secrets or full prompts.

## 14. Rollout and rollback

Implementation is split into two reviewable slices:

1. canonical current-submission assembly and ordering;
2. retry ownership and fresh fallback route construction.

Focused tests run after each slice, followed by the narrow protocol suite. A Launcher refresh is required before user-visible runtime verification because Agent and LLM runtime behavior changes. External provider probing is not part of acceptance.

Rollback reverts only these implementation commits. It does not modify operator configuration, API keys, provider profiles, frontend projection code, or unrelated protocol adapter commits.

## 15. Version impact

This is a patch-level runtime correctness change. The task reports version impact but does not edit `VERSION`, `CHANGELOG.md`, `web/package.json`, or `web/package-lock.json` during ordinary implementation.
