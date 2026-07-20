# Teams modules (`web/src/routes/teams` + Team* panels)

Agent-oriented map for Teams workbench development. Prefer editing a **module** over growing `TeamsRoute.tsx` when possible.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| Canvas / known team ids / org layout pure data | `../TeamsRoute.canvasData.ts` | JSX panels |
| Research workspace views / deep links / labels | `researchWorkspaceModel.ts` | mutations, canvas drag |
| Team kind guards / system-team roles | `teamKindModel.ts` | UI panels |
| Canvas geometry / auto-layout / edge paths | `canvasGeometry.ts` | styles maps, mutations |
| Source-collection evidence / filter pure math | `source-collection/evidenceModel.ts` | EventSource, mutations |
| Source-collection run selection / labels | `source-collection/runModel.ts` | UI panels |
| Stage projection / phase-close readiness | `source-collection/stageProjection.ts` | Graph SVG |
| Research workflow resource queries/keys | `useResearchWorkflowResources.ts` | Canvas drag |
| Research memory evidence UI | `ResearchMemoryEvidencePanel.tsx` | Teams shell mutations |
| Source-collection panel shell alias | `TeamsSourceCollectionPanel.tsx` | full route wiring |
| Workflow graph **layout math** | `../TeamWorkflowGraphLayout.ts` | Graph SVG view |
| Workflow graph **SVG view** | `../TeamWorkflowGraphView.tsx` (via secondary pack) | layout pure math |
| Workflow status panels (quality/paper_note/…) | `../TeamWorkflowStatusPanels.tsx` (via secondary pack) | route orchestration |
| Experiment method planner UI | `../TeamExperimentMethodPanel.tsx` (via secondary pack) | session SSE |
| Team memory index UI | `../TeamMemoryIndexPanel.tsx` (via secondary pack) | bus timeline |
| Source-collection UI panels (`TeamSourceCollection*`) | panel file under `routes/` (via secondary pack) | pure models |
| Secondary-lazy loader helper | `lazyTeamPanel.tsx` | business logic |
| Secondary UI pack barrel | `teamSecondaryPanels.ts` | pure models/hooks |
| Orchestration / wiring only | `../TeamsRoute.tsx` | — |

## Bundle note (secondary lazy)

`TeamsRoute` keeps UI panels off the initial Teams shell chunk via `createLazyNamedTeamPanel` + `teamSecondaryPanels.ts` (one shared async pack).

**Stay static in the shell (on purpose):**

- Pure models: `source-collection/*`, `TeamsRoute.canvasData`, `TeamWorkflowGraphLayout`
- Data hooks: `useResearchWorkflowResources`
- Styles map: `TeamsRoute.styles` (shared class strings)

**Do not** re-add static value imports of panel components into `TeamsRoute.tsx` without a budget re-check.

## Pure extract progress

- **Done:** workspace navigation, team kind guards, canvas geometry (with unit tests).
- **Still in `TeamsRoute.tsx`:** source-collection draft/status labels, experiment/loop types+drafts, AI-search presentation, workflow status labels, mutation wiring, JSX.

## Next (planned)

1. Extract source-collection presentation labels + experiment/loop pure types next (keep mutations in route until claimable hooks exist).
2. Prefer claimability wins over pure LOC grind.
3. Optional: split source-collection pack vs workflow-status pack if the secondary pack itself grows past route budget.

## Rules

1. Do not open a second Team EventSource for the same stream family.
2. Do not change React Query key shapes in drive-by refactors.
3. Keep pure builders free of React / DOM.
4. Font tokens: `[font-size:var(--vui-font-*)]`, never `text-[var(--vui-font-*)]` as size.
