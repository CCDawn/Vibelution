import { describe, expect, it } from "vitest";
import { agentRunSummary, agentRunStatusLabel } from "./agentRunPresentation";

describe("agent run display projection", () => {
  it("uses the meeting display conclusion without protocol fields", () => {
    expect(agentRunSummary(JSON.stringify({
      schemaVersion: 1,
      display: { conclusion: "已完成来源核验", sections: [] },
      privateContext: "must not be a summary",
    }))).toBe("已完成来源核验");
  });
  it("preserves prose and unrecognized or incomplete content", () => {
    for (const text of ["正常摘要", '{"schemaVersion":1', '{"result":3}', '{"schemaVersion":1,"display":{"conclusion":""}}']) {
      expect(agentRunSummary(text)).toBe(text);
    }
    expect(agentRunSummary(undefined)).toBe("");
  });
  it("labels known statuses while retaining unknown status evidence", () => {
    expect(agentRunStatusLabel("completed", "zh")).toBe("已完成");
    expect(agentRunStatusLabel("failed", "zh")).toBe("失败");
    expect(agentRunStatusLabel("custom_error", "zh")).toBe("custom_error");
    expect(agentRunStatusLabel("completed", "en")).toBe("completed");
  });
});
