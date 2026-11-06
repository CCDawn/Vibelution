const scope = "vui-components-conversation-process-disclosure";

function cx(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  flow: cx("flow", "grid min-w-0 content-start gap-2"),
  flowContent: cx("flow-content", "grid min-w-0 content-start gap-1"),
  flowWorkContent: cx("flow-work-content", "min-w-0"),
  flowStatusRow: cx("flow-status-row", "flex min-w-0 items-center py-1 text-vui-xs text-[var(--fg-tertiary)]"),
  flowStatusIcon: cx("flow-status-icon", "shrink-0"),
  flowWorkToggle: cx("flow-work-toggle", "!inline-flex !h-auto !min-h-0 !min-w-0 !justify-start !gap-2 !rounded-none !border-0 !bg-transparent !bg-none !p-0 !text-left !shadow-none !text-vui-xs !leading-[1.4] !font-normal text-[var(--fg-tertiary)] hover:!bg-transparent hover:!bg-none hover:text-[var(--fg-secondary)]"),
  progress: cx("progress", "min-w-0 py-1 text-[var(--fg-primary)]"),
  progressBody: cx("progress-body", "min-w-0 break-words"),
  progressPlainText: cx("progress-plain-text", "whitespace-pre-wrap"),
  disclosure: cx("disclosure", "min-w-0"),
  summary: cx(
    "summary",
    // list-none: prevent native details "›" leaking under the process label.
    "flex min-h-8 w-full list-none cursor-pointer items-center justify-start gap-1 border-0 pb-1.5 pt-1 text-left text-vui-sm leading-5 text-[var(--fg-tertiary)] [&::-webkit-details-marker]:hidden [&::marker]:hidden [&::marker]:content-none hover:text-[var(--fg-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] focus-visible:ring-inset",
  ),
  chevron: cx(
    "chevron",
    "shrink-0 text-[var(--fg-tertiary)] transition-transform duration-200 motion-reduce:transition-none",
  ),
  chevronExpanded: cx("chevron-expanded", "rotate-90"),
  contentMotion: cx(
    "content-motion",
    "grid min-w-0 transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none [overflow-anchor:none]",
  ),
  contentMotionExpanded: cx("content-motion-expanded", "grid-rows-[1fr] opacity-100"),
  contentMotionCollapsed: cx("content-motion-collapsed", "grid-rows-[0fr] opacity-0"),
  contentClip: cx("content-clip", "min-h-0 overflow-hidden"),
  content: cx(
    "content",
    "grid min-w-0 content-start gap-0 pb-1 pt-3",
  ),
  // Expanded-tail line: what the worked time is made of (ZCode parity).
  workBreakdown: cx(
    "work-breakdown",
    "min-w-0 pt-1 text-vui-xs text-[var(--fg-tertiary)]",
  ),
  row: cx(
    "row",
    "min-w-0 transition-[opacity,transform] duration-150 ease-out motion-reduce:transition-none",
  ),
  rowExpanded: cx("row-expanded", "translate-y-0 opacity-100"),
  rowCollapsed: cx("row-collapsed", "-translate-y-1 opacity-0"),
} as const;

export default styles;
