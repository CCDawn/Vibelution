# Evolution modules (`web/src/routes/evolution` + Evolution* panels)

Agent-oriented map for Evolution workbench development. Prefer editing a
**module / panel** over growing `EvolutionRoute.tsx` when possible.

`EvolutionRoute.tsx` remains the **shell**: track/view selection, query wiring,
mutations, pane layout, and panel composition. Pure labels, draft mappers, and
route builders should live outside the shell.

## 30-second routing (Agent reading map)

| You are changing… | Open first |
|-------------------|------------|
| Supervised labels / drafts / route builders / workflow step math | `evolutionRouteModel.ts` |
| Live run stream target / snapshot selection | `../evolutionLiveRun.ts` |
| Workspace cache patch helpers | `../evolutionWorkspaceCache.ts` |
| Run / worktree start-control mutations | `useEvolutionRunMutations.ts` |
| Supervised approval comparison / governance actions | `../SupervisedApprovalDecisionPanel.tsx` + `../supervisedApprovalDecision.ts` |
| Proposal edit/delete/bulk mutations | `useEvolutionProposalMutations.ts` |
| Active run monitor UI | `../EvolutionActiveRunMonitorPanel.tsx` |
| Run records list UI | `../EvolutionRunRecordsPanel.tsx` |
| Proposal action bands UI | `../EvolutionProposalActionBandsPanel.tsx` |
| Self-evolution track boundary | `../EvolutionSelfTrackBoundary.tsx` |
| Shell orchestration only | `../EvolutionRoute.tsx` |

## Ownership map

| Task type | Prefer | Avoid |
|-----------|--------|--------|
| Supervised pure presentation / drafts | `evolutionRouteModel.ts` | shell JSX |
| Live stream selection pure math | `../evolutionLiveRun.ts` | panels |
| Write mutations | `useEvolution*Mutations.ts` | pure files |
| Supervised approval state model / decision UI | `../supervisedApprovalDecision.ts` + `../SupervisedApprovalDecisionPanel.tsx` | shell JSX |
| Live / runs / library panel UI | matching `../Evolution*Panel.tsx` | Route-only inlines |
| Shell selection + composition | `../EvolutionRoute.tsx` | re-adding pure tables |

## Pure extract progress

- **Done:** lazy panel packs (ActiveRun / RunRecords / ProposalActionBands).
- **Done:** `useEvolutionRunMutations`, `useEvolutionProposalMutations`.
- **Done (M4 structure):** `evolutionRouteModel` — supervised workflow/member routes, dataset labels, proposal draft mappers, governance wording helpers.
- **Still in shell:** large JSX composition, pane layout wiring, query/mutation orchestration, copy tables via i18n.

## Structure program

| Wave | Goal | Status |
|------|------|--------|
| M4 | Evolution pure split + README map | **Done** — `evolutionRouteModel.ts` |
| Shell rule | Route only orchestrates | ongoing |

## Rules

1. Keep pure modules free of React Query / DOM.
2. Prefer small named pure files over growing the shell “for convenience”.
3. Do not change React Query key shapes in drive-by structure work.
4. Secondary view panels stay lazy; do not static-import their full graphs into the shell without a budget check.
