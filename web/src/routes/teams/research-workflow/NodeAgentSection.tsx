import type { EffectiveAgentBinding, ResearchBudgetProjection } from "../../../api/types/researchWorkflow";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import { NodeInspectorOpsSection } from "./NodeInspectorOpsSection";

export function NodeAgentSection(props: {
  teamId: string;
  stageId: string;
  stageLabel: string;
  detail: ResearchWorkflowNodeDetail;
  effectiveBindings: EffectiveAgentBinding[] | null;
  budget: ResearchBudgetProjection | null;
  primaryOffer: CommandOffer | null;
  busy: boolean;
  onOffer: (offer: CommandOffer) => Promise<void>;
}) {
  const agentId = String(props.detail.agentId || "");
  const canOpen = Boolean(
    props.detail.sessionId
    && props.detail.taskId
    && props.detail.turnId
    && props.detail.chatDeepLink
    && !props.detail.sessionAnchorDegraded,
  );
  return (
    <section data-vui="node-agent-section">
      <NodeInspectorOpsSection
        teamId={props.teamId}
        nodeId={props.detail.nodeId}
        stageId={props.stageId}
        stageLabel={props.stageLabel}
        title={props.detail.label}
        agentId={agentId}
        agentName={String(props.detail.displayName || agentId)}
        unbound={!agentId}
        runtimeCurrent={props.detail.runtimeCurrent}
        status={props.detail.status}
        canRebindAgent={false}
        agentSwitchReason="运行快照已锁定，换绑请用操作区命令"
        effectiveBindings={props.effectiveBindings}
        budget={props.budget}
        primaryOffer={props.primaryOffer}
        busy={props.busy}
        onOffer={props.onOffer}
        sessionHref={canOpen ? props.detail.chatDeepLink ?? null : null}
        sessionDisabledReason={
          props.detail.sessionAnchorDegraded ? "会话锚点不完整" : "尚未绑定精确会话"
        }
      />
    </section>
  );
}
