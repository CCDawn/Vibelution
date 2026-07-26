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
| Research loop (template / evidence / decision) | `../TeamResearchLoopPanel.tsx` (via secondary pack) | create/record mutations + drafts |
| Experiment planning ledger | `../TeamExperimentPlanningLedgerPanel.tsx` (via secondary pack) | plan/baseline/smoke/full-run mutations + loop render prop |
| Knowledge-collection completion flow graph | `../TeamKnowledgeCollectionCompletionFlowPanel.tsx` (via secondary pack) | stage chat + retry injectables |
| SC conversation / raw-records workspace | `../TeamSourceCollectionConversationWorkspacePanel.tsx` (via secondary pack) | filter/pagination injectables |
| SC screening / review workspace | `../TeamSourceCollectionScreeningWorkspacePanel.tsx` (via secondary pack) | quality/chunk mutations injectables |
| SC extraction recovery workspace | `../TeamSourceCollectionExtractionRecoveryWorkspacePanel.tsx` (via secondary pack) | stage session + screening injectables |
| SC candidate workspace | `../TeamSourceCollectionCandidateWorkspacePanel.tsx` (via secondary pack) | recovery render prop + selection |
| SC graph workspace | `../TeamSourceCollectionGraphWorkspacePanel.tsx` (via secondary pack) | graph query + candidate map injectables |
| SC memory / ingestion workspace | `../TeamSourceCollectionMemoryWorkspacePanel.tsx` (via secondary pack) | knowledge-ingestion status injectables |
| SC selected-source detail workspace | `../TeamSourceCollectionSelectedSourceWorkspacePanel.tsx` (via secondary pack) | storage-open injectables |
| SC controls / side-rail workspace | `../TeamSourceCollectionControlsWorkspacePanel.tsx` (via secondary pack) | run start + writeback + stage agents injectables |
| SC active-stage workspace | `../TeamSourceCollectionActiveStageWorkspacePanel.tsx` (via secondary pack) | stage chat + panel render props |
| Source-collection panel shell alias | `TeamsSourceCollectionPanel.tsx` | full route wiring |
| Workflow graph **layout math** | `../TeamWorkflowGraphLayout.ts` | Graph SVG view |
| Workflow graph **SVG view** | `../TeamWorkflowGraphView.tsx` (via secondary pack) | layout pure math |
| Workflow status panels (quality/paper_note/…) | `../TeamWorkflowStatusPanels.tsx` (via secondary pack) | route orchestration |
| Experiment method planner UI | `../TeamExperimentMethodPanel.tsx` (via secondary pack) | session SSE |
| Team memory index UI | `../TeamMemoryIndexPanel.tsx` (via secondary pack) | bus timeline |
| Source-collection UI panels (`TeamSourceCollection*`) | panel file under `routes/` (via secondary pack) | pure models |
| Secondary-lazy loader helper | `lazyTeamPanel.tsx` | business logic |
| Shared UI pack barrel | `teamSharedPanels.ts` | path-specific orchestration |
| Research UI pack barrel | `teamResearchPanels.ts` | SC orchestration |
| Source-collection UI pack barrel | `teamSourceCollectionPanels.ts` | research orchestration |
| Orchestration / wiring only | `../TeamsRoute.tsx` | — |

## Bundle note (path-scoped secondary packs)

`TeamsRoute` keeps UI panels off the initial shell via `createLazyNamedTeamPanel` and **three** async barrels:

| Pack | Loader | Contains |
|---|---|---|
| Shared | `loadTeamSharedPanels` | Graph view, research memory evidence |
| Research | `loadTeamResearchPanels` | AI search, research stages, loop/ledger, workflow status |
| Source-collection | `loadTeamSourceCollectionPanels` | SC chrome + workspace orchestration |

**Rules:**

- New panels must enter exactly one pack; do **not** revive a mono `teamSecondaryPanels` UI barrel.
- Same-pack static imports are fine; cross-pack **value** imports of workspaces are forbidden.
- Stay static in the shell (on purpose): pure models, query keys/hooks, style maps.
- Prefetch is path-scoped via `teamPanelPrefetch.ts`: warm research or SC after team/view switch; **never** prefetch all packs on shell mount.

**Do not** re-add static value imports of panel components into `TeamsRoute.tsx` without a budget re-check.

## Pure extract progress

- **Done:** workspace navigation, team kind guards, canvas geometry, source-collection presentation, experiment/loop types+labels, AI-search presentation, workflow presentation labels, research stage agent role tables, workflow query keys, stage-agent presentation/routes.
- **Still in `TeamsRoute.tsx`:** mutation wiring, JSX shell, style-bound tone helpers, large panel orchestration.
- **Wave 8G done:** AI Search workspace + research stage agent summary/panel extracted to secondary-lazy components.
- **Wave 8H done:** Research stage launcher (three-stage + Challenge Cup MVP console) extracted to `TeamResearchStageLauncherPanel`.
- **Wave 8I done:** Experiment/iteration standalone stage page extracted to `TeamResearchStageStandalonePagePanel` (ledger/loop panels remain route-owned injectables).
- **Wave 8J done:** Research loop + experiment planning ledger extracted to `TeamResearchLoopPanel` / `TeamExperimentPlanningLedgerPanel` (mutations stay route-owned injectables).
- **Wave 8K done:** Knowledge completion flow + SC conversation/screening workspaces extracted (chrome shells kept; orchestration moved off route).
- **Wave 8L done:** SC recovery / candidate / graph / memory workspaces extracted (controls/active-stage still route-owned).
- **Wave 8M done:** SC selected-source / controls / active-stage workspaces extracted (small helpers like filterBar/pagination/modeFields remain route-local).
- **Wave 8N done:** Split mono secondary barrel into path-scoped packs: `teamSharedPanels` / `teamResearchPanels` / `teamSourceCollectionPanels`.
- **Wave 8N+prefetch done:** Path-scoped pack warm-up after team/view switch (`teamPanelPrefetch.ts`).

## Next (planned)

1. Extract EventSource-free mutation hooks (`useTeamWorkflowMutations` family) only when a hook can own a full boundary.
2. Optional: extract remaining small SC helpers only if they block further shell shrink.
3. Optional: style-bound tone helpers (`workflowQualityTone`) once styles map ownership is clear.
4. Optional: collapse SC chrome+workspace double layer when inject surface stabilizes.

## Rules

1. Do not open a second Team EventSource for the same stream family.
2. Do not change React Query key shapes in drive-by refactors.
3. Keep pure builders free of React / DOM.
4. Font tokens: `[font-size:var(--vui-font-*)]`, never `text-[var(--vui-font-*)]` as size.
