import { vuiFlatPanelClass } from "../../design/vuiSurfaceRecipes";

const styles = {
  root: "inline-flex h-7 min-w-0 max-w-full items-center",
  trigger: "!inline-flex !min-h-7 !h-7 !w-auto !max-w-full !items-center !gap-1 !rounded-full !border-0 !bg-transparent !px-1.5 !py-0 !text-vui-xs !font-medium !tracking-[-0.01em] !text-[var(--fg-tertiary)] !shadow-none hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)] focus-visible:!ring-2 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] data-[open=true]:!bg-[var(--vui-control-muted)] data-[open=true]:!text-[var(--fg-primary)]",
  icon: "shrink-0 opacity-70",
  settingsIcon: "shrink-0 opacity-55",
  label: "max-w-32 min-w-0 truncate whitespace-nowrap",
  fullName: "m-0 whitespace-normal break-words text-center text-vui-sm font-medium leading-snug text-[var(--fg-primary)]",
  popover: `grid w-[min(272px,calc(100vw-16px))] gap-2.5 rounded-[18px] border border-[color-mix(in_srgb,var(--fg-primary)_22%,transparent)] ${vuiFlatPanelClass} p-3 shadow-[0_12px_32px_color-mix(in_srgb,var(--fg-primary)_12%,transparent),var(--vui-shadow-soft)]`,
  fields: "grid min-w-0 gap-3",
  field: "grid min-w-0 gap-0 text-vui-xs text-[var(--fg-secondary)] [&+&]:border-t [&+&]:border-[var(--vui-border-subtle)] [&+&]:pt-3",
  fieldHeader: "relative grid h-7 grid-cols-[28px_minmax(0,1fr)_28px] items-center justify-items-center text-[var(--fg-primary)]",
  fieldIcon: "justify-self-center text-[var(--fg-secondary)]",
  fieldValue: "text-vui-md font-semibold leading-tight tabular-nums text-[var(--fg-primary)]",
  fieldCaption: "mx-7 mb-2 truncate text-center text-vui-xs leading-normal text-[var(--fg-tertiary)]",
  resetButton: "!h-[26px] !min-h-[26px] !w-[26px] !min-w-[26px] !border-0 !bg-transparent !p-0 !text-[var(--fg-secondary)] !shadow-none",
  numberTrigger: "!h-7 !min-h-7 !w-auto !justify-self-center !border-0 !bg-transparent !px-[3px] !py-0 !text-vui-md !font-semibold !text-[var(--fg-primary)] !shadow-none tabular-nums",
  numberInput: "!h-7 !min-h-7 !w-[116px] !justify-self-center !px-[5px] !py-0 !text-center !text-vui-sm",
  error: "m-0 text-vui-xs leading-snug text-[var(--vui-status-danger-fg)]",
  actions: "flex items-center justify-end border-t border-[var(--vui-border-subtle)] pt-1.5",
  saveButton: "!h-7 !w-7 !min-w-7 !rounded-md !border-0 !bg-transparent !text-[var(--fg-tertiary)] !shadow-none hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)]",
};

export default styles;
