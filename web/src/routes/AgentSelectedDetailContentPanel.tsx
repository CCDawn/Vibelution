import { lazy, Suspense, useEffect, useMemo, useState, type ComponentProps, type ReactNode } from "react";

import { VNativeButton } from "../components/vui";
import {
  AgentDetailHeaderPanel,
  type AgentDetailHeaderPaneView,
} from "./AgentDetailHeaderPanel";
import { AgentFocusedOverviewPanel } from "./AgentFocusedOverviewPanel";
import { AgentManagementBriefPanel } from "./AgentManagementBriefPanel";
import { AgentOverviewResourcesPanel } from "./AgentOverviewResourcesPanel";
import styles from "./AgentSelectedDetailContentPanel.styles";
import { ProgressiveRegionSkeleton } from "./shared/ProgressiveRegionSkeleton";

export type AgentSelectedDetailPaneId = "overview" | "config" | "activity";

export type AgentConfigSectionId = "basic" | "profile" | "capability" | "ops";

/** Secondary panes — kept off the default overview graph (F3-B). */
const AgentActivityPanePanel = lazy(() =>
  import("./AgentActivityPanePanel").then((m) => ({ default: m.AgentActivityPanePanel })),
);
const AgentConfigPrimaryPanePanel = lazy(() =>
  import("./AgentConfigPrimaryPanePanel").then((m) => ({ default: m.AgentConfigPrimaryPanePanel })),
);
const AgentConfigPolicyPanePanel = lazy(() =>
  import("./AgentConfigPolicyPanePanel").then((m) => ({ default: m.AgentConfigPolicyPanePanel })),
);
const AgentConfigReferencesPanePanel = lazy(() =>
  import("./AgentConfigReferencesPanePanel").then((m) => ({ default: m.AgentConfigReferencesPanePanel })),
);
const AgentConfigChangeHistoryPanel = lazy(() =>
  import("./AgentConfigChangeHistoryPanel").then((m) => ({ default: m.AgentConfigChangeHistoryPanel })),
);
const AgentVirtualHumanPluginPanel = lazy(() =>
  import("./agent-plugins/AgentVirtualHumanPluginPanel").then((m) => ({ default: m.AgentVirtualHumanPluginPanel })),
);

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
  overview: ComponentProps<typeof AgentFocusedOverviewPanel> | null;
  resources: ComponentProps<typeof AgentOverviewResourcesPanel> | null;
  configChanges: ComponentProps<typeof AgentConfigChangeHistoryPanel>;
  configPrimary: ComponentProps<typeof AgentConfigPrimaryPanePanel>;
  configPolicies: ComponentProps<typeof AgentConfigPolicyPanePanel>;
  configReferences: ComponentProps<typeof AgentConfigReferencesPanePanel>;
  virtualHumanPlugin: ComponentProps<typeof AgentVirtualHumanPluginPanel>;
  activity: ComponentProps<typeof AgentActivityPanePanel>;
  /** Prefer opening ops when agent has health issues. */
  preferOpsSection?: boolean;
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

function PaneSuspense({ children, lang }: { children: ReactNode; lang: "zh" | "en" }) {
  return (
    <Suspense
      fallback={
        <div className={styles.paneContent}>
          <ProgressiveRegionSkeleton
            variant="panel"
            label={lang === "zh" ? "正在加载面板" : "Loading panel"}
          />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

export function AgentSelectedDetailContentPanel({
  activePane,
  header,
  overview,
  configChanges,
  configPrimary,
  configPolicies,
  configReferences,
  virtualHumanPlugin,
  activity,
  preferOpsSection = false,
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

  return (
    <div className={styles.selectedDetailFrame}>
      <div className={styles.detailHeaderRegion}>
        <AgentDetailHeaderPanel {...header} />
      </div>
      {activePane === "overview" && overview ? (
        <div className={styles.overviewLayout}>
          <AgentFocusedOverviewPanel {...overview} />
        </div>
      ) : null}
      {activePane === "config" ? (
        <PaneSuspense lang={header.lang}>
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
                  <AgentVirtualHumanPluginPanel {...virtualHumanPlugin} />
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
        </PaneSuspense>
      ) : null}
      {activePane === "activity" ? (
        <PaneSuspense lang={header.lang}>
          <div className={styles.paneContent}>
            <AgentActivityPanePanel {...activity} />
            <AgentConfigChangeHistoryPanel {...configChanges} lang={header.lang} />
          </div>
        </PaneSuspense>
      ) : null}
    </div>
  );
}
