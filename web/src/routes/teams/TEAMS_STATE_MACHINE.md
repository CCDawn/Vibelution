# TeamsRoute state-machine map (Phases 1-4)

Behavior-conserving extract of React state ownership out of `TeamsRoute.tsx`.
Route remains the orchestration shell: mutations wiring, render* inject adapters, and SC presentation that still needs action handlers.

## Ownership

```
TeamsRoute (orchestration)
|-- useTeamsCatalogQueries           # R2-d -- teams list / agent summary / bus + picker visibility + membership
|-- useTeamsShellCanvasWorkspace     # Phase 3 -- team pick, shell mode, research view, canvas UI state/refs
|   +-- useTeamsCanvasProjection     # Phase 3 -- canvas query + display projection + node-draft sync
|-- useTeamsSelectedTeamDetail       # R2-e -- effectiveTeamId + team detail + kind flags + SC workspace selected
|-- useTeamsSecondaryDataQueries     # R2-f -- panel pack prefetch + AI Search runs list
|-- useTeamsMutationBundle           # R2-g -- shell/start/experiment/SC mutation wiring + saveCanvas
|-- createTeamsResearchNavigation    # R2-h -- workspace view / team pick / shell mode URL nav
|-- createResearchStageLaunchHandlers # R2-i -- launch / primary / advance (late-bound SC guards)
|-- createSourceCollectionStageAgentHelpers # R2-j -- stage agent chat routes + repair
|-- buildExperimentWorkspacePendingFlags # pure -- team-scoped experiment pending flags
|-- researchStageAgentBindings       # pure -- stage role → agent binding table
|-- teamWorkflowResourceDemand       # pure -- candidates/graph/quality/stage-round enable gates
|-- teamsWorkbenchChrome             # styles/panes/tone helpers (from model top)
|-- useSourceCollectionWorkspace     # Phase 1 / 1+ -- SC drafts, run list, selection, hydration, detail queries
|-- useSourceCollectionPresentation  # Phase 4+ -- SC presentation + mutation surfaces + stage action adapters
|   +-- buildTeamsRouteMutationSurface / buildSourceCollectionWriteMutationSurface / actionChrome
|   +-- F3 pure: presentationCountText / presentationExtractionMetrics / presentationActionReadiness / presentationStepStates
|-- composeSourceCollectionStageSurfaces # R2-k -- stage advance / modules / board chrome / controller
|-- source-collection/stageModulesModel  # stageModules / board / standalone / completion flow factory
|-- useResearchExperimentWorkspace   # Phase 2 -- experiment/loop drafts + secondary status queries
|   +-- useTeamResearchSecondaryQueries
|-- mutation hooks (unchanged ownership)
|   |-- useTeamShellMutations
|   |-- useTeamWorkflowStartMutations
|   |-- useTeamSourceCollectionMutations
|   +-- useTeamExperimentLoopMutations
|-- teamSourceCollectionInjectRenderers  # SC inject panel mounts (filter/page/controls/active-stage/…)
|-- teamResearchWorkflowSurfaceRenderers # workflow modules/panel host + communication + inspector shared
|-- teamResearchPrimarySurfaceRenderers  # launcher / overview / stage standalone
+-- remaining drag-save / mutation wiring / surface composers (route-local)
```


## Inputs / boundaries

| Domain | Owned by | Must not reverse-import |
| --- | --- | --- |
| SC UI + run queries | `useSourceCollectionWorkspace` | experiment drafts, canvas drag |
| Experiment/loop drafts | `useResearchExperimentWorkspace` | SC workspace state |
| Shell + canvas | `useTeamsShellCanvasWorkspace` (+ projection) | SC presentation chain |
| Mutation flags | `teamMutationSurface` (+ SC write surface) | React components |
| SC action chrome | `source-collection/actionChrome` | mutations / JSX |

## Verification

- Layout: `TeamsRoute.layout.test.ts` (includes Phase 1-3 source composites)
- Contracts: `useSourceCollectionWorkspace.contract.test.ts`, `useResearchExperimentWorkspace.contract.test.ts`, `useTeamsShellCanvasWorkspace.contract.test.ts`, `teamMutationSurface.contract.test.ts`, `composers.contract.test.ts`
- Pure unit: `teamMutationSurface.test.ts`, F3 `presentation*.test.ts`
- Backend: `tests/test_team_workflow_facade_contract.py`

## Clarity P5 + ①–⑥ progress

