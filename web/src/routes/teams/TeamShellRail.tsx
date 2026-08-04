import { useMemo, useState } from "react";

import type { Team } from "../../api/types";
import { VChip, VInput, VNativeButton, VSurface } from "../../components/vui";
import {
  isAiSearchScopeTeam,
  isChallengeCupResearchWorkflowTeam,
  isKnowledgeExpansionWorkflowTeam,
} from "./teamKindModel";
import { teamShellStatusLabel, type TeamShellListItem } from "./teamShellModel";

export type TeamShellRailProps = {
  lang: "zh" | "en";
  teams: Team[];
  selectedTeamId: string;
  onSelectTeam: (team: Team) => void;
  className?: string;
};

function kindLabelForTeam(team: Team, lang: "zh" | "en"): string {
  if (isChallengeCupResearchWorkflowTeam(team)) {
    return lang === "zh" ? "科研工作流" : "Research workflow";
  }
  if (isAiSearchScopeTeam(team)) {
    return lang === "zh" ? "资料范围" : "Search scope";
  }
  if (isKnowledgeExpansionWorkflowTeam(team)) {
    return lang === "zh" ? "知识扩充" : "Knowledge expand";
  }
  return lang === "zh" ? "团队" : "Team";
}

function toListItem(team: Team, lang: "zh" | "en"): TeamShellListItem {
  return {
    teamId: team.teamId,
    name: team.name,
    purpose: team.purpose || team.teamId,
    memberCount: team.memberCount ?? team.members?.length ?? 0,
    status: teamShellStatusLabel(team.status, lang),
    kindLabel: kindLabelForTeam(team, lang),
  };
}

/**
 * Left rail: select a team, then the right pane shows full team content.
 * VUI controls only — width ownership stays with VSplitWorkspace + layoutId.
 */
export function TeamShellRail({
  lang,
  teams,
  selectedTeamId,
  onSelectTeam,
  className = "",
}: TeamShellRailProps) {
  const [filter, setFilter] = useState("");
  const items = useMemo(
    () => teams.map((team) => ({ team, item: toListItem(team, lang) })),
    [lang, teams],
  );
  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) {
      return items;
    }
    return items.filter(({ item }) =>
      [item.name, item.purpose, item.kindLabel, item.status].join(" ").toLowerCase().includes(q),
    );
  }, [filter, items]);

  return (
    <VSurface
      as="aside"
      tone="rail"
      elevation="flat"
      padding="compact"
      className={[
        "teamShellRail flex h-full min-h-0 min-w-0 flex-col gap-3 overflow-hidden",
        className,
      ].filter(Boolean).join(" ")}
      data-testid="team-shell-rail"
      data-vui="team-shell-rail"
      data-vui-region="teams-sidebar"
      aria-label={lang === "zh" ? "团队列表" : "Team list"}
    >
      <div className="flex min-w-0 items-center justify-between gap-2 px-0.5">
        <h2 className="m-0 text-[13px] font-[760] text-[var(--fg-primary)]">
          {lang === "zh" ? "团队" : "Teams"}
        </h2>
        <span className="text-[11px] text-[var(--fg-tertiary)]">{teams.length}</span>
      </div>
      <VInput
        type="search"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
        placeholder={lang === "zh" ? "搜索团队…" : "Search teams…"}
        aria-label={lang === "zh" ? "搜索团队" : "Search teams"}
        data-testid="team-shell-search"
      />
      <div
        className="grid min-h-0 flex-1 content-start gap-1.5 overflow-auto"
        role="listbox"
        aria-label={lang === "zh" ? "可选团队" : "Available teams"}
      >
        {filtered.length ? filtered.map(({ team, item }) => {
          const active = item.teamId === selectedTeamId;
          return (
            <VNativeButton
              key={item.teamId}
              type="button"
              role="option"
              aria-selected={active}
              data-active={active ? "true" : "false"}
              data-testid={`team-shell-item-${item.teamId}`}
              className={[
                // Multi-line team card: never collapse into an empty ink slab.
                "!grid h-auto min-h-[4.5rem] w-full min-w-0 gap-1 rounded-lg border px-2.5 py-2 text-left !whitespace-normal",
                active
                  // Selected = ink fill + forced light text (token surface-base can fail as dark-on-dark).
                  ? "!border-[var(--fg-primary)] !bg-[var(--fg-primary)] !text-white [&_*]:!text-white"
                  : "!border-transparent !bg-transparent !text-[var(--fg-primary)] hover:!bg-[var(--vui-surface-row)]",
              ].join(" ")}
              onClick={() => onSelectTeam(team)}
            >
              <span className="flex min-w-0 items-center justify-between gap-2">
                <span className="min-w-0 truncate text-[13px] font-[720]">{item.name}</span>
                <VChip
                  className={
                    active
                      ? "!border-white/35 !bg-transparent !text-white"
                      : undefined
                  }
                >
                  {item.status}
                </VChip>
              </span>
              <span
                className={[
                  "flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-[11px]",
                  active ? "!text-white/80" : "text-[var(--fg-tertiary)]",
                ].join(" ")}
              >
                <span>{item.kindLabel}</span>
                <span>
                  {item.memberCount} {lang === "zh" ? "成员" : "members"}
                </span>
              </span>
              <span
                className={[
                  "line-clamp-2 text-[11px] leading-snug",
                  active ? "!text-white/75" : "text-[var(--fg-secondary)]",
                ].join(" ")}
              >
                {item.purpose}
              </span>
            </VNativeButton>
          );
        }) : (
          <p className="m-0 px-1 text-[12px] text-[var(--fg-tertiary)]">
            {lang === "zh" ? "没有匹配的团队" : "No matching teams"}
          </p>
        )}
      </div>
      <p className="m-0 px-0.5 text-[11px] leading-snug text-[var(--fg-tertiary)]">
        {lang === "zh"
          ? "左侧选团队，右侧展示整队内容。拖拽分隔条可调整宽度。"
          : "Select a team on the left. Drag the separator to resize."}
      </p>
    </VSurface>
  );
}
