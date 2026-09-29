const scope = "vui-components-conversationfindbar";

function fb(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

/**
 * Find-in-transcript 覆盖条样式。挂载点为 ConversationView 的 timelineArea
 * （relative 容器）；右上角空档避开了右侧居中的轮次导航栏与右下的回底按钮。
 */
const styles = {
  host: fb(
    "host",
    "absolute right-3 top-2 z-30 flex min-w-0 max-w-[calc(100%-1.5rem)]",
  ),
  bar: fb(
    "bar",
    "flex min-w-0 items-center gap-1.5 rounded-lg border border-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)] bg-[var(--vui-surface-popover)] px-2 py-1.5 shadow-[var(--vui-shadow-soft)] backdrop-blur-[10px]",
  ),
  input: fb(
    "input",
    "min-w-0 w-52 text-vui-sm",
  ),
  count: fb(
    "count",
    "shrink-0 select-none px-0.5 text-vui-xs leading-tight tabular-nums text-[var(--fg-tertiary)]",
  ),
  divider: fb(
    "divider",
    "h-4 w-px shrink-0 bg-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)]",
  ),
} as const;

export default styles;
