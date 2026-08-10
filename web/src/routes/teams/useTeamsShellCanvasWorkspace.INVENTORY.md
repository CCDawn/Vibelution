# useTeamsShellCanvasWorkspace — Phase 3 inventory

After Phase 1 SC + Phase 2 experiment workspace hooks.

## Shell React state (`useTeamsShellCanvasWorkspace`)

| State | Notes |
| --- | --- |
| selectedTeamId | URL / fallback team pick |
| selectedNodeId / nodeDraft | canvas binding inspector |
| teamMessage / teamInterrupt / teamTaskTopic | communication panel drafts |
| showCommunicationEdges | edge visibility toggle |
| researchCanvasLayoutMode | auto vs source layout |
| researchWorkspaceView | board research surface routing |
| teamShellMode | board \| canvas |
| nodePositionDrafts / canvasFrameSize / lockedCanvasViewportStyle | canvas chrome |

Refs: `canvasFrameRef`, `dragStateRef`, `dragFrameRef`.

## Canvas projection (`useTeamsCanvasProjection`)

| Output | Notes |
| --- | --- |
| teamCanvasQuery | gated by resolveTeamCanvasQueryEnabled |
| durableCanvas / canvas / nodes / edges | display model |
| selectedNode / viewport / scale | inspector + drag |
| researchCanvasReadOnly | research team canvas surface |

Effects: node draft hydrate, position-draft reset, locked viewport reset.

## Inputs from route (not owned)

- visibleTeamIds / fallback / URL team ids (from teams list query)
- selectedTeam / effectiveTeamId (from team detail query)
- researchWorkflowTeamSelected / sourceCollectionStandalone
- mutations: saveCanvas, shell mutations, drag commit handlers

## Cross-domain (do not import reverse)

- source-collection workspace
- experiment workspace
- SC agent role resolution (uses canvas but stays in route)
