import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { nextDenseTableColumnWidth, sumDenseTableColumnWidths, VDenseTable } from "./VDenseTable";

describe("VDenseTable", () => {
  it("aligns headers and cells in one table and exposes column resize handles", () => {
    const html = renderToStaticMarkup(
      <VDenseTable
        ariaLabel="instances"
        resizable
        rows={[{ id: "main", name: "main", state: "closed" }]}
        getRowKey={(row) => row.id}
        columns={[
          { id: "name", header: "Branch", width: 160, render: (row) => row.name },
          { id: "state", header: "State", width: 80, render: (row) => row.state },
        ]}
      />,
    );

    expect(html).toContain("<table");
    expect(html).toContain("<colgroup>");
    expect(html).toContain("width:240px");
    expect(html).toContain("min-width:240px");
    expect(html).toContain("width:160px");
    expect(html).toContain("width:80px");
    expect(html).not.toContain("w-full");
    expect(html).toContain('role="separator"');
    expect(html).toContain("Resize name");
    expect(html).toContain("Branch");
    expect(html).toContain("main");
  });

  it("keeps existing non-resizable tables without drag handles", () => {
    const html = renderToStaticMarkup(
      <VDenseTable
        ariaLabel="models"
        rows={[{ id: "a" }]}
        getRowKey={(row) => row.id}
        columns={[{ id: "id", header: "ID", className: "w-[23%]", render: (row) => row.id }]}
      />,
    );

    expect(html).not.toContain("<colgroup>");
    expect(html).not.toContain('role="separator"');
    expect(html).toContain("w-[23%]");
  });

  it("clamps dragged column widths to the column minimum", () => {
    expect(nextDenseTableColumnWidth(120, 40, 48)).toBe(160);
    expect(nextDenseTableColumnWidth(80, -100, 48)).toBe(48);
    expect(sumDenseTableColumnWidths([36, 188, 88, 112])).toBe(424);
  });
});
