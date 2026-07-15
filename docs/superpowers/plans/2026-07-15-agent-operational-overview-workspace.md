# Agent Operational Overview Workspace Plan

> Status: draft
>
> Owner: agent-codex-agent-operational-overview-plan
>
> Claim: claim-f4699bd2d437 (planning artifact only)
>
> Scope: Agent Center selected-Agent overview information architecture, existing activity/reference projections, and desktop layout validation
>
> Supersedes: the summary-only overview layout introduced before local main `7e0df9f9`; retains the fluid-width correction from `a46e7e86`
>
> Implementation link: pending
>
> Validation: plan review only; implementation verification is defined below
>
> Close condition: user approves this plan or replaces its information-architecture direction

## Goal

Turn the selected Agent overview from a short summary strip into an operational home that uses desktop space for current state, recent activity, related resources, and clear next actions without stretching buttons, inventing decorative charts, or duplicating the full Config and Activity panes.

## Decision

- Mode: `COMPACT_PLAN`; one frontend owner can implement the work serially.
- Reuse decision: `REFERENCE_ONLY`. Borrow the workbench information architecture seen in Dify, Langflow, Flowise, Open WebUI, and n8n; do not add or copy an external UI dependency.
- First implementation stays frontend-only. Reuse the existing Agent runs, pending messages, runtime evidence, references, query keys, navigation callbacks, and VUI primitives.
- Do not add a backend overview aggregation endpoint in the first pass. Add one only if browser/network evidence shows the three existing cached requests materially hurt selection latency.

## Product Contract

### Primary user task

After selecting an Agent, the operator must be able to answer, without changing tabs:

1. What is this Agent configured to do?
2. What is it doing or what did it do recently?
3. Is there a problem or pending action?
4. Which session, logs, tools, memory, rooms, or references should I open next?

### Desktop structure

```text
Agent identity, role, health and Overview / Config / Activity tabs
┌────────────────────────────────────────────┬──────────────────────┐
│ Primary facts: model, prompt, persona, task │ Management readiness │
│ Mode membership and current territory      │ Missing items/actions│
├────────────────────────────────────────────┼──────────────────────┤
│ Current runtime focus and next step         │ Related resources    │
│ Latest run/evidence and session/log actions │ prompt/tool/memory   │
├────────────────────────────────────────────┤ rooms/references      │
│ Recent activity preview (up to 5 items)     │                      │
│ run/message/context, timestamp, open action │                      │
├────────────────────────────────────────────┴──────────────────────┤
│ Runtime/delegation summary and collapsed technical information   │
└───────────────────────────────────────────────────────────────────┘
```

At `2048x1106`, the operations and activity sections must be visible in the first viewport. At `1440x900`, the main/aside split remains usable and cards use two columns. Preserve the existing single-column fallback below the desktop breakpoint, but do not introduce new mobile-specific product work.

### State behavior

- `loading`: reserve stable rows for runtime focus and activity; do not hide the entire overview or cause a large layout jump.
- `empty`: show `尚无运行记录` plus one sentence and content-sized `打开会话` / `检查配置` actions. Empty state is a task launcher, not a blank panel.
- `error`: keep identity/config summary visible and show a bounded activity error with retry/open-activity action.
- `ready`: show at most five activity items, newest first. Full history and inbox mutation actions remain in Activity.
- `running`: show the active state, latest phase/summary, updated time, session/log actions, and a non-color status label.
- `pending messages`: show count and preview only; consuming messages stays in Activity to avoid accidental actions from Overview.

## Data And Query Contract

Current sources remain authoritative:

- `/api/agents/{agentId}/runs?limit=12`
- `/api/agents/{agentId}/messages?status=pending&limit=8`
- `/api/agents/{agentId}/runtime-evidence?...&limit=5`
- existing selected Agent projection, `activityTimeline`, `runtimeFocusEvidence`, and `selectedAgentReferencesPanel`

Query behavior changes:

- Enable the existing three activity queries when `activePane` is `overview` or `activity`.
- On Overview, fetch once per normal TanStack Query freshness lifecycle and do not poll.
- On Activity, retain current 12-second runs/messages and 20-second evidence polling.
- Keep the same query keys so opening Activity reuses Overview data instead of issuing a parallel cache family.
- Slice only at the overview presentation boundary; preserve complete data for Activity.

No backend route, DTO, persistence, lifecycle, or destructive behavior changes are planned.

## Component Plan

### Existing files to modify

- `web/src/routes/AgentsRoute.tsx`
  - extend activity-query enablement to Overview;
  - disable polling outside Activity;
  - derive compact runtime, activity and related-resource view data;
  - keep message-consume mutations owned by Activity.
