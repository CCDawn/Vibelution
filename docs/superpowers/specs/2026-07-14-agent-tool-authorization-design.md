# Unified Agent Tool Authorization Design

**Date:** 2026-07-14  
**Status:** Proposed  
**Scope:** Agent tool registration, assignment, model visibility, execution authorization, configuration, audit, and migration

## 1. Decision

Vibelution will use one authorization pipeline for every Agent and every LLM protocol:

1. `Tool Registry` owns facts about registered tools and their risk/capability metadata.
2. `ToolPolicy` owns each Agent's durable tool assignment and maximum permission boundary.
3. `TurnToolGrant` may only narrow that durable boundary for one turn.
4. `ToolAuthorizationService` is the sole resolver for both model-visible tools and executable tools.
5. `ToolExecutor` performs a second authorization check immediately before execution.

The default session Agent remains a full coding Agent and keeps its existing default tool package. This design does not introduce a separate low-capability chat Agent.

## 2. Required behavior

For every Agent:

- A tool assigned by its effective `ToolPolicy`, globally available, and compatible with the current turn is visible to the model.
- A tool not assigned to the Agent is absent from the LLM request and cannot be invoked through replay, aliases, direct HTTP payloads, subagents, or internal fallbacks.
- A visible tool can execute only when its current scope, risk, approval, workspace, network, and runtime constraints pass.
- `blockedTools` and explicit deny rules always win.
- `preferredTools` and runtime recommendations can order or suggest tools but can never grant access.
- Prompt text, Agent-to-Agent messages, tool output, memory content, and model output can never expand permissions.
- Missing, corrupt, stale, or unresolved authorization facts fail closed for high-risk behavior and produce an actionable diagnostic.
- The same authorization semantics apply to Responses, Chat Completions, replay continuation, parallel tool calls, and internal Agent turns.

## 3. Non-goals

- Reducing the default session Agent tool count solely for token savings.
- Replacing OS/process sandboxing with ToolPolicy.
- Allowing a model to approve its own permission request.
- Encoding tool permissions in prompts.
- Maintaining separate authorization implementations for research, self-evolution, supervised, direct-chat, or team Agents.

## 4. Current problems

Authorization is currently distributed across `Key_Tools.create_llm_facing_tools`, default session lists, fixed-role profiles, Agent `ToolPolicy`, mode policies, runtime goals, configuration switches, recommender output, and per-tool executor guards. This creates four defect classes:

1. **Parallel sources of truth:** the same tool can be included or excluded by unrelated modules.
2. **Visibility/execution drift:** a model can see a tool that later fails authorization, or an execution path can bypass model visibility.
3. **Fail-open behavior:** permission lookup exceptions or missing runtime packets can broaden access.
4. **Unclear configuration semantics:** `allowed`, `preferred`, global `enabled`, runtime capability, and recommendation are not visibly separated.

## 5. Canonical data model

### 5.1 ToolDescriptor

Every registered tool has one canonical descriptor:

```ts
type ToolDescriptor = {
  name: string;
  schemaVersion: number;
  schemaHash: string;
  enabled: boolean;
  capabilities: ToolCapability[];
  risk: "read" | "write" | "execute" | "network" | "destructive";
  concurrency: "safe" | "serialized";
  scopes: string[];
  approval: "never" | "on_request" | "always";
  availability?: {
    platforms?: string[];
    requiredConfig?: string[];
  };
};
```

`Tool Registry` owns these facts. Agent configuration cannot redefine tool risk or capability metadata.

### 5.2 ToolPolicy v2

Each active Agent references exactly one durable policy, including explicit zero-tool Agents.

```ts
type ToolPolicyV2 = {
  policyId: string;
  policyVersion: number;
  allowedTools: string[];
  blockedTools: string[];
  preferredTools: string[];
  readScopes: string[];
  writeScopes: string[];
  networkAccess: "none" | "restricted" | "full";
  mutationAccess: "none" | "workspace" | "controlled";
  delegationAccess: "none" | "assigned_only";
  maxCallsPerTurn: number;
  approvalOverrides: Record<string, "never" | "on_request" | "always">;
};
```

