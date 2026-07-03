import { type ComponentProps, type ReactNode } from "react";

import { AgentWorkspacePanel } from "../components/vui/product/agent-management";
import { AgentEmptySelectionPanel } from "./AgentEmptySelectionPanel";
import { AgentReturnBannerPanel } from "./AgentReturnBannerPanel";
import styles from "./AgentsRoute.styles";

type AgentDetailWorkspacePanelProps = {
  createOpen: boolean;
  ariaLabel: string;
  returnBanner: ComponentProps<typeof AgentReturnBannerPanel> | null;
  bulkConfigPanel: ReactNode;
  selectedContent: ReactNode;
  emptySelectionTitle: string;
};

export function AgentDetailWorkspacePanel({
  createOpen,
  ariaLabel,
  returnBanner,
  bulkConfigPanel,
  selectedContent,
  emptySelectionTitle,
}: AgentDetailWorkspacePanelProps) {
  return (
    <AgentWorkspacePanel
      as="aside"
      ariaLabel={ariaLabel}
      className={createOpen ? `${styles.detailPanel} ${styles.detailPanelCreating}` : styles.detailPanel}
    >
      {returnBanner ? <AgentReturnBannerPanel {...returnBanner} /> : null}
      {bulkConfigPanel ?? selectedContent ?? <AgentEmptySelectionPanel title={emptySelectionTitle} />}
    </AgentWorkspacePanel>
  );
}
