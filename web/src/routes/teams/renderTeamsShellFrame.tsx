/**
 * R1-c: Teams shell frame — rail, toolbar, and gate early-return surface.
 */
import type { ReactNode } from "react";
import { LoaderCircle } from "lucide-react";

import { TeamShellRail } from "./TeamShellRail";
import { TeamShellToolbar } from "./TeamShellToolbar";
import { TeamsShellGateSurface } from "./TeamsShellGateSurface";
import type { TeamShellMode } from "./teamShellModel";

type Lang = "zh" | "en";

export type TeamsShellFrameArgs = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  styles: Record<string, string>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  visibleTeams: any[];
  effectiveTeamId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onSelectTeam: (team: any) => void;
  teamName: string;
  purpose: string;
  teamShellMode: TeamShellMode;
  onModeChange: (mode: TeamShellMode) => void;
  onRefreshTeams: () => void;
  // gate
  showGate: boolean;
  ariaLabel: string;
  meta: string;
  gateMode: "unavailable" | "detail-unavailable";
  unavailableTitle: string;
  unavailableMessage: string;
  unavailableDetail: string;
  listUnavailable: boolean;
  summaryUnavailableText: string;
  activeTeamCount: number | string;
  memberCount: number | string;
  teamsFetching: boolean;
  detailTitle: string;
  detailMessage: string;
  detailDetail: string;
  teamNameForDetail?: string;
  teamId: string;
  detailLoadMode: string;
  detailFetching: boolean;
  onRefreshDetail: () => void;
};

export function renderTeamsShellRail(args: Pick<
  TeamsShellFrameArgs,
  "lang" | "visibleTeams" | "effectiveTeamId" | "onSelectTeam"
>): ReactNode {
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden" data-vui-region="teams-sidebar">
      <TeamShellRail
        lang={args.lang}
        teams={args.visibleTeams}
        selectedTeamId={args.effectiveTeamId}
        onSelectTeam={args.onSelectTeam}
      />
    </div>
  );
}

export function renderTeamsShellToolbar(args: Pick<
  TeamsShellFrameArgs,
  "lang" | "teamName" | "purpose" | "teamShellMode" | "onModeChange" | "onRefreshTeams" | "styles" | "teamsFetching"
>): ReactNode {
  return (
    <div className="flex w-full min-w-0 items-center justify-between gap-3">
      <TeamShellToolbar
        lang={args.lang}
        teamName={args.teamName}
        purpose={args.purpose}
        mode={args.teamShellMode}
        onModeChange={args.onModeChange}
        onRefresh={args.onRefreshTeams}
        identityClassName={args.styles.teamShellToolbarIdentity}
        actionsClassName={args.styles.teamShellToolbarActions}
        refreshButtonClassName={args.styles.teamRefreshButton}
      />
      {args.teamsFetching ? (
        <span
          className="flex shrink-0 items-center gap-2 text-[11px] text-[var(--fg-secondary)]"
          role="status"
          aria-live="polite"
        >
          <LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          {args.lang === "zh" ? "正在刷新" : "Refreshing"}
        </span>
      ) : null}
    </div>
  );
}

/** Returns gate surface when loading/unavailable; otherwise null. */
export function renderTeamsShellGate(args: TeamsShellFrameArgs): ReactNode | null {
  if (!args.showGate) {
    return null;
  }
  return (
    <TeamsShellGateSurface
      lang={args.lang}
      styles={args.styles}
      ariaLabel={args.ariaLabel}
      meta={args.meta}
      mode={args.gateMode}
      unavailableTitle={args.unavailableTitle}
      unavailableMessage={args.unavailableMessage}
      unavailableDetail={args.unavailableDetail}
      listUnavailable={args.listUnavailable}
      summaryUnavailableText={args.summaryUnavailableText}
      activeTeamCount={args.activeTeamCount}
      memberCount={args.memberCount}
      teamsFetching={args.teamsFetching}
      onRefreshTeams={args.onRefreshTeams}
      detailTitle={args.detailTitle}
      detailMessage={args.detailMessage}
      detailDetail={args.detailDetail}
      teamName={args.teamNameForDetail}
      teamId={args.teamId}
      detailLoadMode={args.detailLoadMode}
      detailFetching={args.detailFetching}
      onRefreshDetail={args.onRefreshDetail}
    />
  );
}
