/**
 * Workspace panel renderers extracted from TeamsRoute for orchestration slim-down.
 * Route owns state/mutations; this module only mounts already-extracted panels.
 */
import { agentDisplayInfo } from "../agentDisplay";
import { TeamMemoryIndexPanel } from "../TeamMemoryIndexPanel";
import {
  TeamAiSearchWorkspacePanel,
  TeamExperimentPlanningLedgerPanel,
  TeamKnowledgeCollectionCompletionFlowPanel,
  TeamResearchLoopPanel,
  TeamResearchStageAgentPanel,
  TeamResearchStageAgentSummary,
} from "./teamLazyPanels";
import { TeamCanvasReadOnlyInspector } from "./TeamCanvasReadOnlyInspector";
import { TeamNodeBindingPanel } from "./TeamNodeBindingPanel";
import { teamNodeFunctionLabel } from "./teamRouteShellModel";
import { teamCanvasNodeAgentSourceRoute } from "./researchStageAgentPresentation";
import { researchWorkspaceStageRoute } from "./researchWorkspaceModel";
import { parseSourceCollectionStageModuleId } from "./teamRouteShellModel";
import type { ResearchStageType } from "./source-collection/stageProjection";
import type { ExperimentPlanRecord } from "./experimentLoopModel";

/** Loose context bag from TeamsRoute; keep typing light to avoid dual ownership of route state. */
export type TeamsWorkspacePanelRenderContext = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
};

