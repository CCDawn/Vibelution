const styles = {
  root: "min-w-0",
  workspace: "grid w-full max-w-[704px] min-w-0 content-start gap-5",
  inputPanel: "m-0 grid min-w-0 gap-5 border-0 p-0 py-4 [&_[data-vui=field-row]]:gap-1.5 [&_label]:text-vui-micro-13 [&_label]:font-semibold [&_label]:text-vui-fg-secondary",
  twoFields: "grid min-w-0 grid-cols-2 gap-4 max-[640px]:grid-cols-[minmax(0,1fr)] [&_option]:text-vui-fg-primary",
  control: "w-full min-w-0 max-w-full !h-10 !text-vui-xs ![line-height:var(--tw-leading,var(--vui-line-slot-sm))] max-[640px]:!h-11 max-[640px]:!text-vui-md max-[640px]:![line-height:var(--tw-leading,var(--vui-line-slot-base))] aria-invalid:!border-[var(--state-error)]",
  noCredential: "flex min-h-10 items-center gap-1.5 text-vui-xs [line-height:var(--tw-leading,var(--vui-line-slot-sm))] text-vui-fg-secondary",
  modelInput: "flex min-w-0 items-center gap-2 [&>input]:flex-1 [&>input]:!w-0 max-[640px]:flex-wrap max-[640px]:[&>input]:basis-full max-[640px]:[&>input]:!w-full",
  detectAction: "!min-h-10 shrink-0 max-[640px]:!min-h-11 max-[640px]:w-full",
  hint: "text-vui-xs [line-height:var(--vui-line-readable)] leading-relaxed text-vui-fg-tertiary [overflow-wrap:anywhere]",
  error: "text-vui-xs [line-height:var(--vui-line-readable)] leading-relaxed text-[var(--state-error)] [overflow-wrap:anywhere]",
  advanced: "min-w-0 border-t border-vui-border-subtle pt-1 [&>div]:pt-3",
  advancedSummary: "min-h-11 cursor-pointer py-3 text-vui-xs [line-height:var(--tw-leading,var(--vui-line-slot-sm))] font-semibold text-vui-fg-secondary",
  footer: "flex min-w-0 flex-wrap items-center justify-between gap-3 border-t border-vui-border-subtle py-4",
  feedback: "min-w-0 flex-1 text-vui-xs [line-height:var(--vui-line-readable)] leading-relaxed text-vui-fg-tertiary [overflow-wrap:anywhere] max-[640px]:basis-full",
  success: "flex flex-wrap items-center gap-x-2 gap-y-1 text-vui-fg-primary [&>svg]:shrink-0 [&>svg]:text-vui-accent-cool",
  savedModel: "font-mono text-vui-fg-secondary",
  actions: "flex min-w-0 flex-wrap justify-end gap-2 max-[640px]:w-full [&>button]:!min-h-10 max-[640px]:[&>button]:!min-h-11",
  primaryAction: "!min-h-10 justify-center px-4 max-[640px]:!min-h-11",
};

export default styles;
