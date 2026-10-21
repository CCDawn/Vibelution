const styles = {
  button: "shrink-0 whitespace-nowrap tabular-nums",
  runningIcon: "animate-spin motion-reduce:animate-none",
  pausedLabel: "ml-1.5 hidden text-[var(--fg-tertiary)] min-[480px]:inline",
  popover: [
    "!min-w-0 w-[344px] !max-w-[calc(100vw-24px)] !rounded-[var(--vui-workbench-radius)] p-3",
    "max-h-[min(70dvh,520px)] overflow-y-auto overscroll-contain [overflow-wrap:anywhere]",
    "[&_.vui-components-conversationtodochecklist.card]:border-0 [&_.vui-components-conversationtodochecklist.card]:p-0",
  ].join(" "),
} as const;

export default styles;
