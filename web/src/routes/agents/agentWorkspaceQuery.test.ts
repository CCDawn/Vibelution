import { describe, expect, it } from "vitest";

import {
  agentSummaryMetricValue,
  resolveAgentWorkspaceQueryState,
  resolveAgentWorkspaceSource,
} from "./agentWorkspaceQuery";

describe("agentWorkspaceQuery", () => {
  it("prefers full workspace only when required", () => {
    expect(
      resolveAgentWorkspaceSource({
        summary: "summary",
        full: "full",
        fullWorkspaceNeeded: true,
      }),
    ).toBe("full");
    expect(
      resolveAgentWorkspaceSource({
        summary: "summary",
        full: "full",
        fullWorkspaceNeeded: false,
      }),
    ).toBe("summary");
    expect(
      resolveAgentWorkspaceSource({
        summary: undefined,
        full: "full",
        fullWorkspaceNeeded: false,
      }),
    ).toBe("full");
  });

  it("classifies summary/full query error ownership", () => {
    expect(
      resolveAgentWorkspaceQueryState({
        hasSummary: false,
        hasFull: false,
        fullWorkspaceNeeded: true,
        summaryError: true,
        fullError: true,
      }),
    ).toEqual({
      hasWorkspace: false,
      initialError: true,
      backgroundError: false,
      errorOwner: "full",
    });

    expect(
      resolveAgentWorkspaceQueryState({
        hasSummary: true,
        hasFull: false,
        fullWorkspaceNeeded: true,
        summaryError: false,
        fullError: true,
      }),
    ).toEqual({
      hasWorkspace: true,
      initialError: false,
      backgroundError: true,
      errorOwner: "full",
    });
  });

  it("hides metrics when presentation is error-empty", () => {
    expect(agentSummaryMetricValue("error-empty", 12, "—")).toBe("—");
    expect(agentSummaryMetricValue("ready", 12, "—")).toBe(12);
    expect(agentSummaryMetricValue("ready", undefined, "—")).toBe(0);
  });
});
