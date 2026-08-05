/**
 * R1-c: Teams shell frame — rail, toolbar, and gate early-return surface.
 */
import type { ReactNode } from "react";

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
  gateMode: "initial-loading" | "unavailable" | "detail-unavailable";
  initialTitle: string;
  initialMessage: string;
  listMetricLoadingLabel: string;
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
  "lang" | "teamName" | "purpose" | "teamShellMode" | "onModeChange" | "onRefreshTeams" | "styles"
>): ReactNode {
  return (
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
      initialTitle={args.initialTitle}
      initialMessage={args.initialMessage}
      listMetricLoadingLabel={args.listMetricLoadingLabel}
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
