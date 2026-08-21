import { RefreshCw } from "lucide-react";

import type { TeamShellMode } from "./teamShellModel";
import { VButton, VSelect, VStatusChip } from "../../components/vui";

export type TeamShellToolbarOption = {
  id: string;
  label: string;
  description?: string;
};

export type TeamShellToolbarProps = {
  lang: "zh" | "en";
  teamName: string;
  purpose: string;
  /** Kept for call-site compatibility; chrome no longer exposes mode switch. */
  mode?: TeamShellMode;
  onModeChange?: (mode: TeamShellMode) => void;
  onRefresh?: () => void;
  identityClassName?: string;
  actionsClassName?: string;
  refreshButtonClassName?: string;
  switchClassName?: string;
  teamOptions?: TeamShellToolbarOption[];
  selectedTeamId?: string;
  onSelectTeamId?: (teamId: string) => void;
  kindLabel?: string;
};

/**
 * Shared Teams shell toolbar: team switcher in the header.
 * Left rail is status (next/stage/node), not the team list.
 */
export function TeamShellToolbar({
  lang,
  teamName,
  purpose,
  onRefresh,
  identityClassName = "",
  actionsClassName = "",
  refreshButtonClassName = "",
  switchClassName = "",
  teamOptions = [],
  selectedTeamId = "",
  onSelectTeamId,
  kindLabel = "",
}: TeamShellToolbarProps) {
  const fallbackName = lang === "zh" ? "暂无团队" : "No team";
  const fallbackPurpose = lang === "zh" ? "团队工作台" : "Team workbench";
  const canSwitch = teamOptions.some((item) => item.id);

  return (
    <div className={identityClassName} data-testid="team-shell-toolbar-identity">
      {canSwitch ? (
        <>
          <div className={switchClassName}>
            <VSelect
              density="compact"
              aria-label={lang === "zh" ? "切换团队" : "Switch team"}
              data-vui="team-shell-team-select"
              placeholder={lang === "zh" ? "选择团队" : "Select team"}
              selectedKey={selectedTeamId || null}
              options={teamOptions}
              onSelectionChange={(key) => {
                if (key == null) return;
                onSelectTeamId?.(String(key));
              }}
            />
          </div>
          {kindLabel ? <VStatusChip tone="accent">{kindLabel}</VStatusChip> : null}
        </>
      ) : (
        <>
          <strong>{teamName || fallbackName}</strong>
          <span>{purpose || fallbackPurpose}</span>
        </>
      )}
      {onRefresh ? (
        <div className={actionsClassName}>
          <VButton
            type="button"
            variant="ghost"
            density="compact"
            isIconOnly
            className={refreshButtonClassName}
            aria-label={lang === "zh" ? "刷新团队" : "Refresh team"}
            title={lang === "zh" ? "刷新团队" : "Refresh team"}
            icon={<RefreshCw size={14} aria-hidden="true" />}
            onClick={onRefresh}
          />
        </div>
      ) : null}
    </div>
  );
}
