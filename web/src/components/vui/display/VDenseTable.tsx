import { type ReactNode } from "react";

export type VDenseTableColumn<TRow> = {
  align?: "left" | "right";
  className?: string;
  header: ReactNode;
  id: string;
  render: (row: TRow) => ReactNode;
};

export type VDenseTableProps<TRow> = {
  ariaLabel: string;
  className?: string;
  columns: Array<VDenseTableColumn<TRow>>;
  emptyText?: string;
  getRowKey: (row: TRow) => string;
  rows: TRow[];
};

export function VDenseTable<TRow>({
  ariaLabel,
  className,
  columns,
  emptyText = "No records",
  getRowKey,
  rows,
}: VDenseTableProps<TRow>) {
  return (
    <div
      data-vui="dense-table"
      aria-label={ariaLabel}
      className={[
        "min-w-0 overflow-hidden rounded-[var(--radius-control)] border border-vui-border-hairline bg-vui-surface-row",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <table className="w-full table-fixed border-collapse text-left">
        <thead className="bg-vui-surface-toolbar text-vui-fg-tertiary">
          <tr>
            {columns.map((column) => (
              <th
                key={column.id}
                className={[
                  "px-2 py-1 text-[var(--vui-font-xs)] font-semibold uppercase tracking-[0.04em]",
                  column.align === "right" ? "text-right" : "text-left",
                  column.className,
                ]
                  .filter(Boolean)
                  .join(" ")}
                scope="col"
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length ? (
            rows.map((row) => (
              <tr
                key={getRowKey(row)}
                className="border-t border-vui-border-hairline text-vui-fg-secondary hover:bg-vui-surface-row-hover"
              >
                {columns.map((column) => (
                  <td
                    key={column.id}
                    className={[
                      "min-w-0 truncate px-2 py-1.5 text-[var(--vui-font-sm)]",
                      column.align === "right" ? "text-right" : "text-left",
                      column.className,
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))
          ) : (
            <tr>
              <td
                className="px-2 py-2 text-[var(--vui-font-sm)] text-vui-fg-tertiary"
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
