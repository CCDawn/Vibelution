import { useEffect, useState, type KeyboardEvent, type MouseEvent } from "react";
import type { Team } from "../../api/types";
import type { TeamContextMenuState } from "../teams/TeamContextMenu";
import { eventInsideContextMenuSurface } from "./chatContextMenuDismiss";
import { loadHiddenTeamIds, saveHiddenTeamIds } from "./teamDirectoryVisibility";

export type TeamDirectoryAction = { teamId: string; mode: "rename" | "settings" | "archive" };

/** Rail-only chrome. No server mutation happens until a dialog is submitted. */
export function useTeamDirectoryManagement(teams: Team[]) {
  const [menu, setMenu] = useState<TeamContextMenuState | null>(null);
  const [action, setAction] = useState<TeamDirectoryAction | null>(null);
  const [hiddenTeamIds, setHiddenTeamIds] = useState(loadHiddenTeamIds);
  const [restoreOpen, setRestoreOpen] = useState(false);
  useEffect(() => saveHiddenTeamIds(hiddenTeamIds), [hiddenTeamIds]);

  useEffect(() => {
    if (!menu) return;
    const dismiss = (event: Event) => {
      if (!eventInsideContextMenuSurface(event.target)) setMenu(null);
    };
    const scroll = () => setMenu(null);
    window.addEventListener("pointerdown", dismiss);
    window.addEventListener("scroll", scroll, true);
    return () => {
      window.removeEventListener("pointerdown", dismiss);
      window.removeEventListener("scroll", scroll, true);
    };
  }, [menu]);

  const openMenu = (event: MouseEvent<HTMLElement> | KeyboardEvent<HTMLElement>, team: Team) => {
    event.preventDefault();
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    setMenu({
      team,
      x: "clientX" in event ? event.clientX : rect.left + 16,
      y: "clientY" in event ? event.clientY : rect.bottom,
    });
  };
  const begin = (team: Team, mode: TeamDirectoryAction["mode"]) => {
    setMenu(null);
    setAction({ teamId: team.teamId, mode });
  };
  const hiddenTeams = teams.filter((team) => hiddenTeamIds.includes(team.teamId) && team.status !== "archived");
  return {
    menu, setMenu, action, setAction, openMenu, begin, hiddenTeamIds, hiddenTeams, restoreOpen, setRestoreOpen,
    hide: (team: Team) => {
      setMenu(null);
      setHiddenTeamIds((current) => [...new Set([...current, team.teamId])]);
    },
    restore: (teamId: string) => setHiddenTeamIds((current) => current.filter((id) => id !== teamId)),
  };
}
