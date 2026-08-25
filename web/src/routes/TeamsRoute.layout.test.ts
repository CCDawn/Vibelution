import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import sourceCollectionApiSource from "../api/sourceCollection.ts?raw";
import type { SourceCollectionMaterializedKnowledgeIngestion } from "../api/sourceCollection";
import dataProcessingApiSource from "../api/dataProcessing.ts?raw";
import stageRoundsApiSource from "../api/stageRounds.ts?raw";
import teamWorkflowApiSource from "../api/teamWorkflow.ts?raw";
import teamKnowledgeApiSource from "../api/teamKnowledge.ts?raw";
import teamExperimentApiSource from "../api/teamExperiment.ts?raw";
import teamResearchOpsApiSource from "../api/teamResearchOps.ts?raw";
import researchLoopApiSource from "../api/researchLoop.ts?raw";
import { teamWorkspaceRoute } from "./teams/researchWorkspaceModel";
import canvasDataSource from "./TeamsRoute.canvasData.ts?raw";
import routeSourceRawThin from "./teams/useTeamsWorkbenchModel.tsx?raw";
import routeSourceRawFoundation from "./teams/useTeamsWorkbenchFoundation.tsx?raw";
import routeSourceRawShellPhase from "./teams/useTeamsWorkbenchShellPhase.tsx?raw";
const routeSourceRaw = `${routeSourceRawThin}\n${routeSourceRawFoundation}\n${routeSourceRawShellPhase}`;
import teamsRouteShellSource from "./teams/TeamsRouteWorkbench.tsx?raw";
import teamsSourceCollectionPanelSource from "./teams/TeamsSourceCollectionPanel.tsx?raw";
import researchMemoryEvidencePanelSource from "./teams/ResearchMemoryEvidencePanel.tsx?raw";
import canvasGeometrySource from "./teams/canvasGeometry.ts?raw";
import teamOrganizationCanvasSurfaceSource from "./teams/TeamOrganizationCanvasSurface.tsx?raw";
import teamNodeBindingPanelSource from "./teams/TeamNodeBindingPanel.tsx?raw";
import teamShellToolbarSource from "./teams/TeamShellToolbar.tsx?raw";
import teamCanvasReadOnlyInspectorSource from "./teams/TeamCanvasReadOnlyInspector.tsx?raw";
import teamsWorkspacePanelRenderersSource from "./teams/teamsWorkspacePanelRenderers.tsx?raw";
import teamSourceCollectionInjectRenderersSource from "./teams/teamSourceCollectionInjectRenderers.tsx?raw";
import sourceCollectionControllerSource from "./teams/source-collection/createSourceCollectionController.tsx?raw";
import teamResearchWorkflowSurfaceRenderersSource from "./teams/teamResearchWorkflowSurfaceRenderers.tsx?raw";
import teamResearchPrimarySurfaceRenderersSource from "./teams/teamResearchPrimarySurfaceRenderers.tsx?raw";
import teamCanvasNodeEditingSource from "./teams/useTeamCanvasNodeEditing.ts?raw";
import teamCanvasNodeModelSource from "./teams/teamCanvasNodeModel.ts?raw";
import teamCanvasNodePresentationSource from "./teams/teamCanvasNodePresentation.ts?raw";
import useSourceCollectionWorkspaceSource from "./teams/useSourceCollectionWorkspace.ts?raw";
import useResearchExperimentWorkspaceSource from "./teams/useResearchExperimentWorkspace.ts?raw";
import useTeamsShellCanvasWorkspaceSource from "./teams/useTeamsShellCanvasWorkspace.ts?raw";
import useTeamsCatalogQueriesSource from "./teams/useTeamsCatalogQueries.ts?raw";
import useTeamsSelectedTeamDetailSource from "./teams/useTeamsSelectedTeamDetail.ts?raw";
import teamsWorkbenchChromeSource from "./teams/teamsWorkbenchChrome.ts?raw";
import teamWorkflowResourceDemandSource from "./teams/teamWorkflowResourceDemand.ts?raw";
import useTeamsSecondaryDataQueriesSource from "./teams/useTeamsSecondaryDataQueries.ts?raw";
import useTeamsMutationBundleSource from "./teams/useTeamsMutationBundle.ts?raw";
import researchStageAgentBindingsSource from "./teams/researchStageAgentBindings.ts?raw";
import createTeamsResearchNavigationSource from "./teams/createTeamsResearchNavigation.ts?raw";
import createSourceCollectionStageAgentHelpersSource from "./teams/createSourceCollectionStageAgentHelpers.ts?raw";
import createResearchStageLaunchHandlersSource from "./teams/createResearchStageLaunchHandlers.ts?raw";
import buildExperimentWorkspacePendingFlagsSource from "./teams/buildExperimentWorkspacePendingFlags.ts?raw";
import composeSourceCollectionStageSurfacesSource from "./teams/composeSourceCollectionStageSurfaces.ts?raw";
import deriveSourceCollectionListMetricsSource from "./teams/source-collection/deriveSourceCollectionListMetrics.ts?raw";
import deriveSourceCollectionDisplayLabelsSource from "./teams/source-collection/deriveSourceCollectionDisplayLabels.ts?raw";
import deriveSourceCollectionDownstreamMetricsSource from "./teams/source-collection/deriveSourceCollectionDownstreamMetrics.ts?raw";
import deriveSourceCollectionStageDisplaySurfacesSource from "./teams/source-collection/deriveSourceCollectionStageDisplaySurfaces.ts?raw";
import deriveSourceCollectionSelectionPresentationSource from "./teams/source-collection/deriveSourceCollectionSelectionPresentation.ts?raw";
import deriveSourceCollectionSummaryProjectionSource from "./teams/source-collection/deriveSourceCollectionSummaryProjection.ts?raw";
import createSourceCollectionStageActionHelpersSource from "./teams/source-collection/createSourceCollectionStageActionHelpers.ts?raw";
import useSourceCollectionPresentationEffectsSource from "./teams/source-collection/useSourceCollectionPresentationEffects.ts?raw";
import useSourceCollectionPresentationCoreSource from "./teams/useSourceCollectionPresentationCore.ts?raw";
import useSourceCollectionPresentationPipelineSource from "./teams/useSourceCollectionPresentationPipeline.ts?raw";
import useSourceCollectionPresentationMidSource from "./teams/useSourceCollectionPresentationMid.ts?raw";
import useSourceCollectionPresentationTailSource from "./teams/useSourceCollectionPresentationTail.ts?raw";
import teamMutationSurfaceSource from "./teams/teamMutationSurface.ts?raw";
import sourceCollectionActionChromeSource from "./teams/source-collection/actionChrome.ts?raw";
import useSourceCollectionPresentationEntrySource from "./teams/useSourceCollectionPresentation.ts?raw";
import useSourceCollectionPresentationSourceRaw from "./teams/useSourceCollectionPresentationCore.ts?raw";
import useSourceCollectionPresentationPipelineSource2 from "./teams/useSourceCollectionPresentationPipeline.ts?raw";
const useSourceCollectionPresentationSource = `${useSourceCollectionPresentationSourceRaw}\n${useSourceCollectionPresentationPipelineSource}\n${useSourceCollectionPresentationMidSource}\n${useSourceCollectionPresentationTailSource}`;
import useTeamsScCompositionSource from "./teams/useTeamsScComposition.ts?raw";
import useTeamsWorkbenchModelSource from "./teams/useTeamsWorkbenchModel.tsx?raw";
import useTeamsWorkbenchFoundationSource from "./teams/useTeamsWorkbenchFoundation.tsx?raw";
import useTeamsWorkbenchShellPhaseSource from "./teams/useTeamsWorkbenchShellPhase.tsx?raw";
import useTeamsWorkbenchScLayerSource from "./teams/useTeamsWorkbenchScLayer.ts?raw";
import buildTeamsWorkbenchResearchSurfacesFromBagSource from "./teams/buildTeamsWorkbenchResearchSurfacesFromBag.ts?raw";
import createTeamsResearchSurfacesSource from "./teams/createTeamsResearchSurfaces.ts?raw";
import renderTeamsShellFrameSource from "./teams/renderTeamsShellFrame.tsx?raw";
import teamsShellSurfaceModelSource from "./teams/teamsShellSurfaceModel.ts?raw";
import buildTeamWorkflowCandidatePreviewItemsSource from "./teams/buildTeamWorkflowCandidatePreviewItems.tsx?raw";
import buildSourceCollectionOverviewBagSource from "./teams/buildSourceCollectionOverviewBag.ts?raw";
import stageModulesModelSource from "./teams/source-collection/stageModulesModel.ts?raw";
import sourceCollectionActionHandlersSource from "./teams/source-collection/createSourceCollectionActionHandlers.ts?raw";
import teamsShellGateSurfaceSource from "./teams/TeamsShellGateSurface.tsx?raw";
import teamsLoadingShellSource from "./teams/TeamsLoadingShell.tsx?raw";
import teamsCanvasComposerSource from "./teams/TeamsCanvasComposer.tsx?raw";
import teamsOverviewComposerSource from "./teams/TeamsOverviewComposer.tsx?raw";
import renderTeamsWorkbenchCanvasPageSource from "./teams/renderTeamsWorkbenchCanvasPage.tsx?raw";
import renderTeamsWorkbenchBoardPageSource from "./teams/renderTeamsWorkbenchBoardPage.tsx?raw";
import researchProcessWorkspaceSource from "./teams/research-workflow/ResearchProcessWorkspace.tsx?raw";
import deriveSourceCollectionOperationFlagsSource from "./teams/source-collection/deriveSourceCollectionOperationFlags.ts?raw";
import researchStageWorkbenchShellSource from "./teams/ResearchStageWorkbenchShell.tsx?raw";
import sourceCollectionComposerSource from "./teams/SourceCollectionComposer.tsx?raw";
import experimentStageComposerSource from "./teams/ExperimentStageComposer.tsx?raw";
import createExperimentControllerSource from "./teams/createExperimentController.tsx?raw";
import presentationActionReadinessSource from "./teams/source-collection/presentationActionReadiness.ts?raw";
import presentationStepStatesSource from "./teams/source-collection/presentationStepStates.ts?raw";
import presentationExtractionMetricsSource from "./teams/source-collection/presentationExtractionMetrics.ts?raw";
import presentationCountTextSource from "./teams/source-collection/presentationCountText.ts?raw";
import { TeamSourceCollectionActiveStagePanel } from "./teams/source-collection/ui/TeamSourceCollectionActiveStagePanel";

/** Route + extracted shell modules (layout contracts may live in either). */
const routeSourceParts = [
  routeSourceRaw,
  teamsRouteShellSource,
  teamOrganizationCanvasSurfaceSource,
  teamNodeBindingPanelSource,
  teamShellToolbarSource,
  teamCanvasReadOnlyInspectorSource,
  teamsWorkspacePanelRenderersSource,
  teamSourceCollectionInjectRenderersSource,
  teamResearchWorkflowSurfaceRenderersSource,
  teamResearchPrimarySurfaceRenderersSource,
  teamCanvasNodeEditingSource,
  teamCanvasNodeModelSource,
  useSourceCollectionWorkspaceSource,
  useResearchExperimentWorkspaceSource,
  useTeamsShellCanvasWorkspaceSource,
  useTeamsCatalogQueriesSource,
  useTeamsSelectedTeamDetailSource,
  teamsWorkbenchChromeSource,
  teamWorkflowResourceDemandSource,
  useTeamsSecondaryDataQueriesSource,
  useTeamsMutationBundleSource,
  researchStageAgentBindingsSource,
  createTeamsResearchNavigationSource,
  createSourceCollectionStageAgentHelpersSource,
  createResearchStageLaunchHandlersSource,
  buildExperimentWorkspacePendingFlagsSource,
  composeSourceCollectionStageSurfacesSource,
  deriveSourceCollectionListMetricsSource,
  deriveSourceCollectionDisplayLabelsSource,
  deriveSourceCollectionDownstreamMetricsSource,
  deriveSourceCollectionStageDisplaySurfacesSource,
  deriveSourceCollectionSelectionPresentationSource,
  deriveSourceCollectionSummaryProjectionSource,
  createSourceCollectionStageActionHelpersSource,
  useSourceCollectionPresentationEffectsSource,
  useSourceCollectionPresentationCoreSource,
  useSourceCollectionPresentationPipelineSource,
  useSourceCollectionPresentationMidSource,
  useSourceCollectionPresentationTailSource,
  teamMutationSurfaceSource,
  sourceCollectionActionChromeSource,
  useSourceCollectionPresentationEntrySource,
  useSourceCollectionPresentationSource,
  useTeamsWorkbenchModelSource,
  useTeamsWorkbenchFoundationSource,
  useTeamsWorkbenchShellPhaseSource,
  useTeamsWorkbenchScLayerSource,
  buildTeamsWorkbenchResearchSurfacesFromBagSource,
  useTeamsScCompositionSource,
  createTeamsResearchSurfacesSource,
  renderTeamsShellFrameSource,
  teamsShellSurfaceModelSource,
  buildTeamWorkflowCandidatePreviewItemsSource,
  buildSourceCollectionOverviewBagSource,
  stageModulesModelSource,
  sourceCollectionControllerSource,
  sourceCollectionActionHandlersSource,
  teamsShellGateSurfaceSource,
  teamsLoadingShellSource,
  teamsCanvasComposerSource,
  teamsOverviewComposerSource,
  researchStageWorkbenchShellSource,
  sourceCollectionComposerSource,
  experimentStageComposerSource,
  createExperimentControllerSource,
  presentationActionReadinessSource,
  presentationStepStatesSource,
  presentationExtractionMetricsSource,
  presentationCountTextSource,
];
import researchWorkspaceModelSource from "./teams/researchWorkspaceModel.ts?raw";
import researchProjectSwitcherSource from "./teams/research-projects/ResearchProjectSwitcher.tsx?raw";
import teamLazyPanelsSource from "./teams/teamLazyPanels.tsx?raw";
import teamKindModelSource from "./teams/teamKindModel.ts?raw";
import evidenceModelSource from "./teams/source-collection/evidenceModel.ts?raw";
import presentationModelSource from "./teams/source-collection/presentationModel.ts?raw";
import runModelSource from "./teams/source-collection/runModel.ts?raw";
import stageProjectionSource from "./teams/source-collection/stageProjection.ts?raw";
import extractionRecoveryViewModelSource from "./teams/source-collection/extractionRecoveryViewModel.ts?raw";
import researchWorkflowResourcesSource from "./teams/useResearchWorkflowResources.ts?raw";
import teamExperimentLoopMutationsSource from "./teams/useTeamExperimentLoopMutations.ts?raw";
import teamSourceCollectionMutationsSource from "./teams/useTeamSourceCollectionMutations.ts?raw";
import teamShellMutationsSource from "./teams/useTeamShellMutations.ts?raw";
import teamWorkflowStartMutationsSource from "./teams/useTeamWorkflowStartMutations.ts?raw";
import teamResearchSecondaryQueriesSource from "./teams/useTeamResearchSecondaryQueries.ts?raw";
import sourceCollectionRunQueriesSource from "./teams/useSourceCollectionRunQueries.ts?raw";
import workflowToneSource from "./teams/workflowTone.ts?raw";

/** Route shell + claimable pure modules extracted from TeamsRoute. */
import experimentLoopModelSource from "./teams/experimentLoopModel.ts?raw";
import aiSearchPresentationSource from "./teams/aiSearchPresentation.ts?raw";
import workflowPresentationSource from "./teams/workflowPresentation.ts?raw";
import researchStageRolesSource from "./teams/researchStageRoles.ts?raw";
import teamWorkflowQueryKeysSource from "./teams/teamWorkflowQueryKeys.ts?raw";
import researchStageAgentPresentationSource from "./teams/researchStageAgentPresentation.ts?raw";
import teamRouteShellModelSource from "./teams/teamRouteShellModel.ts?raw";
import teamSourceCollectionShellModelSource from "./teams/teamSourceCollectionShellModel.ts?raw";
import teamSourceCollectionInjectModelSource from "./teams/source-collection/injectModel.ts?raw";
import teamSourceCollectionModeFieldsSource from "./teams/TeamSourceCollectionModeFields.tsx?raw";

/** Include pure/lazy owners so import cleanup in workbench does not break layout ownership asserts. */
const routeSource = [
  ...routeSourceParts,
  teamLazyPanelsSource,
  teamKindModelSource,
  experimentLoopModelSource,
  evidenceModelSource,
  researchWorkspaceModelSource,
  presentationModelSource,
  stageProjectionSource,
  researchWorkflowResourcesSource,
  teamWorkflowStartMutationsSource,
  teamExperimentLoopMutationsSource,
  sourceCollectionRunQueriesSource,
  renderTeamsWorkbenchCanvasPageSource,
  renderTeamsWorkbenchBoardPageSource,
  deriveSourceCollectionOperationFlagsSource,
].join("\n");

const routeAndPureSource = `${routeSource}\n${canvasGeometrySource}\n${researchWorkspaceModelSource}\n${teamKindModelSource}\n${presentationModelSource}\n${experimentLoopModelSource}\n${aiSearchPresentationSource}\n${workflowPresentationSource}\n${researchStageRolesSource}\n${teamWorkflowQueryKeysSource}\n${researchStageAgentPresentationSource}\n${teamRouteShellModelSource}\n${teamSourceCollectionShellModelSource}`;

function renderSourceCollectionKnowledgeIngestionStatus(
  payload: SourceCollectionMaterializedKnowledgeIngestion | null,
) {
  return renderToStaticMarkup(createElement(TeamSourceCollectionActiveStagePanel, {
    lang: "zh",
    stageId: "ingestion",
    title: "资料入库",
    status: "当前阶段",
    materializedKnowledgeIngestion: payload,
    primaryAction: {
      tone: "primary",
      disabled: false,
      title: "开始入库",
      label: "开始入库",
      icon: "play",
      onAction: () => undefined,
    },
    agentChatAction: createElement("span", null, "Agent 私聊"),
    agentConfigAction: createElement("span", null, "配置 Agent"),
    errors: null,
    renderConversationPanel: () => createElement("span", null, "conversation"),
    renderScreeningPanel: () => createElement("span", null, "screening"),
    renderGraphPanel: () => createElement("span", null, "graph"),
    renderMemoryPanel: () => createElement("span", null, "memory"),
  }));
}

describe("research project workspace", () => {
  it("never routes an active source-collection batch to a legacy direct Agent session", () => {
    // R2-j: stage agent chat helpers live in createSourceCollectionStageAgentHelpers.
    expect(createSourceCollectionStageAgentHelpersSource).toContain(
      "const route = currentTaskSessionRoute;",
    );
    expect(createSourceCollectionStageAgentHelpersSource).toContain("projectRunAvailable: Boolean(selectedSourceCollectionRunEffectiveId)");
    expect(createSourceCollectionStageAgentHelpersSource).not.toContain("currentTaskSessionRoute || researchStageAgentDirectChatRoute(");
  });

  it("labels a project-session creation action as Agent chat rather than Agent repair", () => {
    const panel = teamSourceCollectionActiveStageWorkspacePanelSource.replace(/\r\n/g, "\n");
    expect(panel).toContain(
      'const primaryStageAgentSessionCreateReady = primaryStageAgentChatState.status === "ready";',
    );
    expect(panel).toContain("进入 Agent 私聊");
    expect(panel).toContain("Open Agent chat");
  });

  it("does not enable legacy experiment projections from the Challenge workflow shell", () => {
    expect(routeSource).toContain("challengeProgramProgressVisible: false");
    expect(routeSource).not.toContain("challengeTeamSurface");
  });

  it("anchors experiment mutations to the stable route team while details are deferred", () => {
    const experimentActionSource = routeSource.slice(
      routeSource.indexOf("} = createExperimentWorkspaceActions({"),
      routeSource.indexOf("function renderResearchStageAgentSummary"),
    );

    expect(experimentActionSource).toContain("teamId: effectiveTeamId");
    expect(experimentActionSource).not.toContain('teamId: selectedTeam?.teamId || ""');
  });

  it("mounts the Challenge Program workflow only through the canonical primary surface", () => {
    expect(teamResearchStageLauncherPanelSource).not.toContain(
      "const challengeProgramSurfaceSelected =",
    );
    expect(teamResearchPrimarySurfaceRenderersSource).toContain("ResearchProcessWorkspace");
    expect(teamResearchStageLauncherPanelSource).not.toContain("ResearchProcessWorkspace");
    expect(teamResearchStageLauncherPanelSource).not.toContain('surface="workspace"');
  });

  it("keeps one overall progress rail outside the challenge research workspace", () => {
    expect(renderTeamsWorkbenchBoardPageSource).toContain(
      "rail={suppressOuterShellChrome ? null : p.teamShellRail}",
    );
    expect(researchProcessWorkspaceSource).not.toContain("<ResearchProcessRail");
    expect(researchProcessWorkspaceSource).not.toContain('sidebar: { id: "rail"');
    expect(researchProcessWorkspaceSource).toContain('aside: { id: "inspector"');
  });

  it("mounts persistent project switching above the three-stage workspace", () => {
    // Wave 8H: ResearchProjectSwitcher remains for non-challenge stage launcher paths.
    expect(teamResearchStageLauncherPanelSource).toContain("<ResearchProjectSwitcher");
    expect(teamResearchStageLauncherPanelSource).toContain("onProjectActivated");
    expect(routeSource).toContain("TeamResearchStageLauncherPanel");
    expect(researchProjectSwitcherSource).toContain("新建研究项目");
  });

  it("keeps challenge platform surfaces compact and moves explanations into VUI tooltips", () => {
    // Board mode drops dual surface tabs; shell mode switch is the primary chrome.
    expect(routeSource).toContain("TeamShellToolbar");
    expect(routeSource).not.toContain("<TeamShellModeSwitch");
    expect(routeSource).toContain("selectTeamShellMode");
    expect(routeStyles.challengeSurfaceSwitch).toContain("inline-grid");
    expect(routeStyles.challengeSurfaceSwitch).toContain("w-fit");
    expect(routeStyles.challengeSurfaceSwitch).not.toContain("w-full");
  });
});
import teamMemoryIndexPanelSource from "./TeamMemoryIndexPanel.tsx?raw";
import teamMemoryIndexPanelStyles from "./TeamMemoryIndexPanel.styles";
import teamAiSearchWorkspacePanelSource from "./TeamAiSearchWorkspacePanel.tsx?raw";
import teamResearchStageAgentPanelSource from "./TeamResearchStageAgentPanel.tsx?raw";
import teamResearchStageLauncherPanelSource from "./TeamResearchStageLauncherPanel.tsx?raw";
import teamCommunicationPanelSource from "./teams/TeamCommunicationPanel.tsx?raw";
import teamResearchBoardPrimarySurfaceSource from "./teams/TeamResearchBoardPrimarySurface.tsx?raw";
import teamResearchWorkflowPanelHostSource from "./teams/TeamResearchWorkflowPanelHost.tsx?raw";
import teamResearchWorkflowStageModulesSource from "./teams/TeamResearchWorkflowStageModules.tsx?raw";
import teamSourceCollectionSearchBriefShellSource from "./teams/TeamSourceCollectionSearchBriefShell.tsx?raw";
import teamSourceCollectionStorageActionsInjectSource from "./teams/TeamSourceCollectionStorageActionsInject.tsx?raw";
import teamResearchLoopPanelSource from "./TeamResearchLoopPanel.tsx?raw";
import teamExperimentPlanningLedgerPanelSource from "./TeamExperimentPlanningLedgerPanel.tsx?raw";
import teamExperimentHypothesisGovernancePanelSource from "./TeamExperimentHypothesisGovernancePanel.tsx?raw";
import teamKnowledgeCollectionCompletionFlowPanelSource from "./TeamKnowledgeCollectionCompletionFlowPanel.tsx?raw";
import teamSourceCollectionConversationWorkspacePanelSource from "./teams/source-collection/ui/TeamSourceCollectionConversationWorkspacePanel.tsx?raw";
import teamSourceCollectionScreeningWorkspacePanelSource from "./teams/source-collection/ui/TeamSourceCollectionScreeningWorkspacePanel.tsx?raw";
import teamSourceCollectionExtractionRecoveryWorkspacePanelSource from "./teams/source-collection/ui/TeamSourceCollectionExtractionRecoveryWorkspacePanel.tsx?raw";
import teamSourceCollectionCandidateWorkspacePanelSource from "./teams/source-collection/ui/TeamSourceCollectionCandidateWorkspacePanel.tsx?raw";
import teamSourceCollectionGraphWorkspacePanelSource from "./teams/source-collection/ui/TeamSourceCollectionGraphWorkspacePanel.tsx?raw";
import teamSourceCollectionMemoryWorkspacePanelSource from "./teams/source-collection/ui/TeamSourceCollectionMemoryWorkspacePanel.tsx?raw";
import teamSourceCollectionSelectedSourceWorkspacePanelSource from "./teams/source-collection/ui/TeamSourceCollectionSelectedSourceWorkspacePanel.tsx?raw";
import teamSourceCollectionControlsWorkspacePanelSource from "./teams/source-collection/ui/TeamSourceCollectionControlsWorkspacePanel.tsx?raw";
import teamSourceCollectionActiveStageWorkspacePanelSource from "./teams/source-collection/ui/TeamSourceCollectionActiveStageWorkspacePanel.tsx?raw";
import teamExperimentMethodPanelSource from "./TeamExperimentMethodPanel.tsx?raw";
import teamExperimentMethodPanelStyles from "./TeamExperimentMethodPanel.styles";
import teamSourceCollectionActiveStagePanelSource from "./teams/source-collection/ui/TeamSourceCollectionActiveStagePanel.tsx?raw";
import teamSourceCollectionActiveStagePanelStyles from "./teams/source-collection/ui/TeamSourceCollectionActiveStagePanel.styles";
import teamSourceCollectionCandidatePanelSource from "./teams/source-collection/ui/TeamSourceCollectionCandidatePanel.tsx?raw";
import teamSourceCollectionCandidatePanelStyles from "./teams/source-collection/ui/TeamSourceCollectionCandidatePanel.styles";
import teamSourceCollectionConversationPanelSource from "./teams/source-collection/ui/TeamSourceCollectionConversationPanel.tsx?raw";
import teamSourceCollectionConversationPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionConversationPanel.styles";
import teamSourceCollectionConversationPanelStylesSource from "./teams/source-collection/ui/TeamSourceCollectionConversationPanel.styles.ts?raw";
import teamSourceCollectionControlsPanelSource from "./teams/source-collection/ui/TeamSourceCollectionControlsPanel.tsx?raw";
import teamSourceCollectionControlsPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionControlsPanel.styles";
import teamSourceCollectionExtractionRecoveryPanelSource from "./teams/source-collection/ui/TeamSourceCollectionExtractionRecoveryPanel.tsx?raw";
import teamSourceCollectionExtractionRecoveryPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionExtractionRecoveryPanel.styles";
import teamSourceCollectionFindingDetailsPanelSource from "./teams/source-collection/ui/TeamSourceCollectionFindingDetailsPanel.tsx?raw";
import teamSourceCollectionFindingDetailsPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionFindingDetailsPanel.styles";
import teamSourceCollectionGraphPanelSource from "./teams/source-collection/ui/TeamSourceCollectionGraphPanel.tsx?raw";
import teamSourceCollectionGraphPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionGraphPanel.styles";
import teamSourceCollectionManualWritebackPanelSource from "./teams/source-collection/ui/TeamSourceCollectionManualWritebackPanel.tsx?raw";
import teamSourceCollectionManualWritebackPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionManualWritebackPanel.styles";
import teamSourceCollectionMemoryPanelSource from "./teams/source-collection/ui/TeamSourceCollectionMemoryPanel.tsx?raw";
import teamSourceCollectionMemoryPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionMemoryPanel.styles";
import teamSourceCollectionPhaseCloseGatePanelSource from "./teams/source-collection/ui/TeamSourceCollectionPhaseCloseGatePanel.tsx?raw";
import teamSourceCollectionPhaseCloseGatePanelStyles from "./teams/source-collection/ui/TeamSourceCollectionPhaseCloseGatePanel.styles";
import teamSourceCollectionOverviewPanelSource from "./teams/source-collection/ui/TeamSourceCollectionOverviewPanel.tsx?raw";
import teamSourceCollectionOverviewPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionOverviewPanel.styles";
import teamSourceCollectionOverviewPanelStylesSource from "./teams/source-collection/ui/TeamSourceCollectionOverviewPanel.styles.ts?raw";
import teamSourceCollectionPanelFrameStyles from "./teams/source-collection/ui/TeamSourceCollectionPanelFrame.styles";
import teamSourceCollectionPanelFrameStylesSource from "./teams/source-collection/ui/TeamSourceCollectionPanelFrame.styles.ts?raw";
import teamSourceCollectionResultControlsSource from "./teams/source-collection/ui/TeamSourceCollectionResultControls.tsx?raw";
import teamSourceCollectionRunSettingsPanelSource from "./teams/source-collection/ui/TeamSourceCollectionRunSettingsPanel.tsx?raw";
import teamSourceCollectionRunSettingsPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionRunSettingsPanel.styles";
import teamSourceCollectionSearchBriefPanelSource from "./teams/source-collection/ui/TeamSourceCollectionSearchBriefPanel.tsx?raw";
import teamSourceCollectionSearchBriefPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionSearchBriefPanel.styles";
import teamSourceCollectionScreeningPanelSource from "./teams/source-collection/ui/TeamSourceCollectionScreeningPanel.tsx?raw";
import teamSourceCollectionScreeningPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionScreeningPanel.styles";
import teamSourceCollectionStageAgentsPanelSource from "./teams/source-collection/ui/TeamSourceCollectionStageAgentsPanel.tsx?raw";
import teamSourceCollectionStageAgentsPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionStageAgentsPanel.styles";
import teamSourceCollectionRunSwitcherPanelSource from "./teams/source-collection/ui/TeamSourceCollectionRunSwitcherPanel.tsx?raw";
import teamSourceCollectionRunSwitcherPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionRunSwitcherPanel.styles";
import teamSourceCollectionSourceDetailPanelSource from "./teams/source-collection/ui/TeamSourceCollectionSourceDetailPanel.tsx?raw";
import teamSourceCollectionSourceDetailPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionSourceDetailPanel.styles";
import teamSourceCollectionStandaloneStagePanelSource from "./teams/source-collection/ui/TeamSourceCollectionStandaloneStagePanel.tsx?raw";
import teamSourceCollectionStandaloneStagePanelStyles from "./teams/source-collection/ui/TeamSourceCollectionStandaloneStagePanel.styles";
import teamSourceCollectionStorageActionsPanelSource from "./teams/source-collection/ui/TeamSourceCollectionStorageActionsPanel.tsx?raw";
import teamSourceCollectionStorageActionsPanelStyles from "./teams/source-collection/ui/TeamSourceCollectionStorageActionsPanel.styles";
import teamWorkflowCandidatePreviewPanelSource from "./TeamWorkflowCandidatePreviewPanel.tsx?raw";
import teamWorkflowCandidatePreviewPanelStyles from "./TeamWorkflowCandidatePreviewPanel.styles";
import teamWorkflowCandidatePreviewPanelStylesSource from "./TeamWorkflowCandidatePreviewPanel.styles.ts?raw";
import teamWorkflowStatusPanelsSource from "./TeamWorkflowStatusPanels.tsx?raw";
import teamWorkflowStatusPanelStyles from "./TeamWorkflowStatusPanels.styles";
import teamWorkflowStatusPanelStylesSource from "./TeamWorkflowStatusPanels.styles.ts?raw";
import workflowGraphViewSource from "./TeamWorkflowGraphView.tsx?raw";
import workflowGraphViewStyles from "./TeamWorkflowGraphView.styles";
import teamCandidateCardSource from "../components/vui/product/team-management/TeamCandidateCard.tsx?raw";
import teamSourceEmptyStateSource from "../components/vui/product/team-management/TeamSourceEmptyState.tsx?raw";
import teamSourceFilterBarSource from "../components/vui/product/team-management/TeamSourceFilterBar.tsx?raw";
import teamSourcePaginationSource from "../components/vui/product/team-management/TeamSourcePagination.tsx?raw";
import teamStageCardSource from "../components/vui/product/team-management/TeamStageCard.tsx?raw";
import teamStageCommandBarSource from "../components/vui/product/team-management/TeamStageCommandBar.tsx?raw";
import teamStagePipelineSource from "../components/vui/product/team-management/TeamStagePipeline.tsx?raw";
import teamSourceResultListSource from "../components/vui/product/team-management/TeamSourceResultList.tsx?raw";
import teamSourceResultStatsSource from "../components/vui/product/team-management/TeamSourceResultStats.tsx?raw";
import shellRouteStyles from "./TeamsRoute.styles";
import researchRouteStyles from "./TeamsRoute.research.styles";
import aiSearchRouteStyles from "./TeamsRoute.aiSearch.styles";
import experimentRouteStyles from "./TeamsRoute.experiment.styles";
import workflowRouteStyles from "./TeamsRoute.workflow.styles";
const routeStylesBase = {
  ...shellRouteStyles,
  ...researchRouteStyles,
  ...aiSearchRouteStyles,
  ...experimentRouteStyles,
  ...workflowRouteStyles,
} as Record<string, string>;
import shellRouteStylesModuleSource from "./TeamsRoute.styles.ts?raw";
import researchRouteStylesModuleSource from "./TeamsRoute.research.styles.ts?raw";
import aiSearchRouteStylesModuleSource from "./TeamsRoute.aiSearch.styles.ts?raw";
import experimentRouteStylesModuleSource from "./TeamsRoute.experiment.styles.ts?raw";
import workflowRouteStylesModuleSource from "./TeamsRoute.workflow.styles.ts?raw";
const routeStylesModuleSource = [
  shellRouteStylesModuleSource,
  researchRouteStylesModuleSource,
  aiSearchRouteStylesModuleSource,
  experimentRouteStylesModuleSource,
  workflowRouteStylesModuleSource,
].join("\n");
import routerSource from "../app/router.tsx?raw";

const sourceCollectionLocalStyles = {
  ...teamSourceCollectionActiveStagePanelStyles,
  ...teamSourceCollectionCandidatePanelStyles,
  ...teamSourceCollectionConversationPanelStyles,
  ...teamSourceCollectionControlsPanelStyles,
  ...teamSourceCollectionExtractionRecoveryPanelStyles,
  ...teamSourceCollectionGraphPanelStyles,
  ...teamSourceCollectionMemoryPanelStyles,
  ...teamSourceCollectionOverviewPanelStyles,
  ...teamSourceCollectionPhaseCloseGatePanelStyles,
  ...teamSourceCollectionPanelFrameStyles,
  ...teamSourceCollectionRunSwitcherPanelStyles,
  ...teamSourceCollectionSearchBriefPanelStyles,
  ...teamSourceCollectionScreeningPanelStyles,
  ...teamSourceCollectionSourceDetailPanelStyles,
  ...teamSourceCollectionStageAgentsPanelStyles,
  ...teamSourceCollectionStandaloneStagePanelStyles,
  ...teamSourceCollectionStorageActionsPanelStyles,
  ...teamSourceCollectionFindingDetailsPanelStyles,
  ...teamSourceCollectionManualWritebackPanelStyles,
  ...teamSourceCollectionRunSettingsPanelStyles,
};

