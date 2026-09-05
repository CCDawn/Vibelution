import { VButton, VStateSurface } from "../../../components/vui";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import { getNodeAdapter } from "./nodeAdapterModel";
import { ResearchProcessNodeInspector } from "./ResearchProcessNodeInspector";
import { useNodeDetailState } from "./useNodeDetailState";
import { useResearchWorkflowCommand } from "./useResearchWorkflowCommand";
import { useResearchWorkflowRun } from "./useResearchWorkflowRun";

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
    enabled: props.nodeId === "knowledge_handoff",
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
    handoffs={handoffs.data?.handoffs ?? []}
    handoffPending={Boolean(run.run?.humanTasks?.some((task) => task.nodeId === props.nodeId && task.status === "pending"))}
    busy={command.busy || run.busy}
    onOffer={submit}
  />;
}
import { useQuery } from "@tanstack/react-query";
import { fetchResearchWorkflowHandoffs } from "../../../api/researchWorkflow";
import { queryKeys } from "../../../api/queryKeys";
