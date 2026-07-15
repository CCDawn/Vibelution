import { type ComponentProps } from "react";

import { AgentActivityPanePanel } from "./AgentActivityPanePanel";
import { AgentConfigPrimaryPanePanel } from "./AgentConfigPrimaryPanePanel";
import { AgentConfigPolicyPanePanel } from "./AgentConfigPolicyPanePanel";
import { AgentConfigReferencesPanePanel } from "./AgentConfigReferencesPanePanel";
import {
  AgentDetailHeaderPanel,
  type AgentDetailHeaderPaneView,
} from "./AgentDetailHeaderPanel";
import { AgentManagementBriefPanel } from "./AgentManagementBriefPanel";
import { AgentOverviewPanel } from "./AgentOverviewPanel";

export type AgentSelectedDetailPaneId = "overview" | "config" | "activity";

type AgentSelectedDetailHeaderProps = Omit<
  ComponentProps<typeof AgentDetailHeaderPanel>,
  "activePane" | "onSelectPane" | "panes"
> & {
  activePane: AgentSelectedDetailPaneId;
  onSelectPane: (pane: AgentSelectedDetailPaneId) => void;
  panes: AgentDetailHeaderPaneView<AgentSelectedDetailPaneId>[];
};

export type AgentSelectedDetailContentPanelProps = {
  activePane: AgentSelectedDetailPaneId;
  header: AgentSelectedDetailHeaderProps;
  brief: ComponentProps<typeof AgentManagementBriefPanel>;
  overview: ComponentProps<typeof AgentOverviewPanel> | null;
  configPrimary: ComponentProps<typeof AgentConfigPrimaryPanePanel>;
  configPolicies: ComponentProps<typeof AgentConfigPolicyPanePanel>;
  configReferences: ComponentProps<typeof AgentConfigReferencesPanePanel>;
  activity: ComponentProps<typeof AgentActivityPanePanel>;
};

export function AgentSelectedDetailContentPanel({
  activePane,
  header,
  brief,
  overview,
  configPrimary,
  configPolicies,
  configReferences,
  activity,
}: AgentSelectedDetailContentPanelProps) {
  return (
    <>
      <AgentDetailHeaderPanel {...header} />
      {activePane === "overview" && overview ? <AgentOverviewPanel {...overview} /> : null}
      {activePane === "overview" ? <AgentManagementBriefPanel {...brief} /> : null}
      {activePane === "config" ? (
        <>
          <AgentConfigPrimaryPanePanel {...configPrimary} />
          <AgentConfigPolicyPanePanel {...configPolicies} />
          <AgentConfigReferencesPanePanel {...configReferences} />
        </>
      ) : null}
      {activePane === "activity" ? <AgentActivityPanePanel {...activity} /> : null}
    </>
  );
}
