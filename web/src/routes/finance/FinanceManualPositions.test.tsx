// @vitest-environment happy-dom

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FinancialManualPosition } from "../../api/financialPreferences";
import { FinanceManualPositions } from "./FinanceManualPositions";

const api = vi.hoisted(() => ({ quotes: vi.fn() }));
vi.mock("../../api/financialResearch", () => ({
  fetchFinancialMarketQuotes: api.quotes,
  financialResearchKeys: { quotes: (symbols: readonly string[]) => ["quotes", [...symbols].sort()] },
}));
vi.mock("../../api/financialMarket", () => ({
  financialMarketKeys: { search: (query: string, market: string) => ["stock-search", query, market] },
  searchFinancialStocks: vi.fn(),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const stock = { symbol: "usAAPL", ticker: "AAPL", name: "Apple", market: "NASDAQ" };
const position: FinancialManualPosition = { id: "position-1", stock, quantity: 5, costPrice: 180, currency: "USD", note: "long-term" };
let root: Root | null = null;
let container: HTMLDivElement;
let client: QueryClient;

async function settle() {
  await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
}

function button(label: string): HTMLButtonElement {
  const found = [...document.querySelectorAll("button")].find((item) => item.textContent?.includes(label));
  if (!found) throw new Error(`Button not found: ${label}`);
  return found;
}

function setInputValue(input: HTMLInputElement, next: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, next);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

beforeEach(() => {
  api.quotes.mockReset().mockResolvedValue({ source: "test", fetchedAt: "2026-10-06T12:00:00Z", items: [] });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  container.remove();
  client.clear();
});

describe("FinanceManualPositions conflict behavior", () => {
  it("keeps the edit dialog and entered values visible when a stale concurrent edit is rejected", async () => {
    const onSave = vi.fn(async (change: (current: FinancialManualPosition[]) => FinancialManualPosition[]) =>
      change([{ ...position, note: "changed in another window" }])
    );
    await act(async () => root?.render(<QueryClientProvider client={client}><FinanceManualPositions
      positions={[position]}
      stock={stock}
      onSave={onSave}
      onSelectStock={() => {}}
      onResearchPrompt={() => {}}
      pending={false}
      researchDisabled={false}
      zh
    /></QueryClientProvider>));
    await settle();

    await act(async () => button("编辑").click());
    const quantity = document.querySelector<HTMLInputElement>('input[aria-label="持仓股数"]');
    expect(quantity?.value).toBe("5");
    await act(async () => setInputValue(quantity!, "7"));
    await act(async () => button("保存持仓").click());
    await settle();

    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(document.querySelector<HTMLInputElement>('input[aria-label="持仓股数"]')?.value).toBe("7");
    expect(document.body.textContent).toContain("这条持仓已在其他窗口修改");
    expect(onSave).toHaveBeenCalledOnce();
  });

  it("keeps the edit dialog when the latest revision has deleted the holding", async () => {
    const onSave = vi.fn(async (change: (current: FinancialManualPosition[]) => FinancialManualPosition[]) => change([]));
    await act(async () => root?.render(<QueryClientProvider client={client}><FinanceManualPositions
      positions={[position]}
      stock={stock}
      onSave={onSave}
      onSelectStock={() => {}}
      onResearchPrompt={() => {}}
      pending={false}
      researchDisabled={false}
      zh
    /></QueryClientProvider>));
    await settle();
    await act(async () => button("编辑").click());
    await act(async () => button("保存持仓").click());
    await settle();

    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(document.body.textContent).toContain("这条持仓已在其他窗口删除");
  });
});
