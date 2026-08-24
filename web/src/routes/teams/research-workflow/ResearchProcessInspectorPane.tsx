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
import { VButton, VStateSurface, VSurface } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import {
  ChallengeMvpProgressPanel,
  ChallengeQuestionDetailPanel,
  EvidenceGraphView,
  HypothesisFirstNodeInspector,
  ResearchAgentBindingPanel,
  ResearchProcessDefinitionNodePanel,
  ResearchProcessNodeInspector,
  ResearchRunLaunchPanel,
  ResearchRunTimeline,
  ResearchTeamPanel,
} from "../teamLazyPanels";
import {
  hypothesisFirstSemanticNodeId,
  isHypothesisFirstCanvasNode,
} from "./hypothesisFirstCanvasRegion";
import {
  shouldHideSourceFindingStart,
  type HypothesisFirstNextAction,
} from "./hypothesisFirstNextAction";
import { getNodeAdapter } from "./nodeAdapterModel";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import { ResearchCenteredEmptyState } from "./ResearchCenteredEmptyState";
import type { ResearchProcessPanel } from "./researchProcessPanelSelection";
import { handoffsForNode } from "./researchNodeHandoffModel";
import type { ScopedDiscussionModel } from "./scopedDiscussionModel";
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
    queryKey: queryKeys.challengeQuestionRunDetail(scope.teamId, scope.questionId),
    queryFn: () => getChallengeQuestionRunDetail(scope.teamId, scope.questionId, selectedQuestionRunId || undefined),
    enabled: Boolean(scope.teamId && scope.questionId && scope.panel === "question"),
    staleTime: 60_000,
  });

  const collectionRecoveryOwnsCurrentTask = Boolean(
    nextAction?.collectionRequestId
    && (nextAction.command === "retry_collection" || nextAction.command === "continue_collection"),
  );

  if (scope.panel === "progress") {
    return <ChallengeMvpProgressPanel teamId={scope.teamId} onOpenQuestion={(questionId) => actions.replaceParams({ panel: "question", questionId })} />;
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
  if (scope.panel === "launch" || (scope.panel === "node" && !scope.selectedNodeId && !scope.runId)) {
    return (
      <ResearchRunLaunchPanel
        lang={lang}
        teamId={scope.teamId}
        busy={state.busy}
        initialQuestionId={scope.questionId}
        onSubmit={actions.submitRun}
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
  if (scope.panel === "timeline") {
    return <ResearchRunTimeline run={state.run} projection={state.projection} insights={state.insights} />;
  }
  if (scope.panel === "team") {
    return <ResearchTeamPanel teamId={scope.teamId} teamName={scope.teamName} linkedChatRoomId={scope.linkedChatRoomId} run={state.run} projection={state.projection} effectiveBindings={state.effectiveBindings} meetingRoundId={nextAction?.meetingRoundId || ""} />;
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
        discussionModel={discussionModel}
        collectionChildStatus={collectionChildStatus}
        onOpenQuestion={(questionId) => actions.replaceParams({ panel: "question", questionId })}
        onNavigateToNode={(nodeId) => actions.replaceParams({ node: nodeId, panel: "node" })}
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
        nextAction && shouldHideSourceFindingStart(nextAction.stage) && scope.selectedNodeId === "source_finding"
          ? (nextAction.statusMessage || nextAction.recovery?.reason || (nextAction.stage === "collecting" ? (isZh ? "资料搜集中" : "Collecting sources") : ""))
          : null
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
    />
  );
}
