import { CheckSquare, Square } from "lucide-react";
import { type ReactNode } from "react";

export type AgentDenseRow = {
  id: string;
  name: string;
  roleLabel: ReactNode;
  roleTone: string;
  avatarUrl?: string;
  avatarInitials: string;
  modelLabel: ReactNode;
  modelDetail?: string;
  promptLabel: ReactNode;
  runtimeLabel: ReactNode;
  runtimeTone: string;
  modes: ReactNode[];
  issueLabel: ReactNode;
  issueTone: string;
  issueSummary?: string;
  active: boolean;
  bulkSelected: boolean;
  selectLabel: string;
};

export type AgentDenseColumn = {
  id: string;
  label: ReactNode;
  description?: string;
  count: number;
  rows: AgentDenseRow[];
};

export type AgentDenseListColumnLabels = {
  agent: ReactNode;
  model: ReactNode;
  prompt: ReactNode;
  runtime: ReactNode;
  modes: ReactNode;
  reminders: ReactNode;
};

export type AgentDenseListProps = {
  columns: AgentDenseColumn[];
  columnLabels: AgentDenseListColumnLabels;
  onSelectRow: (rowId: string, event: React.MouseEvent<HTMLButtonElement>) => void;
  onToggleBulk: (rowId: string, checked: boolean, shiftKey: boolean) => void;
};

const GRID_TEMPLATE =
  "grid-cols-[minmax(180px,1.3fr)_minmax(120px,0.86fr)_minmax(110px,0.82fr)_minmax(88px,0.48fr)_minmax(104px,0.72fr)_minmax(128px,0.68fr)]";

const PILL_BASE =
  "inline-flex items-center justify-center min-h-[26px] px-[7px] border rounded-full text-[0.76rem] font-bold whitespace-nowrap";

const ROLE_TAG_BASE =
  "inline-flex items-center justify-self-start min-h-[22px] max-w-full px-[7px] border rounded-full text-[0.66rem] leading-none overflow-hidden text-ellipsis whitespace-nowrap";

const MODE_PILL =
  "inline-flex items-center min-h-[22px] px-[6px] border border-[color-mix(in_srgb,var(--accent-cool)_22%,transparent)] rounded-full bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)] text-[0.7rem] not-italic whitespace-nowrap";

const AVATAR =
  "grid place-items-center shrink-0 w-[30px] h-[30px] rounded-full overflow-hidden text-[var(--fg-primary)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--surface-card))] [font-family:var(--font-display)] font-extrabold text-[0.66rem]";

function runtimeToneClass(tone: string): string {
  if (tone === "running") {
    return "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] text-[var(--accent-cool)]";
  }
  if (tone === "failed" || tone === "blocked") {
    return "border-[color-mix(in_srgb,var(--state-error)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_10%,transparent)] text-[var(--state-error)]";
  }
  return "border-[color-mix(in_srgb,var(--fg-tertiary)_24%,transparent)] bg-[color-mix(in_srgb,var(--fg-tertiary)_8%,transparent)] text-[var(--fg-secondary)]";
}

function issueToneClass(tone: string): string {
  if (tone === "ok") {
    return "border-[color-mix(in_srgb,var(--state-success)_28%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]";
  }
  if (tone === "warning") {
    return "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_10%,transparent)] text-[var(--accent-warm-2)]";
  }
  if (tone === "info") {
    return "border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]";
  }
  if (tone === "blocking") {
    return "border-[color-mix(in_srgb,var(--state-error)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_10%,transparent)] text-[var(--state-error)]";
  }
  return "border-[color-mix(in_srgb,var(--fg-tertiary)_24%,transparent)] bg-[color-mix(in_srgb,var(--fg-tertiary)_8%,transparent)] text-[var(--fg-secondary)]";
}

function roleToneClass(tone: string): string {
  switch (tone) {
    case "chat":
      return "border-[color-mix(in_srgb,var(--accent-warm)_34%,var(--border-soft))] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]";
    case "research":
      return "border-[color-mix(in_srgb,var(--accent-cool)_36%,var(--border-soft))] bg-[color-mix(in_srgb,var(--accent-cool)_13%,transparent)] text-[var(--accent-cool-2)]";
    case "self":
      return "border-[color-mix(in_srgb,var(--state-success)_34%,var(--border-soft))] bg-[color-mix(in_srgb,var(--state-success)_12%,transparent)] text-[var(--state-success)]";
    case "supervised":
      return "border-[color-mix(in_srgb,var(--state-warning)_36%,var(--border-soft))] bg-[color-mix(in_srgb,var(--state-warning)_12%,transparent)] text-[var(--state-warning)]";
    case "tool":
    case "memory":
      return "border-[color-mix(in_srgb,var(--fg-tertiary)_30%,var(--border-soft))] bg-[color-mix(in_srgb,var(--fg-tertiary)_10%,transparent)] text-[var(--fg-secondary)]";
    default:
      return "border-[color-mix(in_srgb,var(--fg-tertiary)_24%,var(--border-soft))] bg-[color-mix(in_srgb,var(--fg-tertiary)_8%,transparent)] text-[var(--fg-secondary)]";
  }
}

