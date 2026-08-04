# Teams modules (`web/src/routes/teams` + Team* panels)

Agent-oriented map for Teams workbench development. Prefer editing a **module** over growing `TeamsRoute.tsx` when possible.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| Canvas / known team ids / org layout pure data | `../TeamsRoute.canvasData.ts` | JSX panels |
| Research workspace views / deep links / labels | `researchWorkspaceModel.ts` | mutations, canvas drag |
| Overview primary CTA + stage handoff pure model | `researchPrimaryActionModel.ts` | TeamsRoute orchestration only |
| Overview surface composition (CTA → stages → advanced) | `ResearchOverviewSurface.tsx` | burying CTA under stage console |
| Overview primary CTA UI | `ResearchPrimaryActionBar.tsx` | mutations ownership |
| Overview advanced disclosure shell | `ResearchOverviewSecondary.tsx` | evidence/path dumps in hero |
| Design acceptance preview (static) | `web/research-overview-preview-standalone.html` + `design/research-overview-preview.*` | production routes |
| Teams shell (left team list + board/canvas mode) | `teamShellModel.ts` + `TeamShellRail.tsx` + `TeamShellModeSwitch.tsx` + `TeamShellToolbar.tsx` + VUI `VBoardWorkbenchPage` / `VCanvasWorkbenchPage` | burying team pick in dense header only |
| Organization canvas surface | `TeamOrganizationCanvasSurface.tsx` | inlining graph/drag chrome in TeamsRoute |
| Canvas node binding inspector | `TeamNodeBindingPanel.tsx` | duplicating bind form in board/canvas |
| Read-only canvas inspector | `TeamCanvasReadOnlyInspector.tsx` | ad-hoc read-only blocks in route |
| Team discussion + broadcast | `TeamCommunicationPanel.tsx` | duplicating task/broadcast JSX in board/canvas shells |
| Research workflow stage host | `TeamResearchWorkflowPanelHost.tsx` + `renderResearchWorkflowModules` in `TeamsRoute` | inlining workflow section chrome / stage modules twice in board+canvas |
| Board primary overview/launcher | `TeamResearchBoardPrimarySurface.tsx` | board fill loading/empty/ready + launcher branch buried in route return |
| Shared inspector tail | `renderTeamsInspectorSharedPanels` in `TeamsRoute` | duplicating bind/AI-search/workflow/communication stack on board+canvas |
| Stage launcher prop bags | `researchStageLauncherProps.ts` + `TeamResearchStageLauncherPanel` | flat 60-key injection spray from TeamsRoute |
| Research workflow stage modules | `TeamResearchWorkflowStageModules.tsx` | SC/coordination/ingestion/graph/candidates JSX inlined in TeamsRoute |
| SC storage open inject | `TeamSourceCollectionStorageActionsInject.tsx` | storage action target list + labels in route |
| SC search brief + project reset shell | `TeamSourceCollectionSearchBriefShell.tsx` | reset surface + search brief start form in route |
| SC run switcher inject | `TeamSourceCollectionRunSwitcherInject.tsx` + runModel hint/options | empty-run hint + option mapping in route |
| SC screening inject | `TeamSourceCollectionScreeningInject.tsx` + injectModel recommended-next | screening next-step copy in route |
| SC graph / memory / selected / conversation injects | `TeamSourceCollection*Inject.tsx` | route mounting workspace panels directly |
| SC active-stage extraction recovery bag | `source-collection/extractionRecoveryBag.ts` + ActiveStageInject normalize | inline extractionRecovery object in TeamsRoute |
| SC filter / pagination / stage agents | `TeamSourceCollectionFilterBarInject` / `PaginationInject` / `StageAgentsInject` + stageAgentsPresentation | list chrome + agent cards inlined in route |
| SC controls metrics/feedback bags | `source-collection/controlsFeedbackBag.ts` | untyped controls prop groups |
| Workspace panel render factory | `teamsWorkspacePanelRenderers.tsx` | memory/AI-search/completion/loop/ledger/canvas inspector render* in TeamsRoute |
| SC workspace state machine | `useSourceCollectionWorkspace.ts` | SC useState + project/run list + selection + detail queries in TeamsRoute |
| SC presentation + action adapters | `useSourceCollectionPresentation.ts` | SC summary/counts/readiness/display + mutation surfaces + run actions in TeamsRoute |
| Experiment + research-loop workspace state | `useResearchExperimentWorkspace.ts` | experiment/loop drafts + secondary status queries in TeamsRoute |
| Shell + canvas state machine | `useTeamsShellCanvasWorkspace.ts` (`useTeamsShellCanvasWorkspace` + `useTeamsCanvasProjection`) | shell/canvas useState, team pick sync, canvas query + display projection in TeamsRoute |
| Team-scoped mutation surface (pending/error/result) | `teamMutationSurface.ts` | repeating `variables?.teamId === selectedTeam` ternaries in TeamsRoute |
| SC write mutation surface + quality feedback | `teamMutationSurface.ts` (`buildSourceCollectionWriteMutationSurface`) | graph/quality/knowledge write flags in TeamsRoute |
| SC action chrome (loading copy / readiness helpers) | `source-collection/actionChrome.ts` | inline i18n readiness helpers in TeamsRoute |
| Workflow API error product copy | `researchWorkflowErrorModel.ts` + `ResearchWorkflowErrorSurface.tsx` | raw Error.message in UI |
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
| Lazy pack loaders + panel facades | `teamLazyPanels.tsx` | route orchestration |
| Experiment/research-loop workspace action adapters | `experimentWorkspaceActions.ts` | mutation hooks / draft ownership |
| Shared UI pack barrel | `teamSharedPanels.ts` | path-specific orchestration |
| Research core UI pack barrel | `teamResearchPanels.ts` | experiment / AI-search packs |
| Research experiment UI pack barrel | `teamResearchExperimentPanels.ts` | core / SC packs |
| Research AI-search UI pack barrel | `teamResearchSearchPanels.ts` | core / experiment packs |
| Source-collection UI pack barrel | `teamSourceCollectionPanels.ts` | research orchestration |
| Experiment + research-loop mutations | `useTeamExperimentLoopMutations.ts` | drafts/view orchestration |
| Source-collection write mutations | `useTeamSourceCollectionMutations.ts` | drafts/view/session-task orchestration |
| Source-collection mutation payload types | `sourceCollectionMutationModel.ts` | route-only presentation |
| Team shell write mutations | `useTeamShellMutations.ts` | drafts/view orchestration |
| Workflow start / stage-session mutations | `useTeamWorkflowStartMutations.ts` | draft/view navigation |
| Research stage start payload | `workflowStartMutationModel.ts` | route-only presentation |
| SC selected-run detail queries | `useSourceCollectionRunQueries.ts` | run selection / view gating |
| SC run query payload types | `sourceCollectionRunQueryModel.ts` | route-only presentation |
| Experiment + research-loop status queries | `useTeamResearchSecondaryQueries.ts` | workspace-view gating |
| Workflow tag tone helpers | `workflowTone.ts` | style map ownership |
| Shell pure helpers (stage parse / node labels / candidate graph) | `teamRouteShellModel.ts` | style-bound class helpers |
| Canvas node role/tone classification | `teamCanvasNodePresentation.ts` | hard-coding class strings in pure files |
| SC shell inject pure math (page/bindings/launch) | `teamSourceCollectionShellModel.ts` | JSX inject adapters |
| SC inject model (mode/writeback guards) | `source-collection/injectModel.ts` | route-only JSX |
| SC mode fields inject UI | `TeamSourceCollectionModeFields.tsx` | TeamsRoute query ownership |
| SC search-brief inject | `TeamSourceCollectionSearchBriefInject.tsx` | start mutation ownership |
| SC manual writeback inject | `TeamSourceCollectionManualWritebackInject.tsx` | record mutation ownership |
| SC controls inject | `TeamSourceCollectionControlsInject.tsx` | side-rail workspace body |
| SC active-stage inject | `TeamSourceCollectionActiveStageInject.tsx` | active-stage workspace body |
| SC filter/pagination pure | `source-collection/injectModel.ts` | route-only JSX |
| Orchestration / wiring only | `../TeamsRoute.tsx` | — |

