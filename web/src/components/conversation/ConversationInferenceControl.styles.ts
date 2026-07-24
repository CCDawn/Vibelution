import {
  vuiFlatPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  root: "relative flex min-w-0 items-center",
  fixedLabel: "inline-flex min-h-7 max-w-[220px] items-center truncate px-1.5 [font-size:var(--vui-font-xs)] font-medium tracking-[-0.01em] text-[var(--fg-tertiary)] max-[719px]:max-w-[132px]",
  // Compact trigger: sits in toolbar end next to send; model truncates first.
  trigger: "!inline-flex !min-h-7 !h-7 !w-auto !max-w-[min(240px,42vw)] !items-center !gap-1 !rounded-full !border-0 !bg-transparent !px-1.5 !py-0 ![font-size:var(--vui-font-xs)] !font-medium !tracking-[-0.01em] !text-[var(--fg-tertiary)] !shadow-none hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)] focus-visible:!ring-2 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] max-[719px]:!max-w-[min(168px,48vw)]",
  triggerModel: "min-w-0 truncate",
  triggerSeparator: "shrink-0 opacity-55",
  triggerEffort: "shrink-0 text-[var(--fg-secondary)]",
  triggerChevron: "shrink-0 opacity-70",
  // Fixed portal menu (not absolute) — escapes composer overflow-hidden clipping.
  menu: `grid w-[min(220px,calc(100vw-16px))] gap-0.5 overflow-y-auto overscroll-contain rounded-[12px] border border-[var(--vui-border-subtle)] ${vuiFlatPanelClass} p-1 shadow-[var(--vui-shadow-soft)]`,
  option: "!grid !h-auto !min-h-10 !w-full !grid-cols-[minmax(0,1fr)_1rem] !items-start !gap-x-2 !gap-y-0 !rounded-[9px] !border-0 !bg-transparent !px-2.5 !py-1.5 !text-left !shadow-none hover:!bg-[var(--vui-control-muted)] aria-selected:!bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)]",
  optionCopy: "grid min-w-0 content-start gap-0.5 py-0.5",
  optionLabel: "[font-size:var(--vui-font-sm)] font-medium leading-tight text-[var(--fg-primary)]",
  // Allow 2-line descriptions; avoid single-line truncate making rows look clipped.
  optionDescription: "line-clamp-2 whitespace-normal [font-size:var(--vui-font-xs)] leading-[1.35] text-[var(--fg-tertiary)]",
  check: "mt-1 shrink-0 text-[var(--accent-cool)]",
  checkSlot: "mt-1 block size-3.5 shrink-0",
};

export default styles;
