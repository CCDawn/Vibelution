import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  VEmptyState,
  VEntityList,
  VRouteHeader,
  VSplitWorkspace,
  VStatusStrip,
  VWorkbenchPage,
} from "./index";

describe("VUI workbench layout templates", () => {
  it("renders reusable route-level layout slots with stable data attributes", () => {
    const markup = renderToStaticMarkup(
      <VWorkbenchPage ariaLabel="Agent workbench">
        <VRouteHeader
          eyebrow="Team"
          title="Research Console"
          meta="11 agents"
          actions={<button type="button">Refresh</button>}
        />
        <VStatusStrip
          items={[
            { label: "Running", value: "2" },
            { label: "Ready", value: "9" },
          ]}
        />
        <VSplitWorkspace
          sidebar={<nav>Team list</nav>}
          main={
            <VEntityList
              ariaLabel="Agents"
              items={[
                { id: "a", label: "Source" },
                { id: "b", label: "Writer" },
              ]}
              renderItem={(item) => <span>{item.label}</span>}
            />
          }
          aside={<VEmptyState title="No selection" />}
        />
      </VWorkbenchPage>,
    );

    expect(markup).toContain('data-vui="workbench-page"');
    expect(markup).toContain('data-vui="route-header"');
    expect(markup).toContain("rounded-[var(--radius-panel)]");
    expect(markup).toContain("text-[var(--font-size-title)]");
    expect(markup).toContain("text-[var(--font-size-caption)]");
    expect(markup).toContain("text-[var(--font-size-micro)]");
    expect(markup).toContain('data-vui="status-strip"');
    expect(markup).toContain('data-vui="split-workspace"');
    expect(markup).toContain('data-vui="entity-list"');
    expect(markup).toContain('data-vui="empty-state"');
    expect(markup).toContain("Research Console");
    expect(markup).toContain("Source");
  });
});
