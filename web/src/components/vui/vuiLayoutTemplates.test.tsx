import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  VBoardWorkbenchPage,
  VButton,
  VCanvasWorkbenchPage,
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
  VSessionWorkbenchPage,
  VTrackWorkbenchPage,
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

  it("can hide the route-header intro and shrink-wrap around actions", () => {
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
    // Content-sized chrome only — not a full-width empty grid shell.
    expect(markup).toContain("w-fit");
    expect(markup).toContain("justify-self-end");
    expect(markup).not.toContain("grid-cols-1");
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
        <VStateSurface fill tone="loading" title="Loading research overview">
          Occupies the board region instead of a one-line label.
        </VStateSurface>
        <VStateSurface
          density="compact"
          tone="error"
          title="Autonomous loop did not complete"
          facts={[
            { key: "phase", label: "Phase", value: "observing_interrupted" },
            { key: "candidate", label: "Candidate", value: "Not created" },
          ]}
        >
          Interrupted before the process restarted.
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
    const loadingSurfaceMarkup = renderToStaticMarkup(
      <VStateSurface fill tone="loading" title="Loading research overview" />,
    );

    expect(markup).toContain('data-vui="workbench-page"');
    expect(markup).toContain('data-vui="route-header"');
    expect(markup).toContain("rounded-[var(--radius-panel)]");
    expect(markup).toContain("text-[var(--font-size-title)]");
    expect(markup).toContain("text-[var(--font-size-caption)]");
    expect(markup).toContain("text-[var(--font-size-micro)]");
    expect(markup).toContain('data-vui="status-strip"');
    expect(markup).toContain('data-vui="status-strip-item"');
    expect(markup).toContain('data-tone="neutral"');
    expect(markup).toContain('data-vui="loading-value"');
    expect(markup).toContain('role="status"');
    expect(markup).toContain('aria-label="Loading agents"');
    expect(markup).toContain("animate-spin");
    expect(markup).toContain("motion-reduce:animate-none");
    expect(markup).toContain('data-vui="state-surface"');
    expect(markup).toContain('data-tone="loading"');
    expect(markup).toContain('data-fill="true"');
    expect(loadingSurfaceMarkup).toContain("bg-[var(--vui-surface-panel)]");
    expect(loadingSurfaceMarkup).not.toContain("vui-control-muted");
    expect(markup).toContain("Loading research overview");
    expect(markup).toContain('data-density="compact"');
    expect(markup).toContain("observing_interrupted");
    expect(markup).toContain("max-w-[min(100%,18rem)]");
    expect(markup).toContain("Team detail API");
    expect(markup).toContain("animate-pulse");
    expect(markup).toContain('data-vui="split-workspace"');
    expect(markup).toContain("--vui-workspace-sidebar,16rem");
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
        toolbar={<div>Tabs</div>}
        footer={<VButton type="button">Save</VButton>}
      >
        <VFieldRow label="Name">
          <VInput aria-label="Name" defaultValue="gpt" />
        </VFieldRow>
      </VSettingsFormPage>,
    );

    expect(markup).toContain('data-vui-recipe="settings-form-page"');
    expect(markup).toContain('data-vui="settings-form-header"');
    expect(markup).toContain('data-vui="settings-form-toolbar"');
    expect(markup).toContain("Tabs");
    expect(markup).toContain('data-vui="settings-form-body"');
    expect(markup).toContain('data-vui="settings-form-footer"');
    expect(markup).toContain('data-vui="field-row"');
    expect(markup).toContain("Save");
  });

  it("renders board and canvas workbench recipes with coordinated fill slots", () => {
    const boardMarkup = renderToStaticMarkup(
      <VBoardWorkbenchPage
        ariaLabel="Teams board"
        title="Team workbench"
        hideHeader
        domainRecipe="teams-organization-workbench"
        layoutId="teams"
        rail={<nav>Teams</nav>}
        toolbar={<span>Board mode</span>}
        board={<div>Kanban</div>}
      />,
    );
    expect(boardMarkup).toContain('data-vui-recipe="board-workbench-page"');
    expect(boardMarkup).toContain('data-vui-domain-recipe="teams-organization-workbench"');
    expect(boardMarkup).toContain('data-fill="true"');
    expect(boardMarkup).toContain('data-vui="board-workbench-rail"');
    expect(boardMarkup).toContain('data-vui="board-workbench-board"');
    expect(boardMarkup).toContain("Kanban");
    // hideHeader → stack fill (flex column), not header-body grid auto row.
    expect(boardMarkup).toContain('data-fill-layout="stack"');
    expect(boardMarkup).toContain("flex h-full min-h-0");

    const canvasMarkup = renderToStaticMarkup(
      <VCanvasWorkbenchPage
        ariaLabel="Org canvas"
        title="Canvas"
        hideHeader
        toolbar={<div>Canvas tools</div>}
        rail={<nav>Layers</nav>}
        canvas={<div>Graph</div>}
        inspector={<div>Node</div>}
      />,
    );
    expect(canvasMarkup).toContain('data-vui-recipe="canvas-workbench-page"');
    expect(canvasMarkup).toContain('data-vui="canvas-workbench-canvas"');
    expect(canvasMarkup).toContain('data-vui="canvas-workbench-inspector"');
    expect(canvasMarkup).toContain("Graph");
    expect(canvasMarkup).toContain("Node");
    expect(canvasMarkup).toContain('data-fill-layout="stack"');
    expect(canvasMarkup).toContain('data-vui="canvas-workbench-toolbar"');
    expect(canvasMarkup).toContain("relative z-20 shrink-0 overflow-hidden");
    expect(canvasMarkup).toContain("!h-auto");
    expect(canvasMarkup).toContain("Canvas tools");
  });

  it("fill workbench strips route grid geometry that would collapse hideHeader body", () => {
    const markup = renderToStaticMarkup(
      <VWorkbenchPage
        fill
        fillLayout="stack"
        className="route grid h-full grid-rows-[auto_minmax(0,1fr)] content-stretch overflow-hidden bg-red-500"
        ariaLabel="fill-guard"
      >
        <div>body-only</div>
      </VWorkbenchPage>,
    );
    expect(markup).toContain('data-fill-layout="stack"');
    expect(markup).toContain("flex h-full min-h-0");
    expect(markup).toContain("bg-red-500");
    // Conflicting display/track utilities must not remain (cn cannot merge them).
    expect(markup).not.toMatch(/class="[^"]*\bgrid\b/);
    expect(markup).not.toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(markup).not.toContain("content-stretch");
    expect(markup).toContain("body-only");
  });

  it("renders the session workbench page recipe with dual-pane slots", () => {
    const markup = renderToStaticMarkup(
      <VSessionWorkbenchPage
        ariaLabel="Chat session"
        domainRecipe="chat-session-workbench"
        layoutId="chat"
        hostAsRoot
        className="chat-grid"
        overlay={<div>Backdrop</div>}
        statusRail={<aside>Status</aside>}
        session={<main>Conversation</main>}
        indexRail={<nav>Index</nav>}
        leftResizeHandle={<div>L</div>}
        rightResizeHandle={<div>R</div>}
      >
        <dialog>Modal</dialog>
      </VSessionWorkbenchPage>,
    );
    expect(markup).toContain('data-vui-recipe="session-workbench-page"');
    expect(markup).toContain('data-vui-domain-recipe="chat-session-workbench"');
    expect(markup).toContain('data-vui-layout-id="chat"');
    expect(markup).toContain("chat-grid");
    expect(markup).toContain("Backdrop");
    expect(markup).toContain("Status");
    expect(markup).toContain("Conversation");
    expect(markup).toContain("Index");
    expect(markup).toContain("Modal");
  });

  it("renders the track workbench page recipe with optional header and body fill", () => {
    const withHeader = renderToStaticMarkup(
      <VTrackWorkbenchPage
        ariaLabel="Evolution"
        domainRecipe="evolution-multi-rail"
        header={{
          title: "Supervised",
          actions: <button type="button">Track A</button>,
        }}
      >
        <div>Multi-rail body</div>
      </VTrackWorkbenchPage>,
    );
    expect(withHeader).toContain('data-vui-recipe="track-workbench-page"');
    expect(withHeader).toContain('data-vui-domain-recipe="evolution-multi-rail"');
    expect(withHeader).toContain('data-fill="true"');
    expect(withHeader).toContain('data-vui="route-header"');
    expect(withHeader).toContain('data-vui="track-workbench-body"');
    expect(withHeader).toContain("Multi-rail body");
    expect(withHeader).toContain("Track A");

    const bodyOnly = renderToStaticMarkup(
      <VTrackWorkbenchPage ariaLabel="Self track" header={null}>
        <div>Self workspace</div>
      </VTrackWorkbenchPage>,
    );
    expect(bodyOnly).toContain('data-vui="track-workbench-body"');
    expect(bodyOnly).toContain("Self workspace");
    expect(bodyOnly).not.toContain('data-vui="route-header"');
    expect(bodyOnly).toContain("!grid-rows-[minmax(0,1fr)]");
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
    expect(emptyMarkup).toContain('data-fill="true"');
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
    expect(bareToolbarMarkup).toContain('data-vui="dense-ops-chrome"');
    expect(bareToolbarMarkup).toContain('data-vui="dense-ops-body"');
    expect(bareToolbarMarkup.indexOf('data-vui="dense-ops-chrome"')).toBeLessThan(
      bareToolbarMarkup.indexOf('data-vui="dense-ops-body"'),
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

    const headerlessMarkup = renderToStaticMarkup(
      <VDenseOpsPage ariaLabel="Launcher" hideHeader>
        <span>Instances</span>
      </VDenseOpsPage>,
    );
    expect(headerlessMarkup).toContain('data-vui-recipe="dense-ops-page"');
    expect(headerlessMarkup).toContain("Instances");
    expect(headerlessMarkup).not.toContain('data-vui="route-header"');
  });

  it("supports reusable start-aligned empty states without route-owned markup", () => {
    const markup = renderToStaticMarkup(
      <VEmptyState
        align="start"
        title="No experiment design"
        actions={<VButton>Open design</VButton>}
      >
        The current projection has no frozen design details.
      </VEmptyState>,
    );

    expect(markup).toContain('data-vui="empty-state"');
    expect(markup).toContain('data-align="start"');
    expect(markup).toContain("justify-items-start");
    expect(markup).toContain("text-left");
    expect(markup).toContain("No experiment design");
    expect(markup).toContain("Open design");
  });
});
