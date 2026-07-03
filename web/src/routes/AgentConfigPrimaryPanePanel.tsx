import { type ComponentProps } from "react";

import { AgentArchiveZonePanel } from "./AgentArchiveZonePanel";
import { AgentCoreConfigPanel } from "./AgentCoreConfigPanel";
import { AgentDebugResetPanel } from "./AgentDebugResetPanel";
import { AgentHealthMaintenancePanel } from "./AgentHealthMaintenancePanel";
import { AgentPersonaProfilePanel } from "./AgentPersonaProfilePanel";
import { AgentTaskProfilePanel } from "./AgentTaskProfilePanel";
import { AgentToolGovernancePanel } from "./AgentToolGovernancePanel";

type AgentConfigPrimaryPanePanelProps = {
  coreConfig: ComponentProps<typeof AgentCoreConfigPanel>;
  personaProfile: ComponentProps<typeof AgentPersonaProfilePanel> | null;
  toolGovernance: ComponentProps<typeof AgentToolGovernancePanel>;
  taskProfile: ComponentProps<typeof AgentTaskProfilePanel> | null;
  healthMaintenance: ComponentProps<typeof AgentHealthMaintenancePanel>;
  archiveZone: ComponentProps<typeof AgentArchiveZonePanel>;
  debugReset: ComponentProps<typeof AgentDebugResetPanel> | null;
};

export function AgentConfigPrimaryPanePanel({
  coreConfig,
  personaProfile,
  toolGovernance,
  taskProfile,
  healthMaintenance,
  archiveZone,
  debugReset,
}: AgentConfigPrimaryPanePanelProps) {
  return (
    <>
      <AgentCoreConfigPanel {...coreConfig} />
      {personaProfile ? <AgentPersonaProfilePanel {...personaProfile} /> : null}
      <AgentToolGovernancePanel {...toolGovernance} />
      {taskProfile ? <AgentTaskProfilePanel {...taskProfile} /> : null}
      <AgentHealthMaintenancePanel {...healthMaintenance} />
      <AgentArchiveZonePanel {...archiveZone} />
      {debugReset ? <AgentDebugResetPanel {...debugReset} /> : null}
    </>
  );
}
