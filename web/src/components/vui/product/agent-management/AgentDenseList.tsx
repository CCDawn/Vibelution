import { CheckSquare, Square } from "lucide-react";
import { type ReactNode } from "react";

import { VNativeButton, VNativeInput, VTooltip } from "../../index";

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

const PILL_BASE =
  "inline-flex items-center justify-center min-h-[22px] px-[7px] border rounded-full [font-size:var(--vui-font-xs)] font-bold not-italic whitespace-nowrap";

const ROLE_TAG_BASE =
  "inline-flex min-h-[18px] max-w-full items-center justify-self-start overflow-hidden text-ellipsis whitespace-nowrap px-0.5 [font-size:var(--vui-font-xs)] font-[600] not-italic leading-none text-[var(--fg-secondary)]";

const AVATAR =
  "grid place-items-center shrink-0 w-[30px] h-[30px] rounded-full overflow-hidden text-[var(--fg-primary)] bg-[var(--vui-control-muted)] [font-family:var(--font-display)] font-extrabold text-[0.66rem]";

function issueToneClass(tone: string): string {
  if (tone === "ok") {
    return "border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] text-[var(--fg-secondary)]";
  }
  if (tone === "warning") {
    return "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_10%,transparent)] text-[var(--accent-warm-2)]";
  }
  if (tone === "info") {
    return "border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] text-[var(--fg-secondary)]";
  }
  if (tone === "blocking") {
    return "border-[color-mix(in_srgb,var(--state-error)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_10%,transparent)] text-[var(--state-error)]";
  }
  return "border-[color-mix(in_srgb,var(--fg-tertiary)_24%,transparent)] bg-[color-mix(in_srgb,var(--fg-tertiary)_8%,transparent)] text-[var(--fg-secondary)]";
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
  const rowTooltip = (
    <span className="grid gap-1">
      <span>{row.modelLabel}</span>
      {row.modelDetail ? <span>{row.modelDetail}</span> : null}
      <span>{row.promptLabel}</span>
      {row.modes.length ? <span>{row.modes}</span> : null}
      {row.issueSummary ? <span>{row.issueSummary}</span> : null}
    </span>
  );
  const rowClass = [
    "w-full min-h-[46px] p-1.5 border border-[var(--vui-border-hairline)] rounded-[var(--radius-control)] bg-[var(--vui-surface-row)] text-[var(--fg-primary)] min-w-0 grid grid-cols-[28px_minmax(0,1fr)] items-center gap-1.5",
    "transition-[border-color,background] duration-150 hover:bg-[var(--vui-surface-row-hover)]",
    row.active
      ? "border-[color-mix(in_srgb,var(--accent-warm)_48%,var(--vui-border-hairline))] bg-[color-mix(in_srgb,var(--accent-warm)_9%,var(--vui-surface-row))]"
      : "",
    row.bulkSelected ? "border-[color-mix(in_srgb,var(--fg-primary)_22%,var(--vui-border-hairline))] bg-[var(--vui-control-muted)]" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const selectionControl = (
    <label
      className="relative grid place-items-center w-[28px] h-[36px] rounded-[var(--radius-control)] text-[var(--fg-secondary)] cursor-pointer hover:bg-[color-mix(in_srgb,var(--fg-tertiary)_8%,transparent)] hover:text-[var(--accent-warm-2)]"
    >
      <VNativeInput
        type="checkbox"
        checked={row.bulkSelected}
        aria-label={row.selectLabel}
        className="absolute !w-px !h-px opacity-0 pointer-events-none"
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
  );

  const showIssue = row.issueTone !== "ok";
  const agentCard = (
    <VNativeButton
      type="button"
      data-vui="agent-row"
      className="grid w-full min-w-0 grid-cols-[minmax(0,1fr)] items-center border-0 bg-transparent p-0 text-left text-[var(--fg-primary)]"
      onClick={(event) => onSelectRow(row.id, event)}
    >
      <span className="grid grid-cols-[30px_minmax(0,1fr)] items-center gap-2 min-w-0 overflow-hidden text-ellipsis">
        <span className={AVATAR} aria-hidden="true">
          {row.avatarUrl ? (
            <img src={row.avatarUrl} alt="" className="block w-full h-full rounded-[inherit] object-cover" />
          ) : (
            row.avatarInitials
          )}
        </span>
        <span className="grid min-w-0 gap-1">
          <span className="flex min-w-0 items-center gap-1.5">
            <strong className="min-w-0 overflow-hidden text-[var(--fg-primary)] [font-size:var(--vui-font-sm)] text-ellipsis whitespace-nowrap">
              {row.name}
            </strong>
            {showIssue ? (
              <em className={[PILL_BASE, issueToneClass(row.issueTone)].join(" ")}>{row.issueLabel}</em>
            ) : null}
          </span>
          <em data-tone={row.roleTone} className={ROLE_TAG_BASE}>{row.roleLabel}</em>
        </span>
      </span>
    </VNativeButton>
  );

  return (
    <div className={rowClass}>
      <VTooltip content={row.selectLabel}>{selectionControl}</VTooltip>
      <VTooltip content={rowTooltip} width="wide">{agentCard}</VTooltip>
    </div>
  );
}

export function AgentDenseList({ columns, columnLabels, onSelectRow, onToggleBulk }: AgentDenseListProps) {
  // Card rows carry their own visible hierarchy; keep the shared label contract for callers.
  void columnLabels;

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
            <em className="inline-flex min-h-5 min-w-5 items-center justify-center rounded-[6px] bg-[var(--vui-control-muted)] px-1 text-[0.72rem] font-extrabold not-italic text-[var(--fg-secondary)]">
              {column.count}
            </em>
          </div>
          <div className="grid content-start gap-1 min-h-0">
            {column.rows.map((row) => (
              <AgentRow key={row.id} row={row} onSelectRow={onSelectRow} onToggleBulk={onToggleBulk} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
