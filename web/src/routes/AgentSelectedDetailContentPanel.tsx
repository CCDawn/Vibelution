import { useEffect, useMemo, useState, type ComponentProps } from "react";

import { VNativeButton } from "../components/vui";
import { AgentActivityPanePanel } from "./AgentActivityPanePanel";
import { AgentConfigPrimaryPanePanel } from "./AgentConfigPrimaryPanePanel";
import { AgentConfigPolicyPanePanel } from "./AgentConfigPolicyPanePanel";
import { AgentConfigReferencesPanePanel } from "./AgentConfigReferencesPanePanel";
import { AgentEffectiveConfigurationPanel } from "./AgentEffectiveConfigurationPanel";
import { AgentTeamRelationsPanel } from "./AgentTeamRelationsPanel";
import {
  AgentDetailHeaderPanel,
  type AgentDetailHeaderPaneView,
} from "./AgentDetailHeaderPanel";
import { AgentManagementBriefPanel } from "./AgentManagementBriefPanel";
import { AgentOverviewPanel } from "./AgentOverviewPanel";
import { AgentOverviewOperationsPanel } from "./AgentOverviewOperationsPanel";
import { AgentOverviewResourcesPanel } from "./AgentOverviewResourcesPanel";
import styles from "./AgentSelectedDetailContentPanel.styles";

export type AgentSelectedDetailPaneId = "overview" | "effective" | "relations" | "config" | "activity";

export type AgentConfigSectionId = "basic" | "profile" | "capability" | "ops";

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
  effectiveConfiguration: ComponentProps<typeof AgentEffectiveConfigurationPanel>;
  teamRelations: ComponentProps<typeof AgentTeamRelationsPanel>;
  configPrimary: ComponentProps<typeof AgentConfigPrimaryPanePanel>;
  configPolicies: ComponentProps<typeof AgentConfigPolicyPanePanel>;
  configReferences: ComponentProps<typeof AgentConfigReferencesPanePanel>;
  activity: ComponentProps<typeof AgentActivityPanePanel>;
  /** Prefer opening ops when agent has health issues. */
  preferOpsSection?: boolean;
  /**
   * When true, brief/resources render in workspace inspector rail instead of
   * nested overview aside (overall three-column layout).
   */
  inspectorInWorkspaceRail?: boolean;
};

function configSectionLabels(lang: "zh" | "en") {
  return lang === "zh"
    ? {
        basic: "基本",
        profile: "人设与任务",
        capability: "能力绑定",
        ops: "运维·危险",
        navLabel: "配置分组",
      }
    : {
        basic: "Basics",
        profile: "Persona",
        capability: "Capabilities",
        ops: "Ops · Danger",
        navLabel: "Configuration sections",
      };
}

export function AgentSelectedDetailContentPanel({
  activePane,
  header,
  brief,
  overview,
  operations,
  resources,
  effectiveConfiguration,
  teamRelations,
  configPrimary,
  configPolicies,
  configReferences,
  activity,
  preferOpsSection = false,
  inspectorInWorkspaceRail = true,
}: AgentSelectedDetailContentPanelProps) {
  const [configSection, setConfigSection] = useState<AgentConfigSectionId>(
    preferOpsSection ? "ops" : "basic",
  );
  const labels = configSectionLabels(header.lang);

  useEffect(() => {
    if (activePane !== "config") {
      return;
    }
    setConfigSection(preferOpsSection ? "ops" : "basic");
  }, [activePane, header.agentName, preferOpsSection]);

  const opsBadge = useMemo(() => {
    const health = configPrimary.healthMaintenance?.health;
    return health?.hasIssues ? (health.issues?.length ?? 1) : 0;
  }, [configPrimary.healthMaintenance]);

  const showNestedAside = !inspectorInWorkspaceRail;

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
          {showNestedAside ? (
            <aside className={styles.overviewAside}>
              <AgentManagementBriefPanel {...brief} />
              {resources ? <AgentOverviewResourcesPanel {...resources} /> : null}
            </aside>
          ) : null}
        </div>
      ) : null}
      {activePane === "effective" ? (
        <div className={styles.paneContent}>
          <AgentEffectiveConfigurationPanel {...effectiveConfiguration} />
        </div>
      ) : null}
      {activePane === "relations" ? (
        <div className={styles.paneContent}>
          <AgentTeamRelationsPanel {...teamRelations} />
        </div>
      ) : null}
      {activePane === "config" ? (
        <div className={styles.paneContent}>
          <nav className={styles.configSectionNav} aria-label={labels.navLabel}>
            {(
              [
                ["basic", labels.basic],
                ["profile", labels.profile],
                ["capability", labels.capability],
                ["ops", labels.ops],
              ] as const
            ).map(([id, label]) => (
              <VNativeButton
                key={id}
                type="button"
                className={
                  configSection === id ? styles.configSectionTabActive : styles.configSectionTab
                }
                onClick={() => setConfigSection(id)}
                aria-pressed={configSection === id}
              >
                <span>{label}</span>
                {id === "ops" && opsBadge > 0 ? (
                  <strong className={styles.configSectionBadge}>{opsBadge}</strong>
                ) : null}
              </VNativeButton>
            ))}
          </nav>
          <div className={styles.configSectionBody}>
            {configSection === "basic" ? (
              <AgentConfigPrimaryPanePanel {...configPrimary} section="basic" />
            ) : null}
            {configSection === "profile" ? (
              <AgentConfigPrimaryPanePanel {...configPrimary} section="profile" />
            ) : null}
            {configSection === "capability" ? (
              <>
                <AgentConfigPolicyPanePanel {...configPolicies} />
                <AgentConfigReferencesPanePanel {...configReferences} />
              </>
            ) : null}
            {configSection === "ops" ? (
              <AgentConfigPrimaryPanePanel
                {...configPrimary}
                section="ops"
                opsTitle={header.lang === "zh" ? "运维与危险操作" : "Ops and dangerous actions"}
                opsHint={
                  header.lang === "zh"
                    ? "健康检查、归档删除与调试重置与日常配置分离。"
                    : "Health, archive/delete, and debug reset are separated from daily config."
                }
              />
            ) : null}
          </div>
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
