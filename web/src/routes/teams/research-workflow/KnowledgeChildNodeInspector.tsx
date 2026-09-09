import { useEffect, useState } from "react";

import { VButton, VErrorSummary, VStateSurface } from "../../../components/vui";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import { fetchEvidenceGraphMissingLinks } from "../../../api/researchWorkflow";
import { useShellI18n } from "../../../i18n/useShellI18n";
import { getNodeAdapter } from "./nodeAdapterModel";
import {
  commandOfferUnavailableReason,
  isUnknownOutcomeCommandError,
  resolveCurrentCommandOffer,
} from "./nodeInspectorOpsModel";
import { MissingLinkWaiverSection } from "./MissingLinkWaiverSection";
import { ResearchProcessNodeInspector } from "./ResearchProcessNodeInspector";
import { useNodeDetailState } from "./useNodeDetailState";
import { useResearchWorkflowCommand } from "./useResearchWorkflowCommand";
import { useResearchWorkflowRun } from "./useResearchWorkflowRun";
import { EvidenceGraphView } from "./EvidenceGraphView";
import { ResearchRunTimeline } from "./ResearchRunTimeline";
import { useResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import { handoffsForNode } from "./researchNodeHandoffModel";

/** A failed submit kept for the error-surface retry (缺陷㉑ + A06).
 * ``outcomeUnknown`` splits the two retry classes: a transport-level failure
 * (network drop / lost response) may replay the SAME offer with its original
 * idempotency key, while a definite server rejection must re-resolve a fresh
 * offer before retrying. */
type FailedCommand = { offer: CommandOffer; outcomeUnknown: boolean };

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
  // verbatim keeps the actionable text. A06: the failed command is kept only
  // as an identity anchor — the retry never resubmits its stale signature.
  const [failedCommand, setFailedCommand] = useState<FailedCommand | null>(null);
  useEffect(() => {
    // Switching node/run invalidates the failed target: never keep an
    // executable old offer across surfaces.
    setFailedCommand(null);
  }, [props.runId, props.nodeId]);
  const handoffs = useQuery({
    queryKey: queryKeys.researchWorkflowHandoffs(props.runId, props.teamId),
    queryFn: () => fetchResearchWorkflowHandoffs(props.runId, { teamId: props.teamId }),
    enabled: Boolean(props.runId),
  });
  const submit = async (offer: CommandOffer) => {
    try {
      await command.submit(offer);
      setFailedCommand(null);
    } catch (error) {
      setFailedCommand({ offer, outcomeUnknown: isUnknownOutcomeCommandError(error) });
      throw error;
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
  // A06 retry resolution: by the time the error surface is interactive the
  // `finally` refetch has landed, so `detail.state.detail.commandOffers` is
  // the freshest server-signed snapshot for this exact node.
  const isZh = props.lang === "zh";
  const currentOffers = detail.state.detail.commandOffers ?? [];
  const reResolvedOffer = failedCommand && !failedCommand.outcomeUnknown
    ? resolveCurrentCommandOffer(currentOffers, failedCommand.offer)
    : null;
  const retryUnavailableReason = failedCommand && !failedCommand.outcomeUnknown
    ? (reResolvedOffer
      ? commandOfferUnavailableReason(reResolvedOffer, isZh, detail.state.detail.runVersion)
      : (isZh
        ? "该命令在当前运行状态下已不再提供，请刷新或改用节点上的其他操作。"
        : "This command is no longer offered for the current run state; refresh or use another node action."))
    : "";
  const commandErrorActions = <>
    {failedCommand?.outcomeUnknown ? (
      // Result unknown: the request may have landed server-side, so replay
      // the SAME offer (same idempotency key) instead of a new execution.
      <VButton
        variant="secondary"
        density="compact"
        isPending={command.busy}
        onClick={() => { void submit(failedCommand.offer).catch(() => undefined); }}
      >
        {isZh ? "重试命令" : "Retry command"}
      </VButton>
    ) : failedCommand && reResolvedOffer?.available ? (
      // Definite rejection: resubmit only a freshly resolved offer — new
      // expectedRunVersion and new server-signed idempotency key.
      <VButton
        variant="secondary"
        density="compact"
        isPending={command.busy}
        onClick={() => { void submit(reResolvedOffer).catch(() => undefined); }}
      >
        {isZh ? "重试命令" : "Retry command"}
      </VButton>
    ) : failedCommand && reResolvedOffer ? (
      // The command still exists but is no longer actionable: disabled with
      // the fresh reason instead of a guaranteed-failing click.
      <VButton
        variant="secondary"
        density="compact"
        isPending={command.busy}
        isDisabled
        title={retryUnavailableReason}
      >
        {isZh ? "重试命令" : "Retry command"}
      </VButton>
    ) : null}
    <VButton variant="ghost" density="compact" onClick={command.clearCommandError}>
      {isZh ? "清除" : "Dismiss"}
    </VButton>
  </>;
  return <>
    {command.commandError ? (
      <VErrorSummary
        data-testid="knowledge-child-command-error"
        label={isZh ? "命令提交失败" : "Command failed"}
        summary={command.commandError}
        details={retryUnavailableReason || undefined}
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
  // snapshot, so it must never be replaced by the formal URL run id.
  // A05: the gap list reads the run-scoped missing-link projection — the
  // server resolves the same snapshot authority the waive write mutates and
  // the readiness gate counts. The previous team-latest ``candidate_graph``
  // query could render another run's gaps (A05); the run id is part of the
  // queryKey so switching child runs never leaks stale gaps.
  const missingLinks = useQuery({
    queryKey: queryKeys.researchWorkflowEvidenceMissingLinks(props.runId, props.teamId || "none"),
    queryFn: ({ signal }) => fetchEvidenceGraphMissingLinks({
      runId: props.runId,
      teamId: props.teamId,
      signal,
    }),
    enabled: Boolean(props.teamId && props.runId),
  });
  return props.panel === "evidence"
    ? <>
        <EvidenceGraphView teamId={props.teamId} runId={props.runId} />
        <MissingLinkWaiverSection
          lang={lang}
          teamId={props.teamId}
          childWorkflowRunId={props.runId}
          missingLinks={missingLinks.data?.missingLinks}
          refetchGraph={() => missingLinks.refetch()}
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
