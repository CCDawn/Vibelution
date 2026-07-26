# Agents modules (`web/src/routes/agents` + Agent* panels)

Agent-oriented map for the Agent management workbench. Prefer editing a
**panel / pure module** over growing `AgentsRoute.tsx` when possible.

`AgentsRoute.tsx` remains the **shell**: selection state, query wiring, mutations,
and panel composition. Pure query/presentation helpers should leave the shell.

## 30-second routing

| You are changing… | Open first |
|-------------------|------------|
| Summary/full workspace query selection & error ownership | `agentWorkspaceQuery.ts` |
| Display name / tone / noisy label cleanup | `../agentDisplay.ts` |
| Center deep-links (memory/models/tools/prompts) | `../agentCenterRoutes.ts` |
| Workspace cache patch helpers after bulk ops | `../agentWorkspaceCache.ts` |
| Create wizard | `../agent-create/*` |
| List / detail / overview / tool / memory panels | matching `../Agent*Panel.tsx` |
| Shell styles map | `../AgentsRoute.styles.ts` |
| Route orchestration only | `../AgentsRoute.tsx` |

## Ownership map (claim scopes)

| Task type | Prefer | Avoid |
|-----------|--------|--------|
| Workspace query pure math | `agentWorkspaceQuery.ts` | JSX panels |
| Health / runtime / mode status labels | `agentStatusPresentation.ts` | mutations |
| Agent label / avatar tone pure | `../agentDisplay.ts` | mutations |
| Bulk archive/purge cache math | `../agentWorkspaceCache.ts` | EventSource |
| Overview / config / activity panes | panel file | Route-only inlines |
| Shell selection + mutations | `../AgentsRoute.tsx` | re-adding pure tables |

## Pure extract progress

- **Done (earlier):** many `Agent*Panel` UI slices, `agentDisplay`, `agentCenterRoutes`, `agentWorkspaceCache`, create wizard pack.
- **Done (ROI D1 start):** `agentWorkspaceQuery.ts` — workspace query pure helpers.
- **Done (ROI D1 cont):** `agentStatusPresentation.ts` — health/runtime/mode labels and next-step copy.
- **Still in `AgentsRoute.tsx`:** draft mappers, tool/memory policy drafts, list/filter builders, shell JSX.

## Perf program F3 (Agents ROI)

| Wave | Goal | Status |
|---|---|---|
| F3-A mutation hooks | Move EventSource-free writes out of shell | **Blocked pending draft/state DI design** — archive/purge/config drafts close over many route setters (`setConfigDraft`, `draftSyncSourceRef`, pane selection). Naive extract failed tsc; next attempt should extract **one cluster at a time** with explicit options (notice + draft setters + pure mappers co-located first). |
| F3-B pane lazy packs | overview default light; config/activity/relations async | Pending after F3-A or independent if panels already split files |
| F3-C query gates | tighten fullWorkspaceNeeded vs pack | Pending |

**Recommended F3-A order:** (1) promote pure mappers to `agents/*Model.ts`, (2) `useAgentConfigDraftMutations` only (save/discard/update/promote), (3) lifecycle, (4) policy/inbox.

## Next (planned, by ROI)

1. F3-A: pure mappers then config-draft mutation cluster (see above).
2. Extract list/filter pure builders (`filterAgents`, management brief) with unit tests.
3. Do not re-inline pure helpers into the shell for convenience.
4. Pane-scoped lazy packs when mutation boundary is clean.

## Rules

1. Keep pure modules free of React Query / DOM.
2. Re-export shell-facing pure APIs from `AgentsRoute.tsx` only when layout tests or external imports require the historical path.
3. Do not change React Query key shapes in drive-by structure work.