Rules:

- `allowedTools` is the durable assignment.
- `blockedTools` has higher priority than `allowedTools`.
- `preferredTools` must be a subset of effective allowed tools.
- Empty `allowedTools` is a valid explicit no-tool policy, not a missing policy.
- Policy templates may be shared, but every Agent reference must resolve to a concrete immutable policy version for a running turn.

### 5.3 TurnToolGrant

The host creates a turn-scoped grant. It cannot add tools beyond the Agent policy.

```ts
type TurnToolGrant = {
  turnId: string;
  source: "session" | "team" | "research" | "supervised" | "self_evolution";
  allowedCapabilities: ToolCapability[];
  deniedTools: string[];
  readScopes?: string[];
  writeScopes?: string[];
  networkAccess?: "none" | "restricted" | "full";
  mutationAccess?: "none" | "workspace" | "controlled";
  approvalMode: "never" | "on_request";
};
```

Omitted turn constraints inherit the Agent maximum. Explicit turn constraints only narrow it.

### 5.4 AuthorizationDecision

The resolver returns one immutable snapshot per turn:

```ts
type AuthorizationDecision = {
  agentId: string;
  turnId: string;
  policyId: string;
  policyVersion: number;
  registryVersion: number;
  visibleTools: string[];
  executableTools: string[];
  preferredTools: string[];
  denied: Record<string, ToolDenyReason>;
  decisionFingerprint: string;
  generatedAt: string;
};
```

The fingerprint binds the LLM tool surface to execution authorization and is recorded with every tool call.

## 6. Single authorization formula

Model visibility:

```text
registered
INTERSECT globally_enabled
INTERSECT agent_allowed
MINUS agent_blocked
INTERSECT turn_capability_compatible
INTERSECT environment_available
= visible_tools
```

Execution:

```text
tool IN visible_tools
AND request decisionFingerprint matches the active turn
AND scope authorized
AND approval satisfied
AND sandbox/runtime guards pass
= executable
```

No other module may add a tool after this calculation.

## 7. Resolution priority

From strongest to weakest:

1. Tool absent/disabled in Registry: deny.
2. Agent `blockedTools`: deny.
3. Tool absent from Agent `allowedTools`: deny and hide.
4. Turn explicit deny or missing capability: deny and hide.
5. Environment/config unavailable: hide with diagnostic.
6. Scope, approval, sandbox, or runtime guard failure: visible when useful, but execution denied with a structured reason.
7. Preferred/recommended status: ordering only.

Unknown tool names and aliases must normalize through the Registry before policy evaluation. Unknown names are denied.

## 8. Runtime architecture

### 8.1 New owner

Add `core/authorization/tool_authorization_service.py` as the only public authorization API:

```python
resolve_turn_tools(context) -> AuthorizationDecision
authorize_tool_call(context, tool_name, arguments, fingerprint) -> ToolAuthorizationResult
explain_tool_decision(context, tool_name) -> ToolAuthorizationExplanation
```

Pure policy computation should live in `core/authorization/tool_policy_evaluator.py`; persistence and Agent lookup remain in existing services.

### 8.2 LLM binding

Before every Agent turn:

1. Resolve Agent identity and concrete policy version.
2. Build the host-owned `TurnToolGrant`.
3. Resolve one `AuthorizationDecision`.
4. Bind only descriptors in `visibleTools` to the LLM.
5. Store the decision fingerprint in turn context and invocation logs.

The same semantic tool list is projected independently to Responses and Chat wire formats. Protocol adapters cannot change authorization.

### 8.3 Execution gate

Every tool call, including replayed and parallel calls, enters `authorize_tool_call` before dispatch. The executor must reject:

