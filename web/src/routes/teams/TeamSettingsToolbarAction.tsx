/**
 * Teams toolbar "team settings" action: opens TeamSettingsDialog for the
 * selected team. Self-contained mount (mirrors TeamCreateToolbarActions) —
 * the toolbar only renders <TeamSettingsToolbarAction />.
 */
import { useRef, useState } from "react";
import { Settings2 } from "lucide-react";

import type { AgentConfigWorkspaceAgent, Team } from "../../api/types";
import { VButton } from "../../components/vui";
import { TeamSettingsDialog } from "./TeamSettingsDialog";
import { useTeamSettingsActions } from "./useTeamSettingsActions";

export type TeamSettingsToolbarActionProps = {
  lang: "zh" | "en";
  /** Selected team detail (full). Hidden when absent. */
  team: Team | null;
  agents: AgentConfigWorkspaceAgent[];
  teams: Team[];
  agentsById: Map<string, AgentConfigWorkspaceAgent>;
};

export function TeamSettingsToolbarAction({
  lang,
  team,
  agents,
  teams,
  agentsById,
}: TeamSettingsToolbarActionProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const settings = useTeamSettingsActions({
    onArchived: () => setOpen(false),
  });

  const closeAndReset = () => {
    setOpen(false);
    settings.reset();
  };

  const label = lang === "zh" ? "团队设置" : "Team settings";

  return (
    <>
      <VButton
        ref={triggerRef}
        type="button"
        variant="ghost"
        density="compact"
        icon={<Settings2 size={14} aria-hidden="true" />}
        aria-label={label}
        title={label}
        isDisabled={!team}
        onClick={() => setOpen(true)}
      >
        {label}
      </VButton>
      <TeamSettingsDialog
        open={open}
        lang={lang}
        team={team}
        agents={agents}
        teams={teams}
        agentsById={agentsById}
        pending={settings.pending}
        createRoomPending={settings.createRoomPending}
        errorMessage={settings.errorMessage}
        onSubmit={(teamId, payload) => settings.submit(teamId, payload)}
        onCreateRoom={(teamId) => settings.createRoom(teamId)}
        archivePending={settings.archivePending}
        onArchive={(teamId) => settings.archive(teamId)}
        onClose={closeAndReset}
      />
    </>
  );
}
