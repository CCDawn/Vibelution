import type { ResearchWorkflowNodeDetail } from "../../../api/types/researchWorkflow";
import { VEmptyState, VSurface } from "../../../components/vui";
import type { NodeAdapterSpec } from "./nodeAdapterModel";
import { NodeAgentSection } from "./NodeAgentSection";
import { NodeArtifactSection } from "./NodeArtifactSection";
import { NodeCommandSection } from "./NodeCommandSection";
import { NodeHandoffSection } from "./NodeHandoffSection";
import { NodeSessionSection } from "./NodeSessionSection";
import styles from "./ResearchProcessNodeInspector.styles";

export type ResearchProcessNodeInspectorProps = {
  nodeId: string | null;
  adapter: NodeAdapterSpec | null;
  detail: ResearchWorkflowNodeDetail | null;
  handoffPending: boolean;
  busy: boolean;
  onCommand: (command: string) => void;
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
  return (
    <VSurface tone="panel" className={styles.root} data-vui="node-inspector">
      <header>
        <div className={styles.stage}>{adapter.stageId.replace(/_/g, " ")}</div>
        <h3 className={styles.title}>{detail.label || adapter.label}</h3>
        <div className={styles.meta}>
          {adapter.actorKind}
          {detail.runtimeCurrent ? " · 运行当前" : ""}
          {detail.nodeAttempt ? ` · 第 ${detail.nodeAttempt} 次尝试` : ""}
        </div>
      </header>
      {adapter.actorKind === "agent" ? <NodeAgentSection detail={detail} /> : null}
      {adapter.actorKind === "agent" ? <NodeSessionSection detail={detail} /> : null}
      <NodeHandoffSection pending={props.handoffPending} blockedReason={detail.blockedReason} />
      <NodeArtifactSection artifacts={detail.artifacts} />
      <NodeCommandSection capabilities={detail.commands} busy={props.busy} onCommand={props.onCommand} />
    </VSurface>
  );
}
