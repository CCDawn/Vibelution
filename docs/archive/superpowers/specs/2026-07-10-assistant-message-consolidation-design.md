# Assistant Message Consolidation Design

## Problem

The same completed assistant response can appear twice in the conversation UI. The observed turn persisted two events with identical text and the same `turnId`:

- `assistant_delta_committed`, projected as `assistant_timeline_segment`
- `assistant_message`, persisted as the completed response

The model generated one answer, but the frontend treated the provisional stream segment and the canonical final message as two independently visible messages.

## Reference Pattern

OpenAI Codex TUI separates provisional streaming presentation from canonical transcript presentation:

1. Streaming deltas update temporary `AgentMessageCell` instances and a mutable tail.
2. When the message completes, the final payload is not appended again if streaming already accumulated the content.
3. A consolidation event replaces the trailing provisional cells with one source-backed `AgentMarkdownCell`.
4. Persisted transcript replay renders only canonical `ThreadItem::AgentMessage` items.

Vibelution should preserve the same ownership rule while adapting it to a browser timeline, where tool and status events may be interleaved. Therefore, consolidation must use stable message identity rather than relying on contiguous array position.

## Decision

Introduce canonical assistant-message consolidation in the frontend timeline projection.

For each assistant message identity:

- `assistant_delta_committed` represents a provisional `draft` projection.
- `assistant_message` represents the canonical `final` projection.
- If both exist, only the final projection is visible.
- If no final projection exists, the committed draft remains visible for interrupted-turn recovery.
- Tool, status, reasoning, commentary, and other assistant items remain independently visible.

The final message is authoritative even if its text differs from the accumulated draft.

## Identity

The durable identity should be:

```text
sessionId + turnId + itemId
```

The initial frontend fix may use the strongest identity currently available in projected messages. It must not deduplicate solely by text. If `assistant_delta_committed` and `assistant_message` do not currently share a stable `itemId`, backend event metadata should be aligned in a follow-up change.

## Frontend Data Flow

```text
session timeline events
        |
        v
classify assistant projections as draft or final
        |
        v
group by stable assistant message identity
        |
        +-- final exists --> emit final only
        |
        +-- no final -----> emit latest/merged draft
        |
        v
existing process-message projection and rendering
```

Consolidation belongs before final rendering and after enough normalization exists to identify role, turn, item, and projection source. The renderer should receive one primary assistant text projection per message identity.

## Scope

The first implementation is limited to the conversation timeline projection and focused regression coverage.

Expected files:

- `web/src/components/conversation/useAgentMessageTimelineProjection.ts`
- A focused projection or conversation-view test covering the duplicate event sequence

Backend event-schema changes, historical data migration, SSE retry handling, and broad timeline refactoring are out of scope for the first fix.

## Edge Cases

- A completed turn with both draft and final renders one final response.
- An interrupted turn with only a committed draft still renders recoverable text.
- A final message that differs from the draft replaces the draft.
- Two assistant items in one turn remain distinct when their item identities differ.
- Commentary or tool/status items in the same turn are not removed.
- Identical text in different turns or item identities is not deduplicated.
- Replaying the same stream event remains a separate idempotency concern unless a stable event ID is available.

## Test Strategy

Use test-first development with the smallest fixture reproducing the observed journal sequence:

1. Add `assistant_delta_committed` and `assistant_message` projections with the same turn/message identity and identical text.
2. Assert the visible assistant text appears once.
3. Verify the test fails before production changes.
4. Implement the smallest projection consolidation needed to pass.
5. Add focused cases for interrupted draft-only recovery and differing final text.

No content-based global deduplication is permitted.

## Success Criteria

- The reported AMD395 response renders once.
- Completed assistant messages have one canonical visible owner.
- Draft-only recovery remains visible.
- Other timeline items in the same turn are preserved.
- Existing native-transcript suppression behavior remains intact.

## Follow-up Hardening

After the frontend fix, align backend stream and final events around a stable `itemId`, and add a unique `eventId` or monotonic stream sequence for replay idempotency. This follow-up is not required to resolve the confirmed duplicate projection.
