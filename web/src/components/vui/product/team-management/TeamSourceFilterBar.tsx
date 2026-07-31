import { type ReactNode } from "react";

import { VButton } from "../../primitives/VButton";

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

const BAR = "flex min-w-0 gap-1.5 overflow-x-auto pb-px";

/** Compact filter toggle chips — VButton + density tokens (not a second chip system). */
const CHIP_BASE =
  "min-w-[4.75rem] flex-none justify-between gap-1.5 rounded-[var(--radius-control)] border px-2 " +
  "[font-size:var(--vui-font-xs)] font-semibold " +
  "bg-[var(--vui-surface-row)] border-[var(--vui-border-subtle)] text-[var(--fg-secondary)] " +
  "hover:border-[color:color-mix(in_srgb,var(--accent-cool)_48%,var(--vui-border-subtle))] " +
  "hover:bg-[color:color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-row))] hover:text-[var(--fg-primary)] " +
  "focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus)]";

const CHIP_ACTIVE =
  "border-[color:color-mix(in_srgb,var(--accent-cool)_48%,var(--vui-border-subtle))] " +
  "bg-[color:color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-row))] text-[var(--fg-primary)]";

const CHIP_COUNT = "text-[var(--fg-primary)] [font-size:var(--vui-font-xs)] font-semibold";

/**
 * Horizontally scrollable filter chips (label + count) with accent-tinted active state.
 */
export function TeamSourceFilterBar({ ariaLabel, options, onSelect }: TeamSourceFilterBarProps) {
  return (
    <div data-vui-product="team-source-filter-bar" className={BAR} aria-label={ariaLabel}>
      {options.map((option) => (
        <VButton
          key={option.key}
          density="compact"
          type="button"
          variant="secondary"
          trailingIcon={<strong className={CHIP_COUNT}>{option.count}</strong>}
          className={[CHIP_BASE, option.selected ? CHIP_ACTIVE : ""].filter(Boolean).join(" ")}
          onClick={() => onSelect(option.key)}
          aria-pressed={option.selected}
        >
          {option.label}
        </VButton>
      ))}
    </div>
  );
}
