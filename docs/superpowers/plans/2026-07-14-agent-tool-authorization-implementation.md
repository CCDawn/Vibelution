# Unified Agent Tool Authorization Implementation Plan

**Date:** 2026-07-14  
**Design:** `docs/superpowers/specs/2026-07-14-agent-tool-authorization-design.md`  
**Route:** SPLIT_REQUIRED

## 1. Goal

Implement one enforceable authorization chain so every Agent sees and executes exactly its assigned tools, configuration is effective and explainable, and no protocol or runtime path can bypass policy.

## 2. Delivery strategy

Use seven serialized milestones. Each milestone produces an independently reviewable artifact and consumes the previous milestone's contract. Do not implement frontend configuration before the canonical evaluator and API projections are stable.

## 3. Source-of-truth map

| Fact | Canonical source | Writer | Readers / projections | Invalidation | Legacy cleanup |
|---|---|---|---|---|---|
| Tool identity, schema, risk, capability | Tool Registry descriptor | Tool registration code | authorization, API, UI, LLM adapters | registry version | remove policy metadata from scattered tool maps |
| Agent durable assignment | Agent Directory ToolPolicy v2 | versioned config API | authorization, Agent UI | policy version | migrate role/default policy branches |
| Turn restriction | host-created TurnToolGrant | session/team/research runtime owner | authorization only | every turn | remove implicit env/prompt grants |
| Model-visible tools | AuthorizationDecision | ToolAuthorizationService | LLM binding, logs, UI diagnostic | decision cache key | remove independent filtering |
| Execution permission | AuthorizationResult | ToolAuthorizationService | ToolExecutor, logs | every call | replace per-path allow decisions with constraints |
| Tool recommendation | ToolRecommender | runtime observation | prompt guidance, UI | observation state | ensure it cannot grant tools |

## 4. Milestone 0: Contract fixtures and inventory

**Owner:** authorization architecture  
**Depends on:** approved design

Tasks:

1. Inventory every LLM binding and tool dispatch entrypoint.
2. Inventory all Agent categories and current policy sources.
3. Add canonical fixtures for default session, explicit zero-tool, research, team, supervised, self-evolution, legacy-wide, and missing-policy Agents.
4. Add protocol fixtures for Responses, Chat, replay, and parallel tool calls.
5. Record current visible tool sets as migration baselines.

Primary files:

- `tests/fixtures/tool_authorization/`
- `tests/test_agent_lifecycle_create_delete.py`
- `tests/test_agent_protocol.py`
- `tests/test_llm_wire_responses.py`
- `tests/test_llm_wire_chat_completions.py`

Exit gate:

- every runtime entrypoint and Agent class has an owner;
- fixture expectations explicitly distinguish assigned, preferred, blocked, visible, and executable.

## 5. Milestone 1: Canonical Registry descriptors

**Owner:** tool registry  
**Depends on:** Milestone 0

Tasks:

1. Introduce canonical `ToolDescriptor` and `ToolCapability` types.
2. Adapt all built-in tools to descriptors without changing execution behavior.
3. Generate deterministic `schemaHash` and monotonic Registry version.
4. Validate duplicate names, aliases, missing risk metadata, and invalid capabilities at startup.
5. Expose a secret-safe Registry API projection.

Primary files:

- `core/web/services/tool_registry_service.py`
- `tools/Key_Tools.py`
- `core/infrastructure/tool_intents.py`
- `core/web/routes/config.py` or a dedicated tool route
- focused Registry tests

Logging:

- Registry version, descriptor count, invalid count, unavailable count.

Exit gate:

- every LLM-facing tool has exactly one descriptor;
- unknown or duplicate tools cannot enter the active Registry.

## 6. Milestone 2: Pure policy evaluator and v2 migration projection

**Owner:** authorization core  
**Depends on:** Milestone 1

Tasks:

1. Add pure `ToolPolicyV2`, `TurnToolGrant`, `AuthorizationDecision`, and deny-code models.
2. Implement deterministic deny-first evaluation with no I/O.
3. Implement legacy policy normalization (`deniedTools` to `blockedTools`, explicit zero-tool preservation).
4. Materialize default session and fixed-role profiles as policy templates.
5. Add fail-closed typed errors for missing Agent, policy, Registry, or grant.
6. Add decision fingerprinting and immutable cache keys.

Primary files:

- `core/authorization/tool_policy_models.py`
- `core/authorization/tool_policy_evaluator.py`
- `core/web/services/agent_directory_service.py`
- `core/web/services/agent_role_tool_profile_service.py`
- evaluator and migration tests

Key tests:

- table-driven allow/deny/preferred/capability/scope matrix;
- turn grant cannot expand policy;
- resolver exceptions never return all tools;
- default session package remains behaviorally unchanged.

Exit gate:

- evaluator is deterministic and has no fail-open result;
- all existing Agent policies can be projected without silent expansion.

## 7. Milestone 3: Shadow authorization and observability

**Owner:** runtime authorization integration  
**Depends on:** Milestone 2

Tasks:

1. Add `ToolAuthorizationService` and resolve shadow decisions for every turn.
2. Compare shadow `visibleTools` with the legacy bound tool surface.
3. Emit bounded diff telemetry with Agent, policy, reason counts, and fingerprints.
4. Add an Agent-facing explain query over authorization logs.
5. Do not enforce or mutate behavior in this milestone.

Primary files:

- `core/authorization/tool_authorization_service.py`
- `agent.py`
- `core/web/services/session_service.py`
- `core/logging/`
- `tools/conversation_log_tools.py`
- shadow parity tests

Exit gate:

- runtime scenes reconstruct every decision;
- no unexplained default-session visibility diffs;
- expected legacy-wide and fixed-role diffs are classified.

## 8. Milestone 4: Model visibility enforcement

**Owner:** Agent/LLM binding  
**Depends on:** Milestone 3 parity gate

Tasks:

1. Resolve authorization before each LLM turn.
2. Bind only `visibleTools` and carry `decisionFingerprint` in invocation context.
3. Project the same semantic tool surface to Responses and Chat adapters.
4. Make legacy filtering an assertion, then remove its authority.
5. Replace exception fallback returning all tools with typed no-tool failure.
6. Preserve default session Agent's current assigned tool set.

Primary files:

- `agent.py`
- `core/llm/invocation.py`
- `core/llm/client.py`
- `core/llm/wire/responses.py`
- `core/llm/wire/chat_completions.py`
- protocol and Agent integration tests

Exit gate:

- unassigned tools are absent from both wire protocols;
- authorized tool schemas and hashes are protocol-equivalent;
- missing authorization facts cannot broaden visibility.

## 9. Milestone 5: Execution enforcement and approval

**Owner:** tool execution/security  
**Depends on:** Milestone 4

Tasks:

1. Require Agent, turn, call ID, and decision fingerprint at the ToolExecutor boundary.
2. Authorize every normal, replayed, parallel, internal, and subagent call.
3. Enforce tool assignment, call budget, scope, network, mutation, delegation, approval, and runtime constraints.
4. Convert existing special guards into constraints evaluated after the canonical assignment decision.
5. Reject stale, cross-Agent, cross-turn, hidden, alias-injected, and unknown calls.
6. Make permission request tools proposal-only and next-turn effective.

Primary files:

- `core/infrastructure/tool_executor.py`
- `core/orchestration/tool_lifecycle.py`
- `core/orchestration/runtime_goal.py`
- `core/authorization/tool_authorization_service.py`
- approval/governance services
- executor security tests

Exit gate:

- direct executor calls cannot bypass policy;
- every dispatch has an allowed or denied audit event;
- no hidden tool reaches its implementation.

## 10. Milestone 6: Versioned configuration API and UI

**Owner:** Agent configuration  
**Depends on:** Milestone 5 contracts

Tasks:

1. Add versioned policy list/detail/validate/update/assign/explain endpoints.
2. Add optimistic concurrency and affected-Agent impact projection.
3. Separate assigned, blocked, preferred, scopes, capabilities, and approval controls in UI.
4. Add effective visibility preview and unavailable/denied reasons.
5. Require explicit confirmation for shared-policy and high-risk permission changes.
6. Ensure operator global tool switches only control availability.

Primary backend files:

- `core/web/services/agent_directory_service.py`
- `core/web/services/agent_config_workspace_service.py`
- `core/web/services/tool_registry_service.py`
- config/Agent routes and DTO tests

Primary frontend files:

- `web/src/api/types/agents.ts`
- Agent configuration route/panels
- policy editor logic and layout tests

Exit gate:

- an operator can assign/remove a tool and preview the exact next-turn effect;
- stale or invalid writes are rejected without partial updates;
- shared impact is visible before save.

## 11. Milestone 7: Cutover and cleanup

**Owner:** integration/release  
**Depends on:** all previous gates

Tasks:

1. Migrate every active Agent to a concrete policy ID/version.
2. Preserve and label legacy-wide policies for manual review.
3. Activate authorization enforcement for all run kinds.
4. Remove parallel role/runtime allowlists and fail-open fallback code.
5. Remove migration aliases after compatibility fixtures pass.
6. Update project memory, operational documentation, and diagnostic runbook.

Exit gate:

- direct chat, team, research, supervised, self-evolution, replay, and subagent paths all use the canonical service;
- repository search finds no runtime authorization bypass;
- Launcher-refreshed runtime smoke proves assignment, removal, denial, approval, and explain flows.

## 12. Test and release gates

Focused gates per milestone precede wider tests. Final gate includes:

1. Authorization unit matrix.
2. Agent lifecycle/policy migration tests.
3. Responses and Chat protocol acceptance tests.
4. Parallel/replay tool lifecycle tests.
5. Direct ToolExecutor bypass tests.
6. Config API transaction and concurrency tests.
7. Frontend policy editor logic/layout tests.
8. `npm --prefix web run build`.
9. Launcher refresh and runtime scenes for one allowed, one hidden, one denied, and one approval-required call.

No milestone may claim success from UI-only evidence. Runtime evidence must show both the LLM-visible surface and the executor decision.

## 13. Security review checklist

- No `except` path returns all tools.
- No missing packet/policy defaults to write/network/delegation access.
- No prompt, memory, message, or tool result can mutate authorization context.
- No child Agent inherits more than the intersection of parent delegation grant and child ToolPolicy.
- No alias bypasses canonical Registry names.
- No stale decision survives a policy, Registry, environment, or turn change.
- No approval response can be replayed for another call.
- No log or API exposes secrets or raw arguments.

## 14. Rollback

Each enforcing milestone is guarded by an evaluator-version switch and retains the previous valid policy snapshot. Rollback means selecting the previous evaluator/policy snapshot while keeping authorization active. It never means bypassing policy or binding every registered tool.

## 15. Ownership and sequencing

This plan requires multiple serialized owners because shared hot files and public DTOs are involved:

1. Registry owner completes Milestone 1.
2. Authorization-core owner completes Milestone 2.
3. Runtime owner completes Milestones 3-5 in order.
4. Configuration backend and frontend owners complete Milestone 6 after contracts freeze.
5. Integration owner completes Milestone 7 and runtime validation.

Parallel work is safe only within a milestone when write sets are disjoint. `agent.py`, `core/web/services/session_service.py`, shared DTOs, and Agent Directory policy persistence are serialized merge surfaces.

## 16. Completion evidence

The program is complete only when:

- every Agent has a resolvable policy;
- every turn has one immutable decision fingerprint;
- model-visible and executable sets are traceable and consistent;
- assignment/removal works through configuration;
- hidden tools are absent and direct calls are rejected;
- all protocols and run kinds pass the same acceptance fixtures;
- legacy authority paths are removed rather than left as silent fallbacks.