- hidden or unassigned tools;
- stale/missing fingerprints;
- calls from the wrong Agent or turn;
- scope escalation in arguments;
- unsatisfied approval;
- disabled/unavailable tools;
- calls exceeding the policy's per-turn budget.

Internal tools are not exempt. A system-only tool needs an explicit system ToolPolicy and host-owned grant.

### 8.4 Permission requests

`agent_tool_permission_request_tool` creates a proposal only. It does not mutate the active decision.

Flow:

1. Agent requests a named tool/capability and explains the reason.
2. Backend verifies the tool exists and computes the requested delta.
3. UI shows affected Agent, policy, risk, scopes, and duration.
4. User applies a durable policy update or a future-turn temporary grant.
5. The active turn remains unchanged; a new decision is created for the next turn.

## 9. Configuration and API

### 9.1 Configuration source

Agent Directory `toolPolicies` remains the durable assignment source. Operator `[tools]` configuration controls global availability only and cannot grant an Agent access.

Fixed role profiles become policy templates that materialize ordinary `ToolPolicyV2` records. Runtime code must not enforce a second hidden role allowlist.

### 9.2 API contracts

Add or normalize endpoints:

- `GET /api/tools/registry`: descriptors and availability, no secrets.
- `GET /api/tool-policies`: policy summaries and affected Agent counts.
- `GET /api/tool-policies/{policyId}`: complete editable policy.
- `POST /api/tool-policies/validate`: dry-run validation and effective diff.
- `PUT /api/tool-policies/{policyId}`: optimistic versioned update.
- `POST /api/agents/{agentId}/tool-policy`: assign an existing policy.
- `GET /api/agents/{agentId}/tool-authorization`: effective policy and last-turn decision.
- `POST /api/tool-authorization/explain`: explain why a tool is visible/hidden/denied.

Updates require `expectedPolicyVersion`; stale writes return `409`.

### 9.3 Configuration UI

The Agent configuration surface must separate:

- **Assigned tools:** durable allowlist.
- **Explicitly blocked tools:** deny overrides.
- **Preferred tools:** ordering only.
- **Capability/scopes:** read, write, network, mutation, delegation.
- **Approval requirements:** tool-specific overrides.
- **Effective preview:** visible, unavailable, denied, and reason.

Saving must show a diff, affected shared-policy Agents, newly added high-risk tools, and tools removed from active Agents. Shared policies require explicit impact confirmation.

## 10. Fail-closed behavior

Replace broad fallback behavior with typed outcomes:

- Unknown Agent: no tools, `agent_unresolved`.
- Missing policy: no tools, `policy_missing`.
- Corrupt policy: no tools, `policy_invalid`.
- Registry unavailable: no tools, `registry_unavailable`.
- Missing turn grant: no mutating/network/delegation tools; session bootstrap may use an explicitly named minimal recovery policy only.
- Authorization service exception: reject execution and publish bounded error telemetry.

There is no fallback that returns all tools. Recovery policies are explicit policy records, not exception handlers.

## 11. Audit and observability

Required runtime scene events:

- `tool.authorization.surface_resolved`
- `tool.authorization.call_allowed`
- `tool.authorization.call_denied`
- `tool.authorization.policy_invalid`
- `tool.authorization.policy_updated`
- `tool.authorization.permission_requested`
- `tool.authorization.permission_resolved`

Bounded fields:

```text
agentId, turnId, callId, toolName, policyId, policyVersion,
registryVersion, decisionFingerprint, outcome, denyCode,
risk, capability, approvalMode, durationMs
```

Do not log tool arguments, secrets, full prompts, full schemas, or unbounded outputs. Logs must support an Agent-facing explanation tool without exposing sensitive values.

## 12. Caching and invalidation

Cache immutable decisions by:

```text
agentId + policyVersion + registryVersion + turnGrantHash + environmentHash
```

