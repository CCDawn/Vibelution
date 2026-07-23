import { type ComponentProps } from "react";

import { AgentArchiveZonePanel } from "./AgentArchiveZonePanel";
import { AgentCoreConfigPanel } from "./AgentCoreConfigPanel";
import { AgentDebugResetPanel } from "./AgentDebugResetPanel";
import { AgentHealthMaintenancePanel } from "./AgentHealthMaintenancePanel";
import { AgentPersonaProfilePanel } from "./AgentPersonaProfilePanel";
import { AgentTaskProfilePanel } from "./AgentTaskProfilePanel";
import { AgentToolGovernancePanel } from "./AgentToolGovernancePanel";
import styles from "./AgentConfigPrimaryPanePanel.styles";

export type AgentConfigPrimarySectionId = "all" | "basic" | "profile" | "ops";

type AgentConfigPrimaryPanePanelProps = {
  section?: AgentConfigPrimarySectionId;
  coreConfig: ComponentProps<typeof AgentCoreConfigPanel>;
  personaProfile: ComponentProps<typeof AgentPersonaProfilePanel> | null;
  toolGovernance: ComponentProps<typeof AgentToolGovernancePanel>;
  taskProfile: ComponentProps<typeof AgentTaskProfilePanel> | null;
  healthMaintenance: ComponentProps<typeof AgentHealthMaintenancePanel>;
  archiveZone: ComponentProps<typeof AgentArchiveZonePanel>;
  debugReset: ComponentProps<typeof AgentDebugResetPanel> | null;
  opsTitle?: string;
  opsHint?: string;
};

export function AgentConfigPrimaryPanePanel({
  section = "all",
  coreConfig,
  personaProfile,
  toolGovernance,
  taskProfile,
  healthMaintenance,
  archiveZone,
  debugReset,
  opsTitle = "运维与危险操作",
  opsHint = "健康检查、归档删除与调试重置与日常配置分离，默认仅在需要时查看。",
}: AgentConfigPrimaryPanePanelProps) {
  const showBasic = section === "all" || section === "basic";
  const showProfile = section === "all" || section === "profile";
  const showOps = section === "all" || section === "ops";

  return (
    <>
      {showBasic ? <AgentCoreConfigPanel {...coreConfig} /> : null}
      {showProfile ? (
        <>
          {personaProfile ? <AgentPersonaProfilePanel {...personaProfile} /> : null}
          <AgentToolGovernancePanel {...toolGovernance} />
          {taskProfile ? <AgentTaskProfilePanel {...taskProfile} /> : null}
        </>
      ) : null}
      {showOps ? (
        <section
          data-vui-product="agent-config-ops-zone"
          className={styles.opsZone}
          aria-label={`${opsTitle} · ${opsHint}`}
        >
          <header className={styles.opsHeader}>
            <p className={styles.opsTitle}>
              {opsTitle}
            </p>
            <p className={styles.opsHint}>{opsHint}</p>
          </header>
          <AgentHealthMaintenancePanel {...healthMaintenance} />
          <AgentArchiveZonePanel {...archiveZone} />
          {debugReset ? <AgentDebugResetPanel {...debugReset} /> : null}
        </section>
      ) : null}
    </>
  );
}
