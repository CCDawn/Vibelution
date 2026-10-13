import { vuiFlatPanelClass } from "../../design/vuiSurfaceRecipes";

const styles = {
  root: "inline-flex h-7 min-w-0 max-w-full items-center",
  trigger: "!inline-flex !min-h-7 !h-7 !w-auto !max-w-full !items-center !gap-1 !rounded-full !border-0 !bg-transparent !px-1.5 !py-0 !text-vui-xs !font-medium !tracking-[-0.01em] !text-[var(--fg-tertiary)] !shadow-none hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)] focus-visible:!ring-2 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] data-[open=true]:!bg-[var(--vui-control-muted)] data-[open=true]:!text-[var(--fg-primary)]",
  icon: "shrink-0 opacity-70",
  settingsIcon: "shrink-0 opacity-55",
  label: "max-w-32 min-w-0 truncate whitespace-nowrap",
  popover: `grid w-[min(272px,calc(100vw-16px))] gap-2.5 rounded-xl border border-[var(--vui-border-subtle)] ${vuiFlatPanelClass} p-3 shadow-[0_12px_32px_color-mix(in_srgb,var(--fg-primary)_12%,transparent),var(--vui-shadow-soft)]`,
  fields: "grid min-w-0 gap-3",
  field: "grid min-w-0 gap-1.5 text-vui-xs text-[var(--fg-secondary)]",
  fieldHeader: "flex min-w-0 items-center justify-between gap-2 font-medium",
  fieldLimit: "shrink-0 text-vui-2xs font-normal tabular-nums text-[var(--fg-tertiary)]",
  inputRow: "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2",
  unit: "text-vui-2xs text-[var(--fg-tertiary)]",
  error: "m-0 text-vui-xs leading-snug text-[var(--vui-status-danger-fg)]",
  actions: "flex items-center justify-end border-t border-[var(--vui-border-subtle)] pt-1.5",
  saveButton: "!h-7 !w-7 !min-w-7 !rounded-md !border-0 !bg-transparent !text-[var(--fg-tertiary)] !shadow-none hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)]",
};

export default styles;
