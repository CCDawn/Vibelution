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

export function AgentManagementHeaderPanel() {
  return <AgentManagementModuleBar active="agents" />;
}

/** Directory actions stay beside the list they create and refresh. */
export function AgentManagementDirectoryActions({
  copy,
  createAgentButtonRef,
  createAgentButtonId,
  refreshing = false,
  onCreateAgent,
  onRefresh,
}: AgentManagementHeaderPanelProps) {
  return (
    <>
      <VIconButton
        type="button"
        variant="ghost"
        label={copy.refresh}
        icon={<RefreshCw size={15} />}
        isDisabled={refreshing}
        onPress={onRefresh}
      />
      <VButton
        ref={createAgentButtonRef}
        id={createAgentButtonId}
        type="button"
        variant="ghost"
        isIconOnly
        aria-label={copy.createAgent}
        tooltip={copy.createAgent}
        icon={<Plus size={15} />}
        onPress={onCreateAgent}
      />
    </>
  );
}
