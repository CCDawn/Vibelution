/**
 * Teams shell presentation: left team rail + right content modes.
 * board = stage workspaces (experiment / iteration / KC launcher)
 * canvas = organization graph + research flow strip (end-user home)
 */

export type TeamShellMode = "board" | "canvas";

export function parseTeamShellMode(value: string | null | undefined): TeamShellMode | null {
  const raw = String(value || "").trim().toLowerCase();
  if (raw === "board" || raw === "kanban" || raw === "看板") {
    return "board";
  }
  if (raw === "canvas" || raw === "graph" || raw === "画布") {
    return "canvas";
  }
  return null;
}

export function teamShellModeLabel(mode: TeamShellMode, lang: "zh" | "en"): string {
  if (mode === "board") {
    return lang === "zh" ? "看板模式" : "Board";
  }
  return lang === "zh" ? "画布模式" : "Canvas";
}

/**
 * Map research workspace view → shell mode.
 * Overview / canvas home use the org canvas; stage destinations use board.
 */
export function teamShellModeFromResearchView(view: string | null | undefined): TeamShellMode {
  const value = String(view || "").trim();
  if (
    value === "experiment"
    || value === "iteration"
    || value === "knowledge_collection"
    || value === "source_collection"
  ) {
    return "board";
  }
  // overview, canvas, empty → end-user canvas home
  return "canvas";
}

export type TeamShellListItem = {
  teamId: string;
  name: string;
  purpose: string;
  memberCount: number;
  status: string;
  kindLabel: string;
};

export function teamShellStatusLabel(status: string, lang: "zh" | "en"): string {
  const value = String(status || "").toLowerCase();
  if (value === "active" || value === "operational") {
    return lang === "zh" ? "活跃" : "Active";
  }
  if (value === "archived") {
    return lang === "zh" ? "归档" : "Archived";
  }
  if (value === "stale") {
    return lang === "zh" ? "失效" : "Stale";
  }
  return status || (lang === "zh" ? "—" : "—");
}
