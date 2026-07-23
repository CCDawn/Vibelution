import { type ReactNode } from "react";

import { AgentManagementNav, type AgentManagementSection } from "./AgentManagementNav";
import styles from "./AgentManagementModuleBar.styles";

type AgentManagementModuleBarProps = {
  active: AgentManagementSection;
  actions?: ReactNode;
};

export function AgentManagementModuleBar({
  active,
  actions,
}: AgentManagementModuleBarProps) {
  return (
    <header className={styles.moduleBar} data-agent-management="module-bar">
      <AgentManagementNav active={active} className={styles.managementNav} />
      {actions ? <div className={styles.moduleActions}>{actions}</div> : null}
    </header>
  );
}
