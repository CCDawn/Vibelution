const form = "grid min-w-0 gap-3 text-vui-xs leading-6 [&_p]:m-0 [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:text-vui-xs [&_[data-vui=native-button]]:w-fit [&_[data-vui=native-button]]:gap-2";
const header = "flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-vui-xs leading-6 [&_strong]:min-w-0 [&_strong]:font-semibold [&_strong]:[overflow-wrap:anywhere] [&_span]:text-vui-2xs [&_span]:font-normal [&_span]:text-[var(--fg-tertiary)]";
export default {
  recordActions: "grid min-w-0 gap-3",
  recordActionsHeading: "text-vui-xs font-medium",
  recordActionItem: "grid min-w-0 gap-2 border-b border-vui-border-subtle pb-3",
  recordActionCopy: "line-clamp-2 break-words text-vui-2xs text-vui-fg-secondary",
  recordActionEmpty: "text-vui-2xs text-vui-fg-secondary",

  researchDiscussionPanel: "grid min-w-0 gap-5 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-3 text-vui-xs leading-6 [&>section]:min-w-0 [&>section]:border-t [&>section]:border-[var(--vui-border-subtle)] [&>section]:pt-4",
  teamTaskForm: form,
  teamMessageForm: `${form} border-t border-[var(--vui-border-subtle)] pt-4`,
  sectionTitle: header,
  teamRoundHeader: header,
  teamHistoryHeader: header,
  teamRoundPanel: "grid min-w-0 gap-3 border-t border-[var(--vui-border-subtle)] pt-4",
  teamRoundCard: "grid min-w-0 gap-2 text-vui-xs leading-6 [&_p]:m-0 [&_p]:[overflow-wrap:anywhere] [&_a]:text-[var(--accent-cool)]",
  teamRoundMeta: "flex min-w-0 flex-wrap gap-x-3 gap-y-1 text-vui-2xs text-[var(--fg-tertiary)]",
  teamHistoryPanel: "grid min-w-0 gap-3",
  teamHistoryList: "grid min-w-0 gap-3",
  teamHistoryItem: "grid min-w-0 gap-2 text-vui-xs leading-6 [&_p]:m-0 [&_p]:[overflow-wrap:anywhere]",
  inlineToggle: "flex min-w-0 items-start gap-2 text-vui-2xs leading-5 [&_input]:mt-0.5 [&_input]:shrink-0",
} as const;
