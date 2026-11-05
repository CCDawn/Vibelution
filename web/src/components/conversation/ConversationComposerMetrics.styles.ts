const quietButton = "!border-0 !bg-transparent !shadow-none hover:!bg-[var(--vui-control-muted)]";

const styles = {
  root: "inline-flex shrink-0 items-center",
  trigger: `${quietButton} !size-7 !min-h-7 !min-w-7 !rounded-full !p-0 !text-[var(--fg-tertiary)] hover:!text-[var(--fg-primary)] data-[state=open]:!text-[var(--fg-primary)]`,
  popover: "w-[min(324px,calc(100vw-24px))] max-h-[min(calc(100dvh-24px),var(--radix-popover-content-available-height))] overflow-y-auto !rounded-xl !px-4 !pt-3.5 !pb-3",
  header: "mb-2 flex min-h-6 items-center justify-between gap-2 text-vui-2xs [&_strong]:font-semibold",
  close: `${quietButton} !size-[26px] !min-h-0 !min-w-0 !p-0 !text-[var(--fg-tertiary)]`,
  cacheSection: "mt-2 border-t border-[var(--vui-border-subtle)] pt-3",
  cacheTitle: "m-0 text-vui-micro-11 font-medium text-[var(--fg-secondary)]",
  rows: "mb-0 mt-1 text-vui-2xs tabular-nums [&>div]:flex [&>div]:justify-between [&>div]:gap-5 [&>div]:py-1.5 [&_dt]:text-[var(--fg-secondary)] [&_dd]:m-0 [&_dd]:font-medium",
  note: "mb-0 mt-2 text-vui-micro-11 leading-relaxed text-[var(--fg-tertiary)]",
  detailLink: `${quietButton} !mt-2 !flex !h-7 !w-full !items-center !justify-between !gap-2 !p-0 !text-vui-micro-11 !text-[var(--accent-cool)] hover:underline`,
} as const;

export default styles;
