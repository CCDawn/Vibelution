import { type ReactNode } from "react";

import { AgentManagementNav, type AgentManagementSection } from "./AgentManagementNav";
import styles from "./AgentManagementModuleBar.styles";

type AgentManagementModuleBarProps = {
  active: AgentManagementSection;
  actions?: ReactNode;
};

/**
 * Agents module strip: section nav + optional actions.
 * Intentionally **not** VPanelHeader — this is navigation chrome (tabs/links), not a panel title band.
 * Landmark stays a nav region with product data attribute for layout contracts.
 */
export function AgentManagementModuleBar({
  active,
  actions,
}: AgentManagementModuleBarProps) {
  return (
    <div
      className={styles.moduleBar}
      data-agent-management="module-bar"
      data-vui="agent-management-module-bar"
      role="navigation"
      aria-label="Agent management modules"
    >
      <AgentManagementNav active={active} className={styles.managementNav} />
      {actions ? <div className={styles.moduleActions}>{actions}</div> : null}
    </div>
  );
}
