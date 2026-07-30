import { vuiFlatPanelClass } from "../../../../design/vuiSurfaceRecipes";

const styles = {
  root: "relative flex min-w-0 items-center",
  trigger:
    "!inline-flex !min-h-7 !h-7 !w-auto !max-w-[min(180px,44vw)] !items-center !gap-1 !rounded-full !border-0 !bg-transparent !px-1.5 !py-0 ![font-size:var(--vui-font-xs)] !font-semibold !tracking-[-0.01em] !text-[var(--fg-tertiary)] !shadow-none hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)] focus-visible:!ring-2 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] data-[open=true]:!bg-[var(--vui-control-muted)] data-[open=true]:!text-[var(--fg-primary)] data-[preset=full_access]:!text-[var(--state-warning)]",
  triggerSettings:
    "!min-h-9 !h-auto !w-full !max-w-none !justify-between !rounded-[var(--radius-control)] !border !border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-row)] !px-2.5 !py-1.5 !text-left",
  triggerIcon: "size-3.5 shrink-0",
  triggerLabel: "min-w-0 truncate",
  triggerChevron:
    "size-3.5 shrink-0 opacity-70 transition-transform duration-150 data-[open=true]:rotate-180",
  menu:
    `grid w-[min(360px,calc(100vw-16px))] gap-0.5 overflow-y-auto overscroll-contain rounded-[12px] border border-[var(--vui-border-subtle)] ${vuiFlatPanelClass} p-1 shadow-[0_14px_36px_color-mix(in_srgb,var(--fg-primary)_14%,transparent),var(--vui-shadow-soft)]`,
  menuHeader:
    "flex items-center justify-between gap-3 px-2 py-1 [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  option:
    "!grid !h-auto !min-h-12 !w-full !grid-cols-[1rem_minmax(0,1fr)_0.875rem] !items-start !gap-x-2 !rounded-[8px] !border-0 !bg-transparent !px-2 !py-2 !text-left !shadow-none hover:!bg-[var(--vui-control-muted)] data-[selected=true]:!bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] data-[preset=full_access]:[&_svg]:text-[var(--state-warning)]",
  optionIcon: "mt-0.5 size-4 shrink-0 text-[var(--fg-tertiary)]",
  optionCopy: "grid min-w-0 gap-0.5",
  optionLabel: "[font-size:var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-primary)]",
  optionDescription:
    "whitespace-normal [font-size:var(--vui-font-xs)] leading-[1.4] text-[var(--fg-tertiary)]",
  check: "mt-0.5 size-3.5 shrink-0 text-[var(--accent-cool)]",
  checkSlot: "mt-0.5 block size-3.5 shrink-0",
};

export default styles;
