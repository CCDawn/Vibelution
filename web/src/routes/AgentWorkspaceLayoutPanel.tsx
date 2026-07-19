import { type ComponentProps } from "react";

import { AgentFilterRail } from "../components/vui/product/agent-management";
import { AgentDetailWorkspacePanel } from "./AgentDetailWorkspacePanel";
import { AgentListWorkspacePanel } from "./AgentListWorkspacePanel";
import styles from "./AgentWorkspaceLayoutPanel.styles";

type AgentWorkspaceLayoutPanelProps = {
  detailWorkspace: ComponentProps<typeof AgentDetailWorkspacePanel>;
  filterRail: ComponentProps<typeof AgentFilterRail>;
  listWorkspace: ComponentProps<typeof AgentListWorkspacePanel>;
};

export function AgentWorkspaceLayoutPanel({
  detailWorkspace,
  filterRail,
  listWorkspace,
}: AgentWorkspaceLayoutPanelProps) {
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
