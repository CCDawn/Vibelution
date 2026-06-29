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
  AgentPageHeader,
  AgentSummaryStrip,
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
});
