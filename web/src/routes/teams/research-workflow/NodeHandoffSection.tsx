import type { NodeHandoffRecord } from "../../../api/types/researchWorkflow";
import styles from "./NodeHandoffSection.styles";

function blockedReasonLabel(reason: string, isZh: boolean): string {
  if (reason === "budget_exceeded") {
    return isZh
      ? "本阶段预算已用完，请提高预算后创建新运行。"
      : "Stage budget exhausted; raise the budget and create a new run.";
  }
  if (reason === "retry_owns_recovery") {
    return isZh ? "当前节点已阻塞，请使用重试。" : "This node is blocked; use retry.";
  }
  if (reason === "checkpoint_node_mismatch") {
    return isZh
      ? "检查点仍停留在前驱节点，无法从当前节点恢复。"
      : "The checkpoint still points at a previous node; cannot resume from this node.";
  }
  return reason;
}

export function NodeHandoffSection(props: {
  handoffs: NodeHandoffRecord[];
  pending: boolean;
  blockedReason: string;
  lang?: "zh" | "en";
}) {
  const isZh = props.lang !== "en";
  if (!props.pending && !props.blockedReason && !props.handoffs.length) return null;
  return (
    <section className={styles.root} data-vui="node-handoff-section">
      <h4 className={styles.title}>{isZh ? "交接" : "Handoffs"}</h4>
      <dl className={styles.details}>
        <dt className={styles.label}>{isZh ? "状态" : "Status"}</dt>
        <dd className={styles.value}>{props.pending ? (isZh ? "等待人工" : "Waiting for human") : (isZh ? "已处理" : "Handled")}</dd>
        {props.blockedReason ? <><dt className={styles.label}>{isZh ? "阻塞" : "Blocked"}</dt><dd className={styles.valueBreak}>{blockedReasonLabel(props.blockedReason, isZh)}</dd></> : null}
      </dl>
      {props.handoffs.map((handoff) => (
        <article className={styles.record} key={handoff.handoffId}>
          <strong>{handoff.fromNodeId} → {handoff.toNodeId}</strong>
          <span>{handoff.status} · {(handoff.outputArtifactRefs ?? []).length} {isZh ? "项产物" : "artifacts"}</span>
          {handoff.supersedesHandoffId ? <span>{isZh ? `接替 ${handoff.supersedesHandoffId}` : `Supersedes ${handoff.supersedesHandoffId}`}</span> : null}
        </article>
      ))}
    </section>
  );
}
