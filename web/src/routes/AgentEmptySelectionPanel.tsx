import { Bot } from "lucide-react";

import styles from "./AgentEmptySelectionPanel.styles";

type AgentEmptySelectionPanelProps = {
  title: string;
};

export function AgentEmptySelectionPanel({ title }: AgentEmptySelectionPanelProps) {
  return (
    <section className={styles.emptyState}>
      <Bot size={24} />
      <strong>{title}</strong>
    </section>
  );
}
