import { useQuery } from "@tanstack/react-query";

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
import { isHypothesisFirstCanvasNode } from "./hypothesisFirstCanvasRegion";
import {
  shouldHideSourceFindingStart,
  type HypothesisFirstNextAction,
} from "./hypothesisFirstNextAction";
import { getNodeAdapter } from "./nodeAdapterModel";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import { ResearchCenteredEmptyState } from "./ResearchCenteredEmptyState";
import type { ResearchProcessPanel } from "./researchProcessPanelSelection";
import { handoffsForNode } from "./researchNodeHandoffModel";
import type { NodeDetailState } from "./useNodeDetailState";
import type { ResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import styles from "./ResearchProcessInspectorPane.styles";

type ReplaceParams = (patch: Record<string, string | null | undefined>) => void;

export function ResearchProcessInspectorPane(props: {
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
  retryCollectionOffer?: CommandOffer | null;
}) {
  const { scope, state, actions, nextAction, retryCollectionOffer = null } = props;
  const { lang } = useShellI18n();
  const questionDetail = useQuery({
    queryKey: queryKeys.challengeQuestionRunDetail(scope.teamId, scope.questionId),
    queryFn: () => getChallengeQuestionRunDetail(scope.teamId, scope.questionId),
    enabled: Boolean(scope.teamId && scope.questionId && scope.panel === "question"),
    staleTime: 60_000,
  });

  if (scope.panel === "progress") {
    return <ChallengeMvpProgressPanel teamId={scope.teamId} onOpenQuestion={(questionId) => actions.replaceParams({ panel: "question", questionId })} />;
  }
  if (scope.panel === "question") {
    if (!scope.questionId) {
      return (
        <ResearchCenteredEmptyState
          title="单题验收"
          hint="先在「题目进度」中选择一道题，这里会显示该题的假说、证据与验收状态。"
        />
      );
    }
    return (
      <div className={styles.question}>
        <ChallengeQuestionDetailPanel
          requestedQuestionId={scope.questionId}
          teamId={scope.teamId}
          detail={questionDetail.data}
          isLoading={questionDetail.isPending}
          errorMessage={questionDetail.error instanceof Error ? questionDetail.error.message : questionDetail.isError ? "challenge_question_run_unavailable" : ""}
          onClose={() => actions.replaceParams({ panel: "progress" })}
        />
      </div>
    );
  }
  if (scope.panel === "agents") {
    return <ResearchAgentBindingPanel teamId={scope.teamId} run={state.run} effectiveBindings={state.effectiveBindings} lang={lang} />;
  }
  if (scope.panel === "launch" || (scope.panel === "node" && !scope.selectedNodeId && !scope.runId)) {
    return (
      <ResearchRunLaunchPanel
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
    return state.run && scope.selectedNodeId === "evidence_relations"
      ? <EvidenceGraphView runId={state.run.runId} nodeId={scope.selectedNodeId} teamId={scope.teamId} runVersion={state.run.runVersion} />
      : <ResearchCenteredEmptyState title="证据关系尚不可用" />;
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
        teamId={scope.teamId}
        questionId={scope.questionId || state.run?.questionId || ""}
        nodeId={scope.selectedNodeId}
        runId={scope.runId}
        collectionChildStatus={state.projection?.run.nodeRuns.source_finding?.status ?? null}
        onOpenQuestion={(questionId) => actions.replaceParams({ panel: "question", questionId })}
        onNavigateToNode={(nodeId) => actions.replaceParams({ node: nodeId, panel: "node" })}
        onRetryCollection={retryCollectionOffer ? () => actions.submitOffer(retryCollectionOffer) : undefined}
      />
    );
  }
  if (scope.selectedNodeId && !scope.runId && state.projection) {
    return <ResearchProcessDefinitionNodePanel teamId={scope.teamId} nodeId={scope.selectedNodeId} definition={state.projection.definition} effectiveBindings={state.effectiveBindings} />;
  }
  if (!scope.selectedNodeId) return <ResearchCenteredEmptyState title="选择流程节点" />;
  if (state.nodeDetail.kind === "loading" || state.nodeDetail.kind === "idle") {
    return <VStateSurface tone="loading" title="加载节点详情" fill className={styles.fill} />;
  }
  if (state.nodeDetail.kind === "error") {
    return (
      <VSurface tone="panel" className={styles.errorSurface} data-vui="node-detail-error">
        <div className={styles.error} role="alert">节点详情加载失败：{state.nodeDetail.message}</div>
        <VButton type="button" onClick={actions.retryNodeDetail}>重试</VButton>
      </VSurface>
    );
  }
  if (state.nodeDetail.kind === "empty") return <ResearchCenteredEmptyState title="暂无节点详情" />;
  if (state.nodeDetail.kind !== "ready") return <ResearchCenteredEmptyState title="暂无节点详情" />;
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
      onOffer={actions.submitOffer}
      hideStartOffer={Boolean(nextAction && shouldHideSourceFindingStart(nextAction.stage) && scope.selectedNodeId === "source_finding")}
      statusBanner={
        nextAction && shouldHideSourceFindingStart(nextAction.stage) && scope.selectedNodeId === "source_finding"
          ? (nextAction.statusMessage || nextAction.recovery?.reason || (nextAction.stage === "collecting" ? "资料搜集中" : ""))
          : null
      }
      hypothesisNavLabel={
        nextAction && nextAction.stage !== "collecting" && nextAction.targetNodeId?.startsWith("hf_")
          ? nextAction.navigationLabel
          : null
      }
      onNavigateHypothesis={
        nextAction?.targetNodeId
          ? () => actions.replaceParams({ node: nextAction.targetNodeId, panel: "node" })
          : undefined
      }
    />
  );
}
