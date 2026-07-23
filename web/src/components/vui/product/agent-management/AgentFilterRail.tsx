import { ChevronDown, Search, SlidersHorizontal } from "lucide-react";
import { type ReactNode } from "react";

import { VNativeButton, VNativeInput, VTooltip } from "../../index";
import { AgentWorkspacePanel } from "./AgentWorkspacePanel";

export type AgentFilterGroupView = {
  id: string;
  label: ReactNode;
  title?: string;
  ariaLabel?: string;
  count: number;
  icon?: ReactNode;
  healthLabel?: ReactNode;
};

export type AgentFilterSectionView = {
  id: string;
  label: ReactNode;
  groups: AgentFilterGroupView[];
};

export type AgentFilterRailProps = {
  ariaLabel: string;
  searchValue: string;
  searchPlaceholder: string;
  onSearchChange: (value: string) => void;
  sections: AgentFilterSectionView[];
  advancedSections?: AgentFilterSectionView[];
  advancedLabel?: ReactNode;
  activeGroupId: string;
  onSelectGroup: (groupId: string) => void;
  moreFiltersLabel?: ReactNode;
  className?: string;
};

const GROUP_BUTTON_BASE =
  "grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 w-full min-h-[34px] px-[9px] py-[6px] rounded-none border-0 border-b border-[var(--vui-border-hairline)] bg-transparent text-[var(--fg-secondary)] text-left transition-[background,color,border-color] duration-150 hover:bg-[var(--vui-surface-row-hover)] hover:text-[var(--fg-primary)]";

const GROUP_BUTTON_ACTIVE =
  "border-l-2 border-l-[var(--accent-warm)] bg-[color-mix(in_srgb,var(--accent-warm)_9%,transparent)] text-[var(--fg-primary)]";

const STATUS_BUTTON_BASE =
  "inline-flex min-w-0 flex-1 items-center justify-between gap-2 min-h-[30px] px-2.5 rounded-[var(--radius-control)] border border-[var(--border-soft)] bg-transparent text-[var(--fg-secondary)] text-[0.76rem] font-bold transition-[background,color,border-color] duration-150 hover:border-[var(--border-strong)] hover:bg-[var(--vui-surface-row-hover)] hover:text-[var(--fg-primary)]";

const STATUS_BUTTON_ACTIVE =
  "border-[color-mix(in_srgb,var(--accent-cool)_40%,var(--border-soft))] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] text-[var(--accent-cool-2)]";

const GROUP_LABEL =
  "inline-flex items-center gap-2 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";

const COUNT_BADGE =
  "inline-flex items-center justify-center min-w-[22px] min-h-[22px] rounded-full text-[0.72rem] not-italic font-bold bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] text-[var(--accent-cool)]";

const HEALTH_BADGE =
  "inline-flex items-center justify-center gap-1 min-w-[22px] min-h-[22px] px-[7px] rounded-full text-[0.72rem] not-italic bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]";

const DETAILS_SUMMARY =
  "grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 min-h-[30px] px-2.5 rounded-[var(--radius-control)] border border-[var(--border-soft)] bg-transparent text-[var(--fg-secondary)] text-[0.76rem] font-bold cursor-pointer list-none [&::-webkit-details-marker]:hidden hover:border-[var(--border-strong)] hover:bg-[var(--vui-surface-row-hover)] hover:text-[var(--fg-primary)]";

function FilterSection({
  section,
  activeGroupId,
  onSelectGroup,
}: {
  section: AgentFilterSectionView;
  activeGroupId: string;
  onSelectGroup: (groupId: string) => void;
}) {
  return (
    <section data-vui-product="agent-filter-section" className="grid gap-[5px] min-w-0">
      <p className="m-0 px-0.5 text-[var(--fg-tertiary)] text-[0.6rem] font-bold tracking-[0.08em] leading-[1.2] uppercase">
        {section.label}
      </p>
      <div className="grid min-w-0">
        {section.groups.map((group) => {
          const active = activeGroupId === group.id;
          const button = (
            <VNativeButton
              key={group.id}
              type="button"
              data-vui="filter-group-button"
              data-active={active ? "true" : undefined}
              className={[GROUP_BUTTON_BASE, active ? GROUP_BUTTON_ACTIVE : ""]
                .filter(Boolean)
                .join(" ")}
              onClick={() => onSelectGroup(group.id)}
              aria-label={group.ariaLabel}
              aria-pressed={active}
            >
              <span className={GROUP_LABEL}>
                {group.icon}
                {group.label}
              </span>
              <strong className={COUNT_BADGE}>{group.count}</strong>
              {group.healthLabel ? <em className={HEALTH_BADGE}>{group.healthLabel}</em> : null}
            </VNativeButton>
          );
          return group.title ? (
            <VTooltip key={group.id} content={group.title} width="wide">
              {button}
            </VTooltip>
          ) : (
            button
          );
        })}
      </div>
    </section>
  );
}

