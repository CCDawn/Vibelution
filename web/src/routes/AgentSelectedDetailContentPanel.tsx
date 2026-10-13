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
import { FinancialAssistantStatusNote } from "./finance/FinancialAssistantStatusNote";
import { ProgressiveRegionSkeleton } from "./shared/ProgressiveRegionSkeleton";
import type { AgentPerceptionDraftState, AgentPerceptionDraftStore } from "./agentPerception/useAgentPerceptionDraft";

export type AgentSelectedDetailPaneId = "overview" | "config" | "activity" | "perception";

export type AgentConfigSectionId = "models" | "basic" | "persona" | "task" | "capability" | "runtime" | "ops";

/** Secondary panes — kept off the default overview graph (F3-B). */
const AgentActivityPanePanel = lazy(() =>
  import("./AgentActivityPanePanel").then((m) => ({ default: m.AgentActivityPanePanel })),
);
const AgentPerceptionPane = lazy(() =>
  import("./AgentPerceptionPane").then((m) => ({ default: m.AgentPerceptionPane })),
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
const AgentRuntimePolicyPanel = lazy(() =>
  import("./AgentRuntimePolicyPanel").then((m) => ({ default: m.AgentRuntimePolicyPanel })),
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
  agentId: string;
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
  onOpenSession: (sessionId: string) => void;
  /** Prefer opening ops when agent has health issues. */
  preferOpsSection?: boolean;
};

function configSectionLabels(lang: "zh" | "en") {
  return lang === "zh"
    ? {
        basic: "基本",
        models: "模型",
        persona: "人物",
        task: "任务",
        capability: "工具与记忆",
        runtime: "委派与监督",
        ops: "运维",
        navLabel: "配置分组",
      }
    : {
        basic: "Basics",
        models: "Models",
        persona: "Persona",
        task: "Tasks",
        capability: "Tools & memory",
        runtime: "Delegation & supervision",
        ops: "Operations",
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
  agentId,
  header,
  overview,
  configChanges,
  configPrimary,
  configPolicies,
  configReferences,
  virtualHumanPlugin,
  activity,
  onOpenSession,
  preferOpsSection = false,
}: AgentSelectedDetailContentPanelProps) {
  const [configSection, setConfigSection] = useState<AgentConfigSectionId>(
    preferOpsSection ? "ops" : "models",
  );
  const [perceptionDrafts, setPerceptionDrafts] = useState<AgentPerceptionDraftState>({});
  const perceptionDraftStore = useMemo<AgentPerceptionDraftStore>(() => ({
    drafts: perceptionDrafts,
    setDrafts: setPerceptionDrafts,
  }), [perceptionDrafts]);
  const labels = configSectionLabels(header.lang);

  useEffect(() => {
    if (activePane !== "config") {
      return;
    }
    setConfigSection(preferOpsSection ? "ops" : "models");
  }, [activePane, agentId, preferOpsSection]);

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
          <div className={styles.configPane}>
            <div><FinancialAssistantStatusNote agentId={agentId} lang={header.lang} /></div>
            <nav className={styles.configSectionNav} aria-label={labels.navLabel}>
              {(
                [
                  ["models", labels.models],
                  ["basic", labels.basic],
                  ["persona", labels.persona],
                  ["task", labels.task],
                  ["capability", labels.capability],
                  ["runtime", labels.runtime],
                  ["ops", labels.ops],
                ] as const
              ).filter(([id]) => id === "persona" ? Boolean(configPrimary.personaProfile) : id === "task" ? Boolean(configPrimary.taskProfile) : true).map(([id, label]) => (
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
              {configSection === "models" ? <AgentConfigPrimaryPanePanel {...configPrimary} section="models" /> : null}
              {configSection === "basic" ? (
                <AgentConfigPrimaryPanePanel {...configPrimary} section="basic" />
              ) : null}
              {configSection === "persona" ? <AgentConfigPrimaryPanePanel {...configPrimary} section="persona" /> : null}
              {configSection === "task" ? <AgentConfigPrimaryPanePanel {...configPrimary} section="task" /> : null}
              {configSection === "capability" ? (
                <AgentConfigPolicyPanePanel {...configPolicies} toolGovernance={<AgentConfigPrimaryPanePanel {...configPrimary} section="tools" />} />
              ) : null}
              {configSection === "runtime" ? <AgentRuntimePolicyPanel {...activity.runtimePolicy} /> : null}
              {configSection === "ops" ? (
                <div className={styles.opsContent}>
                <AgentConfigPrimaryPanePanel
                  {...configPrimary}
                  section="ops"
                  opsTitle={header.lang === "zh" ? "Agent 管理" : "Agent management"}
                  opsHint={
                    header.lang === "zh"
                      ? "健康检查、归档删除与调试重置与日常配置分离。"
                      : "Health, archive/delete, and debug reset are separated from daily config."
                  }
                />
                <details className={styles.secondaryDetails}><summary className={styles.secondarySummary}>{header.lang === "zh" ? "关联与插件" : "References & plugins"}</summary><div className={styles.secondaryBody}><AgentVirtualHumanPluginPanel {...virtualHumanPlugin} /><AgentConfigReferencesPanePanel {...configReferences} /></div></details>
                </div>
              ) : null}
            </div>
          </div>
        </PaneSuspense>
      ) : null}
      {activePane === "activity" ? (
        <PaneSuspense lang={header.lang}>
          <div className={styles.paneContent}>
            <AgentActivityPanePanel {...activity} hideRuntimePolicy />
            <AgentConfigChangeHistoryPanel {...configChanges} lang={header.lang} />
          </div>
        </PaneSuspense>
      ) : null}
      {activePane === "perception" ? (
        <PaneSuspense lang={header.lang}>
          <div className={styles.paneContent}>
            <AgentPerceptionPane
              agentId={agentId}
              lang={header.lang}
              onOpenSession={onOpenSession}
              draftStore={perceptionDraftStore}
            />
          </div>
        </PaneSuspense>
      ) : null}
    </div>
  );
}
