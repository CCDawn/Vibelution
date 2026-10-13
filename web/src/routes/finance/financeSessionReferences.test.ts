import { afterEach, describe, expect, it } from "vitest";
import type { SessionSummary } from "../../api/types";
import { resetSessionDeleteTombstonesForTests, markSessionDeleteTombstone } from "../sessionDeleteTombstone";
import { financeSessionReferences } from "./financeSessionReferences";

const row = (id: string, overrides: Partial<SessionSummary> = {}) => ({
  id, agentId: "finance", title: `研究 ${id}`, taskSummary: "已核验摘要", updatedAt: "2026-10-13T00:00:00Z", ...overrides,
} as SessionSummary);

afterEach(() => resetSessionDeleteTombstonesForTests());

describe("finance scoped session references", () => {
  it("excludes current, foreign, archived, hidden and deleted sessions and deduplicates pages", () => {
    markSessionDeleteTombstone("deleted", { confirmed: true });
    const options = financeSessionReferences([
      row("old"), row("current"), row("foreign", { agentId: "other" }),
      row("archived", { archiveState: { status: "archived" } as SessionSummary["archiveState"] }),
      row("hidden", { hiddenFromIndex: true }), row("deleted"), row("old"),
    ], "finance", "current", "验收助手");
    expect(options).toHaveLength(1);
    expect(options[0]).toMatchObject({ id: "old", title: "研究 old", meta: "2026-10-13", reference: {
      referenceId: "session:old", kind: "session", sessionId: "old", agentId: "finance",
      agentDisplayName: "验收助手", summary: "已核验摘要",
    } });
  });
  it("returns no candidates without an assistant identity", () => {
    expect(financeSessionReferences([row("empty", { agentId: "" })], "", "", "")).toEqual([]);
  });
});
