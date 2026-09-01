/**
 * Path-scoped Teams UI pack loaders and lazy panel facades.
 * Keep shell imports here so TeamsRoute stays orchestration-only.
 * See teams/README.md pack rules.
 */
import { createLazyNamedTeamPanel } from "./lazyTeamPanel";
import type { TeamsPanelPackLoaders } from "./teamPanelPrefetch";

/** Path-scoped packs: shared | research core | research experiment | research search | research workflow inspector | SC. */
export const loadTeamSharedPanels = () => import("./teamSharedPanels");
export const loadTeamResearchPanels = () => import("./teamResearchPanels");
export const loadTeamResearchExperimentPanels = () => import("./teamResearchExperimentPanels");
export const loadTeamResearchSearchPanels = () => import("./teamResearchSearchPanels");
export const loadTeamResearchWorkflowPanels = () => import("./teamResearchWorkflowPanels");
export const loadTeamSourceCollectionPanels = () => import("./teamSourceCollectionPanels");

export const teamsPanelPackLoaders: TeamsPanelPackLoaders = {
  shared: loadTeamSharedPanels,
  research: loadTeamResearchPanels,
  research_experiment: loadTeamResearchExperimentPanels,
  research_search: loadTeamResearchSearchPanels,
  research_workflow: loadTeamResearchWorkflowPanels,
  source_collection: loadTeamSourceCollectionPanels,
};

