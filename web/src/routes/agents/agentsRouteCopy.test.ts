import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspaceAgent } from "../../api/types";
import { agentConfigPanes, agentsRouteCopy } from "./agentsRouteCopy";

describe("agentsRouteCopy", () => {
  it("returns bilingual workbench labels for zh and en", () => {
    const zh = agentsRouteCopy("zh");
    const en = agentsRouteCopy("en");
    expect(zh.title).toBe("Agent 中心");
    expect(en.title).toMatch(/Agent/i);
    expect(zh.bulkArchive).toBeTruthy();
    expect(en.bulkArchive).toBeTruthy();
    expect(zh.filterSections.status).toBe("状态");
    expect(en.filterSections.status.toLowerCase()).toContain("status");
    expect(zh.overviewPane).toBeTruthy();
    expect(en.activityPane).toBeTruthy();
  });

  it("builds pane badges from actionable agent signals only", () => {
    const copy = agentsRouteCopy("zh");
    const panes = agentConfigPanes(copy, {
      health: [{ severity: "warning" }, { severity: "blocking" }],
      effectiveConfiguration: { fields: [{ status: "missing" }] },
      references: [{ kind: "team" }, { kind: "session" }],
      agentInboxPendingCount: 2,
      groupContextEvents: [{}],
    } as AgentConfigWorkspaceAgent);
    expect(panes.map((pane) => pane.id)).toEqual([
      "overview",
      "effective",
      "relations",
      "config",
      "changes",
      "activity",
    ]);
    expect(panes.find((pane) => pane.id === "config")?.count).toBe(2);
    expect(panes.find((pane) => pane.id === "effective")?.count).toBe(1);
    expect(panes.find((pane) => pane.id === "relations")?.count).toBe(1);
    expect(panes.find((pane) => pane.id === "activity")?.count).toBe(3);
    expect(panes.find((pane) => pane.id === "overview")?.count).toBe(0);
  });
});
