# useResearchExperimentWorkspace — Phase 2 inventory

Baseline: after Phase 1 `useSourceCollectionWorkspace` (commit 366c7325e).

## React state (must own)

| State | Notes |
| --- | --- |
| preferredExperimentMethod | method picker default |
| experimentBaselineArtifactDraft | baseline register form |
| experimentSmokeResultDraft | smoke result form |
| experimentFullRunResultDraft | full-run result form |
| experimentKnowledgeIngestionDraft | experiment KB ingest form |
| selectedResearchLoopTemplateId | loop template pick |
| researchLoopCreateDraft | create loop form |
| researchLoopEvidenceDraft | evidence form |
| researchLoopDecisionDraft | decision form |

## Compose (existing hooks)

| Hook | Role |
| --- | --- |
| useTeamResearchSecondaryQueries | planning status + method catalog + loop templates/status |
| useTeamExperimentLoopMutations | Phase 2b optional; stays in route with hook setters |
| createExperimentWorkspaceActions | stays in route |

## Inputs from shell (not owned)

- effectiveTeamId, researchWorkflowTeamSelected
- researchWorkspaceView, sourceCollectionStandalone
- researchSecondaryStatusQueryEnabled (includes challenge surface)

## Outputs consumed by route

- All experiment/loop drafts + setters
- preferredExperimentMethod
- secondary status queries

## Cross-domain (do not import reverse)

- source-collection workspace state
- canvas node draft / team shell mode
