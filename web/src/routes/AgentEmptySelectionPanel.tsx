import { Bot } from "lucide-react";

import styles from "./AgentsRoute.styles";

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
