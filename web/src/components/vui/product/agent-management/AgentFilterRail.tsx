import { ChevronDown, Search } from "lucide-react";
import { type ReactNode } from "react";

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
  advancedCount?: number;
  activeGroupId: string;
  onSelectGroup: (groupId: string) => void;
  storageLabel: ReactNode;
  storagePaths: string[];
  className?: string;
};

const GROUP_BUTTON_BASE =
  "grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 w-full min-h-[34px] px-[9px] py-[6px] rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card)] text-[var(--fg-secondary)] text-left transition-[border-color,background,color] duration-150 hover:border-[var(--border-strong)] hover:text-[var(--fg-primary)] hover:bg-[var(--surface-panel-hover)]";

const GROUP_BUTTON_ACTIVE =
  "border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_10%,var(--surface-panel-strong))] text-[var(--fg-primary)]";

const GROUP_LABEL =
  "inline-flex items-center gap-2 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";

const COUNT_BADGE =
  "inline-flex items-center justify-center min-w-[22px] min-h-[22px] rounded-full text-[0.72rem] not-italic font-bold bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] text-[var(--accent-cool)]";

const HEALTH_BADGE =
  "inline-flex items-center justify-center gap-1 min-w-[22px] min-h-[22px] px-[7px] rounded-full text-[0.72rem] not-italic bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]";

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
      <div className="grid gap-[5px] min-w-0">
        {section.groups.map((group) => {
          const active = activeGroupId === group.id;
          return (
            <button
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
              title={group.title}
            >
              <span className={GROUP_LABEL}>
                {group.icon}
                {group.label}
              </span>
              <strong className={COUNT_BADGE}>{group.count}</strong>
              {group.healthLabel ? <em className={HEALTH_BADGE}>{group.healthLabel}</em> : null}
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function AgentFilterRail({
  ariaLabel,
  searchValue,
  searchPlaceholder,
  onSearchChange,
  sections,
  advancedSections,
  advancedLabel,
  advancedCount,
  activeGroupId,
  onSelectGroup,
  storageLabel,
  storagePaths,
  className,
}: AgentFilterRailProps) {
  return (
    <AgentWorkspacePanel
      as="aside"
      ariaLabel={ariaLabel}
      className={["grid-rows-[auto_minmax(0,1fr)_auto]", className].filter(Boolean).join(" ")}
    >
      <label
        data-vui-product="agent-filter-search"
        className="flex items-center gap-2 min-h-[32px] px-[9px] rounded-lg border border-[var(--border-soft)] bg-[color-mix(in_srgb,var(--surface-input)_84%,var(--surface-card))] text-[var(--fg-tertiary)] focus-within:border-[color-mix(in_srgb,var(--accent-cool)_44%,transparent)] focus-within:shadow-[var(--focus-ring)] focus-within:text-[var(--fg-secondary)]"
      >
        <Search size={15} className="shrink-0" />
        <input
          value={searchValue}
          placeholder={searchPlaceholder}
          onChange={(event) => onSearchChange(event.target.value)}
          className="min-w-0 w-full border-0 outline-0 bg-transparent text-[var(--fg-primary)] text-[0.82rem] font-[inherit]"
        />
      </label>

      <nav aria-label={ariaLabel} className="grid content-start gap-[10px] min-h-0 overflow-auto">
        {sections.map((section) => (
          <FilterSection
            key={section.id}
            section={section}
            activeGroupId={activeGroupId}
            onSelectGroup={onSelectGroup}
          />
        ))}
        {advancedSections && advancedSections.length ? (
          <details data-vui-product="agent-filter-advanced" className="group grid min-w-0">
            <summary className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 min-h-[34px] px-[9px] py-[6px] rounded-lg border border-[var(--border-soft)] bg-[color-mix(in_srgb,var(--surface-card)_86%,var(--bg-canvas))] text-[var(--fg-secondary)] text-[0.8rem] font-[760] cursor-pointer list-none [&::-webkit-details-marker]:hidden hover:border-[var(--border-strong)] hover:text-[var(--fg-primary)] hover:bg-[var(--surface-panel-hover)]">
              <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                {advancedLabel}
              </span>
              {advancedCount ? <strong className={COUNT_BADGE}>{advancedCount}</strong> : <span />}
              <ChevronDown
                size={14}
                className="shrink-0 transition-transform duration-150 group-[[open]]:rotate-180"
              />
            </summary>
            <div className="grid gap-[10px] min-w-0 pt-2">
              {advancedSections.map((section) => (
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

      <section
        data-vui-product="agent-filter-storage"
        className="grid gap-[5px] min-w-0 p-2 rounded-lg border border-[var(--border-soft)] bg-[color-mix(in_srgb,var(--surface-card)_86%,var(--bg-canvas))]"
      >
        <p className="m-0 mb-px text-[var(--fg-tertiary)] text-[0.61rem] tracking-[0.07em] uppercase">
          {storageLabel}
        </p>
        {storagePaths.map((path) => (
          <code
            key={path}
            className="min-w-0 overflow-hidden text-[var(--fg-secondary)] text-[0.74rem] text-ellipsis whitespace-nowrap"
          >
            {path}
          </code>
        ))}
      </section>
    </AgentWorkspacePanel>
  );
}
