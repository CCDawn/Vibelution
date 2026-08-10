import type { ResearchWorkflowNodeDetail } from "../../../api/types/researchWorkflow";
import { VRouteLinkButton } from "../../../components/vui";
import styles from "./NodeSessionSection.styles";

export function NodeSessionSection({ detail }: { detail: ResearchWorkflowNodeDetail }) {
  const binding = detail.sessionBinding;
  const canOpen = Boolean(binding?.sessionId && detail.chatDeepLink && !detail.sessionAnchorDegraded);
  return (
    <section data-vui="node-session-section">
      <h4 className={styles.title}>会话</h4>
      {binding ? (
        <dl className={styles.details} data-vui="session-anchor">
          <dt className={styles.label}>会话</dt><dd className={styles.valueBreak}>{binding.sessionId}</dd>
          <dt className={styles.label}>任务</dt><dd className={styles.valueBreak}>{binding.taskId}</dd>
          <dt className={styles.label}>轮次</dt><dd className={styles.valueBreak}>{binding.turnId}</dd>
        </dl>
      ) : (
        <div className={styles.empty}>未绑定会话</div>
      )}
      {canOpen ? (
        <VRouteLinkButton className={styles.action} to={detail.chatDeepLink!} variant="ghost">打开精确会话</VRouteLinkButton>
      ) : null}
    </section>
  );
}
