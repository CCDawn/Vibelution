const quietButton =
  "!border-0 !bg-transparent !shadow-none !font-normal hover:!bg-[var(--vui-control-muted)]";
const styles = {
  root: "relative inline-flex shrink-0",
  trigger: `${quietButton} !flex !h-[30px] !min-w-0 !items-center !gap-1 !rounded-md !px-1.5 !py-0 !text-[11px] !text-[var(--accent-cool)] tabular-nums`,
  ring: "size-5 shrink-0",
  popover:
    "w-[min(324px,calc(100vw-24px))] max-h-[calc(100dvh-36px)] overflow-y-auto !rounded-xl !px-4 !pt-3.5 !pb-2",
  head: "mb-3 flex h-6 items-center justify-between gap-2",
  title: "text-[13px] font-semibold text-vui-fg-primary",
  back: `${quietButton} !flex !h-6 !items-center !gap-1.5 !p-0 !text-[12px] !font-semibold`,
  close: `${quietButton} !size-[26px] !min-w-0 !p-0 !text-[var(--fg-tertiary)]`,
  capacity:
    "flex items-baseline justify-between gap-2 text-[12px] tabular-nums [&_b]:text-[17px] [&_b]:font-semibold",
  nums: "text-[11px] text-[var(--fg-secondary)] [&_span]:text-[var(--fg-tertiary)]",
  track:
    "mt-2.5 h-1.5 overflow-hidden rounded-full bg-[var(--vui-control-muted)]",
  fill: "block h-full rounded-full bg-[var(--accent-cool)]",
  warningFill: "block h-full rounded-full bg-[var(--accent-warm)]",
  note: "mb-4 mt-2 text-[10px] leading-relaxed text-[var(--fg-tertiary)]",
  sectionTitle:
    "mb-1 flex items-center justify-between text-[10px] font-normal text-[var(--fg-tertiary)]",
  row: "flex min-h-7 items-center justify-between gap-3 text-[12px] [&_b]:font-medium [&_b]:tabular-nums",
  name: "min-w-0 flex-1 break-words text-left",
  detailRow: `${quietButton} !flex !min-h-[30px] !h-auto !w-full !items-center !gap-1.5 !px-0 !py-1 !text-[12px] [&_b]:font-medium [&_b]:tabular-nums [&_svg]:shrink-0 [&_svg]:text-[var(--fg-tertiary)]`,
  expanded: "pb-2.5 pl-[19px] text-[10px] text-[var(--fg-secondary)]",
  segment: "flex items-baseline justify-between gap-2 py-1 tabular-nums",
  preview:
    "mb-2 mt-1 max-h-24 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-[var(--vui-control-muted)] p-2 text-[10px] leading-relaxed",
  cache:
    "mt-3 flex items-center justify-between gap-3 border-t border-[var(--vui-border-subtle)] pb-2 pt-3 text-[11px]",
  cacheNext:
    "flex items-center justify-between gap-3 border-t border-[var(--vui-border-subtle)] pb-2 pt-3 text-[11px]",
  muted: "text-[var(--fg-tertiary)]",
  observed: "text-[var(--accent-cool)] tabular-nums",
  autoCompact:
    "mt-3 rounded-md border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-2.5 text-[11px]",
  autoCompactTitle:
    "flex items-center justify-between gap-2 font-medium text-[var(--accent-warm)] tabular-nums",
  autoCompactNote: "mt-1 text-[10px] leading-relaxed text-[var(--fg-tertiary)]",
  detailNote: "mb-2 text-[10px] leading-relaxed text-[var(--fg-tertiary)]",
  detailLink: `${quietButton} !flex !h-[30px] !w-full !items-center !justify-between !gap-2 !p-0 !text-[11px] !text-[var(--accent-cool)] hover:underline`,
};
export default styles;
