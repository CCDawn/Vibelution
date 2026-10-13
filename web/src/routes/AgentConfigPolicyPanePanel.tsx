import { type ComponentProps, type ReactNode } from "react";

import { AgentMemoryPolicyPanel } from "./AgentMemoryPolicyPanel";
import { AgentToolSummaryPanel } from "./AgentToolSummaryPanel";
import styles from "./AgentConfigPolicyPanePanel.styles";

type AgentConfigPolicyPanePanelProps = {
  toolSummary: ComponentProps<typeof AgentToolSummaryPanel>;
  memoryPolicy: ComponentProps<typeof AgentMemoryPolicyPanel>;
  toolGovernance?: ReactNode;
};

export function AgentConfigPolicyPanePanel({
  toolSummary,
  memoryPolicy,
  toolGovernance,
}: AgentConfigPolicyPanePanelProps) {
  return (
    <div className={styles.pane}>
      <details className={styles.tools}><summary className={styles.summary}>{toolSummary.lang === "zh" ? "工具" : "Tools"}</summary><div className={styles.body}><AgentToolSummaryPanel {...toolSummary} />{toolGovernance}</div></details>
      <AgentMemoryPolicyPanel {...memoryPolicy} />
    </div>
  );
}
