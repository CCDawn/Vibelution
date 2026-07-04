import { Plus } from "lucide-react";
import { type ComponentProps } from "react";

import { AgentWorkspacePanel } from "../components/vui/product/agent-management";
import { VButton, VChip, VPanelHeader } from "../components/vui";
import { AgentBulkOperationsPanel } from "./AgentBulkOperationsPanel";
import { AgentCreatePanel } from "./AgentCreatePanel";
import { AgentListStatePanel } from "./AgentListStatePanel";
import styles from "./AgentListWorkspacePanel.styles";

type AgentListWorkspacePanelProps = {
  createOpen: boolean;
  ariaLabel: string;
  headerEyebrow: string;
  headerTitle: string;
  createAgentLabel: string;
  visibleAgentCount: number;
  createPanel: ComponentProps<typeof AgentCreatePanel>;
  bulkOperations: ComponentProps<typeof AgentBulkOperationsPanel>;
  listState: ComponentProps<typeof AgentListStatePanel>;
  onToggleCreate: () => void;
};

export function AgentListWorkspacePanel({
  createOpen,
  ariaLabel,
  headerEyebrow,
  headerTitle,
  createAgentLabel,
  visibleAgentCount,
  createPanel,
  bulkOperations,
  listState,
  onToggleCreate,
}: AgentListWorkspacePanelProps) {
  return (
    <AgentWorkspacePanel
      as="main"
      ariaLabel={ariaLabel}
      className={createOpen ? `${styles.agentPanel} ${styles.agentPanelCreating}` : styles.agentPanel}
    >
      <VPanelHeader
        eyebrow={headerEyebrow}
        title={headerTitle}
        actions={
          <>
            <VButton
              type="button"
              variant="secondary"
              icon={<Plus size={15} />}
              onPress={onToggleCreate}
            >
              {createAgentLabel}
            </VButton>
            <VChip tone="neutral">{visibleAgentCount}</VChip>
          </>
        }
      />
      {createOpen ? <AgentCreatePanel {...createPanel} /> : null}
      {!createOpen ? <AgentBulkOperationsPanel {...bulkOperations} /> : null}
      <AgentListStatePanel {...listState} />
    </AgentWorkspacePanel>
  );
}
