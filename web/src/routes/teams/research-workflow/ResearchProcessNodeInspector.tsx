import type { NodeHandoffRecord } from "../../../api/types/researchWorkflow";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";
import { VEmptyState, VSurface } from "../../../components/vui";
import type { NodeAdapterSpec } from "./nodeAdapterModel";
import { NodeAgentSection } from "./NodeAgentSection";
import { NodeCommandSection } from "./NodeCommandSection";
import { NodeHandoffSection } from "./NodeHandoffSection";
import { NodeSessionSection } from "./NodeSessionSection";
import { researchActorLabel, researchStageLabel } from "./researchNodePresentation";
import styles from "./ResearchProcessNodeInspector.styles";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";

export type ResearchProcessNodeInspectorProps = {
  nodeId: string | null;
  adapter: NodeAdapterSpec | null;
  detail: ResearchWorkflowNodeDetail | null;
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
  const attempt = detail.nodeAttempt || detail.latestAttempt?.attempt || 0;
  return (
    <VSurface tone="panel" className={styles.root} data-vui="node-inspector">
      <header>
        <div className={styles.stage}>{researchStageLabel(adapter.stageId)}</div>
        <h3 className={styles.title}>{detail.label || adapter.label}</h3>
        <div className={styles.meta}>
          {researchActorLabel(adapter.actorKind)}
          {detail.runtimeCurrent ? " · 运行当前" : ""}
          {attempt ? ` · 第 ${attempt} 次尝试` : ""}
        </div>
      </header>
      {adapter.actorKind === "agent" ? <NodeAgentSection detail={detail} /> : null}
      {adapter.actorKind === "agent" ? <NodeSessionSection detail={detail} /> : null}
      <NodeHandoffSection
        handoffs={props.handoffs ?? []}
        pending={props.handoffPending}
        blockedReason={detail.blockedReason || ""}
      />
      <NodeCommandSection
        offers={detail.commandOffers ?? []}
        busy={props.busy}
        onOffer={props.onOffer}
      />
    </VSurface>
  );
}
