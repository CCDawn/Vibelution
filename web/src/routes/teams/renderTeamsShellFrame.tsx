/**
 * R1-c: Teams shell frame — rail, toolbar, and gate early-return surface.
 */
import type { ReactNode } from "react";
import { LoaderCircle } from "lucide-react";

import type { Team } from "../../api/types";
import { TeamShellStatusRail } from "./TeamShellStatusRail";
import { TeamShellToolbar } from "./TeamShellToolbar";
import { TeamsShellGateSurface } from "./TeamsShellGateSurface";
import type { TeamShellMode } from "./teamShellModel";
import type { TeamShellStatusNode, TeamShellStatusStage } from "./teamShellStatusModel";

type Lang = "zh" | "en";

export type TeamsShellFrameArgs = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  styles: Record<string, string>;
  visibleTeams: Team[];
  effectiveTeamId: string;
  onSelectTeam: (team: Team) => void;
  teamName: string;
  purpose: string;
  kindLabel?: string;
  teamShellMode: TeamShellMode;
  onModeChange: (mode: TeamShellMode) => void;
  onRefreshTeams: () => void;
  statusNextTitle: string;
  statusNextBody: string;
  statusCta?: string;
  statusCtaDisabled?: boolean;
  onStatusCta?: () => void;
  statusStages: TeamShellStatusStage[];
  statusNodes?: TeamShellStatusNode[];
  selectedNodeId?: string | null;
  onSelectNode?: (nodeId: string) => void;
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
  | "lang"
  | "statusNextTitle"
  | "statusNextBody"
  | "statusCta"
  | "statusCtaDisabled"
  | "onStatusCta"
  | "statusStages"
  | "statusNodes"
  | "selectedNodeId"
  | "onSelectNode"
>): ReactNode {
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden" data-vui-region="teams-sidebar">
      <TeamShellStatusRail
        lang={args.lang}
        nextTitle={args.statusNextTitle}
        nextBody={args.statusNextBody}
        cta={args.statusCta}
        ctaDisabled={args.statusCtaDisabled}
        onCta={args.onStatusCta}
        stages={args.statusStages}
        nodes={args.statusNodes}
        selectedNodeId={args.selectedNodeId}
        onSelectNode={args.onSelectNode}
      />
    </div>
  );
}

export function renderTeamsShellToolbar(args: Pick<
  TeamsShellFrameArgs,
  | "lang"
  | "teamName"
  | "purpose"
  | "kindLabel"
  | "teamShellMode"
  | "onModeChange"
  | "onRefreshTeams"
  | "styles"
  | "teamsFetching"
  | "visibleTeams"
  | "effectiveTeamId"
  | "onSelectTeam"
>): ReactNode {
  return (
    <div className="flex w-full min-w-0 items-center justify-between gap-3">
      <TeamShellToolbar
        lang={args.lang}
        teamName={args.teamName}
        purpose={args.purpose}
        kindLabel={args.kindLabel}
        mode={args.teamShellMode}
        onModeChange={args.onModeChange}
        onRefresh={args.onRefreshTeams}
        identityClassName={args.styles.teamShellToolbarIdentity}
        switchClassName={args.styles.teamShellToolbarSwitch}
        actionsClassName={args.styles.teamShellToolbarActions}
        refreshButtonClassName={args.styles.teamRefreshButton}
        teamOptions={args.visibleTeams.map((team) => ({
          id: team.teamId,
          label: team.name,
          description: team.purpose || team.teamId,
        }))}
        selectedTeamId={args.effectiveTeamId}
        onSelectTeamId={(teamId) => {
          const team = args.visibleTeams.find((item) => item.teamId === teamId);
          if (team) {
            args.onSelectTeam(team);
          }
        }}
      />
      {args.teamsFetching ? (
        <span
          className="flex shrink-0 items-center gap-2 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]"
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
