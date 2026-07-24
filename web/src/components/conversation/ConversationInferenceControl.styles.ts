import {
  vuiFlatPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  root: "relative flex min-w-0 max-w-full items-center",
  fixedLabel: "inline-flex min-h-7 max-w-[200px] items-center truncate px-1.5 [font-size:var(--vui-font-xs)] font-medium tracking-[-0.01em] text-[var(--fg-tertiary)] max-[719px]:max-w-[120px]",
  // Compact trigger: model truncates first; effort + chevron stay visible next to send.
  trigger: "!inline-flex !min-h-7 !h-7 !w-auto !max-w-[min(200px,38vw)] !items-center !gap-1 !rounded-full !border-0 !bg-transparent !px-1.5 !py-0 ![font-size:var(--vui-font-xs)] !font-medium !tracking-[-0.01em] !text-[var(--fg-tertiary)] !shadow-none hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)] focus-visible:!ring-2 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] data-[open=true]:!bg-[var(--vui-control-muted)] data-[open=true]:!text-[var(--fg-primary)] max-[719px]:!max-w-[min(148px,44vw)]",
  triggerModel: "min-w-0 truncate",
  triggerSeparator: "shrink-0 opacity-55",
  triggerEffort: "shrink-0 font-semibold text-[var(--fg-secondary)]",
  triggerChevron: "shrink-0 opacity-70 transition-transform duration-150 data-[open=true]:rotate-180",
  // Fixed portal menu — escapes composer overflow-hidden; width matches short zh labels.
  menu: `grid w-[min(200px,calc(100vw-16px))] gap-0.5 overflow-y-auto overscroll-contain rounded-[12px] border border-[var(--vui-border-subtle)] ${vuiFlatPanelClass} p-1 shadow-[0_12px_32px_color-mix(in_srgb,var(--fg-primary)_12%,transparent),var(--vui-shadow-soft)]`,
  option: "!grid !h-auto !min-h-9 !w-full !grid-cols-[minmax(0,1fr)_0.875rem] !items-start !gap-x-2 !gap-y-0 !rounded-[8px] !border-0 !bg-transparent !px-2 !py-1.5 !text-left !shadow-none hover:!bg-[var(--vui-control-muted)] data-[selected=true]:!bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)]",
  optionCopy: "grid min-w-0 content-start gap-0.5",
  optionLabel: "[font-size:var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-primary)]",
  optionDescription: "line-clamp-2 whitespace-normal [font-size:var(--vui-font-xs)] leading-[1.35] text-[var(--fg-tertiary)]",
  check: "mt-0.5 shrink-0 text-[var(--accent-cool)]",
  checkSlot: "mt-0.5 block size-3.5 shrink-0",
};

export default styles;