function AgentRow({
  row,
  onSelectRow,
  onToggleBulk,
}: {
  row: AgentDenseRow;
  onSelectRow: AgentDenseListProps["onSelectRow"];
  onToggleBulk: AgentDenseListProps["onToggleBulk"];
}) {
  const rowClass = [
    "w-full min-h-[44px] px-2 py-[var(--agent-row-pad-y)] border border-[var(--border-soft)] rounded-lg bg-[var(--surface-card)] text-[var(--fg-primary)] text-left items-center gap-2 min-w-0 grid",
    GRID_TEMPLATE,
    "max-[860px]:grid-cols-[1fr] max-[860px]:items-start",
    "transition-[border-color,background,box-shadow] duration-150 hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)]",
    row.active
      ? "border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_9%,var(--surface-panel-strong))]"
      : "",
    row.bulkSelected ? "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--surface-panel-strong))]" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="grid grid-cols-[28px_minmax(0,1fr)] items-center gap-[5px] min-w-0">
      <label
        className="relative grid place-items-center w-[28px] h-[36px] border border-[var(--border-soft)] rounded-lg bg-[var(--surface-card)] text-[var(--fg-secondary)] cursor-pointer hover:border-[var(--border-strong)] hover:text-[var(--accent-warm-2)]"
        title={row.selectLabel}
      >
        <input
          type="checkbox"
          checked={row.bulkSelected}
          aria-label={row.selectLabel}
          className="absolute w-px h-px opacity-0 pointer-events-none"
          onChange={(event) =>
            onToggleBulk(
              row.id,
              event.target.checked,
              Boolean((event.nativeEvent as globalThis.MouseEvent).shiftKey),
            )
          }
        />
        {row.bulkSelected ? <CheckSquare size={15} /> : <Square size={15} />}
      </label>
      <button type="button" data-vui="agent-row" className={rowClass} onClick={(event) => onSelectRow(row.id, event)}>
        <span className="grid grid-cols-[30px_minmax(0,1fr)] items-center gap-2 min-w-0 overflow-hidden text-ellipsis">
          <span className={AVATAR} aria-hidden="true">
            {row.avatarUrl ? (
              <img src={row.avatarUrl} alt="" className="block w-full h-full rounded-[inherit] object-cover" />
            ) : (
              row.avatarInitials
            )}
          </span>
          <span className="grid min-w-0 gap-1">
            <strong className="min-w-0 overflow-hidden text-[color-mix(in_srgb,var(--fg-primary)_88%,var(--accent-cool))] text-[0.82rem] text-ellipsis whitespace-nowrap">
              {row.name}
            </strong>
            <em className={[ROLE_TAG_BASE, roleToneClass(row.roleTone)].join(" ")}>{row.roleLabel}</em>
          </span>
        </span>
        <span className="min-w-0 overflow-hidden text-ellipsis" title={row.modelDetail}>
          {row.modelLabel}
        </span>
        <span className="min-w-0 overflow-hidden text-ellipsis">{row.promptLabel}</span>
        <span className={[PILL_BASE, runtimeToneClass(row.runtimeTone)].join(" ")}>{row.runtimeLabel}</span>
        <span className="flex flex-wrap gap-[3px] min-w-0 overflow-hidden">
          {row.modes.map((mode, index) => (
            <em key={`${row.id}:mode:${index}`} className={MODE_PILL}>
              {mode}
            </em>
          ))}
        </span>
        <span className="flex items-center justify-items-start min-w-0" title={row.issueSummary}>
          <span className={[PILL_BASE, issueToneClass(row.issueTone)].join(" ")}>{row.issueLabel}</span>
        </span>
      </button>
    </div>
  );
}

export function AgentDenseList({ columns, columnLabels, onSelectRow, onToggleBulk }: AgentDenseListProps) {
  return (
    <div data-vui-product="agent-dense-list" className="grid content-start gap-2 min-h-0 overflow-auto pr-1">
      {columns.map((column, index) => (
        <section
          key={column.id}
          aria-label={typeof column.label === "string" ? column.label : undefined}
          className={[
            "grid content-start gap-[6px] min-w-0",
            index === 0
              ? ""
              : "pt-[7px] border-t border-[color-mix(in_srgb,var(--border-soft)_76%,transparent)]",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 min-w-0 px-1 pb-0.5">
            <div className="flex items-center gap-[6px] min-w-0" title={column.description}>
              <strong className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-[var(--fg-primary)] text-[0.82rem] font-extrabold">
                {column.label}
              </strong>
            </div>
            <em className="inline-flex items-center justify-center min-w-[24px] min-h-[22px] px-[7px] border border-[color-mix(in_srgb,var(--accent-cool)_22%,var(--border-soft))] rounded-full bg-[color-mix(in_srgb,var(--accent-cool)_9%,transparent)] text-[var(--accent-cool)] text-[0.72rem] not-italic font-extrabold">
              {column.count}
            </em>
          </div>
          <div className="grid content-start gap-1 min-h-0">
            <div
              className={[
                "grid items-center gap-2 min-w-0 sticky top-0 z-[1] px-2 pb-[5px] text-[var(--fg-tertiary)] text-[0.72rem] uppercase bg-[var(--surface-panel)]",
                GRID_TEMPLATE,
                "max-[860px]:hidden",
              ].join(" ")}
            >
              <span>{columnLabels.agent}</span>
              <span>{columnLabels.model}</span>
              <span>{columnLabels.prompt}</span>
              <span>{columnLabels.runtime}</span>
              <span>{columnLabels.modes}</span>
              <span>{columnLabels.reminders}</span>
            </div>
            {column.rows.map((row) => (
              <AgentRow key={row.id} row={row} onSelectRow={onSelectRow} onToggleBulk={onToggleBulk} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