export const TeamMemoryIndexPanel = createLazyNamedTeamPanel(loadTeamResearchSearchPanels, "TeamMemoryIndexPanel");
export const TeamAiSearchWorkspacePanel = createLazyNamedTeamPanel(loadTeamResearchSearchPanels, "TeamAiSearchWorkspacePanel");
export const TeamResearchStageAgentPanel = createLazyNamedTeamPanel(loadTeamResearchPanels, "TeamResearchStageAgentPanel");
export const TeamResearchStageAgentSummary = createLazyNamedTeamPanel(loadTeamResearchPanels, "TeamResearchStageAgentSummary");
export const TeamResearchStageLauncherPanel = createLazyNamedTeamPanel(loadTeamResearchPanels, "TeamResearchStageLauncherPanel");
export const TeamResearchLoopPanel = createLazyNamedTeamPanel(loadTeamResearchPanels, "TeamResearchLoopPanel");
export const TeamExperimentPlanningLedgerPanel = createLazyNamedTeamPanel(loadTeamResearchExperimentPanels, "TeamExperimentPlanningLedgerPanel");
// TeamExperimentMethodPanel is mounted inside TeamExperimentPlanningLedgerPanel (same experiment pack).
export const TeamSourceCollectionActiveStagePanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionActiveStagePanel");
export const TeamSourceCollectionPhaseCloseGatePanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionPhaseCloseGatePanel");
export const TeamSourceCollectionStageAgentsPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionStageAgentsPanel");
export const TeamSourceCollectionRunSwitcherPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionRunSwitcherPanel");
export const TeamSourceCollectionFindingDetailsPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionFindingDetailsPanel");
export const TeamSourceCollectionConversationPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionConversationPanel");
export const TeamSourceCollectionControlsPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionControlsPanel");
export const TeamSourceCollectionExtractionRecoveryPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionExtractionRecoveryPanel");
export const TeamSourceCollectionGraphPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionGraphPanel");
export const TeamSourceCollectionManualWritebackPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionManualWritebackPanel");
export const TeamSourceCollectionMemoryPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionMemoryPanel");
export const TeamSourceCollectionScreeningPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionScreeningPanel");
export const TeamKnowledgeCollectionCompletionFlowPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamKnowledgeCollectionCompletionFlowPanel");
export const TeamSourceCollectionConversationWorkspacePanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionConversationWorkspacePanel");
export const TeamSourceCollectionScreeningWorkspacePanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionScreeningWorkspacePanel");
export const TeamSourceCollectionExtractionRecoveryWorkspacePanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionExtractionRecoveryWorkspacePanel");
export const TeamSourceCollectionGraphWorkspacePanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionGraphWorkspacePanel");
export const TeamSourceCollectionMemoryWorkspacePanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionMemoryWorkspacePanel");
export const TeamSourceCollectionSelectedSourceWorkspacePanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionSelectedSourceWorkspacePanel");
export const TeamSourceCollectionControlsWorkspacePanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionControlsWorkspacePanel");
export const TeamSourceCollectionActiveStageWorkspacePanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionActiveStageWorkspacePanel");
export const TeamSourceCollectionSourceDetailPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionSourceDetailPanel");
export const TeamSourceCollectionStandaloneStagePanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionStandaloneStagePanel");
export const TeamSourceCollectionSearchBriefPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionSearchBriefPanel");
export const TeamSourceCollectionRunSettingsPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionRunSettingsPanel");
export const TeamSourceCollectionFilterBar = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionFilterBar");
export const TeamSourceCollectionPagination = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionPagination");
export const TeamSourceCollectionStorageActionsPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionStorageActionsPanel");
export const TeamWorkflowCandidatePreviewPanel = createLazyNamedTeamPanel(loadTeamResearchExperimentPanels, "TeamWorkflowCandidatePreviewPanel");
export const TeamsSourceCollectionPanel = createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamsSourceCollectionPanel");
export const ResearchMemoryEvidencePanel = createLazyNamedTeamPanel(loadTeamSharedPanels, "ResearchMemoryEvidencePanel");
export const TeamWorkflowGraphView = createLazyNamedTeamPanel(loadTeamSharedPanels, "TeamWorkflowGraphView");
export const TeamWorkflowCandidateGraphStatusPanel = createLazyNamedTeamPanel(loadTeamResearchExperimentPanels, "TeamWorkflowCandidateGraphStatusPanel");
export const TeamWorkflowCoordinationStatusPanel = createLazyNamedTeamPanel(loadTeamResearchExperimentPanels, "TeamWorkflowCoordinationStatusPanel");
export const TeamWorkflowKnowledgeIngestionStatusPanel = createLazyNamedTeamPanel(loadTeamResearchExperimentPanels, "TeamWorkflowKnowledgeIngestionStatusPanel");
export const TeamWorkflowModelEvidenceStatusPanel = createLazyNamedTeamPanel(loadTeamResearchExperimentPanels, "TeamWorkflowModelEvidenceStatusPanel");
export const TeamWorkflowPaperNoteChunkStatusPanel = createLazyNamedTeamPanel(loadTeamResearchExperimentPanels, "TeamWorkflowPaperNoteChunkStatusPanel");
export const TeamWorkflowSourceQualityStatusPanel = createLazyNamedTeamPanel(loadTeamResearchExperimentPanels, "TeamWorkflowSourceQualityStatusPanel");
// Research process-canvas inspector leaves (panel=-driven + node-driven).
export const ChallengeQuestionDetailPanel = createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "ChallengeQuestionDetailPanel");
export const ChallengeMvpProgressPanel = createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "ChallengeMvpProgressPanel");
export const EvidenceGraphView = createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "EvidenceGraphView");
export const HypothesisFirstNodeInspector = createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "HypothesisFirstNodeInspector");
export const HypothesisLeaderboardPanel = createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "HypothesisLeaderboardPanel");
export const ResearchAgentBindingPanel = createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "ResearchAgentBindingPanel");
export const ResearchAnomalyInboxPanel = createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "ResearchAnomalyInboxPanel");
export const ResearchProcessDefinitionNodePanel = createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "ResearchProcessDefinitionNodePanel");
export const ResearchProcessNodeInspector = createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "ResearchProcessNodeInspector");
export const ResearchRunLaunchPanel = createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "ResearchRunLaunchPanel");
export const ResearchRunTimeline = createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "ResearchRunTimeline");
export const ResearchTeamPanel = createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "ResearchTeamPanel");
