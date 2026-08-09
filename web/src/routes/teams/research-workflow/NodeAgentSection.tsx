import type { ResearchWorkflowNodeDetail } from "../../../api/types/researchWorkflow";
import styles from "./NodeAgentSection.styles";

const SOURCE_LABELS: Record<string, string> = {
  workflow_default: "团队/工作流默认",
  stage_override: "阶段覆盖",
  node_override: "节点覆盖",
  rebind: "运行内换绑",
  unbound: "未绑定",
};

export function NodeAgentSection({ detail }: { detail: ResearchWorkflowNodeDetail }) {
  const snapshot = detail.bindingSnapshot ?? {};
  const source = String(snapshot.resolvedFrom || "");
  return (
    <section data-vui="node-agent-section">
      <h4 className={styles.title}>Agent</h4>
      <dl className={styles.details}>
        <dt className={styles.label}>角色</dt>
        <dd className={styles.value}>{detail.primaryRoleKey}</dd>
        <dt className={styles.label}>名称</dt>
        <dd className={styles.valueName} title={String(snapshot.displayName || snapshot.agentId || "")}>
          {String(snapshot.displayName || snapshot.agentId || "未绑定")}
        </dd>
        <dt className={styles.label}>Agent ID</dt>
        <dd className={styles.valueBreak}>{String(snapshot.agentId || "—")}</dd>
        <dt className={styles.label}>绑定来源</dt>
        <dd className={styles.value}>{SOURCE_LABELS[source] || source || "—"}</dd>
      </dl>
    </section>
  );
}
