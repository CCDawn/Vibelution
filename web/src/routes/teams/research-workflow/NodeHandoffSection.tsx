import type { NodeHandoffRecord } from "../../../api/types/researchWorkflow";
import styles from "./NodeHandoffSection.styles";

export function NodeHandoffSection(props: {
  handoffs: NodeHandoffRecord[];
  pending: boolean;
  blockedReason: string;
}) {
  if (!props.pending && !props.blockedReason && !props.handoffs.length) return null;
  return (
    <section className={styles.root} data-vui="node-handoff-section">
      <h4 className={styles.title}>交接</h4>
      <dl className={styles.details}>
        <dt className={styles.label}>状态</dt>
        <dd className={styles.value}>{props.pending ? "等待人工" : "已处理"}</dd>
        {props.blockedReason ? <><dt className={styles.label}>阻塞</dt><dd className={styles.valueBreak}>{props.blockedReason}</dd></> : null}
      </dl>
      {props.handoffs.map((handoff) => (
        <article className={styles.record} key={handoff.handoffId}>
          <strong>{handoff.fromNodeId} → {handoff.toNodeId}</strong>
          <span>{handoff.status} · {handoff.outputArtifactRefs.length} 项产物</span>
          {handoff.supersedesHandoffId ? <span>接替 {handoff.supersedesHandoffId}</span> : null}
        </article>
      ))}
    </section>
  );
}