function sectionContainsActive(section: AgentFilterSectionView, activeGroupId: string) {
  return section.groups.some((group) => group.id === activeGroupId);
}

export function AgentFilterRail({
  ariaLabel,
  searchValue,
  searchPlaceholder,
  onSearchChange,
  sections,
  advancedSections,
  advancedLabel,
  activeGroupId,
  onSelectGroup,
  moreFiltersLabel,
  className,
}: AgentFilterRailProps) {
  const primarySections = sections.filter((section) => section.id === "status");
  const secondarySections = [
    ...sections.filter((section) => section.id !== "status"),
    ...(advancedSections ?? []),
  ];
  const secondaryOpen = secondarySections.some((section) =>
    sectionContainsActive(section, activeGroupId),
  );

  return (
    <AgentWorkspacePanel
      as="aside"
      ariaLabel={ariaLabel}
      className={["grid-rows-[auto_auto]", className].filter(Boolean).join(" ")}
    >
      <label
        data-vui-product="agent-filter-search"
        className="flex items-center gap-2 min-h-[32px] px-[9px] rounded-[var(--radius-control)] border border-[var(--border-soft)] bg-[color-mix(in_srgb,var(--surface-input)_84%,var(--vui-surface-row))] text-[var(--fg-tertiary)] focus-within:border-[color-mix(in_srgb,var(--accent-cool)_44%,transparent)] focus-within:shadow-[var(--focus-ring)] focus-within:text-[var(--fg-secondary)]"
      >
        <Search size={15} className="shrink-0" />
        <VNativeInput
          value={searchValue}
          placeholder={searchPlaceholder}
          onChange={(event) => onSearchChange(event.target.value)}
          className="min-w-0 w-full !border-0 !bg-transparent !px-0 !shadow-none outline-0 text-[var(--fg-primary)] text-[0.82rem] font-[inherit]"
        />
      </label>

      <nav aria-label={ariaLabel} className="grid content-start gap-1.5 min-h-0">
        <div className="flex min-w-0 items-center gap-1.5">
          {primarySections.flatMap((section) =>
            section.groups.map((group) => {
              const active = activeGroupId === group.id;
              return (
                <VNativeButton
                  key={group.id}
                  type="button"
                  aria-label={group.ariaLabel}
                  aria-pressed={active}
                  className={[
                    STATUS_BUTTON_BASE,
                    active ? STATUS_BUTTON_ACTIVE : "",
                  ].filter(Boolean).join(" ")}
                  onClick={() => onSelectGroup(group.id)}
                >
                  <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                    {group.label}
                  </span>
                  <strong className={COUNT_BADGE}>{group.count}</strong>
                </VNativeButton>
              );
            }),
          )}
        </div>

        {secondarySections.length ? (
          <details
            data-vui-product="agent-filter-more"
            className="group grid min-w-0"
            open={secondaryOpen || undefined}
          >
            <summary className={DETAILS_SUMMARY}>
              <span className="inline-flex min-w-0 items-center gap-2 overflow-hidden text-ellipsis whitespace-nowrap">
                <SlidersHorizontal size={14} className="shrink-0" />
                {moreFiltersLabel ?? advancedLabel}
              </span>
              {secondaryOpen ? <strong className={COUNT_BADGE}>1</strong> : <span />}
              <ChevronDown
                size={14}
                className="shrink-0 transition-transform duration-150 group-[[open]]:rotate-180"
              />
            </summary>
            <div className="grid max-h-[min(42vh,360px)] gap-2 min-w-0 overflow-auto pt-2">
              {secondarySections.map((section) => (
                <FilterSection
                  key={section.id}
                  section={section}
                  activeGroupId={activeGroupId}
                  onSelectGroup={onSelectGroup}
                />
              ))}
            </div>
          </details>
        ) : null}
      </nav>
    </AgentWorkspacePanel>
  );
}
