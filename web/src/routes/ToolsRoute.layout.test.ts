import { describe, expect, it } from "vitest";

import routeSource from "./ToolsRoute.tsx?raw";

describe("ToolsRoute layout contract", () => {
  it("keeps manual generated-tool creation out of the page", () => {
    expect(routeSource).not.toContain('fetchJson<ToolRegistryItem>("/api/tools/generated"');
    expect(routeSource).not.toContain("toolsAddGenerated");
    expect(routeSource).not.toContain("createMutation");
  });

  it("surfaces tool readiness before raw schema details", () => {
    const readinessIndex = routeSource.indexOf("styles.readinessPanel");
    const schemaIndex = routeSource.indexOf("styles.schemaDisclosure");

    expect(readinessIndex).toBeGreaterThan(0);
    expect(schemaIndex).toBeGreaterThan(readinessIndex);
    expect(routeSource).toContain("toolReadinessCards(activeTool, t)");
    expect(routeSource).toContain("readinessTone");
  });

  it("summarizes filter counts and test outcomes as scan-friendly cards", () => {
    expect(routeSource).toContain("toolFilterCounts");
    expect(routeSource).toContain("filterCounts");
    expect(routeSource).toContain("styles.resultSummaryGrid");
    expect(routeSource).toContain("testResultSummaryCards(testResult, t)");
    expect(routeSource).toContain("styles.resultCard");
  });

  it("keeps test controls and result panels in normal document flow", () => {
    expect(routeSource).toContain("styles.policyPanel");
    expect(routeSource).toContain("styles.detailActions");
    expect(routeSource.indexOf("styles.detailActions")).toBeGreaterThan(routeSource.indexOf("styles.policyPanel"));
    expect(routeSource.indexOf("styles.testPanel")).toBeGreaterThan(routeSource.indexOf("styles.detailActions"));
  });

  it("keeps raw args schema folded behind a disclosure", () => {
    expect(routeSource).toContain("<details className={styles.schemaDisclosure}>");
    expect(routeSource).toContain("<summary>");
    expect(routeSource).toContain("toolsShowSchema");
  });
});