```
TeamsRoute
|-- useTeamsWorkbenchModel             # R2-c full orchestration + early returns
|     |-- useTeamsScComposition         # R1-a presentation+modules+controller
|     |     |-- useSourceCollectionPresentation → Core
|     |-- createTeamsResearchSurfaces   # R1-b
|     |-- renderTeamsShellFrame         # R1-c
|     |-- teamsShellSurfaceModel        # R2-b
|     +-- overview/candidate bags
|-- TeamsRouteWorkbench (thin) → useTeamsWorkbenchModel
|-- if (sourceCollectionStandalone) return renderStandalonePage(chrome)
|-- if (gate) return TeamsShellGateSurface
|-- if (canvas) return TeamsCanvasComposer
+-- board: TeamsOverviewComposer
```

- Shell: `ResearchStageWorkbenchShell` (`data-team-rail="hidden"`)
- F3: count + extraction metrics + action readiness + step states
- R2-c: Workbench entry thin; model owns body
- B1: `core/web/routes/team_workflows/` package
- B6: `experiment_api/*` + `source_collection/{stage_session,stage_writeback}.py`

## Done this wave

- **R2-d** `useTeamsCatalogQueries` — teams list, agent summary, project bus, picker membership/fallback
- **R2-e** `useTeamsSelectedTeamDetail` — effective team + detail query + kind flags + SC workspace selected
- **chrome** `teamsWorkbenchChrome` — style map, panes, canvas tone helpers
- **pure** `teamWorkflowResourceDemand` — workflow resource enable gates
- **R2-f** `useTeamsSecondaryDataQueries` — pack warm-up + AI Search runs
- **R2-g** `useTeamsMutationBundle` — four mutation-hook families + saveCanvas
- **R2-h** `createTeamsResearchNavigation` — workspace/team/shell URL navigation
- **R2-i** `createResearchStageLaunchHandlers` — launch/primary/advance with late-bound SC guards
- **R2-j** `createSourceCollectionStageAgentHelpers` — stage agent chat + repair
- **pure** `buildExperimentWorkspacePendingFlags` — team-scoped experiment pending flags
- **pure** `researchStageAgentBindings` — canvas/member role binding table
- **R2-k** `composeSourceCollectionStageSurfaces` — stage modules / board chrome / SC controller out of scComposition
- **R2-l** `useSourceCollectionPresentationEffects` + `deriveSourceCollectionListMetrics` — presentation effects + list/count/loading pure metrics
- **R2-m** `deriveSourceCollectionDisplayLabels` + `deriveSourceCollectionDownstreamMetrics` + `deriveSourceCollectionStageDisplaySurfaces` — count labels / graph-memory-ingest / stage display surfaces
- **R2-n** `deriveSourceCollectionSelectionPresentation` — finding options / prompt-cache / search accepted / candidate maps
- **R2-o** `useTeamsScComposition` bag passthrough (spread presentation + stage surfaces) + `deriveSourceCollectionSummaryProjection` + `createSourceCollectionStageActionHelpers` + presentation return spreads
- **R2-p debt** workbench unused-import purge + scComposition `pickCtx` rewrite
- **R2-q close-out** canvas/board extractors; presentation core thin + pipeline; SC presentation context on standalone
- **R2-s ship/close** workbench model thin (foundation + shell + scLayer); presentation pipeline thin (mid + tail); research surfaces bag builder; **编排主链收工**

## Ship status (编排主链收工)

```
TeamsRoute (5)
  → TeamsRouteWorkbench (16)
    → useTeamsWorkbenchModel (12)
         ├─ useTeamsWorkbenchFoundation (~1365)  // data + mutations + scLayer
         │    └─ useTeamsWorkbenchScLayer (~140)
         └─ useTeamsWorkbenchShellPhase (~668)
              ├─ buildTeamsWorkbenchResearchSurfacesFromBag (~140)
              ├─ renderTeamsWorkbenchCanvasPage (~157)
              └─ renderTeamsWorkbenchBoardPage (~73)

SC presentation:
  useSourceCollectionPresentation (9)
    → Core (15) → Pipeline (11)
         ├─ Mid (~959)   // derive / metrics
         └─ Tail (~674)  // handlers / return
  useTeamsScComposition (~58) → presentation + composeSourceCollectionStageSurfaces (~617)
```

| Spine (原三块主肉) | 收工形态 |
| --- | --- |
| Foundation | foundation + scLayer（数据编排归位） |
| Presentation pipeline | pipeline orchestrator + mid + tail |
| Shell phase | shell + research bag builder + canvas/board pages |

**Verification:** `TeamsRoute.layout.test.ts` + `src/routes/teams/**` → **101 files / 402 tests green**.

## Out of scope for this ship (不再作为编排连环债)

- Domain pure：`stageProjection` / `experimentLoopModel` / `evidenceModel` / `presentationModel`
- Mutation 族与 UI 面板（含 ChallengeCup workspace）
- inject 全量改 Context（Provider 已就绪）
- bag 字段级严格类型

以上不阻塞「Teams 编排拆分收工」。
