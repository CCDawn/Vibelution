import { type ComponentProps } from "react";

import { AgentActivityHistoryPanel } from "./AgentActivityHistoryPanel";
import { AgentRuntimeFocusPanel } from "./AgentRuntimeFocusPanel";
import { AgentRuntimePolicyPanel } from "./AgentRuntimePolicyPanel";

type AgentActivityPanePanelProps = {
  runtimeFocus: ComponentProps<typeof AgentRuntimeFocusPanel>;
  activityHistory: ComponentProps<typeof AgentActivityHistoryPanel>;
  runtimePolicy: ComponentProps<typeof AgentRuntimePolicyPanel>;
};

export function AgentActivityPanePanel({
  runtimeFocus,
  activityHistory,
  runtimePolicy,
}: AgentActivityPanePanelProps) {
  return (
    <>
      <AgentRuntimeFocusPanel {...runtimeFocus} />
      <AgentActivityHistoryPanel {...activityHistory} />
      <AgentRuntimePolicyPanel {...runtimePolicy} />
    </>
  );
}