/** Wave 8E: merge panel maps so routeStyles resolves ownership after dead-key prune. */
const routeStyles = {
  ...routeStylesBase,
  ...sourceCollectionLocalStyles,
  ...teamMemoryIndexPanelStyles,
  ...teamExperimentMethodPanelStyles,
  ...teamWorkflowCandidatePreviewPanelStyles,
  ...teamWorkflowStatusPanelStyles,
  ...workflowGraphViewStyles,
} as Record<string, string>;

const routeStylesSource = [
  routeStylesModuleSource,
  ...Object.keys(routeStylesBase).map((key) => `.${key}`),
  ...Object.values(routeStylesBase),
  // Panel-owned class names still contracted via routeStylesSource scans.
  ...Object.keys(teamMemoryIndexPanelStyles).map((key) => `.${key}`),
  ...Object.values(teamMemoryIndexPanelStyles),
].join("\n");

function classTokenCount(className: string, token: string) {
  return className.split(/\s+/).filter((item) => item === token).length;
}

function topLevelBackgroundTokenCount(className: string) {
  return className
    .split(/\s+/)
    .filter((item) =>
      item.startsWith("bg-[")
      || item.startsWith("!bg-[")
      || item.startsWith("bg-vui-surface-")
      || item.startsWith("!bg-vui-surface-")
    ).length;
}

function expectOperationalSurface(className: string, surface = "var(--vui-surface-panel)") {
  const acceptsThemeUtility =
    (surface.includes("surface-panel")
      && /bg-vui-surface-panel|!bg-vui-surface-panel|var\(--vui-surface-panel\)/.test(className))
    || (surface.includes("surface-row")
      && /bg-vui-surface-row|!bg-vui-surface-row|var\(--vui-surface-row\)/.test(className))
    || className.includes(surface);
  expect(acceptsThemeUtility, `expected opaque surface for ${surface}, got: ${className.slice(0, 120)}`).toBe(true);
  expect(className).not.toContain("bg-[var(--vui-surface-glass)]");
  expect(className).not.toContain("bg-vui-surface-glass");
  expect(className).not.toContain("shadow-[var(--vui-shadow-hairline)]");
  expect(className).not.toContain("bg-[image:var(--vui-gradient-route-soft)]");
  expect(className).not.toContain("shadow-[var(--vui-elevation-1-sheen)]");
  expect(className).not.toContain("hover:shadow-[var(--vui-elevation-2-sheen)]");
}

