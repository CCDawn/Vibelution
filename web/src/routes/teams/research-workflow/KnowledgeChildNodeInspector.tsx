import { VButton, VStateSurface } from "../../../components/vui";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import { getNodeAdapter } from "./nodeAdapterModel";
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
  const handoffs = useQuery({
    queryKey: queryKeys.researchWorkflowHandoffs(props.runId, props.teamId),
    queryFn: () => fetchResearchWorkflowHandoffs(props.runId, { teamId: props.teamId }),
    enabled: Boolean(props.runId),
  });
  const submit = async (offer: CommandOffer) => {
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
  return <ResearchProcessNodeInspector
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
  />;
}

/** Read surfaces retain the selected child run; no parent-run commands. */
export function KnowledgeChildReadPanel(props: {
  teamId: string;
  runId: string;
  nodeId: string;
  panel: "evidence" | "timeline";
}) {
  return props.panel === "evidence"
    ? <EvidenceGraphView teamId={props.teamId} runId={props.runId} />
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
