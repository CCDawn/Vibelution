import { type ReactNode } from "react";

import { VNativeButton } from "../../index";

export type TeamSourceFilterOption = {
  key: string;
  label: ReactNode;
  count: ReactNode;
  selected: boolean;
};

export type TeamSourceFilterBarProps = {
  ariaLabel: string;
  options: TeamSourceFilterOption[];
  onSelect: (key: string) => void;
};

const BAR = "flex min-w-0 gap-[5px] overflow-x-auto pb-px";

const CHIP_BASE =
  "inline-flex min-w-[76px] min-h-[28px] flex-none items-center justify-between gap-2 px-2 rounded-[7px] border cursor-pointer " +
  "text-[0.64rem] font-[820] bg-[color:var(--source-workbench-card)] " +
  "border-[var(--border-soft)] text-[var(--fg-muted)] " +
  "hover:border-[color:color-mix(in_srgb,var(--accent-primary)_48%,var(--border-soft))] hover:bg-[color:color-mix(in_srgb,var(--accent-primary)_9%,var(--surface-card))] hover:text-[var(--fg-primary)] " +
  "focus-visible:outline-none focus-visible:border-[color:color-mix(in_srgb,var(--accent-primary)_48%,var(--border-soft))] focus-visible:bg-[color:color-mix(in_srgb,var(--accent-primary)_9%,var(--surface-card))] focus-visible:text-[var(--fg-primary)]";

const CHIP_ACTIVE =
  "border-[color:color-mix(in_srgb,var(--accent-primary)_48%,var(--border-soft))] bg-[color:color-mix(in_srgb,var(--accent-primary)_9%,var(--surface-card))] text-[var(--fg-primary)]";

const CHIP_COUNT = "text-[var(--fg-primary)] text-[0.68rem]";

/**
 * Faithful reproduction of `.sourceCollectionFilterBar`: a horizontally
 * scrollable row of compact filter chips (label + count) with an accent-tinted
 * active state.
 */
export function TeamSourceFilterBar({ ariaLabel, options, onSelect }: TeamSourceFilterBarProps) {
  return (
    <div data-vui-product="team-source-filter-bar" className={BAR} aria-label={ariaLabel}>
      {options.map((option) => (
        <VNativeButton
          key={option.key}
          type="button"
          className={[CHIP_BASE, option.selected ? CHIP_ACTIVE : ""].filter(Boolean).join(" ")}
          onClick={() => onSelect(option.key)}
          aria-pressed={option.selected}
        >
          <span>{option.label}</span>
          <strong className={CHIP_COUNT}>{option.count}</strong>
        </VNativeButton>
      ))}
    </div>
  );
}
