import { Plus, RefreshCw } from "lucide-react";
import { type Ref } from "react";

import { VButton, VIconButton } from "../components/vui";
import { AgentManagementModuleBar } from "./AgentManagementModuleBar";

type AgentManagementHeaderPanelCopy = {
  createAgent: string;
  refresh: string;
};

type AgentManagementHeaderPanelProps = {
  copy: AgentManagementHeaderPanelCopy;
  createAgentButtonRef?: Ref<HTMLButtonElement>;
  createAgentButtonId?: string;
  refreshing?: boolean;
  onCreateAgent: () => void;
  onRefresh: () => void;
};

export function AgentManagementHeaderPanel({
  copy,
  createAgentButtonRef,
  createAgentButtonId,
  refreshing = false,
  onCreateAgent,
  onRefresh,
}: AgentManagementHeaderPanelProps) {
  return (
    <AgentManagementModuleBar
      active="agents"
      actions={(
        <>
          <VIconButton
            type="button"
            label={copy.refresh}
            icon={<RefreshCw size={15} />}
            isDisabled={refreshing}
            onPress={onRefresh}
          />
          <VButton
            ref={createAgentButtonRef}
            id={createAgentButtonId}
            type="button"
            variant="primary"
            icon={<Plus size={15} />}
            onPress={onCreateAgent}
          >
            {copy.createAgent}
          </VButton>
        </>
      )}
    />
  );
}
