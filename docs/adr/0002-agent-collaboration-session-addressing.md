# Agent Collaboration Uses Session Landing With Retained Inbox

## Status

Accepted (requirements alignment 2026-08-03).

## Context

`agent_message_tool` today addresses a **target Agent**, persists into an **Agent inbox**, and optionally wakes that Agent's **default direct session**. That model is too coarse for product use:

- Users think in **session tabs**, not mailboxes.
- "Send it to that conversation" cannot be expressed safely.
- Inbox-only consumption feels like an extra hop and delays wake.

Mature multi-agent systems separate concerns:

| Layer | Role |
| --- | --- |
| **Mailbox / outbox** | Reliable delivery, audit, retry, dead-letter (Actor mailbox, enterprise messaging) |
| **Thread / context / session** | Continuous dialogue and user-visible history (A2A `contextId`, OpenAI handoff thread) |
| **Task / turn** | One unit of work that may be scheduled immediately |

This ADR locks Vibelution's collaboration send path to that split, without deleting inbox infrastructure.

## Decision

### 1. Semantic model: **C (session authority + inbox index/log)**

- **Authoritative landing** for collaboration content: the **target session's visible conversation history**.
- **Inbox is retained** as a **delivery log / recovery index / future queue surface**, not as the primary user UX for reading collab messages.
- Phase 1 implementation **MAY dual-write full body** into both session history and inbox, but **MUST** share one `messageId` and treat **session history as the source of truth** for UI and model context assembly.
- Phase 2 **SHOULD** shrink inbox rows to pointers (`bodyRef` → session message) plus status machine fields.

### 2. Addressing: explicit `targetSessionId` is required

- Collaboration send **MUST** require `targetSessionId` (tool/API field; name may be `target_session`).
- Resolve session first; derive `targetAgentId` from the session ownership record.
- **MUST NOT** trust a caller-supplied agent id when it disagrees with the session owner.
- **MUST NOT** fall back to "default direct session" when session is missing or invalid.
- Missing/invalid session → hard block with a typed error (see Contract).

### 3. Wake: default immediate wake of **that session**

- Default `wakeTarget=true`.
- Wake target is the **resolved `targetSessionId`**, not "whatever directSessionId the agent currently has" unless they are the same.
- Success for the happy path: history appended **and** wake requested (or session already running).
- If wake fails after a successful history write: **partial success** — keep history + inbox row with `wakeStatus=failed` / retryable; do not pretend full success.

### 4. Cross-agent sessions: allowed under strong gates

- Same-agent multi-session: require session ownership match only.
- Cross-agent: require organization / research-graph policy (and any future user-authorization gates) **before** write or wake.
- Opaque execution: deliver structured collab payload only; do not dump peer internal tool traces by default.

### 5. Inbox retention (not removed)

Inbox remains for:

- delivery audit and idempotency,
- Agent-level pending counts / ops surfaces,
- recovery of failed wakes,
- future queue policies (busy deferral, priority, TTL, dead-letter).

Inbox **MUST NOT** be required for the user to *see* a newly sent collab message in the target session tab.

### 6. Out of scope (this ADR)

- Full A2A Task streaming protocol.
- GroupChat / shared multi-speaker room as default collab path.
- Deleting historical inbox APIs in phase 1.
- Automatic session inference from free-text ("send to that one") without an explicit session id.

## Contract (tool / kernel)

### Tool surface (target)

```
agent_message_tool(
  target_session: str,   # REQUIRED session id
  content: str,          # REQUIRED body
  summary: str = "",
  wake_target: bool = True,  # default immediate wake on that session
  thread_id: str = "",       # optional business correlation; defaults may equal session
  metadata_json: str = "",
)
```

Compatibility: a transitional overload that accepts only `target_agent` is **deprecated**. New call sites **MUST** pass `target_session`. Deprecation window and hard-removal are tracked in implementation tasks, not here.

### Delivery object (logical)

```
AgentCollaborationMessage
  messageId            # shared across session row + inbox row
  sourceAgentId
  sourceSessionId      # sender runtime session when available
  targetSessionId      # REQUIRED landing
  targetAgentId        # derived from target session
  content
  summary
  wakeTarget
  correlationId?       # optional task/turn linkage
  policyRoute          # same_agent | cross_agent
  delivery
    historyStatus      # appended | rejected
    historyMessageId?
    inboxStatus        # recorded | skipped_legacy | failed
    inboxMessageId?
    wakeStatus         # started | already_running | failed | not_requested
    turnId?
    reason?
```

### Error codes (minimum)

| Code | When |
| --- | --- |
| `target_session_required` | Missing session id |
| `session_not_found` | Unknown / inaccessible session |
| `session_agent_mismatch` | Caller agent claim disagrees with session owner (if applicable) |
| `policy_blocked` | Cross-agent or org graph rejection |
| `content_required` | Empty body |
| `self_session_blocked` | Optional: block noop self-spam if product requires |
| `wake_failed` | History ok, wake did not start (partial) |
| `history_append_failed` | Could not land on session |

### Idempotency

- Generate or accept a stable `messageId` / `idempotency_key` per send.
- Retries with the same key **MUST NOT** create duplicate user-visible bubbles in the target session.

### Model / UI rules

- Conversation assembly for turns **reads session history**, not pending inbox, for collab body.
- Inbox list UIs remain available for ops / unread; they **SHOULD** deep-link to `targetSessionId`.

## Consequences

### Positive

- User-visible landing matches session tabs.
- Immediate wake aligns with "send then run" collaboration.
- Inbox kept for reliability and future queue optimization.
- Aligns with mature split: mailbox reliability + thread continuity (A2A context / handoff-style landing).

### Negative / costs

- Kernel and `agent_message_tool` must grow session resolution and dual-write/pointer logic.
- Cross-agent policy path must run before side effects.
- Dual-write phase needs careful idempotency to avoid double bubbles.
- Legacy agent-only callers need migration.

### Follow-up implementation order (non-normative)

1. Contract tests for address resolution and error codes.
2. Session history append path for collab message type.
3. Inbox write with shared `messageId` + `targetSessionId`.
4. Wake bound to `targetSessionId`.
5. Deprecate agent-only addressing; update prompts/tool schemas.
6. Phase 2: pointer-only inbox, busy queue, ack/TTL/dead-letter.

## References

- Prior product alignment: session landing, required session id, cross-agent strong gates, retain inbox, default immediate wake.
- Industry: Actor mailbox; Google A2A Message / Task / `contextId`; OpenAI Agents handoff (same-thread transfer) as UX analogue for "land in conversation", not as exclusive protocol.
- Code touchpoints (implementation): `tools/agent_message_tools.py`, `core/agent_kernel/*`, agent inbox services under `core/web/services/agent_directory_service.py` (and related).
