const styles = {
  card: "relative flex max-h-[min(72dvh,42rem)] w-full flex-col overflow-hidden !rounded-2xl border border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-card)] shadow-xs",
  form: "flex min-h-0 flex-1 flex-col gap-3 p-3",
  body: "flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain pr-1",
  title: "m-0 whitespace-pre-wrap break-words text-sm font-medium leading-6",
  answerRow: "flex w-full cursor-text items-center gap-3 rounded-xl px-3 py-2 transition-colors",
  selectedRow: "bg-[var(--vui-control-muted)]",
  idleRow: "hover:bg-[var(--vui-control-muted)]",
  number: "mt-px w-5 shrink-0 self-start text-sm font-medium leading-5 text-[var(--fg-secondary)]",
  input: "!h-auto !min-h-5 !max-h-[5lh] !min-w-0 !max-w-full !resize-none !overflow-y-auto !rounded-none !border-0 !bg-transparent !px-0 !py-0 !text-sm !font-medium !leading-5 !text-[var(--fg-primary)] ![box-shadow:none] [field-sizing:content] placeholder:!text-[var(--fg-tertiary)] focus:!bg-transparent focus:!outline-none focus:!ring-0 focus:!ring-offset-0",
  error: "m-0 px-1 text-[13px] text-[var(--vui-status-danger-fg)]",
  footer: "flex shrink-0 flex-wrap items-center justify-between gap-2 px-1",
  hint: "m-0 flex min-w-0 flex-1 items-center gap-2 text-xs leading-5 text-[var(--fg-secondary)]",
  icon: "shrink-0",
  submit: "!h-8 !min-h-8 !rounded-lg !border-[var(--fg-primary)] !bg-[var(--fg-primary)] !px-2.5 !text-sm !font-normal !text-[var(--vui-surface-card)] max-sm:!h-11 max-sm:!min-h-11",
} as const;

export default styles;
