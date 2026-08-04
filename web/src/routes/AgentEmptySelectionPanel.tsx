import { Bot } from "lucide-react";

import { VStateSurface } from "../components/vui";
import styles from "./AgentEmptySelectionPanel.styles";

type AgentEmptySelectionPanelProps = {
  title: string;
};

export function AgentEmptySelectionPanel({ title }: AgentEmptySelectionPanelProps) {
  return (
    <section className={styles.emptyState}>
      <VStateSurface
        fill
        tone="empty"
        title={title}
        icon={<Bot size={18} />}
      />
    </section>
  );
}
