# External Agent Service Pack

The pack owns the backend policy and durable task projection for the local MCP
managed-Agent gateway. Session and Turn content remain owned by the existing
session services; this pack stores only opaque task ownership, bounded status,
lease, permission, and Session/Turn references.

- `policy.py`: the single non-team external eligibility policy.
- `store.py`: atomic task projection persistence under `.runtime/external_agents/`.
- `service.py`: task lifecycle, approval, cancellation, and recovery orchestration.

Operator policy comes from `[external_agent_gateway]` in the active operator
config.  The production default is disabled and read-only.  All state changes
emit bounded runtime-scene events without prompts, tool arguments, tokens, or
full Agent replies.

The MCP adapter must call this pack through the loopback API, never by importing
write services directly.
