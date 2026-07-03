import { type ComponentProps } from "react";

import { AgentMemoryPolicyPanel } from "./AgentMemoryPolicyPanel";
import { AgentToolSummaryPanel } from "./AgentToolSummaryPanel";

type AgentConfigPolicyPanePanelProps = {
  toolSummary: ComponentProps<typeof AgentToolSummaryPanel>;
  memoryPolicy: ComponentProps<typeof AgentMemoryPolicyPanel>;
};

export function AgentConfigPolicyPanePanel({
  toolSummary,
  memoryPolicy,
}: AgentConfigPolicyPanePanelProps) {
  return (
    <>
      <AgentToolSummaryPanel {...toolSummary} />
      <AgentMemoryPolicyPanel {...memoryPolicy} />
    </>
  );
}
