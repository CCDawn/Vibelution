import { describe, expect, it } from "vitest";
import type { AssistantConversationTurn, ConversationMessage, SessionTurnItem } from "../../api/types";
import { projectStockReport, stockResearchPrompt } from "./stockResearchModel";

const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
const finalItem = { type: "agent_message", phase: "final_answer", status: "completed", text: "## 结论\n经营质量仍需核实。" };
function turn(id: string): AssistantConversationTurn {
  return { role: "assistant", id, turnId: id, status: "completed", timestamp: "2026-10-04T12:00:00Z", turnItems: [finalItem as SessionTurnItem] };
}

describe("native research report parameters", () => {
  it("keeps parameters from the original report request after a short follow-up", () => {
    const request: ConversationMessage = { role: "user", id: "request", timestamp: "", content: stockResearchPrompt(stock, "2024FY", "2026-10-04", "financial", "brief") };
    const messages: ConversationMessage[] = [
      request,
      turn("research-turn"),
      { role: "user", id: "followup", timestamp: "", content: "再核对现金流风险" },
      turn("followup-turn"),
    ];

    expect(projectStockReport(messages)?.researchParameters).toEqual({
      stock,
      analysisDate: "2026-10-04",
      reportPeriod: "2024FY",
      scope: "financial",
      depth: "brief",
    });
  });

  it("omits invalid or unknown fields instead of guessing", () => {
    const request: ConversationMessage = {
      role: "user", id: "invalid-request", timestamp: "",
      content: stockResearchPrompt(stock, "x".repeat(41), "2099-01-01", "financial", "brief"),
    };
    expect(projectStockReport([request, turn("research-turn")])?.researchParameters).toEqual({ stock, scope: "financial", depth: "brief" });
  });

  it("does not invent finance parameters for an ordinary prompt", () => {
    const request: ConversationMessage = { role: "user", id: "ordinary", timestamp: "", content: "研究现金流和竞争风险" };
    expect(projectStockReport([request, turn("research-turn")])?.researchParameters).toBeUndefined();
  });
});
