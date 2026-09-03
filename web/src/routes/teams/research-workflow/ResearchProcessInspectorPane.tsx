import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getChallengeQuestionRunDetail } from "../../../api/challengeQuestionRuns";
import { queryKeys } from "../../../api/queryKeys";
import type {
  CreateResearchWorkflowRunInput,
  WorkflowRunRecord,
} from "../../../api/researchWorkflow";
import type {
  EffectiveAgentBinding,
  WorkflowCanvasProjection,
} from "../../../api/types/researchWorkflow";
import type { KnowledgeInvocationBadge } from "../../../api/types/research-workflow/core";
import { VButton, VStateSurface, VSurface } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import {
  ChallengeMvpProgressPanel,
  ChallengeQuestionDetailPanel,
  EvidenceGraphView,
  HypothesisFirstNodeInspector,
  HypothesisLeaderboardPanel,
  ResearchAgentBindingPanel,
  ResearchAnomalyInboxPanel,
  ResearchProcessDefinitionNodePanel,
  ResearchProcessNodeInspector,
  ResearchRunLaunchPanel,
  ResearchRunTimeline,
  ResearchTeamPanel,
} from "../teamLazyPanels";
import {
  HYPOTHESIS_FIRST_GENERATION_NODE_ID,
  hypothesisFirstSemanticNodeId,
  isHypothesisFirstCanvasNode,
} from "./hypothesisFirstCanvasRegion";
import {
  definitionNeedsSideflowRegion,
  isKnowledgeSideflowCanvasNode,
  knowledgeSideflowSemanticNodeId,
  sideflowNodeStatesFromBadges,
} from "./knowledgeSideflowCanvasRegion";
import { NodeKnowledgeCollectionSection } from "./NodeKnowledgeCollectionSection";
import {
  shouldHideSourceFindingStart,
  type HypothesisFirstNextAction,
} from "./hypothesisFirstNextAction";
import type { HypothesisFirstV2NextAction } from "./hypothesisFirstStateV2Adapter";
import { getNodeAdapter } from "./nodeAdapterModel";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import { ResearchCenteredEmptyState } from "./ResearchCenteredEmptyState";
import type { ResearchProcessPanel } from "./researchProcessPanelSelection";
import { handoffsForNode } from "./researchNodeHandoffModel";
import type { ScopedDiscussionModel } from "./scopedDiscussionModel";
import {
  definitionNeedsStageTwoInactiveRegion,
  isStageTwoInactiveCanvasNode,
  stageTwoInactiveNodeLabel,
} from "./stageTwoCanvasRegion";
import { StageTwoInactiveNodePanel } from "./StageTwoInactiveNodePanel";
import type { NodeDetailState } from "./useNodeDetailState";
import type { ResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import styles from "./ResearchProcessInspectorPane.styles";

type ReplaceParams = (patch: Record<string, string | null | undefined>) => void;

export function ownsResearchCurrentTask(
  selectedNodeId: string | null | undefined,
  currentTaskNodeId: string | null | undefined,
): boolean {
  const selected = hypothesisFirstSemanticNodeId(selectedNodeId);
  const current = hypothesisFirstSemanticNodeId(currentTaskNodeId);
  return Boolean(selected && current && selected === current);
}

export function researchArchiveReturnNodeId(
  selectedNodeId: string | null | undefined,
  currentTaskNodeId: string | null | undefined,
): string | null {
  return hypothesisFirstSemanticNodeId(currentTaskNodeId)
    ?? hypothesisFirstSemanticNodeId(selectedNodeId);
}

export function ResearchProcessInspectorPane(props: {
  lang?: "zh" | "en";
  scope: {
    teamId: string;
    teamName: string;
    linkedChatRoomId: string;
    runId: string;
    selectedNodeId: string | null;
    questionId: string;
    panel: ResearchProcessPanel;
  };
  state: {
    run: WorkflowRunRecord | null;
    projection: WorkflowCanvasProjection | null;
    effectiveBindings: EffectiveAgentBinding[] | null;
    nodeDetail: NodeDetailState;
    insights: ResearchWorkflowInsights;
    busy: boolean;
    /** Snapshot invocationBadges (absent on legacy snapshots). */
    invocationBadges?: Record<string, KnowledgeInvocationBadge> | null;
    /** Snapshot-level command offers (knowledge commands live here, not in
     * per-node detail offers). */
    snapshotOffers?: CommandOffer[];
    /** Pinned-definition resolution diagnostic from the snapshot. */
    definitionResolution?: string;
  };
  actions: {
    replaceParams: ReplaceParams;
    retryNodeDetail: () => void;
    submitRun: (input: CreateResearchWorkflowRunInput) => Promise<void>;
    pendingTaskId: (nodeId: string) => string | null;
    submitOffer: (offer: import("../../../api/types/research-workflow/commands").CommandOffer) => Promise<void>;
  };
  nextAction?: HypothesisFirstNextAction;
  discussionModel?: ScopedDiscussionModel;
  onRecoverCollection?: (requestId: string) => Promise<void>;
  collectionRecoveryBusy?: boolean;
  collectionRecoveryError?: string | null;
  primaryActionOwnedByWorkspace?: boolean;
  /** Stale launch URLs must not create a second mutation surface. */
  allowLaunchPanel?: boolean;
  archiveSummary?: {
    selectedHypotheses?: number;
    effectiveReviews: number;
    retryAttempts: number;
    collectionRequests: number;
    reviewHistory?: Array<{
      id: string;
      round: number;
      status: string;
      digestAvailable: boolean;
      retryAttempts: number;
    }>;
  };
}) {
  const {
    scope,
    state,
    actions,
    nextAction,
    discussionModel,
    onRecoverCollection,
    collectionRecoveryBusy = false,
    collectionRecoveryError = null,
    allowLaunchPanel = true,
  } = props;
  const { lang: shellLang } = useShellI18n();
  const lang = props.lang ?? shellLang;
  const isZh = lang === "zh";
  const collectionChildStatus = nextAction?.collectionRequestId
    ? null
    : (state.projection?.run.nodeRuns.source_finding?.status ?? null);
  const [selectedQuestionRunId, setSelectedQuestionRunId] = useState("");
  const questionDetail = useQuery({
    queryKey: queryKeys.challengeQuestionRunDetail(
      scope.teamId,
      scope.questionId,
      selectedQuestionRunId,
    ),
    queryFn: () => getChallengeQuestionRunDetail(scope.teamId, scope.questionId, selectedQuestionRunId || undefined),
    enabled: Boolean(scope.teamId && scope.questionId && scope.panel === "question"),
    staleTime: 60_000,
  });

  const collectionRecoveryOwnsCurrentTask = Boolean(
    nextAction?.collectionRequestId
    && (nextAction.command === "retry_collection" || nextAction.command === "continue_collection"),
  );
  // Formal-runtime recovery belongs to the run-level task surface.  The
  // selected pipeline node is only a navigation anchor and may be stale or
  // absent, so do not require an exact node-id match before exposing the
  // server-authored recovery actions.
  const formalRuntimeOwnsInspector = Boolean(
    scope.panel === "node"
    && scope.runId
    && nextAction
    && (
      nextAction.stage === "converged"
      || (
        nextAction.stage === "blocked"
        && (
          ((nextAction as HypothesisFirstV2NextAction).canonicalActions ?? [])
            .some((action) => action.targetPhase === "formal_runtime")
          || nextAction.canonicalAction?.targetPhase === "formal_runtime"
          || !isHypothesisFirstCanvasNode(scope.selectedNodeId)
          || !isHypothesisFirstCanvasNode(nextAction.targetNodeId)
        )
      )
    ),
  );
  // Only definitions without an in-graph knowledge chain (main 3.0.0) expose
  // the sideflow section; legacy 17-node runs keep their knowledge_handoff node.
  const sideflowRegionEnabled = state.projection
    ? definitionNeedsSideflowRegion(
        state.projection.definition as { nodes: Array<{ nodeId: string }> },
      )
    : false;
  // Stage-two truncated runs render protocol/experiment selections as an
  // inactive explanation, never as runtime detail. Labels come from the
  // static region mirror: a truncated definition never carries these nodes.
  const stageTwoInactive = definitionNeedsStageTwoInactiveRegion(
    state.projection
      ? (state.projection.definition as { nodes: Array<{ nodeId: string }> })
      : null,
  );
  const stageTwoSelectedLabel = stageTwoInactive
    && scope.selectedNodeId
    && isStageTwoInactiveCanvasNode(scope.selectedNodeId)
    ? stageTwoInactiveNodeLabel(scope.selectedNodeId)
    : undefined;

  if (scope.panel === "progress") {
    // R4.3: the anomaly inbox sits directly below the batch console so the
    // operator sees the single anomaly queue next to batch observability.
    // The progress panel itself is untouched.
    return (
      <div className={styles.progressStack} data-vui="research-progress-stack">
        <ChallengeMvpProgressPanel teamId={scope.teamId} onOpenQuestion={(questionId) => actions.replaceParams({ panel: "question", questionId })} />
        <ResearchAnomalyInboxPanel
          teamId={scope.teamId}
          questionId={scope.questionId}
          lang={lang}
          onOpenItem={({ questionId, runId, nodeId }) => actions.replaceParams(runId
            ? { runId, questionId: questionId || scope.questionId, node: nodeId || null, panel: "node" }
            : { questionId: questionId || scope.questionId, panel: "question" })}
        />
      </div>
    );
  }
  if (scope.panel === "question") {
    if (!scope.questionId) {
      return (
        <ResearchCenteredEmptyState
          title={isZh ? "单题验收" : "Question review"}
          hint={isZh
            ? "先在「题目进度」中选择一道题，这里会显示该题的假说、证据与验收状态。"
            : "Select a question from progress to review its hypotheses, evidence, and acceptance status."}
        />
      );
    }
    const returnNodeId = researchArchiveReturnNodeId(
      scope.selectedNodeId,
      nextAction?.targetNodeId,
    );
    return (
      <div className={styles.question} data-vui="research-question-archive">
        <ChallengeQuestionDetailPanel
          requestedQuestionId={scope.questionId}
          teamId={scope.teamId}
          detail={questionDetail.data}
          selectedRunId={selectedQuestionRunId}
          onSelectRunId={setSelectedQuestionRunId}
          isLoading={questionDetail.isPending}
          errorMessage={questionDetail.error instanceof Error ? questionDetail.error.message : questionDetail.isError ? "challenge_question_run_unavailable" : ""}
          onClose={() => actions.replaceParams({ panel: "node", node: returnNodeId })}
          onNavigateToNode={(nodeId) => actions.replaceParams({ node: hypothesisFirstSemanticNodeId(nodeId) ?? nodeId, panel: "node" })}
          readOnlyArchive
          archiveSummary={props.archiveSummary}
        />
      </div>
    );
  }
  if (scope.panel === "agents") {
    return <ResearchAgentBindingPanel teamId={scope.teamId} run={state.run} effectiveBindings={state.effectiveBindings} lang={lang} />;
  }
  if (scope.panel === "launch" && collectionRecoveryOwnsCurrentTask) {
    return (
      <ResearchCenteredEmptyState
        title={isZh ? "资料补充需要处理" : "Evidence collection needs attention"}
        hint={nextAction?.recovery?.reason || nextAction?.statusMessage}
      />
    );
  }
  if (scope.panel === "launch" && !allowLaunchPanel) {
    return (
      <ResearchCenteredEmptyState
        title={isZh ? "当前任务已接管操作" : "The current task owns the action"}
        hint={isZh ? "请从右侧当前任务继续，启动入口已隐藏。" : "Continue from the current-task panel; the launch entry is hidden."}
      />
    );
  }
  if (
    scope.panel === "launch"
    || (scope.panel === "node" && !scope.selectedNodeId && !scope.runId)
  ) {
    return (
      <ResearchRunLaunchPanel
        lang={lang}
        teamId={scope.teamId}
        busy={state.busy}
        initialQuestionId={scope.questionId}
        onSubmit={actions.submitRun}
        onStartHypothesis={(questionId) => actions.replaceParams({
          questionId,
          node: HYPOTHESIS_FIRST_GENERATION_NODE_ID,
          panel: "node",
        })}
        onCancel={() => actions.replaceParams({ panel: "node" })}
        onContinueRun={({ runId, nodeId, questionId }) => actions.replaceParams({
          runId,
          node: nodeId,
          questionId: questionId || scope.questionId,
          panel: "node",
        })}
      />
    );
  }
  if (scope.panel === "evidence") {
    return state.run
      ? <EvidenceGraphView runId={state.run.runId} nodeId="evidence_relations" teamId={scope.teamId} runVersion={state.run.runVersion} />
      : <ResearchCenteredEmptyState title={isZh ? "证据关系尚不可用" : "Evidence relations unavailable"} />;
  }
  if (scope.panel === "leaderboard") {
    return (
      <HypothesisLeaderboardPanel
        teamId={scope.teamId}
        questionId={scope.questionId}
        lang={lang}
      />
    );
  }
  if (scope.panel === "timeline") {
    return <ResearchRunTimeline run={state.run} projection={state.projection} insights={state.insights} />;
  }
  if (scope.panel === "team") {
    return (
      <ResearchTeamPanel
        teamId={scope.teamId}
        teamName={scope.teamName}
        linkedChatRoomId={scope.linkedChatRoomId}
        run={state.run}
        projection={state.projection}
        effectiveBindings={state.effectiveBindings}
        meetingRoundId={nextAction?.meetingRoundId || ""}
        questionId={scope.questionId || state.run?.questionId || ""}
        discussionModel={discussionModel}
      />
    );
  }
  // Grayed stage-two nodes own the inspector before any runtime panel: the
  // explanation is the only thing a selection of them should ever surface.
  if (stageTwoInactive && scope.selectedNodeId && isStageTwoInactiveCanvasNode(scope.selectedNodeId)) {
    return (
      <StageTwoInactiveNodePanel
        nodeId={scope.selectedNodeId}
        nodeLabel={stageTwoSelectedLabel}
        lang={lang}
      />
    );
  }
  if (formalRuntimeOwnsInspector && scope.selectedNodeId) {
    return (
      <HypothesisFirstNodeInspector
        lang={lang}
        teamId={scope.teamId}
        questionId={scope.questionId || state.run?.questionId || ""}
        nodeId={scope.selectedNodeId}
        runId={scope.runId}
        formalRuntime
        discussionModel={discussionModel}
        collectionChildStatus={collectionChildStatus}
        onOpenQuestion={(questionId) => actions.replaceParams({ panel: "question", questionId })}
        onNavigateToNode={(nodeId) => actions.replaceParams({ node: nodeId, panel: "node" })}
        onFormalRunCreated={({ runId, nodeId, questionId }) => actions.replaceParams({
          runId,
          node: nodeId,
          questionId,
          panel: "node",
        })}
        onRetryCollection={
          onRecoverCollection && nextAction?.collectionRequestId
            ? () => onRecoverCollection(nextAction.collectionRequestId || "")
            : undefined
        }
      />
    );
  }
  // Knowledge-sideflow cards: the run-level latest invocation drives the same
  // aggregate the canvas region used, so inspector and canvas never disagree.
  if (scope.selectedNodeId && isKnowledgeSideflowCanvasNode(scope.selectedNodeId)) {
    const states = sideflowNodeStatesFromBadges(state.invocationBadges);
    const semanticId = knowledgeSideflowSemanticNodeId(scope.selectedNodeId);
    const nodeState = states.find((item) => item.sideflowNodeId === semanticId) ?? null;
    const parentBadge = nodeState?.latest?.invocationId
      ? Object.values(state.invocationBadges ?? {}).find(
          (badge) => badge.latest?.invocationId === nodeState.latest?.invocationId,
        ) ?? null
      : null;
    return (
      <NodeKnowledgeCollectionSection
        badge={parentBadge}
        offers={state.snapshotOffers ?? []}
        busy={state.busy}
        onOffer={actions.submitOffer}
        lang={lang}
      />
    );
  }
  // Hypothesis-first region cards: summary + deep link, in definition and run views alike.
  if (scope.selectedNodeId && isHypothesisFirstCanvasNode(scope.selectedNodeId)) {
    return (
      <HypothesisFirstNodeInspector
        lang={lang}
        teamId={scope.teamId}
        questionId={scope.questionId || state.run?.questionId || ""}
        nodeId={scope.selectedNodeId}
        runId={scope.runId}
        formalRuntime={formalRuntimeOwnsInspector}
        discussionModel={discussionModel}
        collectionChildStatus={collectionChildStatus}
        onOpenQuestion={(questionId) => actions.replaceParams({ panel: "question", questionId })}
        onNavigateToNode={(nodeId) => actions.replaceParams({ node: nodeId, panel: "node" })}
        onFormalRunCreated={({ runId, nodeId, questionId }) => actions.replaceParams({
          runId,
          node: nodeId,
          questionId,
          panel: "node",
        })}
        onRetryCollection={
          onRecoverCollection && nextAction?.collectionRequestId
            ? () => onRecoverCollection(nextAction.collectionRequestId || "")
            : undefined
        }
      />
    );
  }
  if (scope.selectedNodeId && !scope.runId && state.projection) {
    return <ResearchProcessDefinitionNodePanel teamId={scope.teamId} nodeId={scope.selectedNodeId} definition={state.projection.definition} effectiveBindings={state.effectiveBindings} />;
  }
  if (!scope.selectedNodeId) return <ResearchCenteredEmptyState title={isZh ? "选择流程节点" : "Select a workflow node"} />;
  if (state.nodeDetail.kind === "loading" || state.nodeDetail.kind === "idle") {
    return <VStateSurface tone="loading" title={isZh ? "加载节点详情" : "Loading node details"} fill className={styles.fill} />;
  }
  if (state.nodeDetail.kind === "error") {
    return (
      <VSurface tone="panel" className={styles.errorSurface} data-vui="node-detail-error">
        <div className={styles.error} role="alert">
          {isZh ? "节点详情加载失败：" : "Node details failed to load: "}{state.nodeDetail.message}
        </div>
        <VButton type="button" onClick={actions.retryNodeDetail}>{isZh ? "重试" : "Retry"}</VButton>
      </VSurface>
    );
  }
  if (state.nodeDetail.kind === "empty") return <ResearchCenteredEmptyState title={isZh ? "暂无节点详情" : "No node details yet"} />;
  if (state.nodeDetail.kind !== "ready") return <ResearchCenteredEmptyState title={isZh ? "暂无节点详情" : "No node details yet"} />;
  const isCurrentTask = ownsResearchCurrentTask(scope.selectedNodeId, nextAction?.targetNodeId);
  return (
    <ResearchProcessNodeInspector
      teamId={scope.teamId}
      nodeId={scope.selectedNodeId}
      adapter={getNodeAdapter(scope.selectedNodeId)}
      detail={state.nodeDetail.detail}
      effectiveBindings={state.effectiveBindings}
      budget={state.insights.budget}
      handoffs={handoffsForNode(state.insights.handoffs?.handoffs ?? [], scope.selectedNodeId)}
      handoffPending={Boolean(actions.pendingTaskId(scope.selectedNodeId))}
      busy={state.busy}
      isCurrentTask={isCurrentTask}
      primaryActionOwnedByWorkspace={props.primaryActionOwnedByWorkspace}
      onOffer={actions.submitOffer}
      hideStartOffer={Boolean(nextAction && shouldHideSourceFindingStart(nextAction.stage) && scope.selectedNodeId === "source_finding")}
      statusBanner={
        state.definitionResolution === "degraded"
          ? (isZh
              ? "未能按本运行的钉住定义解析流程拓扑，当前展示为降级视图。"
              : "This run's pinned definition could not be resolved; showing a degraded view.")
          : (nextAction && shouldHideSourceFindingStart(nextAction.stage) && scope.selectedNodeId === "source_finding"
              ? (nextAction.statusMessage || nextAction.recovery?.reason || (nextAction.stage === "collecting" ? (isZh ? "资料搜集中" : "Collecting sources") : ""))
              : null)
      }
      hypothesisNavLabel={
        nextAction && nextAction.stage !== "collecting" && nextAction.targetNodeId?.startsWith("hf_")
          ? nextAction.navigationLabel
          : null
      }
      onNavigateHypothesis={
        nextAction?.targetNodeId
          ? () => actions.replaceParams({ node: hypothesisFirstSemanticNodeId(nextAction.targetNodeId), panel: "node" })
          : undefined
      }
      collectionRecoveryRequestId={
        scope.selectedNodeId === "source_finding"
          && (nextAction?.command === "retry_collection" || nextAction?.command === "continue_collection")
          ? nextAction.collectionRequestId
          : undefined
      }
      collectionRecoveryLabel={
        nextAction?.command === "continue_collection"
          ? (isZh ? "继续搜集" : "Continue collection")
          : (isZh ? "重试搜集" : "Retry collection")
      }
      onRecoverCollection={onRecoverCollection}
      collectionRecoveryBusy={collectionRecoveryBusy}
      collectionRecoveryError={collectionRecoveryError}
      knowledgeBadge={
        sideflowRegionEnabled
          ? (scope.selectedNodeId
              ? (state.invocationBadges?.[scope.selectedNodeId] ?? null)
              : undefined)
          : undefined
      }
      knowledgeOffers={sideflowRegionEnabled ? (state.snapshotOffers ?? []) : undefined}
    />
  );
}
