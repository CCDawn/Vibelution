import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  VDenseRow,
  VDenseToolbar,
  VEmbeddedPanel,
  VMetricChip,
  VStateRow,
  VStatusChip,
} from "./index";

describe("VUI quiet-workbench aesthetic primitives", () => {
  it("renders embedded panels without primary panel chrome", () => {
    const markup = renderToStaticMarkup(
      <VEmbeddedPanel ariaLabel="Evidence summary">
        <strong>Evidence</strong>
      </VEmbeddedPanel>,
    );

    expect(markup).toContain('data-vui="embedded-panel"');
    expect(markup).toContain('aria-label="Evidence summary"');
    expect(markup).toContain("bg-vui-surface-row/70");
    expect(markup).toContain("shadow-none");
    expect(markup).not.toContain("shadow-[var(--vui-shadow-hairline)]");
  });

  it("renders dense toolbars and rows with stable data attributes", () => {
    const markup = renderToStaticMarkup(
      <VDenseToolbar ariaLabel="Memory filters">
        <VMetricChip label="Items" value="42" />
        <VStatusChip tone="accent">Active</VStatusChip>
        <VDenseRow>Knowledge source</VDenseRow>
      </VDenseToolbar>,
    );

    expect(markup).toContain('data-vui="dense-toolbar"');
    expect(markup).toContain('role="toolbar"');
    expect(markup).toContain('aria-label="Memory filters"');
    expect(markup).toContain('data-vui="metric-chip"');
    expect(markup).toContain('data-vui="status-chip"');
    expect(markup).toContain('data-vui="dense-row"');
    expect(markup).toContain("Items");
    expect(markup).toContain("42");
  });

  it("keeps critical row and chip states visibly distinct", () => {
    const markup = renderToStaticMarkup(
      <div>
        <VStateRow tone="danger">Delete confirmation required</VStateRow>
        <VStateRow tone="warning">Blocked by review</VStateRow>
        <VStatusChip tone="danger">Failed</VStatusChip>
        <VStatusChip tone="success">Ready</VStatusChip>
      </div>,
    );

    expect(markup).toContain('data-tone="danger"');
    expect(markup).toContain('data-tone="warning"');
    expect(markup).toContain('data-tone="success"');
    expect(markup).toContain("var(--state-error)");
    expect(markup).toContain("var(--state-warning)");
    expect(markup).toContain("var(--state-success)");
  });
});
