import type { ResearchWorkflowNodeDetail } from "../../../api/types/researchWorkflow";
import styles from "./NodeExecutionSection.styles";

export function NodeExecutionSection({ detail }: { detail: ResearchWorkflowNodeDetail }) {
  const lease = detail.taskLease;
  const quality = detail.qualityGateEvaluation;
  if (!detail.executionEnvelope && !lease && !quality && !detail.artifactManifests.length) return null;
  return (
    <section className={styles.root} data-vui="node-execution-section">
      <h4 className={styles.title}>运行治理</h4>
      <dl className={styles.details}>
        <dt className={styles.label}>Lease</dt>
        <dd className={styles.value}>{String(lease?.status || "—")} · {String(lease?.leaseOwner || "—")}</dd>
        <dt className={styles.label}>质量门</dt>
        <dd className={styles.value}>{String(quality?.status || "—")}</dd>
        <dt className={styles.label}>Artifact</dt>
        <dd className={styles.value}>{detail.artifactManifests.length}</dd>
        <dt className={styles.label}>复用命中</dt>
        <dd className={styles.value}>{detail.artifactReuseCount}</dd>
      </dl>
    </section>
  );
}
