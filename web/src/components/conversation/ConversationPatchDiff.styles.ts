const scope = "vui-components-conversation-patch-diff";

const styles = {
  root:
    `${scope} root grid min-w-0 max-w-full overflow-hidden rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)]`,
  file: `${scope} file min-w-0 max-w-full [&:not(:first-child)]:border-t [&:not(:first-child)]:border-[var(--vui-border-subtle)]`,
  fileHeader:
    `${scope} fileHeader flex min-w-0 max-w-full items-baseline gap-x-2 bg-[var(--vui-surface-raised)] px-3 py-1.5 [font-size:var(--vui-font-xs)]`,
  filePath:
    `${scope} filePath min-w-0 max-w-full truncate font-[var(--font-mono)] text-[var(--fg-secondary)]`,
  fileOp:
    `${scope} fileOp shrink-0 font-medium text-[var(--fg-tertiary)]`,
  fileMoveTo:
    `${scope} fileMoveTo min-w-0 max-w-full truncate font-[var(--font-mono)] text-[var(--fg-tertiary)]`,
  diffStat:
    `${scope} diffStat ml-auto shrink-0 tabular-nums text-[var(--fg-tertiary)]`,
  diffStatAdd: `${scope} diffStatAdd text-[var(--state-success)]`,
  diffStatDel: `${scope} diffStatDel text-[var(--state-error)]`,
  lines: `${scope} lines m-0 min-w-0 max-w-full py-1 font-[var(--font-mono)] [font-size:var(--vui-font-xs)] leading-[1.55]`,
  line: `${scope} line grid min-w-0 max-w-full grid-cols-[auto_auto_minmax(0,1fr)] gap-x-2 px-3 [overflow-wrap:anywhere]`,
  lineNumber:
    `${scope} lineNumber shrink-0 select-none text-right tabular-nums text-[color-mix(in_srgb,var(--fg-tertiary)_62%,transparent)]`,
  lineSign: `${scope} lineSign shrink-0 select-none text-[var(--fg-tertiary)]`,
  lineText: `${scope} lineText min-w-0 whitespace-pre-wrap`,
  line_add:
    `${scope} lineAdd bg-[color-mix(in_srgb,var(--state-success)_9%,var(--vui-surface-panel))] text-[var(--fg-primary)]`,
  line_del:
    `${scope} lineDel bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-panel))] text-[var(--fg-secondary)]`,
  line_context: `${scope} lineContext text-[var(--fg-secondary)]`,
  line_hunk:
    `${scope} lineHunk bg-[var(--vui-surface-raised)] text-[var(--fg-tertiary)]`,
  line_add_sign: `${scope} lineSignAdd text-[var(--state-success)]`,
  line_del_sign: `${scope} lineSignDel text-[var(--state-error)]`,
  overflow: `${scope} overflow border-t border-[var(--vui-border-subtle)]`,
  overflowSummary:
    `${scope} overflowSummary flex w-full list-none cursor-pointer items-center gap-x-1.5 px-3 py-1.5 text-left [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)] [&::-webkit-details-marker]:hidden [&::marker]:hidden [&::marker]:content-none hover:text-[var(--fg-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]`,
  truncated:
    `${scope} truncated border-t border-[var(--vui-border-subtle)] px-3 py-1.5 text-[var(--fg-tertiary)]`,
} as const;

export default styles;
