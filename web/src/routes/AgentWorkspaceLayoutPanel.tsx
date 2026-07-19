import { type ComponentProps } from "react";

import { AgentFilterRail } from "../components/vui/product/agent-management";
import { AgentCreatePanel } from "./AgentCreatePanel";
import { AgentDetailWorkspacePanel } from "./AgentDetailWorkspacePanel";
import { AgentListWorkspacePanel } from "./AgentListWorkspacePanel";
import styles from "./AgentWorkspaceLayoutPanel.styles";

type AgentWorkspaceLayoutPanelProps = {
  createOpen: boolean;
  createWorkspace: ComponentProps<typeof AgentCreatePanel>;
  detailWorkspace: ComponentProps<typeof AgentDetailWorkspacePanel>;
  filterRail: ComponentProps<typeof AgentFilterRail>;
  listWorkspace: ComponentProps<typeof AgentListWorkspacePanel>;
};

export function AgentWorkspaceLayoutPanel({
  createOpen,
  createWorkspace,
  detailWorkspace,
  filterRail,
  listWorkspace,
}: AgentWorkspaceLayoutPanelProps) {
  if (createOpen) {
    return (
      <div className={`${styles.workspace} ${styles.workspaceCreating}`}>
        <section className={styles.createWorkspace} aria-label={createWorkspace.copy.createAgentTitle}>
          <AgentCreatePanel {...createWorkspace} />
        </section>
      </div>
    );
  }

  return (
    <div className={styles.workspace}>
      <div className={styles.directory}>
        <AgentFilterRail {...filterRail} />
        <AgentListWorkspacePanel {...listWorkspace} />
      </div>
      <AgentDetailWorkspacePanel {...detailWorkspace} />
    </div>
  );
}
