import type { TeamShellMode } from "./teamShellModel";

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
};

/**
 * Shared Teams shell toolbar: team identity only.
 * Board/canvas mode and refresh were removed for end-user density
 * (home is always flow + canvas; stage pages navigate via flow strip).
 */
export function TeamShellToolbar({
  lang,
  teamName,
  purpose,
  identityClassName = "",
}: TeamShellToolbarProps) {
  const fallbackName = lang === "zh" ? "暂无团队" : "No team";
  const fallbackPurpose = lang === "zh" ? "团队工作台" : "Team workbench";

  return (
    <div className={identityClassName} data-testid="team-shell-toolbar-identity">
      <strong>{teamName || fallbackName}</strong>
      <span>{purpose || fallbackPurpose}</span>
    </div>
  );
}
