import { type KeyboardEvent, type PointerEvent, type ReactNode, useMemo, useState } from "react";

export type VDenseTableColumn<TRow> = {
  align?: "left" | "center" | "right";
  className?: string;
  header: ReactNode;
  id: string;
  minWidth?: number;
  render: (row: TRow) => ReactNode;
  resizable?: boolean;
  truncate?: boolean;
  width?: number;
};

export type VDenseTableRowState = {
  className?: string;
  selected?: boolean;
  tabIndex?: number;
  tone?: "neutral" | "success" | "warning";
};

export type VDenseTableProps<TRow> = {
  ariaLabel: string;
  className?: string;
  columns: Array<VDenseTableColumn<TRow>>;
  emptyText?: string;
  getRowKey: (row: TRow) => string;
  getRowState?: (row: TRow) => VDenseTableRowState;
  onRowClick?: (row: TRow) => void;
  resizable?: boolean;
  rows: TRow[];
};

const DEFAULT_COLUMN_WIDTH = 120;
const DEFAULT_MIN_WIDTH = 48;

export function nextDenseTableColumnWidth(startWidth: number, delta: number, minWidth: number): number {
  return Math.max(minWidth, Math.round(startWidth + delta));
}

export function VDenseTable<TRow>({
  ariaLabel,
  className,
  columns,
  emptyText = "No records",
  getRowKey,
  getRowState,
  onRowClick,
  resizable = false,
  rows,
}: VDenseTableProps<TRow>) {
  const [widths, setWidths] = useState<Record<string, number>>(() => initialColumnWidths(columns));
  const columnWidths = useMemo(
    () => Object.fromEntries(columns.map((column) => [column.id, widths[column.id] ?? column.width ?? DEFAULT_COLUMN_WIDTH])),
    [columns, widths],
  );

  const startResize = (column: VDenseTableColumn<TRow>, event: PointerEvent<HTMLSpanElement>) => {
    if (!canResizeColumn(column, resizable)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const handle = event.currentTarget;
    const startX = event.clientX;
    const startWidth = columnWidths[column.id] ?? DEFAULT_COLUMN_WIDTH;
    const minWidth = column.minWidth ?? DEFAULT_MIN_WIDTH;
    handle.setPointerCapture(event.pointerId);
    const onMove = (moveEvent: globalThis.PointerEvent) => {
      setWidths((current) => ({
        ...current,
        [column.id]: nextDenseTableColumnWidth(startWidth, moveEvent.clientX - startX, minWidth),
      }));
    };
    const onUp = () => {
      handle.releasePointerCapture(event.pointerId);
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      handle.removeEventListener("pointercancel", onUp);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
    handle.addEventListener("pointercancel", onUp);
  };

  return (
    <div
      data-vui="dense-table"
      data-vui-resizable={resizable ? "true" : undefined}
      aria-label={ariaLabel}
      className={[
        "min-w-0 rounded-[var(--radius-control)] border border-vui-border-hairline bg-vui-surface-row",
        resizable ? "overflow-x-auto" : "overflow-hidden",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <table className="w-full table-fixed border-collapse text-left">
        {resizable ? (
          <colgroup>
            {columns.map((column) => (
              <col key={column.id} style={{ width: `${columnWidths[column.id]}px` }} />
            ))}
          </colgroup>
        ) : null}
        <thead className="bg-vui-surface-toolbar text-vui-fg-tertiary">
          <tr>
            {columns.map((column) => (
              <th
                key={column.id}
                className={[
                  "relative px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold uppercase tracking-[0.04em]",
                  alignClass(column.align),
                  column.className,
                ]
                  .filter(Boolean)
                  .join(" ")}
                scope="col"
              >
                {column.header}
                {canResizeColumn(column, resizable) ? (
                  <span
                    role="separator"
                    aria-orientation="vertical"
                    aria-label={`Resize ${column.id}`}
                    aria-valuenow={columnWidths[column.id]}
                    aria-valuemin={column.minWidth ?? DEFAULT_MIN_WIDTH}
                    tabIndex={0}
                    className="absolute inset-y-0 right-0 z-10 w-2 cursor-col-resize touch-none select-none after:absolute after:inset-y-1 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-transparent hover:after:bg-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]"
                    onPointerDown={(event) => startResize(column, event)}
                    onClick={(event) => event.stopPropagation()}
                  />
                ) : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length ? (
            rows.map((row) => {
              const state = getRowState?.(row) ?? {};
              return (
                <tr
                  key={getRowKey(row)}
                  className={[
                    "border-t border-vui-border-hairline text-vui-fg-secondary hover:bg-[var(--vui-surface-row-hover)]",
                    onRowClick ? "cursor-pointer" : "",
                    state.selected ? "bg-[color-mix(in_srgb,var(--vui-accent)_14%,var(--vui-surface-row))]" : "",
                    state.tone === "success" ? "border-l-2 border-l-[var(--state-success)]" : "",
                    state.tone === "warning" ? "border-l-2 border-l-[var(--state-warning)]" : "",
                    state.className,
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  data-selected={state.selected ? "true" : "false"}
                  data-tone={state.tone ?? "neutral"}
                  tabIndex={state.tabIndex ?? (onRowClick ? 0 : undefined)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  onKeyDown={onRowClick ? (event) => activateRow(event, () => onRowClick(row)) : undefined}
                >
                  {columns.map((column) => (
                    <td
                      key={column.id}
                      className={[
                        "min-w-0 px-2 py-1.5 align-middle [font-size:var(--vui-font-sm)]",
                        column.truncate === false ? "overflow-visible" : "truncate",
                        alignClass(column.align),
                        column.className,
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      {column.render(row)}
                    </td>
                  ))}
                </tr>
              );
            })
          ) : (
            <tr>
              <td
                className="px-2 py-2 [font-size:var(--vui-font-sm)] text-vui-fg-tertiary"
                colSpan={columns.length}
              >
                {emptyText}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function initialColumnWidths<TRow>(columns: Array<VDenseTableColumn<TRow>>): Record<string, number> {
  return Object.fromEntries(columns.map((column) => [column.id, column.width ?? DEFAULT_COLUMN_WIDTH]));
}

function canResizeColumn<TRow>(column: VDenseTableColumn<TRow>, tableResizable: boolean): boolean {
  return tableResizable && column.resizable !== false;
}

function alignClass(align: VDenseTableColumn<unknown>["align"]): string {
  if (align === "right") {
    return "text-right";
  }
  if (align === "center") {
    return "text-center";
  }
  return "text-left";
}

function activateRow(event: KeyboardEvent<HTMLTableRowElement>, activate: () => void): void {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    activate();
  }
}
