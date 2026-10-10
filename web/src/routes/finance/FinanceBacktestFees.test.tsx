// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { FinanceBacktestFees } from "./FinanceBacktestFees";
import type { AIBacktestFeePolicyAudit, AIBacktestRun } from "../../api/types/financialBacktests";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it("keeps the two accounts separate and shows included fees without inventing settlement certainty", async () => {
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  const audit: AIBacktestFeePolicyAudit = { feeModel: "verified_ashare_fees_v1", startDate: "2023-08-25", endDate: "2023-08-29", symbols: ["sh600036"], commissionIncludes: ["handlingFee", "regulatoryFee"], roundingStatus: "unverified_broker_settlement", minimumGranularity: "simulated_order", sourceURLs: ["https://one.sse.com.cn/onething/gptz/", "javascript:alert(1)", "https://sse.com.cn.evil.example/"] };
  const order = { date: "2023-08-28", status: "filled", filledShares: 100, commission: 5, handlingFee: 0.34, regulatoryFee: 0.2, brokerCommission: 4.46, transferFee: 0.1, stampDuty: 0, fee: 5.1 };
  const run = { symbol: "sh600036", orders: [order, { ...order, date: "2023-08-29", status: "rejected", filledShares: 0 }], benchmarkOrders: [order] } as AIBacktestRun;
  try {
    await act(async () => root.render(<FinanceBacktestFees audit={audit} run={run} zh />));
    expect(host.textContent).toContain("佣金含规费 · 过户费另计");
    expect(host.querySelector('[role="table"]')).toBeNull();
    await act(async () => host.querySelector<HTMLButtonElement>("button")!.click());
    expect(host.textContent).toContain("AI策略"); expect(host.textContent).toContain("持有基准");
    expect(host.textContent).toContain("券商实际结算未核实");
    expect(host.querySelector('[aria-label="AI回测费用审计"]')?.textContent).not.toContain("2023-08-29");
    const links = host.querySelectorAll("a"); expect(links).toHaveLength(1);
    expect(links[0].getAttribute("rel")).toBe("noreferrer");
    expect(links[0].href).toBe(audit.sourceURLs[0]);
  } finally { await act(async () => root.unmount()); host.remove(); }
});
