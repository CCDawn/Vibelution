import { useState } from "react";
import { AgentMessageCenter, AgentMessageDetail, AgentMessageSidebar, type AgentMessageRecord } from "../../../components/agent-messages";
import { VuiPreviewCard } from "../VuiPreviewCard";
import styles from "./AgentMessageCatalog.styles";

const records: AgentMessageRecord[] = [
  { id: "preview-request", type: "request", title: "请核对本次交付", body: "请检查变更与验收结果，并回复发现的问题。", createdAt: "2026-11-01T12:00:00Z",
    sender: { agentId: "assistant", name: "个人助理" }, recipients: [{ agentId: "reviewer", name: "审查助手", delivery: "delivered", handling: "replied" }] },
  { id: "preview-reply", type: "reply", replyToId: "preview-request", title: "已完成核对", body: "变更与验收结果一致。", createdAt: "2026-11-01T12:01:00Z",
    sender: { agentId: "reviewer", name: "审查助手" }, recipients: [{ agentId: "assistant", name: "个人助理", delivery: "delivered", handling: "received" }] },
  { id: "preview-notification", type: "notification", title: "检查结果已归档", body: "请按需查看归档结果，无需回复。", createdAt: "2026-11-01T12:02:00Z",
    sender: { agentId: "assistant", name: "个人助理" }, recipients: [
      { agentId: "tester", name: "测试助手", delivery: "delivered", handling: "queued" },
      { agentId: "researcher", name: "调研助手", delivery: "delivered", handling: "wake_failed", error: "示例：目标会话尚未启动" },
    ] },
];

/** Pure presentation examples: no queries, delivery actions or product data. */
export function AgentMessageCatalog() {
  const [selectedId, setSelectedId] = useState<string | null>("preview-request");
  const [scope, setScope] = useState<"current" | "all">("all");
  const visible = scope === "current" ? records.filter((record) => record.type !== "notification") : records;
  const common = { records: visible, selectedId, onSelect: setSelectedId, lang: "zh" as const };
  return <>
    <VuiPreviewCard name="AgentMessageSidebar" className={styles.fullCard}>
      <div className={styles.sidebar}><AgentMessageSidebar {...common} scope={scope} onScopeChange={setScope} /></div>
    </VuiPreviewCard>
    <VuiPreviewCard name="AgentMessageDetail" className={styles.fullCard}>
      <div className={styles.detail}><AgentMessageDetail {...common} /></div>
    </VuiPreviewCard>
    <VuiPreviewCard name="AgentMessageCenter" className={styles.fullCard}>
      <div className={styles.center}><AgentMessageCenter {...common} scope={scope} onScopeChange={setScope} /></div>
    </VuiPreviewCard>
  </>;
}
