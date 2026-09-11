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
  it("extracts a readable conclusion from a truncated structured summary", () => {
    const truncated = '{\n"schemaVersion": 1,\n"display": {\n"conclusion": "C01-C03 具备可证伪结构但当前整体处于 needs_more_evidence，我按会议临时职责补充独立候选 C04，并主张先锁定测量';
    expect(agentRunSummary(truncated)).toBe("C01-C03 具备可证伪结构但当前整体处于 needs_more_evidence，我按会议临时职责补充独立候选 C04，并主张先锁定测量…");
  });
  it("keeps a complete conclusion when only the trailing payload was cut", () => {
    const truncated = '{"schemaVersion": 1,\n"display": {"conclusion": "已完成来源核验",';
    expect(agentRunSummary(truncated)).toBe("已完成来源核验");
  });
  it("decodes escaped quotes and newlines in truncated conclusions", () => {
    const truncated = '{"display": {"conclusion": "第一行\\n第二行 \\"引用\\"';
    expect(agentRunSummary(truncated)).toBe("第一行\n第二行 \"引用\"…");
  });
  it("labels known statuses while retaining unknown status evidence", () => {
    expect(agentRunStatusLabel("completed", "zh")).toBe("已完成");
    expect(agentRunStatusLabel("failed", "zh")).toBe("失败");
    expect(agentRunStatusLabel("custom_error", "zh")).toBe("custom_error");
    expect(agentRunStatusLabel("completed", "en")).toBe("completed");
  });
});