- `web/src/routes/AgentSelectedDetailContentPanel.tsx`
  - place the operational workspace in the overview main column;
  - add the related-resource preview below the management brief in the aside.
- `web/src/routes/AgentSelectedDetailContentPanel.styles.ts`
  - preserve the fluid `4fr / 1fr` desktop split;
  - let the main column grow naturally from useful content, not `min-height:100%` filler.
- `web/src/routes/AgentOverviewPanel.tsx`
  - keep identity facts and mode membership first;
  - keep runtime/delegation summary and technical disclosure after operational content.
- `web/src/routes/AgentOverviewPanel.styles.ts`
  - define the main operational grid and stable loading/empty-state geometry using current VUI tokens.
- `web/src/routes/AgentsRoute.layout.test.ts`
  - lock query gating, component ownership, fluid layout, content-sized actions, and empty-state presence.
- `web/src/routes/AgentOverviewPanel.test.tsx`
  - preserve technical disclosure and verify operational ordering.

### New focused components

- `web/src/routes/AgentOverviewOperationsPanel.tsx`
- `web/src/routes/AgentOverviewOperationsPanel.styles.ts`
- `web/src/routes/AgentOverviewOperationsPanel.test.tsx`
  - current runtime focus;
  - recent activity preview;
  - loading, empty, error and ready states;
  - navigation-only actions.
- `web/src/routes/AgentOverviewResourcesPanel.tsx`
- `web/src/routes/AgentOverviewResourcesPanel.styles.ts`
- `web/src/routes/AgentOverviewResourcesPanel.test.tsx`
  - prompt/tool/memory summary;
  - room/reference counts and up to four direct links;
  - route to Config for full editing.

Do not reuse the full `AgentActivityHistoryPanel` or `AgentReferencesPanel` markup in Overview: both contain deep-management controls and lists intended for their dedicated panes. Reuse their source projections and callbacks instead.

## Implementation Sequence

1. Add failing component/layout tests for operational ordering, explicit empty/error states, content-sized actions, and Overview query gating.
2. Add `AgentOverviewOperationsPanel` and `AgentOverviewResourcesPanel` with static fixture props; make their focused tests pass.
3. Wire existing `activityTimeline`, runtime focus, references and navigation callbacks through `AgentSelectedDetailContentPanel`.
4. Change query gating so Overview loads once and Activity owns polling; verify cache keys remain unchanged.
5. Reorder the overview so technical details remain last and collapsed.
6. Run focused tests, TypeScript/build, then Launcher browser verification at both desktop target sizes.

## Protection Boundaries

- Do not change Agent lifecycle, Team/ChatRoom membership ownership, session binding, message consumption, runtime evidence generation, or config save semantics.
- Do not add charts without a real metric source.
- Do not enlarge short buttons or make whole cards clickable unless the entire row is intentionally a navigation target.
- Do not duplicate Config forms in Overview.
- Do not copy Flowise/Langflow canvases; Vibelution is not adding graph editing in this round.
- Preserve unrelated concurrent Agent Center work and re-run claim checks immediately before implementation.

## Verification Contract

### Automated

```powershell
npm --prefix web run test -- AgentOverviewOperationsPanel.test.tsx AgentOverviewResourcesPanel.test.tsx AgentOverviewPanel.test.tsx AgentsRoute.layout.test.ts
npm --prefix web run build
git diff --check
```

The implementation owner must also run the project local quality closeout selected by `local_quality_gate.py`, because `AgentsRoute.tsx` is a hot, shared frontend surface.

### Browser

Use the native Launcher refresh path and verify `/agents` with:

- `2048x1106`: selected Agent with activity; current focus, recent activity and resource panel appear before the first viewport ends; no horizontal overflow.
- `2048x1106`: Agent without runs/messages; explicit task-oriented empty state appears instead of an uninterrupted blank region.
- `1440x900`: main/aside split remains readable, actions hug content, long Chinese/English labels wrap without overlap.
- switch Overview -> Activity -> Overview: cache is reused, Activity polling starts only while active, and no stale/error flash replaces existing summary data.
- console: no React warnings, request loop, layout overflow, or failed navigation.

### Success criteria

- The Overview is useful even when configuration is complete and the Agent is idle.
- Empty space is reduced by real operational content, not decorative filler or stretched cards.
- Overview exposes the latest state and next action; Activity remains the deep operational history/editor.
- No new dependency, backend contract, or persistent state is introduced.

## Deferred Decisions

- Add a single backend `overview-activity` aggregation endpoint only if measured request latency or server load justifies it.
- Add charts only after a stable time-series metric contract exists.
- Add graph/canvas editing only as a separate Agent orchestration feature, not as layout filler.
