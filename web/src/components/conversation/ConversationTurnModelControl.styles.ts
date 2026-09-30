import {
  vuiFlatPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  root: "relative flex min-w-0 max-w-full items-center",
  // Same compact toolbar footprint as the session-level inference control;
  // the override state lifts the chip onto the muted control surface with an
  // accent ring so "≠ session default" is visible without reading the label.
  trigger: "!inline-flex !min-h-7 !h-7 !w-auto !max-w-full !items-center !gap-1 !rounded-full !border-0 !bg-transparent !px-1.5 !py-0 !text-vui-xs !font-medium !tracking-[-0.01em] !text-[var(--fg-tertiary)] !shadow-none hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)] focus-visible:!ring-2 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] data-[open=true]:!bg-[var(--vui-control-muted)] data-[open=true]:!text-[var(--fg-primary)]",
  triggerOverride: "!bg-[color-mix(in_srgb,var(--accent-cool)_14%,var(--vui-control-muted))] !text-[var(--fg-primary)] !ring-1 !ring-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] hover:!bg-[color-mix(in_srgb,var(--accent-cool)_20%,var(--vui-control-muted))] data-[open=true]:!bg-[color-mix(in_srgb,var(--accent-cool)_20%,var(--vui-control-muted))]",
  triggerIcon: "shrink-0 opacity-70",
  triggerModel: "min-w-0 whitespace-nowrap",
  // "≠ session default" marker: small accent dot, never a raw color literal.
  overrideDot: "inline-block size-1.5 shrink-0 rounded-full bg-[var(--accent-cool)]",
  triggerChevron: "shrink-0 opacity-70 transition-transform duration-150 data-[open=true]:rotate-180",
  // Portaled via VPopover — escapes composer overflow-hidden.
  menu: `grid w-[min(240px,calc(100vw-16px))] max-h-[min(420px,60vh)] gap-0.5 overflow-y-auto overscroll-contain rounded-xl border border-[var(--vui-border-subtle)] ${vuiFlatPanelClass} p-1 shadow-[0_12px_32px_color-mix(in_srgb,var(--fg-primary)_12%,transparent),var(--vui-shadow-soft)]`,
  option: "!grid !h-auto !min-h-9 !w-full !grid-cols-[minmax(0,1fr)_0.875rem] !items-start !gap-x-2 !gap-y-0 !rounded-lg !border-0 !bg-transparent !px-2 !py-1.5 !text-left !shadow-none hover:!bg-[var(--vui-control-muted)] data-[selected=true]:!bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)]",
  optionCopy: "grid min-w-0 content-start gap-0.5",
  followLabel: "text-vui-sm font-semibold leading-tight text-[var(--fg-primary)]",
  optionLabel: "text-vui-sm font-semibold leading-tight text-[var(--fg-primary)]",
  optionMeta: "line-clamp-1 whitespace-nowrap text-vui-xs leading-[1.35] text-[var(--fg-tertiary)]",
  check: "mt-0.5 shrink-0 text-[var(--accent-cool)]",
  checkSlot: "mt-0.5 block size-3.5 shrink-0",
  // Reasoning-effort sub-section for the pinned model: indented quieter rows.
  effortSection: "mt-0.5 grid gap-0.5 border-t border-[var(--vui-border-subtle)] pt-1",
  effortOption: "!grid !h-auto !min-h-7 !w-full !grid-cols-[minmax(0,1fr)_0.75rem] !items-center !gap-x-2 !rounded-md !border-0 !bg-transparent !px-2 !py-1 !pl-4 !text-left !shadow-none hover:!bg-[var(--vui-control-muted)] data-[selected=true]:!bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)]",
  effortLabel: "min-w-0 truncate text-vui-xs font-medium text-[var(--fg-secondary)]",
  checkSlotSmall: "block size-3 shrink-0",
};

export default styles;