## Bundle note (path-scoped secondary packs)

`TeamsRoute` keeps UI panels off the initial shell via `createLazyNamedTeamPanel` and **path-scoped** async barrels:

| Pack | Loader | Contains |
|---|---|---|
| Shared | `loadTeamSharedPanels` | Graph view, research memory evidence |
| Research core | `loadTeamResearchPanels` | Stage launcher/agents, research loop |
| Research experiment | `loadTeamResearchExperimentPanels` | Experiment ledger/method, workflow status, candidate preview |
| Research search | `loadTeamResearchSearchPanels` | AI search workspace, team memory index |
| Source-collection | `loadTeamSourceCollectionPanels` | SC chrome + workspace orchestration |

**Rules:**

- New panels must enter exactly one pack; do **not** revive a mono `teamSecondaryPanels` UI barrel.
- Same-pack static imports are fine; cross-pack **value** imports of workspaces are forbidden.
- Stay static in the shell (on purpose): pure models, query keys/hooks, style maps.
- Prefetch is path-scoped via `teamPanelPrefetch.ts`: warm research core / experiment / search / SC after team/view switch; **never** prefetch all packs on shell mount.

**Do not** re-add static value imports of panel components into `TeamsRoute.tsx` without a budget re-check.

## Pure extract progress

- **Done:** workspace navigation, team kind guards, canvas geometry, source-collection presentation, experiment/loop types+labels, AI-search presentation, workflow presentation labels, research stage agent role tables, workflow query keys, stage-agent presentation/routes.
- **Done (M5 structure):** `teamRouteShellModel.ts` — stage module parse, node/function labels, chat feedback text, candidate graph/chunk-plan pure helpers.
- **Done (M9 structure):** `teamCanvasNodePresentation.ts` — canvas role badge / node tone pure kinds + style-map mappers; shell keeps CSS token maps.
- **Still in `TeamsRoute.tsx` (intentional shell):** URL/view drafts, selection, JSX composition, thin `render*` inject adapters (filterBar/pagination/modeFields), tone wrappers, and remaining shell queries.
- **Wave 8G–8P done:** panel extract, path packs + prefetch, experiment/loop mutations, SC write mutations (see history below).
- **Wave 8Q done:** Team shell write mutations → `useTeamShellMutations`.
- **Wave 8R done:** Workflow start/session mutations → `useTeamWorkflowStartMutations` + `workflowStartMutationModel`.
- **Wave 8S done:** SC selected-run detail queries + research secondary queries extracted; SC run list selection stays route-owned.
- **Wave 8T done:** `workflowQualityTone` / `workflowIngestionTone` → `workflowTone.ts` (styles map injected via bound wrappers). Thin SC helpers remain route-local by design.
- **Wave 8U done:** Phase 8 closure — ownership map + contracts green; route has **zero** inline `useMutation` definitions.
- **M5 done:** shell pure helpers extracted without touching path packs or mutation ownership.

