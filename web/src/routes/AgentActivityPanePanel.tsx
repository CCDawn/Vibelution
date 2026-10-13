import { type ComponentProps } from "react";

import { AgentActivityHistoryPanel } from "./AgentActivityHistoryPanel";
import { AgentRuntimeFocusPanel } from "./AgentRuntimeFocusPanel";
import { AgentRuntimePolicyPanel } from "./AgentRuntimePolicyPanel";

type AgentActivityPanePanelProps = {
  runtimeFocus: ComponentProps<typeof AgentRuntimeFocusPanel>;
  activityHistory: ComponentProps<typeof AgentActivityHistoryPanel>;
  runtimePolicy: ComponentProps<typeof AgentRuntimePolicyPanel>;
  hideRuntimePolicy?: boolean;
};

export function AgentActivityPanePanel({
  runtimeFocus,
  activityHistory,
  runtimePolicy,
  hideRuntimePolicy = false,
}: AgentActivityPanePanelProps) {
  return (
    <>
      <AgentRuntimeFocusPanel {...runtimeFocus} />
      <AgentActivityHistoryPanel {...activityHistory} />
      {!hideRuntimePolicy ? <AgentRuntimePolicyPanel {...runtimePolicy} /> : null}
    </>
  );
}
