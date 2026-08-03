import { useMemo, useState } from "react";

import type { Team } from "../../api/types";
import { isChallengeCupResearchWorkflowTeam, isAiSearchScopeTeam, isKnowledgeExpansionWorkflowTeam } from "./teamKindModel";
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
    <aside
      className={[
        "teamShellRail min-w-0 flex h-full min-h-0 flex-col gap-3 overflow-hidden border-r border-[var(--vui-border-subtle)] bg-[var(--vui-surface-rail)] p-3",
        className,
      ].filter(Boolean).join(" ")}
      data-testid="team-shell-rail"
      data-vui="team-shell-rail"
      aria-label={lang === "zh" ? "团队列表" : "Team list"}
    >
      <div className="flex min-w-0 items-center justify-between gap-2 px-0.5">
        <h2 className="m-0 text-[13px] font-[760] text-[var(--fg-primary)]">
          {lang === "zh" ? "团队" : "Teams"}
        </h2>
        <span className="text-[11px] text-[var(--fg-tertiary)]">{teams.length}</span>
      </div>
      <label className="grid min-w-0 gap-1">
        <span className="sr-only">{lang === "zh" ? "搜索团队" : "Search teams"}</span>
        <input
          type="search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder={lang === "zh" ? "搜索团队…" : "Search teams…"}
          className="min-h-8 w-full rounded-lg border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2.5 text-[12.5px] text-[var(--fg-primary)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)]"
          data-testid="team-shell-search"
        />
      </label>
      <div
        className="grid min-h-0 flex-1 content-start gap-1.5 overflow-auto"
        role="listbox"
        aria-label={lang === "zh" ? "可选团队" : "Available teams"}
      >
        {filtered.length ? filtered.map(({ team, item }) => {
          const active = item.teamId === selectedTeamId;
          return (
            <button
              key={item.teamId}
              type="button"
              role="option"
              aria-selected={active}
              data-active={active ? "true" : "false"}
              data-testid={`team-shell-item-${item.teamId}`}
              className={[
                "grid min-w-0 gap-1 rounded-lg border px-2.5 py-2 text-left transition-colors",
                active
                  ? "border-[var(--fg-primary)] bg-[var(--fg-primary)] text-[var(--vui-surface-base)]"
                  : "border-transparent bg-transparent text-[var(--fg-primary)] hover:bg-[var(--vui-surface-row)]",
              ].join(" ")}
              onClick={() => onSelectTeam(team)}
            >
              <span className="flex min-w-0 items-center justify-between gap-2">
                <span className="min-w-0 truncate text-[13px] font-[720]">{item.name}</span>
                <span
                  className={[
                    "shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-[740]",
                    active
                      ? "border-[color-mix(in_srgb,var(--vui-surface-base)_35%,transparent)]"
                      : "border-[var(--vui-border-subtle)] text-[var(--fg-tertiary)]",
                  ].join(" ")}
                >
                  {item.status}
                </span>
              </span>
              <span
                className={[
                  "flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-[11px]",
                  active ? "text-[color-mix(in_srgb,var(--vui-surface-base)_78%,transparent)]" : "text-[var(--fg-tertiary)]",
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
                  active ? "text-[color-mix(in_srgb,var(--vui-surface-base)_72%,transparent)]" : "text-[var(--fg-secondary)]",
                ].join(" ")}
              >
                {item.purpose}
              </span>
            </button>
          );
        }) : (
          <p className="m-0 px-1 text-[12px] text-[var(--fg-tertiary)]">
            {lang === "zh" ? "没有匹配的团队" : "No matching teams"}
          </p>
        )}
      </div>
      <p className="m-0 px-0.5 text-[11px] leading-snug text-[var(--fg-tertiary)]">
        {lang === "zh"
          ? "左侧选团队，右侧展示整队内容。可用看板 / 画布模式。"
          : "Select a team on the left. Use board or canvas mode on the right."}
      </p>
    </aside>
  );
}
