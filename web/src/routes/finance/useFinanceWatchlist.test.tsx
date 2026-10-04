// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it } from "vitest";
import { useFinanceWatchlist } from "./useFinanceWatchlist";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所", price: 1258.62, timestamp: "old quote" };
let cleanup = async () => {};
afterEach(async () => { await cleanup(); localStorage.clear(); });

it("persists only Agent-scoped identities even when the selection comes from a quote", async () => {
  const node = document.createElement("div"); document.body.appendChild(node);
  const root = createRoot(node);
  cleanup = async () => { await act(async () => root.unmount()); node.remove(); };
  function Consumer({ agentId }: { agentId: string }) {
    const preferences = useFinanceWatchlist(agentId);
    return <button onClick={() => { preferences.selectStock(stock); preferences.toggleStock(stock); }}>{preferences.watchlist.length}</button>;
  }
  await act(async () => root.render(<Consumer key="first" agentId="first" />));
  await act(async () => node.querySelector("button")!.click());
  const saved = JSON.parse(localStorage.getItem("vibelution.finance-stocks.v1:first")!);
  const identity = { symbol: stock.symbol, ticker: stock.ticker, name: stock.name, market: stock.market };
  expect(saved).toEqual({ selected: identity, watchlist: [identity] });
  await act(async () => root.render(<Consumer key="another" agentId="another" />));
  expect(node.querySelector("button")?.textContent).toBe("0");
  expect(JSON.parse(localStorage.getItem("vibelution.finance-stocks.v1:another")!).watchlist).toEqual([]);
  expect(JSON.parse(localStorage.getItem("vibelution.finance-stocks.v1:first")!).watchlist).toEqual([identity]);
});
