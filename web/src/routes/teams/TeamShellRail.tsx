import { useId, useMemo, useRef, useState } from "react";

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
  const listboxId = useId();
  // WAI-ARIA listbox: focus stays on the container; options are tabbable=-1 and
  // tracked via aria-activedescendant. keyboardActiveId is null until the user
  // navigates; then the selected team (or first row) is the effective active one.
  const [keyboardActiveId, setKeyboardActiveId] = useState<string | null>(null);
  const [listboxFocused, setListboxFocused] = useState(false);
  const optionRefs = useRef(new Map<string, HTMLButtonElement>());
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

  const optionIdFor = (teamId: string) => `${listboxId}-option-${teamId}`;
  const effectiveActiveTeamId = useMemo(() => {
    if (!filtered.length) {
      return null;
    }
    if (keyboardActiveId && filtered.some(({ item }) => item.teamId === keyboardActiveId)) {
      return keyboardActiveId;
    }
    if (filtered.some(({ item }) => item.teamId === selectedTeamId)) {
      return selectedTeamId;
    }
    return filtered[0].item.teamId;
  }, [filtered, keyboardActiveId, selectedTeamId]);

  const onListboxKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!filtered.length) {
      return;
    }
    const currentIndex = filtered.findIndex(({ item }) => item.teamId === effectiveActiveTeamId);
    const current = currentIndex >= 0 ? currentIndex : 0;
    let next = current;
    switch (event.key) {
      case "ArrowDown":
        next = Math.min(current + 1, filtered.length - 1);
        break;
      case "ArrowUp":
        next = Math.max(current - 1, 0);
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = filtered.length - 1;
        break;
      case "Enter":
      case " ": {
        event.preventDefault();
        const target = filtered[current];
        if (target) {
          setKeyboardActiveId(target.item.teamId);
          onSelectTeam(target.team);
        }
        return;
      }
      default:
        return;
    }
    event.preventDefault();
    if (next !== current) {
      const target = filtered[next];
      setKeyboardActiveId(target.item.teamId);
      optionRefs.current.get(target.item.teamId)?.scrollIntoView?.({ block: "nearest" });
    }
  };

  return (
    <VSurface
      as="aside"
      tone="rail"
      elevation="flat"
      padding="compact"
      className={[
        // Fill split-sidebar height (shadcn sidebar pattern: h-full + min-h-0 chain).
        "teamShellRail flex h-full min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-hidden",
        className,
      ].filter(Boolean).join(" ")}
      data-testid="team-shell-rail"
      data-vui="team-shell-rail"
      data-vui-region="teams-sidebar"
      aria-label={lang === "zh" ? "团队列表" : "Team list"}
    >
      <div className="flex min-w-0 items-center justify-between gap-2 px-0.5">
        <h2 className="m-0 [font-size:var(--vui-font-xs)] font-[760] text-[var(--fg-primary)]">
          {lang === "zh" ? "团队" : "Teams"}
        </h2>
        <span className="[font-size:var(--vui-font-2xs)] text-[var(--fg-tertiary)]">{teams.length}</span>
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
        className="grid min-h-0 flex-1 content-start gap-1.5 overflow-auto rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:[box-shadow:var(--focus-ring)]"
        role="listbox"
        tabIndex={0}
        aria-label={lang === "zh" ? "可选团队" : "Available teams"}
        aria-activedescendant={effectiveActiveTeamId ? optionIdFor(effectiveActiveTeamId) : undefined}
        onKeyDown={onListboxKeyDown}
        onFocus={() => setListboxFocused(true)}
        onBlur={() => setListboxFocused(false)}
      >
        {filtered.length ? filtered.map(({ team, item }) => {
          const active = item.teamId === selectedTeamId;
          const keyboardActive = listboxFocused && !active && item.teamId === effectiveActiveTeamId;
          return (
            <VNativeButton
              key={item.teamId}
              ref={(node) => {
                if (node) {
                  optionRefs.current.set(item.teamId, node);
                } else {
                  optionRefs.current.delete(item.teamId);
                }
              }}
              id={optionIdFor(item.teamId)}
              type="button"
              role="option"
              tabIndex={-1}
              aria-selected={active}
              data-active={active ? "true" : "false"}
              data-keyboard-active={keyboardActive ? "true" : undefined}
              data-testid={`team-shell-item-${item.teamId}`}
              className={[
                // Multi-line team card; selected = muted surface + accent edge (not full ink fill).
                "!grid h-auto min-h-[4.5rem] w-full min-w-0 gap-1 rounded-lg border px-2.5 py-2 text-left !whitespace-normal",
                active
                  ? "!border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] !bg-[var(--vui-surface-row)] !text-[var(--fg-primary)] shadow-[inset_3px_0_0_0_var(--fg-primary)]"
                  : keyboardActive
                    ? "!border-transparent !bg-[var(--vui-surface-row)] !text-[var(--fg-primary)]"
                    : "!border-transparent !bg-transparent !text-[var(--fg-primary)] hover:!bg-[var(--vui-surface-row)]",
              ].join(" ")}
              onClick={() => {
                setKeyboardActiveId(item.teamId);
                onSelectTeam(team);
              }}
            >
              <span className="flex min-w-0 items-center justify-between gap-2">
                <span className="min-w-0 truncate [font-size:var(--vui-font-xs)] font-[720]">{item.name}</span>
                <VChip>
                  {item.status}
                </VChip>
              </span>
              <span
                className={[
                  "flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 [font-size:var(--vui-font-2xs)]",
                  active ? "text-[var(--fg-secondary)]" : "text-[var(--fg-tertiary)]",
                ].join(" ")}
              >
                <span>{item.kindLabel}</span>
                <span>
                  {item.memberCount} {lang === "zh" ? "成员" : "members"}
                </span>
              </span>
              <span className="line-clamp-2 [font-size:var(--vui-font-2xs)] leading-snug text-[var(--fg-secondary)]">
                {item.purpose}
              </span>
            </VNativeButton>
          );
        }) : (
          <p className="m-0 px-1 [font-size:var(--vui-font-2xs)] text-[var(--fg-tertiary)]">
            {lang === "zh" ? "没有匹配的团队" : "No matching teams"}
          </p>
        )}
      </div>
    </VSurface>
  );
}
