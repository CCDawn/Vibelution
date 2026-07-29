const scope = "vui-components-conversation-process-disclosure";

function cx(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  disclosure: cx("disclosure", "min-w-0"),
  summary: cx(
    "summary",
    "flex min-h-8 w-full cursor-pointer items-center justify-start gap-1 border-b border-[var(--vui-border-subtle)] pb-2 pt-1 text-left [font-size:var(--vui-font-sm)] leading-5 text-[var(--fg-tertiary)] [&::-webkit-details-marker]:hidden hover:text-[var(--fg-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] focus-visible:ring-inset",
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
  row: cx(
    "row",
    "min-w-0 transition-[opacity,transform] duration-150 ease-out motion-reduce:transition-none",
  ),
  rowExpanded: cx("row-expanded", "translate-y-0 opacity-100"),
  rowCollapsed: cx("row-collapsed", "-translate-y-1 opacity-0"),
} as const;

export default styles;
