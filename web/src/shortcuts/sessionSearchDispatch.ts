import type { ShortcutCommandId } from "./commands";

/** A mounted ordinary Chat index can handle search without a second dialog. */
export const SESSION_INDEX_SEARCH_EVENT = "vibelution:open-session-index-search";

export function requestSessionIndexSearch(command: ShortcutCommandId, binding = ""): boolean {
  const defaultPaletteSearch = command === "openCommandPalette"
    && ["CmdOrCtrl+k", "Ctrl+k", "Meta+k"].includes(binding);
  if (command !== "openSessionSearch" && !defaultPaletteSearch) return false;
  return !window.dispatchEvent(new Event(SESSION_INDEX_SEARCH_EVENT, { cancelable: true }));
}
