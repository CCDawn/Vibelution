# Agents modules (`web/src/routes/agents` + Agent* panels)

Agent-oriented map for the Agent management workbench. Prefer editing a
**panel / pure module** over growing `AgentsRoute.tsx` when possible.

`AgentsRoute.tsx` remains the **shell**: selection state, query wiring, mutations,
and panel composition. Pure query/presentation/draft helpers should leave the shell.

## 30-second routing (Agent reading map)

| You are changing… | Open first |
|-------------------|------------|
| Summary/full workspace query selection & error ownership | `agentWorkspaceQuery.ts` |
| Health / runtime / mode status labels | `agentStatusPresentation.ts` |
| List labels, model choice presentation | `agentRouteListModel.ts` |
| LLM bindings / reasoning effort math | `agentRouteLlmModel.ts` |
| Lightweight workspace, filterAgents, references | `agentRouteWorkspaceModel.ts` |
| Config/persona/task/context-compression drafts | `agentRouteDraftModel.ts` |
| Tool/memory/membership/runtime policy drafts | `agentRoutePolicyDraftModel.ts` |
| Management brief / setup filters / list columns | `agentRouteManagementModel.ts` |
| Config draft mutations | `useAgentConfigDraftMutations.ts` |
| Workbench profile/lifecycle/policy mutations | `useAgentWorkbenchMutations.ts` |
| Display name / tone | `../agentDisplay.ts` |
| Center deep-links | `../agentCenterRoutes.ts` |
| Workspace cache patch helpers | `../agentWorkspaceCache.ts` |
| Create wizard | `../agent-create/*` |
| List / detail / overview / tool / memory panels | matching `../Agent*Panel.tsx` |
| Route orchestration only | `../AgentsRoute.tsx` |

## Ownership map

| Task type | Prefer | Avoid |
|-----------|--------|--------|
| Workspace query pure math | `agentWorkspaceQuery.ts` | JSX panels |
| Health / runtime / mode status labels | `agentStatusPresentation.ts` | mutations |
| List/search/model presentation | `agentRouteListModel.ts` | shell JSX |
| LLM binding / reasoning | `agentRouteLlmModel.ts` | panels |
| Lightweight list projection / filters | `agentRouteWorkspaceModel.ts` | mutations |
| Draft mappers (config/persona/task/compression) | `agentRouteDraftModel.ts` | EventSource |
| Policy drafts (tool/memory/membership/delegation/supervision) | `agentRoutePolicyDraftModel.ts` | EventSource |
| Management brief / setup filters / columns | `agentRouteManagementModel.ts` | shell JSX |
| Write mutations | `useAgent*Mutations.ts` | pure files |
| Overview / config / activity panes | panel file | Route-only inlines |
| Shell selection + composition | `../AgentsRoute.tsx` | re-adding pure tables |

## Pure extract progress

- **Done:** `Agent*Panel` UI slices, `agentDisplay`, `agentCenterRoutes`, `agentWorkspaceCache`, create wizard.
- **Done:** `agentWorkspaceQuery.ts`, `agentStatusPresentation.ts`.
- **Done (D3):** `agentRouteListModel`, `agentRouteLlmModel`, `agentRouteWorkspaceModel`.
- **Done (M1 structure):** `agentRouteDraftModel` — config/persona/task/context-compression mappers + `sortedIds`.
- **Done (M2 structure):** `agentRouteManagementModel` — management brief, setup filters, list columns, group labels.
- **Done (M3 structure):** `agentRoutePolicyDraftModel` — tool/memory/membership/delegation/supervision drafts + capability preview.
- **Still in shell:** bulk config helpers, large JSX composition, copy tables.

## Structure program (maintainability-first)

| Wave | Goal | Status |
|------|------|--------|
| M1 | Draft/mapper pure extract | **Done** — `agentRouteDraftModel.ts` |
| M2 | Management brief + setup filter predicates | **Done** — `agentRouteManagementModel.ts` |
| M3 | Tool/memory/membership draft mappers | **Done** — `agentRoutePolicyDraftModel.ts` |
| M4–M6 | Evolution / Teams / Conversation maps | See `evolution/README.md`, `teams/README.md`, `components/conversation/README.md` |
| Shell rule | Route only orchestrates | ongoing |

## Perf notes (secondary)

| Wave | Goal | Status |
|---|---|---|
| F3-A mutation hooks | EventSource-free writes out of shell | **Done** |
| F3-B pane lazy | secondary panes React.lazy | **Done** |
| F3-C query gates | activity poll gated | **Already** |

## Rules

1. Keep pure modules free of React Query / DOM.
2. Re-export shell-facing pure APIs from `AgentsRoute.tsx` only when layout tests or external imports require the historical path.
3. Do not change React Query key shapes in drive-by structure work.
4. Prefer small named pure files over growing the shell “for convenience”.