Invalidate on policy update, Agent policy reassignment, Registry availability change, operator tool configuration change, workspace/sandbox change, or turn change. Execution always checks that the call fingerprint matches the active decision.

## 13. Migration

Migration is additive before enforcement:

### Phase A: Canonical evaluator in shadow mode

- Build descriptors for existing tools.
- Materialize existing session defaults and fixed-role profiles as ToolPolicy v2 snapshots.
- Compute new decisions alongside legacy filtering.
- Log bounded visibility diffs; legacy behavior remains active.

### Phase B: Visibility enforcement

- New service becomes the sole source for LLM-bound tools.
- Legacy filters remain as assertions only.
- Protocol acceptance tests prove identical authorized surfaces for Responses and Chat.

### Phase C: Execution enforcement

- Require decision fingerprints at the executor boundary.
- Reject hidden/unassigned/stale calls.
- Preserve explicit approval and sandbox gates.

### Phase D: Configuration cutover

- Enable versioned policy editing, assignment, preview, and explain UI.
- Migrate all Agent records to concrete policy IDs.
- Mark legacy wide policies for explicit operator review without silently narrowing them.

### Phase E: Remove parallel authorities

- Remove authorization behavior from `create_llm_facing_tools` exclusions, fixed-role runtime branches, and fail-open exception handlers.
- Keep Registry assembly, policy templates, recommendations, and execution guards in their correct non-authoritative roles.

## 14. Compatibility and rollback

- Existing policy IDs remain addressable through a one-time normalized v2 projection.
- `blockedTools` accepts legacy `deniedTools` during migration, but storage writes only the canonical field.
- Existing Agents with the session default package keep the same assigned tools.
- Explicit zero-tool Agents remain zero-tool.
- Legacy wide private policies are preserved and labeled; no silent privilege expansion or reduction.
- Rollback selects the previous evaluator version and its last valid policy snapshot. Rollback never means bypassing authorization or exposing all tools.

## 15. Validation matrix

Required automated coverage:

1. Assigned tool is visible and executable.
2. Unassigned tool is absent from the LLM payload and rejected by direct execution.
3. Blocked tool is denied even when allowed/preferred.
4. Preferred tool cannot grant access.
5. Turn grant can narrow but cannot expand Agent policy.
6. Unknown Agent/policy/tool and resolver exceptions fail closed.
7. Responses and Chat receive the same semantic visible set.
8. Replay and parallel calls preserve `callId`, Agent, turn, and fingerprint.
9. Stale fingerprints and cross-turn/cross-Agent calls are denied.
10. Scope, network, mutation, delegation, approval, and max-call limits are enforced.
11. Policy update invalidates cache and affects only the next decision.
12. Shared-policy edits report all affected Agents.
13. Prompt injection and Agent messages cannot alter permissions.
14. Self-evolution/supervised no-tool roles remain no-tool.
15. Legacy policies migrate without silent expansion.

## 16. Acceptance criteria

The design is complete when runtime evidence proves:

- every active Agent resolves exactly one policy;
- every LLM invocation records one authorization fingerprint;
- the LLM payload contains exactly the resolved visible tools;
- every tool execution records an allowed or denied decision against that fingerprint;
- no direct, replay, parallel, subagent, or protocol path bypasses authorization;
- operators can configure assignments and understand effective results before saving;
- permission failures are diagnosable without exposing secrets;
- all legacy fail-open paths and parallel authorization authorities are removed.

## 17. Reference decisions

- Vibelution's existing Agent Kernel plan already requires all tool use to pass Tool Registry and ToolPolicy.
- OpenAI Codex separates turn permission profiles, approval policy, sandbox policy, and execution checks; Vibelution follows the same separation of concerns while retaining Agent-specific durable assignments.
- Claude-style `allowedTools` demonstrates that model visibility must be derived from explicit permission context, with execution-time permission checks remaining authoritative.

