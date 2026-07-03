import { type ComponentProps, type ReactNode } from "react";

import { AgentWorkspacePanel } from "../components/vui/product/agent-management";
import { AgentBulkConfigPanel } from "./AgentBulkConfigPanel";
import { AgentEmptySelectionPanel } from "./AgentEmptySelectionPanel";
import { AgentReturnBannerPanel } from "./AgentReturnBannerPanel";
import styles from "./AgentsRoute.styles";

type AgentDetailWorkspacePanelProps = {
  createOpen: boolean;
  ariaLabel: string;
  returnBanner: ComponentProps<typeof AgentReturnBannerPanel> | null;
  bulkConfig: ComponentProps<typeof AgentBulkConfigPanel> | null;
  selectedContent: ReactNode;
  emptySelectionTitle: string;
};

export function AgentDetailWorkspacePanel({
  createOpen,
  ariaLabel,
  returnBanner,
  bulkConfig,
  selectedContent,
  emptySelectionTitle,
}: AgentDetailWorkspacePanelProps) {
  const bulkConfigPanel = bulkConfig ? <AgentBulkConfigPanel {...bulkConfig} /> : null;

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
