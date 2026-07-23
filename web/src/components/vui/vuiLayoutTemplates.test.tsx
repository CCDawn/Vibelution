import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  VButton,
  VDenseOpsPage,
  VDenseTable,
  VEmptyState,
  VEntityList,
  VFieldRow,
  VInput,
  VListDetailPage,
  VLoadingValue,
  VMetricStrip,
  VPanelHeader,
  VRouteHeader,
  VSection,
  VSettingsFormPage,
  VSplitWorkspace,
  VStateSurface,
  VStatusStrip,
  VWorkbenchPage,
} from "./index";

describe("VUI workbench layout templates", () => {
  it("keeps panel-header text without rendering a heading when requested", () => {
    const markup = renderToStaticMarkup(
      <VPanelHeader
        headingLevel={null}
        title="Sidebar navigation"
        tooltip="Choose a workspace section"
        tooltipLabel="Sidebar navigation details"
      />,
    );

    expect(markup).toContain('data-vui="panel-header"');
    expect(markup).toContain("Sidebar navigation");
    expect(markup).toContain('data-vui="contextual-hint"');
    expect(markup).not.toContain("<h2");
  });

  it("places a public section header class on the direct header before its direct body", () => {
    const markup = renderToStaticMarkup(
      <VSection
        headerClassName="config-section-header-contract"
        title="Config section"
        tooltip="Settings in this card"
        tooltipLabel="Config section details"
      >
        <div data-layout-marker="section-body">Body</div>
      </VSection>,
    );

    expect(markup).toMatch(
      /<section[^>]*><header[^>]*config-section-header-contract[^>]*>.*<\/header><div data-layout-marker="section-body">Body<\/div><\/section>/,
    );
    expect(markup).toContain('aria-label="Config section details"');
  });

  it("can hide the route-header intro so actions own the full row", () => {
    const markup = renderToStaticMarkup(
      <VRouteHeader
        hideIntro
        title="Hidden intro"
        actions={<button type="button">Workflow</button>}
      />,
    );

    expect(markup).toContain('data-vui="route-header"');
    expect(markup).toContain('data-hide-intro="true"');
    expect(markup).toContain("Workflow");
    expect(markup).not.toContain("Hidden intro");
    expect(markup).toContain("grid-cols-1");
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
        <VMetricStrip
          ariaLabel="Agent summary"
          metrics={[
            { id: "agents", label: "Agents", value: <VLoadingValue label="Loading agents" /> },
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
    expect(markup).toContain('data-vui="loading-value"');
    expect(markup).toContain('role="status"');
    expect(markup).toContain('aria-label="Loading agents"');
    expect(markup).toContain("animate-spin");
    expect(markup).toContain("motion-reduce:animate-none");
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

  it("renders the list-detail page recipe with stable slots", () => {
    const markup = renderToStaticMarkup(
      <VListDetailPage
        ariaLabel="Agents"
        eyebrow="Directory"
        title="Agent center"
        list={<nav>List</nav>}
        detail={<VEmptyState title="Select an agent" />}
      />,
    );

    expect(markup).toContain('data-vui-recipe="list-detail-page"');
    expect(markup).toContain('data-vui="workbench-page"');
    expect(markup).toContain('data-vui="route-header"');
    expect(markup).toContain('data-vui="split-workspace"');
    expect(markup).toContain("Agent center");
    expect(markup).toContain("Select an agent");
  });

  it("allows route style maps to own list-detail workspace columns", () => {
    const markup = renderToStaticMarkup(
      <VListDetailPage
        title="Custom split"
        workspaceClassName="workspace-contract-grid"
        columnsClassName=""
        list={<span>L</span>}
        detail={<span>D</span>}
      />,
    );

    expect(markup).toContain("workspace-contract-grid");
    expect(markup).toContain('data-vui="split-sidebar"');
    expect(markup).toContain('data-vui="split-main"');
  });

  it("renders the settings-form page recipe with sticky footer slot", () => {
    const markup = renderToStaticMarkup(
      <VSettingsFormPage
        ariaLabel="Model settings"
        title="Basics"
        footer={<VButton type="button">Save</VButton>}
      >
        <VFieldRow label="Name">
          <VInput aria-label="Name" defaultValue="gpt" />
        </VFieldRow>
      </VSettingsFormPage>,
    );

    expect(markup).toContain('data-vui-recipe="settings-form-page"');
    expect(markup).toContain('data-vui="settings-form-body"');
    expect(markup).toContain('data-vui="settings-form-footer"');
    expect(markup).toContain('data-vui="field-row"');
    expect(markup).toContain("Save");
  });

  it("renders the dense-ops page recipe with toolbar and empty state", () => {
    const emptyMarkup = renderToStaticMarkup(
      <VDenseOpsPage
        ariaLabel="Queue"
        title="Work queue"
        toolbar={<button type="button">Refresh</button>}
        isEmpty
        empty={{ title: "No jobs", description: "Queue is idle" }}
      />,
    );

    expect(emptyMarkup).toContain('data-vui-recipe="dense-ops-page"');
    expect(emptyMarkup).toContain('data-vui-recipe="dense-ops-toolbar"');
    expect(emptyMarkup).toContain('data-vui="toolbar"');
    expect(emptyMarkup).toContain('data-vui="empty-state"');
    expect(emptyMarkup).toContain("No jobs");

    const bareToolbarMarkup = renderToStaticMarkup(
      <VDenseOpsPage
        title="Usage"
        toolbarSlot={<div data-test-id="metric-slot">Metrics</div>}
      >
        <span>Body</span>
      </VDenseOpsPage>,
    );
    expect(bareToolbarMarkup).toContain('data-vui-recipe="dense-ops-toolbar"');
    expect(bareToolbarMarkup).toContain('data-test-id="metric-slot"');
    expect(bareToolbarMarkup).not.toContain('data-vui="toolbar"');

    const tableMarkup = renderToStaticMarkup(
      <VDenseOpsPage ariaLabel="Queue" title="Work queue">
        <VDenseTable
          ariaLabel="Jobs"
          getRowKey={(row) => row.id}
          columns={[{ id: "name", header: "Name", render: (row) => row.name }]}
          rows={[{ id: "1", name: "Job A" }]}
        />
      </VDenseOpsPage>,
    );

    expect(tableMarkup).toContain('data-vui="dense-table"');
    expect(tableMarkup).toContain("Job A");
  });
});
