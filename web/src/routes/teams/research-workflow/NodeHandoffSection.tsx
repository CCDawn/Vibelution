import type { NodeHandoffRecord } from "../../../api/types/researchWorkflow";
import styles from "./NodeHandoffSection.styles";

function blockedReasonLabel(reason: string): string {
  if (reason === "budget_exceeded") {
    return "本阶段预算已用完，请提高预算后创建新运行。";
  }
  return reason;
}

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
        {props.blockedReason ? <><dt className={styles.label}>阻塞</dt><dd className={styles.valueBreak}>{blockedReasonLabel(props.blockedReason)}</dd></> : null}
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
