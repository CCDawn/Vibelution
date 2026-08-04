# TeamsRoute state-machine map (Phases 1-4)

Behavior-conserving extract of React state ownership out of `TeamsRoute.tsx`.
Route remains the orchestration shell: mutations wiring, render* inject adapters, and SC presentation that still needs action handlers.

## Ownership

```
TeamsRoute (orchestration)
|-- useTeamsShellCanvasWorkspace     # Phase 3 -- team pick, shell mode, research view, canvas UI state/refs
|   +-- useTeamsCanvasProjection     # Phase 3 -- canvas query + display projection + node-draft sync
|-- useSourceCollectionWorkspace     # Phase 1 / 1+ -- SC drafts, run list, selection, hydration, detail queries
|-- useSourceCollectionPresentation  # Phase 4+ -- SC presentation + mutation surfaces + stage action adapters
|   +-- buildTeamsRouteMutationSurface / buildSourceCollectionWriteMutationSurface / actionChrome
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
+-- remaining research launcher/overview/standalone adapters / drag-save (route-local)
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
- Contracts: `useSourceCollectionWorkspace.contract.test.ts`, `useResearchExperimentWorkspace.contract.test.ts`, `useTeamsShellCanvasWorkspace.contract.test.ts`, `teamMutationSurface.contract.test.ts`
- Pure unit: `teamMutationSurface.test.ts`

## Intentionally not Phase 4

- Force `TeamsRoute` under 2k LOC
- Replace inject props with React Context
- Full SC stageModules/readiness move (still couples to start-session handlers)
