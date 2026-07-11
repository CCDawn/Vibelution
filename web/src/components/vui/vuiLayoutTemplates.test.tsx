import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  VEmptyState,
  VEntityList,
  VRouteHeader,
  VSection,
  VSplitWorkspace,
  VStateSurface,
  VStatusStrip,
  VWorkbenchPage,
} from "./index";

describe("VUI workbench layout templates", () => {
  it("places a public section header class on the direct header before its direct body", () => {
    const markup = renderToStaticMarkup(
      <VSection headerClassName="config-section-header-contract" title="Config section">
        <div data-layout-marker="section-body">Body</div>
      </VSection>,
    );

    expect(markup).toMatch(
      /<section[^>]*><header[^>]*config-section-header-contract[^>]*>.*<\/header><div data-layout-marker="section-body">Body<\/div><\/section>/,
    );
  });

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
        <VStateSurface
          tone="loading"
          title="Loading team details"
          facts={[{ key: "source", label: "Source", value: "Team detail API" }]}
          skeletonLines
        >
          Keeping the workspace frame visible while details load.
        </VStateSurface>
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
    expect(markup).toContain('data-vui="state-surface"');
    expect(markup).toContain('data-tone="loading"');
    expect(markup).toContain("Team detail API");
    expect(markup).toContain("animate-pulse");
    expect(markup).toContain('data-vui="split-workspace"');
    expect(markup).toContain('data-vui="entity-list"');
    expect(markup).toContain('data-vui="empty-state"');
    expect(markup).toContain("Research Console");
    expect(markup).toContain("Source");
  });
});
