// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { FinancialWorkspaceSettings, FinancialWorkspacePatch } from "../../api/financialPreferences";
import { fetchFinancialWorkspace, updateFinancialWorkspace } from "../../api/financialPreferences";
import { useFinanceWatchlist } from "./useFinanceWatchlist";

vi.mock("../../api/financialPreferences", () => ({ financialWorkspaceKey: (id: string) => ["finance", "workspace-settings", id], fetchFinancialWorkspace: vi.fn(), updateFinancialWorkspace: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const stock = { symbol: "usAAPL", ticker: "AAPL", name: "Apple", market: "NASDAQ", marketCode: "US", currency: "USD", price: 200, timestamp: "old quote" };
const identity = { symbol: stock.symbol, ticker: stock.ticker, name: stock.name, market: stock.market };
const state = new Map<string, FinancialWorkspaceSettings>();
const empty = (agentId: string): FinancialWorkspaceSettings => ({ schemaVersion: 1, agentId, revision: 0, updatedAt: "", selectedStock: null, watchlist: [], profiles: [], manualPositions: [], reviewCases: [] });
let cleanup = async () => {};
beforeEach(() => {
  state.clear();
  vi.mocked(fetchFinancialWorkspace).mockImplementation(async (id) => structuredClone(state.get(id) ?? empty(id)));
  vi.mocked(updateFinancialWorkspace).mockImplementation(async (id, expectedRevision, patch: FinancialWorkspacePatch) => {
    const current = state.get(id) ?? empty(id);
    if (current.revision !== expectedRevision) throw Object.assign(new Error("Revision conflict"), { status: 409 });
    const result = { ...current, ...patch, revision: current.revision + 1 }; state.set(id, result); return structuredClone(result);
  });
});
afterEach(async () => { await cleanup(); localStorage.clear(); vi.clearAllMocks(); });

async function renderAgent(agentId: string) {
  const node = document.createElement("div"); document.body.appendChild(node);
  const root = createRoot(node), client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  cleanup = async () => { await act(async () => root.unmount()); client.clear(); node.remove(); };
  function Consumer() {
    const preferences = useFinanceWatchlist(agentId);
    return <><button aria-label="select" onClick={() => preferences.selectStock(stock)}>select</button><button aria-label="toggle" onClick={() => preferences.toggleStock(stock)}>toggle</button><output>{preferences.watchlist.length}</output><span>{preferences.selected.ticker}</span></>;
  }
  await act(async () => { root.render(<QueryClientProvider client={client}><Consumer /></QueryClientProvider>); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  return { node, flush: async () => { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); }); } };
}

it("persists Agent-scoped identities on the server and strips live quote metadata", async () => {
  const { node, flush } = await renderAgent("first");
  await act(async () => { node.querySelector<HTMLButtonElement>("[aria-label=select]")!.click(); node.querySelector<HTMLButtonElement>("[aria-label=toggle]")!.click(); });
  await flush();
  expect(state.get("first")?.selectedStock).toEqual(identity);
  expect(state.get("first")?.watchlist).toEqual([{ ...identity, tags: [], note: "" }]);
  expect(state.get("first")?.revision).toBe(2);
  expect(JSON.stringify(state.get("first"))).not.toContain("old quote");
  expect(localStorage.getItem("vibelution.finance-stocks.v1:first")).toBeNull();
});

it("rejects a 51st stock without silently evicting saved stock notes", async () => {
  const watchlist = Array.from({ length: 50 }, (_, index) => ({ symbol: `sh${600001 + index}`, ticker: String(600001 + index), name: `股票${index}`, market: "上交所", tags: ["已记录"], note: `私有备注${index}` }));
  state.set("full", { ...empty("full"), revision: 2, watchlist });
  const { node, flush } = await renderAgent("full");
  await act(async () => node.querySelector<HTMLButtonElement>("[aria-label=toggle]")!.click());
  await flush();
  expect(state.get("full")?.watchlist).toEqual(watchlist);
  expect(state.get("full")?.revision).toBe(2);
  expect(updateFinancialWorkspace).not.toHaveBeenCalled();
  expect(node.querySelector("output")?.textContent).toBe("50");
});

it("migrates the previously selected stock even when the old watchlist is empty", async () => {
  localStorage.setItem("vibelution.finance-stocks.v1:selected-only", JSON.stringify({ selected: stock, watchlist: [] }));
  const { node, flush } = await renderAgent("selected-only");
  await flush();
  expect(state.get("selected-only")?.selectedStock).toEqual(identity);
  expect(state.get("selected-only")?.watchlist).toEqual([]);
  expect(node.querySelector("span")?.textContent).toBe("AAPL");
});

it("serializes rapid opposite toggles instead of saving the same stale intent twice", async () => {
  const { node, flush } = await renderAgent("double");
  await act(async () => { const button = node.querySelector<HTMLButtonElement>("[aria-label=toggle]")!; button.click(); button.click(); });
  await flush();
  expect(state.get("double")?.watchlist).toEqual([]);
  expect(node.querySelector("output")?.textContent).toBe("0");
});

it("migrates legacy browser data once without replacing an existing server watchlist", async () => {
  localStorage.setItem("vibelution.finance-stocks.v1:migrate", JSON.stringify({ selected: stock, watchlist: [stock] }));
  const { flush } = await renderAgent("migrate"); await flush();
  expect(state.get("migrate")?.watchlist[0]).toEqual({ ...identity, tags: [], note: "" });
  await cleanup();
  state.set("existing", { ...empty("existing"), revision: 3, watchlist: [], selectedStock: identity });
  localStorage.setItem("vibelution.finance-stocks.v1:existing", JSON.stringify({ watchlist: [stock] }));
  const other = await renderAgent("existing"); await other.flush();
  expect(state.get("existing")?.revision).toBe(3);
  expect(state.get("existing")?.watchlist).toEqual([]);
});

it("rebases a revision conflict and preserves the other page's tags", async () => {
  const { node, flush } = await renderAgent("rebase");
  state.set("rebase", { ...empty("rebase"), revision: 1, watchlist: [{ symbol: "hk00700", ticker: "00700", name: "腾讯", market: "港交所", tags: ["长期"], note: "另一页面" }] });
  await act(async () => node.querySelector<HTMLButtonElement>("[aria-label=toggle]")!.click()); await flush();
  expect(state.get("rebase")?.watchlist.map((row) => row.symbol)).toEqual(["hk00700", "usAAPL"]);
  expect(state.get("rebase")?.watchlist[0].tags).toEqual(["长期"]);
  expect(state.get("rebase")?.revision).toBe(2);
});
