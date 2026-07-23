import { type ComponentProps } from "react";

import { AgentArchiveZonePanel } from "./AgentArchiveZonePanel";
import { AgentCoreConfigPanel } from "./AgentCoreConfigPanel";
import { AgentDebugResetPanel } from "./AgentDebugResetPanel";
import { AgentHealthMaintenancePanel } from "./AgentHealthMaintenancePanel";
import { AgentPersonaProfilePanel } from "./AgentPersonaProfilePanel";
import { AgentTaskProfilePanel } from "./AgentTaskProfilePanel";
import { AgentToolGovernancePanel } from "./AgentToolGovernancePanel";

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
          className="grid min-w-0 content-start gap-2 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--state-error)_22%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_4%,var(--vui-surface-panel))] p-2.5"
          aria-label={`${opsTitle} · ${opsHint}`}
        >
          <header className="grid min-w-0 gap-0.5 px-0.5">
            <p className="m-0 text-[0.62rem] font-bold uppercase tracking-[0.08em] text-[var(--state-error)]">
              {opsTitle}
            </p>
            <p className="m-0 text-[0.76rem] leading-[1.35] text-[var(--fg-secondary)]">{opsHint}</p>
          </header>
          <AgentHealthMaintenancePanel {...healthMaintenance} />
          <AgentArchiveZonePanel {...archiveZone} />
          {debugReset ? <AgentDebugResetPanel {...debugReset} /> : null}
        </section>
      ) : null}
    </>
  );
}