describe("TeamsRoute layout contract", () => {
  it("lets the backend resolve the experiment session instead of requiring directSessionId", () => {
    expect(routeSource).not.toContain("!binding?.agent?.directSessionId");
    expect(sourceCollectionControllerSource).toContain("navigate(payload.chatRoute)");
    expect(sourceCollectionControllerSource).toContain(
      "formalRetry: options.formalRetry ?? sourceCollectionStageFormalRetryRequired(stageId)",
    );
    expect(routeSource).toContain("sourceCollectionStageFormalRetryRequired");
    expect(routeSource).not.toContain("chatState.route || payload.chatRoute");
    expect(routeSource).not.toContain("payload.chatRoute || chatState.route");
  });

  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(teamsRouteShellSource).toContain("useTeamsWorkbenchModel");
    expect(teamsRouteShellSource).toContain("export function TeamsRoute");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("is mounted as the top-level Team workspace without retired research routes", () => {
    expect(routerSource).toContain('path: "teams"');
    expect(routerSource).toContain('guardedLazyElement(<TeamsRoute />, "workbench", "teams")');
    expect(routerSource).not.toContain('path: "agents/teams"');
    expect(routerSource).not.toContain('path: "research"');
    expect(routerSource).not.toContain('path: "research/flow-canvas"');
    expect(routerSource).not.toContain("LegacyTeamsRedirect");
    expect(routeSource).not.toContain("AgentManagementNav");
    expect(routeSource).toContain("团队工作台");
    expect(routeSource).toContain("Team workbench");
  });

  it("keeps canvas action labels compact and exposes non-critical explanations through VUI tooltips", () => {
    expect(routeSource).toContain("VTooltip");
    // Status/next-step live in the left rail; org-canvas layout chrome stays on the canvas toolbar.
    expect(routeSource).toContain("TeamShellStatusRail");
    expect(routeSource).toContain("hideCanvasToolbar");
    expect(teamShellToolbarSource).toContain("VSelect");
    // Wave 8M: stage-agent config tooltip lives on active-stage workspace panel.
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain('content={lang === "zh" ? "当前阶段 Agent 配置"');
    expect(routeSource).toContain('content={lang === "zh" ? "到 AgentDirectory 源配置修改"');
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).not.toContain('title={lang === "zh" ? "当前阶段 Agent 配置"');
    expect(routeSource).not.toContain('title={lang === "zh" ? "到 AgentDirectory 源配置修改"');
  });

  it("keeps selected Team deep links on canonical /teams teamId routes", () => {
    expect(teamWorkspaceRoute("research-core")).toBe(
      "/teams?teamId=research-core&researchView=workflow&workflowId=challenge-cup-research",
    );
  });

  it("uses Team APIs and Agent Center as the binding source", () => {
    expect(routeSource).toContain("listTeams({ signal })");
    expect(routeSource).toContain("TEAM_BOOTSTRAP_REFETCH_STATUSES");
    expect(routeSource).toContain("query.state.data?.systemTeamBootstrap?.status");
    expect(routeSource).toContain("TEAM_BOOTSTRAP_ACTIVE_REFETCH_MS");
    expect(routeSource).not.toContain('fetchJson<TeamTemplateListPayload>("/api/team-templates")');
    expect(routeSource).not.toContain("/api/team-templates/${encodeURIComponent(templateId)}/instantiate");
    expect(routeSource).not.toContain("instantiateTeamTemplateMutation");
    expect(routeSource).toContain("TEAM_PICKER_TEAM_IDS");
    expect(canvasDataSource).toContain("const TEAM_PICKER_TEAM_IDS = [RESEARCH_TEAM_ID, AI_SEARCH_TEAM_ID, KNOWLEDGE_EXPANSION_TEAM_ID] as const");
    expect(useTeamsSelectedTeamDetailSource).toContain("fetchTeam(effectiveTeamId, { signal, detail: teamDetailLoadMode })");
    expect(routeSource).toContain("queryKeys.agentSummary(false)");
    expect(routeSource).toContain("listAgentSummaries<AgentConfigWorkspaceAgent>({ signal })");
    expect(routeSource).not.toContain("includeArchived=true&detail=summary");
    expect(routeSource).not.toContain('fetchJson<AgentConfigWorkspace>("/api/agents/config-workspace")');
    // Wave 8Q: archive/delete team lives on useTeamShellMutations.
    expect(teamShellMutationsSource).toContain("archiveTeam(teamId)");
    expect(teamShellMutationsSource).toContain("saveTeamCanvas(");
    expect(teamShellMutationsSource).toContain("sendTeamProjectBusMessage(payload)");
    // Kernel deep-links live on TeamCommunicationPanel after discussion/broadcast extraction.
    expect(teamCommunicationPanelSource).toContain("kernelTaskCenterHref");
    expect(routeSource).toContain("queryFn: ({ signal }) => listProjectAgentBusTimeline(PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT, { signal })");
    expect(teamShellMutationsSource).toContain("revokeProjectAgentBusMessage({");
    expect(teamShellMutationsSource).toContain("syncTeamChatRoom(teamId)");
    expect(routeSource).toContain("syncTeamChatRoomMutation");
    expect(teamShellMutationsSource).toContain("startChatRoomRound(payload.roomId, {");
    expect(routeSource).toContain("fetchChatRoomDetail(linkedChatRoomId, { signal })");
    expect(routeSource).toContain("enabled: linkedChatRoomQueryEnabled");
    expect(routeSource).toContain("linkedRoomRefetchInterval(pageVisible");
    expect(routeSource).toContain("latestChatRoomRound(linkedRoomDetail)");
    expect(researchWorkflowResourcesSource).toContain("fetchTeamWorkflowOrchestration(");
    expect(teamWorkflowApiSource).toContain("/workflow-orchestration");
    expect(researchWorkflowResourcesSource).toContain("fetchTeamWorkflowCandidates<");
    expect(teamExperimentApiSource).toContain("/workflow-orchestration/candidates");
    // Wave 8P: candidate-graph build fetch lives on useTeamSourceCollectionMutations.
    expect(teamSourceCollectionMutationsSource).toContain("buildCandidateGraph(");
    expect(researchWorkflowResourcesSource).toContain("fetchKnowledgeIngestionStatus(");
    expect(teamKnowledgeApiSource).toContain("/workflow-orchestration/knowledge-ingestion/status");
    expect(researchWorkflowResourcesSource).toContain("fetchOfficialModelEvidenceStatus<");
    expect(researchWorkflowResourcesSource).toContain("TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT");
    expect(researchWorkflowResourcesSource).toContain("TEAM_WORKFLOW_CANDIDATE_GRAPH_LIMIT");
    expect(routeSource).toContain("isResearchWorkflowTeam(selectedTeam)");
    expect(routeSource).toContain("researchWorkflowTeamSelected");
    expect(routeSource).toContain("teamWorkflowKnowledgeIngestionStatusQuery");
    expect(teamKnowledgeApiSource).toContain("/workflow-orchestration/knowledge-ingestion/status");
    expect(routeSource).toContain("teamWorkflowOfficialModelEvidenceStatusQuery");
    expect(teamResearchOpsApiSource).toContain("/workflow-orchestration/official-model-evidence/status");
    expect(researchWorkflowResourcesSource).toContain("fetchOfficialModelEvidenceStatus<");
    expect(researchWorkflowResourcesSource).toContain("TeamWorkflowSourceQualityStatus");
    expect(routeSource).toContain("teamWorkflowSourceQualityStatusQuery");
    expect(teamResearchOpsApiSource).toContain("/workflow-orchestration/source-quality/status");
    expect(researchWorkflowResourcesSource).toContain("fetchSourceQualityStatus<");
    // Wave 8P: SC quality/plan write endpoints live on useTeamSourceCollectionMutations.
    expect(teamResearchOpsApiSource).toContain("/source-quality/assess");
    expect(teamSourceCollectionMutationsSource).toContain("assessCandidateSourceQuality<");
    expect(routeSource).toContain("assessSourceQualityMutation");
    expect(routeSource).toContain("useTeamSourceCollectionMutations");
    expect(routeSource).toContain("candidateSourceQualityAssessmentSummary");
    expect(researchWorkflowResourcesSource).toContain("TeamWorkflowPaperNoteChunkStatus");
    expect(routeSource).toContain("teamWorkflowPaperNoteChunkStatusQuery");
    expect(teamResearchOpsApiSource).toContain("/workflow-orchestration/paper-note-chunks/status");
    expect(researchWorkflowResourcesSource).toContain("fetchPaperNoteChunkStatus<");
    expect(teamResearchOpsApiSource).toContain("/paper-note-chunks/plan");
    expect(teamSourceCollectionMutationsSource).toContain("planPaperNoteChunks<");
    expect(routeSource).toContain("planPaperNoteChunksMutation");
    expect(routeSource).toContain("sourceCandidateHasCompletedExtraction");
    expect(routeSource).toContain("candidatePaperNoteChunkPlanSummary");
    // Owned by research workflow resources + stageProjection type, not inlined in workbench.
    expect(researchWorkflowResourcesSource).toContain("ResearchStageRoundStatusPayload");
    expect(routeSource).toContain("researchStageRoundStatusQuery");
    expect(stageRoundsApiSource).toContain("/workflow-orchestration/stage-rounds/status");
    expect(researchWorkflowResourcesSource).toContain("fetchResearchStageRoundStatus<");
    expect(stageRoundsApiSource).toContain("/workflow-orchestration/stage-rounds/start");
    expect(teamWorkflowStartMutationsSource).toContain("startResearchStageRound<");
    expect(routeSource).toContain("startResearchStageRoundMutation");
    expect(routeSource).toContain("seedSourceCollectionAgentSessionContextMutation");
    expect(teamWorkflowStartMutationsSource).toContain("seedSourceCollectionAgentSessionContext(");
    expect(sourceCollectionApiSource).toContain("/source-collection-runs/${encodeURIComponent(runId)}/agent-session-context");
    expect(createSourceCollectionStageAgentHelpersSource).toContain("await seedSourceCollectionAgentSessionContextMutation.mutateAsync");
    // Payload type owned by workflow-start mutations module after import cleanup.
    expect(sourceCollectionApiSource).toContain("TeamWorkflowSourceCollectionStageSessionTaskPayload");
    expect(routeSource).toContain("startSourceCollectionStageSessionTaskMutation");
    expect(teamWorkflowStartMutationsSource).toContain("startSourceCollectionStageSessionTask(");
    expect(sourceCollectionApiSource).toContain("/source-collection-runs/${encodeURIComponent(runId)}/stage-session-tasks");
    expect(routeSource).toContain("createSourceCollectionStageAdvance");
    expect(sourceCollectionControllerSource).toContain("options: { formalRetry?: boolean }");
    expect(sourceCollectionControllerSource).toContain("resetResearchProjectSourceCollectionMutation.isPending");
    expect(sourceCollectionControllerSource).toContain("await startSourceCollectionStageSessionTaskMutation.mutateAsync");
    expect(sourceCollectionControllerSource).toContain("sourceCollectionStageTaskClickKey(stageId)");
    // Wave 8R: stage-session idempotency lives on useTeamWorkflowStartMutations.
    expect(teamWorkflowStartMutationsSource).toContain("idempotencyKey: payload.idempotencyKey");
    expect(sourceCollectionControllerSource).toContain("idempotencyKey: sourceCollectionStageTaskClickKey(stageId)");
    expect(teamSourceCollectionShellModelSource).toContain('ingestion: ["source_ingestor"]');
    expect(teamSourceCollectionShellModelSource).toContain("priorityByKey");
    // Experiment payload types live on experimentLoopModel after workbench import cleanup.
    expect(experimentLoopModelSource).toContain("ExperimentFullRunResultRegisterPayload");
    expect(experimentLoopModelSource).toContain("ExperimentResultKnowledgeIngestionPayload");
    // Wave 8O: experiment write endpoints live on useTeamExperimentLoopMutations.
    expect(teamExperimentApiSource).toContain("/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/full-run-result");
    expect(teamExperimentApiSource).toContain("/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/knowledge-ingestion-request");
    expect(teamExperimentLoopMutationsSource).toContain("registerTeamExperimentFullRunResult<");
    expect(teamExperimentLoopMutationsSource).toContain("requestTeamExperimentKnowledgeIngestion<");
    expect(routeSource).toContain("registerExperimentFullRunResultMutation");
    expect(routeSource).toContain("useTeamExperimentLoopMutations");
    expect(routeSource).toContain("requestExperimentKnowledgeIngestionMutation");
    // Wave 8J: full-run / knowledge-admin CTA copy lives on experiment ledger panel.
    expect(teamExperimentPlanningLedgerPanelSource).toContain("登记 full-run");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("通知知识库管理员");
    // Wave 8O: full-run / knowledge-ingestion metadata lives on experiment-loop mutations hook.
    expect(teamExperimentLoopMutationsSource).toContain("manualFullRunResult: true");
    expect(teamExperimentLoopMutationsSource).toContain("explicitUserBoundary: true");
    expect(teamExperimentLoopMutationsSource).toContain("stewardReviewRequired: true");
    expect(routeStylesSource).toContain(".experimentKnowledgePanel");
    expect(routeStylesSource).toContain(".experimentKnowledgeForm");
    expect(experimentLoopModelSource).toContain("ResearchLoopStatusPayload");
    expect(routeSource).toContain("researchLoopTemplatesQuery");
    expect(routeSource).toContain("researchLoopStatusQuery");
    // Wave 8S: research-loop status/templates live on useTeamResearchSecondaryQueries.
    expect(researchLoopApiSource).toContain("/workflow-orchestration/research-loop/templates");
    expect(researchLoopApiSource).toContain("/workflow-orchestration/research-loop/status");
    expect(teamResearchSecondaryQueriesSource).toContain("fetchResearchLoopTemplates<");
    expect(teamResearchSecondaryQueriesSource).toContain("fetchResearchLoopStatus<");
    expect(researchLoopApiSource).toContain("/workflow-orchestration/research-loop/loops");
    expect(researchLoopApiSource).toContain("/evidence");
    expect(researchLoopApiSource).toContain("/decision");
    expect(teamExperimentLoopMutationsSource).toContain("createResearchLoop<");
    expect(teamExperimentLoopMutationsSource).toContain("recordResearchLoopEvidence<");
    expect(teamExperimentLoopMutationsSource).toContain("recordResearchLoopDecision<");
    expect(routeSource).toContain("createResearchLoopMutation");
    expect(routeSource).toContain("recordResearchLoopEvidenceMutation");
    expect(routeSource).toContain("recordResearchLoopDecisionMutation");
    expect(teamExperimentLoopMutationsSource).toContain("createNextDesignDraft:");
    expect(teamExperimentLoopMutationsSource).toContain("idempotencyKey: buildResearchLoopDecisionIdempotencyKey({");
    // Wave 8J: research-loop UI + design-draft CTA live on TeamResearchLoopPanel.
    expect(teamResearchLoopPanelSource).toContain("nextDesignPlanId");
    expect(teamResearchLoopPanelSource).toContain("已生成下一版设计");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("进入执行与迭代");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("openIterationWorkspace");
    expect(routeSource).toContain('researchWorkspaceStageRoute(selectedTeam.teamId, "iteration")');
    expect(routeSource).toMatch(/experimentMethodCatalogQuery\?\.refetch|experimentMethodCatalogQuery\.refetch/);
    expect(routeSource).toMatch(/researchLoopStatusQuery\?\.refetch|researchLoopStatusQuery\.refetch/);
    expect(routeSource).toMatch(/createExperimentPlanMutation\?\.reset|createExperimentPlanMutation\.reset/);
    expect(routeSource).toContain("freezeExperimentDesignMutation");
    expect(teamExperimentApiSource).toContain("/freeze");
    expect(teamExperimentLoopMutationsSource).toContain("freezeTeamExperimentDesign<");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("冻结设计");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("designExecutionAllowed");
    expect(routeSource).toContain("materializeResearchLoopIterationDesignMutation");
    expect(teamResearchLoopPanelSource).toContain("pendingDesignProposals");
    expect(teamResearchLoopPanelSource).toContain("生成设计草稿");
    expect(teamResearchLoopPanelSource).toContain("生成后仍需人工冻结，不会自动执行实验。");
    expect(teamResearchLoopPanelSource).toContain("允许变化路径");
    expect(teamResearchLoopPanelSource).toContain("固定控制项");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("缺少允许变化路径或固定控制项");
    expect(routeSource).toContain("renderResearchLoopPanel");
    expect(routeSource).toContain("TeamResearchLoopPanel");
    expect(teamResearchLoopPanelSource).toContain("Research Loop 模板");
    expect(teamResearchLoopPanelSource).toContain("实验迭代决策");
    expect(teamResearchLoopPanelSource).toContain("historicalEmptyLoops");
    expect(teamResearchLoopPanelSource).toContain("历史空轮次");
    expect(teamResearchLoopPanelSource).toContain("currentLoopCount");
    expect(teamExperimentLoopMutationsSource).toContain("noSandboxRunner: true");
    expect(teamExperimentLoopMutationsSource).toContain("noTrainingExecution: true");
    expect(teamExperimentLoopMutationsSource).toContain("commandPreviewOnly: true");
    expect(routeSource).toContain("startSourceCollectionRunMutation");
    expect(routeSource).toContain("knowledgeExpansionWorkflowTeamSelected");
    expect(routeAndPureSource).toContain("SOURCE_COLLECTION_KNOWLEDGE_EXPANSION_ROLES");
    expect(routeSource).toMatch(/from "\.\/(?:teams\/)?teamKindModel"/);
    expect(routeSource).toContain("source_finder");
    expect(teamWorkflowStartMutationsSource).toContain("collectionMode");
    expect(teamSourceCollectionInjectModelSource).toContain("local_workspace");
    expect(teamSourceCollectionModeFieldsSource).toContain("TeamSourceCollectionModeFields");
    expect(routeSource).toContain("TeamSourceCollectionModeFields");
    expect(presentationModelSource).toContain('collectionMode: "mixed"');
    // Wave 8R: SC run start payload fields live on useTeamWorkflowStartMutations.
    expect(teamWorkflowStartMutationsSource).toContain("localScanScope");
    expect(teamWorkflowStartMutationsSource).toContain("workflowPurpose");
    expect(teamWorkflowStartMutationsSource).toContain("workflowKind");
    expect(teamWorkflowStartMutationsSource).toContain("resetTeamResearchProjectSourceCollection");
    expect(teamWorkflowStartMutationsSource).toContain("researchProjectId: options.activeSourceCollectionResearchProjectId");
    expect(routeSource).toContain("sourceCollectionFreshProjectDraft");
    // Project reset buttons live under the right-rail stage card (not left search brief).
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("清空本项目资料并重新开始");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("连同实验与迭代一起清空");
    expect(teamSourceCollectionSearchBriefShellSource).not.toContain("清空本项目资料并重新开始");
    expect(routeSource).toContain("includeDownstream");
    expect(routeSource).toContain("runSourceCollectionProjectReset");
    expect(routeSource).toContain("ResearchOverviewSurface");
    expect(routeSource).toContain("ResearchWorkflowErrorSurface");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("ResearchWorkflowErrorSurface");
    expect(routeSource).toContain("getTeamResearchProjectProgress");
    expect(routeSource).toContain("renderResearchOverviewSurface");
    expect(routeSource).toContain('presentationMode');
    expect(routeSource).toContain("recordSourceCollectionOutputMutation");
    expect(routeSource).toContain("executeSourceCollectionSearchMutation");
    // Wave 8P: execute/extract/writeback mutations live on useTeamSourceCollectionMutations.
    const executeSearchMutationSource = teamSourceCollectionMutationsSource.slice(
      teamSourceCollectionMutationsSource.indexOf("const executeSourceCollectionSearchMutation"),
      teamSourceCollectionMutationsSource.indexOf("const extractSourceCollectionCandidatesMutation"),
    );
    expect(executeSearchMutationSource).toContain("researchStageRoundStatusQueryKey(variables.teamId)");
    expect(sourceCollectionApiSource).toContain("/workflow-orchestration/source-collection-runs");
    expect(teamWorkflowStartMutationsSource).toContain("startSourceCollectionRun(");
    expect(sourceCollectionApiSource).toContain("/search/execute");
    expect(teamSourceCollectionMutationsSource).toContain("executeSourceCollectionSearch<");
    expect(dataProcessingApiSource).toContain("/api/data-processing/runs?");
    expect(useSourceCollectionWorkspaceSource).toContain("listDataProcessingRuns(");
    expect(useSourceCollectionWorkspaceSource).toContain("limit: SOURCE_COLLECTION_RUN_PREVIEW_LIMIT");
    expect(dataProcessingApiSource).toContain("/collection-assignments/${encodeURIComponent(assignmentId)}/outputs");
    expect(teamSourceCollectionMutationsSource).toContain("recordDataProcessingCollectionOutput<");
    expect(sourceCollectionApiSource).toContain("/source-candidate");
    expect(teamSourceCollectionMutationsSource).toContain("importDataRecordAsSourceCandidate(");
    expect(routeSource).toContain("sourceCollectionRunsForTeam");
    expect(routeSource).toContain("sourceCollectionRunHasUsableRecords");
    expect(routeSource).toContain("selectDefaultSourceCollectionRun");
    expect(routeSource).not.toContain("function sourceCollectionRunMetric");
    expect(routeSource).not.toContain("export function sourceCollectionRunRecordCount");
    expect(runModelSource).toContain("function sourceCollectionRunMetric");
    expect(runModelSource).toContain("export function selectDefaultSourceCollectionRun");
    expect(routeSource).toContain("sourceCollectionHistoricalRunWithRecords");
    expect(routeSource).toContain("sourceCollectionLatestRunIsEmpty");
    expect(routeSource).toContain("renderSourceCollectionRunSwitcher");
    expect(routeSource).toContain("TeamSourceCollectionRunSwitcherInject");
    expect(routeSource).toContain("onRunChange={setSelectedSourceCollectionRunId}");
    expect(teamSourceCollectionRunSwitcherPanelSource).toContain("sourceCollectionRunSwitcher");
    expect(teamSourceCollectionRunSwitcherPanelSource).toContain("sourceCollectionRunSwitcherMain");
    expect(teamSourceCollectionRunSwitcherPanelSource).toContain("sourceCollectionRunSwitcherStats");
    expect(teamSourceCollectionRunSwitcherPanelSource).toContain("VTooltip");
    expect(teamSourceCollectionRunSwitcherPanelSource).not.toContain("<small>{hint}</small>");
    // Option mapping + empty-run hints live on runModel / inject.
    expect(runModelSource).toContain("buildSourceCollectionRunSwitcherOptions");
    expect(runModelSource).toContain("resolveSourceCollectionRunSwitcherHint");
    // Wave 8K: raw-record empty-state copy lives on conversation workspace panel.
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("TeamSourceEmptyState");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("rawRecordEmptyFacts");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("rawRecordEmptyActions");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("请在右侧「推荐下一步」推进搜集");
    expect(teamSourceCollectionConversationWorkspacePanelSource).not.toContain("findingStageActionLabel");
    expect(routeSource).not.toContain("sourceCollectionEmptyRunNotice");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("当前批次暂无资料");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("上一轮有资料");
    expect(teamSourceCollectionRunSwitcherPanelSource).toContain("切换到有资料批次");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("还没有开始资料搜集");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("文件产物");
    expect(routeSource).toContain("TeamSourceCollectionStorageActionsInject");
    expect(teamSourceCollectionStorageActionsInjectSource).toContain("TeamSourceCollectionStorageActionsPanel");
    expect(teamSourceCollectionStorageActionsInjectSource).toContain("run_directory");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("workflowSourceCollectionStorageActions");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("workflowSourceCollectionStorageButtons");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("workflowSourceCollectionStorageDetails");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("本轮产物");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("更多证据文件");
    expect(routeSource).toContain("SOURCE_COLLECTION_DEFAULT_ROLES");
    expect(researchWorkflowResourcesSource).toContain('candidateType: "candidate_graph"');
    expect(researchWorkflowResourcesSource).toContain("fetchTeamWorkflowCandidates<");
    expect(teamExperimentApiSource).toContain("/workflow-orchestration/candidates");
    // Wave 8P: candidate-graph write endpoint lives on useTeamSourceCollectionMutations.
    expect(teamKnowledgeApiSource).toContain("/workflow-orchestration/candidate-graph");
    expect(teamSourceCollectionMutationsSource).toContain("buildCandidateGraph(");
    expect(routeSource).toContain("buildCandidateGraphMutation");
    expect(teamShellMutationsSource).toContain('source: "team_workspace"');
    // Wave 8Q: team round + room membership cache live on shell mutations / remaining route selects.
    expect(teamShellMutationsSource).toContain("teamId: payload.teamId");
    expect(routeSource).toContain("startTeamRoundMutation");
    expect(routeSource).toContain("useTeamShellMutations");
    expect(routeSource).toContain("useTeamWorkflowStartMutations");
    expect(teamShellMutationsSource).toContain("chatWorkspaceCache.afterTeamRoomMembershipChanged(variables.teamId, room.roomId)");
    expect(teamShellMutationsSource).toContain("chatWorkspaceCache.afterTeamRoomMembershipChanged(team.teamId, team.linkedChatRoom.roomId)");
    expect(routeSource).toContain("selectedTeam?.conversation");
    expect(routeSource).toContain("isAiSearchScopeTeam(selectedTeam)");
    expect(routeSource).toContain("showAiSearchScopePanel");
    expect(routeSource).toContain("renderAiSearchSourceScopePanel");
    expect(routeSource).toContain("TeamAiSearchWorkspacePanel");
    expect(routeSource).toContain("selectedTeam?.sourceScope");
    expect(routeSource).toContain("AiSearchRunListPayload");
    expect(routeSource).toContain("queryKeys.teamAiSearchRuns");
    expect(routeSource).toContain("listTeamAiSearchRuns(effectiveTeamId, {");
    expect(teamWorkflowStartMutationsSource).toContain("startAiSearchRun(payload.teamId");
    expect(routeSource).toContain("startAiSearchRunMutation");
    expect(routeSource).toContain("aiSearchRunTopic");
    // Wave 8G: AI Search copy lives in TeamAiSearchWorkspacePanel.
    expect(teamAiSearchWorkspacePanelSource).toContain("主题 -> 可信来源 -> 摘要/引用 -> 运行记录");
    expect(teamAiSearchWorkspacePanelSource).toContain("结论需一手证据");
    expect(teamAiSearchWorkspacePanelSource).toContain("默认启用");
    expect(teamAiSearchWorkspacePanelSource).toContain("线索");
    expect(teamAiSearchWorkspacePanelSource).toContain("白名单、去重、存储路径");
    expect(teamAiSearchWorkspacePanelSource).toContain("启动一键搜索");
    expect(teamAiSearchWorkspacePanelSource).toContain("最近搜索结果");
    expect(routeSource).toContain("latestAiSearchRun");
    expect(teamShellMutationsSource).toContain("saveTeamCanvas(nextCanvas)");
    expect(routeSource).toContain("成员源");
    expect(routeSource).toContain("Member source");
    expect(routeSource).toContain("Agent Center");
    expect(routeSource).toContain("teamCanvasNodeAgentSourceRoute");
    expect(routeSource).toContain("writableTeamCanvas(nextCanvas)");
    expect(researchStageAgentPresentationSource).toContain("delete writableNode.agentSourceRef");
    expect(researchStageAgentPresentationSource).toContain("delete writableNode.agentProjectionEdit");
    expect(researchStageAgentPresentationSource).toContain("delete writableNode.agentProjectionCanWrite");
    // The canonical kind belongs to the canvas-data owner, not the route shell.
    expect(canvasDataSource).toContain("TEAM_ORGANIZATION_CANVAS_KIND");
    expect(canvasDataSource).toContain("team_organization_canvas");
    expect(routeSource).not.toContain("/api/research/flow-canvas");
  });

  it("extracts the research source-collection workspace through a route-local wrapper", () => {
    // Stage SC panel is composed via TeamResearchWorkflowStageModules (eager import of wrapper).
    expect(teamResearchWorkflowStageModulesSource).toContain("TeamsSourceCollectionPanel");
    expect(routeSource).toContain("TeamResearchWorkflowStageModules");
    // Wave 8N: path-scoped secondary packs (shared / research / source-collection).
    expect(routeSource).toMatch(/from "\.\/?(\.\.\/)?teams\/teamLazyPanels"|from "\.\/teamLazyPanels"/);
    expect(teamLazyPanelsSource).toContain('import("./teamSharedPanels")');
    expect(teamLazyPanelsSource).toContain('import("./teamResearchPanels")');
    expect(teamLazyPanelsSource).toContain('import("./teamResearchExperimentPanels")');
    expect(teamLazyPanelsSource).toContain('import("./teamResearchSearchPanels")');
    expect(teamLazyPanelsSource).toContain('import("./teamResearchWorkflowPanels")');
    expect(teamLazyPanelsSource).toContain("loadTeamResearchExperimentPanels");
    expect(teamLazyPanelsSource).toContain("loadTeamResearchSearchPanels");
    expect(teamLazyPanelsSource).toContain("loadTeamResearchWorkflowPanels");
    expect(teamLazyPanelsSource).toContain('createLazyNamedTeamPanel(loadTeamResearchSearchPanels, "TeamAiSearchWorkspacePanel")');
    expect(teamLazyPanelsSource).toContain('createLazyNamedTeamPanel(loadTeamResearchExperimentPanels, "TeamExperimentPlanningLedgerPanel")');
    expect(teamLazyPanelsSource).toContain('createLazyNamedTeamPanel(loadTeamResearchWorkflowPanels, "ResearchRunLaunchPanel")');
    expect(teamLazyPanelsSource).toContain('import("./teamSourceCollectionPanels")');
    expect(teamLazyPanelsSource).toContain('createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamsSourceCollectionPanel")');
    // Wave 8N+prefetch: warm packs after team/view switch, not mount-all.
    expect(routeSource).toContain("resolveTeamsPanelPrefetchPacks");
    expect(routeSource).toContain("prefetchTeamsPanelPacks");
    expect(routeSource).toContain("sourceCollectionWorkspaceSelected");
    expect(teamsSourceCollectionPanelSource).toContain("TeamSourceCollectionOverviewPanel");
    expect(teamsSourceCollectionPanelSource).not.toContain("TeamsRoute.styles");
    expect(teamsSourceCollectionPanelSource).not.toContain("useQuery");
    expect(teamsSourceCollectionPanelSource).not.toContain("useMutation");
  });

  it("can deep-link from Agent references to a selected Team", () => {
    expect(routeSource).toContain("useSearchParams");
    expect(routeSource).toContain('searchParams.get("teamId")');
    expect(routeSource).toContain('searchParams.get("agent")');
    expect(routeSource).toContain('searchParams.get("researchView")');
    expect(routeSource).toContain("parseResearchWorkspaceView");
    expect(routeSource).toContain("requestedAgentTeamId");
    // R2-h: team deep-link param writes live in createTeamsResearchNavigation.
    expect(createTeamsResearchNavigationSource).toContain('nextParams.set("teamId", effectiveTeamId)');
    expect(createTeamsResearchNavigationSource).toContain('nextParams.set("teamMode", "canvas")');
    expect(createTeamsResearchNavigationSource).toContain('nextParams.set("teamMode", "board")');
  });

  it("exposes Team and member Agent memory deep links from the Team workspace", () => {
    expect(routeSource).toContain("teamMemoryRoute");
    expect(routeSource).toContain("agentCenterMemoryRoute");
    expect(routeSource).toContain("selectedTeamReturnRoute");
    expect(routeSource).toContain("selectedTeamKnowledgeRoute");
    expect(routeSource).toContain("selectedTeamGraphRoute");
    expect(routeSource).toContain("selectedTeamMemoryMembers: TeamMemoryIndexMember[]");
    expect(routeSource).toContain("renderTeamMemoryIndex()");
    expect(routeSource).toContain("<TeamMemoryIndexPanel");
    expect(routeSource).toContain("members={selectedTeamMemoryMembers}");
    expect(routeSource).toContain("knowledgeRoute={selectedTeamKnowledgeRoute}");
    expect(routeSource).toContain("graphRoute={selectedTeamGraphRoute}");
    expect(teamMemoryIndexPanelSource).toContain("styles.teamMemoryIndex");
    expect(teamMemoryIndexPanelSource).toContain("styles.teamMemoryMemberTable");
    expect(teamMemoryIndexPanelSource).toContain("styles.teamMemoryMemberHeading");
    expect(teamMemoryIndexPanelSource).toContain("styles.teamMemoryActionRail");
    expect(teamMemoryIndexPanelSource).toContain("团队记忆索引");
    expect(teamMemoryIndexPanelSource).toContain("团队知识库");
    expect(teamMemoryIndexPanelSource).toContain("团队记忆图谱");
    expect(teamMemoryIndexPanelSource).toContain("职责");
    expect(teamMemoryIndexPanelSource).toContain("入口");
    expect(routeSource).not.toContain("跳转到团队知识、图谱和成员 Agent 私有记忆");
    expect(routeSource).toContain('view: "agents"');
    expect(routeSource).toContain('view: "knowledge"');
    expect(routeSource).toContain('view: "graph"');
    expect(routeSource).toContain("teamId: selectedTeam.teamId");
    expect(routeSource).toContain("teamId: selectedTeam?.teamId");
    // Full-height board shell: memory index stretches with the pane (not content-sized).
    expect(routeStyles.teamMemoryIndex).toContain("flex-1");
    expect(routeStyles.teamMemoryIndex).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(routeStyles.teamMemoryMemberTable).toContain("grid-cols-[minmax(0,1fr)]");
    expect(routeStyles.teamMemoryMemberTable).toContain("overflow-auto");
    expect(routeStyles.teamMemoryMemberTable).not.toContain("repeat(auto-fit");
    expect(routeStyles.teamMemoryMemberTable).not.toContain("repeat(auto-fill");
    expect(routeStyles.teamMemoryMemberCard).toMatch(/bg-vui-surface-row|bg-\[var\(--vui-surface-row\)\]/);
    expect(routeStyles.teamMemoryMemberCard).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(routeStyles.teamMemoryMemberCard).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(teamMemoryIndexPanelStyles.teamMemoryIndex).toContain("flex-1");
    expect(teamMemoryIndexPanelStyles.teamMemoryIndex).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberTable).toContain("grid-cols-[minmax(0,1fr)]");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberTable).toContain("overflow-auto");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberTable).not.toContain("repeat(auto-fit");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberTable).not.toContain("repeat(auto-fill");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberCard).toMatch(/bg-vui-surface-row|bg-\[var\(--vui-surface-row\)\]/);
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberCard).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberCard).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(routeStylesSource).toContain(".teamMemoryMemberTable");
    expect(routeStylesSource).toContain(".teamMemoryMemberHeading");
    expect(routeStylesSource).toContain(".teamMemoryActionRail");
    expect(routeStyles.teamMemoryMemberHeading).toContain("sr-only");
    expect(routeStyles.teamMemoryMemberCard).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(routeStyles.teamMemoryMemberMain).toContain("teamMemoryMemberMain");
    expect(routeStyles.teamMemoryMemberActions).toContain("[&_a]:min-h-7");
    expect(routeStyles.teamMemoryActionRail).toContain("[&_a]:inline-flex");
    expect(teamMemoryIndexPanelSource).toContain("styles.teamMemoryMemberMain");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberCard).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberHeading).toContain("sr-only");
  });

  it("distinguishes Agent-directory hydration from a missing Team binding in the memory index", () => {
    expect(routeSource).toContain("const memoryIndexAgentHydrationPending = Boolean(");
    expect(routeSource).toContain("const memoryIndexAgentLoadFailed = Boolean(");
    expect(routeSource).toContain('lang === "zh" ? "正在读取 Agent 目录" : "Loading Agent directory"');
    expect(routeSource).toContain('lang === "zh" ? "Agent 目录加载失败" : "Agent directory load failed"');
    expect(routeSource).toContain('lang === "zh" ? "Agent 引用失效" : "Agent reference missing"');
    expect(routeSource).not.toContain("statusLabel: researchStageAgentConfigStatusLabel(agent, lang)");
  });

  it("keeps the research overview on a readable workbench surface instead of a transparent card wall", () => {
    // Shell: board/canvas page recipes + panel fill.
    expect(routeStyles.teamShellWorkspace).toContain("!flex");
    expect(routeStyles.teamShellContentBoard).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(routeStyles.teamShellMain).toContain("flex-col");
    expect(routeSource).toContain("VBoardWorkbenchPage");
    expect(routeSource).toContain("VCanvasWorkbenchPage");

    expect(routeStyles.researchStageLauncher).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(routeStyles.researchStageLauncher).toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.researchStageLauncher).toContain("grid");
    expect(routeStyles.researchStageLauncher).toContain("gap-3");

    expect(routeStyles.teamMemoryIndex).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(routeStyles.teamMemoryIndex).toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.teamMemoryMemberTable).toContain("grid-cols-[minmax(0,1fr)]");
    expect(routeStyles.teamMemoryMemberTable).not.toContain("repeat(auto-fit");
    expect(routeStyles.teamMemoryMemberCard).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(routeStyles.teamMemoryMemberCard).not.toContain("minmax(10rem,1.1fr)");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberTable).toContain("grid-cols-[minmax(0,1fr)]");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberTable).not.toContain("repeat(auto-fit");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberCard).toContain("grid-cols-[minmax(0,1fr)_auto]");
  });

  it("keeps only the fixed research and AI search teams in the picker", () => {
    expect(teamKindModelSource).toContain("EVOLUTION_SYSTEM_TEAM_IDS");
    expect(teamKindModelSource).toContain('"self-evolution-team"');
    expect(teamKindModelSource).toContain('"supervised-evolution-team"');
    expect(canvasDataSource).toContain('RESEARCH_TEAM_ID = "research-team"');
    expect(canvasDataSource).toContain('AI_SEARCH_TEAM_ID = "ai-search-team"');
    expect(canvasDataSource).toContain('KNOWLEDGE_EXPANSION_TEAM_ID = "knowledge-expansion-team"');
    expect(routeSource).toContain("TEAM_PICKER_TEAM_IDS.map((teamId) => teamsById.get(teamId))");
    expect(routeAndPureSource).toContain("isEvolutionSystemTeam");
    expect(teamKindModelSource).toContain('team.teamKind === "self_evolution"');
    expect(teamKindModelSource).toContain('team.teamKind === "supervised_evolution"');
    expect(teamKindModelSource).toContain('team.teamSource === "self_evolution"');
    expect(teamKindModelSource).toContain('team.teamSource === "supervised_evolution"');
    // R2-d: picker derivation lives in useTeamsCatalogQueries (formatting may wrap useMemo).
    expect(useTeamsCatalogQueriesSource).toContain("const visibleTeamIds = useMemo");
    expect(useTeamsCatalogQueriesSource).toContain("new Set(visibleTeams.map((team) => team.teamId))");
    expect(routeSource).toContain("requestedVisibleTeamId");
    expect(routeSource).toContain("requestedVisibleAgentTeamId");
    expect(routeSource).toContain("selectedVisibleTeamId");
    expect(routeSource).toContain("fallbackVisibleTeamId");
    expect(routeSource).toContain("visibleTeamIds.has(RESEARCH_TEAM_ID)");
    expect(routeSource).toContain("const hasTeams = visibleTeams.length > 0");
    expect(routeSource).toContain("visibleTeamSummary.activeTeamCount");
    expect(routeSource).toMatch(/visibleTeams\.map\(\(team(?::[^\)]*)?\) => \(/);
    expect(routeSource).toContain("TeamShellStatusRail");
    expect(routeSource).toContain("visibleTeams.find((item) => item.teamId === teamId)");
    expect(routeSource).not.toContain("{teams.map((team) => (");
    expect(routeSource).not.toContain("teams[0]?.teamId");
  });

  it("renders a dense list canvas inspector workflow", () => {
    expect(routeSource).toContain("VDenseOpsPage");
    expect(routeSource).toContain("VNativeButton");
    // Form selects live in extracted panels (VStringSelect); shell keeps dense native buttons.
    expect(routeSource).not.toContain("VNativeSelect");
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
    expect(routeSource).toContain("challengeWorkspaceContextHidden");
    expect(routeStyles.teamContextBar).toBeTypeOf("string");
    // Team pick lives in TeamShellToolbar VSelect, not a left-rail team list.
    expect(teamShellToolbarSource).toContain("VSelect");
    expect(routeSource).toContain("TeamShellStatusRail");
    expect(routeSource).toContain("teamRefreshButton");
    expect(routeSource).toContain("selectedTeamContextTitle");
    expect(routeSource).toContain("成员源");
    expect(routeSource).toContain("Member source");
    expect(routeSource).not.toContain("teamPickerPanel");
    expect(routeSource).not.toContain("teamSwitcherBar");
    expect(routeSource).not.toContain("teamPickerLabel");
    expect(routeSource).not.toContain("teamPickerSummary");
    expect(routeSource).not.toContain("summaryBar");
    expect(routeSource).toContain("TeamShellStatusRail");
    expect(routeSource).not.toContain("<select\n            value={selectedTeam?.teamId ?? effectiveTeamId}");
    expect(routeSource).not.toContain("className={styles.teamPanel}");
    expect(routeSource).toContain("canvasPanel");
    expect(routeSource).toContain("inspector");
    expect(routeSource).toContain("hasTeams");
    expect(routeSource).toContain("showTeamInitialLoadingSurface");
    expect(routeSource).toContain("showTeamUnavailableSurface");
    expect(routeSource).toContain("teamListInitialLoading");
    // R2-b: shell flags live in teamsShellSurfaceModel (still exact assignment form).
    expect(routeSource).toContain("const showTeamInitialLoadingSurface = teamListInitialLoading");
    expect(routeSource).toContain("const showTeamUnavailableSurface = !teamListInitialLoading && !hasTeams");
    expect(routeSource).toContain("buildTeamsShellSurfaceModel");
    expect(routeSource).toContain("teamContextMeta");
    expect(routeSource).toContain("styles.teamUnavailableSurface");
    expect(routeSource).toContain("teamListUnavailable");
    expect(routeSource).toContain("团队数据不可用");
    expect(routeSource).toContain("正在读取团队");
    expect(routeSource).toContain("团队尚未初始化");
    expect(routeSource).not.toContain("styles.workspaceEmpty");
    expect(routeSource).toContain("showTeamInitialLoadingSurface");
    expect(routeSource).toContain('mode={');
    expect(routeSource).toContain("showTeamUnavailableSurface");
    expect(routeSource).toContain("<TeamsLoadingShell lang={lang} />");
    expect(useTeamsWorkbenchModelSource).toContain("fallback={<TeamsLoadingShell");
    expect(teamsLoadingShellSource).toContain("VBoardWorkbenchPage");
    expect(teamsLoadingShellSource).toContain("TEAMS_LAYOUT_ID");
    expect(teamsLoadingShellSource).toContain('shellMode="loading"');
    expect(teamsLoadingShellSource).toContain('role="status"');
    expect(teamsLoadingShellSource).toContain('aria-live="polite"');
    expect(teamsLoadingShellSource).toContain('aria-busy="true"');
    expect(teamsLoadingShellSource).toContain("VSkeleton");
    expect(teamsLoadingShellSource).toContain(
      "narrow ? undefined : <LoadingInspector lang={lang} />",
    );
    expect(teamsShellGateSurfaceSource).not.toContain('mode === "initial-loading"');
    expect(teamsShellGateSurfaceSource).not.toContain("<VLoadingValue");
    // Gate surface: list unavailable tone (TeamsShellGateSurface).
    expect(routeSource).toMatch(/tone=\{(?:props\.)?listUnavailable \? "error" : "empty"\}|tone=\{teamListUnavailable \? "error" : "empty"\}/);
    expect(routeSource).toMatch(/TeamsShellGateSurface|renderTeamsShellGate/);
    expect(routeSource).not.toContain('gateMode: "initial-loading"');
    expect(renderTeamsShellFrameSource).toContain('role="status"');
    expect(renderTeamsShellFrameSource).toContain("args.teamsFetching");
    // Board main: research overview progressive shell (stable IA + in-place skeleton),
    // not a full-region fill "正在读取" surface and not styles.empty one-liner.
    expect(teamResearchBoardPrimarySurfaceSource).not.toContain("正在读取科研总览");
    expect(teamResearchBoardPrimarySurfaceSource).not.toContain("Loading research overview");
    expect(teamResearchBoardPrimarySurfaceSource).toContain("workflowPending || workflowReady");
    expect(teamResearchBoardPrimarySurfaceSource).toContain("fill");
    expect(routeSource).toContain("TeamResearchBoardPrimarySurface");
    expect(routeSource).toContain("loading: overviewWorkflowPending");
    expect(routeSource).toContain("fill");
    expect(routeSource).toContain("styles.emptyCanvasPanel");
    expect(routeSource).not.toContain("选择团队后进入对应工作区");
    expect(routeSource).not.toContain("顶部只保留 AI 搜索范围团队和 挑战杯ai科研团队 两个入口");
    expect(routeSource).toContain("暂无可用团队。请确认 AI 搜索范围团队和 挑战杯ai科研团队 已初始化。");
    expect(routeSource).not.toContain("teamNameInputRef");
    expect(routeSource).not.toContain("从模板创建");
    expect(routeSource).not.toContain("创建 Demo 团队");
    expect(routeSource).not.toContain("selectedTemplate.chatRoom.mode");
    expect(routeSource).not.toContain("styles.templatePanel");
    expect(routeSource).not.toContain("styles.templatePicker");
    expect(routeSource).not.toContain("styles.templateSelect");
    expect(routeSource).not.toContain("styles.templatePreview");
    expect(routeSource).not.toContain("styles.templateCard");
    expect(routeSource).not.toContain("先填写团队名称，再创建团队。");
    expect(routeSource).not.toContain("styles.formError");
    expect(routeSource).not.toContain("styles.formHint");
    expect(routeSource).toContain("暂无画布数据");
    expect(routeSource).toContain("等待数据");
    expect(routeSource).toContain("styles.nodeBindingSection");
    expect(routeSource).toContain("styles.nodeBindingPlaceholder");
    expect(routeSource).toContain("styles.nodeSourceAuthority");
    expect(routeSource).toContain("Agent 身份只读投影");
    expect(routeSource).toContain("Read-only Agent identity");
    expect(routeSource).toContain("到 AgentDirectory 源配置修改");
    expect(routeSource).toContain("selectedNode.agentSourceRef?.owner");
    expect(routeSource).toContain("teamCanvasNodeAgentSourceRoute");
    expect(routeSource).toContain("agentSourceRoute");
    expect(routeSource).toContain("正在读取团队节点");
    expect(routeSource).toContain("agentTeamMembership");
    expect(routeSource).toContain("membership.teamId !== selectedTeam.teamId");
    // Radix VStringSelect options use `disabled:` on option objects (not native option attr).
    expect(routeSource).toContain("disabled: ownedByOtherTeam");
    expect(routeSource).toContain("<VStringSelect");
    expect(routeSource).toContain("已属于");
    expect(routeSource).toContain("接入主干");
    expect(routeSource).toContain("保存节点");
    expect(routeSource).toContain("归档");
    expect(teamKindModelSource).toContain("function isSystemManagedTeam");
    expect(routeAndPureSource).toContain("systemManagedTeamArchiveReason");
    expect(teamKindModelSource).toContain("系统团队由工作流自动维护，不能在这里归档。");
    // Keep the toolbar label short; the system-team lock reason stays on title/disabled path.
    expect(routeSource).toContain('{lang === "zh" ? "归档" : "Archive"}');
    expect(routeSource).not.toContain("系统团队不可归档");
    expect(routeSource).toContain("解绑节点");
    expect(routeSource).toContain("删除节点");
    // Discussion/broadcast chrome extracted to TeamCommunicationPanel.
    expect(teamCommunicationPanelSource).toContain("团队任务");
    expect(teamCommunicationPanelSource).toContain("启动团队讨论");
    expect(routeSource).toContain("teamTaskTopic");
    expect(routeSource).toContain("linkedRoomBusy");
    expect(teamCommunicationPanelSource).toContain("最近团队任务");
    expect(teamCommunicationPanelSource).toContain("styles.teamRoundPanel");
    expect(teamCommunicationPanelSource).toContain("styles.teamRoundCard");
    expect(teamCommunicationPanelSource).toContain("查看完整群聊");
    expect(teamCommunicationPanelSource).toContain("styles.teamTaskForm");
    expect(routeSource).toContain("TeamCommunicationPanel");
    // Workflow section chrome extracted to TeamResearchWorkflowPanelHost.
    expect(teamResearchWorkflowPanelHostSource).toContain("科研流程");
    expect(teamResearchWorkflowPanelHostSource).toContain("Research workflow");
    expect(routeSource).toContain("createResearchWorkflowSurfaceRenderers");
    expect(routeSource).toContain("teamWorkflowQuery");
    expect(routeSource).toContain("teamWorkflowCandidatesQuery");
    expect(routeSource).toContain("teamWorkflowValidationSummary");
    expect(routeSource).toContain("teamWorkflowKnowledgeIngestionStatus");
    expect(routeSource).toContain("teamWorkflowOfficialModelEvidenceStatus");
    expect(routeSource).toContain("workflowStateLabel");
    expect(routeSource).toContain("workflowQualityTone");
    expect(routeSource).toContain("workflowIngestionStatusLabel");
    expect(routeSource).toContain("workflowIngestionTone");
    expect(teamResearchWorkflowPanelHostSource).toContain("styles.workflowPanel");
    expect(routeSource).toContain("TeamWorkflowModelEvidenceStatusPanel");
    expect(teamResearchWorkflowStageModulesSource).toContain("TeamWorkflowCoordinationStatusPanel");
    expect(teamResearchWorkflowStageModulesSource).toContain("TeamWorkflowKnowledgeIngestionStatusPanel");
    expect(teamResearchWorkflowStageModulesSource).toContain("TeamWorkflowCandidateGraphStatusPanel");
    expect(teamResearchWorkflowStageModulesSource).toContain("TeamWorkflowSourceQualityStatusPanel");
    expect(teamResearchWorkflowStageModulesSource).toContain("TeamWorkflowPaperNoteChunkStatusPanel");
    expect(routeSource).toContain("TeamResearchWorkflowStageModules");
    expect(teamWorkflowStatusPanelsSource).toContain("styles.workflowIngestionPanel");
    expect(teamWorkflowStatusPanelsSource).toContain("styles.workflowIngestionStages");
    expect(teamWorkflowStatusPanelsSource).toContain("styles.workflowIngestionBoundary");
    expect(teamWorkflowStatusPanelsSource).toContain("styles.workflowGraphPanel");
    expect(workflowGraphViewSource).toContain("styles.workflowGraphFrame");
    expect(workflowGraphViewSource).toContain("styles.workflowGraphNode");
    expect(teamWorkflowStatusPanelsSource).toContain("styles.workflowGraphBoundary");
    expect(routeSource).not.toContain("styles.workflowCandidateList");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateList");
    expect(teamSourceCollectionGraphPanelStyles.workflowCandidateList).toContain("overflow-auto");
    // Nav items live in researchWorkspaceModel pure module.
    expect(researchWorkspaceModelSource).toContain("RESEARCH_WORKSPACE_NAV_ITEMS");
    expect(routeSource).toContain("ResearchWorkspaceView");
    expect(routeSource).toContain("researchWorkspaceView");
    expect(routeSource).toContain("selectResearchWorkspaceView");
    expect(routeSource).toContain("selectTeamRecord");
    expect(routeSource).toContain("renderResearchStageLauncher");
    expect(routeSource).toContain("TeamResearchStageLauncherPanel");
    expect(researchWorkspaceModelSource).toContain("researchWorkspaceViewLabel");
    expect(routeSource).toContain("styles.teamShellWorkspace");
    expect(routeSource).toContain("styles.teamShellPageBody");
    expect(routeSource).toContain("styles.teamShellWorkspaceBoard");
    expect(routeSource).toContain("styles.teamShellWorkspaceCanvas");
    // Full-height shell (shadcn/Kernel fill): page grid + body + workspace never content-shrink.
    expect(routeStylesSource).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(routeStylesSource).toContain("teamShellPageBody");
    expect(routeStyles.teamShellBoardBody).toContain("flex-1");
    expect(routeStyles.teamShellContentBoard).toContain("overflow-hidden");
    expect(routeSource).toContain("styles.researchInspector");
    expect(routeSource).toContain("styles.researchCanvasPanelHidden");
    // Wave 8G: AI Search surface classes live on panel + aiSearch style cluster.
    expect(teamAiSearchWorkspacePanelSource).toContain("styles.aiSearchScopePanel");
    expect(teamAiSearchWorkspacePanelSource).toContain("styles.aiSearchSourceGroups");
    expect(teamAiSearchWorkspacePanelSource).toContain("styles.aiSearchSourceItem");
    // Overview: ResearchOverviewSurface is a flow strip; main body is org canvas (not kanban wall).
    expect(routeSource).toContain("ResearchOverviewSurface");
    expect(routeSource).toContain("renderResearchOverviewSurface");
    expect(routeSource).toContain("researchFlowSlot");
    expect(teamResearchPrimarySurfaceRenderersSource).not.toContain("ResearchBoardKanban");
    // End-user overview no longer mounts evidence ledger / advanced secondary in primary renderers.
    expect(teamResearchPrimarySurfaceRenderersSource).not.toContain("TeamWorkflowModelEvidenceStatusPanel");
    expect(teamResearchPrimarySurfaceRenderersSource).not.toContain("advanced={");
    expect(routeSource).toContain('renderResearchStageLauncher("interactive")');
    expect(routeSource).toContain("styles.researchOverviewSurface");
    // Shell: VBoardWorkbenchPage / VCanvasWorkbenchPage + team rail + board/canvas modes.
    expect(routeSource).toContain("VBoardWorkbenchPage");
    expect(routeSource).toContain("VCanvasWorkbenchPage");
    expect(routeSource).toContain("teamsRailResize");
    expect(routeSource).toContain("TeamShellStatusRail");
    expect(routeSource).toContain("TeamShellToolbar");
    expect(routeSource).not.toContain("<TeamShellModeSwitch");
    expect(routeSource).toContain("selectTeamShellMode");
    expect(routeSource).toContain('shellTestId="team-shell-workspace"');
    expect(routeSource).toContain("teamShellMode");
    expect(routeSource).toContain("id: TEAMS_RAIL_PANE.id");
    expect(routeSource).not.toContain("startTeamsInspectorResize");
    expect(routeSource).not.toContain("usePersistedPaneResize");
    expect(routeSource).not.toContain("科研三阶段索引");
    expect(routeSource).not.toContain("团队专属阶段页");
    expect(routeSource).toContain("researchFlowSlot");
    expect(routeSource).toContain("ResearchStageWorkspaceView");
    expect(routeSource).toContain("researchWorkspaceStageRoute");
    expect(researchWorkspaceModelSource).toContain('view: "knowledge_collection"');
    expect(researchWorkspaceModelSource).toContain('view: "experiment"');
    expect(researchWorkspaceModelSource).toContain('view: "iteration"');
    expect(researchStageRolesSource).toContain('key: "experiment_planner"');
    expect(researchStageRolesSource).toContain('challenge_cup_experiment_planner');
    expect(researchStageRolesSource).toContain('key: "experiment_ledger"');
    expect(researchStageRolesSource).toContain('challenge_cup_experiment_ledger');
    expect(researchStageRolesSource).toContain('key: "iteration_planner"');
    expect(researchStageRolesSource).toContain('challenge_cup_iteration_planner');
    expect(researchStageRolesSource).toContain('key: "iteration_versioning"');
    expect(researchStageRolesSource).toContain('challenge_cup_versioning');
    expect(routeSource).not.toContain('key: "paper_note_extraction"');
    expect(routeSource).not.toContain('key: "neuro_mechanism"');
    expect(routeSource).not.toContain('key: "mechanism_mapping"');
    expect(routeSource).not.toContain('key: "challenge_cup_delivery"');
    expect(routeSource).not.toContain('view: "source_collection", zh: "资料搜集"');
    expect(routeAndPureSource).toContain("组织画布");
    expect(researchWorkspaceModelSource).toContain('canvas: { zh: "组织画布", en: "Canvas" }');
    expect(routeAndPureSource).toContain("搜索资料");
    // Wave 8H: research console copy lives on TeamResearchStageLauncherPanel.
    expect(teamResearchStageLauncherPanelSource).toContain("科研控制台");
    expect(teamResearchStageLauncherPanelSource).toContain("开始${RESEARCH_STAGE_TERMS.knowledge_collection.zh}");
    expect(teamResearchStageLauncherPanelSource).toContain("搜索下一批");
    expect(routeSource).toContain("新一轮搜集");
    expect(routeSource).toContain("继续审查");
    expect(routeSource).toContain("准备实验");
    expect(runModelSource).toContain("正在团队搜索");
    expect(sourceCollectionControllerSource).toContain("${RESEARCH_STAGE_TERMS.knowledge_collection.zh}操作台");
    expect(routeSource).toContain("sourceCollectionDecisionText");
    expect(routeSource).toContain("下一步");
    expect(routeSource).toContain("待执行");
    // Wave 8K: raw-record stats labels live on conversation workspace panel.
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("原始记录");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("原始资料");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("可点击来源");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("本地文件");
    expect(evidenceModelSource).toContain("缺少来源");
    expect(routeSource).toContain("SourceCollectionSourceFilter");
    // Filter constants/labels live on filter-bar inject + evidence model.
    expect(evidenceModelSource).toContain("SOURCE_COLLECTION_SOURCE_FILTERS");
    expect(evidenceModelSource).toContain("sourceCollectionSourceFilterLabel");
    expect(routeSource).toContain("sourceCollectionSourceFilter");
    expect(routeSource).toContain("TeamSourceCollectionFilterBarInject");
    expect(routeSource).toContain("sourceCollectionFilteredRecords");
    expect(routeSource).toContain("sourceCollectionFilteredRunCandidates");
    expect(evidenceModelSource).toContain("sourceCollectionFilterMatches");
    expect(evidenceModelSource).toContain("论文网页/DOI");
    expect(evidenceModelSource).toContain("PDF");
    expect(evidenceModelSource).toContain("sourceCollectionCandidateProvenance");
    expect(evidenceModelSource).toContain("sourceCollectionRecordProvenance");
    expect(routeSource).toContain("sourceCollectionRecordClickableSourceCount");
    expect(routeSource).toContain("sourceCollectionRecordLocalFileCount");
    expect(routeSource).toContain("sourceCollectionRecordMissingSourceCount");
    expect(routeSource).toContain("sourceCollectionRawRecordCount");
    expect(routeSource).toContain("sourceCollectionRunCandidateCount");
    expect(routeSource).toContain("sourceCollectionRunPendingScreeningCount");
    expect(routeSource).toContain("sourceCollectionPendingCandidateImportCount");
    // Wave 8S: selected-run records live on useSourceCollectionRunQueries.
    expect(dataProcessingApiSource).toContain("/api/data-processing/runs/${encodeURIComponent(runId)}/records");
    expect(sourceCollectionRunQueriesSource).toContain("listDataProcessingRunRecords<");
    expect(teamSourceCollectionConversationPanelSource).toContain("还有 ${pendingCandidateImportCount} 条原始记录尚未进入候选库");
    expect(evidenceModelSource).toContain('label: "DOI"');
    expect(evidenceModelSource).toContain("https://doi.org/");
    // Wave 8L: candidate detail activate title lives on candidate workspace panel.
    expect(teamSourceCollectionCandidateWorkspacePanelSource).toContain("点击查看来源详情");
    expect(evidenceModelSource).toContain("sourceCollectionCandidateTrace");
    expect(routeSource).toContain("selectedSourceCollectionCandidateId");
    expect(teamLazyPanelsSource).toContain("TeamSourceCollectionSourceDetailPanel");
    // Wave 8M: selected-source detail typing/copy live on selected-source workspace panel.
    expect(teamSourceCollectionSelectedSourceWorkspacePanelSource).toContain("TeamSourceCollectionSourceDetailFact[]");
    expect(evidenceModelSource).toContain("打开论文 DOI");
    expect(teamSourceCollectionSelectedSourceWorkspacePanelSource).toContain("打开 API 原文");
    expect(teamSourceCollectionSourceDetailPanelSource).toContain("sourceCollectionSourceDetailPanel");
    expect(teamSourceCollectionSourceDetailPanelSource).toContain("sourceCollectionSearchEvidence");
    expect(teamSourceCollectionSourceDetailPanelSource).toContain("查看搜索证据");
    expect(evidenceModelSource).toContain("sourceCollectionIsMachineEvidenceUrl");
    expect(teamSourceCollectionSelectedSourceWorkspacePanelSource).toContain("仅有搜索记录，缺少可读来源");
    expect(routeSource).not.toContain("打开搜索页");
    expect(teamSourceCollectionConversationPanelSource).toContain("本轮原始资料记录");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("当前筛选没有资料");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("查看全部来源");
    expect(routeSource).toContain("搜索问题");
    expect(routeSource).toContain("待质量审查");
    expect(routeSource).not.toContain("<span>{lang === \"zh\" ? \"缓存\" : \"cache\"}");
    expect(routeSource).toContain("sourceCollectionScreeningButtonText");
    expect(routeSource).toContain("sourceCollectionScreeningDisabled");
    expect(routeSource).toContain("openSourceCollectionScreeningPanel");
    expect(routeSource).toContain("runSourceCollectionScreeningAction");
    expect(routeSource).toContain("assessSourceQualityBatchMutation");
    expect(routeSource).toContain("sourceCollectionExtractorAgentId");
    // Wave 8P: batch assess endpoint lives on useTeamSourceCollectionMutations.
    expect(teamResearchOpsApiSource).toContain("source-quality/assess-batch");
    expect(teamSourceCollectionMutationsSource).toContain("assessSourceQualityBatch<");
    expect(runModelSource).toContain("执行资料提炼复核");
    expect(routeSource).toContain("质量审查中");
    expect(routeSource).toContain("sourceCollectionExpandedPanelId");
    expect(routeSource).toContain("sourceCollectionFocusedPanelId");
    expect(routeSource).toContain("sourceCollectionControlPanelRef");
    expect(routeSource).toContain("TeamSourceCollectionControlsPanel");
    expect(teamSourceCollectionControlsPanelSource).toContain("source-collection-actions");
    expect(teamSourceCollectionControlsPanelSource).toContain("sourceCollectionControlPanel");
    expect(teamSourceCollectionControlsPanelSource).toContain("forwardRef");
    expect(routeSource).toContain("TeamSourceCollectionManualWritebackInject");
    expect(routeSource).toContain("TeamSourceCollectionSearchBriefShell");
    expect(teamSourceCollectionSearchBriefShellSource).toContain("TeamSourceCollectionSearchBriefInject");
    expect(routeSource).toContain("renderSourceCollectionManualWritebackPanel");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("workflowSourceCollectionDetails");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("workflowSourceCollectionOutputForm");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("兜底手工回写");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("写入一条资料结果");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("分工任务");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("sourceTypeLabel(sourceType)");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("回写并导入候选");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("wrapInDetails");
    expect(routeSource).not.toContain("sourceCollectionPanelClassName");
    expect(teamSourceCollectionPanelFrameStylesSource).toContain("workflowSourceCollectionDetails");
    expect(teamSourceCollectionPanelFrameStylesSource).toContain("sourceCollectionFocusedPanel");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("TeamStagePipeline");
    expect(routeSource).toContain("container.scrollTo");
    expect(routeSource).toContain("HTMLDetailsElement");
    expect(routeSource).toContain("暂无候选");
    expect(routeSource).toContain("TeamSourceCollectionScreeningPanel");
    expect(teamSourceCollectionScreeningPanelSource).toContain("source-collection-screening-panel");
    expect(teamSourceCollectionScreeningPanelSource).toContain("sourceCollectionScreeningListShell");
    expect(teamSourceCollectionScreeningPanelSource).toContain("sourceCollectionScreeningScrollCue");
    expect(teamSourceCollectionScreeningPanelSource).toContain("质量审查候选列表");
    expect(teamSourceCollectionScreeningPanelSource).not.toContain("可向下滚动查看更多");
    expect(teamSourceCollectionScreeningPanelSource).not.toContain("向下滚动查看更多本页候选");
    expect(routeSource).not.toContain("TeamSourceCollectionCandidateWorkspacePanel");
    expect(teamSourceCollectionCandidatePanelSource).toContain("source-collection-candidates-panel");
    expect(routeSource).toContain("TeamSourceCollectionGraphPanel");
    expect(routeSource).toContain("source-collection-graph-panel");
    expect(teamSourceCollectionGraphPanelSource).toContain("source-collection-graph-panel");
    expect(teamSourceCollectionGraphPanelSource).toContain("workflowGraphStats");
    expect(routeSource).toContain("TeamSourceCollectionMemoryPanel");
    expect(teamSourceCollectionMemoryPanelSource).toContain("source-collection-memory-panel");
    expect(routeSource).not.toContain("researchView=candidates");
    expect(routeSource).toContain("查看提炼结果");
    expect(routeSource).toContain("openSourceCollectionCandidatePanel");
    expect(routeSource).not.toContain("renderSourceCollectionCandidatePanel");
    expect(routeSource).not.toContain("sourceCollectionRunCandidates.slice(0, 6)");
    // Recovery metrics integrate into the extraction stage card (ActiveStage workspace).
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("TeamSourceCollectionExtractionRecoveryWorkspacePanel");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("renderIntegratedRecovery");
    expect(routeSource).toContain("extractionRecovery=");
    expect(routeSource).not.toContain("renderSourceCollectionExtractionRecoveryPanel");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("sourceCollectionExtractionRecoveryStats");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("sourceCollectionExtractionRecoveryActions");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("titleLabel");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("failedLabel");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("recoverLabel");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("可保留");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("待质量审查");
    // Wave 8L: recovery CTA copy / open-chat wiring live on recovery workspace panel.
    expect(teamSourceCollectionExtractionRecoveryWorkspacePanelSource).toContain("进入 Agent 私聊");
    expect(teamSourceCollectionExtractionRecoveryWorkspacePanelSource).toContain("qualityReviewActionText");
    expect(routeSource).toContain("runSourceCollectionCandidateExtractionAction");
    expect(routeSource).toContain("runSourceCollectionScreeningAction");
    expect(teamSourceCollectionExtractionRecoveryWorkspacePanelSource).toContain("openSourceCollectionStageAgentChat(\"extraction\")");
    // F3: material gap / excluded recovery math in presentationExtractionMetrics
    expect(routeSource).toContain("sourceCollectionMaterialGapCount");
    expect(routeSource).toContain("hasCurrentCandidates");
    expect(routeSource).toContain("needsRevisionCount");
    expect(routeSource).toContain("deriveSourceCollectionExcludedRecoveryState");
    expect(routeSource).toContain("sourceCollectionExtractionExcludedRecoveryState");
    expect(evidenceModelSource).toContain("剩余资料已被排除");
    expect(evidenceModelSource).toContain("查看排除原因");
    expect(evidenceModelSource).toContain("提炼排除项确认");
    expect(routeSource).toContain("sourceCollectionExtractionCanProceedAfterExclusions");
    expect(evidenceModelSource).toContain("可继续推进");
    expect(teamSourceCollectionExtractionRecoveryWorkspacePanelSource).toContain('onPress={() => void openSourceCollectionStageAgentChat("extraction")}');
    expect(routeSource).not.toContain("sourceCollectionRunCandidates.slice(0, 12)");
    expect(routeSource).not.toContain("SOURCE_COLLECTION_RESULT_PREVIEW_LIMIT");
    expect(routeSource).toContain("sourceCollectionStageCard");
    expect(routeSource).toContain("detailLabel");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("onActivate={module.onDetail}");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("sourceCollectionStagePrimaryAction");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("sourceCollectionStageSecondaryAction");
    expect(routeSource).not.toContain("styles.sourceCollectionStagePrimaryAction");
    expect(routeSource).not.toContain("styles.sourceCollectionStageSecondaryAction");
    expect(routeSource).not.toContain("sourceCollectionStageActionRow");
    expect(routeSource).not.toContain("module.onAgentChat");
    expect(routeSource).toContain("SourceCollectionStepState");
    expect(routeSource).toContain("SourceCollectionStageModuleId");
    expect(routeSource).toContain("SourceCollectionStageCardProjection");
    expect(routeSource).toContain("sourceCollectionStageCards");
    expect(routeSource).toContain("sourceCollectionStageCardSummary");
    expect(routeSource).toContain("sourceCollectionStageCardById");
    expect(routeSource).toContain("excludedSourceCount");
    // Wave 8P: filteredExcludedCount is owned by SC mutation payload model + controls workspace copy.
    expect(teamSourceCollectionControlsWorkspacePanelSource).toContain("filteredExcludedCount");
    // Wave 8M: search result feedback copy lives on controls workspace panel.
    expect(teamSourceCollectionControlsWorkspacePanelSource).toContain("无效来源已过滤");
    expect(stageProjectionSource).toContain("已移出");
    expect(routeSource).toContain("sourceCollectionDisplayedCandidateCount");
    expect(routeSource).toContain("sourceCollectionPrimaryDataLoading");
    expect(routeSource).toContain("sourceCollectionSourceQualityLoading");
    expect(routeSource).toContain("sourceCollectionScreeningDataLoading");
    expect(routeSource).toContain("sourceCollectionLoadingText");
    expect(routeSource).toContain("sourceCollectionLoadingSummary");
    expect(routeSource).toContain("sourceCollectionDisplayedCandidateFilterCounts");
    expect(routeSource).toContain("sourceCollectionCandidateProjectionFallbackCount");
    // Wave 8L: candidate empty-state refresh gate lives on candidate workspace panel.
    expect(teamSourceCollectionCandidateWorkspacePanelSource).toContain("candidateListAwaitingRefresh");
    expect(evidenceModelSource).toContain("正在加载资料提炼结果");
    expect(routeSource).toContain("正在读取资料提炼结果");
    expect(evidenceModelSource).toContain("列表正在同步");
    expect(routeSource).toContain("sourceCollectionStageProjectionState");
    expect(stageProjectionSource).toContain("agent_interrupted");
    expect(stageProjectionSource).toContain("agent_done_artifact_pending");
    expect(routeSource).toContain("latestTask");
    expect(stageProjectionSource).toContain("blockingReasons");
    expect(routeSource).toContain("sourceCollectionStageUserStatusLabel");
    expect(routeSource).toContain("sourceCollectionStageUserSummary");
    expect(routeSource).toContain("sourceCollectionStageRecoveryStatusLabel");
    expect(routeSource).not.toContain("sourceCollectionStageTechnicalDetails");
    expect(routeSource).toContain("sourceCollectionCandidateEmptyStateText");
    expect(stageProjectionSource).toContain("已收到 Agent 结果，等待生成可用资料");
    expect(stageProjectionSource).toContain("Agent 返回的候选 ID 没有匹配到本轮资料");
    expect(routeSource).not.toContain("技术详情");
    expect(evidenceModelSource).toContain("待补提炼");
    expect(stageProjectionSource).toContain("已中断，需要继续");
    expect(stageProjectionSource).toContain("继续这次任务");
    expect(routeSource).toContain("待质量审查");
    expect(evidenceModelSource).toContain("继续补全提炼");
    expect(routeSource).not.toContain("sourceCollectionStageBlockingReasonLabel(module.projection.blockingReasons[0], lang)");
    expect(stageProjectionSource).toContain("sourceCollectionStageBlockingReasonsLabel");
    expect(stageProjectionSource).toContain("sourceCollectionStageArtifactSummaryLabel");
    expect(routeSource).not.toContain("待 Agent 产出");
    expect(routeSource).not.toContain("已有输入，等待该阶段生成目标产物。");
    expect(routeSource).not.toContain("证据 ${evidenceCount}");
    expect(routeSource).not.toContain("candidateProjection.blockingReasons.join");
    expect(routeSource).not.toContain("{module.projection.blockingReasons[0]}</small>");
    expect(evidenceModelSource).toContain("evidenceRefCount");
    expect(stageProjectionSource).toContain("materializedSources");
    expect(stageProjectionSource).toContain("SourceCollectionCoverageSummary");
    expect(routeSource).toContain("coverageSummary");
    expect(routeSource).toContain("currentCoverageSummary");
    expect(stageProjectionSource).toContain("partial_current_inputs");
    expect(stageProjectionSource).toContain("当前批次还有资料未处理");
    expect(stageProjectionSource).toContain("SourceCollectionStageClosureSummary");
    expect(routeSource).toContain("closureSummary");
    expect(stageProjectionSource).toContain("SourceCollectionStageTaskToolProgress");
    expect(stageProjectionSource).toContain("taskToolProgress");
    expect(stageProjectionSource).toContain("SourceCollectionStageCompletionGate");
    expect(stageProjectionSource).toContain("SourceCollectionStageActionReadinessProjection");
    expect(stageProjectionSource).toContain("actionReadiness?: SourceCollectionStageActionReadinessProjection");
    expect(routeSource).toContain("sourceCollectionStageBackendActionReadiness");
    expect(routeSource).toContain("sourceCollectionStageActionLabelFor");
    expect(stageProjectionSource).toContain("completionGatePassed");
    expect(stageProjectionSource).toContain("sourceCollectionTaskToolProgressMetric");
    expect(stageProjectionSource).toContain("检查项");
    expect(routeSource).toContain("sourceCollectionStageLaunchActive");
    expect(routeSource).toContain("sourceCollectionStageLaunchSummary");
    expect(teamSourceCollectionShellModelSource).toContain("Agent 已启动，正在进入私聊");
    expect(runModelSource).toContain("等待 Agent 回写");
    expect(routeSource).toContain("sourceCollectionStageDisplayState");
    expect(stageProjectionSource).toContain("sourceCollectionStageInterruptedSummary");
    expect(stageProjectionSource).toContain("剩余检查项");
    expect(routeSource).toContain('modules.find((module) => module.state === "failed")');
    expect(routeSource).toContain("pickSourceCollectionPipelineModule");
    expect(routeSource).not.toContain("仍需完成检查项或生成本阶段产物");
    // Wave 8L: recovery view-model consumes invalid id counts from projection.
    expect(extractionRecoveryViewModelSource).toContain("invalidRecordIds");
    expect(stageProjectionSource).toContain("本轮未生成候选资料");
    expect(evidenceModelSource).toContain("没有生成候选资料");
    expect(stageProjectionSource).toContain("完整 recordId");
    expect(stageProjectionSource).toContain("sourceCollectionCoverageMetric");
    expect(extractionRecoveryViewModelSource).toContain("invalidCandidateIds");
    expect(extractionRecoveryViewModelSource).toContain("重新质量审查");
    expect(extractionRecoveryViewModelSource).toContain("系统不会重复访问已经拒绝的来源链接");
    expect(extractionRecoveryViewModelSource).toContain("showExcludeUnverifiableAction");
    expect(extractionRecoveryViewModelSource).toContain("排除 ${sourceVerificationCount} 条不可核验来源");
    expect(extractionRecoveryViewModelSource).toContain('excluded || sourceVerificationOnly ? "chat" : "continue_task"');
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("VConfirmDialog");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("排除本轮不可核验来源？");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("excludeUnverifiableCandidates");
    // F3: unverifiable ids from presentationExtractionMetrics; exclude action from action handlers.
    expect(routeSource).toContain("sourceCollectionUnverifiableCandidateIds");
    expect(routeSource).toContain("unverifiableCandidateIds");
    expect(routeSource).toContain("excludeUnverifiableSourceCollectionCandidates");
    expect(routeSource).toContain('decision: "rejected"');
    expect(teamSourceCollectionMutationsSource).toContain('"approved" | "needs_revision" | "rejected"');
    expect(stageProjectionSource).toContain("materializedContentExtraction");
    expect(evidenceModelSource).toContain("继续补全提炼");
    expect(evidenceModelSource).toContain("继续补全提炼");
    expect(routeSource).not.toContain("Agent 已回写，仍待补产物");
    // Wave 8K: extraction status chips used by conversation/screening workspaces.
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("已提炼");
    expect(evidenceModelSource).toContain("待补提炼");
    expect(routeSource).toContain("已审");
    expect(routeSource).toContain("待质量审查");
    expect(routeSource).not.toContain("未匹配资料");
    // Wave 8L: graph projection selection lives on graph workspace panel.
    expect(teamSourceCollectionGraphWorkspacePanelSource).toContain("graphForSelectedSourceRun");
    expect(routeSource).toContain("parseSourceCollectionStageModuleId");
    expect(routeSource).toContain("collectionStage");
    expect(routeSource).toContain("selectedSourceCollectionStageId");
    expect(routeSource).toContain("selectSourceCollectionStage");
    expect(routeSource).toContain("renderSourceCollectionActiveStagePanel");
    expect(createSourceCollectionStageAgentHelpersSource).toContain("researchStageAgentDirectChatRoute");
    expect(createSourceCollectionStageAgentHelpersSource).toContain("researchStageSessionChatRoute");
    expect(createSourceCollectionStageAgentHelpersSource).toContain("sourceCollectionSummaryQuery.data?.latestTasks?.[stageId]?.sessionId");
    expect(routeSource).toContain("sourceCollectionSummaryQuerySeedText");
    expect(createSourceCollectionStageAgentHelpersSource).toContain("stageSessionPending");
    expect(routeSource).toContain("sourceCollectionStageReturnRoute");
    expect(routeSource).toContain("sourceCollectionStageChatReturnLabel");
    expect(researchStageAgentPresentationSource).toContain("params.set(\"returnTo\", normalizedReturnTo)");
    expect(researchStageAgentPresentationSource).toContain("params.set(\"returnLabel\", normalizedReturnLabel)");
    expect(routeSource).toContain("openSourceCollectionStageAgentChat");
    expect(teamSourceCollectionShellModelSource).toContain('export type SourceCollectionStageAgentChatStatus = "ready" | "loading" | "error" | "repair" | "blocked"');
    expect(routeSource).toContain("resolveSourceCollectionStageAgentChatState");
    expect(routeSource).toContain("sourceCollectionStageAgentChatState(stageId");
    expect(routeSource).toContain("agentSummaryQuery.isPending || agentSummaryQuery.isFetching");
    // Wave 8M: primary stage agent chat fallback state lives on active-stage workspace.
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("primaryStageAgentChatLoading");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("先推进搜集再进入私聊");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("加载本轮会话...");
    expect(routeSource).toContain('chatState.status === "repair"');
    expect(routeSource).toContain("onAction: () => void startSourceCollectionStageSessionTask(\"finding\")");
    expect(routeSource).toContain("onAction: sourceCollectionExtractionCanProceedAfterExclusions");
    expect(routeSource).toContain(": () => void startSourceCollectionStageSessionTask(\"extraction\")");
    expect(routeSource).toContain("onAction: () => void startSourceCollectionStageSessionTask(\"relations\")");
    expect(routeSource).toContain("sourceCollectionIngestionReadyForExperiment");
    expect(routeSource).toContain("sourceCollectionExperimentPlanningRoute");
    expect(routeSource).toContain("researchWorkspaceStageRoute");
    expect(routeSource).toContain("RESEARCH_TEAM_ID");
    expect(routeSource).toContain("onSecondaryAction: sourceCollectionIngestionReadyForExperiment");
    expect(routeSource).toContain("进入实验设计（离开${RESEARCH_STAGE_TERMS.knowledge_collection.zh}）");
    expect(routeSource).toContain("navigate(sourceCollectionExperimentPlanningRoute)");
    expect(routeSource).toContain(": () => void startSourceCollectionStageSessionTask(\"ingestion\")");
    expect(routeSource).toContain("repairChallengeCupTeamAgentsMutation");
    // Wave 8Q: agent repair endpoints live on useTeamShellMutations.
    expect(teamShellMutationsSource).toContain("repairChallengeCupTeamAgents(");
    expect(routeSource).toContain("repairKnowledgeExpansionTeamAgentsMutation");
    expect(teamShellMutationsSource).toContain("repairKnowledgeExpansionTeamAgents(");
    // Wave 8M: repair/open-chat CTAs live on active-stage workspace (and recovery).
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("修复团队 Agent");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("进入 Agent 私聊");
    expect(teamRouteShellModelSource).toContain("Agent 私聊");
    expect(routeSource).toMatch(/from "\.\/(?:teams\/)?teamRouteShellModel"/);
    expect(routeSource).not.toContain("window.alert(lang === \"zh\"");
    expect(routeSource).not.toContain("sourceCollectionStageChatRoute");
    expect(routeSource).not.toContain("sourceCollectionStageRoomKey");
    expect(routeSource).not.toContain("createSourceCollectionStageChatRoomMutation");
    expect(routeSource).not.toContain("sourceCollectionStageViewMode");
    expect(routeSource).not.toContain("SourceCollectionStageViewMode");
    expect(routeSource).toContain("sourceCollectionPageItems");
    expect(routeSource).toContain("renderSourceCollectionPagination");
    expect(routeSource).toContain("stopSourceCollectionPaginationEvent");
    expect(routeSource).toContain("onContain={stopSourceCollectionPaginationEvent}");
    expect(routeSource).toContain("sourceCollectionExtractionDefaultPanelId");
    // Wave 8K/8L: expanded-panel open logic lives on screening/candidate workspace panels.
    expect(teamSourceCollectionScreeningWorkspacePanelSource).toContain("sourceCollectionExpandedPanelId === \"source-collection-screening-panel\"");
    expect(teamSourceCollectionCandidateWorkspacePanelSource).toContain("sourceCollectionExpandedPanelId === \"source-collection-candidates-panel\"");
    expect(routeSource).not.toContain("preventSourceCollectionPanelSummaryToggle");
    expect(routeSource).not.toContain("onClick={preventSourceCollectionPanelSummaryToggle}");
    expect(routeSource).not.toContain("sourceCollectionTraceMessagesForStage");
    expect(routeSource).not.toContain("renderSourceCollectionStageProcessPanel");
    expect(routeSource).toContain("selected: module.id === selectedSourceCollectionStageId");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("selected={module.selected}");
    expect(routeSource).not.toContain("sourceCollectionStageOperationPanel");
    expect(routeSource).not.toContain("<small>{module.summary}</small>");
    expect(routeSource).not.toContain("sourceCollectionStageProjectionTaskMetric(module.projection");
    expect(routeSource).not.toContain("<summary>{lang === \"zh\" ? \"技术详情\" : \"Technical details\"}</summary>");
    const graphStateExpression = routeSource.slice(
      routeSource.indexOf("const sourceCollectionGraphStepState"),
      routeSource.indexOf("const sourceCollectionMemoryStepState"),
    );
    const memoryStateExpression = routeSource.slice(
      routeSource.indexOf("const sourceCollectionMemoryStepState"),
      routeSource.indexOf("const sourceCollectionCollectionActionLabel"),
    );
    expect(graphStateExpression).not.toContain("teamWorkflowCandidateGraphQuery.isFetching");
    expect(memoryStateExpression).not.toContain("teamWorkflowKnowledgeIngestionStatusQuery.isFetching");
    expect(routeSource).not.toContain("className={styles.sourceCollectionStageMiniFlow}");
    // Stage card is action-first: no handoff copy wall / coaching hints under CTA.
    expect(teamSourceCollectionActiveStagePanelSource).toContain("sourceCollectionStageProjectReset");
    expect(teamSourceCollectionActiveStagePanelSource).not.toContain("sourceCollectionStageHandoffNext");
    expect(routeSource).not.toContain("Agent过程");
    // Wave 8M: active-stage action/binding copy lives on active-stage workspace.
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("activeModule.onAction");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("sourceCollectionStagePrimaryAgentBinding(activeModule.id)");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("配置 Agent");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("绑定 Agent");
    expect(routeSource).toContain("sourceCollectionStageModules.map");
    expect(routeSource).toContain("sourceCollectionStepClassName");
    expect(routeSource).not.toContain("下一步操作");
    expect(routeSource).toContain("TeamSourceCollectionActiveStagePanel");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("sourceCollectionStageWorkspace");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("sourceCollectionStageChatActions");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("当前阶段子页");
    expect(teamSourceCollectionControlsPanelSource).toContain("步骤侧栏");
    expect(teamSourceCollectionActiveStagePanelSource).not.toContain("流水线当前");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).not.toContain("流水线当前");
    // Wave 8H: stage card chrome lives on TeamResearchStageLauncherPanel.
    expect(teamResearchStageLauncherPanelSource).toContain("styles.researchStageCardHead");
    expect(teamResearchStageLauncherPanelSource).toContain("styles.researchStageCardMetrics");
    expect(routeSource).toContain("RESEARCH_STAGE_AGENT_ROLES");
    expect(routeSource).toContain("researchStageAgentBindingsByStage");
    // Wave 8H: summary is invoked from TeamResearchStageLauncherPanel.
    // Product workbench: stage page mounts ledger only (no agent panel dump).
    expect(teamResearchStageLauncherPanelSource).toContain("renderResearchStageAgentSummary(stageType)");
    // Task 9: TeamResearchStageStandalonePagePanel removed with the Challenge Cup stage-rail shell.
    expect(routeSource).toContain("function renderResearchStageAgentPanel");
    expect(routeSource).toContain("renderResearchStageAgentPanel");
    expect(routeSource).toContain("TeamResearchStageAgentSummary");
    expect(routeSource).toContain("TeamResearchStageAgentPanel");
    expect(routeSource).not.toContain('renderResearchStageAgentPanel("knowledge_collection", "compact")');
    expect(routeSource).toContain("SOURCE_COLLECTION_STAGE_AGENT_KEYS");
    expect(teamSourceCollectionShellModelSource).toContain("SOURCE_COLLECTION_STAGE_AGENT_KEYS");
    expect(routeSource).toContain("sourceCollectionStageAgentBindings(stageId)");
    expect(routeSource).not.toContain("renderSourceCollectionStageAgentStrip");
    expect(teamStageCardSource).toContain('target.closest("button, a")');
    // Wave 8M: stage-agents strip mount lives on controls workspace.
    expect(teamSourceCollectionControlsWorkspacePanelSource).toContain("renderSourceCollectionStageAgents(activeModule.id)");
    expect(routeSource).toContain("TeamSourceCollectionStageAgentsInject");
    expect(teamSourceCollectionStageAgentsPanelSource).toContain("TeamSourceCollectionStageAgentsPanel");
    // Agent card mapping lives on stageAgentsPresentation pure helper.
    expect(routeSource).toContain("bindings={sourceCollectionStageAgentBindings(stageId)}");
    expect(teamSourceCollectionStageAgentsPanelSource).toContain("当前步骤 Agent 配置");
    expect(teamSourceCollectionStageAgentsPanelSource).toContain("VDenseTable");
    expect(teamSourceCollectionStageAgentsPanelSource).toContain("VRouteLinkButton");
    expect(teamSourceCollectionStageAgentsPanelSource).toContain("VStatusChip");
    expect(teamSourceCollectionStageAgentsPanelSource).toContain("sourceCollectionStageAgentPanel");
    expect(routeSource).not.toContain("sourceCollectionStageAgentStrip");
    expect(routeSource).not.toContain("sourceCollectionStageAgentChips");
    expect(routeSource).not.toContain("sourceCollectionStageAgentChip");
    // Config route composition moved into stageAgentsPresentation pure helper.
    expect(routeSource).toContain("TeamSourceCollectionStageAgentsInject");
    expect(routeSource).not.toContain("const chatRoute = researchStageAgentDirectChatRoute");
    // Wave 8G: Agent management CTA copy lives on TeamResearchStageAgentPanel.
    expect(teamResearchStageAgentPanelSource).toContain("Agent 管理");
    expect(routeSource).not.toContain("还需补充资料");
    expect(routeSource).toContain("sourceCollectionSearchOpenAssignmentCount");
    expect(routeSource).toContain("sourceCollectionDownstreamOpenAssignmentCount");
    expect(routeSource).toContain("SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES");
    expect(routeSource).toContain("个搜索任务待执行");
    expect(runModelSource).toContain("搜索已停止，还有");
    expect(routeSource).not.toContain("sourceCollectionOpenAssignmentCount > 0 ? <Search");
    // Wave 8M: ingestion feedback copy lives on controls workspace panel.
    expect(teamSourceCollectionControlsWorkspacePanelSource).toContain("条资料通过审查");
    expect(routeSource).toContain("重新质量审查");
    expect(routeSource).toContain("Agent 质量审查");
    expect(routeSource).toContain("质量审查完成");
    expect(routeSource).toContain("sourceCollectionIngestorAgentId");
    expect(routeSource).toContain("runKnowledgeIngestionPrecheckMutation");
    // Wave 8P: ingestion precheck/complete write endpoints live on useTeamSourceCollectionMutations.
    expect(teamKnowledgeApiSource).toContain("knowledge-ingestion/precheck");
    expect(teamSourceCollectionMutationsSource).toContain("runKnowledgeIngestionPrecheck<");
    expect(routeSource).toContain("runSourceCollectionGraphAction");
    expect(routeSource).not.toContain("runSourceCollectionMemoryPrecheckAction");
    expect(routeSource).toContain("runKnowledgeCollectionLoopAction");
    expect(routeSource).toContain("runKnowledgeCollectionCompletionMutation");
    expect(teamKnowledgeApiSource).toContain("/workflow-orchestration/knowledge-collection/complete");
    expect(teamSourceCollectionMutationsSource).toContain("completeKnowledgeCollection(");
    expect(routeSource).toContain("sourceCollectionActionRunId");
    // R2-o: summary runId projection lives in deriveSourceCollectionSummaryProjection.
    expect(deriveSourceCollectionSummaryProjectionSource).toContain("sourceCollectionSummary?.runId");
    expect(routeSource).toContain("startKnowledgeCollectionCompletionForRun(sourceCollectionActionRunId");
    const sourceCollectionCompletionDisabledSource = routeSource.slice(
      routeSource.indexOf("sourceCollectionLoopActionDisabled"),
      routeSource.indexOf("sourceCollectionLoopActionLabel"),
    );
    expect(sourceCollectionCompletionDisabledSource).not.toContain("!selectedSourceCollectionRun");
    expect(routeSource).toContain("extractionAgentId: sourceCollectionExtractorAgentId");
    expect(routeSource).toContain("agent_approved_only");
    expect(routeSource).toContain("Agent 生成关系图");
    expect(routeSource).toContain("通知资料入库 Agent");
    expect(routeSource).toContain("开始第一轮闭环");
    expect(routeSource).toContain("继续本轮闭环");
    expect(routeSource).toContain("开始下一轮闭环");
    expect(routeSource).toContain("renderKnowledgeCollectionCompletionFlowPanel");
    expect(routeSource).toContain("TeamKnowledgeCollectionCompletionFlowPanel");
    // Wave 8K: completion-flow chrome/copy lives on dedicated panel.
    expect(teamKnowledgeCollectionCompletionFlowPanelSource).toContain("knowledgeCompletionFlowPanel");
    expect(routeSource).toContain("sourceCollectionCompletionFlowNodes");
    expect(routeSource).toContain("selectedTeamKnowledgeIngestionLatestWorkRun");
    expect(routeSource).toContain("flowVisualization");
    expect(routeSource).toContain("latestWorkRun");
    expect(routeSource).toContain('nextParams.set("researchView", "workflow")');
    expect(routeSource).toContain('nextParams.set("node", "knowledge_ingestion")');
    expect(teamKnowledgeCollectionCompletionFlowPanelSource).toContain("一键流程图");
    expect(teamKnowledgeCollectionCompletionFlowPanelSource).toContain("阶段详情");
    expect(teamKnowledgeCollectionCompletionFlowPanelSource).toContain("Agent 私聊");
    expect(teamKnowledgeCollectionCompletionFlowPanelSource).toContain("重新执行搜集闭环");
    expect(teamKnowledgeCollectionCompletionFlowPanelSource).toContain("openSourceCollectionStageAgentChat(node.stageId)");
    expect(routeSource).toContain("提炼后通知入库 Agent");
    expect(teamSourceCollectionControlsWorkspacePanelSource).toContain("资料已写入团队知识库");
    expect(routeSource).toContain("sourceCollectionPrecheckCandidateCount");
    expect(routeSource).toContain("sourceCollectionIngestCandidateCount");
    expect(routeSource).toContain("sourceCollectionCanBuildGraph");
    expect(routeSource).toContain("sourceCollectionGraphActionDisabled");
    expect(routeSource).toContain("审查并生成关系图");
    expect(routeSource).toContain("sourceCollectionMemoryActionDisabled");
    expect(routeSource).toContain("sourceCollectionMemoryActionLabel");
    expect(routeSource).toContain("maxCandidates: Math.max(1, Math.min(80, sourceCollectionIngestCandidateCount))");
    expect(routeSource).toContain("forceReview: precheckCandidateCount <= 0 && displayedCandidateCount > 0");
    expect(routeSource).toContain("forceReview: sourceCollectionRunApprovedCount <= 0 && sourceCollectionDisplayedCandidateCount > 0");
    expect(routeSource).toContain("可通知资料入库 Agent");
    expect(routeSource).toContain("条候选资料");
    expect(routeSource).not.toContain("onAction: refreshSourceCollectionGraph");
    expect(routeSource).not.toContain("onAction: refreshSourceCollectionMemoryPrecheck");
    expect(routeSource).toContain("forceRescreen");
    expect(routeSource).toContain("force: forceRescreen");
    expect(teamSourceCollectionScreeningPanelSource).toContain("sourceCollectionPanelActions");
    expect(routeSource).toContain("Source Extractor Agent re-ran quality scoring on already assessed source_manifest candidates");
    expect(routeSource).toContain("通知资料入库 Agent");
    expect(routeSource).not.toContain("待继续搜索");
    // Wave 8P: storage open write endpoint lives on useTeamSourceCollectionMutations.
    expect(sourceCollectionApiSource).toContain("/storage/open");
    expect(teamSourceCollectionMutationsSource).toContain("openSourceCollectionStorage<");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("本轮产物");
    expect(routeAndPureSource).toContain("打开批次目录");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("更多证据文件");
    expect(routeAndPureSource).toContain("sourceCollectionStorageTargetForRef");
    expect(routeAndPureSource).toContain("sourceCollectionStatusLabel");
    expect(routeAndPureSource).toContain("sourceCollectionAgentRoleLabel");
    expect(routeSource).not.toContain("currentTraceMessage");
    expect(routeSource).toContain("结果");
    expect(routeSource).not.toContain("Agent 执行过程");
    expect(routeSource).not.toContain("过程</button>");
    expect(routeSource).toContain("TeamSourceCollectionConversationPanel");
    expect(routeSource).toContain("TeamSourceCollectionConversationInject");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("TeamSourceCollectionConversationWorkspacePanel");
    expect(teamSourceCollectionConversationPanelSource).toContain("sourceCollectionResultsPanel");
    expect(teamSourceCollectionConversationPanelSource).toContain("source-collection-results");
    expect(teamSourceCollectionConversationPanelSource).toContain("TeamSourceResultStats");
    expect(teamSourceCollectionConversationPanelSource).toContain("sourceCollectionResultWarning");
    // Wave 8K: result list + screening empty copy moved to workspace panels.
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("TeamSourceResultList");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("TeamSourceResultItem");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("sourceCollectionResultTone");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("statusLabel={resultStatus.label}");
    expect(teamSourceCollectionScreeningWorkspacePanelSource).toContain("当前过滤条件下没有候选资料");
    expect(teamSourceCollectionScreeningWorkspacePanelSource).toContain("sourceCollectionSimpleCandidateStatusPresentation");
    expect(teamSourceCollectionScreeningWorkspacePanelSource).toContain("statusTitle={");
    expect(teamSourceCollectionScreeningWorkspacePanelSource).not.toContain("workflowIngestionStatusLabel(sourceQualitySummary.decision");
    // Wave 8L: graph/memory empty filter copy live on workspace panels.
    expect(teamSourceCollectionGraphWorkspacePanelSource).toContain("当前过滤条件下没有入库关系节点");
    expect(teamSourceCollectionMemoryWorkspacePanelSource).toContain("当前过滤条件下没有入库资料");
    expect(deriveSourceCollectionListMetricsSource).toContain("sourceCollectionCandidateQualityState(candidate).approved");
    expect(workflowPresentationSource).toContain("source_needs_quality_revision: \"需补资料\"");
    expect(workflowPresentationSource).toContain("source_screened: \"已审查\"");
    expect(teamSourceCollectionCandidatePanelSource).toContain("sourceCollectionCandidateListShell");
    expect(teamSourceCollectionCandidatePanelSource).toContain("loading && !hasCandidates");
    expect(teamSourceCollectionCandidatePanelSource).toContain("sourceCollectionCandidateSkeletonRow");
    expect(routeSource).not.toContain("const resultPanel = selectedSourceCollectionStageId");
    expect(teamSourceCollectionActiveStagePanelSource).toContain('stageId === "ingestion"');
    expect(teamSourceCollectionActiveStagePanelSource).toContain("styles.sourceCollectionIngestionPanels");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("renderGraphPanel()");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("renderMemoryPanel()");
    expect(teamSourceCollectionActiveStagePanelSource).toContain('stageId === "extraction"');
    expect(teamSourceCollectionActiveStagePanelSource).toContain("styles.sourceCollectionExtractionPanels");
    expect(teamSourceCollectionActiveStagePanelSource).not.toContain("renderCandidatePanel");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("renderScreeningPanel()");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("renderIntegratedRecovery");
    expect(teamSourceCollectionActiveStagePanelSource).not.toContain("renderRecoveryPanel()");
    // Wave 8M: stage panel render-prop mounts live on active-stage workspace.
    // Extraction recovery is merged into the right-hand stage card (not candidate list / dock).
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("renderGraphPanel={renderSourceCollectionGraphPanel}");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("renderMemoryPanel={renderSourceCollectionMemoryPanel}");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).not.toContain("renderCandidatePanel=");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("renderScreeningPanel={renderSourceCollectionScreeningPanel}");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("renderIntegratedRecovery=");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("extractionRecovery");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain('presentation="stageCard"');
    expect(teamSourceCollectionCandidateWorkspacePanelSource).not.toContain("renderSourceCollectionExtractionRecoveryPanel");
    expect(teamSourceCollectionCandidatePanelSource).not.toContain("recoveryPanel");
    // Wave 8L: graph open condition lives on graph workspace panel.
    const graphPanelOpenSource = teamSourceCollectionGraphWorkspacePanelSource.slice(
      teamSourceCollectionGraphWorkspacePanelSource.indexOf("<TeamSourceCollectionGraphPanel"),
      teamSourceCollectionGraphWorkspacePanelSource.indexOf(
        "onToggle={(event) =>",
        teamSourceCollectionGraphWorkspacePanelSource.indexOf("<TeamSourceCollectionGraphPanel"),
      ),
    );
    expect(graphPanelOpenSource).toContain('selectedSourceCollectionStageId === "relations"');
    expect(graphPanelOpenSource).not.toContain('selectedSourceCollectionStageId === "ingestion"');
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionIngestionPanels).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionIngestionPanels).toContain("overflow-hidden");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionIngestionPanels).toContain("min-h-0");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionIngestionPanels).toContain("max-[860px]:min-h-[560px]");

    const completed = renderSourceCollectionKnowledgeIngestionStatus({
      status: "completed",
      formalKnowledgeItemCount: 1,
      formalKnowledgeItemIds: ["knowledge-1"],
      knowledgeBaseId: "kb-1",
      failedCount: 0,
      failed: [],
    });
    expect(completed).toContain('data-testid="source-collection-knowledge-ingestion-status"');
    expect(completed).toContain('data-ingestion-state="completed"');
    expect(completed).toContain('data-ingestion-reason-code="official_sync_completed"');
    expect(completed).toContain("1 条");
    expect(completed).not.toContain("knowledge-1");

    const pending = renderSourceCollectionKnowledgeIngestionStatus({
      status: "pending_review",
      formalKnowledgeItemCount: 0,
      knowledgeBaseId: "kb-pending",
      skippedCount: 1,
    });
    expect(pending).toContain('data-ingestion-state="pending"');
    expect(pending).toContain('data-ingestion-reason-code="official_sync_pending"');
    expect(pending).toContain("等待正式同步");
    expect(pending).not.toContain("kb-pending");

    const failed = renderSourceCollectionKnowledgeIngestionStatus({
      status: "completed",
      formalKnowledgeItemCount: 1,
      formalKnowledgeItemIds: ["knowledge-stale"],
      failedCount: 1,
      failed: [{ reason: "knowledge review rejected" }],
    });
    expect(failed).toContain('data-ingestion-state="failed"');
    expect(failed).toContain('data-ingestion-reason-code="official_sync_failed"');
    expect(failed).not.toContain('data-ingestion-state="completed"');
    expect(failed).toContain("正式知识同步失败");
    expect(failed).not.toContain("knowledge-stale");
    expect(failed).not.toContain("knowledge review rejected");

    const empty = renderSourceCollectionKnowledgeIngestionStatus({});
    expect(empty).not.toContain("source-collection-knowledge-ingestion-status");
    // Wave 6E: graph node list height is shared PaneHeight, not fixed max-h.
    expect(teamSourceCollectionGraphPanelStyles.sourceCollectionGraphNodeListShell).not.toContain("max-h-[28vh]");
    expect(teamSourceCollectionGraphPanelStyles.sourceCollectionGraphNodeListShell).toContain("[scrollbar-gutter:stable]");
    expect(teamSourceCollectionGraphPanelSource).toContain("PersistedHeightListShell");
    expect(teamSourceCollectionGraphPanelSource).toContain("TEAM_SOURCE_COLLECTION_GRAPH_NODES_HEIGHT_PANE");
    expect(routeStylesSource).not.toContain(".sourceCollectionIngestionPanels");
    expect(routeStylesSource).not.toContain(".sourceCollectionGraphNodeListShell");
    expect(teamSourceCollectionMemoryPanelSource).toContain("sourceCollectionMemoryListShell");
    expect(teamSourceCollectionMemoryPanelSource).toContain("PersistedHeightListShell");
    expect(teamSourceCollectionMemoryPanelSource).toContain("TEAM_SOURCE_COLLECTION_MEMORY_HEIGHT_PANE");
    expect(teamSourceCollectionMemoryPanelStyles.sourceCollectionMemoryListShell).not.toContain("max-h-[44vh]");
    expect(teamSourceCollectionMemoryPanelStyles.sourceCollectionMemoryListShell).not.toContain("max-[860px]:max-h-[58vh]");
    expect(teamSourceCollectionMemoryPanelStyles.sourceCollectionMemoryListShell).toContain("[scrollbar-gutter:stable]");
    expect(routeSource).toContain("待质量审查");
    expect(routeSource).not.toContain("待质检");
    expect(routeSource).not.toContain("workflowSourceCollectionPrimaryButton");
    // Wave 8H: stage primary action labels live on TeamResearchStageLauncherPanel.
    expect(teamResearchStageLauncherPanelSource).toContain("启动设计");
    expect(teamResearchStageLauncherPanelSource).toContain("启动执行迭代");
    expect(routeSource).not.toContain("{researchWorkflowTeamSelected ? renderResearchWorkspaceNav() : null}");
    expect(routeSource).toContain("onSelectTeam: selectTeamRecord");
    expect(routeSource).toContain("args.onSelectTeam(team)");
    expect(createTeamsResearchNavigationSource).toContain("function selectTeamRecord");
    expect(createTeamsResearchNavigationSource).toContain("setResearchWorkspaceView(\"overview\")");
    expect(routeSource).toContain("createTeamsResearchNavigation({");
    expect(routeSource).not.toContain("{renderResearchWorkspaceNav()}");
    expect(routeSource).toContain("renderResearchStageLauncher");
    expect(routeSource).toContain("renderResearchOverviewSurface");
    // Board primary: overview | experiment/iteration stage | launcher hub.
    expect(routeSource).toContain("TeamResearchBoardPrimarySurface");
    expect(routeSource).toContain("boardPrimaryMode={boardPrimaryMode}");
    expect(routeSource).toContain("stageSlot=");
    expect(teamResearchBoardPrimarySurfaceSource).toContain('boardPrimaryMode === "stage"');
    expect(teamResearchBoardPrimarySurfaceSource).toContain("stageSlot");
    // Wave 8H: research graph / MVP console copy and ChallengeCup workspace live on launcher panel.
    expect(teamResearchStageLauncherPanelSource).toContain("研究关系图");
    expect(teamResearchStageLauncherPanelSource).toContain("researchStageHeaderActions");
    expect(teamResearchStageLauncherPanelSource).toContain("researchCanvasRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)");
    expect(researchWorkspaceModelSource).toContain("搜索、提炼、审查与入库");
    expect(researchWorkspaceModelSource).toContain("资料寻找 / 资料提炼 / 资料关系整理 / 资料入库");
    expect(researchWorkspaceModelSource).toContain("研究问题 / 假设 / 控制变量 / 冻结设计");
    expect(researchWorkspaceModelSource).toContain("执行批次 / 结果评估 / 消融归因 / 优化迭代");
    // Wave 8I: lifecycleProjection consumed by launcher; standalone page is action-first ledger.
    expect(teamResearchStageLauncherPanelSource).toContain("lifecycleProjection");
    expect(routeSource).toContain("data-product-workbench");
    expect(routeSource).toContain("ExperimentStageComposer");
    // Wave 8H: challengeProgramProjection is read inside TeamResearchStageLauncherPanel.
    expect(teamResearchStageLauncherPanelSource).toContain("challengeProgramProjection");
    expect(teamResearchPrimarySurfaceRenderersSource).toContain("ResearchProcessWorkspace");
    expect(teamResearchStageLauncherPanelSource).not.toContain("ResearchProcessWorkspace");
    expect(teamResearchStageLauncherPanelSource).not.toContain("ChallengeCupOperationsWorkspace");
    expect(routeSource).toContain("challengeCupResearchTeamSelected");
    expect(routeSource).not.toContain('useState<"workspace" | "progress">("workspace")');
    expect(routeSource).not.toContain("challengeTeamSurface");
    // Board/canvas shell owns mode chrome; Challenge progress is URL-panel state in the canonical workspace.
    expect(routeSource).toContain("TeamShellToolbar");
    expect(routeSource).not.toContain("<TeamShellModeSwitch");
    expect(routeSource).toContain("challengeWorkspaceContextHidden");
    expect(routeSource).toContain("challengeWorkspaceBody");
    expect(teamResearchStageLauncherPanelSource).toContain("MVP 黄金样例");
    expect(teamResearchStageLauncherPanelSource).toContain("3 题试运行");
    expect(teamResearchStageLauncherPanelSource).toContain("challengeTrialRevisionRequiredCount");
    expect(teamResearchStageLauncherPanelSource).toContain("MVP 需修订");
    expect(teamResearchStageLauncherPanelSource).toContain("后续规模化与深研");
    expect(teamResearchStageLauncherPanelSource).toContain("125 题批跑、三个深研案例和最终参赛封装均延后到 MVP 验收之后");
    expect(teamResearchStageLauncherPanelSource).toContain("stage1ComplianceReadiness.mvpManifest.completedQuestionCount");
    expect(teamResearchStageLauncherPanelSource).toContain("challengeProgramLoading");
    expect(teamResearchStageLauncherPanelSource).toContain("正在读取挑战杯 MVP 状态，不会显示旧科研流程");
    expect(teamResearchStageLauncherPanelSource).toContain('href={stageType === "knowledge_collection"');
    expect(teamResearchStageLauncherPanelSource).toContain('"#challenge-mvp-sample"');
    expect(teamResearchStageLauncherPanelSource).toContain('"#challenge-mvp-trials"');
    expect(teamResearchStageLauncherPanelSource).toContain('"#challenge-mvp-roadmap"');
    expect(teamResearchStageLauncherPanelSource).toContain("查看黄金样例");
    expect(teamResearchStageLauncherPanelSource).toContain("查看试运行结果");
    expect(teamResearchStageLauncherPanelSource).toContain("人工审核与机器验证分开记录");
    expect(teamResearchStageLauncherPanelSource).toContain("stage1.mvpManifest.trialQuestionIds ?? stage1.mvpManifest.testQuestionIds");
    expect(routeSource).not.toContain("测试入口待接入");
    expect(teamResearchStageLauncherPanelSource).toContain('blockers.includes("dashscope_qwen_provider_missing")');
    expect(teamResearchStageLauncherPanelSource).toContain('"BLOCKED · 待验证"');
    expect(teamResearchStageLauncherPanelSource).toContain("caseRecords[0]?.title");
    expect(teamResearchStageLauncherPanelSource).toContain("已设计 · 待执行");
    expect(teamResearchStageLauncherPanelSource).toContain("训练结果不参与本阶段完成判定");
    expect(teamResearchStageLauncherPanelSource).toContain("最近诊断单独展示，不覆盖主线结果");
    expect(teamResearchStageLauncherPanelSource).toContain("bestValidatedResultId");
    expect(teamResearchStageLauncherPanelSource).toContain("latestDiagnosticStatus");
    expect(teamResearchStageLauncherPanelSource).toContain("researchIterationLifecycleStatusLabel");
    // Product standalone stage page: compact status + ledger only (no hero dump).
    expect(routeSource).toContain("research-stage-detail-status");
    expect(routeSource).toContain("experimentPlanningStatusQuery");
    expect(routeSource).toContain("research-stage-workbench-body");
    expect(routeSource).toContain("experimentPlanningStatusQuery={experimentPlanningStatusQuery}");
    expect(routeAndPureSource).toContain("researchDiagnosticStatusLabel");
    expect(experimentLoopModelSource).toContain('smoke_needs_review: { zh: "Smoke 待复核", en: "smoke needs review" }');
    expect(experimentLoopModelSource).toContain('full_run_needs_review: { zh: "正式实验待复核", en: "formal run needs review" }');
    expect(teamResearchStageLauncherPanelSource).toContain("团队记忆");
    expect(teamResearchStageLauncherPanelSource).toContain("已用记忆");
    expect(teamResearchStageLauncherPanelSource).toContain("forbiddenDuplicateExperimentCount");
    expect(researchMemoryEvidencePanelSource).toContain("查看 Claim Map 与变量边界");
    expect(researchMemoryEvidencePanelSource).toContain("claimStatusCounts");
    expect(researchMemoryEvidencePanelSource).toContain("allowedVariableContract");
    expect(researchMemoryEvidencePanelSource).toContain("claimMap");
    expect(researchMemoryEvidencePanelSource).toContain("data-memory-context-id");
    // Wave 8H: compact memory mount stays on launcher; stage page stays action-first.
    expect(teamResearchStageLauncherPanelSource).toContain("ResearchMemoryEvidencePanel");
    expect(teamResearchStageLauncherPanelSource).toContain("stage={stage}");
    expect(routeSource).toContain('stageView="iteration"');
    expect(researchWorkspaceModelSource).not.toContain('value === "source_collection"');
    expect(researchWorkspaceModelSource).toContain('value === "workflow" || value === "overview"');
    expect(teamResearchWorkflowPanelHostSource).toContain('id="research-workflow-overview"');
    expect(routeSource).toContain("TeamResearchWorkflowPanelHost");
    expect(researchWorkspaceModelSource).toContain('knowledge_collection: "research-workflow-knowledge-collection"');
    expect(teamSourceCollectionOverviewPanelSource).toContain('id="research-workflow-source-collection"');
    expect(routeAndPureSource).toContain('id="research-organization-canvas"');
    expect(routeSource).toContain('researchWorkspaceView === "canvas"');
    expect(routeSource).toContain("teamShellMode === \"canvas\"");
    expect(routeSource).toContain("const researchCanvasVisible = teamShellMode === \"canvas\"");
    expect(routeSource).toContain("showNodeBindingPanel = researchCanvasVisible && !researchCanvasReadOnly");
    expect(routeSource).toContain("renderResearchCanvasReadOnlyPanel");
    expect(routeSource).toContain("researchCanvasReadOnly ? renderResearchCanvasReadOnlyPanel() : null");
    expect(routeSource).toContain("只读组织画布");
    expect(routeSource).toContain("canvasNodeStatusLabel");
    expect(teamRouteShellModelSource).toContain("已绑定");
    expect(teamRouteShellModelSource).toContain("专属管理员");
    expect(routeSource).toContain("暂无信息线");
    expect(routeSource).toContain("没有可展开的信息线");
    expect(routeSource).toContain('useState<ResearchCanvasLayoutMode>("auto")');
    expect(routeSource).toContain("autoLayoutResearchCanvasNodes(canvasNodes, organizationEdges)");
    expect(routeSource).toContain("const researchCanvasAutoLayoutActive = researchCanvasReadOnly && researchCanvasLayoutMode === \"auto\"");
    expect(routeSource).toContain("const displayCanvasNodes = researchCanvasAutoLayoutActive ? autoLayoutCanvasNodes : canvasNodes");
    expect(routeSource).toContain("hideCanvasToolbar");
    expect(routeSource).toContain("trailingActions");
    expect(canvasGeometrySource).toContain("RESEARCH_CANVAS_AUTO_LAYOUT_LAYER_GAP");
    expect(canvasGeometrySource).toContain("RESEARCH_CANVAS_AUTO_LAYOUT_ROW_GAP");
    expect(canvasGeometrySource).toContain("researchCanvasRoleLayer");
    // Stage switch lives on the flow strip (ResearchStageNav), not a "返回三阶段" link.
    expect(routeSource).toContain("ResearchStageNav");
    expect(routeSource).toContain("onNodePointerDown: startNodeDrag");
    expect(routeSource).toContain("onNodePointerDown={p.onNodePointerDown}");
    expect(routeSource).toContain("onPointerDown={researchCanvasReadOnly ? undefined : (event) => onNodePointerDown?.(event, node)}");
    expect(routeSource).toContain("onPointerMove={researchCanvasReadOnly ? undefined : onNodePointerMove}");
    expect(routeSource).toContain("onPointerUp={researchCanvasReadOnly ? undefined : onNodePointerUp}");
    expect(routeSource).toContain("researchCanvasReadOnly ? nodeReadOnlyClassName : \"\"");
    expect(routeSource).toContain("styles.canvasReadOnlyPanel");
    expect(routeSource).toContain("showNodeBindingPanel");
    expect(routeSource).toContain("showWorkflowPanel");
    expect(routeSource).toContain("showResearchSourceCollection");
    expect(routeSource).toContain("resolveTeamDetailLoadMode");
    expect(routeSource).toContain("resolveTeamCanvasQueryEnabled");
    expect(routeSource).toContain("resolveSourceCollectionRunsQueryEnabled");
    expect(routeSource).toContain("queryKeys.team(effectiveTeamId, teamDetailLoadMode)");
    expect(routeSource).toContain("detail: teamDetailLoadMode");
    expect(routeSource).toContain("enabled: teamCanvasQueryEnabled");
    expect(routeSource).toContain("sourceCollectionAgentIdsFromTeam(selectedTeam, canvas)");
    expect(routeSource).toContain("sourceCollectionOwnerAgentIdFromTeam(selectedTeam, canvas)");
    expect(routeSource).toContain("researchSourceCollectionRoute");
    expect(routeSource).toContain("teamWorkspaceRoute");
    expect(routeSource).toContain("researchCanvasRoute");
    expect(routeSource).toContain("teamChatRoomRoute");
    expect(routeSource).toContain("返回团队页面");
    expect(routeSource).toContain("返回${RESEARCH_STAGE_TERMS.knowledge_collection.zh}");
    // Wave 8I: stage-page chat back-link copy lives on the standalone stage panel.
    expect(routeSource).toContain("返回阶段页");
    expect(routeSource).toContain("renderSourceCollectionConversation");
    expect(routeSource).toContain("renderSourceCollectionControlsPanel");
    expect(routeSource).toContain("${RESEARCH_STAGE_TERMS.knowledge_collection.zh}工作台");
    expect(routeSource).not.toContain("挑战杯ai科研团队 / 知识搜集阶段");
    expect(routeSource).toContain("researchStageAgentDirectChatRoute");
    expect(routeSource).toContain("openSourceCollectionStageAgentChat");
    expect(routeSource).not.toContain("sourceCollectionStageChatRoute");
    expect(routeSource).not.toContain("SOURCE_COLLECTION_STAGE_CHAT_PURPOSE");
    expect(routeSource).not.toContain("sourceCollectionTraceMessages");
    expect(routeSource).not.toContain("KV 缓存门禁已写入本轮搜集");
    expect(routeSource).not.toContain("执行模型：见当前步骤 Agent 配置");
    expect(routeAndPureSource).toContain("sourceCollectionPromptCacheModelDisplay");
    expect(routeSource).not.toContain("本轮使用 ${sourceCollectionPromptCachePolicy?.modelName");
    // Wave 8R: prompt cache policy is applied on workflow start mutations.
    expect(teamWorkflowStartMutationsSource).toContain("promptCachePolicy: SOURCE_COLLECTION_PROMPT_CACHE_POLICY");
    expect(presentationModelSource).toContain('SOURCE_COLLECTION_PROMPT_CACHE_MODEL_LABEL = "configured prompt-cache model"');
    expect(routeSource).not.toContain('modelId: "houmo_qwen35_9b_agent"');
    // Operation-failed aggregate lives in pure operation-flags helper after R2-q.
    expect(routeSource).toMatch(/selectedTeamStartResearchStageError|deriveSourceCollectionOperationFlags/);
    expect(teamRouteShellModelSource).toContain("continuedSourceRunRef");
    expect(routeSource).toContain("researchStageStartFeedbackText");
    expect(routeSource).toContain("sourceCollectionSearchExecution");
    expect(routeSource).toContain("selectedTeamInitialSourceCollectionSearchResult");
    expect(routeSource).toContain("selectedSourceCollectionSearchExecutionResult");
    const sourceCollectionBackgroundRefreshSource = routeSource.slice(
      routeSource.indexOf("const selectedSourceCollectionActiveWorkRun"),
      routeSource.indexOf("const sourceCollectionAcceptedBackgroundActive"),
    );
    expect(sourceCollectionBackgroundRefreshSource).not.toContain("researchStageRoundStatusQueryKey(selectedTeam.teamId)");
    expect(routeSource).toContain("sourceCollectionStageWritebackRefetchInterval");
    expect(routeSource).toContain("SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS");
    expect(routeSource).toContain("sourceCollectionStageSyncUntilMs");
    expect(routeSource).toContain("sourceCollectionStageWritebackSyncActive");
    expect(routeSource).toContain("sourceCollectionPendingStageTaskIds");
    expect(routeSource).toContain("sourceCollectionPendingStageTaskIdList");
    expect(routeSource).toContain("sourceCollectionStageWritebackAwaitingTask");
    expect(routeSource).toContain("setSourceCollectionPendingStageTaskIds");
    // Wave 8R: pending stage task id capture lives on start mutations hook.
    expect(teamWorkflowStartMutationsSource).toContain("payload.taskId");
    expect(stageProjectionSource).toContain("正在同步 Agent 结果");
    expect(stageProjectionSource).toContain("Syncing Agent result");
    expect(researchWorkflowResourcesSource).toContain("refetchInterval: (query) =>");
    expect(researchWorkflowResourcesSource).toContain("query.state.data as ResearchStageRoundStatusPayload | null | undefined");
    expect(routeSource).toContain("sourceCollectionStageWritebackSyncActive,");
    // Wave 8S: summary writeback interval is applied from useSourceCollectionRunQueries.
    expect(sourceCollectionRunQueriesSource).toContain("sourceCollectionStageWritebackRefetchInterval(");
    expect(researchWorkflowResourcesSource).toContain("refetchInterval: () => sourceCollectionStageWritebackRefetchInterval(");
    const sourceQualityStatusQuerySource = researchWorkflowResourcesSource.slice(
      researchWorkflowResourcesSource.indexOf("const sourceQuality = useQuery"),
      researchWorkflowResourcesSource.indexOf("const paperNoteChunks = useQuery"),
    );
    expect(sourceQualityStatusQuerySource).toContain("refetchInterval");
    expect(sourceQualityStatusQuerySource).toContain("stageWritebackSync.active");
    expect(routeSource).toContain("SourceCollectionSummaryPayload");
    expect(routeSource).toContain("sourceCollectionSummaryQueryKey");
    // Wave 8S: SC summary query lives on useSourceCollectionRunQueries; path lives in sourceCollection.ts.
    expect(sourceCollectionRunQueriesSource).toContain("fetchSourceCollectionSummary");
    expect(sourceCollectionApiSource).toContain("/workflow-orchestration/source-collection/summary");
    expect(routeSource).toContain("sourceCollectionSummaryQueryPrefix");
    expect(researchWorkflowResourcesSource).toContain("includeValidation: false");
    expect(researchWorkflowResourcesSource).toContain("includeStore: false");
    expect(researchWorkflowResourcesSource).toContain("const TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT = 80;");
    expect(researchWorkflowResourcesSource).not.toContain("const TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT = 500;");
    expect(routeSource).toContain("sourceCollectionWorkspaceSelected");
    expect(routeSource).toContain("teamWorkflowCandidateListEnabled");
    expect(routeSource).toContain("teamWorkflowGraphEnabled");
    expect(routeSource).toContain("teamWorkflowKnowledgeIngestionEnabled");
    expect(routeSource).toContain("teamWorkflowSourceQualityEnabled");
    expect(routeSource).toContain("researchStageRoundStatusEnabled");
    expect(routeSource).toContain("sourceCollectionSummaryStageRound");
    expect(routeSource).toContain("sourceCollectionSummaryCounts");
    expect(routeSource).toContain("summarySourceCollectionActiveWorkRun");
    expect(routeSource).toContain("workflow: teamWorkflowOrchestrationEnabled");
    expect(routeSource).toContain("teamWorkflowOrchestrationEnabled");
    expect(routeSource).toContain("processCanvasHome");
    expect(routeSource).toContain("const sourceCollectionFindingDetailsVisible = Boolean(");
    const sourceCollectionFindingDetailsVisibleSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionFindingDetailsVisible = Boolean("),
      routeSource.indexOf("const runtimeSummaryQuery = useQuery({"),
    );
    expect(sourceCollectionFindingDetailsVisibleSource).toContain("sourceCollectionWorkspaceSelected");
    expect(sourceCollectionFindingDetailsVisibleSource).toContain("selectedSourceCollectionRunEffectiveId");
    expect(sourceCollectionFindingDetailsVisibleSource).toContain('selectedSourceCollectionStageId === "finding"');
    expect(sourceCollectionFindingDetailsVisibleSource).not.toContain("sourceCollectionSummaryQuery.isSuccess");
    expect(sourceCollectionFindingDetailsVisibleSource).not.toContain("sourceCollectionSummaryQuery.isError");
    // Wave 8S: detail query enablement lives on useSourceCollectionRunQueries.
    expect(sourceCollectionRunQueriesSource).toContain("sourceCollectionRecordsQueryEnabled");
    expect(sourceCollectionRunQueriesSource).toContain("sourceCollectionAssignmentsQueryEnabled");
    expect(sourceCollectionRunQueriesSource).toContain("sourceCollectionRunStatusQueryEnabled");
    expect(sourceCollectionRunQueriesSource).toContain("enabled: sourceCollectionRunStatusQueryEnabled");
    expect(sourceCollectionRunQueriesSource).toContain("enabled: sourceCollectionRecordsQueryEnabled");
    expect(sourceCollectionRunQueriesSource).toContain("enabled: sourceCollectionAssignmentsQueryEnabled");
    expect(routeSource).toContain("useSourceCollectionRunQueries({");
    const sourceCollectionRecordsDataLoadingSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionRecordsDataLoading = Boolean("),
      routeSource.indexOf("const sourceCollectionAssignmentsDataLoading = Boolean("),
    );
    expect(sourceCollectionRecordsDataLoadingSource).toContain("sourceCollectionRecordsQuery.isPending");
    expect(sourceCollectionRecordsDataLoadingSource).toContain("sourceCollectionRunStatusQuery.isPending");
    expect(sourceCollectionRecordsDataLoadingSource).not.toContain("sourceCollectionSummaryQuery.isPending");
    const sourceCollectionPrimaryLoadingSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionPrimaryDataLoading = Boolean("),
      routeSource.indexOf("const sourceCollectionSourceQualityLoading = Boolean("),
    );
    expect(sourceCollectionPrimaryLoadingSource).toContain("sourceCollectionSummaryQuery.isPending");
    expect(sourceCollectionPrimaryLoadingSource).not.toContain("researchStageRoundStatusQuery.isPending");
    expect(sourceCollectionPrimaryLoadingSource).not.toContain("teamWorkflowCandidatesQuery.isPending");
    expect(routeSource).toContain("sourceCollectionRecordsDataLoading");
    expect(routeSource).toContain("sourceCollectionAssignmentsDataLoading");
    expect(routeSource).toContain("sourceCollectionCollectedCountText");
    expect(routeSource).toContain("sourceCollectionSearchOpenAssignmentCountText");
    expect(routeSource).toContain("sourceCollectionQueryCountText");
    expect(stageProjectionSource).toContain("已有部分资料");
    expect(stageProjectionSource).toContain("Partial output ready");
    expect(stageProjectionSource).toContain("historicalTask");
    expect(stageProjectionSource).toContain("历史任务 ${historicalTaskCount} 已忽略");
    expect(routeSource).toContain("createSourceCollectionController");
    expect(routeSource).toContain("sourceCollectionStandaloneStageModules");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("<TeamStageCommandBar");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("<TeamStagePipeline");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("<TeamStageCard");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("TeamSourceCollectionStageActionIcon");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("steps={commandSteps}");
    expect(routeSource).toContain("sourceCollectionConsoleStatusText");
    expect(sourceCollectionControllerSource).toContain("sourceCollectionConsoleStatusText");
    expect(sourceCollectionControllerSource).toContain("sourceCollectionBoardNextStepLabel");
    expect(sourceCollectionControllerSource).toContain("sourceCollectionCollectedCountLabel");
    expect(sourceCollectionControllerSource).toContain('key: "progress"');
    expect(sourceCollectionControllerSource).toContain("emphasis: \"accent\"");
    expect(sourceCollectionControllerSource).not.toContain("sourceCollectionSearchOpenAssignmentCountLabel");
    expect(sourceCollectionControllerSource).not.toContain("sourceCollectionDownstreamOpenAssignmentCountLabel");
    expect(sourceCollectionControllerSource).not.toContain("sourceCollectionQueryCountLabel");
    expect(sourceCollectionControllerSource).not.toContain("sourceCollectionPromptCacheStatusLabel");
    expect(routeSource).not.toContain("researchStageRoundStatusQueryKey(effectiveTeamId || \"none\"),\n    queryFn: () =>\n      fetchJson<ResearchStageRoundStatusPayload>(\n        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/stage-rounds/status`,\n      ),\n    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data)");
    expect(routeSource).not.toContain("queryKeys.teamWorkflowCandidates(effectiveTeamId || \"none\", TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT),\n    queryFn: () =>\n      fetchJson<TeamWorkflowCandidateListPayload>(\n        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/candidates?limit=${TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT}`,\n      ),\n    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data)");
    expect(routeSource).not.toContain("enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data)");
    expect(routeSource.match(/&& teamWorkflowQuery\.data\)/g) ?? []).toEqual([]);

    // R2-d: teams list / agent summary / bus bootstrap live in useTeamsCatalogQueries.
    expect(useTeamsCatalogQueriesSource).toContain("export function useTeamsCatalogQueries");
    expect(useTeamsCatalogQueriesSource).toContain("queryFn: ({ signal }) => listTeams({ signal })");
    expect(useTeamsCatalogQueriesSource).toContain("TEAM_BOOTSTRAP_REFETCH_STATUSES");
    expect(useTeamsCatalogQueriesSource).toContain("listProjectAgentBusTimeline(PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT, { signal })");
    expect(routeSourceRaw).toContain("useTeamsCatalogQueries({");
    expect(routeSourceRaw).not.toContain("const teamsQuery = useQuery({");
    // R2-e: team detail + kind flags live in useTeamsSelectedTeamDetail.
    expect(useTeamsSelectedTeamDetailSource).toContain("export function useTeamsSelectedTeamDetail");
    expect(useTeamsSelectedTeamDetailSource).toContain(
      "fetchTeam(effectiveTeamId, { signal, detail: teamDetailLoadMode })",
    );
    expect(routeSourceRaw).toContain("useTeamsSelectedTeamDetail({");
    expect(routeSourceRaw).not.toContain("const teamDetailQuery = useQuery<Team>({");
    expect(useTeamsSelectedTeamDetailSource).not.toContain("fetchJson<TeamOrganizationCanvas>");
    expect(useTeamsSelectedTeamDetailSource).not.toContain("queryKey: researchProjectQueryKey");
    // Phase 3: organization canvas query lives in useTeamsCanvasProjection.
    expect(useTeamsShellCanvasWorkspaceSource).toContain("fetchTeamCanvas(effectiveTeamId, { signal })");
    // Phase 1 state-machine: project/run list queries live in useSourceCollectionWorkspace.
    expect(useSourceCollectionWorkspaceSource).toContain("queryKey: researchProjectQueryKey(effectiveTeamId || \"none\")");
    expect(useSourceCollectionWorkspaceSource).toContain("activeSourceCollectionResearchProjectId");
    expect(routeSource).toContain("useSourceCollectionWorkspace");
    // Phase 2: experiment/loop drafts + secondary queries live in useResearchExperimentWorkspace.
    expect(routeSourceRaw).toContain("useResearchExperimentWorkspace");
    expect(routeSourceRaw).not.toContain("const [experimentBaselineArtifactDraft, setExperimentBaselineArtifactDraft]");
    expect(routeSourceRaw).not.toContain("} = useTeamResearchSecondaryQueries({");
    expect(useResearchExperimentWorkspaceSource).toContain("useTeamResearchSecondaryQueries");
    expect(useResearchExperimentWorkspaceSource).toContain("experimentBaselineArtifactDraft");
    // Phase 3: shell/canvas state + canvas projection live in useTeamsShellCanvasWorkspace module.
    expect(routeSourceRaw).toContain("useTeamsShellCanvasWorkspace");
    expect(routeSourceRaw).toContain("useTeamsCanvasProjection");
    expect(routeSourceRaw).not.toContain('const [selectedTeamId, setSelectedTeamId] = useState("")');
    expect(routeSourceRaw).not.toContain("const durableCanvas = canvasFromTeamOrFallback");
    expect(useTeamsShellCanvasWorkspaceSource).toContain("resolveTeamCanvasQueryEnabled");
    expect(useTeamsShellCanvasWorkspaceSource).toContain("autoLayoutResearchCanvasNodes");
    // R2-e team detail + R2-d catalog list both use signal-bearing queryFn.
    expect(useTeamsSelectedTeamDetailSource).toContain("queryFn: ({ signal }) =>");
    expect(useTeamsSelectedTeamDetailSource.match(/queryFn: \(\) =>/g) ?? []).toEqual([]);
    expect(useTeamsCatalogQueriesSource).toContain("queryFn: ({ signal }) =>");
    expect(useTeamsCatalogQueriesSource.match(/queryFn: \(\) =>/g) ?? []).toEqual([]);
    expect(teamWorkflowResourceDemandSource).toContain("export function resolveTeamWorkflowResourceDemand");
    expect(teamsWorkbenchChromeSource).toContain("export const teamsWorkbenchStyles");
    // R2-l: stage-return + search-accepted invalidation live in useSourceCollectionPresentationEffects.
    const effectsStageReturnRefreshSource = useSourceCollectionPresentationEffectsSource.slice(
      useSourceCollectionPresentationEffectsSource.indexOf("if (!researchWorkflowTeamSelected || !pageVisible"),
      useSourceCollectionPresentationEffectsSource.indexOf("if (!selectedTeamId || !selectedSourceCollectionRunEffectiveId || !selectedSourceCollectionSearchAccepted"),
    );
    expect(effectsStageReturnRefreshSource).toContain("requestedSourceCollectionStage");
    expect(effectsStageReturnRefreshSource).not.toContain("researchStageRoundStatusQueryKey(selectedTeam.teamId)");
    expect(effectsStageReturnRefreshSource).not.toContain("queryKeys.teamWorkflowCandidates(selectedTeam.teamId");
    expect(effectsStageReturnRefreshSource).not.toContain("sourceQualityStatusQueryKey(selectedTeam.teamId)");
    expect(effectsStageReturnRefreshSource).toContain("sourceCollectionRunRecordsQueryKey(selectedSourceCollectionRunEffectiveId)");
    const searchAcceptedStart = useSourceCollectionPresentationEffectsSource.indexOf(
      "if (!selectedTeamId || !selectedSourceCollectionRunEffectiveId || !selectedSourceCollectionSearchAccepted",
    );
    // R2-l: effect ends at next candidate-hygiene useEffect (or file end).
    const searchAcceptedEndMarker = useSourceCollectionPresentationEffectsSource.indexOf(
      "if (!selectedSourceCollectionCandidateId)",
      searchAcceptedStart,
    );
    const sourceCollectionSearchAcceptedRefreshSource = useSourceCollectionPresentationEffectsSource.slice(
      searchAcceptedStart,
      searchAcceptedEndMarker > 0 ? searchAcceptedEndMarker : searchAcceptedStart + 2000,
    );
    expect(sourceCollectionSearchAcceptedRefreshSource).toContain("selectedSourceCollectionSearchAccepted");
    expect(sourceCollectionSearchAcceptedRefreshSource).toContain("sourceCollectionSummaryQueryKey(selectedTeamId");
    expect(sourceCollectionSearchAcceptedRefreshSource).not.toContain("queryKeys.teamWorkflowCandidates(selectedTeam.teamId");
    expect(sourceCollectionSearchAcceptedRefreshSource).not.toContain("researchStageRoundStatusQueryKey(selectedTeam.teamId)");
    expect(sourceCollectionSearchAcceptedRefreshSource).not.toContain("queryKeys.teamWorkflowKnowledgeIngestionStatus(selectedTeam.teamId)");
    expect(sourceCollectionSearchAcceptedRefreshSource).not.toContain("sourceCollectionRunStatus?.runStatus");
    expect(sourceCollectionSearchAcceptedRefreshSource).not.toContain("sourceCollectionRunStatus?.summary.recordCount");
    // Wave 8P: skippedDuplicateCount lives on SC mutation payload model + controls workspace copy.
    expect(teamSourceCollectionControlsWorkspacePanelSource).toContain("skippedDuplicateCount");
    // Wave 8M: duplicate-skip feedback lives on controls workspace panel.
    expect(teamSourceCollectionControlsWorkspacePanelSource).toContain("条重复跳过");
    expect(routeSource).toContain("selectedSourceCollectionSearchAccepted");
    expect(teamSourceCollectionShellModelSource).toContain('finding: ["source_finder"]');
    expect(teamSourceCollectionShellModelSource).toContain('extraction: ["source_extractor"]');
    expect(teamSourceCollectionShellModelSource).toContain('relations: ["source_relation_mapper"]');
    expect(teamSourceCollectionShellModelSource).toContain('ingestion: ["source_ingestor"]');
    expect(presentationModelSource).toContain('source_finder: "资料寻找 Agent"');
    expect(presentationModelSource).toContain('source_extractor: "资料提炼 Agent"');
    expect(presentationModelSource).toContain('source_relation_mapper: "资料关系整理 Agent"');
    expect(presentationModelSource).toContain('source_ingestor: "资料入库 Agent"');
    expect(routeSource).toContain('return "relations";');
    expect(routeAndPureSource).toContain("SOURCE_COLLECTION_TEAM_AGENT_ROLES");
    expect(researchStageRolesSource).toContain('key: "source_relation_mapper"');
    expect(routeSource).toContain("const sourceCollectionRelationMapperAgentId");
    expect(routeSource).toContain("createdByAgent: sourceCollectionRelationMapperAgentId");
    expect(routeSource).not.toContain("createdByAgent: sourceCollectionQualityAgentId");
    expect(routeSource).not.toContain("sourceCollectionStageRoomKey");
    expect(routeSource).toContain("openSourceCollectionStageAgentChat");
    expect(routeSource).toContain("repairChallengeCupTeamAgentsMutation.mutate(selectedTeam.teamId)");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("进入 Agent 私聊");
    expect(routeSource).toContain("researchStageStartFeedbackText");
    expect(teamRouteShellModelSource).toContain("已复用正在运行的");
    expect(routeSource).not.toContain("像对话一样记录：搜索了什么");
    expect(routeSource).not.toContain("搜集批次已启动，等待功能 Agent 回写");
    expect(routeSource).not.toContain("后续接入全文下载或提炼器时");
    expect(routeSource).not.toContain("通常无需修改");
    expect(routeSource).not.toContain("一键生成搜索计划、团队分工");
    expect(routeSource).not.toContain("搜索计划、步骤记录、资料记录和候选镜像都已落盘");
    // Wave 8I: stage standalone page is a product workbench (no team rail dump wall).
    expect(routeSource).toContain("返回团队首页");
    expect(routeSource).toContain("实验规划工作台");
    expect(routeSource).toContain('data-product-workbench="true"');
    expect(routeSource).toContain("experimentPlanningStatusQueryKey");
    expect(routeSource).toContain("renderExperimentPlanningLedgerPanel");
    expect(routeSource).toContain("TeamExperimentPlanningLedgerPanel");
    // Product workbench: stepped ledger, not the old full-page form dump.
    expect(teamExperimentPlanningLedgerPanelSource).toContain("experiment-planning-workbench");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("EXPERIMENT_WORKBENCH_STEPS");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("TeamExperimentMethodPanel");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("TeamExperimentHypothesisGovernancePanel");
    expect(routeSource).toContain('researchWorkspaceView === "experiment" || researchWorkspaceView === "iteration"');
    expect(teamExperimentHypothesisGovernancePanelSource).toContain("人工批准用于设计");
    expect(teamExperimentHypothesisGovernancePanelSource).toContain("创建新设计修订");
    expect(teamExperimentHypothesisGovernancePanelSource).toContain("不会自动冻结");
    expect(teamExperimentHypothesisGovernancePanelSource).toContain("candidate.approvedForExperiment");
    expect(routeSource).toContain("experimentMethodCatalogQueryKey");
    // Wave 8S: experiment method catalog gating lives on research secondary queries.
    expect(teamResearchSecondaryQueriesSource).toContain('["overview", "experiment"].includes(options.researchWorkspaceView)');
    // Wave 8H: overview experiment method quick-select is on TeamResearchStageLauncherPanel.
    expect(teamResearchStageLauncherPanelSource).toContain("researchExperimentMethodQuickSelect");
    expect(teamResearchStageLauncherPanelSource).toContain("selectedExperimentAdapterStatus");
    expect(teamResearchStageLauncherPanelSource).toContain("selectedExperimentAdapterReason");
    expect(teamResearchStageLauncherPanelSource).toContain("activeExperimentContractAdapterSelection");
    expect(teamResearchStageLauncherPanelSource).toContain("selectedExperimentResolvedAdapterId");
    expect(teamResearchStageLauncherPanelSource).toContain("executableAlternativeMethods");
    expect(teamResearchStageLauncherPanelSource).toContain("可执行替代");
    expect(teamResearchStageLauncherPanelSource).toContain("已登记");
    expect(teamResearchStageLauncherPanelSource).toContain("当前模式尚未自动就绪");
    expect(teamResearchStageLauncherPanelSource).toContain('ariaLabel={lang === "zh" ? "选择实验方式" : "Select experiment method"}');
    expect(teamResearchStageLauncherPanelSource).toContain("<VStringSelect");
    expect(routeSource).toContain("preferredExperimentMethod=");
    // Wave 8S / Phase 2: methods endpoint on secondary queries; route consumes via experiment workspace.
    expect(teamExperimentApiSource).toContain("/workflow-orchestration/experiments/methods");
    expect(teamResearchSecondaryQueriesSource).toContain("fetchExperimentMethodCatalog<");
    expect(routeSourceRaw).toContain("useResearchExperimentWorkspace");
    expect(routeSourceRaw).not.toContain("useTeamResearchSecondaryQueries({");
    // SC run detail queries composed inside useSourceCollectionWorkspace (Phase 1).
    expect(useSourceCollectionWorkspaceSource).toContain("useSourceCollectionRunQueries");
    expect(workflowToneSource).toContain("export function workflowQualityTone");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("activeContract={activeExperimentContract}");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("onSubmit={createExperimentPlanFromWorkspace}");
    expect(teamExperimentMethodPanelSource).toContain("catalog.researchModes.map");
    expect(teamExperimentMethodPanelSource).toContain("实验配置");
    expect(teamExperimentMethodPanelSource).toContain("实验目的");
    expect(teamExperimentMethodPanelSource).toContain("验证方法");
    expect(teamExperimentMethodPanelSource).toContain("buildExperimentPlanMethodRequest");
    expect(teamExperimentMethodPanelSource).toContain("保存为新版本");
    expect(teamExperimentMethodPanelSource).toContain("执行器尚未就绪");
    expect(teamExperimentMethodPanelStyles.methodGrid).toContain("max-[560px]:grid-cols-[minmax(0,1fr)]");
    // Single-column form — no empty half / forced min-height.
    expect(teamExperimentMethodPanelStyles.form).toContain("grid-cols-1");
    expect(teamExperimentMethodPanelStyles.form).not.toContain("min-h-[18rem]");
    expect(teamExperimentApiSource).toContain("baseline-artifact");
    expect(teamExperimentLoopMutationsSource).toContain("registerTeamExperimentBaselineArtifact<");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("登记基线工件");
    expect(teamExperimentPlanningLedgerPanelSource).toMatch(
      /const canRegisterBaselineArtifact[\s\S]*?&& designExecutionAllowed[\s\S]*?&& !activePlan\.baselineSelection\.activeBaselineReady/,
    );
    expect(routeSource).toContain("reproductionCommand");
    expect(teamExperimentLoopMutationsSource).toContain("runTeamExperimentSmoke");
    expect(teamExperimentApiSource).toContain("smoke-run");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("运行受控 Smoke");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("activePlan.readiness.readyForBoundedSmokeRun");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("runExperimentSmokeFromWorkspace");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("VMetricChip");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("VStatusChip");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("activeSmokeRun.smokeRunId");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("activeSmokeRun.artifactHash");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("activeSmokeRun.proxyOnly");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("activeSmokeRun.boundaries");
    expect(teamExperimentPlanningLedgerPanelSource).toMatch(
      /const statusPayload =\s*experimentPlanningStatus\s*\?\? latestFreezePayload\?\.experimentStatus/,
    );
    expect(teamExperimentPlanningLedgerPanelSource).toMatch(
      /const activePlan =\s*statusPayload\?\.activePlan\s*\?\? latestFreezePayload\?\.plan/,
    );
    expect(teamExperimentApiSource).toContain("smoke-result");
    expect(teamExperimentLoopMutationsSource).toContain("registerTeamExperimentSmokeResult<");
    expect(routeAndPureSource).toContain("ExperimentSmokeResultRecord");
    expect(routeAndPureSource).toContain("activeSmokeResult");
    expect(routeAndPureSource).toContain("gateDecision");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("登记 smoke 结果");
    expect(routeAndPureSource).toContain("needs_review");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("full-run 已解锁");
    expect(routeAndPureSource).toContain("readyForSmoke");
    expect(routeAndPureSource).toContain("baselineSelection");
    expect(routeAndPureSource).toContain("readyForFullRun");
    expect(teamExperimentLoopMutationsSource).toContain("No training execution was triggered.");
    expect(routeSource).toContain("迭代优化工作台");
    expect(routeSource).toContain("renderResearchStageStandalonePage");
    // F4: experiment stage chrome via createExperimentController + ExperimentStageComposer
    expect(routeSource).toContain("createExperimentController");
    expect(routeSource).toContain("ExperimentStageComposer");
    expect(routeSource).toContain("data-product-workbench");
    expect(teamWorkflowStatusPanelsSource).toContain("资料提炼 Agent");
    expect(teamWorkflowStatusPanelsSource).toContain("入库审核状态");
    expect(teamWorkflowStatusPanelsSource).toContain("模型调用证据链");
    expect(teamWorkflowStatusPanelsSource).toContain("证据登记，不是正式知识");
    // CandidateStore boundary copy (keeps formal Knowledge/RAG/Graph writes off).
    expect(teamWorkflowStatusPanelsSource).toContain("CandidateStore 快照 · 正式知识/RAG/图谱写入关闭");
    expect(teamWorkflowStatusPanelsSource).toContain("只写 CandidateStore");
    expect(routeSource).toContain("TeamSourceCollectionOverviewPanel");
    expect(teamSourceCollectionOverviewPanelSource).toContain("workflowSourceCollectionPanel");
    expect(teamResearchWorkflowStageModulesSource).toContain("资料搜索执行");
    expect(routeSource).toContain("sourceCollectionOverviewSummary");
    expect(routeSource).toContain("sourceCollectionOverviewStats");
    expect(routeSource).toContain("sourceCollectionOverviewPlan");
    expect(routeSource).toContain("TeamSourceCollectionRunSettingsPanel");
    expect(routeSource).toContain("onDraftChange:");
    expect(routeSource).toContain("setSourceCollectionDraft");
    expect(teamSourceCollectionRunSettingsPanelSource).toContain("启动搜集批次");
    expect(teamSourceCollectionRunSettingsPanelSource).toContain("workflowSourceCollectionForm");
    expect(teamSourceCollectionRunSettingsPanelSource).toContain("wrapInDetails");
    expect(routeSource).toContain("TeamSourceCollectionFindingDetailsPanel");
    expect(routeSource).toContain("sourceCollectionFindingRunOptions");
    expect(routeSource).toContain("sourceCollectionFindingAssignments");
    expect(routeSource).toContain("storageActions: renderSourceCollectionStorageActions()");
    expect(teamSourceCollectionFindingDetailsPanelSource).toContain("最近批次");
    expect(teamSourceCollectionFindingDetailsPanelSource).toContain("查询与分工详情");
    expect(teamSourceCollectionFindingDetailsPanelSource).toContain("assignmentEmptyMessage");
    expect(routeSource).toContain("手工回写一条搜集结果");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("回写并导入候选");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("原始位置");
    expect(routeSource).toContain("不触发外部搜索，不写正式知识/RAG/图谱");
    expect(teamWorkflowStatusPanelsSource).toContain("正式知识写入关闭");
    expect(teamWorkflowStatusPanelsSource).toContain("入库关系图");
    expect(routeSource).toContain("Agent 生成关系图");
    expect(teamWorkflowStatusPanelsSource).toContain("CandidateStore 快照 · 正式知识/RAG/图谱写入关闭");
    expect(teamWorkflowStatusPanelsSource).toContain("paper_note 分块计划");
    expect(teamWorkflowStatusPanelsSource).toContain("资料提炼复核");
    expect(routeSource).toContain("通过复核");
    expect(routeSource).toContain("退回补资料");
    expect(teamWorkflowStatusPanelsSource).toContain("Source extraction Agent");
    expect(teamResearchWorkflowStageModulesSource).toContain("TeamWorkflowCandidatePreviewPanel");
    expect(routeSource).toContain("teamWorkflowCandidatePreviewItems");
    expect(teamWorkflowCandidatePreviewPanelSource).toContain("候选仓库");
    expect(teamWorkflowCandidatePreviewPanelSource).not.toContain("VMetricChip");
    expect(teamWorkflowCandidatePreviewPanelSource).toContain("VButton");
    expect(teamWorkflowCandidatePreviewPanelSource).toContain("提炼复核");
    expect(teamWorkflowCandidatePreviewPanelSource).not.toContain("当前显示");
    expect(teamWorkflowCandidatePreviewPanelSource).not.toContain("向下滚动查看更多候选");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateListPanel");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateListScroll");
    expect(routeSource).toContain("生成分块计划");
    expect(routeSource).toContain("重建分块计划");
    expect(teamWorkflowStatusPanelsSource).toContain("后续 paper_note draft 需带 chunkId");
    expect(teamResearchWorkflowPanelHostSource).toContain("选择 research-team / 挑战杯ai科研团队 后显示挑战杯科研流程。");
    expect(teamCommunicationPanelSource).toContain("团队广播");
    expect(teamCommunicationPanelSource).toContain("发送给团队");
    expect(teamCommunicationPanelSource).toContain("最近团队广播");
    expect(teamCommunicationPanelSource).toContain("teamChatRoomRoute(startRoundResult.roomId");
    expect(teamCommunicationPanelSource).toContain("teamChatRoomRoute(latestTeamRound.roomId");
    expect(teamCommunicationPanelSource).toContain("teamWorkspaceRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)");
    // Canvas end-user chrome no longer dumps linked-room status lines; style tokens may remain.
    expect(routeSource).toContain("styles.toolbarLink");
    expect(routeSource).toContain("teamBusEvents");
    expect(teamCommunicationPanelSource).toContain("isProjectAgentBusEventRevoked");
    expect(routeSource).toContain("projectAgentBusEventsForTeam");
    expect(routeSource).toContain("revokeTeamMessageMutation");
    expect(teamCommunicationPanelSource).toContain("messageResult.kernel?.taskId");
    expect(teamCommunicationPanelSource).toContain("event.kernel?.taskId");
    expect(teamCommunicationPanelSource).toContain("styles.teamHistoryPanel");
    expect(routeStyles.kernelTraceLink).toBeTypeOf("string");
    expect(teamCommunicationPanelSource).toContain("interrupt_targets");
    expect(routeSource).toContain("buildCanvasWithDeletedNode");
    expect(routeSource).toContain("edge.source !== selectedNodeId && edge.target !== selectedNodeId");
    expect(routeSource).toContain("disabled={!hasWritableCanvas");
    expect(routeStyles.teamContextBar).toBeTypeOf("string");
    // Wave 8E: teamTitleBlock removed as unused route residue; context chrome remains.
    expect(routeStyles.teamSelectField).toBeTypeOf("string");
    expect(routeStyles.teamSelectPrefix).toBeTypeOf("string");
    expect(routeStyles.teamSelectControl).toBeTypeOf("string");
    expect(routeStyles.teamRefreshButton).toBeTypeOf("string");
    expect(routeStyles.teamContextChips).toBeTypeOf("string");
    expect(routeStyles.teamContextActions).toBeTypeOf("string");
    expect(routeStyles.teamContextActions).not.toContain("accent-warm");
    expect(routeStyles.teamContextBar).not.toContain("accent-warm");
    expect(routeStyles.teamSelectField).toContain("[&_[data-vui=select-trigger]]:!inline-flex");
    expect(routeStyles.teamSelectField).toContain("[&_[data-vui=select-trigger]]:justify-between");
    expect(routeStyles.teamRefreshButton).toContain("!h-8");
    expect(routeStyles.teamRefreshButton).toContain("!w-8");
    expect(routeStylesSource).not.toContain(".summaryBar");
    expect(routeStylesSource).not.toContain(".teamPickerPanel");
    expect(routeStylesSource).not.toContain(".teamPickerSummary");
    expect(routeStyles.nodeBindingSection).toBeTypeOf("string");
    expect(routeStyles.nodeBindingPlaceholder).toBeTypeOf("string");
    expect(routeStyles.nodeSourceAuthority).toBeTypeOf("string");
    expect(routeStyles.workflowPanel).toBeTypeOf("string");
    expect(routeStyles.workflowStats).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowIngestionPanel).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowIngestionStages).toBeTypeOf("string");
    expect(routeStyles.workflowIngestionBoundary).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowSourceQualityPanel).toBeTypeOf("string");
    expect(routeStyles.workflowSourceQualityStats).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowSourceQualityQueue).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowPaperNoteChunkPanel).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowPaperNoteChunkStats).toBeTypeOf("string");
    expect(teamSourceCollectionStorageActionsPanelStyles.workflowSourceCollectionStorageActions).toBeTypeOf("string");
    expect(teamSourceCollectionStorageActionsPanelStyles.workflowSourceCollectionStorageButtons).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowPaperNoteChunkPlans).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowModelEvidencePanel).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowModelEvidenceStats).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowModelEvidenceCoverage).toBeTypeOf("string");
    expect(teamSourceCollectionOverviewPanelStyles.workflowSourceCollectionPanel).toBeTypeOf("string");
    expect(teamSourceCollectionRunSettingsPanelStyles.workflowSourceCollectionForm).toBeTypeOf("string");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionRuns).toBeTypeOf("string");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionAssignments).toBeTypeOf("string");
    expect(teamSourceCollectionManualWritebackPanelStyles.workflowSourceCollectionOutputForm).toBeTypeOf("string");
    expect(routeStyles.workflowSuccess).toBeTypeOf("string");
    expect(routeStyles.workflowError).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionPage).toBeTypeOf("string");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionRunBadge).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionExtractionPanels).toBeTypeOf("string");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toBeTypeOf("string");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toBeTypeOf("string");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsHeader).toBeTypeOf("string");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultWarning).toBeTypeOf("string");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanelCompact).toBeTypeOf("string");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanelCompact).toBeTypeOf("string");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcher).toBeTypeOf("string");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcherMain).toBeTypeOf("string");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcherStats).toBeTypeOf("string");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toBeTypeOf("string");
    expect(teamSourceCollectionResultControlsSource).toContain("TeamSourceFilterBar");
    expect(teamSourceCollectionResultControlsSource).toContain("TeamSourcePagination");
    expect(teamSourceFilterBarSource).toContain("const BAR");
    expect(teamSourceFilterBarSource).toContain("const CHIP_ACTIVE");
    expect(teamSourceResultStatsSource).toContain('data-vui-product="team-source-result-stats"');
    expect(teamSourceResultListSource).toContain('data-vui-product="team-source-result-list"');
    expect(teamSourceResultListSource).toContain('data-vui-product="team-source-result-item"');
    expect(teamSourceResultListSource).toContain("ROW_SELECTED");
    expect(routeStylesSource).not.toContain(".sourceCollectionTraceMessage");
    expect(routeStylesSource).not.toContain(".sourceCollectionTrace_cache");
    expect(routeStylesSource).not.toContain(".sourceCollectionTraceStorage");
    expect(teamSourceEmptyStateSource).toContain('data-vui-product="team-source-empty-state"');
    expect(teamSourceEmptyStateSource).toContain('data-slot="source-empty-facts"');
    expect(teamSourceEmptyStateSource).toContain("actions");
    expect(teamSourceEmptyStateSource).toContain("border-dashed");
    expect(teamSourceEmptyStateSource).toContain("w-full");
    expect(teamSourceEmptyStateSource).not.toContain("self-start");
    expect(teamSourceEmptyStateSource).toContain("flex-wrap items-center justify-center");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailPanel).toBeTypeOf("string");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailActions).toBeTypeOf("string");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailFacts).toBeTypeOf("string");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailNotice).toBeTypeOf("string");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSearchEvidence).toBeTypeOf("string");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSearchEvidenceBody).toBeTypeOf("string");
    // Wave 8E: workflowCandidateItemSelected removed as unused route residue.
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateList).toBeTypeOf("string");
    expect(routeStylesSource).not.toContain(".sourceCollectionResultStatus");
    expect(routeStylesSource).not.toContain(".sourceCollectionResultSource");
    expect(routeStylesSource).not.toContain(".sourceCollectionResultSourceMissing");
    expect(routeStylesSource).not.toContain(".sourceCollectionFilterBar");
    expect(routeStylesSource).not.toContain(".sourceCollectionFilterActive");
    expect(teamSourceResultListSource).toContain(
      "grid-cols-[max-content_minmax(0,1fr)_minmax(70px,max-content)_minmax(8rem,16rem)]",
    );
    expect(teamSourceResultListSource).not.toContain("minmax(120px,220px)");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcher).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcherMain).toContain("grid-cols-[max-content_minmax(220px,360px)]");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcherMain).not.toContain("[&_small]");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcherStats).toContain("flex flex-wrap items-center justify-end");
    expect(teamSourceResultListSource).toContain("min-h-[36px]");
    expect(teamSourceResultListSource).toContain("whitespace-nowrap");
    expect(teamSourceResultListSource).not.toContain("grid-rows-[auto_auto_auto]");
    expect(routeStylesSource).not.toContain(".sourceCollectionCandidateListShell");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toContain("overflow-auto");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toContain("[scrollbar-gutter:stable]");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toContain("items-start");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toContain("content-start");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toContain("self-start");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryPanel).toBeTypeOf("string");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryBody).toBeTypeOf("string");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryBody).toContain("[&_p]:m-0");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryPanel).toContain(
      "grid-cols-[minmax(0,1fr)]",
    );
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryPanelDanger).toContain("state-error");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryPanel).not.toContain(
      "grid-cols-[minmax(0,1fr)_auto]",
    );
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryStats).toBeTypeOf("string");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryStats).toContain("repeat(auto-fit,minmax(7rem,1fr))");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryActions).toBeTypeOf("string");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryActions).toContain("[&_[data-vui=native-button]]:w-fit");
    // Wave 6E: list shells use PersistedHeightListShell (min/max live on pane specs).
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).not.toContain("max-h-[44vh]");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).not.toContain("min-h-[220px]");
    expect(teamSourceCollectionCandidatePanelSource).toContain("PersistedHeightListShell");
    expect(teamSourceCollectionCandidatePanelSource).toContain("TEAM_SOURCE_COLLECTION_CANDIDATES_HEIGHT_PANE");
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionScreeningListShell).not.toContain("max-h-[44vh]");
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionScreeningListShell).toContain("[scrollbar-gutter:stable]");
    expect(teamSourceCollectionScreeningPanelSource).toContain("PersistedHeightListShell");
    expect(teamSourceCollectionScreeningPanelSource).toContain("TEAM_SOURCE_COLLECTION_SCREENING_HEIGHT_PANE");
    expect(routeStylesSource).not.toContain("grid-template-rows: auto minmax(0, 1fr) auto auto");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("h-[var(--workflow-graph-height,360px)]");
    expect(workflowGraphViewStyles.workflowGraphFrame).not.toContain("h-full");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("w-[168px]");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("h-[58px]");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("overflow-hidden");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("[&_strong]:truncate");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("[&_span]:truncate");
    expect(teamSourceFilterBarSource).toContain("min-w-[4.75rem]");
    expect(teamSourceFilterBarSource).toContain("flex-none");
    expect(routeStylesSource).not.toContain("min-height: 122px");
    expect(routeStylesSource).not.toContain("min-height: 96px");
    expect(routeStylesSource).not.toContain(".sourceCollectionTraceBody");
    expect(routeStylesSource).not.toContain("grid-cols-[58px_minmax(0,1fr)]");
    expect(routeStylesSource).not.toMatch(/\.sourceCollectionTraceBody p \{[\s\S]*?-webkit-line-clamp: 3/);
    expect(teamSourceCollectionPanelFrameStyles.sourceCollectionFocusedPanel).toContain("ring-2");
    expect(teamSourceCollectionPanelFrameStyles.sourceCollectionFocusedPanel).not.toContain("grid-cols");
    expect(teamSourceCollectionPanelFrameStyles.sourceCollectionFocusedPanel).not.toContain("auto-rows");
    expect(routeStyles.route).toContain("[--team-workbench-gap:4px]");
    expect(routeStyles.sourceCollectionPage).toContain("h-full");
    expect(routeStyles.sourceCollectionPage).toContain("flex-1");
    expect(routeStyles.sourceCollectionPage).toContain("overflow-hidden");
    expect(routeStyles.sourceCollectionPageHeader).toContain("w-full");
    expect(routeStyles.sourceCollectionPageHeader).toContain("max-w-none");
    expect(routeStyles.sourceCollectionPageHeader).not.toContain("mx-auto");
    expect(routeStyles.sourceCollectionPageHeader).not.toContain("max-w-[1480px]");
    expect(routeStyles.sourceCollectionPageHeader).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(routeStyles.sourceCollectionPageHeader).toContain("gap-[var(--team-workbench-gap)]");
    expect(routeStyles.sourceCollectionPageHeader).toContain("px-[var(--team-workbench-gap)]");
    // Stage workspace: center list + right actions via persisted VSplitWorkspace.
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("flex");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("h-full");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("min-h-[360px]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("overflow-hidden");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).toContain("h-full");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).toContain("min-h-0");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).toContain("overflow-hidden");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).not.toContain("min-h-[360px]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).not.toContain("grid-cols-[minmax(0,1fr)_clamp");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).toContain("grid-cols-[minmax(0,1fr)]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageChatActions).toContain("grid-cols-[repeat(2,minmax(0,1fr))]");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("WORKBENCH_LAYOUT_IDS.teamsSourceCollectionStage");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("VSplitWorkspace");
    // Standalone page body (panel styles, not route unavailable body): flex + left rail split.
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBody).toContain("flex");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBody).toContain("h-full");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBody).toContain("w-full");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBody).toContain("max-w-none");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBody).not.toContain("grid-cols-[clamp");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBody).toContain("gap-[var(--team-workbench-gap)]");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBody).toContain("p-[var(--team-workbench-gap)]");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBodyCompact).toBeTypeOf("string");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBodyCompact).toContain("overflow-hidden");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("compactActivePanel ? styles.sourceCollectionPageBodyCompact : styles.sourceCollectionPageBody");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("searchBrief?: ReactNode");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("styles.sourceCollectionLeftRail");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("styles.sourceCollectionRunHistory");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("WORKBENCH_LAYOUT_IDS.teamsSourceCollection");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("VSplitWorkspace");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionLeftRail).toContain("overflow-y-auto");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionRunHistory).toContain("[&>summary]:cursor-pointer");
    expect(teamSourceCollectionSearchBriefPanelSource).toContain('data-vui-product="source-collection-search-brief"');
    expect(teamSourceCollectionSearchBriefPanelSource).toContain("先决定要研究什么");
    expect(teamSourceCollectionSearchBriefPanelSource).toContain("右侧「推荐下一步」");
    expect(teamSourceCollectionSearchBriefPanelSource).not.toContain("按当前方案搜索下一批");
    expect(teamSourceCollectionSearchBriefPanelSource).not.toContain("onSubmit");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toContain("h-full");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toContain("overflow-hidden");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toContain("max-[760px]:!h-auto");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toContain("max-[760px]:grid-rows-[auto_auto]");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toContain("max-[760px]:overflow-visible");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toContain("min-h-0");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toContain("h-full");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toContain("flex");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).not.toContain("col-start-2");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGridCompact).toBeTypeOf("string");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGridCompact).toContain("flex");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGridCompact).toContain("h-full");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGridCompact).toContain("overflow-hidden");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("compactActivePanel");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageSplit).toContain("flex-1");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("min-h-0");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("!flex");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("flex-col");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("overflow-hidden");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("max-[760px]:!h-auto");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("max-[760px]:overflow-visible");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("max-[760px]:min-h-0");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).not.toContain("min-h-[260px]");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).not.toContain("min-h-[210px]");
    expect(teamSourceCollectionConversationPanelSource).toContain("compact");
    expect(teamSourceCollectionConversationPanelSource).toContain("sourceCollectionResultsPanelCompact");
    // Wave 8K: conversation compact projection lives on workspace panel.
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("const sourceCollectionConversationHasVisibleResults = visibleResults.length > 0");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("const sourceCollectionConversationCompact = !sourceCollectionConversationHasVisibleResults");
    expect(teamSourceCollectionConversationWorkspacePanelSource).toContain("compact={sourceCollectionConversationCompact}");
    // Wave 8M: active-stage compact projection lives on active-stage workspace.
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("const sourceCollectionActiveStageCompact =");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("compact={sourceCollectionActiveStageCompact}");
    expect(composeSourceCollectionStageSurfacesSource).toContain("const sourceCollectionFindingHasVisibleRecords =");
    expect(composeSourceCollectionStageSurfacesSource).toContain("&& !sourceCollectionFindingHasVisibleRecords");
    expect(sourceCollectionControllerSource).toContain("compactActivePanel={chrome.sourceCollectionFindingStageCompact}");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanelCompact).toContain("h-auto");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanelCompact).toContain("shrink-0");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanelCompact).toContain("grid-rows-[auto_auto]");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanelCompact).not.toContain("h-full");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanelCompact).not.toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanelCompact).toContain("self-start");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanelCompact).toContain("shrink-0");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanelCompact).toContain("overflow-visible");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanelCompact).not.toContain("overflow-hidden");
    expect(teamSourceCollectionConversationPanelStylesSource).not.toContain("sourceCollectionConversationPanelCompact:\n    \"sourceCollectionConversationPanelCompact h-full");
    expect(teamSourceResultListSource).toContain("flex-1");
    expect(teamSourceResultListSource).toContain("overflow-auto");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionExtractionPanels).toContain(
      "grid-rows-[minmax(0,1fr)]",
    );
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionExtractionPanels).not.toContain(
      "grid-rows-[minmax(0,1fr)_auto]",
    );
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionExtractionScrollRegion).toContain("overflow-auto");
    expect(teamStageCommandBarSource).toContain('data-vui-product="team-stage-command-bar"');
    // Progress and statistics stay in a compact wrapping command group.
    expect(teamStageCommandBarSource).toContain("flex-wrap items-center gap-2");
    expect(teamStageCommandBarSource).toContain('aria-label="stage-progress"');
    expect(teamStageCardSource).toContain('data-vui-product="team-stage-card"');
    expect(teamStageCardSource).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamStageCardSource).toContain("ACTION_ROW");
    expect(teamStageCardSource).toContain("ACTION_BUTTON");
    expect(teamStageCardSource).not.toContain("sourceCollectionStageProjection");
    expect(routeStyles.canvasLayoutModeSwitch).toContain("grid-cols-[repeat(auto-fit,minmax(86px,max-content))]");
    expect(routeSource).toContain("<VActionGroup");
    expect(routeStyles.canvasToolbar).toContain("grid-cols-[minmax(0,1fr)_max-content]");
    expect(routeStyles.canvasToolbar).toContain("max-[900px]:grid-cols-[minmax(0,1fr)]");
    expect(routeStyles.canvasToolbar).toContain("[&>div:first-child]:min-w-0");
    expect(routeStyles.toolbarActions).toContain("max-w-full");
    expect(routeStyles.toolbarActions).toContain("[&_[data-vui=native-button]]:min-h-[28px]");
    expect(routeStyles.toolbarActions).toContain("[&_[data-vui=native-button]:not(.dangerButton)]:border");
    expect(routeStyles.toolbarActions).toContain("[&_a]:min-h-[28px]");
    expect(routeStyles.toolbarActions).not.toContain("min-w-[72px]");
    expect(routeStyles.knowledgeCompletionFlowPanel).toContain("overflow-hidden");
    expect(routeStyles.knowledgeCompletionFlowHeader).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(routeStyles.knowledgeCompletionFlowNodes).toContain("grid-cols-[repeat(auto-fit,minmax(280px,1fr))]");
    expect(routeStyles.knowledgeCompletionFlowNodesRail).toContain("!grid-cols-2");
    expect(routeStyles.knowledgeCompletionFlowPanelRail).toContain("knowledgeCompletionFlowPanelRail");
    // Next-step + 4-card hero: stable md:grid-cols-2 (arbitrary fr grids get purged).
    expect(routeStyles.researchPrimaryHeroSplit).toContain("md:!grid-cols-2");
    expect(routeStyles.researchPrimaryHeroSplit).toContain("!grid");
    expect(routeStyles.researchPrimaryHeroSide).toContain("md:border-l");
    expect(routeStyles.researchPrimaryHeroHeader).toContain("border-b");
    expect(routeStyles.knowledgeCompletionFlowNode).toContain("grid");
    expect(routeStyles.knowledgeCompletionFlowNode).toContain("rounded-[var(--radius-control)]");
    expect(routeStyles.knowledgeCompletionFlowNodeBody).toContain("[&_p]:max-w-[min(100%,72ch)]");
    expect(routeStyles.knowledgeCompletionFlowNodeBody).toContain("[&_p]:break-words");
    expect(routeStyles.workflowError).toContain("break-words");
    expect(routeStyles.knowledgeCompletionFlowError).toContain("break-words");
    expect(routeStyles.nodeRoleBadge).toContain("max-w-[128px]");
    expect(routeStyles.nodeRoleBadge).toContain("truncate");
    expect(teamMemoryIndexPanelStyles.teamMemoryRole).toContain("truncate");
    expect(teamStagePipelineSource).toContain("grid-cols-[repeat(auto-fit,minmax(220px,1fr))]");
    expect(teamStagePipelineSource).not.toContain("repeat(4");
    expect(teamStagePipelineSource).toContain("repeat(auto-fit,minmax(220px,1fr))");
    expect(teamStagePipelineSource).not.toContain("repeat(5");
    expect(teamSourceResultListSource).toContain("minmax(8rem,16rem)");
    expect(teamSourceResultListSource).not.toContain("max-h-[44vh]");
    expect(teamSourceResultListSource).not.toContain("max-h-[min(44vh,100%)]");
    expect(teamSourceResultListSource).not.toContain("minmax(120px,220px)");
    expect(teamSourceFilterBarSource).toContain("VButton");
    expect(teamSourceFilterBarSource).toContain("trailingIcon=");
    expect(teamSourceFilterBarSource).not.toContain("VNativeButton");
    expect(teamSourcePaginationSource).toContain("VButton");
    expect(teamSourcePaginationSource).not.toContain("VNativeButton");
    expect(teamCandidateCardSource).toContain("flex min-h-[40px]");
    expect(teamCandidateCardSource).toContain("max-[820px]:flex-wrap");
    expect(teamCandidateCardSource).toContain("VTooltip");
    expect(teamCandidateCardSource).not.toContain("title={activateTitle}");
    expect(teamCandidateCardSource).not.toContain("title={source.title}");
    expect(teamSourceResultListSource).toContain("VTooltip");
    expect(teamSourceResultListSource).not.toContain("title={activateTitle}");
    expect(teamSourceResultListSource).not.toContain("title={statusTitle}");
    expect(teamSourceResultListSource).not.toContain("title={titleTooltip}");
    expect(teamSourceResultListSource).not.toContain("title={source.title}");
    expect(teamStageCardSource).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamStageCardSource).toContain("VTooltip");
    expect(teamStageCardSource).not.toContain("title={title}");
    expect(teamStageCardSource).toContain("ACTION_ROW");
    expect(teamStageCardSource).toContain("ACTION_BUTTON");
    expect(teamStageCardSource).toContain("text-[0.72rem]");
    expect(teamSourcePaginationSource).toContain("select-none");
    expect(teamSourcePaginationSource).toContain("whitespace-nowrap");
    expect(teamSourcePaginationSource).not.toContain("writing-mode:vertical");
    expect(teamSourceCollectionStorageActionsPanelStyles.workflowSourceCollectionStorageActions).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamSourceCollectionStorageActionsPanelStyles.workflowSourceCollectionStorageButtons).toContain("justify-end");
    expect(teamSourceCollectionStorageActionsPanelStyles.workflowSourceCollectionStorageDetails).toContain("col-span-2");
    expect(teamSourceCollectionControlsPanelStyles.sourceCollectionControlPanel).toBeTypeOf("string");
    expect(teamStagePipelineSource).toContain("TeamStagePipeline");
    expect(teamStageCardSource).toContain("TeamStageCard");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageHandoff).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageHandoffNext).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageChatActions).toBeTypeOf("string");
    expect(routeStylesSource).not.toContain(".sourceCollectionStageTabs");
    expect(routeStylesSource).not.toContain(".sourceCollectionStageTabActive");
    expect(routeStylesSource).not.toContain(".sourceCollectionTraceHandoff");
    expect(teamSourcePaginationSource).toContain("TeamSourcePagination");
    expect(routeStylesSource).not.toContain(".sourceCollectionStageActionRow");
    expect(routeStylesSource).not.toContain(".sourceCollectionStageOperationPanel");
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionPanelActions).toBeTypeOf("string");
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionScreeningListShell).toBeTypeOf("string");
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionScreeningList).toBeTypeOf("string");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionScreeningScrollHint).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStagePrimaryAction).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageSecondaryAction).toBeTypeOf("string");
    expect(teamSourceCollectionPanelFrameStyles.sourceCollectionFocusedPanel).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionStepActive).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionStepDone).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionStepFailed).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionStepIdle).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionStepPending).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionStepActive).toContain("accent-cool");
    expect(routeStyles.sourceCollectionStepDone).toContain("state-success");
    expect(routeStyles.sourceCollectionStepFailed).toContain("state-error");
    expect(routeStyles.sourceCollectionStepPending).toContain("state-warning");
    expect(teamSourceCollectionStorageActionsPanelStyles.workflowSourceCollectionStorageDetails).toBeTypeOf("string");
    expect(routeStyles.researchStagePage).toBeTypeOf("string");
    expect(routeStyles.researchStageHeroPanel).toBeTypeOf("string");
    expect(routeStyles.researchStageActionPanel).toBeTypeOf("string");
    expect(routeStyles.researchStageModuleGrid).toBeTypeOf("string");
    expect(routeStyles.researchStageBoundaryPanel).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowGraphPanel).toBeTypeOf("string");
    expect(workflowGraphViewStyles.workflowGraphFrame).toBeTypeOf("string");
    expect(workflowGraphViewStyles.workflowGraphNode).toBeTypeOf("string");
    expect(workflowGraphViewStyles.workflowGraphEdge).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowGraphBoundary).toBeTypeOf("string");
    expect(routeStylesSource).not.toContain("workflowCandidateList:");
    expect(teamSourceCollectionCandidatePanelStyles.workflowCandidateList).toBeTypeOf("string");
    expect(routeStylesSource).not.toContain("workflowCandidateListPanel");
    expect(routeStylesSource).not.toContain("workflowCandidateListHeader");
    expect(routeStylesSource).not.toContain("workflowCandidateListScroll");
    expect(routeStylesSource).not.toContain("workflowCandidateListScrollHint");
    expect(routeStylesSource).not.toContain("workflowCandidateActions");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateListPanel");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateListHeader");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateListScroll");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateListScrollCue");
    expect(routeStylesSource).not.toContain("workflowModelEvidencePanel");
    expect(routeStylesSource).not.toContain("workflowCoordinationPanel");
    expect(routeStylesSource).not.toContain("workflowIngestionPanel");
    expect(routeStylesSource).not.toContain("workflowGraphPanel");
    expect(routeStylesSource).not.toContain("workflowSourceQualityPanel");
    expect(routeStylesSource).not.toContain("workflowPaperNoteChunkPanel");
    expect(teamWorkflowStatusPanelStylesSource).toContain("workflowModelEvidencePanel");
    expect(teamWorkflowStatusPanelStylesSource).toContain("workflowCoordinationPanel");
    expect(teamWorkflowStatusPanelStylesSource).toContain("workflowIngestionPanel");
    expect(teamWorkflowStatusPanelStylesSource).toContain("workflowGraphPanel");
    expect(teamWorkflowStatusPanelStylesSource).toContain("workflowSourceQualityPanel");
    expect(teamWorkflowStatusPanelStylesSource).toContain("workflowPaperNoteChunkPanel");
    expect(routeStylesSource).not.toContain("workflowSourceCollectionPanel");
    expect(routeStylesSource).not.toContain("workflowSourceCollectionStats");
    expect(routeStylesSource).not.toContain("workflowSourceCollectionPlan");
    expect(routeStylesSource).not.toContain("workflowSourceCollectionForm");
    expect(routeStylesSource).not.toContain("workflowSourceCollectionOutputForm");
    expect(routeStylesSource).not.toContain("workflowSourceCollectionStorageActions");
    expect(teamSourceCollectionOverviewPanelStylesSource).toContain("workflowSourceCollectionPanel");
    expect(teamSourceCollectionOverviewPanelStylesSource).toContain("workflowSourceCollectionStats");
    expect(teamSourceCollectionOverviewPanelStylesSource).toContain("workflowSourceCollectionPlan");
    expect(routeStyles.workflowValidation).toBeTypeOf("string");
    expect(routeStyles.workspaceResearch).toBeTypeOf("string");
    expect(routeStyles.workspaceResearchCanvas).toBeTypeOf("string");
    expect(routeStyles.researchStageLauncher).toBeTypeOf("string");
    expect(routeStyles.researchStageHeaderActions).toBeTypeOf("string");
    expect(routeStyles.researchStageDegradedNotice).toBeTypeOf("string");
    expect(routeStyles.researchStageStatus).toBeTypeOf("string");
    expect(routeStyles.researchStageStatusLoading).toBeTypeOf("string");
    expect(routeStyles.researchStageStatusUnavailable).toBeTypeOf("string");
    expect(routeStyles.researchStageCard).toBeTypeOf("string");
    expect(routeStyles.researchStageCardHead).toBeTypeOf("string");
    expect(routeStyles.researchStageCardMetrics).toBeTypeOf("string");
    expect(routeStyles.challengeProgramScope).toBeTypeOf("string");
    expect(routeStyles.challengeProgramResults).toBeTypeOf("string");
    expect(routeStyles.challengeProgramResultGrid).toBeTypeOf("string");
    expect(routeStyles.challengeProgramResultCard).toBeTypeOf("string");
    expect(routeStyles.challengeProgramQuestionList).toBeTypeOf("string");
    expect(routeStyles.challengeWorkspaceBody).toBeTypeOf("string");
    expect(routeStyles.challengeWorkspaceBody).toContain("w-full");
    expect(routeStyles.challengeWorkspaceBody).toContain("flex-1");
    expect(routeStyles.challengeWorkspaceContextHidden).toBeTypeOf("string");
    expect(routeStyles.challengeWorkspaceInspector).toBeTypeOf("string");
    expect(routeStyles.challengeWorkspaceInspector).toContain("w-full");
    expect(routeStyles.challengeWorkspaceLayout).toBeTypeOf("string");
    expect(routeStyles.challengeWorkspaceLayout).toContain("!grid-cols-[minmax(0,1fr)]");
    expect(routeStyles.challengeWorkspaceLayout).toContain("h-full");
    expect(routeStyles.challengeWorkspaceLayout).toContain("max-h-full");
    expect(routeStyles.challengeSurfaceSwitch).toBeTypeOf("string");
    expect(routeStyles.challengeSurfaceSwitchActive).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentSummary).toBeTypeOf("string");
    expect(routeStyles.researchExperimentMethodQuickSelect).toBeTypeOf("string");
    expect(routeStyles.researchExperimentMethodReady).toBeTypeOf("string");
    expect(routeStyles.researchExperimentMethodPending).toBeTypeOf("string");
    expect(routeStyles.researchExperimentMethodReason).toBeTypeOf("string");
    expect(routeStyles.researchExperimentMethodAlternatives).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentSummaryLoading).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentSummaryReady).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentSummaryMissing).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentSummaryBlocked).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentPanel).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentPanelCompact).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentGrid).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentCard).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentCard_ready).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentCard_warning).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentCard_blocked).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentCard_missing).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentPanel).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentHeader).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentTable).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentRole).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentModel).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentModelContent).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentModelValue).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentConfigLink).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentStatus).toBeTypeOf("string");
    expect(routeStyles.researchInspector).toBeTypeOf("string");
    expect(routeStyles.researchCanvasPanelHidden).toBeTypeOf("string");
    expect(routeStyles.canvasReadOnlyBadge).toBeTypeOf("string");
    expect(routeStyles.canvasReadOnlyPanel).toBeTypeOf("string");
    expect(routeStyles.canvasLayoutModeSwitch).toBeTypeOf("string");
    expect(routeStyles.canvasReadOnlyNotice).toBeTypeOf("string");
    expect(routeStyles.canvasReadOnlyNode).toBeTypeOf("string");
    expect(routeStyles.canvasReadOnlyNodeWide).toBeTypeOf("string");
    expect(routeStyles.nodeReadOnly).toBeTypeOf("string");
    expect(routeStyles.aiSearchScopePanel).toBeTypeOf("string");
    expect(routeStyles.aiSearchScopeStats).toBeTypeOf("string");
    expect(routeStyles.aiSearchSourceGroups).toBeTypeOf("string");
    expect(routeStyles.aiSearchSourceItem).toBeTypeOf("string");
    expect(routeStyles.aiSearchRunPanel).toBeTypeOf("string");
    expect(routeStyles.aiSearchRunHeader).toBeTypeOf("string");
    expect(routeStyles.aiSearchRunStats).toBeTypeOf("string");
    expect(routeStyles.aiSearchRunCard).toBeTypeOf("string");
    expect(routeStyles.aiSearchRunRefs).toBeTypeOf("string");
    expect(routeStyles.teamUnavailableSurface).not.toContain("place-items-center");
    expect(routeStyles.teamUnavailableSurface).toContain("justify-center");
    expect(routeStyles.teamUnavailableSurface).toContain("content-center");
    expect(routeStyles.teamUnavailableSurface).toContain("grid-cols-[minmax(0,720px)]");
    expect(routeStyles.teamUnavailableCard).toContain("max-w-[720px]");
    expect(routeStyles.workspace).toContain("overflow-hidden");
    expect(routeStyles.teamShellWorkspace).toContain("!flex");
    expect(routeStyles.teamShellInspectorPane).toContain("min-w-[280px]");
    expect(routeSource).toContain("VBoardWorkbenchPage");
    expect(routeSource).toContain("VCanvasWorkbenchPage");
    expect(routeSource).toContain("WORKBENCH_LAYOUT_IDS.teams");
    expect(routeSource).toContain('domainRecipe="teams-organization-workbench"');
    expect(routeSource).toContain('data-vui-region="teams-canvas"');
    expect(routeSource).toContain('data-vui-region="teams-inspector"');
    expect(routeSource).toContain('data-vui-region="teams-sidebar"');
    expect(routeStyles.teamShellContentCanvas).toContain("overflow-hidden");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("h-[var(--workflow-graph-height,360px)]");
    expect(workflowGraphViewStyles.workflowGraphFrame).not.toContain("h-full");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("overflow-auto");
    expect(routeStyles.canvasPanel).toContain("!flex");
    expect(routeStyles.canvasPanel).not.toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(routeStyles.canvasPanel).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(routeStyles.canvasPanel).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(routeStyles.canvas).toContain("bg-[var(--vui-surface-base)]");
    expect(routeStyles.canvas).toContain("[background-size:40px_40px]");
    expect(routeStyles.canvas).not.toContain("var(--vui-surface-glass)_94%");
    expect(routeStyles.inspector).toContain("!flex");
    expect(routeStyles.inspector).toMatch(/bg-vui-surface-rail|bg-\[var\(--vui-surface-rail\)\]/);
    expect(routeStyles.workspace).toMatch(/bg-vui-surface-workspace|bg-\[var\(--vui-surface-workspace\)\]/);
    expect(routeStyles.teamShellContentCanvas).toMatch(
      /bg-vui-surface-workspace|bg-\[var\(--vui-surface-workspace\)\]|teamShellContentCanvas/,
    );
    expect(routeStyles.route).toMatch(/bg-vui-surface-workspace|bg-\[var\(--vui-surface-workspace\)\]/);
    expect(routeStylesSource).toContain(".canvasLayoutModeSwitch");
  });

  it("keeps the bounded Smoke gate visible while prerequisites are still locked", () => {
    const smokeCardIndex = teamExperimentPlanningLedgerPanelSource.indexOf(
      'lang === "zh" ? "受控试跑" : "Bounded smoke"',
    );
    const executeStepIndex = teamExperimentPlanningLedgerPanelSource.indexOf(
      'currentStep === "execute"',
    );

    expect(smokeCardIndex).toBeGreaterThan(0);
    expect(executeStepIndex).toBeGreaterThan(0);
    expect(smokeCardIndex).toBeGreaterThan(executeStepIndex);
    expect(teamExperimentPlanningLedgerPanelSource).toContain("smokeGateDetail");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("先完成假设审查并冻结设计");
    expect(teamExperimentPlanningLedgerPanelSource).toContain("自包含执行器会在 Smoke 中同时计算 baseline 与 variant");
    expect(teamExperimentHypothesisGovernancePanelSource).toContain("仍缺：");
  });

  it("uses shared Phase 2 surfaces for Team unavailable and canvas states", () => {
    expect(routeSource).toContain("VActionGroup");
    expect(routeSource).toContain("VSurface");
    expect(routeSource).toContain('tone="unavailable"');
    expect(routeSource).toContain('tone="rail"');
    expect(routeSource).toContain('elevation="panel"');
    expect(routeSource).not.toContain("<section className={styles.teamUnavailableCard}");
    expect(routeStyles.canvasPanel).not.toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.canvasPanel).not.toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(routeStyles.teamUnavailableSurface).not.toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
  });

  it("uses quiet workbench panels instead of nested glass card walls in the Team canvas", () => {
    const quietSurfaceKeys = [
      "canvasPanel",
      "teamHistoryPanel",
      "teamRoundPanel",
      "workflowPanel",
      "teamMemoryMemberCard",
    ] as const;

    for (const key of quietSurfaceKeys) {
      expect(routeStyles[key]).not.toContain("bg-[var(--vui-surface-glass)]");
      expect(routeStyles[key]).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    }

    expect(routeStyles.workflowPanel).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(routeStyles.teamRoundPanel).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(routeStyles.teamHistoryPanel).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
  });

  it("keeps Teams route-level research and workflow surfaces operational instead of decorative", () => {
    const routeOperationalPanelKeys = [
      "aiSearchRunPanel",
      "aiSearchRunSummary",
      "aiSearchScopePanel",
      "aiSearchWorkflowSummary",
      "experimentKnowledgePanel",
      "experimentLedgerPanel",
      "experimentPlanSummary",
      "knowledgeCompletionFlowPanel",
      "researchDiscussionPanel",
      "researchLoopPanel",
      "researchLoopTemplateSummary",
      "researchStageActionPanel",
      "researchStageBoundaryPanel",
      "researchStageHeroPanel",
      "researchStageModuleCard",
      "teamRoundCard",
      "workflowPanel",
    ] as const;

    for (const key of routeOperationalPanelKeys) {
      expectOperationalSurface(routeStyles[key]);
    }

    expect(researchRouteStyles.researchLoopActive).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(researchRouteStyles.researchLoopActive).toContain("[&>div:first-child]:grid");
    expect(researchRouteStyles.researchLoopStatusPills).toContain("gap-1.5");

    const routeRowKeys = [
      "aiSearchRunCard",
      "aiSearchRunCardDegraded",
      "aiSearchRunCardDetails",
      "aiSearchRunCardHeader",
      "aiSearchRunCardReview",
      "researchStageAgentCard",
      "researchStageAgentPanel",
      "researchStageCard",
    ] as const;

    for (const key of routeRowKeys) {
      expectOperationalSurface(routeStyles[key], "bg-[var(--vui-surface-row)]");
    }

    expect(routeStyles.researchStageCard).toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.researchStageCard).not.toContain("hover:-translate-y-px");
    expect(routeStyles.researchStageHeroPanel).toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.sourceCollectionUnavailable).toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.sourceCollectionUnavailable).not.toContain("rounded-lg");
    expect(routeStyles.sourceCollectionUnavailable).not.toContain("bg-[image:var(--vui-gradient-route-soft)]");

    const researchAgentCardToneKeys = [
      "researchStageAgentCard_ready",
      "researchStageAgentCard_warning",
      "researchStageAgentCard_blocked",
      "researchStageAgentCard_missing",
      "researchStageAgentCard_error",
    ] as const;

    for (const key of researchAgentCardToneKeys) {
      const composedClassName = `${routeStyles.researchStageAgentCard} ${routeStyles[key]}`;
      expectOperationalSurface(composedClassName, "var(--vui-surface-row)");
      expect(topLevelBackgroundTokenCount(composedClassName)).toBe(1);
      expect(composedClassName).not.toContain("bg-[color-mix");
    }

    const researchAgentSummaryToneKeys = [
      "researchStageAgentSummaryReady",
      "researchStageAgentSummaryMissing",
      "researchStageAgentSummaryBlocked",
    ] as const;

    for (const key of researchAgentSummaryToneKeys) {
      const composedClassName = `${routeStyles.researchStageAgentSummary} ${routeStyles[key]}`;
      expectOperationalSurface(composedClassName, "bg-[var(--vui-control-muted)]");
      expect(topLevelBackgroundTokenCount(composedClassName)).toBe(1);
      expect(composedClassName).not.toContain("bg-[color-mix");
    }

    const compactPanelClassName = `${routeStyles.researchStageAgentPanel} ${routeStyles.researchStageAgentPanelCompact}`;
    expectOperationalSurface(compactPanelClassName, "bg-[var(--vui-surface-row)]");
    expect(topLevelBackgroundTokenCount(compactPanelClassName)).toBe(1);
    expect(compactPanelClassName).not.toContain("bg-[color-mix");

    expectOperationalSurface(routeStyles.researchStageAgentPanelHeader, "bg-[var(--vui-surface-row)]");
    expect(topLevelBackgroundTokenCount(routeStyles.researchStageAgentPanelHeader)).toBe(1);
    expect(routeStyles.researchStageAgentPanelHeader).not.toContain("bg-[color-mix");

    const researchAgentInlineKeys = [
      "researchStageAgentActions",
      "researchStageAgentGrid",
      "researchStageAgentMeta",
      "researchStageAgentRole",
    ] as const;

    for (const key of researchAgentInlineKeys) {
      expect(topLevelBackgroundTokenCount(routeStyles[key])).toBe(0);
      expect(routeStyles[key]).not.toContain("bg-[color-mix");
    }
  });

  it("keeps Team source collection child panels flat and scan-first", () => {
    const sourceCollectionPanelSurfaces = [
      teamSourceCollectionPanelFrameStyles.sourceCollectionFocusedPanel,
      teamSourceCollectionPanelFrameStyles.workflowSourceCollectionDetails,
      teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel,
      teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel,
      teamSourceCollectionControlsPanelStyles.sourceCollectionControlPanel,
      teamSourceCollectionOverviewPanelStyles.workflowSourceCollectionPanel,
      teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailPanel,
      teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailNotice,
      teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentPanel,
      teamWorkflowStatusPanelStyles.workflowCoordinationBriefSummary,
      teamWorkflowStatusPanelStyles.workflowCoordinationPanel,
      teamWorkflowStatusPanelStyles.workflowGraphPanel,
      teamWorkflowStatusPanelStyles.workflowIngestionPanel,
      teamWorkflowStatusPanelStyles.workflowModelEvidencePanel,
      teamWorkflowStatusPanelStyles.workflowPaperNoteChunkPanel,
      teamWorkflowStatusPanelStyles.workflowSourceQualityPanel,
    ];

    for (const className of sourceCollectionPanelSurfaces) {
      expectOperationalSurface(className);
    }

    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).not.toContain(
      "bg-[color:var(--source-workbench-card)]",
    );
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageChatActions).not.toContain(
      "bg-[image:var(--vui-gradient-route-soft)]",
    );
    expect(teamSourceCollectionStageAgentsPanelSource).toContain("VDenseTable");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailHeader).toMatch(/bg-vui-surface-row|bg-\[var\(--vui-surface-row\)\]/);
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailFacts).toMatch(/bg-vui-surface-row|bg-\[var\(--vui-surface-row\)\]/);
  });

  it("prioritizes active stage task launch and interruption status over stale summaries", () => {
    // Display-state helpers live in useSourceCollectionPresentation; stage modules stay in route.
    const launchStateIndex = Math.max(
      useSourceCollectionPresentationSource.indexOf("sourceCollectionStageDisplayState"),
      routeSource.indexOf("function sourceCollectionStageDisplayState"),
      routeSource.indexOf("sourceCollectionStageDisplayState"),
    );
    const extractionModuleStateIndex = Math.max(
      routeSource.indexOf('state: sourceCollectionStageDisplayState("extraction"'),
      stageModulesModelSource.indexOf("sourceCollectionStageDisplayState"),
    );
    expect(launchStateIndex).toBeGreaterThan(0);
    expect(extractionModuleStateIndex).toBeGreaterThan(0);

    const interruptedSummaryIndex = stageProjectionSource.indexOf("function sourceCollectionStageInterruptedSummary");
    const staleUserSummaryIndex = stageProjectionSource.indexOf('if (lang === "zh" && projection.userSummary)');
    expect(interruptedSummaryIndex).toBeGreaterThan(0);
    expect(staleUserSummaryIndex).toBeGreaterThan(interruptedSummaryIndex);
  });

  it("keeps restored TeamsRoute grids from the CSS module migration", () => {
    const restoredGridExpectations: Array<[string, string]> = [
      [routeStyles.aiSearchRunCards, "grid-cols-[repeat(auto-fit,minmax(220px,1fr))]"],
      [routeStyles.researchStageCardHead, "grid-cols-[auto_minmax(0,1fr)]"],
      [routeStyles.researchStageCardMetrics, "grid-cols-[repeat(3,minmax(0,1fr))]"],
      [routeStyles.researchStageAgentGrid, "grid-cols-[repeat(auto-fit,minmax(210px,1fr))]"],
      [teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailFacts, "grid-cols-[repeat(auto-fit,minmax(180px,1fr))]"],
      [routeStyles.researchStageHeroStats, "grid-cols-[repeat(3,minmax(0,1fr))]"],
      [routeStyles.workflowStats, "grid-cols-[repeat(3,minmax(0,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowModelEvidenceStats, "grid-cols-[repeat(auto-fit,minmax(118px,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowModelEvidenceCoverage, "grid-cols-[repeat(auto-fit,minmax(118px,1fr))]"],
      [teamSourceCollectionRunSettingsPanelStyles.workflowSourceCollectionForm, "grid-cols-[repeat(2,minmax(0,1fr))]"],
      [teamSourceCollectionManualWritebackPanelStyles.workflowSourceCollectionOutputForm, "grid-cols-[repeat(2,minmax(0,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowIngestionStages, "grid-cols-[repeat(5,minmax(58px,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowSourceQualityStats, "grid-cols-[repeat(5,minmax(72px,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowSourceQualityQueue, "grid-cols-[repeat(3,minmax(0,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowPaperNoteChunkStats, "grid-cols-[repeat(4,minmax(86px,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowPaperNoteChunkPlans, "grid-cols-[repeat(2,minmax(0,1fr))]"],
    ];

    for (const [className, gridTemplate] of restoredGridExpectations) {
      expect(className).toContain("!grid");
      expect(className).toContain(gridTemplate);
    }

    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentTable).toContain("h-11");
  });

  it("keeps source collection subpanels compact, text-safe, and mobile-safe", () => {
    expect(teamSourceCollectionPanelFrameStyles.sourceCollectionFocusedPanel).toContain("ring-inset");
    expect(teamSourceCollectionPanelFrameStyles.sourceCollectionFocusedPanel).not.toMatch(/(?:^|\s)grid(?:\s|$)/);
    expect(teamSourceCollectionControlsPanelStyles.sourceCollectionControlPanel).toContain("!grid");
    expect(teamSourceCollectionControlsPanelStyles.sourceCollectionControlPanel).toContain("grid-cols-[minmax(0,1fr)]");
    expect(teamSourceCollectionControlsPanelStyles.workflowIngestionHeader).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamSourceCollectionControlsPanelStyles.workflowTag).toContain("truncate");

    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).toContain("grid-cols-[minmax(0,1fr)]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).toContain("h-full");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).toContain("overflow-y-auto");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).not.toContain("col-start-2");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).toContain("[&>div>strong]:truncate");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceSplit).toContain("flex-1");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageHandoff).toContain("[&>span]:min-w-0");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageHandoff).toContain("[&>span]:break-words");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageChatActions).toContain("[&_[data-vui=native-button]]:w-full");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageChatActions).toContain("max-[1020px]:[&_[data-vui=native-button]]:w-fit");

    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentPanel).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentTable).not.toContain("max-[720px]");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentRole).toContain("w-[34%]");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentModel).toContain("w-[44%]");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentStatus).toContain("w-[22%]");

    for (const className of [
      teamWorkflowStatusPanelStyles.workflowIngestionStages,
      teamWorkflowStatusPanelStyles.workflowSourceQualityStats,
      teamWorkflowStatusPanelStyles.workflowSourceQualityQueue,
      teamWorkflowStatusPanelStyles.workflowPaperNoteChunkStats,
      teamWorkflowStatusPanelStyles.workflowPaperNoteChunkPlans,
    ]) {
      expect(className).toContain("max-[760px]:grid-cols-[minmax(0,1fr)]");
    }

    expect(teamWorkflowStatusPanelStyles.workflowIngestionStage).toContain("[&_strong]:truncate");
    expect(teamWorkflowStatusPanelStyles.workflowSourceQualityQueue).toContain("[&_strong]:truncate");
    expect(teamWorkflowStatusPanelStyles.workflowPaperNoteChunkPlans).toContain("[&_small]:break-words");
    expect(teamWorkflowStatusPanelStyles.workflowIngestionHeader).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamWorkflowStatusPanelStyles.workflowIngestionActions).toContain("[&_span]:break-words");
  });

  it("keeps Teams graph and candidate child panels light, text-safe, and mobile-fit", () => {
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListPanel).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListPanel).toContain("overflow-hidden");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListPanel).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListPanel).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListHeader).toContain("items-center");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListHeader).toContain("justify-between");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListActions).toContain("shrink-0");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).not.toContain("data-vui=native-button");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListScroll).toContain("[scrollbar-gutter:stable]");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateList).toContain("[&_[data-vui-product=team-candidate-card]]:max-w-full");

    expect(classTokenCount(teamMemoryIndexPanelStyles.teamMemoryActionRail, "flex")).toBe(1);
    expect(classTokenCount(teamMemoryIndexPanelStyles.teamMemoryActionRail, "grid")).toBe(0);
    expect(classTokenCount(teamMemoryIndexPanelStyles.teamMemoryActionRail, "min-w-0")).toBe(1);
    expect(teamMemoryIndexPanelStyles.teamMemoryActionRail).toContain("[&_a]:w-fit");
    expect(classTokenCount(teamMemoryIndexPanelStyles.teamMemoryMemberActions, "flex")).toBe(1);
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberActions).toContain("[&_a]:flex-none");

    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("max-w-full");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("overflow-auto");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("[scrollbar-gutter:stable]");
    expect(workflowGraphViewStyles.workflowGraphCanvas).toContain("min-w-[var(--workflow-graph-width,720px)]");
    expect(workflowGraphViewStyles.workflowGraphNode).toMatch(/bg-vui-surface-row|bg-\[var\(--vui-surface-row\)\]/);
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("shadow-none");
    expect(workflowGraphViewStyles.workflowGraphNode).not.toContain("shadow-[var(--vui-shadow-hairline)]");

    expect(teamSourceCollectionGraphPanelStyles.sourceCollectionGraphNodeListShell).toContain("max-w-full");
    expect(teamSourceCollectionGraphPanelStyles.sourceCollectionGraphNodeListShell).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(teamSourceCollectionGraphPanelStyles.workflowCandidateList).toContain("[&_[data-vui-product=team-candidate-card]]:max-w-full");
    expect(teamSourceCollectionGraphPanelStyles.workflowCandidateList).toContain("[&_[data-vui=native-button]]:w-fit");

    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionAssignments).toContain(
      "grid-cols-[repeat(auto-fit,minmax(9rem,max-content))]",
    );
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionAssignments).toContain("max-[640px]:grid-cols-[minmax(0,1fr)]");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionAssignments).toContain("[&_[data-vui=native-button]]:w-fit");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionAssignments).toContain("[&_[data-vui=native-button]_strong]:truncate");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionAssignments).toContain("[&_[data-vui=native-button]_span]:break-words");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionQueries).toContain("[&_strong]:truncate");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionQueries).toContain("[&_small]:break-words");
  });

  it("uses a subtle mesh canvas background instead of repeated horizontal route stripes", () => {
    for (const className of [routeStyles.canvas, routeStyles.emptyCanvasPanel]) {
      expect(className).toContain("[background-image:linear-gradient(to_right");
      expect(className).toContain("linear-gradient(to_bottom");
      expect(className).toContain("[background-size:40px_40px]");
      expect(className).toContain("var(--vui-border-subtle)_24%");
      expect(className).not.toContain("vui-gradient-route-soft");
    }
  });

  it("keeps one knowledge collection loop CTA on the phase card and leaves manual work in stage details", () => {
    // Wave 8H: phase-card CTA copy lives on TeamResearchStageLauncherPanel; route still owns loop labels.
    const launcherSource = teamResearchStageLauncherPanelSource;
    expect(launcherSource).toContain("runKnowledgeCollectionLoopAction");
    expect(launcherSource).toContain("sourceCollectionLoopActionLabel");
    expect(launcherSource).toContain("sourceCollectionLoopActionDisabled");
    expect(launcherSource).toContain("手动控制");
    expect(routeSource).toContain("开始第一轮闭环");
    expect(routeSource).toContain("继续本轮闭环");
    expect(routeSource).toContain("开始下一轮闭环");
    expect(launcherSource).not.toContain("一键完成知识搜集");
    expect(launcherSource).not.toContain("新一轮搜集");

    // Stage module descriptors live in stageModulesModel after extract.
    const stageModuleSource = stageModulesModelSource.slice(
      stageModulesModelSource.indexOf("const sourceCollectionStageModules: SourceCollectionStageModule[] = ["),
      stageModulesModelSource.indexOf("return sourceCollectionStageModules;"),
    );
    const ingestionModuleSource = stageModuleSource.slice(
      stageModuleSource.indexOf('id: "ingestion"'),
      stageModuleSource.indexOf("];"),
    );
    expect(ingestionModuleSource).toContain("onSecondaryAction: sourceCollectionIngestionReadyForExperiment");
    expect(ingestionModuleSource).toContain("navigate(sourceCollectionExperimentPlanningRoute)");
    expect(ingestionModuleSource).toContain('onAction: () => void startSourceCollectionStageSessionTask("ingestion")');
    expect(ingestionModuleSource).toContain("进入实验设计（离开${RESEARCH_STAGE_TERMS.knowledge_collection.zh}）");
    expect(ingestionModuleSource).not.toContain("runKnowledgeCollectionCompletionAction");
    expect(ingestionModuleSource).not.toContain("runKnowledgeCollectionCompletionMutation");
    expect(ingestionModuleSource).not.toContain("runKnowledgeCollectionIngestMutation.mutate");
    // R1-a: stage modules built inside useTeamsScComposition
    expect(composeSourceCollectionStageSurfacesSource).toContain("buildSourceCollectionStageModules({");
    expect(routeSource).toContain("useTeamsScComposition");
  });

  it("starts a new source collection run before completion when the loop CTA represents the next loop", () => {
    const loopActionSource = routeSource.slice(
      routeSource.indexOf("const runKnowledgeCollectionLoopAction ="),
      routeSource.indexOf("const runSourceCollectionSearchFromHeader ="),
    );
    expect(loopActionSource).toContain("sourceCollectionLoopStartsNewRun");
    expect(loopActionSource).toContain("startSourceCollectionRunMutation.mutateAsync");
    expect(loopActionSource).toContain("const startedRunId =");
    expect(loopActionSource).toContain("startKnowledgeCollectionCompletionForRun(startedRunId");
    expect(loopActionSource).toContain("startKnowledgeCollectionCompletionForRun(sourceCollectionActionRunId");
  });

  it("lets a completed knowledge collection work run clear stale one-click mutation errors", () => {
    // Phase 4+: completion/error gating lives on buildSourceCollectionWriteMutationSurface.
    expect(teamMutationSurfaceSource).toContain("selectedTeamKnowledgeCollectionCompleted");
    expect(teamMutationSurfaceSource).toContain('knowledgeCollectionWorkRunStatus === "completed"');
    expect(teamMutationSurfaceSource).toContain('knowledgeCollectionFlowStatus === "completed"');
    expect(teamMutationSurfaceSource).toContain("!knowledgeCollectionCompleted");
    expect(useSourceCollectionPresentationSource).toContain("buildSourceCollectionWriteMutationSurface({");
  });

  it("does not treat a completed knowledge work run from another source run as the selected loop completion", () => {
    expect(teamMutationSurfaceSource).toContain("knowledgeCollectionSourceRunId");
    expect(teamMutationSurfaceSource).toContain("knowledgeCollectionMatchesSelectedRun");
    expect(teamMutationSurfaceSource).toContain(
      "knowledgeCollectionSourceRunId === input.selectedSourceCollectionRunEffectiveId",
    );
    expect(teamMutationSurfaceSource).toContain("knowledgeCollectionCompletedForSelectedRun");

    // F3: loopStartsNewRun lives in presentationActionReadiness pure factory.
    expect(routeSource).toContain("loopStartsNewRun");
    expect(routeSource).toContain("knowledgeCompletedForSelectedRun");
    expect(routeSource).toContain("sourceCollectionLoopStartsNewRun");
  });

  it("keeps side-effect source collection actions behind initial-data readiness gates", () => {
    expect(routeSource).toContain("type SourceCollectionActionReadiness");
    expect(routeSource).toContain("sourceCollectionActionInitialDataPending");
    expect(routeSource).toContain("sourceCollectionActionDataError");
    expect(routeSource).toContain("sourceCollectionSearchActionReadiness");
    expect(routeSource).toContain("sourceCollectionCompletionActionReadiness");
    expect(routeSource).toContain("sourceCollectionCandidateExtractionActionReadiness");
    expect(routeSource).toContain("sourceCollectionScreeningActionReadiness");
    expect(routeSource).toContain("sourceCollectionGraphActionReadiness");
    expect(routeSource).toContain("sourceCollectionMemoryActionReadiness");
    expect(routeSource).toContain("sourceCollectionStageTaskActionReadiness");
    expect(routeSource).toContain("sourceCollectionActionDisabledTitle");

    expect(routeSource).toContain("sourceCollectionActionInitialDataPending");
    expect(routeSource).toContain("sourceCollectionRecordsDataLoading");
    expect(routeSource).toContain("sourceCollectionAssignmentsDataLoading");
    expect(routeSource).toContain("sourceCollectionPrimaryDataLoading");
    expect(deriveSourceCollectionListMetricsSource).toContain("sourceCollectionSourceQualityLoading");
    expect(deriveSourceCollectionListMetricsSource).toContain("teamWorkflowCandidateGraphQuery.isPending && !teamWorkflowCandidateGraphQuery.data");
    expect(deriveSourceCollectionListMetricsSource).toContain("teamWorkflowKnowledgeIngestionStatusQuery.isPending && !teamWorkflowKnowledgeIngestionStatusQuery.data");
    expect(routeSource).not.toContain("sourceCollectionSummaryQuery.isFetching && sourceCollectionRecordsQuery.isFetching");

    // Wave 8H: readiness gates for stage CTAs are enforced inside TeamResearchStageLauncherPanel.
    const launcherSource = teamResearchStageLauncherPanelSource;
    expect(launcherSource).toContain("sourceCollectionSearchActionReadiness.disabled");
    expect(launcherSource).toContain("disabled={sourceCollectionLoopActionDisabled}");
    expect(routeSource).toContain("sourceCollectionLoopActionDisabled");
    expect(routeSource).toContain("sourceCollectionCompletionActionDisabled");
    expect(routeSource).toMatch(/loopActionDisabled\s*=\s*loopActionReadiness\.disabled|sourceCollectionLoopActionReadiness\.disabled/);
    expect(routeSource).toMatch(/completionActionDisabled\s*=\s*completionActionReadiness\.disabled|sourceCollectionCompletionActionReadiness\.disabled/);
    expect(launcherSource).toContain("title={sourceCollectionActionDisabledTitle(sourceCollectionLoopActionReadiness, sourceCollectionLoopActionLabel)}");

    const stageModuleSource = stageModulesModelSource.slice(
      stageModulesModelSource.indexOf("const sourceCollectionStageModules: SourceCollectionStageModule[] = ["),
      stageModulesModelSource.indexOf("return sourceCollectionStageModules;"),
    );
    expect(stageModuleSource).toContain('sourceCollectionStageActionReadinessFor("finding").disabled');
    expect(stageModuleSource).toContain('sourceCollectionStageActionReadinessFor("extraction").disabled');
    expect(stageModuleSource).toContain('sourceCollectionStageActionReadinessFor("relations").disabled');
    expect(stageModuleSource).toContain('sourceCollectionStageActionReadinessFor("ingestion").disabled');
    expect(stageModuleSource.match(/sourceCollectionStageActionLabelFor/g) ?? []).toHaveLength(4);
    expect(stageModuleSource).toContain('"finding", sourceCollectionCollectionActionLabel');
    expect(stageModuleSource).toContain('"extraction",');
    expect(stageModuleSource).toContain('"relations", sourceCollectionGraphActionLabel');
    expect(stageModuleSource).toContain('"ingestion", sourceCollectionMemoryActionLabel');
  });

  it("keeps source collection stage status stable while the selected run is still loading", () => {
    // R2-o: summary stage-round projection is pure in deriveSourceCollectionSummaryProjection.
    const stageRoundSource = deriveSourceCollectionSummaryProjectionSource;
    expect(stageRoundSource).toContain("summaryRunId");
    expect(stageRoundSource).toContain("selectedSourceCollectionRunEffectiveId && summaryRunId && summaryRunId !== selectedSourceCollectionRunEffectiveId");
    expect(stageRoundSource).toContain("selectSourceCollectionStageRound(");
    expect(stageRoundSource).toContain("sourceCollectionSummaryStageRound");
    expect(stageRoundSource).toContain("selectedSourceCollectionRunEffectiveId");
    expect(stageRoundSource).not.toContain("?? rounds[0] ?? null");
    expect(useSourceCollectionPresentationSource).toContain("deriveSourceCollectionSummaryProjection({");

    // R2-l: candidate/primary loading gates live in deriveSourceCollectionListMetrics.
    expect(deriveSourceCollectionListMetricsSource).toContain("const sourceCollectionCandidateListDataLoading = Boolean(");
    expect(deriveSourceCollectionListMetricsSource).toContain("teamWorkflowCandidateListEnabled");
    expect(deriveSourceCollectionListMetricsSource).toContain("sourceCollectionNeedsCandidateList");
    expect(deriveSourceCollectionListMetricsSource).toContain("!teamWorkflowCandidatesQuery.data");
    expect(routeSource).toContain("const sourceCollectionNeedsCandidateList = sourceCollectionWorkspaceSelected;");
    expect(routeSource).not.toContain("selectedSourceCollectionStageId !== \"finding\"");

    const sourceCollectionPrimaryLoadingSource = deriveSourceCollectionListMetricsSource.slice(
      deriveSourceCollectionListMetricsSource.indexOf("const sourceCollectionPrimaryDataLoading = Boolean("),
      deriveSourceCollectionListMetricsSource.indexOf("const sourceCollectionSourceQualityLoading = Boolean("),
    );
    expect(sourceCollectionPrimaryLoadingSource).toContain("sourceCollectionCandidateListDataLoading");

    expect(routeSource).toContain("sourceCollectionDataSyncText");
    expect(routeSource).toContain("sourceCollectionStableCountText");
    // Wave 8L: candidate panel loading prop lives on candidate workspace panel.
    expect(teamSourceCollectionCandidateWorkspacePanelSource).toContain("loading={sourceCollectionPrimaryDataLoading}");

    // R2-m: stage display loading/state + sync metric labels live in pure module.
    const displayLoadingSource = deriveSourceCollectionStageDisplaySurfacesSource.slice(
      deriveSourceCollectionStageDisplaySurfacesSource.indexOf("const sourceCollectionFindingDisplayLoading"),
      deriveSourceCollectionStageDisplaySurfacesSource.indexOf("sourceCollectionIngestionReadyForExperiment"),
    );
    expect(displayLoadingSource).toContain("const sourceCollectionRelationsDisplayLoading = graphDataLoading");
    expect(displayLoadingSource).toContain("const sourceCollectionIngestionDisplayLoading = sourceQualityLoading || knowledgeIngestionDataLoading");
    expect(displayLoadingSource).toContain("sourceCollectionCandidateSyncStatusText");
    expect(displayLoadingSource).not.toContain("primaryDataLoading || graphDataLoading");
    expect(displayLoadingSource).not.toContain("primaryDataLoading || sourceQualityLoading || knowledgeIngestionDataLoading");
    expect(useSourceCollectionPresentationSource).toContain("deriveSourceCollectionStageDisplaySurfaces({");

    const stageModuleSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionStageModules"),
      routeSource.indexOf("const sourceCollectionBoardCurrentModule"),
    );
    const extractionModuleSource = stageModuleSource.slice(
      stageModuleSource.indexOf('id: "extraction"'),
      stageModuleSource.indexOf('id: "relations"'),
    );
    expect(extractionModuleSource).toContain("sourceCollectionExtractionDisplayLoading");
    expect(extractionModuleSource).toContain('summary: sourceCollectionStageLaunchActive("extraction")');
    expect(extractionModuleSource.indexOf('summary: sourceCollectionStageLaunchActive("extraction")')).toBeLessThan(
      extractionModuleSource.indexOf("sourceCollectionExtractionDisplayLoading"),
    );
    expect(extractionModuleSource.indexOf("sourceCollectionExtractionDisplayLoading")).toBeLessThan(
      extractionModuleSource.indexOf("sourceCollectionStageUserSummary(sourceCollectionExtractionProjection, lang)"),
    );
    expect(extractionModuleSource).toContain('state: sourceCollectionStageDisplayState("extraction", sourceCollectionExtractionCanProceedAfterExclusions');
    expect(extractionModuleSource).toContain('status: sourceCollectionStageDisplayStatus(');
    expect(extractionModuleSource).toContain("sourceCollectionExtractionDisplayLoading");
    expect(extractionModuleSource).toContain("sourceCollectionCandidateSyncStatusText");
    expect(extractionModuleSource).toContain("sourceCollectionExtractionExcludedRecoveryState.statusLabel");
  });

  it("keeps the source collection workspace in a simple status-board mode", () => {
    const standaloneSource = routeSource.slice(
      routeSource.indexOf("if (sourceCollectionStandalone)"),
      routeSource.indexOf("const teamShellRail"),
    );
    expect(standaloneSource).toContain("sourceCollectionBoardNextStepLabel");
    expect(standaloneSource).not.toContain("{renderSourceCollectionControlsPanel()}");
    expect(routeSource).toContain("TeamSourceCollectionFilterBarInject");
    expect(routeSource).toContain("TeamSourceCollectionPaginationInject");
    expect(teamSourceCollectionInjectModelSource).toContain("buildSourceCollectionFilterBarOptions");
    expect(teamSourceCollectionInjectModelSource).toContain("resolveSourceCollectionPaginationView");
    expect(routeSource).toContain("TeamSourceCollectionControlsInject");
    expect(routeSource).toContain("TeamSourceCollectionActiveStageInject");
    expect(teamSourceCollectionInjectModelSource).toContain('filter === ("all" as Key)');
    expect(routeSource).toContain("loadingAllText={sourceCollectionLoadingText}");
    expect(routeSource).not.toContain("count: loading ? loadingValue");

    expect(standaloneSource).toContain("sourceCollectionConsoleStatusText");
    expect(standaloneSource).toContain("sourceCollectionBoardNextStepLabel");
    expect(standaloneSource).toContain("sourceCollectionCollectedCountLabel");
    expect(standaloneSource).not.toContain("sourceCollectionSearchOpenAssignmentCountLabel");
    expect(standaloneSource).not.toContain("sourceCollectionDownstreamOpenAssignmentCountLabel");
    expect(standaloneSource).not.toContain("sourceCollectionQueryCountLabel");
    expect(standaloneSource).not.toContain("sourceCollectionPromptCacheStatusLabel");

    const stageModuleViewModelSource = stageModulesModelSource.slice(
      stageModulesModelSource.indexOf("export function buildSourceCollectionStandaloneStageModules"),
      stageModulesModelSource.length,
    );
    expect(stageModuleViewModelSource).toContain("tone: module.state");
    expect(stageModuleViewModelSource).toContain("status: module.status");
    expect(stageModuleViewModelSource).toContain("metric: module.metric");
    expect(stageModuleViewModelSource).toContain("nextLabel: `${lang === \"zh\" ? \"下一步：\" : \"Next: \"}${module.nextLabel}`");
    expect(stageModuleViewModelSource).toContain("sourceCollectionActionDisabledTitle(cardActionReadiness, module.actionLabel)");
    expect(stageModuleViewModelSource).not.toContain("summary: module.summary");
    expect(stageModuleViewModelSource).not.toContain("sourceCollectionStageProjectionTaskMetric");
    expect(stageModuleViewModelSource).not.toContain("sourceCollectionStageTechnicalDetails");
    // R1-a: standalone stage modules built inside useTeamsScComposition
    expect(composeSourceCollectionStageSurfacesSource).toContain("buildSourceCollectionStandaloneStageModules({");

    const stageCardSource = teamSourceCollectionStandaloneStagePanelSource.slice(
      teamSourceCollectionStandaloneStagePanelSource.indexOf("<TeamStagePipeline"),
      teamSourceCollectionStandaloneStagePanelSource.indexOf("<div className={compactActivePanel"),
    );
    expect(stageCardSource).toContain("TeamStageCard");
    expect(stageCardSource).toContain("tone={module.tone}");
    expect(stageCardSource).toContain("module.status");
    expect(stageCardSource).toContain("module.metric");
    expect(stageCardSource).toContain("module.nextLabel");
    expect(stageCardSource).not.toContain("module.onAction");
    expect(stageCardSource).not.toContain("module.actionDisabled");
    expect(stageCardSource).not.toContain("module.actionTitle");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("onPress={primaryAction.onAction}");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("<VButton");
    expect(teamSourceCollectionActiveStagePanelSource).toContain('variant={primaryAction.tone === "primary" ? "primary" : "secondary"}');

    // Wave 8K: raw-record list body lives on conversation workspace panel.
    const rawRecordSource = teamSourceCollectionConversationWorkspacePanelSource;
    expect(rawRecordSource).toContain("sourceCollectionSimpleRecordStatusPresentation");
    expect(rawRecordSource).toContain("statusTitle={resultStatus.title}");
    expect(rawRecordSource).not.toContain("<p title={record.summary || record.recordId}>");
    expect(rawRecordSource).not.toContain("formatTime(record.updatedAt || record.createdAt");

    // Wave 8L: candidate list body lives on candidate workspace panel.
    const candidatePanelSource = teamSourceCollectionCandidateWorkspacePanelSource;
    expect(candidatePanelSource).toContain("sourceCollectionSimpleCandidateStatusPresentation");
    expect(candidatePanelSource).toContain("statusTitle={qualityPresentation.title}");
    expect(candidatePanelSource).not.toContain("<p>{candidate.summary || candidate.candidateId}</p>");
    expect(candidatePanelSource).not.toContain("formatTime(candidate.updatedAt");
    expect(candidatePanelSource).not.toContain("sourceCollectionStageTechnicalDetails");
    expect(candidatePanelSource).not.toContain("candidateLatestTask?.summary");
    expect(candidatePanelSource).not.toContain("blockingReasons");
  });

  it("surfaces source extraction Evidence Ledger in cards, details, and relation mapping", () => {
    expect(routeSource).toContain("sourceCollectionEvidenceLedgerSummary");
    expect(evidenceModelSource).toContain("metadata.contentExtraction");
    expect(evidenceModelSource).toContain("extraction.evidenceLedger");
    expect(evidenceModelSource).toContain("Evidence Ledger ${summary.status}");
    expect(evidenceModelSource).toContain("evidence_ready");
    expect(evidenceModelSource).toContain("missing_evidence_anchor");
    expect(routeSource).toContain("sourceCollectionEvidenceReadyCandidateCount");
    expect(routeSource).toContain("sourceCollectionMissingEvidenceAnchorCount");

    // Wave 8M: selected-source detail body lives on selected-source workspace panel.
    const selectedSourceDetailSource = teamSourceCollectionSelectedSourceWorkspacePanelSource;
    expect(selectedSourceDetailSource).toContain("sourceCollectionEvidenceLedgerDetailItems");
    expect(selectedSourceDetailSource).toContain("evidenceLedger={evidenceLedgerSummary");
    expect(teamSourceCollectionSourceDetailPanelSource).toContain("Evidence Ledger");
    expect(teamSourceCollectionSourceDetailPanelSource).toContain("evidenceLedger.map");

    // Wave 8L: evidence-ledger labels used from candidate workspace panel.
    const candidatePanelSource = teamSourceCollectionCandidateWorkspacePanelSource;
    expect(candidatePanelSource).toContain("sourceCollectionEvidenceLedgerCardLabel");
    expect(candidatePanelSource).toContain("sourceCollectionEvidenceLedgerTone");

    // Wave 8L: graph evidence-ledger summary lives on graph workspace panel.
    const graphPanelSource = teamSourceCollectionGraphWorkspacePanelSource;
    expect(graphPanelSource).toContain("visibleGraphMissingEvidenceAnchorCount");
    expect(graphPanelSource).toContain("sourceCollectionEvidenceLedgerActionLabel");
    expect(graphPanelSource).toContain("待补证据");
  });

  it("keeps Team actions scoped to the selected Team or message event", () => {
    expect(routeSource).toContain("canvasSavePendingForTeam");
    expect(routeSource).toContain("saveCanvasMutation.variables?.teamId === teamId");
    expect(routeSource).toContain("selectedTeamSyncPending");
    expect(routeSource).toContain("syncTeamChatRoomMutation.variables === selectedTeam?.teamId");
    expect(routeSource).toContain("selectedTeamStartRoundPending");
    expect(routeSource).toContain("startTeamRoundMutation.variables?.teamId === selectedTeam?.teamId");
    expect(routeSource).toContain("selectedTeamMessagePending");
    expect(routeSource).toContain("sendTeamMessageMutation.variables?.teamId === selectedTeam?.teamId");
    // Revoke pending/event matching is projected into TeamCommunicationPanel via revokePendingEventId.
    expect(routeSource).toContain("revokeTeamMessageMutation.variables?.eventId");
    expect(routeSource).toContain("revokePendingEventId=");
    expect(teamCommunicationPanelSource).toContain("revokePendingEventId === event.eventId");
    expect(teamCommunicationPanelSource).toContain("onRevokeTeamMessage({ teamId: selectedTeam.teamId, eventId: event.eventId })");
    expect(routeSource).not.toContain("chatWorkspaceCache.afterTeamChanged(selectedTeamId || undefined)");
    expect(routeSource).not.toContain("revokeTeamMessageMutation.mutate(event.eventId)");
  });

  it("renders visible directional communication edges on the Team canvas", () => {
    expect(routeSource).toContain("<marker");
    expect(routeSource).toContain('id="team-edge-arrow"');
    expect(routeSource).toContain("key={edge.id}");
    expect(routeSource).toContain("Q ${line.cx} ${line.cy}");
    expect(canvasGeometrySource).toContain("nodeBoundaryPoint");
    expect(canvasGeometrySource).toContain("distanceToRectEdge");
    expect(routeSource).toContain("edgeLine(edge, displayCanvasNodes, visibleEdges)");
    expect(canvasGeometrySource).toContain("sourceFanSpread");
    expect(routeSource).not.toContain("<line key={edge.id}");
    expect(routeSource).toContain("className={styles.edges}");
    // Organization edges carry the arrow marker; communication edges stay bidirectional.
    expect(teamOrganizationCanvasSurfaceSource).toContain('fill="context-stroke"');
    expect(teamOrganizationCanvasSurfaceSource).toContain('markerEnd={communication ? undefined : "url(#team-edge-arrow)"}');
  });

  it("separates organization lines from information lines by default", () => {
    expect(routeSource).toContain("showCommunicationEdges");
    expect(routeSource).toContain("isCommunicationEdge(edge)");
    expect(routeSource).toContain("organizationEdges");
    expect(routeSource).toContain("communicationEdges");
    expect(routeSource).toContain("visibleCommunicationEdges");
    expect(routeSource).toContain("visibleCommunicationEdgeCount");
    expect(routeSource).toContain("visibleEdges");
    expect(canvasGeometrySource).toContain('edge.type === "communication"');
    expect(canvasGeometrySource).toContain('edge.type === "collaborates_with"');
    expect(routeSource).toContain("styles.edgeOrganization");
    expect(routeSource).toContain("styles.edgeCommunication");
    expect(routeSource).toContain("信息线");
    expect(routeSource).toContain("信息线已收起（");
    expect(routeSource).toContain("展开信息线");
    expect(routeSource).toContain("暂无信息线");
    expect(routeSource).toContain("没有可展开的信息线");
    expect(routeSource).toContain("收起信息线");
    expect(routeSource).toContain("Info");
    expect(routeSource).toContain('type: "reports_to"');
    expect(routeSource).not.toContain("canvas?.edges.map((edge)");
  });

  it("centers compact Team canvases and renders function role badges", () => {
    expect(routeSource).toContain("canvasViewStyle");
    expect(canvasGeometrySource).toContain("type TeamsRouteDynamicStyle");
    expect(routeAndPureSource).toContain("CANVAS_VIEWPORT_WIDTH");
    expect(routeAndPureSource).toContain("CANVAS_VIEWPORT_HEIGHT");
    expect(routeSource).toContain("canvasViewportStyle");
    expect(routeSource).toContain("lockedCanvasViewportStyle");
    expect(routeSource).toContain("setLockedCanvasViewportStyle(canvasViewportStyle)");
    expect(routeSource).toContain("canvasFrameSize");
    expect(routeSource).toContain("canvasViewStyle(displayCanvasNodes, canvasFrameSize)");
    expect(routeSource).toContain("ResizeObserver");
    expect(routeSource).toContain("styles.canvasViewport");
    expect(canvasGeometrySource).toContain("--canvas-offset-x");
    expect(canvasGeometrySource).toContain("--canvas-scale");
    expect(canvasGeometrySource).toContain("--node-x");
    expect(routeSource).toContain("teamCanvasNodeStyle(node)");
    expect(routeSource).toContain("roleBadgeTone");
    expect(routeSource).toContain("teamNodeFunctionLabel");
    expect(teamRouteShellModelSource).toContain("能力管家");
    // Role badge classes live on teamsWorkbenchChrome style map.
    expect(teamsWorkbenchChromeSource).toContain("nodeRoleBadge");
    expect(teamsWorkbenchChromeSource).toContain("nodeRoleBadgeLead");
    expect(teamsWorkbenchChromeSource).toContain("nodeRoleBadgeAdvisor");
    expect(teamsWorkbenchChromeSource).toContain("nodeRoleBadgeSteward");
    expect(routeSource).toContain("roleBadgeTone");
    expect(routeStyles.canvasViewport).toContain("h-[760px]");
    expect(routeStyles.canvasViewport).toContain("w-[1180px]");
    expect(routeStyles.canvasViewport).toContain("[transform:scale(var(--canvas-scale,1))]");
    expect(routeStyles.edges).toContain("absolute");
    expect(routeStyles.edges).toContain("[transform:translate(var(--canvas-offset-x,0px),var(--canvas-offset-y,0px))]");
    expect(routeStyles.node).toContain("!absolute");
    expect(routeStyles.node).toContain("left-[calc(var(--canvas-offset-x,0px)+var(--node-x,0px))]");
    expect(routeStyles.node).toContain("top-[calc(var(--canvas-offset-y,0px)+var(--node-y,0px))]");
  });

  it("shows agent display name, localized status, and purpose on canvas node cards", () => {
    expect(teamOrganizationCanvasSurfaceSource).toContain("canvasNodeAgentLine(node, display?.name, lang)");
    expect(teamOrganizationCanvasSurfaceSource).toContain("<small>{agentLine}</small>");
    expect(teamOrganizationCanvasSurfaceSource).toContain("className={styles.nodePurpose}");
    expect(teamOrganizationCanvasSurfaceSource).not.toContain("{node.agentCode || node.status}");
    expect(teamCanvasNodePresentationSource).toContain("canvasNodeStatusLabel(node, lang)");
    expect(teamRouteShellModelSource).toContain("canvasNodeStatusLabel");
    expect(routeStyles.node).toContain("h-[108px]");
    expect(routeStyles.node).toContain("grid-rows-[auto_auto_auto_auto]");
    expect(routeStyles.nodeIcon).toContain("row-span-4");
    expect(routeStyles.nodePurpose).toContain("text-[var(--fg-tertiary)]");
    expect(routeStyles.nodePurpose).toContain("[font-size:var(--vui-font-xs)]");
    // Research role badge foreground matches its warm accent like the other role badges.
    expect(routeStyles.nodeRoleBadgeResearch).toContain("[--node-role-fg:var(--accent-warm)]");
  });

  it("keeps Teams dynamic layout values behind typed CSS variable helpers", () => {
    // Wave 8L: Teams SC graph mount lives on graph workspace panel; lazy export stays on teamLazyPanels.
    expect(teamLazyPanelsSource).toContain("TeamWorkflowGraphView");
    expect(teamSourceCollectionGraphWorkspacePanelSource.match(/<TeamWorkflowGraphView/g)?.length ?? 0).toBe(1);
    expect(teamWorkflowStatusPanelsSource.match(/<TeamWorkflowGraphView/g)?.length ?? 0).toBe(1);
    expect(routeSource).not.toContain("workflowGraphFrameStyle(visibleGraphLayout)");
    expect(routeSource).not.toContain("workflowGraphFrameStyle(teamWorkflowCandidateGraphLayout)");
    expect(routeSource).not.toContain("className={styles.workflowGraphSvg}");
    expect(workflowGraphViewSource).toContain("workflowGraphFrameStyle(layout)");
    expect(workflowGraphViewSource).toContain("workflowGraphNodeStyle(node)");
    expect(workflowGraphViewSource).toContain("className={styles.workflowGraphSvg}");
    expect(routeSource).toContain("teamCanvasNodeStyle(node)");
    expect(routeSource).not.toContain("style={{");
    expect(workflowGraphViewSource).not.toContain("style={{");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("min-h-[var(--workflow-graph-height");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("w-[var(--workflow-graph-width");
    expect(workflowGraphViewStyles.workflowGraphCanvas).toContain("relative");
    expect(workflowGraphViewStyles.workflowGraphSvg).toContain("h-full");
    expect(workflowGraphViewStyles.workflowGraphSvg).toContain("w-full");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("absolute");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("left-[var(--workflow-graph-node-x");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("top-[var(--workflow-graph-node-y");
  });

  it("keeps read-only research canvas auto layout visual-only and deterministic", () => {
    expect(routeSource).toMatch(/from "\.\/?(\.\.\/)?teams\/canvasGeometry"|from "\.\/canvasGeometry"/);
    expect(canvasGeometrySource).toContain("function autoLayoutResearchCanvasNodes");
    expect(canvasGeometrySource).toContain("researchCanvasRoleLayer");
    expect(canvasGeometrySource).toContain("RESEARCH_CANVAS_AUTO_LAYOUT_LAYER_GAP");
    expect(canvasGeometrySource).toContain("RESEARCH_CANVAS_AUTO_LAYOUT_ROW_GAP");
    expect(canvasGeometrySource).toContain("teamCanvasNodeSortKey");
    expect(canvasGeometrySource).toContain("positions.set(node.id");
    expect(canvasGeometrySource).toContain("return nodes.map((node) => ({");
    expect(routeSource).toContain("displayCanvasNodes.map((node)");
    expect(routeSource).not.toContain("saveCanvas(autoLayoutCanvasNodes");
    expect(routeSource).not.toContain("saveCanvas(displayCanvasNodes");
    expect(routeStyles.canvasLayoutModeSwitch).toBeTypeOf("string");
  });

  it("lets users drag canvas nodes and persist their positions", () => {
    expect(routeSource).toContain("nodePositionDrafts");
    expect(routeSource).toContain("dragStateRef");
    expect(routeSource).toContain("dragFrameRef");
    expect(routeSource).toContain("startNodeDrag");
    expect(routeSource).toContain("moveNodeDrag");
    expect(routeSource).toContain("finishNodeDrag");
    expect(routeSource).toContain("requestNodeDragFrame");
    expect(routeSource).toContain("window.requestAnimationFrame");
    expect(routeSource).toContain("window.cancelAnimationFrame");
    expect(routeSource).toContain("commitNodeDragPosition(dragState)");
    expect(routeSource).toContain("setPointerCapture(event.pointerId)");
    expect(routeSource).toContain("releasePointerCapture(event.pointerId)");
    expect(routeSource).toContain("buildCanvasWithDraggedNode");
    expect(routeSource).toContain("export function buildCanvasWithDraggedNode");
    expect(routeSource).toContain("onPointerDown={researchCanvasReadOnly ? undefined : (event) => onNodePointerDown?.(event, node)}");
    expect(routeSource).toContain("onPointerMove={researchCanvasReadOnly ? undefined : onNodePointerMove}");
    expect(routeSource).toContain("onPointerUp={researchCanvasReadOnly ? undefined : onNodePointerUp}");
    expect(routeSource).toContain("onNodePointerDown: startNodeDrag");
    expect(routeSource).toContain("onNodePointerDown={p.onNodePointerDown}");
    expect(routeSource).toContain("edgeLine(edge, displayCanvasNodes, visibleEdges)");
  });

  it("keeps Team detail loading inside the workspace shell during cold loading", () => {
    expect(routeSource).toContain("const selectedTeamReference = visibleTeams.find((team) => team.teamId === effectiveTeamId) ?? null");
    expect(routeSource).toContain("const selectedTeamDetailLoading = Boolean(");
    expect(routeSource).toContain("const researchTeamDetailDegraded = Boolean(");
    expect(routeSource).toContain("selectedTeamDetailLoading && !researchWorkflowTeamSelected");
    expect(routeSource).toContain("selectedTeamDetailUnavailable && !researchWorkflowTeamSelected");
    // Wave 8H: degraded research notice lives on launcher panel.
    expect(teamResearchStageLauncherPanelSource).toContain("researchStageDegradedNotice");
    expect(teamResearchStageLauncherPanelSource).toContain("团队详情暂时不可用；当前保留已读取的科研状态。");
    expect(routeSource).toContain("const agentDirectoryHydrating = bindings.some(");
    // Wave 8G: stage member loading copy lives in TeamResearchStageAgentPanel.
    expect(teamResearchStageAgentPanelSource).toContain("正在读取成员配置");
    // Wave 8H: stage status loading copy lives on launcher panel.
    expect(teamResearchStageLauncherPanelSource).toContain("状态同步中");
    expect(teamResearchStageLauncherPanelSource).toContain("状态暂不可用");
    expect(routeSource).toContain("const showTeamLoadingSurface =");
    expect(routeSource).toContain("const showTeamDetailUnavailableSurface =");
    expect(routeSource).toContain("VStateSurface");
    expect(routeStyles.teamLoadingInlineSurface).toBeTypeOf("string");
    expect(routeStyles.teamLoadingInlineSurface).toContain("min-h-[96px]");

    // R1-c: gate early-return via renderTeamsShellGate → TeamsShellGateSurface (VDenseOpsPage).
    const shellGateStart = routeSource.indexOf("const shellGate = renderTeamsShellGate");
    const shellGateEnd = routeSource.indexOf("if (researchCanvasVisible)");
    expect(shellGateStart).toBeGreaterThanOrEqual(0);
    expect(shellGateEnd).toBeGreaterThan(shellGateStart);
    const loadingShellSource = routeSource.slice(shellGateStart, shellGateEnd);
    expect(loadingShellSource).toMatch(/TeamsShellGateSurface|renderTeamsShellGate|shellGate/);
    expect(routeSource).toContain("VDenseOpsPage");
    expect(loadingShellSource).toContain("showTeamUnavailableSurface");
    expect(loadingShellSource).toContain("showTeamDetailUnavailableSurface");
    expect(loadingShellSource).not.toContain("showTeamInitialLoadingSurface ||");
    expect(loadingShellSource).not.toContain("showTeamLoadingSurface ? (");
    expect(routeSource).toContain("teamWorkspaceLoadingTitle");
    expect(routeSource).toContain("className={styles.teamLoadingInlineSurface}");
    // Canvas branch uses TeamsCanvasComposer (wraps VCanvasWorkbenchPage) via R2-q extractor.
    expect(routeSource).toContain("TeamsCanvasComposer");
    expect(routeSource).toContain("VCanvasWorkbenchPage");
    expect(renderTeamsWorkbenchCanvasPageSource).toContain("TeamsCanvasComposer");
    expect(routeSource).toContain("className={styles.teamLoadingInlineSurface}");

    const standaloneSource = routeSource.slice(
      routeSource.indexOf("if (sourceCollectionStandalone)"),
      routeSource.indexOf("const teamShellRail"),
    );
    expect(standaloneSource).toContain("renderSourceCollectionStandalonePage");
    expect(standaloneSource).toContain("teamWorkspaceLoadingTitle");
    expect(standaloneSource).not.toContain("researchWorkflowTeamSelected && !showTeamLoadingSurface && !showTeamDetailUnavailableSurface ? (");
  });

  it("routes the source collection ingestion step to the single source ingestion Agent", () => {
    expect(teamSourceCollectionShellModelSource).toContain('ingestion: ["source_ingestor"]');
    expect(routeSource).toContain("资料入库");
    expect(teamRouteShellModelSource).toContain("资料入库 Agent 私聊");
    expect(routeSource).toContain("sourceCollectionIngestorAgentId");
    expect(routeSource).not.toContain("知识库管理员入库审核");
    expect(routeSource).not.toContain("共享记忆前审");
    expect(routeSource).not.toContain('ingestion: ["source_ingestor", "source_relation_mapper"]');
  });

  it("shows only the selected run's close gate and lets users locate its unfinished stage", () => {
    const standaloneSource = routeSource.slice(
      routeSource.indexOf("if (sourceCollectionStandalone)"),
      routeSource.indexOf("const teamShellRail"),
    );
    expect(stageProjectionSource).toContain("sourceCollectionPhaseCloseGateForRun");
    expect(stageProjectionSource).toContain('scope.kind !== "source_run"');
    expect(stageProjectionSource).toContain("scope.includesHistorical === true");
    // R2-o: phase close gate ownership moved into summary projection pure helper.
    expect(deriveSourceCollectionSummaryProjectionSource).toContain("sourceCollectionPhaseCloseGateForRun(");
    expect(useSourceCollectionPresentationSource).toContain("sourceCollectionPhaseCloseGate");
    // Progress unified into top command bar (not left-rail PhaseCloseGate stack).
    expect(sourceCollectionControllerSource).toContain('progressPlacement="command-bar"');
    expect(sourceCollectionControllerSource).toContain("sourceCollectionPhaseCloseGateNextStage");
    expect(sourceCollectionControllerSource).toContain("phaseCloseGate={null}");
    expect(sourceCollectionControllerSource).toContain("chrome.selectSourceCollectionStage");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain('progressPlacement = "command-bar"');
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("commandSteps");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain('data-progress-placement={progressPlacement}');
    expect(teamLazyPanelsSource).toContain('createLazyNamedTeamPanel(loadTeamSourceCollectionPanels, "TeamSourceCollectionSearchBriefPanel")');
    expect(routeSource).toContain("function renderSourceCollectionSearchBrief(");
    expect(routeSource).toContain("createSourceCollectionController");
    expect(standaloneSource).toContain("renderSourceCollectionStandalonePage");
    expect(standaloneSource).toContain("sourceCollectionRunsQuery");
    expect(standaloneSource).toContain("sourceCollectionFindingStageCompact");
    expect(standaloneSource).toContain("sourceCollectionSelectedRunTopic");
    expect(routeSource).toContain("sourceCollectionDraftHydratedRunIdRef");
    expect(deriveSourceCollectionListMetricsSource).toContain("sourceCollectionRunSummary?.recordCount");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("phaseCloseGate?: ReactNode");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("styles.sourceCollectionRunContext");
    expect(teamSourceCollectionOverviewPanelSource).toContain("phaseCloseGate?: ReactNode");
    expect(teamSourceCollectionOverviewPanelSource).toContain("{phaseCloseGate}");
    expect(teamSourceCollectionPhaseCloseGatePanelSource).toContain('data-vui-product="source-collection-phase-close-gate"');
    expect(teamSourceCollectionPhaseCloseGatePanelSource).toContain("不会用全局历史统计替代");
    expect(teamSourceCollectionPhaseCloseGatePanelSource).toContain("onOpenStage(nextStage)");
    expect(teamSourceCollectionPhaseCloseGatePanelSource).toContain('data-compact="true"');
    expect(teamSourceCollectionPhaseCloseGatePanelSource).toContain('data-compact-steps="hidden"');
    expect(teamSourceCollectionPhaseCloseGatePanelSource).toContain("运行详情");
    expect(teamSourceCollectionPhaseCloseGatePanelSource).toContain("阶段明细见下方");
    // Compact mode keeps steps CSS for full gate layout, but must not render the step list.
    expect(teamSourceCollectionPhaseCloseGatePanelSource).toContain("Do not re-list all four stages");
    expect(teamSourceCollectionPhaseCloseGatePanelStyles.phaseCloseGateSteps).toContain("grid");
    expect(teamSourceCollectionPhaseCloseGatePanelStyles.phaseCloseGateAction).toContain("w-fit");
    expect(teamSourceCollectionPhaseCloseGatePanelStyles.phaseCloseGateHeader).toContain("max-[640px]");
  });

  it("keeps the project-scoped source reset visible while the project snapshot is still catching up", () => {
    expect(routeSource).toContain("const sourceCollectionResetResearchProjectId = activeSourceCollectionResearchProjectId.trim();");
    expect(routeSource).toContain("const sourceCollectionResetAvailable = Boolean(");
    expect(routeSource).toContain("&& sourceCollectionRuns.length > 0,");
    // Reset actions mount under the right-rail stage card via active-stage inject.
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("projectReset");
    expect(teamSourceCollectionActiveStageWorkspacePanelSource).toContain("source-collection-reset-sources-only");
    expect(routeSource).toContain("researchProjectId: sourceCollectionResetResearchProjectId");
    expect(routeSource).toContain("sourceCollectionFreshProjectDraftIdRef.current = \"\";");
    expect(routeSource).toContain("function handleSourceCollectionProjectResetSuccess");
  });
});
