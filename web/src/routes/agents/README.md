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
| Bulk config / archive / center-return helpers | `agentRouteBulkModel.ts` |
| Agents workbench bilingual copy / pane badges | `agentsRouteCopy.ts` → `../../i18n/domains/agentsWorkbenchCopy.ts` |
| Shared nav/compression dictionary pack | `../../i18n/domains/dictionaryAgents.ts` |
| Soft-prefetch workbench copy | `../../i18n/loadAgentsWorkbenchCopy.ts` |
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
| Bulk config / metadata / archive pure helpers | `agentRouteBulkModel.ts` | shell JSX |
| Workbench copy tables / pane badge labels | `agentsRouteCopy.ts` | shell JSX, dictionary core |
| Shared nav/compression i18n keys | `dictionaryAgents` domain | workbench copy tables |
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
- **Done (M7 structure):** `agentRouteBulkModel` — bulk config draft/patch/ready, metadata archive guards, center return labels; draft-equals moved into `agentRouteDraftModel`.
- **Done (C1 structure):** `agentsRouteCopy` — ~800-line zh/en workbench copy + `agentConfigPanes` badges out of shell.
- **Done (C1.1 dictionary charter):** nested workbench tables live under `i18n/domains/agentsWorkbenchCopy.ts`; facade + soft-prefetch loader; flat `dictionaryAgents` stays shared nav/compression only.
- **Done (A8):** `planAgentResetDirectSession` pure plan in `agentRouteBulkModel`; shell only applies store side effects.
- **Still in shell:** large JSX composition, store-side session reconcile apply.
- **Done (C1.2 dictionary phase-2):** high-frequency workbench keys in flat `dictionaryAgents` + dual-read merge.
- **Done (C1.3):** mid-frequency bulk/filter/management keys dual-read expanded.
- **Done (C1.4):** groupLabels / groupDescriptions / management-filter titles dual-read; nested table still owns long confirms and long hints.
- **Deferred (charter later):** more dual-read only when a concrete claim needs it; do not swallow full nested table.

## Dictionary charter (Agents workbench)

| Layer | Owner | Notes |
|-------|-------|-------|
| Flat shared + high-freq keys | `dictionaryAgents` | nav/compression + C1.2 workbench dual-read keys |
| Nested workbench tables | `agentsWorkbenchCopy` | full bulk/filter/setup/policy surface |
| Dual-read merge | `mergeAgentsWorkbenchCopy.ts` | `mergeAgentsRouteCopyWithDictionary(base, t)` |
| Route façade | `routes/agents/agentsRouteCopy.ts` | stable import path for shell/tests |
| Soft warm | `loadAgentsWorkbenchCopy` + AppShell agents `onPointerEnter` | module cache only |

## Structure program (maintainability-first)

| Wave | Goal | Status |
|------|------|--------|
| M1 | Draft/mapper pure extract | **Done** — `agentRouteDraftModel.ts` |
| M2 | Management brief + setup filter predicates | **Done** — `agentRouteManagementModel.ts` |
| M3 | Tool/memory/membership draft mappers | **Done** — `agentRoutePolicyDraftModel.ts` |
| M4–M6 | Evolution / Teams / Conversation maps | See `evolution/README.md`, `teams/README.md`, `components/conversation/README.md` |
| M7 | Bulk config / metadata / archive pure extract | **Done** — `agentRouteBulkModel.ts` |
| C1 | Workbench copy table externalize | **Done** — `agentsRouteCopy.ts` |
| C1.1 | Domain-shaped workbench copy + soft prefetch | **Done** — `i18n/domains/agentsWorkbenchCopy.ts` |
| C1.2 | High-freq workbench keys + dual-read | **Done** — `dictionaryAgents` + `mergeAgentsWorkbenchCopy` |
| C1.3 | Mid-freq bulk/filter/management dual-read | **Done** — expanded merge overlay |
| C1.4 | groupLabels / groupDescriptions dual-read | **Done** — expanded merge overlay |
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
