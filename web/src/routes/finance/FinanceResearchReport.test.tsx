// @vitest-environment happy-dom

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { FinanceResearchReport } from "./FinanceResearchReport";
import { projectStockReport, stockResearchPrompt } from "./stockResearchModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
const request = stockResearchPrompt(stock, "2024FY", "2026-10-04", "financial", "brief");
const report = projectStockReport([
  { role: "user", id: "request", timestamp: "", content: request },
  {
    role: "assistant", id: "assistant", turnId: "research-turn", status: "completed", timestamp: "2026-10-04T12:00:00Z",
    turnItems: [{ type: "agent_message", phase: "final_answer", status: "completed", text: "## 结论\n经营质量仍需核实。" }],
  },
] as never)!;

describe("FinanceResearchReport research metadata", () => {
  let root: Root | undefined;
  afterEach(() => { act(() => root?.unmount()); root = undefined; document.body.replaceChildren(); });

  async function render(props: Partial<React.ComponentProps<typeof FinanceResearchReport>> = {}) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root?.render(<FinanceResearchReport report={report} assistantAgentId="agent-1" sessionId="session-1" zh onCitation={() => {}} onResearch={() => {}} {...props} />));
    return container;
  }

  it("shows the original report's known stock and research settings in one metadata row", async () => {
    const container = await render();
    const metadata = container.querySelector<HTMLElement>("[data-finance-research-metadata]");
    expect(metadata?.textContent).toContain("标的：贵州茅台 600519");
    expect(metadata?.textContent).toContain("分析日期：2026-10-04");
    expect(metadata?.textContent).toContain("报告期：2024FY");
    expect(metadata?.textContent).toContain("范围：财报分析");
    expect(metadata?.textContent).toContain("深度：快速");
    expect(metadata?.textContent).not.toContain("模型");
    expect(metadata?.querySelectorAll("span")).toHaveLength(5);
  });

  it("keeps the metadata visible in the compact brief and hides the row for legacy reports", async () => {
    const brief = await render({ summaryOnly: true });
    expect(brief.querySelector("[data-finance-research-metadata]")?.textContent).toContain("报告期：2024FY");
    act(() => root?.unmount());
    root = undefined;
    document.body.replaceChildren();

    const legacy = await render({ report: { ...report, researchParameters: undefined } });
    expect(legacy.querySelector("[data-finance-research-metadata]")).toBeNull();
  });
});
