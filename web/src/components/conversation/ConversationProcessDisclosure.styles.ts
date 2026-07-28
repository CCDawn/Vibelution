const scope = "vui-components-conversation-process-disclosure";

function cx(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  disclosure: cx("disclosure", "group min-w-0"),
  summary: cx(
    "summary",
    "flex min-h-7 w-full cursor-pointer items-center justify-start gap-1 py-1 text-left [font-size:var(--vui-font-xs)] leading-5 text-[var(--fg-tertiary)] [&::-webkit-details-marker]:hidden hover:text-[var(--fg-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] focus-visible:ring-inset",
  ),
  chevron: cx(
    "chevron",
    "shrink-0 text-[var(--fg-tertiary)] transition-transform duration-150 group-open:rotate-90",
  ),
  content: cx(
    "content",
    "ml-2 grid min-w-0 content-start gap-0 border-l border-[var(--vui-border-subtle)] pb-1 pl-4 pt-2",
  ),
} as const;

export default styles;
