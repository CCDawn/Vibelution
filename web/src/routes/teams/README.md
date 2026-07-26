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
| Source-collection presentation labels / storage paths / tones | `source-collection/presentationModel.ts` | mutations, SSE |
| Source-collection run selection / labels | `source-collection/runModel.ts` | UI panels |
| Stage projection / phase-close readiness | `source-collection/stageProjection.ts` | Graph SVG |
| Experiment + Research Loop types / query keys / status labels | `experimentLoopModel.ts` | mutations, UI panels |
| AI Search presentation labels / run summary copy | `aiSearchPresentation.ts` | mutations, UI panels |
| Workflow status labels / linked-room refetch | `workflowPresentation.ts` | mutations, UI panels |
| Research stage agent role tables | `researchStageRoles.ts` | mutations, UI panels |
| SC / workflow React Query keys | `teamWorkflowQueryKeys.ts` | mutations, UI panels |
| Stage agent binding presentation / routes | `researchStageAgentPresentation.ts` | mutations, UI panels |
| First-paint detail/canvas/SC query gating | `teamDetailLoadPolicy.ts` | mutations, UI panels |
| Research workflow resource queries/keys | `useResearchWorkflowResources.ts` | Canvas drag |
| Research memory evidence UI | `ResearchMemoryEvidencePanel.tsx` | Teams shell mutations |
| AI Search workspace UI | `../TeamAiSearchWorkspacePanel.tsx` (via secondary pack) | start mutation wiring |
| Research stage agent summary/grid UI | `../TeamResearchStageAgentPanel.tsx` (via secondary pack) | binding projection |
| Research stage launcher console | `../TeamResearchStageLauncherPanel.tsx` (via secondary pack) | query/mutation injection |
| Research stage standalone page (experiment/iteration) | `../TeamResearchStageStandalonePagePanel.tsx` (via secondary pack) | ledger/loop render props + launch mutations |
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
- Styles maps: `TeamsRoute.styles` + thematic clusters (`research` / `aiSearch` / `experiment` / `workflow`)

**Do not** re-add static value imports of panel components into `TeamsRoute.tsx` without a budget re-check.

## Pure extract progress

- **Done:** workspace navigation, team kind guards, canvas geometry, source-collection presentation, experiment/loop types+labels, AI-search presentation, workflow presentation labels, research stage agent role tables, workflow query keys, stage-agent presentation/routes.
- **Still in `TeamsRoute.tsx`:** mutation wiring, JSX shell, style-bound tone helpers, large panel orchestration.
- **Wave 8G done:** AI Search workspace + research stage agent summary/panel extracted to secondary-lazy components.
- **Wave 8H done:** Research stage launcher (three-stage + Challenge Cup MVP console) extracted to `TeamResearchStageLauncherPanel`.
- **Wave 8I done:** Experiment/iteration standalone stage page extracted to `TeamResearchStageStandalonePagePanel` (ledger/loop panels remain route-owned injectables).

## Next (planned)

1. Extract research loop panel / experiment planning ledger / remaining source-collection orchestration when each can own a full boundary.
2. Extract EventSource-free mutation hooks (`useTeamWorkflowMutations` family) only when a hook can own a full boundary.
3. Optional: split `teamSecondaryPanels` into source-collection vs workflow-status packs if the secondary pack exceeds route budget.
4. Optional: style-bound tone helpers (`workflowQualityTone`) once styles map ownership is clear.

## Rules

1. Do not open a second Team EventSource for the same stream family.
2. Do not change React Query key shapes in drive-by refactors.
3. Keep pure builders free of React / DOM.
4. Font tokens: `[font-size:var(--vui-font-*)]`, never `text-[var(--vui-font-*)]` as size.