### Phase 8 Closure

| Goal | Status |
|---|---|
| Domain write mutations out of route | Done (shell / start / SC write / experiment-loop) |
| Path-scoped secondary packs + prefetch | Done (8N) |
| Status/detail query ownership | Done (research resources + secondary + SC run detail) |
| Style tone helpers | Done (`workflowTone.ts`) |
| Behavior-conserving refactors only | Done |
| Route is orchestration shell | Done |

### State-machine extract (Phases 1–4)

| Phase | Module | Status |
|---|---|---|
| 1 | `useSourceCollectionWorkspace` — SC drafts, run list, selection, hydration, detail queries | **Done** |
| 1+ | SC pagination reset + writeback-awaiting derived in SC hook | **Done** |
| 2 | `useResearchExperimentWorkspace` — experiment/loop drafts + secondary queries | **Done** |
| 3 | `useTeamsShellCanvasWorkspace` + `useTeamsCanvasProjection` — shell/canvas state + canvas query/projection | **Done** |
| 4 | `teamMutationSurface` — collapse team-scoped mutation pending/error/result ctx; docs/ownership map | **Done** |
| 4+ / presentation | `useSourceCollectionPresentation` — SC summary/records/candidates/counts/readiness/display + write/mutation surfaces + stage action adapters | **Done** |

**Still route-owned (intentional):** `sourceCollectionStageModules` JSX descriptors + board next-step, render* inject adapters, drag/save handlers, createExperimentWorkspaceActions wiring.

**Explicitly deferred to Phase 9+:** SC chrome+workspace double-layer merge; force `TeamsRoute` under 2k LOC; large Context replacement of inject props; cross-route Chat/Agents/Config depth parity.

**History (8G–8P):** 8G AI Search + stage agents · 8H launcher · 8I standalone stage · 8J loop/ledger · 8K–8M SC workspaces · 8N packs · prefetch · 8O experiment mutations · 8P SC mutations.

## Structure program

| Wave | Goal | Status |
|------|------|--------|
| M5 | TeamsRoute shell pure extract | **Done** — `teamRouteShellModel.ts` |
| M9 | Canvas node role/tone pure classification | **Done** — `teamCanvasNodePresentation.ts` |
| T2 | SC shell inject pure helpers | **Done** — `teamSourceCollectionShellModel.ts` |
| T2.1 | SC stage chat-state pure | **Done** — same module (`resolveSourceCollectionStageAgentChatState`) |
| T2.2 | SC inject model + mode fields claim | **Done** — `injectModel` + `TeamSourceCollectionModeFields` |
| T2.3 | SC search-brief / writeback inject claims | **Done** — `*SearchBriefInject` / `*ManualWritebackInject` |
| T2.4 | SC controls/active-stage inject + filter/page pure | **Done** |

## Next (planned) — Phase 9+

1. **Done (structure wave):** lazy pack facades → `teamLazyPanels.tsx`; experiment/research-loop workspace action adapters → `experimentWorkspaceActions.ts`.
2. **Done (state machine 1–4):** SC / experiment / shell-canvas workspace hooks + mutation surface ctx shrink.
3. Optional: extract SC presentation/readiness/stageModules chain when inject surface stabilizes (largest remaining B-section).
4. Optional: collapse SC chrome+workspace double layer; large React Context only with explicit charter.
5. Optional: cross-route query/mutation patterns (Chat/Agents) only with a new phase charter.

## Rules

1. Do not open a second Team EventSource for the same stream family.
2. Do not change React Query key shapes in drive-by refactors.
3. Keep pure builders free of React / DOM.
4. Font tokens: `[font-size:var(--vui-font-*)]`, never `text-[var(--vui-font-*)]` as size.
