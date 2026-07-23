import { CheckSquare } from "lucide-react";
import { type ComponentProps } from "react";

import { AgentWorkspacePanel } from "../components/vui/product/agent-management";
import { VButton, VChip, VPanelHeader } from "../components/vui";
import { AgentBulkOperationsPanel } from "./AgentBulkOperationsPanel";
import { AgentListStatePanel } from "./AgentListStatePanel";
import styles from "./AgentListWorkspacePanel.styles";

type AgentListWorkspacePanelProps = {
  ariaLabel: string;
  headerEyebrow: string;
  headerTitle: string;
  visibleAgentCount: number;
  bulkOperations: ComponentProps<typeof AgentBulkOperationsPanel>;
  listState: ComponentProps<typeof AgentListStatePanel>;
};

export function AgentListWorkspacePanel({
  ariaLabel,
  headerEyebrow,
  headerTitle,
  visibleAgentCount,
  bulkOperations,
  listState,
}: AgentListWorkspacePanelProps) {
  return (
    <AgentWorkspacePanel
      as="main"
      ariaLabel={ariaLabel}
      className={[
        styles.agentPanel,
        bulkOperations.selectedCount > 0 ? styles.agentPanelSelecting : styles.agentPanelIdle,
      ].filter(Boolean).join(" ")}
    >
      <VPanelHeader
        eyebrow={headerEyebrow}
        title={headerTitle}
        actions={
          <>
            {bulkOperations.selectedCount === 0 ? (
              <VButton
                type="button"
                variant="secondary"
                icon={<CheckSquare size={15} />}
                isDisabled={bulkOperations.visibleCount === 0 || bulkOperations.pending}
                onPress={bulkOperations.onSelectVisible}
              >
                {bulkOperations.copy.bulkSelectVisible}
              </VButton>
            ) : null}
            <VChip tone="neutral">{visibleAgentCount}</VChip>
          </>
        }
      />
      {bulkOperations.selectedCount > 0 ? <AgentBulkOperationsPanel {...bulkOperations} /> : null}
      <AgentListStatePanel {...listState} />
    </AgentWorkspacePanel>
  );
}
