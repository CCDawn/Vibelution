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
import { AgentOverviewOperationsPanel } from "./AgentOverviewOperationsPanel";
import { AgentOverviewResourcesPanel } from "./AgentOverviewResourcesPanel";
import styles from "./AgentSelectedDetailContentPanel.styles";

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
  operations: ComponentProps<typeof AgentOverviewOperationsPanel> | null;
  resources: ComponentProps<typeof AgentOverviewResourcesPanel> | null;
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
  operations,
  resources,
  configPrimary,
  configPolicies,
  configReferences,
  activity,
}: AgentSelectedDetailContentPanelProps) {
  return (
    <div className={styles.selectedDetailFrame}>
      <AgentDetailHeaderPanel {...header} />
      {activePane === "overview" && overview ? (
        <div className={styles.overviewLayout}>
          <div className={styles.overviewMain}>
            <AgentOverviewPanel {...overview}>
              {operations ? <AgentOverviewOperationsPanel {...operations} /> : null}
            </AgentOverviewPanel>
          </div>
          <aside className={styles.overviewAside}>
            <AgentManagementBriefPanel {...brief} />
            {resources ? <AgentOverviewResourcesPanel {...resources} /> : null}
          </aside>
        </div>
      ) : null}
      {activePane === "config" ? (
        <div className={styles.paneContent}>
          <AgentConfigPrimaryPanePanel {...configPrimary} />
          <AgentConfigPolicyPanePanel {...configPolicies} />
          <AgentConfigReferencesPanePanel {...configReferences} />
        </div>
      ) : null}
      {activePane === "activity" ? (
        <div className={styles.paneContent}>
          <AgentActivityPanePanel {...activity} />
        </div>
      ) : null}
    </div>
  );
}
