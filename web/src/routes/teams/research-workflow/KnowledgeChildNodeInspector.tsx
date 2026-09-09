import { useState } from "react";

import { VButton, VErrorSummary, VStateSurface } from "../../../components/vui";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import type { TeamWorkflowCandidateListPayload } from "../../../api/types";
import { fetchTeamWorkflowCandidates } from "../../../api/teamExperiment";
import { useShellI18n } from "../../../i18n/useShellI18n";
import { getNodeAdapter } from "./nodeAdapterModel";
import { latestWorkflowCandidate, workflowCandidateGraphFromCandidate } from "../teamRouteShellModel";
import { MissingLinkWaiverSection } from "./MissingLinkWaiverSection";
import { ResearchProcessNodeInspector } from "./ResearchProcessNodeInspector";
import { useNodeDetailState } from "./useNodeDetailState";
import { useResearchWorkflowCommand } from "./useResearchWorkflowCommand";
import { useResearchWorkflowRun } from "./useResearchWorkflowRun";
import { EvidenceGraphView } from "./EvidenceGraphView";
import { ResearchRunTimeline } from "./ResearchRunTimeline";
import { useResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import { handoffsForNode } from "./researchNodeHandoffModel";

/** Sideflow cards execute against their ledger child, never the parent run. */
export function KnowledgeChildNodeInspector(props: {
  teamId: string;
  runId: string;
  nodeId: string;
  lang: "zh" | "en";
}) {
  const run = useResearchWorkflowRun(props.teamId, props.runId);
  const detail = useNodeDetailState(props.teamId, props.runId, props.nodeId, run.lastSequence);
  const command = useResearchWorkflowCommand(props.teamId, props.runId, props.nodeId);
  // 缺陷㉑: a rejected command offer (412 node_not_ready 等) must be visible to
  // the operator. The transport already folds the structured 412 blockers
  // (title + detail) into the error message, so surfacing `commandError`
  // verbatim keeps the actionable text. The last offer is kept so the surface
  // can offer a real retry instead of a dead error line.
  const [lastOffer, setLastOffer] = useState<CommandOffer | null>(null);
  const handoffs = useQuery({
    queryKey: queryKeys.researchWorkflowHandoffs(props.runId, props.teamId),
    queryFn: () => fetchResearchWorkflowHandoffs(props.runId, { teamId: props.teamId }),
    enabled: Boolean(props.runId),
  });
  const submit = async (offer: CommandOffer) => {
    setLastOffer(offer);
    try {
      await command.submit(offer);
    } finally {
      await run.refresh();
      detail.retry();
    }
  };
  const error = run.error || (detail.state.kind === "error" ? detail.state.message : null);
  if (error) return <VStateSurface tone="error" title={error}>
    <VButton onClick={() => { void run.refresh(); detail.retry(); }}>
      {props.lang === "zh" ? "重新加载知识节点" : "Reload knowledge node"}
    </VButton>
  </VStateSurface>;
  if (detail.state.kind !== "ready") return <VStateSurface tone="loading"
    title={props.lang === "zh" ? "加载知识节点" : "Loading knowledge node"} />;
  const commandErrorActions = <>
    {lastOffer ? (
      <VButton
        variant="secondary"
        density="compact"
        isPending={command.busy}
        onClick={() => { void submit(lastOffer); }}
      >
        {props.lang === "zh" ? "重试命令" : "Retry command"}
      </VButton>
    ) : null}
    <VButton variant="ghost" density="compact" onClick={command.clearCommandError}>
      {props.lang === "zh" ? "清除" : "Dismiss"}
    </VButton>
  </>;
  return <>
    {command.commandError ? (
      <VErrorSummary
        data-testid="knowledge-child-command-error"
        label={props.lang === "zh" ? "命令提交失败" : "Command failed"}
        summary={command.commandError}
        actions={commandErrorActions}
      />
    ) : null}
    <ResearchProcessNodeInspector
      teamId={props.teamId}
      nodeId={props.nodeId}
      adapter={getNodeAdapter(props.nodeId)}
      detail={detail.state.detail}
      effectiveBindings={null}
      budget={null}
      handoffs={handoffsForNode(handoffs.data?.handoffs ?? [], props.nodeId)}
      handoffPending={Boolean(run.run?.humanTasks?.some((task) => task.nodeId === props.nodeId && task.status === "pending"))}
      busy={command.busy || run.busy}
      onOffer={submit}
    />
  </>;
}

/** Read surfaces retain the selected child run; no parent-run commands. */
export function KnowledgeChildReadPanel(props: {
  teamId: string;
  runId: string;
  nodeId: string;
  panel: "evidence" | "timeline";
}) {
  const { lang } = useShellI18n();
  // 缺陷⑰: the evidence_graph_incomplete waiver lives next to the read-only
  // evidence graph. ``props.runId`` is the knowledge sideflow CHILD workflow
  // run id (threaded from the run-level invocation badges); the waive endpoint
  // resolves the candidate-graph authority from that run's frozen input
  // snapshot, so it must never be replaced by the formal URL run id. The
  // team-scoped latest candidate_graph record is the same record this child
  // run scopes to; the waive call re-resolves the scoped authority server-side.
  const candidateGraph = useQuery({
    queryKey: queryKeys.teamWorkflowCandidateGraph(props.teamId || "none"),
    queryFn: ({ signal }) => fetchTeamWorkflowCandidates<TeamWorkflowCandidateListPayload>(
      props.teamId,
      { candidateType: "candidate_graph", limit: 20, includeStore: false, signal },
    ),
    enabled: Boolean(props.teamId && props.runId),
  });
  const candidateGraphPayload = workflowCandidateGraphFromCandidate(
    latestWorkflowCandidate(candidateGraph.data?.candidates ?? []),
  );
  return props.panel === "evidence"
    ? <>
        <EvidenceGraphView teamId={props.teamId} runId={props.runId} />
        <MissingLinkWaiverSection
          lang={lang}
          teamId={props.teamId}
          childWorkflowRunId={props.runId}
          graph={candidateGraphPayload}
          refetchGraph={() => candidateGraph.refetch()}
        />
      </>
    : <KnowledgeChildTimeline {...props} />;
}

function KnowledgeChildTimeline(props: { teamId: string; runId: string; nodeId: string }) {
  const run = useResearchWorkflowRun(props.teamId, props.runId);
  const insights = useResearchWorkflowInsights(props.teamId, props.runId, "timeline");
  if (run.error) return <VStateSurface tone="error" title="知识子流程记录读取失败">
    <VButton onClick={() => void run.refresh()}>重新读取记录</VButton>
  </VStateSurface>;
  if (!run.run) return <VStateSurface tone="loading" title="读取知识子流程记录" />;
  return <ResearchRunTimeline run={run.run} projection={run.projection} insights={insights} selectedNodeId={props.nodeId} />;
}
import { useQuery } from "@tanstack/react-query";
import { fetchResearchWorkflowHandoffs } from "../../../api/researchWorkflow";
import { queryKeys } from "../../../api/queryKeys";
