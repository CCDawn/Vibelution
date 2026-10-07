import { cliAgentRunIdFromTabId } from "./cliAgentRunModel";

export type ChatChangeRailModel = {
  show: boolean;
  paths: string[];
  selectedPath: string | null;
};

function isPreviewPath(tab: string) {
  return Boolean(tab) && tab !== "agent" && !cliAgentRunIdFromTabId(tab);
}

/**
 * Right-hand change column for a normal chat.
 * Companion, finance, and group surfaces keep their own right side.
 * The conversation stays in the center; this only chooses which file to show.
 */
export function buildChatChangeRail(input: {
  companion: boolean;
  finance: boolean;
  group: boolean;
  changedFiles: readonly string[];
  openTabs: readonly string[];
  activeTab: string;
}): ChatChangeRailModel {
  if (input.companion || input.finance || input.group) {
    return { show: false, paths: [], selectedPath: null };
  }
  const paths: string[] = [];
  const seen = new Set<string>();
  for (const raw of [...input.changedFiles, ...input.openTabs]) {
    const path = String(raw || "").replace(/\\/g, "/").trim();
    if (!isPreviewPath(path) || seen.has(path)) {
      continue;
    }
    seen.add(path);
    paths.push(path);
  }
  if (!paths.length) {
    return { show: false, paths: [], selectedPath: null };
  }
  const active = String(input.activeTab || "").replace(/\\/g, "/").trim();
  const selectedPath = isPreviewPath(active) && paths.includes(active) ? active : paths[0];
  return { show: true, paths, selectedPath };
}
