import type { NodeHandoffRecord } from "../../../api/types/researchWorkflow";
import { VErrorSummary } from "../../../components/vui";
import { presentResearchWorkflowError } from "../researchWorkflowErrorModel";
import styles from "./NodeHandoffSection.styles";
import { getNodeAdapter } from "./nodeAdapterModel";

const HANDOFF_STATUS_LABELS: Record<string, string> = {
  accepted: "已接收", ready: "待交接", waiting_human: "等待确认", failed: "交接失败",
  offered: "等待接收", rejected: "未接收", superseded: "已替代", pending: "等待确认", cancelled: "已取消",
};

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
  const presented = presentResearchWorkflowError(reason);
  const body = isZh ? presented.bodyZh : presented.bodyEn;
  return body === reason
    ? (isZh ? "此步骤未能完成。请展开诊断查看原因，再按节点提供的操作处理。" : "This step could not finish. Review diagnostics before using the offered recovery action.")
    : body;
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
      <h4 className={styles.title}>{isZh ? "产出与缺口" : "Outputs and gaps"}</h4>
      <dl className={styles.details}>
        <dt className={styles.label}>{isZh ? "状态" : "Status"}</dt>
        <dd className={styles.value}>{props.pending ? (isZh ? "等待人工" : "Waiting for human") : props.blockedReason ? (isZh ? "已阻塞" : "Blocked") : props.handoffs.length ? (isZh ? "已有交接记录" : "Handoffs recorded") : (isZh ? "暂无交接" : "No handoff yet")}</dd>
      </dl>
      {props.blockedReason ? <>
        <p>{blockedReasonLabel(props.blockedReason, isZh)}</p>
        <VErrorSummary label={isZh ? "需要处理" : "Needs attention"} summary={isZh ? "此步骤尚未完成" : "This step has not completed"} details={props.blockedReason} openLabel={isZh ? "诊断" : "Diagnostics"} closeLabel={isZh ? "收起" : "Hide"} defaultOpen={false} />
      </> : null}
      {props.handoffs.map((handoff) => (
        <article className={styles.record} key={handoff.handoffId}>
          <strong>{getNodeAdapter(handoff.fromNodeId)?.label || (isZh ? "前序步骤" : "Previous step")} → {getNodeAdapter(handoff.toNodeId)?.label || (isZh ? "后续步骤" : "Next step")}</strong>
          <span>{isZh ? HANDOFF_STATUS_LABELS[handoff.status] || "状态待确认" : handoff.status} · {(handoff.outputArtifactRefs ?? []).length} {isZh ? "项交接产物" : "handoff artifacts"}</span>
          <VErrorSummary tone="info" label={isZh ? "交接记录" : "Handoff record"}
            summary={isZh ? "查看产物引用与交接状态" : "View artifact references and handoff status"}
            openLabel={isZh ? "详情" : "Details"} closeLabel={isZh ? "收起" : "Hide"}
            details={JSON.stringify({ status: handoff.status, outputArtifactRefs: handoff.outputArtifactRefs, supersedesHandoffId: handoff.supersedesHandoffId }, null, 2)} defaultOpen={false} />
        </article>
      ))}
    </section>
  );
}
