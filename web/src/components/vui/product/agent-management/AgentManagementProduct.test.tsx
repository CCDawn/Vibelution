import React from "react";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { resolve } from "node:path";
import { RefreshCw } from "lucide-react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VibelutionHeroProvider } from "../../renderers/heroui/HeroProvider";
import {
  AgentBulkActionBar,
  AgentPageHeader,
  AgentSummaryStrip,
  AgentWorkspacePanel,
  type AgentSummaryMetric,
} from "./index";

describe("Agent Management VUI product components", () => {
  it("keeps header actions caller-owned without built-in href navigation", () => {
    const source = readFileSync(
      resolve(import.meta.dirname, "AgentPageHeader.tsx"),
      "utf8",
    );

    expect(source).not.toContain("window.location.assign");
    expect(source).not.toContain("href?: string");
  });

  it("renders a compact page header without inline explanatory prose", () => {
    const markup = renderToStaticMarkup(
      <VibelutionHeroProvider>
        <AgentPageHeader
          eyebrow="Agent Center"
          title="Agent Management"
          actions={[
            {
              id: "refresh",
              label: "Refresh",
              icon: <RefreshCw size={14} />,
              onPress: () => undefined,
            },
          ]}
        />
      </VibelutionHeroProvider>,
    );

    expect(markup).toContain("Agent Management");
    expect(markup).toContain('role="toolbar"');
    expect(markup).toContain('aria-label="Refresh"');
    expect(markup).not.toContain("<p>");
  });

  it("renders summary metrics as one dense strip", () => {
    const metrics: AgentSummaryMetric[] = [
      { id: "agents", label: "Agents", value: "11", detail: "Total agents" },
      {
        id: "issues",
        label: "Issues",
        value: "0",
        tone: "success",
        detail: "No blocking issues",
      },
    ];

    const markup = renderToStaticMarkup(
      <AgentSummaryStrip ariaLabel="Agent summary" metrics={metrics} />,
    );

    expect(markup).toContain('data-vui-product="agent-summary-strip"');
    expect(markup).toContain("Agents");
    expect(markup).toContain("11");
    expect(markup).toContain('title="Total agents"');
    expect(markup).not.toContain("overflow-hidden");
    expect(markup).not.toContain("overflow-x-auto");
    expect(markup).toContain("repeat(auto-fit,minmax(88px,1fr))");
  });

  it("renders compact status metadata accessibly when provided", () => {
    const markup = renderToStaticMarkup(
      <AgentSummaryStrip
        ariaLabel="Agent summary"
        status={{
          label: "Warning",
          title: "Needs review",
          ariaLabel: "Workspace health status: Warning. Needs review",
        }}
        metrics={[{ id: "agents", label: "Agents", value: "11" }]}
      />,
    );

    expect(markup).toContain("Warning");
    expect(markup).toContain('title="Needs review"');
    expect(markup).toContain('aria-label="Workspace health status: Warning. Needs review"');
  });

  it("renders workspace panels through the shared product surface", () => {
    const markup = renderToStaticMarkup(
      <AgentWorkspacePanel as="aside" ariaLabel="Agent filters" className="custom-layout-hook">
        <strong>Filters</strong>
      </AgentWorkspacePanel>,
    );

    expect(markup).toContain('data-vui-product="agent-workspace-panel"');
    expect(markup).toContain('data-vui="surface"');
    expect(markup).toContain('aria-label="Agent filters"');
    expect(markup).toContain("border-vui-border-subtle");
    expect(markup).toContain("bg-vui-surface-glass");
    expect(markup).toContain("custom-layout-hook");
    expect(markup).toContain("<strong>Filters</strong>");
  });

  it("renders bulk actions as a dense product toolbar without inline prose", () => {
    const markup = renderToStaticMarkup(
      <AgentBulkActionBar
        ariaLabel="Selected agents"
        summary={
          <>
            <strong>Selected</strong>
            <span>2 / 11</span>
          </>
        }
        selectionActions={<button type="button">Select visible</button>}
        promptPicker={
          <label>
            <span>Prompt</span>
            <select defaultValue="">
              <option value="">Mixed</option>
            </select>
          </label>
        }
        mutationActions={<button type="button">Apply</button>}
        destructiveActions={<button type="button">Purge</button>}
      />,
    );

    expect(markup).toContain('data-vui-product="agent-bulk-action-bar"');
    expect(markup).toContain('data-vui="agent-bulk-action-bar"');
    expect(markup).toContain('role="toolbar"');
    expect(markup).toContain("bg-vui-surface-toolbar");
    expect(markup).toContain("border-vui-border-subtle");
    expect(markup).toContain("Selected");
    expect(markup).toContain("2 / 11");
    expect(markup).not.toContain("<p>");
  });

  it("keeps the bulk toolbar single-line inside narrow workspace columns", () => {
    const markup = renderToStaticMarkup(
      <AgentBulkActionBar
        ariaLabel="Selected agents"
        summary={<span>0 / 32</span>}
        selectionActions={<button type="button">Select visible</button>}
        promptPicker={<select aria-label="Prompt" />}
        mutationActions={<button type="button">Apply prompt</button>}
        destructiveActions={<button type="button">Purge selected</button>}
      />,
    );

    expect(markup).toContain("!flex-nowrap");
    expect(markup).toContain("overflow-x-auto");
    expect(markup).toContain("[&amp;_button]:whitespace-nowrap");
    expect(markup).not.toContain("grid-cols-[auto_auto_minmax");
  });
});