export function createTeamsWorkspacePanelRenderers(ctx: TeamsWorkspacePanelRenderContext) {
    function renderResearchStageAgentSummary(stageType: ResearchStageType) {
      const {
        agentSummaryQuery,
        lang,
        researchStageAgentBindingsByStage
      } = ctx;

      const bindings = researchStageAgentBindingsByStage[stageType] ?? [];
      const agentDirectoryHydrating = bindings.some(
        (binding: { agentId?: string; agent?: unknown }) => binding.agentId && !binding.agent,
      )
        && (agentSummaryQuery.isPending || agentSummaryQuery.isFetching);
      return (
        <TeamResearchStageAgentSummary
          lang={lang}
          bindings={bindings}
          agentDirectoryHydrating={agentDirectoryHydrating}
        />
      );
    }
    function renderResearchStageAgentPanel(stageType: ResearchStageType, variant: "compact" | "page" = "page") {
      const {
        lang,
        researchStageAgentBindingsByStage
      } = ctx;

      const bindings = researchStageAgentBindingsByStage[stageType] ?? [];
      return (
        <TeamResearchStageAgentPanel
          lang={lang}
          stageType={stageType}
          bindings={bindings}
          variant={variant}
        />
      );
    }
    function renderTeamMemoryIndex() {
      const {
        lang,
        selectedTeam,
        selectedTeamGraphRoute,
        selectedTeamKnowledgeRoute,
        selectedTeamMemoryMembers
      } = ctx;

      if (!selectedTeam) {
        return null;
      }
      return (
        <TeamMemoryIndexPanel
          lang={lang}
          members={selectedTeamMemoryMembers}
          knowledgeRoute={selectedTeamKnowledgeRoute}
          graphRoute={selectedTeamGraphRoute}
        />
      );
    }
    function renderResearchCanvasReadOnlyPanel() {
      const {
        activeAgents,
        lang,
        selectedNode,
        styles,
        validation
      } = ctx;

      const node = selectedNode;
      const agent = node?.agentId
        ? activeAgents.find((item: { agentId?: string }) => item.agentId === node.agentId)
        : null;
      const display = agent ? agentDisplayInfo(agent, lang) : null;
      return (
        <TeamCanvasReadOnlyInspector
          lang={lang}
          node={node}
          agentName={display?.name}
          functionLabel={node ? teamNodeFunctionLabel(node, display?.functionLabel, lang) : ""}
          validationIssues={validation?.issues ?? []}
          className={styles.canvasReadOnlyPanel}
          noticeClassName={styles.canvasReadOnlyNotice}
          nodeClassName={styles.canvasReadOnlyNode}
          nodeWideClassName={styles.canvasReadOnlyNodeWide}
          emptyClassName={styles.empty}
          issueListClassName={styles.issueList}
          issueClassName={styles.issue}
        />
      );
    }
    function renderTeamNodeBindingPanel() {
      const {
        activeAgents,
        agentSummaryQuery,
        agentTeamMembership,
        applyNodeDraft,
        connectFromLead,
        deleteSelectedNode,
        durableCanvas,
        hasWritableCanvas,
        lang,
        nodeDraft,
        selectedNode,
        selectedTeam,
        selectedTeamSaveCanvasPending,
        setNodeDraft,
        showNodeBindingPanel,
        styles,
        teamDetailQuery,
        unbindSelectedNode,
        validation
      } = ctx;

      if (!showNodeBindingPanel) {
        return null;
      }
      return (
        <TeamNodeBindingPanel
          lang={lang}
          selectedTeam={selectedTeam}
          selectedNode={selectedNode}
          nodeDraft={nodeDraft}
          onNodeDraftChange={(patch: Record<string, unknown>) => setNodeDraft((current: Record<string, unknown>) => ({ ...current, ...patch }))}
          activeAgents={activeAgents}
          agentTeamMembership={agentTeamMembership}
          agentDisplayName={(agent: Parameters<typeof agentDisplayInfo>[0]) => agentDisplayInfo(agent, lang).name}
          agentSourceRoute={teamCanvasNodeAgentSourceRoute}
          durableCanvas={durableCanvas}
          hasWritableCanvas={hasWritableCanvas}
          savePending={selectedTeamSaveCanvasPending}
          detailPending={teamDetailQuery.isPending}
          agentsPending={agentSummaryQuery.isPending}
          validationIssues={validation?.issues ?? []}
          onSave={applyNodeDraft}
          onConnectFromLead={connectFromLead}
          onUnbind={unbindSelectedNode}
          onDelete={deleteSelectedNode}
          styles={{
            section: styles.nodeBindingSection,
            placeholder: styles.nodeBindingPlaceholder,
            empty: styles.empty,
            sourceAuthority: styles.nodeSourceAuthority,
            actionRow: styles.actionRow,
            dangerButton: styles.dangerButton,
            issueList: styles.issueList,
            issue: styles.issue,
          }}
        />
      );
    }
    function renderKnowledgeCollectionCompletionFlowPanel() {
      const {
        lang,
        openSourceCollectionStageAgentChat,
        researchCanvasReadOnly,
        researchWorkflowTeamSelected,
        runKnowledgeCollectionCompletionAction,
        selectedTeamKnowledgeCollectionIngestPending,
        selectedTeamKnowledgeCollectionWorkRun,
        sourceCollectionActionDisabledTitle,
        sourceCollectionCompletionActionDisabled,
        sourceCollectionCompletionActionReadiness,
        sourceCollectionCompletionFlow,
        sourceCollectionCompletionFlowNodes,
        sourceCollectionStageModules,
        sourceCollectionStagePrimaryAgentBinding,
        sourceCollectionStageReturnRoute,
        sourceCollectionStepClassName,
        workflowIngestionToneBound
      } = ctx;

      // Defensive no-ops: missing binders must not crash canvas completion-flow slot.
      const stagePrimaryBinding =
        typeof sourceCollectionStagePrimaryAgentBinding === "function"
          ? sourceCollectionStagePrimaryAgentBinding
          : () => null;
      const stageReturnRoute =
        typeof sourceCollectionStageReturnRoute === "function"
          ? sourceCollectionStageReturnRoute
          : () => "";
      const openStageAgentChat =
        typeof openSourceCollectionStageAgentChat === "function"
          ? openSourceCollectionStageAgentChat
          : () => {};
      const stepClassName =
        typeof sourceCollectionStepClassName === "function"
          ? sourceCollectionStepClassName
          : () => "";
      const actionDisabledTitle =
        typeof sourceCollectionActionDisabledTitle === "function"
          ? sourceCollectionActionDisabledTitle
          : () => undefined;
      const ingestionTone =
        typeof workflowIngestionToneBound === "function"
          ? workflowIngestionToneBound
          : () => "";

      return (
        <TeamKnowledgeCollectionCompletionFlowPanel
          lang={lang}
          researchWorkflowTeamSelected={researchWorkflowTeamSelected}
          researchCanvasReadOnly={researchCanvasReadOnly}
          selectedTeamKnowledgeCollectionWorkRun={selectedTeamKnowledgeCollectionWorkRun}
          sourceCollectionCompletionFlow={sourceCollectionCompletionFlow}
          sourceCollectionCompletionFlowNodes={Array.isArray(sourceCollectionCompletionFlowNodes) ? sourceCollectionCompletionFlowNodes : []}
          sourceCollectionStageModules={Array.isArray(sourceCollectionStageModules) ? sourceCollectionStageModules : []}
          workflowIngestionTone={ingestionTone}
          parseSourceCollectionStageModuleId={parseSourceCollectionStageModuleId}
          sourceCollectionStagePrimaryAgentBinding={stagePrimaryBinding}
          sourceCollectionStageReturnRoute={stageReturnRoute}
          openSourceCollectionStageAgentChat={openStageAgentChat}
          sourceCollectionStepClassName={stepClassName}
          runKnowledgeCollectionCompletionAction={
            typeof runKnowledgeCollectionCompletionAction === "function"
              ? runKnowledgeCollectionCompletionAction
              : () => {}
          }
          sourceCollectionCompletionActionDisabled={Boolean(sourceCollectionCompletionActionDisabled)}
          selectedTeamKnowledgeCollectionIngestPending={Boolean(selectedTeamKnowledgeCollectionIngestPending)}
          sourceCollectionActionDisabledTitle={actionDisabledTitle}
          sourceCollectionCompletionActionReadiness={sourceCollectionCompletionActionReadiness}
        />
      );
    }
    function renderAiSearchSourceScopePanel() {
      const {
        aiSearchRunCanStart,
        aiSearchRunTopic,
        aiSearchRuns,
        aiSearchRunsQuery,
        lang,
        latestAiSearchRun,
        selectedTeam,
        selectedTeamStartAiSearchError,
        selectedTeamStartAiSearchPending,
        setAiSearchRunTopic,
        startAiSearchRunMutation,
        teamDetailQuery
      } = ctx;

      return (
        <TeamAiSearchWorkspacePanel
          lang={lang}
          scope={selectedTeam?.sourceScope ?? null}
          teamDetailPending={teamDetailQuery.isPending}
          runs={aiSearchRuns}
          runsPending={aiSearchRunsQuery.isPending}
          runsFetching={aiSearchRunsQuery.isFetching}
          visibleRunCount={aiSearchRunsQuery.data?.summary.visibleRunCount ?? aiSearchRuns.length}
          totalRunCount={aiSearchRunsQuery.data?.summary.runCount ?? aiSearchRuns.length}
          latestRun={latestAiSearchRun}
          topic={aiSearchRunTopic}
          onTopicChange={setAiSearchRunTopic}
          canStart={aiSearchRunCanStart}
          startPending={selectedTeamStartAiSearchPending}
          startErrorMessage={selectedTeamStartAiSearchError?.message ?? null}
          onStart={(payload) => startAiSearchRunMutation.mutate(payload)}
          teamId={selectedTeam?.teamId}
        />
      );
    }
    function renderResearchLoopPanel(activePlan: ExperimentPlanRecord | null, variant: "experiment" | "iteration" = "experiment") {
      const {
        createResearchLoopFromWorkspace,
        lang,
        materializeResearchLoopIterationDesignMutation,
        recordResearchLoopDecisionFromWorkspace,
        recordResearchLoopEvidenceFromWorkspace,
        researchLoopCreateDraft,
        researchLoopDecisionDraft,
        researchLoopEvidenceDraft,
        researchLoopStatus,
        researchLoopStatusQuery,
        researchLoopTemplatesPayload,
        selectedResearchLoopTemplateId,
        selectedTeam,
        selectedTeamCreateResearchLoopError,
        selectedTeamCreateResearchLoopPending,
        selectedTeamCreateResearchLoopResult,
        selectedTeamRecordResearchLoopDecisionError,
        selectedTeamRecordResearchLoopDecisionPending,
        selectedTeamRecordResearchLoopDecisionResult,
        selectedTeamRecordResearchLoopEvidenceError,
        selectedTeamRecordResearchLoopEvidencePending,
        selectedTeamRecordResearchLoopEvidenceResult,
        setResearchLoopCreateDraft,
        setResearchLoopDecisionDraft,
        setResearchLoopEvidenceDraft,
        setSelectedResearchLoopTemplateId,
        sourceCollectionDraft
      } = ctx;

      return (
        <TeamResearchLoopPanel
          activePlan={activePlan}
          variant={variant}
          lang={lang}
          selectedTeam={selectedTeam}
          researchLoopStatus={researchLoopStatus}
          researchLoopTemplatesPayload={researchLoopTemplatesPayload}
          selectedResearchLoopTemplateId={selectedResearchLoopTemplateId}
          setSelectedResearchLoopTemplateId={setSelectedResearchLoopTemplateId}
          researchLoopCreateDraft={researchLoopCreateDraft}
          setResearchLoopCreateDraft={setResearchLoopCreateDraft}
          researchLoopEvidenceDraft={researchLoopEvidenceDraft}
          setResearchLoopEvidenceDraft={setResearchLoopEvidenceDraft}
          researchLoopDecisionDraft={researchLoopDecisionDraft}
          setResearchLoopDecisionDraft={setResearchLoopDecisionDraft}
          sourceCollectionDraft={sourceCollectionDraft}
          researchLoopStatusQuery={researchLoopStatusQuery}
          selectedTeamCreateResearchLoopPending={selectedTeamCreateResearchLoopPending}
          selectedTeamCreateResearchLoopError={selectedTeamCreateResearchLoopError}
          selectedTeamCreateResearchLoopResult={selectedTeamCreateResearchLoopResult}
          selectedTeamRecordResearchLoopEvidencePending={selectedTeamRecordResearchLoopEvidencePending}
          selectedTeamRecordResearchLoopEvidenceError={selectedTeamRecordResearchLoopEvidenceError}
          selectedTeamRecordResearchLoopEvidenceResult={selectedTeamRecordResearchLoopEvidenceResult}
          selectedTeamRecordResearchLoopDecisionPending={selectedTeamRecordResearchLoopDecisionPending}
          selectedTeamRecordResearchLoopDecisionError={selectedTeamRecordResearchLoopDecisionError}
          selectedTeamRecordResearchLoopDecisionResult={selectedTeamRecordResearchLoopDecisionResult}
          materializeResearchLoopIterationDesignMutation={materializeResearchLoopIterationDesignMutation}
          createResearchLoopFromWorkspace={createResearchLoopFromWorkspace}
          recordResearchLoopEvidenceFromWorkspace={recordResearchLoopEvidenceFromWorkspace}
          recordResearchLoopDecisionFromWorkspace={recordResearchLoopDecisionFromWorkspace}
        />
      );
    }
    function renderExperimentPlanningLedgerPanel() {
      const {
        completeScientificHypothesisFromWorkspace,
        createExperimentHypothesisRevisionFromWorkspace,
        createExperimentPlanFromWorkspace,
        experimentBaselineArtifactDraft,
        experimentFullRunResultDraft,
        experimentKnowledgeIngestionDraft,
        experimentMethodCatalogQuery,
        experimentPlanningStatus,
        experimentPlanningStatusQuery,
        experimentSmokeResultDraft,
        freezeExperimentDesignFromWorkspace,
        lang,
        materializeEngineeringProxyHypothesisFromWorkspace,
        navigate,
        preferredExperimentMethod,
        registerExperimentBaselineArtifactFromWorkspace,
        registerExperimentFullRunResultFromWorkspace,
        registerExperimentSmokeResultFromWorkspace,
        requestExperimentKnowledgeIngestionFromWorkspace,
        reviewExperimentHypothesisFromWorkspace,
        runExperimentSmokeFromWorkspace,
        searchParams: searchParamsProp,
        selectedTeam,
        selectedTeamCompleteScientificHypothesisCandidateId,
        selectedTeamCompleteScientificHypothesisError,
        selectedTeamCreateExperimentHypothesisRevisionCandidateId,
        selectedTeamCreateExperimentHypothesisRevisionError,
        selectedTeamCreateExperimentPlanError,
        selectedTeamCreateExperimentPlanPending,
        selectedTeamCreateExperimentPlanResult,
        selectedTeamFreezeExperimentDesignError,
        selectedTeamFreezeExperimentDesignPending,
        selectedTeamFreezeExperimentDesignResult,
        selectedTeamMaterializeEngineeringProxyError,
        selectedTeamMaterializeEngineeringProxyPending,
        selectedTeamRegisterExperimentBaselineArtifactError,
        selectedTeamRegisterExperimentBaselineArtifactPending,
        selectedTeamRegisterExperimentBaselineArtifactResult,
        selectedTeamRegisterExperimentFullRunResultError,
        selectedTeamRegisterExperimentFullRunResultPending,
        selectedTeamRegisterExperimentFullRunResultResult,
        selectedTeamRegisterExperimentSmokeResultError,
        selectedTeamRegisterExperimentSmokeResultPending,
        selectedTeamRegisterExperimentSmokeResultResult,
        selectedTeamRequestExperimentKnowledgeIngestionError,
        selectedTeamRequestExperimentKnowledgeIngestionPending,
        selectedTeamRequestExperimentKnowledgeIngestionResult,
        selectedTeamReviewExperimentHypothesisCandidateId,
        selectedTeamReviewExperimentHypothesisError,
        selectedTeamRunExperimentSmokeError,
        selectedTeamRunExperimentSmokePending,
        selectedTeamRunExperimentSmokeResult,
        setExperimentBaselineArtifactDraft,
        setExperimentFullRunResultDraft,
        setExperimentKnowledgeIngestionDraft,
        setExperimentSmokeResultDraft
      } = ctx;

      return (
        <TeamExperimentPlanningLedgerPanel
          lang={lang}
          selectedTeam={selectedTeam}
          experimentPlanningStatus={experimentPlanningStatus}
          experimentPlanningStatusQuery={experimentPlanningStatusQuery}
          experimentMethodCatalogQuery={experimentMethodCatalogQuery}
          preferredExperimentMethod={preferredExperimentMethod}
          searchParams={searchParamsProp ?? null}
          experimentBaselineArtifactDraft={experimentBaselineArtifactDraft}
          setExperimentBaselineArtifactDraft={setExperimentBaselineArtifactDraft}
          experimentSmokeResultDraft={experimentSmokeResultDraft}
          setExperimentSmokeResultDraft={setExperimentSmokeResultDraft}
          experimentFullRunResultDraft={experimentFullRunResultDraft}
          setExperimentFullRunResultDraft={setExperimentFullRunResultDraft}
          experimentKnowledgeIngestionDraft={experimentKnowledgeIngestionDraft}
          setExperimentKnowledgeIngestionDraft={setExperimentKnowledgeIngestionDraft}
          selectedTeamCreateExperimentPlanPending={selectedTeamCreateExperimentPlanPending}
          selectedTeamCreateExperimentPlanError={selectedTeamCreateExperimentPlanError}
          selectedTeamCreateExperimentPlanResult={selectedTeamCreateExperimentPlanResult}
          selectedTeamMaterializeEngineeringProxyPending={selectedTeamMaterializeEngineeringProxyPending}
          selectedTeamMaterializeEngineeringProxyError={selectedTeamMaterializeEngineeringProxyError}
          selectedTeamCompleteScientificHypothesisCandidateId={selectedTeamCompleteScientificHypothesisCandidateId}
          selectedTeamCompleteScientificHypothesisError={selectedTeamCompleteScientificHypothesisError}
          selectedTeamReviewExperimentHypothesisCandidateId={selectedTeamReviewExperimentHypothesisCandidateId}
          selectedTeamReviewExperimentHypothesisError={selectedTeamReviewExperimentHypothesisError}
          selectedTeamCreateExperimentHypothesisRevisionCandidateId={selectedTeamCreateExperimentHypothesisRevisionCandidateId}
          selectedTeamCreateExperimentHypothesisRevisionError={selectedTeamCreateExperimentHypothesisRevisionError}
          selectedTeamFreezeExperimentDesignPending={selectedTeamFreezeExperimentDesignPending}
          selectedTeamFreezeExperimentDesignError={selectedTeamFreezeExperimentDesignError}
          selectedTeamFreezeExperimentDesignResult={selectedTeamFreezeExperimentDesignResult}
          selectedTeamRegisterExperimentBaselineArtifactPending={selectedTeamRegisterExperimentBaselineArtifactPending}
          selectedTeamRegisterExperimentBaselineArtifactError={selectedTeamRegisterExperimentBaselineArtifactError}
          selectedTeamRegisterExperimentBaselineArtifactResult={selectedTeamRegisterExperimentBaselineArtifactResult}
          selectedTeamRunExperimentSmokePending={selectedTeamRunExperimentSmokePending}
          selectedTeamRunExperimentSmokeError={selectedTeamRunExperimentSmokeError}
          selectedTeamRunExperimentSmokeResult={selectedTeamRunExperimentSmokeResult}
          selectedTeamRegisterExperimentSmokeResultPending={selectedTeamRegisterExperimentSmokeResultPending}
          selectedTeamRegisterExperimentSmokeResultError={selectedTeamRegisterExperimentSmokeResultError}
          selectedTeamRegisterExperimentSmokeResultResult={selectedTeamRegisterExperimentSmokeResultResult}
          selectedTeamRegisterExperimentFullRunResultPending={selectedTeamRegisterExperimentFullRunResultPending}
          selectedTeamRegisterExperimentFullRunResultError={selectedTeamRegisterExperimentFullRunResultError}
          selectedTeamRegisterExperimentFullRunResultResult={selectedTeamRegisterExperimentFullRunResultResult}
          selectedTeamRequestExperimentKnowledgeIngestionPending={selectedTeamRequestExperimentKnowledgeIngestionPending}
          selectedTeamRequestExperimentKnowledgeIngestionError={selectedTeamRequestExperimentKnowledgeIngestionError}
          selectedTeamRequestExperimentKnowledgeIngestionResult={selectedTeamRequestExperimentKnowledgeIngestionResult}
          createExperimentPlanFromWorkspace={createExperimentPlanFromWorkspace}
          materializeEngineeringProxyHypothesisFromWorkspace={materializeEngineeringProxyHypothesisFromWorkspace}
          completeScientificHypothesisFromWorkspace={completeScientificHypothesisFromWorkspace}
          reviewExperimentHypothesisFromWorkspace={reviewExperimentHypothesisFromWorkspace}
          createExperimentHypothesisRevisionFromWorkspace={createExperimentHypothesisRevisionFromWorkspace}
          freezeExperimentDesignFromWorkspace={freezeExperimentDesignFromWorkspace}
          registerExperimentBaselineArtifactFromWorkspace={registerExperimentBaselineArtifactFromWorkspace}
          runExperimentSmokeFromWorkspace={runExperimentSmokeFromWorkspace}
          registerExperimentSmokeResultFromWorkspace={registerExperimentSmokeResultFromWorkspace}
          registerExperimentFullRunResultFromWorkspace={registerExperimentFullRunResultFromWorkspace}
          requestExperimentKnowledgeIngestionFromWorkspace={requestExperimentKnowledgeIngestionFromWorkspace}
          openIterationWorkspace={() => {
            if (!selectedTeam?.teamId) {
              return;
            }
            navigate(researchWorkspaceStageRoute(selectedTeam.teamId, "iteration"));
          }}
          renderResearchLoopPanel={renderResearchLoopPanel}
        />
      );
    }

  return {
    renderResearchStageAgentSummary,
    renderResearchStageAgentPanel,
    renderTeamMemoryIndex,
    renderResearchCanvasReadOnlyPanel,
    renderTeamNodeBindingPanel,
    renderKnowledgeCollectionCompletionFlowPanel,
    renderAiSearchSourceScopePanel,
    renderResearchLoopPanel,
    renderExperimentPlanningLedgerPanel,
  };
}
