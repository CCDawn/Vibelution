import { Plus } from "lucide-react";
import { type ComponentProps, type Ref } from "react";

import { AgentWorkspacePanel } from "../components/vui/product/agent-management";
import { VButton, VChip, VPanelHeader } from "../components/vui";
import { AgentBulkOperationsPanel } from "./AgentBulkOperationsPanel";
import { AgentListStatePanel } from "./AgentListStatePanel";
import styles from "./AgentListWorkspacePanel.styles";

type AgentListWorkspacePanelProps = {
  ariaLabel: string;
  headerEyebrow: string;
  headerTitle: string;
  createAgentLabel: string;
  visibleAgentCount: number;
  createAgentButtonRef?: Ref<HTMLButtonElement>;
  createAgentButtonId?: string;
  bulkOperations: ComponentProps<typeof AgentBulkOperationsPanel>;
  listState: ComponentProps<typeof AgentListStatePanel>;
  onToggleCreate: () => void;
};

export function AgentListWorkspacePanel({
  ariaLabel,
  headerEyebrow,
  headerTitle,
  createAgentLabel,
  visibleAgentCount,
  createAgentButtonRef,
  createAgentButtonId,
  bulkOperations,
  listState,
  onToggleCreate,
}: AgentListWorkspacePanelProps) {
  return (
    <AgentWorkspacePanel
      as="main"
      ariaLabel={ariaLabel}
      className={styles.agentPanel}
    >
      <VPanelHeader
        eyebrow={headerEyebrow}
        title={headerTitle}
        actions={
          <>
            <VButton
              ref={createAgentButtonRef}
              id={createAgentButtonId}
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
      <AgentBulkOperationsPanel {...bulkOperations} />
      <AgentListStatePanel {...listState} />
    </AgentWorkspacePanel>
  );
}
