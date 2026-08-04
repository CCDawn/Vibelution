# useSourceCollectionWorkspace — Phase 0 inventory

Baseline tests (2026-08-04 session): TeamsRoute.layout + teams contracts + source-collection pure tests — **106 passed**.

## SC React state (must own)

| State | Notes |
| --- | --- |
| sourceCollectionDraft | hydrated from run + summary |
| selectedSourceCollectionRunId | empty ⇒ default selection |
| sourceCollectionOutputDraft | manual writeback |
| selectedSourceCollectionStageId | finding/extraction/relations/ingestion |
| sourceCollectionStageSyncUntilMs | writeback grace window |
| sourceCollectionPendingStageTaskIds | writeback await |
| sourceCollectionResultPageByStage | pagination |
| sourceCollectionExpandedPanelId / FocusedPanelId | UI chrome |
| sourceCollectionSourceFilter | list filter |
| selectedSourceCollectionCandidateId | selection |

Refs: draft hydrated run id, search plan key, fresh project draft id.

## Compose (existing hooks)

| Hook | Role |
| --- | --- |
| useSourceCollectionRunQueries | summary/status/records/assignments |
| (inline) research-projects + runs list queries | project-scoped run list |
| useTeamSourceCollectionMutations | Phase 1b optional; Phase 1a stays in route with hook setters |
| useTeamWorkflowStartMutations | stays in route (mixes AI search / stage start); needs SC setters |

## Inputs from shell (not owned)

- effectiveTeamId, pageVisible, lang
- researchWorkflowTeamSelected, sourceCollectionWorkspaceSelected (or researchWorkspaceView + standalone)
- selectedTeam (mode / knowledge expansion)
- agent role ids for mutations (from canvas/team)

## Outputs consumed by route

- All SC state + setters
- selectedSourceCollectionRun / EffectiveId / historical run helpers
- sourceCollectionStageWritebackSyncActive + pendingTaskIdList
- run detail queries
- hydration side effects (internal)

## Cross-domain (do not import reverse)

- experiment / researchLoop drafts
- canvas node draft
- team broadcast / shell mode
