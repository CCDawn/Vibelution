const scope = "vui-components-conversationrunningtasks";

function cv(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

/**
 * In-timeline strip for background runtime tasks owned by the current session.
 * Visual vocabulary mirrors ConversationActiveTurnStatusNote (left rule, muted
 * meta line, compact spinner) so tail-of-timeline status rows read as one family.
 */
const styles = {
  root: cv(
    "root",
    "min-w-0 max-w-[min(100%,920px)] border-l border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] bg-transparent py-1 pl-2.5 text-vui-sm leading-tight text-[var(--fg-secondary)]",
  ),
  list: cv("list", "min-w-0 flex flex-col gap-0.5"),
  row: cv("row", "min-w-0 flex flex-wrap items-center gap-x-2 gap-y-1"),
  spinner: cv("spinner", "shrink-0 animate-spin text-[var(--accent-cool)]"),
  kindChip: cv("kindChip", "shrink-0"),
  title: cv(
    "title",
    "min-w-0 max-w-[min(100%,44ch)] truncate text-vui-sm text-[var(--fg-secondary)]",
  ),
  elapsed: cv("elapsed", "shrink-0 tabular-nums text-[var(--fg-tertiary)]"),
  actions: cv("actions", "ml-auto inline-flex shrink-0 items-center gap-1"),
  openLink: cv("openLink", "shrink-0"),
  stopButton: cv("stopButton", "shrink-0"),
  // Ended directory footer row (ZCode EndedDirectoryRow shape): neutral icon,
  // "已结束 · N" meta text and a trailing chevron, one quiet link to /aux.
  endedRow: cv(
    "endedRow",
    "mt-0.5 flex w-full min-w-0 items-center gap-1.5 text-left text-vui-sm text-[var(--fg-tertiary)] hover:text-[var(--fg-secondary)]",
  ),
  endedIcon: cv("endedIcon", "shrink-0"),
  endedLabel: cv("endedLabel", "min-w-0 truncate"),
  endedChevron: cv("endedChevron", "ml-auto shrink-0"),
} as const;

export default styles;
