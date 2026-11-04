const quiet = "!border-0 !bg-transparent !shadow-none !font-normal hover:!bg-[var(--vui-control-muted)]";
const styles = {
  trigger: `${quiet} !inline-flex !h-[var(--vui-control-height-sm)] !min-w-0 !items-center !gap-1 !rounded-md !px-1.5 !py-0 !text-vui-micro-11 !text-[var(--accent-cool)] tabular-nums max-sm:!min-h-11`,
  partial: "text-vui-micro-10 text-[var(--fg-secondary)]",
  popover: "w-[min(224px,calc(100vw-24px))] max-h-[min(calc(100dvh-24px),var(--radix-popover-content-available-height))] overflow-y-auto !rounded-lg !px-3 !py-2.5",
  header: "sticky top-0 z-[1] flex items-center justify-between gap-2 bg-[var(--vui-surface-panel)] text-vui-2xs [&_strong]:font-medium",
  close: `${quiet} !size-[26px] !min-w-0 !p-0 max-sm:!size-11`,
  rows: "mt-1 text-vui-2xs tabular-nums [&>div]:flex [&>div]:justify-between [&>div]:gap-5 [&>div]:py-1.5 [&_dt]:text-[var(--fg-secondary)] [&_dd]:m-0 [&_dd]:font-medium",
  status: "mb-0 mt-2 text-vui-micro-11 leading-relaxed text-[var(--fg-tertiary)]",
} as const;
export default styles;
