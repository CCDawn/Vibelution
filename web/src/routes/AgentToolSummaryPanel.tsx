import { Wrench } from "lucide-react";

import { VButton, VContextualHint } from "../components/vui";
import styles from "./AgentToolSummaryPanel.styles";

export type AgentToolSummaryPanelCopy = {
  toolPolicyTitle: string;
  allowedTools: string;
  preferredTools: string;
  blockedTools: string;
  toolCategoryCount: string;
};

type AgentToolSummaryPanelProps = {
  copy: AgentToolSummaryPanelCopy;
  lang: "zh" | "en";
  policyId: string;
  allowedCount: number;
  preferredCount: number;
  blockedCount: number;
  toolCategoryCount: number;
  onConfigure: () => void;
};

export function AgentToolSummaryPanel({
  copy,
  lang,
  policyId,
  allowedCount,
  preferredCount,
  blockedCount,
  toolCategoryCount,
  onConfigure,
}: AgentToolSummaryPanelProps) {
  const title = lang === "zh"
    ? "工具能力已迁移到 Agent 管理的工具页集中配置；这里保留当前 Agent 的工具摘要和入口。"
    : "Tool permissions are configured in the Agent Tools page. This panel keeps only the current Agent summary and entry point.";
  const actionLabel = lang === "zh" ? "配置工具能力" : "Configure tools";

  return (
    <section className={styles.configEditor}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.toolPolicyTitle}</p>
          <div className={styles.titleRow}>
            <h3>{policyId || "-"}</h3>
            <VContextualHint
              label={lang === "zh" ? "工具能力摘要说明" : "Tool capability summary details"}
              content={title}
              width="wide"
            />
          </div>
        </div>
        <Wrench size={16} />
      </div>
      <div className={styles.policySummaryGrid}>
        <span>{copy.allowedTools}: <strong>{allowedCount}</strong></span>
        <span>{copy.preferredTools}: <strong>{preferredCount}</strong></span>
        <span>{copy.blockedTools}: <strong>{blockedCount}</strong></span>
        <span>{copy.toolCategoryCount}: <strong>{toolCategoryCount}</strong></span>
      </div>
      <div className={styles.editorActions}>
        <VButton type="button" variant="primary" icon={<Wrench size={15} />} onPress={onConfigure}>
          {actionLabel}
        </VButton>
      </div>
    </section>
  );
}
