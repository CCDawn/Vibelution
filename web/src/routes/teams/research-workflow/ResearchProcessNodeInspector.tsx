import type { NodeHandoffRecord, ResearchBudgetProjection, EffectiveAgentBinding } from "../../../api/types/researchWorkflow";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";
import { VEmptyState, VSurface } from "../../../components/vui";
import type { NodeAdapterSpec } from "./nodeAdapterModel";
import { NodeAgentSection } from "./NodeAgentSection";
import { NodeCommandSection } from "./NodeCommandSection";
import { NodeHandoffSection } from "./NodeHandoffSection";
import { pickPrimaryCommandOffer, remainingCommandOffers } from "./nodeInspectorOpsModel";
import { researchActorLabel, researchStageLabel } from "./researchNodePresentation";
import styles from "./ResearchProcessNodeInspector.styles";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";

export type ResearchProcessNodeInspectorProps = {
  teamId: string;
  nodeId: string | null;
  adapter: NodeAdapterSpec | null;
  detail: ResearchWorkflowNodeDetail | null;
  effectiveBindings: EffectiveAgentBinding[] | null;
  budget: ResearchBudgetProjection | null;
  handoffs?: NodeHandoffRecord[];
  handoffPending: boolean;
  busy: boolean;
  onOffer: (offer: CommandOffer) => Promise<void>;
};

export function ResearchProcessNodeInspector(props: ResearchProcessNodeInspectorProps) {
  if (!props.adapter || !props.nodeId) {
    return (
      <div className={styles.centered} data-vui="node-inspector-empty">
        <VEmptyState title="选择流程节点" className={styles.empty}>
          在画布上点击任务节点，查看绑定、会话与运行命令。
        </VEmptyState>
      </div>
    );
  }
  if (!props.detail) {
    return (
      <div className={styles.centered}>
        <VEmptyState title="暂无节点运行数据" className={styles.empty} />
      </div>
    );
  }

  const { adapter, detail } = props;
  const primaryOffer = adapter.actorKind === "agent"
    ? pickPrimaryCommandOffer(detail.commandOffers)
    : null;
  const restOffers = adapter.actorKind === "agent"
    ? remainingCommandOffers(detail.commandOffers, primaryOffer)
    : (detail.commandOffers ?? []);

  return (
    <VSurface tone="panel" className={styles.root} data-vui="node-inspector">
      {adapter.actorKind === "agent" ? (
        <NodeAgentSection
          teamId={props.teamId}
          stageId={adapter.stageId}
          stageLabel={researchStageLabel(adapter.stageId)}
          detail={detail}
          effectiveBindings={props.effectiveBindings}
          budget={props.budget}
          primaryOffer={primaryOffer}
          busy={props.busy}
          onOffer={props.onOffer}
        />
      ) : (
        <header>
          <div className={styles.stage}>{researchStageLabel(adapter.stageId)}</div>
          <h3 className={styles.title}>{detail.label || adapter.label}</h3>
          <div className={styles.meta}>{researchActorLabel(adapter.actorKind)}</div>
        </header>
      )}
      <NodeHandoffSection
        handoffs={props.handoffs ?? []}
        pending={props.handoffPending}
        blockedReason={detail.blockedReason || ""}
      />
      <NodeCommandSection
        offers={restOffers}
        busy={props.busy}
        onOffer={props.onOffer}
      />
    </VSurface>
  );
}
